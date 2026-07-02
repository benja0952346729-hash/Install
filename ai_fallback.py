"""
ai_fallback.py
==============
Booking parse fallback — is_clear_pattern=False ሲሆን ብቻ ይጠራል።
Groq rotation ከ handlers.py ይጠቀማል። (ነባር — ምንም አልተነካም)

+ Context-aware Q&A fallback — Jina confidence score ዝቅ ሲል (unknown
  ወይም score < JINA_MIN_SCORE) ይጠራል። Conversation memory (last
  intent/answer) + game data slice ተጠቅሞ follow-up ጥያቄዎችን
  (ለምሳሌ "ማን አሸነፈ?" → "በዚ ዙር ነው?") በትክክል በአማርኛ ይመልሳል።

  MODEL: qwen/qwen3-next-80b-a3b-instruct (ነባሪ) — NVIDIA free catalog
  ላይ hosted endpoint ያለው Qwen ብቻ 5 ናቸው፦ qwen3-next-80b-a3b-instruct,
  qwen3-next-80b-a3b-thinking, qwen3-235b-a22b, qwen3.5-397b-a17b,
  qwen3-coder-480b-a35b-instruct። ትንንሾቹ dense ሞዴሎች (0.6B-32B, ለምሳሌ
  qwen3-8b) hosted API ላይ የሉም (self-host ብቻ) — ስለዚህ ከተላኩ 404
  ይመልሳሉ። ከላይ ከተዘረዘሩት 5 hosted models ውጪ ማንኛውም ID ቢሞከር 404
  ይሆናል — ይህን ለመለየት ግልጽ log ታክሏል (ከታች ይመልከቱ)።

  qwen3-next-80b-a3b-instruct MoE ነው (80B total, 3.9B active parameters
  ብቻ) እና ኦፊሴላዊ model card መሰረት instruct-only mode ነው፣ <think>
  blocks ጨርሶ አያመነጭም። ስለዚህ ቀደም ሲል የነበረው መዘግየት thinking overflow
  ላይሆን ይችላል — ይልቁን rate-limit queue wait ወይም ራሱ network/generation
  time ሊሆን ይችላል። ኮዱ አሁን wait_elapsed (queue wait) እና call_elapsed
  (እውነተኛ generation time) ለብቻቸው ይመዘግባል፣ ስለዚህ ትክክለኛው ምንጭ ከ log
  በትክክል ይታወቃል።

  ሞዴል ሳይቀየር መሞከር ከፈለጉ NVIDIA_TEXT_MODEL env var ይጠቀሙ (ኮድ redeploy
  ሳያስፈልግ)። ወደ thinking-capable ሞዴል (ለምሳሌ qwen3-next-80b-a3b-thinking
  ወይም qwen3-235b-a22b) ከቀየሩ NVIDIA_TEXT_ENABLE_THINKING=false ያድርጉ
  እንዳይዘገይ።

Setup (Railway / .env):
    NVIDIA_TEXT_API_KEYS=key1,key2,key3
    (handlers.py ውስጥ ላለው NVIDIA_API_KEYS የተለዩ keys — ገለልተኛ pool)
    NVIDIA_TEXT_MODEL=qwen/qwen3-next-80b-a3b-instruct   # optional override
    NVIDIA_TEXT_ENABLE_THINKING=false   # thinking-capable ሞዴል ከተጠቀሙ ብቻ ይመልከቱ
"""

import os
import re
import json
import time
import logging
import asyncio
from collections import defaultdict, deque

from openai import OpenAI

from handlers import _call_groq_with_rotation  # ነባር — booking parse ብቻ ይጠቀማል

logger = logging.getLogger(__name__)


# ================================================================
# EXISTING — BOOKING PARSE FALLBACK (ምንም አልተነካም)
# ================================================================

async def ai_parse_booking(text: str, settings: dict) -> dict:
    """
    is_clear_pattern=False ሲሆን ብቻ ይጠራል።
    booking ነው ወይ + numbers ያወጣ።
    """
    total = settings.get("total_numbers", 100)
    price_full = settings.get("price_full", 0)
    price_half = settings.get("price_half", 0)

    prompt = f"""You are an Ethiopian lottery booking parser.
Game has numbers 1-{total}.
Full price: {price_full} ETB, Half price: {price_half} ETB.

User sends messages in Amharic, English, or mixed.
Booking message contains: number(s) + optional name + booking intent (yaz, ፃፍ, ያዝ, መዝግብ, etc)

Examples of booking:
- "96 ሳልሞን እያለ ብልህ yaz" → booking, num=96, name="ሳልሞን"
- "05 አበበ ፃፍልኝ" → booking, num=5, name="አበበ"
- "10 yaz" → booking, num=10, name=null
- "11 21 31 ያዝ" → booking, 3 numbers

NOT booking:
- "96 ለምን ብልህ ትላለህ" → not booking
- "ሰላም እንደምን ነህ" → not booking
- "ውጤት ምን ነው" → not booking

Respond ONLY in this exact JSON format, no extra text:
{{"is_booking": true or false, "numbers": [{{"num": <int>, "name": "<string or null>", "is_half": false}}]}}

If not booking:
{{"is_booking": false, "numbers": []}}"""

    try:
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ]
        result = await _call_groq_with_rotation(messages, max_tokens=150)
        result = re.sub(r"^```json\s*", "", result)
        result = re.sub(r"^```\s*", "", result)
        result = re.sub(r"\s*```$", "", result)
        parsed = json.loads(result.strip())
        logger.info(f"[AI Booking] '{text[:40]}' → is_booking={parsed.get('is_booking')} numbers={parsed.get('numbers')}")
        return parsed
    except Exception as e:
        logger.warning(f"[AI Booking] Error: {e}")
        return {"is_booking": False, "numbers": []}


# ================================================================
# NVIDIA TEXT KEY ROTATION (Qwen3-8B — context Q&A fallback)
# ================================================================
# ሙሉ ለብቻው pool ነው — handlers.py ውስጥ ካለው vision NVIDIA rotation ጋር
# ምንም አይጋራም (የተለየ client list, index, lock, rate-limit window)።
# handlers.py ውስጥ ምንም ኮድ አልተነካም/አልተቀየረም።

NVIDIA_TEXT_API_KEYS = [
    k.strip() for k in os.environ.get("NVIDIA_TEXT_API_KEYS", "").split(",") if k.strip()
]

_HOSTED_QWEN_MODELS = {
    "qwen/qwen3-next-80b-a3b-instruct",
    "qwen/qwen3-next-80b-a3b-thinking",
    "qwen/qwen3-235b-a22b",
    "qwen/qwen3.5-397b-a17b",
    "qwen/qwen3-coder-480b-a35b-instruct",
}


def _read_model() -> str:
    model = os.environ.get("NVIDIA_TEXT_MODEL", "qwen/qwen3-next-80b-a3b-instruct").strip()
    if model not in _HOSTED_QWEN_MODELS and model.startswith("qwen/"):
        logger.warning(
            f"[NVIDIA Text] ⚠️ '{model}' hosted Qwen models ዝርዝር ውስጥ አልተገኘም "
            f"(hosted የሆኑት፦ {sorted(_HOSTED_QWEN_MODELS)}) — 404 ሊመልስ ይችላል። "
            f"dense ትንንሽ Qwen3 (8B/14B/32B) NVIDIA free API ላይ hosted አይደሉም (self-host ብቻ)።"
        )
    return model


NVIDIA_TEXT_MODEL = _read_model()  # module load ላይ log ለማሳየት


def _read_enable_thinking_raw() -> str | None:
    val = os.environ.get("NVIDIA_TEXT_ENABLE_THINKING")
    return val.strip().lower() if val is not None else None


def _build_extra_body() -> dict:
    """
    ሞዴሉ thinking-capable ካልሆነ (ለምሳሌ qwen3-next-80b-a3b-instruct)
    extra_body ባዶ ሆኖ ቢቀር ችግር የለውም። env var ካልተቀመጠ ምንም
    chat_template_kwargs አንልክም (ላልታወቀ ሞዴል ደህንነቱ የተጠበቀ ነባሪ)።
    """
    raw = _read_enable_thinking_raw()
    if raw is None:
        return {}
    return {"chat_template_kwargs": {"enable_thinking": raw == "true"}}


def _is_thinking_enabled() -> bool:
    return _read_enable_thinking_raw() == "true"


NVIDIA_TEXT_REQUEST_TIMEOUT = 20  # ሰከንድ — 8B ትንሽ ሞዴል ስለሆነ ከ80B (45s) ዝቅ ብሏል

_nvidia_text_index = 0
_nvidia_text_clients = [
    OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=key,
        timeout=NVIDIA_TEXT_REQUEST_TIMEOUT,
        max_retries=0,  # rotation ራሱ retry ስለሚያደርግ SDK-level retry አያስፈልግም (ድግግሞሽ ጊዜ እንዳይጨምር)
    ) for key in NVIDIA_TEXT_API_KEYS
] if NVIDIA_TEXT_API_KEYS else []

NVIDIA_TEXT_RPM_LIMIT = 38
NVIDIA_TEXT_WINDOW_SECONDS = 60
NVIDIA_TEXT_MAX_WAIT_SECONDS = 20  # ከ60 ወደ20 — ተጠቃሚ ብዙ አይጠብቅም፣ ፈጥኖ fail ያደርጋል
NVIDIA_TEXT_HEALTH_RECHECK_INTERVAL = 7 * 60

_nvidia_text_lock = asyncio.Lock()
_nvidia_text_call_times = defaultdict(deque)
_nvidia_text_blocked_until = {}
_nvidia_text_health_task_started = False

_THINK_BLOCK_RE = re.compile(r"<think>(.*?)</think>\s*", re.DOTALL | re.IGNORECASE)
_OPEN_THINK_ONLY_RE = re.compile(r"<think>(.*)$", re.DOTALL | re.IGNORECASE)  # think block ያላለቀ ከሆነ


def _strip_think_block(text: str) -> tuple[str, dict]:
    """
    <think>...</think> ን ያስወግዳል እና diagnostics ይመልሳል፦
    - think_chars: think block ውስጥ ስንት ቁምፊ እንደጠፋ
    - think_closed: </think> ደርሶ ነበር ወይስ max_tokens አልቆ ባልተጨረሰ think
      ውስጥ ተቆርጧል (ይህ ነው "ችግሩ think እያረገ ይቆያል/ባዶ ይመልሳል" ለሚለው ዋናው ምክንያት)
    """
    if not text:
        return text, {"had_think": False, "think_chars": 0, "think_closed": True}

    closed_matches = list(_THINK_BLOCK_RE.finditer(text))
    if closed_matches:
        think_chars = sum(len(m.group(1)) for m in closed_matches)
        cleaned = _THINK_BLOCK_RE.sub("", text).strip()
        return cleaned, {"had_think": True, "think_chars": think_chars, "think_closed": True}

    # <think> ተጀምሮ </think> ያልደረሰ ከሆነ — max_tokens ሙሉ በሙሉ በ thinking
    # ብቻ አልቋል ማለት ነው። ይህ ነው ባዶ/ያልተሟላ መልስ ዋናው ምንጭ።
    open_match = _OPEN_THINK_ONLY_RE.search(text)
    if open_match:
        return "", {"had_think": True, "think_chars": len(open_match.group(1)), "think_closed": False}

    return text.strip(), {"had_think": False, "think_chars": 0, "think_closed": True}


def _nvidia_text_prune_window(idx: int, now: float):
    q = _nvidia_text_call_times[idx]
    while q and now - q[0] > NVIDIA_TEXT_WINDOW_SECONDS:
        q.popleft()


async def _get_available_nvidia_text_client(max_wait: int = NVIDIA_TEXT_MAX_WAIT_SECONDS):
    global _nvidia_text_index
    if not _nvidia_text_clients:
        raise RuntimeError("NVIDIA_TEXT_API_KEYS ያልተቀመጠ!")

    deadline = time.time() + max_wait

    while True:
        async with _nvidia_text_lock:
            now = time.time()
            soonest_free_at = None

            for _ in range(len(_nvidia_text_clients)):
                idx = _nvidia_text_index
                _nvidia_text_index = (_nvidia_text_index + 1) % len(_nvidia_text_clients)

                _nvidia_text_prune_window(idx, now)
                q = _nvidia_text_call_times[idx]

                if len(q) < NVIDIA_TEXT_RPM_LIMIT:
                    q.append(now)
                    return _nvidia_text_clients[idx], idx

                key_free_at = q[0] + NVIDIA_TEXT_WINDOW_SECONDS
                if soonest_free_at is None or key_free_at < soonest_free_at:
                    soonest_free_at = key_free_at

        now = time.time()
        if now >= deadline:
            raise RuntimeError("All NVIDIA text keys are at their rate limit — timed out waiting")

        wait_time = max(0.5, (soonest_free_at or now + 1) - now)
        wait_time = min(wait_time, deadline - now, 5)
        logger.info(f"[NVIDIA Text] ሁሉም keys busy (rate-limit queue) — {wait_time:.1f}s እየጠበቅን...")
        await asyncio.sleep(wait_time)


def _nvidia_text_mark_blocked(idx: int):
    _nvidia_text_blocked_until[idx] = time.time()


def _nvidia_text_clear_blocked(idx: int):
    _nvidia_text_blocked_until.pop(idx, None)


async def _background_recheck_blocked_nvidia_text_keys():
    while True:
        try:
            await asyncio.sleep(NVIDIA_TEXT_HEALTH_RECHECK_INTERVAL)

            for idx in list(_nvidia_text_blocked_until.keys()):
                if idx >= len(_nvidia_text_clients):
                    _nvidia_text_blocked_until.pop(idx, None)
                    continue

                client = _nvidia_text_clients[idx]
                try:
                    await asyncio.to_thread(
                        lambda c=client: c.chat.completions.create(
                            model=NVIDIA_TEXT_MODEL,
                            messages=[{"role": "user", "content": "ping"}],
                            max_tokens=1,
                            extra_body=_build_extra_body(),
                        )
                    )
                    _nvidia_text_clear_blocked(idx)
                    async with _nvidia_text_lock:
                        _nvidia_text_call_times[idx].clear()
                    logger.info(f"[NVIDIA Text Health] Key {idx} ነፃ ሆኗል — ወደ rotation ተመለሰ")
                except Exception as e:
                    err_str = str(e).lower()
                    if "rate" in err_str or "429" in err_str or "limit" in err_str:
                        logger.info(f"[NVIDIA Text Health] Key {idx} ገና busy — {NVIDIA_TEXT_HEALTH_RECHECK_INTERVAL//60} ደቂቃ ይጠብቅ")
                        _nvidia_text_mark_blocked(idx)
                    else:
                        logger.warning(f"[NVIDIA Text Health] Key {idx} non-rate error during recheck: {e}")
        except Exception as loop_err:
            logger.error(f"[NVIDIA Text Health] background loop error: {loop_err}", exc_info=True)


def ensure_nvidia_text_health_task_started():
    global _nvidia_text_health_task_started
    if _nvidia_text_health_task_started or not _nvidia_text_clients:
        return
    _nvidia_text_health_task_started = True
    try:
        asyncio.create_task(_background_recheck_blocked_nvidia_text_keys())
        logger.info("[NVIDIA Text Health] background recheck task started")
    except RuntimeError:
        _nvidia_text_health_task_started = False


def _log_thinking_diagnostics(idx: int, call_elapsed: float, max_tokens: int, diag: dict, raw_len: int, final_len: int):
    """
    "ችግሩ think እያረገ ይቆያል" ለሚለው ጥያቄ ቀጥተኛ መልስ የሚሰጥ log line።
    እያንዳንዱ ጥሪ ካለቀ በኋላ ይጠራል፣ ምክንያቱን በግልጽ ያሳያል።
    """
    enable_thinking = _is_thinking_enabled()

    if diag["had_think"] and not diag["think_closed"]:
        # ትልቁ ችግር — max_tokens ሙሉ በሙሉ በ thinking ብቻ አልቋል፣ ምንም
        # እውነተኛ መልስ አልተፈጠረም። መፍትሄ፦ max_tokens ጨምር ወይም
        # enable_thinking=False አድርግ።
        logger.warning(
            f"[NVIDIA Text][THINK-OVERFLOW] Key #{idx+1} | call_time={call_elapsed:.1f}s | "
            f"enable_thinking={enable_thinking} | max_tokens={max_tokens} | "
            f"think_chars={diag['think_chars']} (ገና ያላለቀ <think> block) | "
            f"→ ውጤቱ ባዶ ሆኗል ምክንያቱም ሙሉ token budget-ው thinking ውስጥ ስላለቀ ነው። "
            f"መፍትሄ፦ NVIDIA_TEXT_ENABLE_THINKING=false ማድረግ ወይም max_tokens መጨመር።"
        )
    elif diag["had_think"] and diag["think_closed"]:
        # thinking ተጠናቅቋል ግን ጊዜ ወስዷል — enable_thinking=True ተብሎ
        # ታስቦ ከሆነ የሚጠበቅ ነው፣ ካልታሰበ ግን env var ትክክል አልገባም ማለት ነው።
        level = logger.info if enable_thinking else logger.warning
        level(
            f"[NVIDIA Text][THINK] Key #{idx+1} | call_time={call_elapsed:.1f}s | "
            f"enable_thinking={enable_thinking} | think_chars={diag['think_chars']} "
            f"(ተጠናቋል) | raw_len={raw_len} → final_len={final_len}"
            + ("" if enable_thinking else " ⚠️ enable_thinking=False ተብሎ ሳለ thinking ታይቷል — extra_body በትክክል እየተላከ እንደሆነ አረጋግጥ")
        )
    else:
        logger.info(
            f"[NVIDIA Text][NO-THINK] Key #{idx+1} | call_time={call_elapsed:.1f}s | "
            f"raw_len={raw_len} → final_len={final_len}"
        )


async def _call_nvidia_text_with_rotation(messages: list, max_tokens: int = 300) -> str:
    total_keys = len(_nvidia_text_clients)
    if total_keys == 0:
        raise RuntimeError("NVIDIA_TEXT_API_KEYS ያልተቀመጠ!")

    max_attempts = total_keys * 3
    last_error = None
    last_limited_idx = None
    call_started_at = time.time()
    extra_body = _build_extra_body()

    logger.info(
        f"[NVIDIA Text] ▶️ ጥሪ ጀመረ | model={NVIDIA_TEXT_MODEL} | enable_thinking={_is_thinking_enabled()} | "
        f"max_attempts={max_attempts} | max_tokens={max_tokens} | msg_preview={str(messages[-1].get('content',''))[:80]!r}"
    )

    for attempt in range(max_attempts):
        t_wait_start = time.time()
        try:
            client, idx = await _get_available_nvidia_text_client()
        except RuntimeError as e:
            logger.warning(f"[NVIDIA Text] {e} — retrying once more after short wait")
            await asyncio.sleep(2)
            continue
        wait_elapsed = time.time() - t_wait_start
        if wait_elapsed > 1:
            logger.info(f"[NVIDIA Text] ⏳ Slot wait {wait_elapsed:.1f}s ነበር (rate-limit queue) | Key #{idx+1} | attempt {attempt+1}/{max_attempts}")
        else:
            logger.info(f"[NVIDIA Text] 🔑 Key #{idx+1} ተመረጠ | attempt {attempt+1}/{max_attempts}")

        t_call_start = time.time()
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda c=client: c.chat.completions.create(
                        model=NVIDIA_TEXT_MODEL,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=0.6,
                        top_p=0.7,
                        extra_body=extra_body,
                    )
                ),
                timeout=NVIDIA_TEXT_REQUEST_TIMEOUT + 5,  # SDK timeout + buffer — hard ceiling
            )
            call_elapsed = time.time() - t_call_start
            _nvidia_text_clear_blocked(idx)
            raw = response.choices[0].message.content or ""
            text, diag = _strip_think_block(raw.strip())

            _log_thinking_diagnostics(idx, call_elapsed, max_tokens, diag, len(raw), len(text))
            logger.info(f"[NVIDIA Text] ✅ Key #{idx+1}/{total_keys} መለሰ | call_time={call_elapsed:.1f}s | total_time={time.time()-call_started_at:.1f}s")
            logger.info(f"[NVIDIA Text] raw response (key {idx+1}): {raw[:300]!r}")

            if not text:
                logger.warning(
                    f"[NVIDIA Text] Key #{idx+1} ባዶ final content መለሰ "
                    f"(had_think={diag['had_think']}, think_closed={diag['think_closed']}) — "
                    f"attempt {attempt+1}/{max_attempts}, ወደ next key/attempt"
                )
                last_limited_idx = idx
                continue
            if last_limited_idx is not None and last_limited_idx != idx:
                logger.info(f"[NVIDIA Text] 🔄 Rotated: Key #{last_limited_idx+1} → Key #{idx+1}")
            return text

        except asyncio.TimeoutError:
            call_elapsed = time.time() - t_call_start
            logger.warning(
                f"[NVIDIA Text] ⏱️ Key #{idx+1} TIMEOUT ({call_elapsed:.1f}s አለፈ, ገደብ {NVIDIA_TEXT_REQUEST_TIMEOUT+5}s) "
                f"— next key ይሞከራል | attempt {attempt+1}/{max_attempts} | ማስታወሻ፦ enable_thinking=True ከሆነ "
                f"timeout ብዙ ጊዜ thinking ራሱ ረዘም ስላደረገ ነው"
            )
            _nvidia_text_mark_blocked(idx)
            last_limited_idx = idx
            last_error = "timeout"
            continue

        except Exception as e:
            call_elapsed = time.time() - t_call_start
            last_error = e
            err_str = str(e).lower()
            is_rate = "rate" in err_str or "429" in err_str or "limit" in err_str
            is_timeout = (
                "timeout" in err_str
                or "timed out" in err_str
                or "timeout" in type(e).__name__.lower()
            )
            is_not_found = "404" in err_str or "not_found" in err_str or "not found" in err_str

            if is_not_found:
                # ሁሉም keys ላይ ተመሳሳይ 404 ይመለሳል (model ID ችግር እንጂ key
                # ችግር ስላልሆነ) — key rotation ከመድገም ይልቅ ወዲያውኑ ግልጽ
                # መልእክት ሰጥቶ ማቆም ይሻላል።
                logger.error(
                    f"[NVIDIA Text] 🛑 MODEL NOT FOUND (404) | model='{NVIDIA_TEXT_MODEL}' | "
                    f"NVIDIA_TEXT_MODEL env var ላይ ያለው ሞዴል ID hosted endpoint ላይ የለም ማለት ነው። "
                    f"hosted Qwen models፦ {sorted(_HOSTED_QWEN_MODELS)} | detail: {e}"
                )
                raise RuntimeError(f"Model '{NVIDIA_TEXT_MODEL}' not found on NVIDIA NIM (404) — check NVIDIA_TEXT_MODEL env var")

            if is_rate or is_timeout:
                reason = "rate limited" if is_rate else "TIMEOUT"
                logger.warning(f"[NVIDIA Text] ⛔ Key #{idx+1} {reason} ({call_elapsed:.1f}s) — next key ይሞከራል | attempt {attempt+1}/{max_attempts}")
                _nvidia_text_mark_blocked(idx)
                last_limited_idx = idx
                continue
            logger.error(f"[NVIDIA Text] ❌ Non-rate/non-timeout error ({call_elapsed:.1f}s): {e}")
            raise

    total_elapsed = time.time() - call_started_at
    logger.error(f"[NVIDIA Text] 🛑 ሁሉም keys አልቀዋል | {max_attempts} attempts | total_time={total_elapsed:.1f}s | last_error={last_error}")
    raise RuntimeError(f"All NVIDIA text keys exhausted after {max_attempts} attempts: {last_error}")


# ================================================================
# CONVERSATION MEMORY (in-RAM, TTL-based, per user_id+group_id)
# ================================================================
# ሙሉ conversation text አይደለም የሚያዝ — ብቻ last intent + short structured
# answer data + timestamp። ስለዚህ prompt ትንሽ፣ ፈጣን፣ rate-limit friendly
# ይሆናል። Context ካረጀ (CONTEXT_TTL_SECONDS አልፎ) ውድቅ ይደረጋል።

CONTEXT_TTL_SECONDS = 5 * 60  # 5 ደቂቃ

_conversation_context: dict[tuple, dict] = {}


def _context_key(user_id: int, group_id: int) -> tuple:
    return (user_id, group_id)


def save_context(user_id: int, group_id: int, intent: str, data: dict, reply_text: str = ""):
    """
    responder.py/handlers.py በየ reply መጨረሻ ይህን ይጥሩ — last intent +
    structured answer data ብቻ (ሙሉ ታሪክ አይደለም) ያስቀምጣል።

    ለምሳሌ፦
        save_context(
            user_id=123, group_id=-100999,
            intent="winner_query",
            data={"place": 1, "name": "አበበ", "number": 5},
            reply_text="🥇 1ኛ፡ አበበ (05)"
        )
    """
    _conversation_context[_context_key(user_id, group_id)] = {
        "intent": intent,
        "data": data or {},
        "reply_text": reply_text,
        "timestamp": time.time(),
    }


def get_context(user_id: int, group_id: int) -> dict | None:
    """last context ካልረጀ ይመልሳል፣ ካረጀ ወይም ከሌለ None ይመልሳል።"""
    ctx = _conversation_context.get(_context_key(user_id, group_id))
    if not ctx:
        return None
    if time.time() - ctx["timestamp"] > CONTEXT_TTL_SECONDS:
        _conversation_context.pop(_context_key(user_id, group_id), None)
        return None
    return ctx


def clear_context(user_id: int, group_id: int):
    """አዲስ game ሲጀመር ወይም explicit reset ሲያስፈልግ ይጠራል።"""
    _conversation_context.pop(_context_key(user_id, group_id), None)


def clear_all_context_for_group(group_id: int):
    """አዲስ game ሲጀመር ያ group ውስጥ ያሉ ሁሉንም users context ያጠፋል።"""
    keys_to_remove = [k for k in _conversation_context if k[1] == group_id]
    for k in keys_to_remove:
        _conversation_context.pop(k, None)


def _cleanup_expired_context():
    now = time.time()
    expired = [k for k, v in _conversation_context.items() if now - v["timestamp"] > CONTEXT_TTL_SECONDS]
    for k in expired:
        _conversation_context.pop(k, None)


# ================================================================
# CONTEXT-AWARE Q&A FALLBACK
# ================================================================
# Jina confidence ዝቅ ሲል (jina_detect_intent → "unknown" ወይም
# score < JINA_MIN_SCORE) responder.py/handlers.py ይህን ይጥሩ።
# last conversation context (ካለ) + relevant game data slice ብቻ
# (ሙሉ game state አይደለም) ወደ Qwen3-8B ልኮ በአማርኛ ትክክለኛ አጭር መልስ ይመልሳል።

_SYSTEM_PROMPT_TEMPLATE = """አንተ የኢትዮጵያ ሎተሪ/ጨዋታ ቴሌግራም ቦት ረዳት ነህ።
ተጠቃሚው ከዚህ በፊት የጠየቀው ጥያቄ እና የቦት መልስ (ካለ) እዚህ ስር አለ፣ አዲሱን ጥያቄ ከዛ context አንፃር መልስ።

ህጎች፦
- መልስህ ሁልጊዜ በአማርኛ፣ አጭር (ከ1-2 አረፍተ ነገር) መሆን አለበት
- 🙏 emoji በመጨረሻ ጨምር
- Context ውስጥ ያለውን መረጃ ብቻ ተጠቀም፣ አትፍጠር/አትገምት
- Context በቂ ካልሆነ ወይም ጥያቄው ግልጽ ካልሆነ "ይቅርታ ግልጽ አይደለም ቤተሰብ 🙏" በል
- ስሌት (ለምሳሌ ስንት ብር ይቀራል) ካስፈለገ game data ውስጥ ካለው ቁጥር ብቻ ተነስተህ አስላ

Respond ONLY with the final Amharic reply text — no JSON, no explanation, no extra text, no <think> tags."""


def _build_context_block(context: dict | None, game_data: dict | None) -> str:
    parts = []
    if context:
        parts.append(
            "ያለፈው ልውውጥ፦\n"
            f"- ተጠቃሚው ጠይቆ ነበር → intent: {context.get('intent')}, data: {json.dumps(context.get('data', {}), ensure_ascii=False)}\n"
            f"- ቦት መልስ ነበር → \"{context.get('reply_text', '')}\""
        )
    else:
        parts.append("ያለፈው ልውውጥ የለም።")

    if game_data:
        parts.append(f"የአሁኑ ጨዋታ መረጃ (ተዛማጅ ክፍል ብቻ)፦\n{json.dumps(game_data, ensure_ascii=False, default=str)}")

    return "\n\n".join(parts)


async def get_ai_fallback(
    text: str,
    user_id: int,
    group_id: int,
    game_data: dict | None = None,
) -> str | None:
    """
    Jina confidence ዝቅ ሲል ይጠራል። Returns:
        - አማርኛ reply string (context ተጠቅሞ ትክክለኛ መልስ ካገኘ)
        - None (context/game_data በቂ ካልሆነ ወይም AI call ካልተሳካ)

    game_data: intent-specific slice ብቻ ትልክ (ሙሉ game state አይደለም)።
        ለምሳሌ recent_winners query context ከሆነ →
        {"recent_winners": [...]}  ብቻ በቂ ነው።
    """
    _cleanup_expired_context()

    context = get_context(user_id, group_id)

    if not context and not game_data:
        # ምንም ማጣቀሻ የለም — AI ጥሪ ማድረግ ትርጉም የለውም
        logger.info(f"[AI Fallback] No context/game_data for user={user_id} — skipping AI call")
        return None

    if not _nvidia_text_clients:
        logger.warning("[AI Fallback] NVIDIA_TEXT_API_KEYS not configured — skipping")
        return None

    context_block = _build_context_block(context, game_data)

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT_TEMPLATE},
        {"role": "user", "content": f"{context_block}\n\nየአሁኑ ጥያቄ፦ \"{text}\""},
    ]

    fallback_started_at = time.time()
    try:
        reply = await _call_nvidia_text_with_rotation(messages, max_tokens=150)
        reply = reply.strip().strip('"')
        total_elapsed = time.time() - fallback_started_at
        logger.info(f"[AI Fallback] user={user_id} total_time={total_elapsed:.1f}s text='{text[:40]}' → reply='{reply[:100]}'")
        return reply if reply else None
    except Exception as e:
        total_elapsed = time.time() - fallback_started_at
        logger.warning(f"[AI Fallback] NVIDIA Text call failed after {total_elapsed:.1f}s: {e}")
        return None


# ================================================================
# TRANSACTION LOGGING (ነባር stub — ምንም አልተነካም)
# ================================================================

def log_transaction(*args, **kwargs):
    pass
