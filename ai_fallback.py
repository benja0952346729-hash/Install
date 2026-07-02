"""
ai_fallback.py
==============
Booking parse fallback — is_clear_pattern=False ሲሆን ብቻ ይጠራል።
Groq rotation ከ handlers.py ይጠቀማል። (ነባር — ምንም አልተነካም)

+ Context-aware Q&A fallback — Jina confidence score ዝቅ ሲል (unknown
  ወይም score < JINA_MIN_SCORE) ይጠራል። Conversation memory (last
  intent/answer) + game data slice ተጠቅሞ follow-up ጥያቄዎችን
  (ለምሳሌ "ማን አሸነፈ?" → "በዚ ዙር ነው?") በትክክል በአማርኛ ይመልሳል።

  NVIDIA Qwen3-235B-A22B ይጠቀማል — ሙሉ ለብቻው key rotation/rate-limit
  pool አለው (handlers.py's vision NVIDIA_API_KEYS ጋር አይጋራም/አይነካካም)።

  NOTE: Qwen3 ተመረጠ (ከ DeepSeek/GLM/Gemma ይልቅ) ምክንያቱም tokenizer/training
  ውስጥ በተለይ ለ አማርኛ (ዝቅተኛ-resource ቋንቋ) ተጨማሪ ዳታ ታክሎበታል፣ 119 ቋንቋዎችን
  ይደግፋል። Hybrid thinking mode ቁጥጥር በ NVIDIA_TEXT_ENABLE_THINKING env var
  (ነባሪ False = ፈጣኑ mode) ይደረጋል — chat_template_kwargs → enable_thinking።

Setup (Railway / .env):
    NVIDIA_TEXT_API_KEYS=key1,key2,key3
    (handlers.py ውስጥ ላለው NVIDIA_API_KEYS የተለዩ keys — ገለልተኛ pool)
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
# NVIDIA TEXT KEY ROTATION (DeepSeek V4 Flash — context Q&A fallback)
# ================================================================
# ሙሉ ለብቻው pool ነው — handlers.py ውስጥ ካለው vision NVIDIA rotation ጋር
# ምንም አይጋራም (የተለየ client list, index, lock, rate-limit window)።
# handlers.py ውስጥ ምንም ኮድ አልተነካም/አልተቀየረም።

NVIDIA_TEXT_API_KEYS = [
    k.strip() for k in os.environ.get("NVIDIA_TEXT_API_KEYS", "").split(",") if k.strip()
]

NVIDIA_TEXT_MODEL = "qwen/qwen3-235b-a22b-instruct-2507"

# NOTE: "qwen/qwen3-235b-a22b" (የቆየው/original) NVIDIA NIM ላይ deprecated/404
# ሆኗል። "-instruct-2507" ስሪት ትክክለኛው/ወቅታዊው endpoint ነው። ይህ ስሪት ተጨማሪ ጥቅም
# አለው፦ Non-thinking mode ብቻ ይደግፋል፣ <think> blocks በጭራሽ አያመነጭም —
# ስለዚህ thinking-mode delay/ambiguity ጨርሶ የለም፣ ሁሌም ፈጣን ነው።

# DeepSeek V4 Flash reasoning mode ቁጥጥር — ፍጥነት ስለሚያስፈልገን Non-think
# (thinking=False) ሁልጊዜ ተልኳል። ይህ ካልገባ NVIDIA NIM endpoint ላይ
# reasoning ራሱ በራሱ ሊበራ/ሊዘገይ ይችላል።
NVIDIA_TEXT_EXTRA_BODY = {}  # -2507 ስሪት non-thinking-only ስለሆነ chat_template_kwargs አያስፈልግም

NVIDIA_TEXT_REQUEST_TIMEOUT = 45  # ሰከንድ — Qwen3-235B ትልቅ ሞዴል ስለሆነ ትንሽ ጊዜ ተጨምሯል (medium speed OK)

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
NVIDIA_TEXT_MAX_WAIT_SECONDS = 60
NVIDIA_TEXT_HEALTH_RECHECK_INTERVAL = 7 * 60

_nvidia_text_lock = asyncio.Lock()
_nvidia_text_call_times = defaultdict(deque)
_nvidia_text_blocked_until = {}
_nvidia_text_health_task_started = False

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def _strip_think_block(text: str) -> str:
    if not text:
        return text
    return _THINK_BLOCK_RE.sub("", text).strip()


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
        logger.info(f"[NVIDIA Text] ሁሉም keys busy — {wait_time:.1f}s እየጠበቅን...")
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
                            extra_body=NVIDIA_TEXT_EXTRA_BODY,
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


async def _call_nvidia_text_with_rotation(messages: list, max_tokens: int = 300) -> str:
    total_keys = len(_nvidia_text_clients)
    if total_keys == 0:
        raise RuntimeError("NVIDIA_TEXT_API_KEYS ያልተቀመጠ!")

    max_attempts = total_keys * 3
    last_error = None
    last_limited_idx = None
    call_started_at = time.time()

    logger.info(f"[NVIDIA Text] ▶️ ጥሪ ጀመረ | max_attempts={max_attempts} | msg_preview={str(messages[-1].get('content',''))[:80]!r}")

    for attempt in range(max_attempts):
        t_wait_start = time.time()
        try:
            client, idx = await _get_available_nvidia_text_client()
        except RuntimeError as e:
            logger.warning(f"[NVIDIA Text] {e} — retrying once more after short wait")
            await asyncio.sleep(2)
            continue
        wait_elapsed = time.time() - t_wait_start
        logger.info(f"[NVIDIA Text] 🔑 Key #{idx+1} ተመረጠ (slot wait: {wait_elapsed:.1f}s) | attempt {attempt+1}/{max_attempts}")

        t_call_start = time.time()
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda c=client: c.chat.completions.create(
                        model=NVIDIA_TEXT_MODEL,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=0.2,
                        extra_body=NVIDIA_TEXT_EXTRA_BODY,  # {} — non-thinking-only ሞዴል
                    )
                ),
                timeout=NVIDIA_TEXT_REQUEST_TIMEOUT + 5,  # SDK timeout + buffer — hard ceiling
            )
            call_elapsed = time.time() - t_call_start
            _nvidia_text_clear_blocked(idx)
            raw = response.choices[0].message.content or ""
            text = _strip_think_block(raw.strip())

            had_think_block = raw.strip() != text
            logger.info(
                f"[NVIDIA Text] ✅ Key #{idx+1}/{total_keys} መለሰ | call_time={call_elapsed:.1f}s | "
                f"total_time={time.time()-call_started_at:.1f}s | had_think_block={had_think_block} | "
                f"raw_len={len(raw)} chars"
            )
            logger.info(f"[NVIDIA Text] raw response (key {idx+1}): {raw[:300]!r}")

            if not text:
                logger.warning(f"[NVIDIA Text] Key #{idx+1} ባዶ content መለሰ — attempt {attempt+1}/{max_attempts}")
                last_limited_idx = idx
                continue
            if last_limited_idx is not None and last_limited_idx != idx:
                logger.info(f"[NVIDIA Text] 🔄 Rotated: Key #{last_limited_idx+1} → Key #{idx+1}")
            return text

        except asyncio.TimeoutError:
            call_elapsed = time.time() - t_call_start
            logger.warning(
                f"[NVIDIA Text] ⏱️ Key #{idx+1} TIMEOUT ({call_elapsed:.1f}s አለፈ, ገደብ {NVIDIA_TEXT_REQUEST_TIMEOUT+5}s) "
                f"— next key ይሞከራል | attempt {attempt+1}/{max_attempts}"
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
# (ሙሉ game state አይደለም) ወደ DeepSeek V4 Flash ልኮ በአማርኛ ትክክለኛ
# አጭር መልስ ይመልሳል።

_SYSTEM_PROMPT_TEMPLATE = """አንተ የኢትዮጵያ ሎተሪ/ጨዋታ ቴሌግራም ቦት ረዳት ነህ።
ተጠቃሚው ከዚህ በፊት የጠየቀው ጥያቄ እና የቦት መልስ (ካለ) እዚህ ስር አለ፣ አዲሱን ጥያቄ ከዛ context አንፃር መልስ።

ህጎች፦
- መልስህ ሁልጊዜ በአማርኛ፣ አጭር (ከ1-2 አረፍተ ነገር) መሆን አለበት
- 🙏 emoji በመጨረሻ ጨምር
- Context ውስጥ ያለውን መረጃ ብቻ ተጠቀም፣ አትፍጠር/አትገምት
- Context በቂ ካልሆነ ወይም ጥያቄው ግልጽ ካልሆነ "ይቅርታ ግልጽ አይደለም ቤተሰብ 🙏" በል
- ስሌት (ለምሳሌ ስንት ብር ይቀራል) ካስፈለገ game data ውስጥ ካለው ቁጥር ብቻ ተነስተህ አስላ

Respond ONLY with the final Amharic reply text — no JSON, no explanation, no extra text."""


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

    try:
        reply = await _call_nvidia_text_with_rotation(messages, max_tokens=150)
        reply = reply.strip().strip('"')
        logger.info(f"[AI Fallback] user={user_id} text='{text[:40]}' → reply='{reply[:100]}'")
        return reply if reply else None
    except Exception as e:
        logger.warning(f"[AI Fallback] NVIDIA Text call failed: {e}")
        return None


# ================================================================
# TRANSACTION LOGGING (ነባር stub — ምንም አልተነካም)
# ================================================================

def log_transaction(*args, **kwargs):
    pass
