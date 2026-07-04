import os
import re
import json
import base64
import logging
import random
import asyncio
import time
from collections import defaultdict, deque
from typing import Optional
from config import BOT_TOKEN, GROUP_CHAT_ID, GROQ_API_KEYS, NVIDIA_API_KEYS, JINA_API_KEYS
import httpx
from groq import Groq
from openai import OpenAI
from database import (
    save_sms_payment,
    save_screenshot_payment,
    get_sms_payment_by_ref,
    is_ref_matched_already,
    cleanup_old_payments,
    confirm_payment,
    get_paid_numbers,
    get_active_settings,
    get_taken_numbers,
    get_user_by_number,
    get_users_by_number,
    add_winner_balance,
    save_winner,
    log_activity,
    find_matching_sms,
)
from jina_brain import get_shared_jina_key

logger = logging.getLogger(__name__)

PAYMENT_SUCCESS_MESSAGES = [
    "መልካም ዕድል, ወዳጄ 🙏",
    "መልካም ዕድል, ይቅናህ ቤተሰብ 🙏",
    "መልካም ዕድል 🙏",
    "እሺ ቤተሰብ 🙏 መልካም ዕድል",
]

# Winner-photo digit confidence (0-100). If the primary vision provider's
# self-reported confidence is below this, a second provider is asked to
# confirm before the result is trusted. Tune this based on real logs —
# lower = fewer cross-checks (faster/cheaper) but more risk of a silent
# misread; higher = more cross-checks (slower) but safer.
WINNER_CONFIDENCE_THRESHOLD = 99

# ============================================================
# GROQ KEY ROTATION
# ============================================================

_groq_index = 0
_groq_clients = [Groq(api_key=key) for key in GROQ_API_KEYS] if GROQ_API_KEYS else []

# Model used for Groq text calls (llama-3.3-70b-versatile was deprecated
# by Groq on 2026-06-17). qwen/qwen3.6-27b is Groq's recommended replacement.
# Groq is now used for text-only calls (parse_sms, HTML parsing, Amharic
# descriptions) — all vision/image calls go through Mistral/Gemini instead.
GROQ_TEXT_MODEL = "qwen/qwen3.6-27b"


def _get_groq_client() -> Groq:
    global _groq_index
    if not _groq_clients:
        raise RuntimeError("GROQ_API_KEY ያልተቀመጠ!")
    client = _groq_clients[_groq_index]
    _groq_index = (_groq_index + 1) % len(_groq_clients)
    return client


_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def _strip_think_block(text: str) -> str:
    """Remove any leaked <think>...</think> reasoning block (safety net —
    reasoning_effort='none' should already prevent this on Groq's qwen3.6-27b,
    but we strip defensively in case a provider/model still emits one)."""
    if not text:
        return text
    return _THINK_BLOCK_RE.sub("", text).strip()


def _extract_json_object(text: str) -> str:
    """Pull out just the {...} object from a response, even if the model
    wrapped it in prose/explanation (e.g. a provider narrating its reasoning
    before the JSON, or markdown fences). Falls back to the original text
    (after fence-stripping) if no braces are found, so json.loads still
    gets a fair shot and raises a normal, catchable error."""
    if not text:
        return text
    cleaned = re.sub(r"^```json\s*", "", text)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start:end + 1]
    return cleaned.strip()


async def _call_groq_with_rotation(messages: list, max_tokens: int = 300) -> str:
    total_keys = len(_groq_clients)
    max_attempts = total_keys * 2
    last_limited_key = None
    for attempt in range(max_attempts):
        client = _get_groq_client()
        key_num = (_groq_index - 1) % total_keys + 1
        try:
            response = await asyncio.to_thread(
                lambda c=client: c.chat.completions.create(
                    model=GROQ_TEXT_MODEL,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.1,
                    reasoning_effort="none",  # qwen3.6-27b defaults to thinking mode;
                                               # disable it or max_tokens gets eaten by
                                               # <think> reasoning and content comes back empty
                )
            )
            raw = response.choices[0].message.content or ""
            text = _strip_think_block(raw.strip())
            logger.info(f"[Groq] raw response ({key_num}): {raw[:300]!r}")
            if not text:
                logger.warning(f"[Groq] Key #{key_num} returned empty content — attempt {attempt+1}/{max_attempts}")
                continue
            if last_limited_key is not None and last_limited_key != key_num:
                logger.info(f"[Groq] 🔄 Rotated: Key #{last_limited_key} → Key #{key_num}")
            logger.info(f"[Groq] ✅ Key #{key_num}/{total_keys} used ({GROQ_TEXT_MODEL})")
            return text
        except Exception as e:
            err_str = str(e).lower()
            if "rate" in err_str or "429" in err_str or "limit" in err_str:
                logger.warning(f"[Groq] Key #{key_num} rate limited — attempt {attempt+1}/{max_attempts}")
                last_limited_key = key_num
                if (attempt + 1) % total_keys == 0:
                    logger.info("[Groq] All keys exhausted — waiting 10s...")
                    await asyncio.sleep(10)
                continue
            logger.error(f"[Groq] Non-rate error: {e}")
            raise
    raise RuntimeError("All Groq keys exhausted or returned empty content")


# Groq vision — used ONLY as a last-resort fallback for analyze_winner_photo
# (Mistral and Gemini are tried first). Kept because this used to work
# reliably before the switch.
GROQ_VISION_MODEL = "qwen/qwen3.6-27b"


async def _call_groq_vision_with_rotation(image_base64: str, prompt: str) -> str:
    total_keys = len(_groq_clients)
    max_attempts = total_keys * 2
    for attempt in range(max_attempts):
        client = _get_groq_client()
        key_num = (_groq_index - 1) % total_keys + 1
        try:
            response = await asyncio.to_thread(
                lambda c=client: c.chat.completions.create(
                    model=GROQ_VISION_MODEL,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                            {"type": "text", "text": prompt},
                        ],
                    }],
                    max_tokens=600,
                    temperature=0.1,
                    reasoning_effort="none",
                )
            )
            raw = response.choices[0].message.content or ""
            text = _strip_think_block(raw.strip())
            logger.info(f"[Groq Vision] raw response ({key_num}): {raw[:300]!r}")
            if not text:
                logger.warning(f"[Groq Vision] Key #{key_num} returned empty content — attempt {attempt+1}/{max_attempts}")
                continue
            logger.info(f"[Groq Vision] ✅ Key #{key_num}/{total_keys} used ({GROQ_VISION_MODEL})")
            return text
        except Exception as e:
            err_str = str(e).lower()
            if "rate" in err_str or "429" in err_str or "limit" in err_str:
                logger.warning(f"[Groq Vision] Key #{key_num} rate limited — attempt {attempt+1}/{max_attempts}")
                if (attempt + 1) % total_keys == 0:
                    logger.info("[Groq Vision] All keys exhausted — waiting 10s...")
                    await asyncio.sleep(10)
                continue
            logger.error(f"[Groq Vision] Non-rate error: {e}")
            raise
    raise RuntimeError("All Groq vision keys exhausted or returned empty content")
    raise RuntimeError("All Groq keys exhausted")


# ============================================================
# JINA KEY ROTATION
# ============================================================

def _get_jina_key() -> str:
    return get_shared_jina_key()


# ============================================================
# MISTRAL KEY ROTATION  (replaces NVIDIA for vision — same rotation/
# rate-limit/health-check structure as before, just pointed at a
# different provider + model. NVIDIA_API_KEYS/config left untouched
# elsewhere in case it's still referenced; this pool reads
# MISTRAL_API_KEYS instead.)
# ============================================================

try:
    from config import MISTRAL_API_KEYS
except ImportError:
    MISTRAL_API_KEYS = []

_nvidia_index = 0
_nvidia_clients = [
    OpenAI(
        base_url="https://api.mistral.ai/v1",
        api_key=key
    ) for key in MISTRAL_API_KEYS
] if MISTRAL_API_KEYS else []

MISTRAL_VISION_MODEL = "mistral-small-2506"

NVIDIA_RPM_LIMIT = 280  # mistral-small-2506 dashboard limit ~300 RPM — kept a safety margin
NVIDIA_WINDOW_SECONDS = 60
NVIDIA_MAX_WAIT_SECONDS = 120
NVIDIA_HEALTH_RECHECK_INTERVAL = 7 * 60

_nvidia_lock = asyncio.Lock()
_nvidia_call_times = defaultdict(deque)
_nvidia_blocked_until = {}
_nvidia_health_task_started = False


def _get_nvidia_client():
    global _nvidia_index
    if not _nvidia_clients:
        raise RuntimeError("MISTRAL_API_KEYS ያልተቀመጠ!")
    client = _nvidia_clients[_nvidia_index]
    _nvidia_index = (_nvidia_index + 1) % len(_nvidia_clients)
    return client


def _nvidia_prune_window(idx: int, now: float):
    q = _nvidia_call_times[idx]
    while q and now - q[0] > NVIDIA_WINDOW_SECONDS:
        q.popleft()


async def _get_available_nvidia_client(max_wait: int = NVIDIA_MAX_WAIT_SECONDS):
    global _nvidia_index
    deadline = time.time() + max_wait

    while True:
        async with _nvidia_lock:
            now = time.time()
            soonest_free_at = None

            for _ in range(len(_nvidia_clients)):
                idx = _nvidia_index
                _nvidia_index = (_nvidia_index + 1) % len(_nvidia_clients)

                _nvidia_prune_window(idx, now)
                q = _nvidia_call_times[idx]

                if len(q) < NVIDIA_RPM_LIMIT:
                    q.append(now)
                    return _nvidia_clients[idx], idx

                key_free_at = q[0] + NVIDIA_WINDOW_SECONDS
                if soonest_free_at is None or key_free_at < soonest_free_at:
                    soonest_free_at = key_free_at

        now = time.time()
        if now >= deadline:
            raise RuntimeError("All Mistral keys are at their rate limit — timed out waiting")

        wait_time = max(0.5, (soonest_free_at or now + 1) - now)
        wait_time = min(wait_time, deadline - now, 5)
        logger.info(f"[Mistral] ሁሉም keys busy — {wait_time:.1f}s እየጠበቅን...")
        await asyncio.sleep(wait_time)


def _nvidia_mark_blocked(idx: int):
    _nvidia_blocked_until[idx] = time.time()


def _nvidia_clear_blocked(idx: int):
    _nvidia_blocked_until.pop(idx, None)


async def _background_recheck_blocked_nvidia_keys():
    while True:
        try:
            await asyncio.sleep(NVIDIA_HEALTH_RECHECK_INTERVAL)

            for idx in list(_nvidia_blocked_until.keys()):
                if idx >= len(_nvidia_clients):
                    _nvidia_blocked_until.pop(idx, None)
                    continue

                client = _nvidia_clients[idx]
                try:
                    await asyncio.to_thread(
                        lambda c=client: c.chat.completions.create(
                            model=MISTRAL_VISION_MODEL,
                            messages=[{"role": "user", "content": "ping"}],
                            max_tokens=1,
                        )
                    )
                    _nvidia_clear_blocked(idx)
                    async with _nvidia_lock:
                        _nvidia_call_times[idx].clear()
                    logger.info(f"[Mistral Health] Key {idx} ነፃ ሆኗል — ወደ rotation ተመለሰ")
                except Exception as e:
                    err_str = str(e).lower()
                    if "rate" in err_str or "429" in err_str or "limit" in err_str:
                        logger.info(f"[Mistral Health] Key {idx} ገና busy — {NVIDIA_HEALTH_RECHECK_INTERVAL//60} ደቂቃ ይጠብቅ")
                        _nvidia_mark_blocked(idx)
                    else:
                        logger.warning(f"[Mistral Health] Key {idx} non-rate error during recheck: {e}")
        except Exception as loop_err:
            logger.error(f"[Mistral Health] background loop error: {loop_err}", exc_info=True)


def ensure_nvidia_health_task_started():
    global _nvidia_health_task_started
    if _nvidia_health_task_started or not _nvidia_clients:
        return
    _nvidia_health_task_started = True
    try:
        asyncio.create_task(_background_recheck_blocked_nvidia_keys())
        logger.info("[Mistral Health] background recheck task started")
    except RuntimeError:
        _nvidia_health_task_started = False


async def _call_nvidia_with_rotation(image_base64: str, prompt: str) -> str:
    total_keys = len(_nvidia_clients)
    if total_keys == 0:
        raise RuntimeError("MISTRAL_API_KEYS ያልተቀመጠ!")

    max_attempts = total_keys * 3
    last_error = None
    last_limited_idx = None

    for attempt in range(max_attempts):
        try:
            client, idx = await _get_available_nvidia_client()
        except RuntimeError as e:
            logger.warning(f"[Mistral] {e} — retrying once more after short wait")
            await asyncio.sleep(2)
            continue

        try:
            response = await asyncio.to_thread(
                lambda c=client: c.chat.completions.create(
                    model=MISTRAL_VISION_MODEL,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                            {"type": "text", "text": prompt},
                        ],
                    }],
                    max_tokens=600,
                    temperature=0.1,
                )
            )
            _nvidia_clear_blocked(idx)
            raw = response.choices[0].message.content or ""
            text = raw.strip()
            logger.info(f"[Mistral] raw response (key {idx+1}): {raw[:300]!r}")
            if not text:
                logger.warning(f"[Mistral] Key #{idx+1} returned empty content — attempt {attempt+1}/{max_attempts}")
                last_limited_idx = idx
                continue
            if last_limited_idx is not None and last_limited_idx != idx:
                logger.info(f"[Mistral] 🔄 Rotated: Key #{last_limited_idx+1} → Key #{idx+1}")
            logger.info(f"[Mistral] ✅ Key #{idx+1}/{total_keys} used ({MISTRAL_VISION_MODEL})")
            return text
        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            if "rate" in err_str or "429" in err_str or "limit" in err_str:
                logger.warning(f"[Mistral] Key #{idx+1} rate limited — attempt {attempt+1}/{max_attempts}")
                _nvidia_mark_blocked(idx)
                last_limited_idx = idx
                continue
            logger.error(f"[Mistral] Non-rate error: {e}")
            raise

    raise RuntimeError(f"All Mistral keys exhausted after {max_attempts} attempts: {last_error}")


# ============================================================
# GEMINI KEY ROTATION (NVIDIA-style sliding window RPM tracking)
# ============================================================

try:
    from config import GEMINI_API_KEYS
except ImportError:
    GEMINI_API_KEYS = []

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_RPM_LIMIT = 8  # conservative vs free-tier ceiling (10-15 RPM/key)
GEMINI_WINDOW_SECONDS = 60
GEMINI_MAX_WAIT_SECONDS = 120
GEMINI_HEALTH_RECHECK_INTERVAL = 7 * 60
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_gemini_index = 0
_gemini_lock = asyncio.Lock()
_gemini_call_times = defaultdict(deque)
_gemini_blocked_until = {}
_gemini_health_task_started = False


def _gemini_prune_window(idx: int, now: float):
    q = _gemini_call_times[idx]
    while q and now - q[0] > GEMINI_WINDOW_SECONDS:
        q.popleft()


async def _get_available_gemini_key(max_wait: int = GEMINI_MAX_WAIT_SECONDS):
    global _gemini_index
    if not GEMINI_API_KEYS:
        raise RuntimeError("GEMINI_API_KEY ያልተቀመጠ!")

    deadline = time.time() + max_wait
    total_keys = len(GEMINI_API_KEYS)

    while True:
        async with _gemini_lock:
            now = time.time()
            soonest_free_at = None

            for _ in range(total_keys):
                idx = _gemini_index
                _gemini_index = (_gemini_index + 1) % total_keys

                _gemini_prune_window(idx, now)
                q = _gemini_call_times[idx]

                if len(q) < GEMINI_RPM_LIMIT:
                    q.append(now)
                    return GEMINI_API_KEYS[idx], idx

                key_free_at = q[0] + GEMINI_WINDOW_SECONDS
                if soonest_free_at is None or key_free_at < soonest_free_at:
                    soonest_free_at = key_free_at

        now = time.time()
        if now >= deadline:
            raise RuntimeError("All Gemini keys are at their rate limit — timed out waiting")

        wait_time = max(0.5, (soonest_free_at or now + 1) - now)
        wait_time = min(wait_time, deadline - now, 5)
        logger.info(f"[Gemini] ሁሉም keys busy — {wait_time:.1f}s እየጠበቅን...")
        await asyncio.sleep(wait_time)


def _gemini_mark_blocked(idx: int):
    _gemini_blocked_until[idx] = time.time()


def _gemini_clear_blocked(idx: int):
    _gemini_blocked_until.pop(idx, None)


async def _background_recheck_blocked_gemini_keys():
    while True:
        try:
            await asyncio.sleep(GEMINI_HEALTH_RECHECK_INTERVAL)

            for idx in list(_gemini_blocked_until.keys()):
                if idx >= len(GEMINI_API_KEYS):
                    _gemini_blocked_until.pop(idx, None)
                    continue

                key = GEMINI_API_KEYS[idx]
                try:
                    url = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent?key={key}"
                    async with httpx.AsyncClient(timeout=15) as client:
                        res = await client.post(
                            url,
                            json={"contents": [{"parts": [{"text": "ping"}]}]},
                        )
                    if res.status_code == 200:
                        _gemini_clear_blocked(idx)
                        async with _gemini_lock:
                            _gemini_call_times[idx].clear()
                        logger.info(f"[Gemini Health] Key {idx} ነፃ ሆኗል — ወደ rotation ተመለሰ")
                    elif res.status_code == 429:
                        logger.info(f"[Gemini Health] Key {idx} ገና busy — {GEMINI_HEALTH_RECHECK_INTERVAL//60} ደቂቃ ይጠብቅ")
                        _gemini_mark_blocked(idx)
                    else:
                        logger.warning(f"[Gemini Health] Key {idx} non-rate status {res.status_code} during recheck")
                except Exception as e:
                    logger.warning(f"[Gemini Health] Key {idx} recheck error: {e}")
        except Exception as loop_err:
            logger.error(f"[Gemini Health] background loop error: {loop_err}", exc_info=True)


def ensure_gemini_health_task_started():
    global _gemini_health_task_started
    if _gemini_health_task_started or not GEMINI_API_KEYS:
        return
    _gemini_health_task_started = True
    try:
        asyncio.create_task(_background_recheck_blocked_gemini_keys())
        logger.info("[Gemini Health] background recheck task started")
    except RuntimeError:
        _gemini_health_task_started = False


async def _call_gemini_with_rotation(image_base64: str, prompt: str) -> str:
    total_keys = len(GEMINI_API_KEYS)
    if total_keys == 0:
        raise RuntimeError("GEMINI_API_KEY ያልተቀመጠ!")

    max_attempts = total_keys * 3
    last_error = None
    last_limited_idx = None

    for attempt in range(max_attempts):
        try:
            key, idx = await _get_available_gemini_key()
        except RuntimeError as e:
            logger.warning(f"[Gemini] {e} — retrying once more after short wait")
            await asyncio.sleep(2)
            continue

        try:
            url = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent?key={key}"
            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/jpeg", "data": image_base64}},
                    ]
                }],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 600},
            }
            async with httpx.AsyncClient(timeout=30) as client:
                res = await client.post(url, json=payload)

            if res.status_code == 429:
                logger.warning(f"[Gemini] Key #{idx+1} rate limited — attempt {attempt+1}/{max_attempts}")
                _gemini_mark_blocked(idx)
                last_limited_idx = idx
                continue

            res.raise_for_status()
            data = res.json()
            candidates = data.get("candidates") or []
            raw = ""
            if candidates:
                parts = candidates[0].get("content", {}).get("parts") or []
                raw = "".join(p.get("text", "") for p in parts)
            text = raw.strip()
            logger.info(f"[Gemini] raw response (key {idx+1}): {raw[:300]!r}")
            if not text:
                logger.warning(f"[Gemini] Key #{idx+1} returned empty/blocked content ({data.get('promptFeedback')}) — attempt {attempt+1}/{max_attempts}")
                last_limited_idx = idx
                continue
            _gemini_clear_blocked(idx)
            if last_limited_idx is not None and last_limited_idx != idx:
                logger.info(f"[Gemini] 🔄 Rotated: Key #{last_limited_idx+1} → Key #{idx+1}")
            logger.info(f"[Gemini] ✅ Key #{idx+1}/{total_keys} used ({GEMINI_MODEL})")
            return text

        except httpx.HTTPStatusError as e:
            last_error = e
            logger.error(f"[Gemini] HTTP error on key #{idx+1}: {e}")
            raise
        except Exception as e:
            last_error = e
            logger.error(f"[Gemini] Non-rate error on key #{idx+1}: {e}")
            raise

    raise RuntimeError(f"All Gemini keys exhausted after {max_attempts} attempts: {last_error}")


# ============================================================
# SMS PARSER
# ============================================================

async def parse_sms(sms: str) -> Optional[dict]:
    prompt = """You are an Ethiopian bank SMS parser.

Analyze this SMS and extract payment information.

Rules:
- is_incoming: true only if money was RECEIVED (credited, received). false if money was SENT (transferred, debited).
- type: "Telebirr", "CBE", "Awash", "BOA", or "Other"
- amount: the amount received (not including service charges/VAT)
- sender_name: name of who sent the money (if mentioned). null if not found.
- ref: transaction reference number. Only extract if Telebirr (transaction number). null for others.
- url: any URL found in the SMS. null if none.

Respond ONLY in this exact JSON format with no extra text:
{
  "is_incoming": true or false,
  "type": "CBE" or "Telebirr" or "Awash" or "BOA" or "Other",
  "amount": <number or null>,
  "sender_name": "<name or null>",
  "ref": "<ref or null>",
  "url": "<url or null>"
}"""

    try:
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": sms},
        ]
        text = await _call_groq_with_rotation(messages)
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"^```\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        parsed = json.loads(text.strip())

        for field in ("sender_name", "ref", "url"):
            if parsed.get(field) in ("null", "None", "", "N/A"):
                parsed[field] = None

        return parsed

    except Exception as e:
        logger.error(f"[SMS Parse] error: {e}", exc_info=True)
        return None


# ============================================================
# JINA URL → full payment data
# ============================================================

async def _parse_html_with_groq(html: str, url: str) -> Optional[dict]:
    messages = [
        {"role": "system", "content": """You are an Ethiopian bank receipt parser. Extract payment info from receipt page HTML or text.

Supported banks: CBE, Telebirr, Awash, BOA, Dashen, Abay, Nib, Wegagen, United, Lion, Oromia, Bunna, Berhan, Coopbank, Enat, Amhara, Zemen, and any other Ethiopian bank.

AMOUNT RULES (very important):
- Use ONLY the base transferred/sent amount
- Do NOT use "Total amount debited" or "Total" (includes service charge)
- Do NOT use service charge / VAT / fee amounts
- Look for: "Transferred Amount", "Amount", "የተላከ መጠን", "ክፍያ መጠን"
- If only total is available, subtract service charge to get base amount

SENDER NAME RULES:
- Look for: "Payer", "Sender", "From", "የላኪ ስም", "ላኪ"
- Return full name as shown

REFERENCE RULES:
- Look for: "Reference No", "Transaction ID", "Ref", "Transaction No", "የግብይት ቁጥር"
- Return as-is

BANK DETECTION:
- mbreciept.cbe.com.et → "CBE"
- telebirr → "Telebirr"
- awash → "Awash"
- boa → "BOA"
- dashen → "Dashen"
- Otherwise detect from page content

If the page is NOT a bank receipt at all, return:
{"amount": null, "sender_name": null, "ref": null, "bank": null}

Only return amount if you are confident this is a payment receipt.

Respond ONLY in JSON with no extra text:
{"amount": <number or null>, "sender_name": "<name or null>", "ref": "<ref or null>", "bank": "<bank name or null>"}"""},
        {"role": "user", "content": html[:4000]},
    ]
    try:
        logger.info(f"[URL Fetch] HTML preview (first 600): {html[:600]!r}")
        result_text = await _call_groq_with_rotation(messages)
        logger.info(f"[URL Fetch] Groq raw response: {result_text!r}")
        result_text = re.sub(r"^```json\s*", "", result_text)
        result_text = re.sub(r"^```\s*", "", result_text)
        result_text = re.sub(r"\s*```$", "", result_text)
        parsed = json.loads(result_text.strip())
        logger.info(f"[URL Fetch] Groq parsed: {parsed}")
        if parsed.get("amount"):
            return parsed
        return None
    except Exception as e:
        logger.warning(f"[URL Fetch] Groq parse error: {e}")
        return None


async def fetch_payment_data_from_url(url: str) -> Optional[dict]:
    fail_reason = "unknown"

    jina_url = f"https://r.jina.ai/{url}"
    jina_key = _get_jina_key()
    headers = {
        "Accept": "text/plain",
        "User-Agent": "Mozilla/5.0",
        "X-Timeout": "30",
        "X-Return-Format": "text",
    }
    if jina_key:
        headers["Authorization"] = f"Bearer {jina_key}"

    for attempt in range(len(JINA_API_KEYS) if JINA_API_KEYS else 1):
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                res = await client.get(jina_url, headers=headers)

            if res.status_code == 200 and res.text.strip():
                logger.info(f"[URL Fetch] Jina succeeded (attempt {attempt+1})")
                result = await _parse_html_with_groq(res.text, url)
                if result:
                    return result
                fail_reason = "jina_ok_no_amount"
                logger.info("[URL Fetch] Jina content ok but no amount — trying direct")
                break

            elif res.status_code == 429:
                fail_reason = f"jina_rate_limit_{attempt+1}"
                logger.warning(f"[URL Fetch] Jina rate limited (attempt {attempt+1}) — rotating key")
                new_key = _get_jina_key()
                if new_key:
                    headers["Authorization"] = f"Bearer {new_key}"
                await asyncio.sleep(2)
                continue

            else:
                fail_reason = f"jina_status_{res.status_code}"
                logger.warning(f"[URL Fetch] Jina status {res.status_code} — trying direct")
                break

        except Exception as e:
            fail_reason = f"jina_error_{type(e).__name__}"
            logger.warning(f"[URL Fetch] Jina error (attempt {attempt+1}): {e}")
            break

    try:
        headers_direct = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            res = await client.get(url, headers=headers_direct)
            if res.status_code == 200 and res.text.strip():
                logger.info("[URL Fetch] Direct fetch succeeded")
                result = await _parse_html_with_groq(res.text, url)
                if result:
                    return result
                fail_reason = "direct_ok_no_amount"
                logger.info("[URL Fetch] Direct fetch — no amount found")
            else:
                fail_reason = f"direct_status_{res.status_code}"
    except Exception as e:
        fail_reason = f"direct_error_{type(e).__name__}"
        logger.warning(f"[URL Fetch] Direct fetch failed: {e}")

    logger.error(f"[URL Fetch] All methods failed for: {url} | reason: {fail_reason}")
    return {"_fail_reason": fail_reason}


# ============================================================
# SMS WEBHOOK
# ============================================================

async def handle_sms_webhook(raw_sms: str, bot=None, nekay_cb=None, group_id: int = None) -> dict:
    logger.info(f"[SMS] Received: {raw_sms}")

    parsed = await parse_sms(raw_sms)
    if not parsed:
        return {"success": False, "reason": "unparseable"}

    if not parsed.get("is_incoming"):
        logger.info("[SMS] Outgoing SMS — skipping")
        return {"success": False, "reason": "outgoing"}

    amount = parsed.get("amount")
    sender_name = parsed.get("sender_name")
    ref = parsed.get("ref")
    sms_type = parsed.get("type")
    url = parsed.get("url")

    if not amount:
        return {"success": False, "reason": "no_amount"}

    if url and (not sender_name or len(sender_name.split()) < 2):
        logger.info(f"[SMS] Sender name incomplete — fetching from URL: {url}")
        url_data = await fetch_payment_data_from_url(url)
        if url_data:
            if url_data.get("sender_name"):
                sender_name = url_data["sender_name"]
            if url_data.get("amount") and not amount:
                amount = url_data["amount"]
            if url_data.get("ref") and not ref:
                ref = url_data["ref"]

    logger.info(f"[SMS] type={sms_type} | amount={amount} | sender={sender_name} | ref={ref} | group={group_id}")

    settings = get_active_settings(group_id=group_id)
    game_id = settings["id"] if settings else None

    result = save_sms_payment(
        amount=amount,
        sender_name=sender_name,
        ref=ref,
        sms_type=sms_type,
        raw_sms=raw_sms,
        group_id=group_id,
        game_id=game_id,
    )

    if result.get("matched") and bot:
        matched = result["matched"]
        target_chat = matched.get("group_id") or group_id or GROUP_CHAT_ID
        await notify_match(
            bot, matched, chat_id=target_chat, nekay_cb=nekay_cb,
            receipt_msg_id=matched.get("receipt_message_id"),
            receipt_chat_id=matched.get("receipt_chat_id"),
        )

    return {
        "success": True,
        "matched": result.get("matched"),
        "amount": amount,
        "sender_name": sender_name,
        "ref": ref,
        "type": sms_type,
    }


# ============================================================
# PAYMENT PHOTO HANDLER
# ============================================================

async def handle_payment_photo(bot, msg, nekay_cb=None, group_id: int = None):
    chat_id = msg.chat.id
    telegram_id = msg.from_user.id
    username = msg.from_user.username or msg.from_user.first_name or "Unknown"
    _group_id = group_id or chat_id

    try:
        photo = msg.photo[-1]
        image_base64 = await download_image_as_base64(photo.file_id)
        receipt_msg = await msg.reply_text("እሺ ቤተሰብ 🙏")
        analysis = await analyze_screenshot(image_base64)

        if not analysis:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=receipt_msg.message_id,
                    text="⚠️ ምስሉ ሊተነተን አልቻለም። ግልጽ screenshot ይላኩ።"
                )
            except Exception:
                pass
            return

        photo_type = analysis.get("photoType", "other")

        if photo_type == "other":
            description = analysis.get("description", "ክፍያ ያልሆነ ምስል")
            try:
                desc = await describe_photo_in_amharic(description)
            except Exception as e:
                logger.warning(f"[Describe] Failed: {e}")
                desc = "ℹ️ ይህ ምስል የክፍያ ደረሰኝ አይደለም።"
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=receipt_msg.message_id, text=desc
                )
            except Exception:
                pass
            return

        amount = analysis.get("amount")
        sender_name = analysis.get("sender_name")
        ref = analysis.get("ref")

        if not amount:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=receipt_msg.message_id,
                    text="⚠️ Amount ሊነበብ አልቻለም። ግልጽ screenshot ይላኩ።"
                )
            except Exception:
                pass
            return

        logger.info(f"[Payment] type={photo_type} | amount={amount} | sender={sender_name} | ref={ref} | user={username} | group={_group_id}")

        settings = get_active_settings(group_id=_group_id)
        game_id = settings["id"] if settings else None

        match = find_matching_sms(
            telegram_id=telegram_id, amount=amount, sender_name=sender_name,
            ref=ref, pay_type=photo_type, group_id=_group_id,
            game_id=game_id,
        )

        if not match:
            save_screenshot_payment(
                telegram_id=telegram_id, amount=amount, sender_name=sender_name,
                ref=ref, pay_type=photo_type,
                description=analysis.get("description", ""), group_id=_group_id,
                game_id=game_id,
                receipt_chat_id=chat_id,
                receipt_message_id=receipt_msg.message_id,
            )
            return

        await notify_match(
            bot,
            {**match, "telegram_id": telegram_id, "group_id": _group_id},
            msg.message_id, _group_id,
            nekay_cb=nekay_cb,
            success_msg=random.choice(PAYMENT_SUCCESS_MESSAGES),
            receipt_msg_id=receipt_msg.message_id,
            receipt_chat_id=chat_id,
        )

        try:
            log_activity(_group_id, payments=1)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"[Payment] Photo handler error: {e}", exc_info=True)
        await msg.reply_text("❌ Error ተፈጥሯል። እንደገና ይምከሩ።")


# ============================================================
# Receipt URL handler
# ============================================================

async def handle_receipt_url(bot, msg, url: str, telegram_id: int, group_id: int, nekay_cb=None):
    chat_id = msg.chat.id
    _group_id = group_id or chat_id

    try:
        receipt_msg = await msg.reply_text("እሺ ቤተሰብ 🙏")

        payment_data = await fetch_payment_data_from_url(url)

        # ባንክ ያልሆነ URL → ዝም በል
        if not payment_data or not payment_data.get("amount"):
            try:
                await bot.delete_message(chat_id=chat_id, message_id=receipt_msg.message_id)
            except Exception:
                pass
            return

        amount = payment_data["amount"]
        sender_name = payment_data.get("sender_name")
        ref = payment_data.get("ref")
        bank = payment_data.get("bank", "Bank")

        logger.info(f"[Receipt URL] bank={bank} | amount={amount} | sender={sender_name} | ref={ref} | group={_group_id}")

        settings = get_active_settings(group_id=_group_id)
        game_id = settings["id"] if settings else None

        match = find_matching_sms(
            telegram_id=telegram_id, amount=amount,
            sender_name=sender_name, ref=ref,
            pay_type=bank, group_id=_group_id,
            game_id=game_id,
        )

        if not match:
            save_screenshot_payment(
                telegram_id=telegram_id, amount=amount,
                sender_name=sender_name, ref=ref,
                pay_type=bank,
                description="Receipt URL: " + url,
                group_id=_group_id,
                game_id=game_id,
            )
            try:
                await bot.delete_message(chat_id=chat_id, message_id=receipt_msg.message_id)
            except Exception:
                pass
            return

        await notify_match(
            bot,
            {**match, "telegram_id": telegram_id, "group_id": _group_id},
            msg.message_id, _group_id,
            nekay_cb=nekay_cb,
            success_msg=random.choice(PAYMENT_SUCCESS_MESSAGES),
            receipt_msg_id=receipt_msg.message_id,
            receipt_chat_id=chat_id,
        )

        try:
            log_activity(_group_id, payments=1)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"[Receipt URL] Error: {e}", exc_info=True)
        await msg.reply_text("❌ Error ተፈጥሯል።")


# ============================================================
# SCREENSHOT ANALYZER — Mistral primary, Gemini fallback (Amharic)
# ============================================================

async def analyze_screenshot(image_base64: str) -> dict:
    prompt = """You are a payment receipt analyzer for Ethiopian banks.

You must recognize ALL Ethiopian bank receipts including but not limited to:
- CBE, Telebirr, Awash, BOA, Dashen, Abay, Nib, Wegagen, United, Lion,
  Oromia, Bunna, Berhan, Coopbank, Enat, Amhara, ZemenBank and any other Ethiopian bank.

RULES:
- If image is ANY Ethiopian bank receipt → extract info, never return "other"
- photoType: use bank name like "CBE", "Telebirr", "Awash", "BOA", "Dashen", etc.
- amount: transferred amount (number only)
- sender_name: name of sender/payer. null if not found.
- ref: transaction ref (Telebirr only). null for others.
- description: brief English description
- lang: is the receipt text in "amharic" or "english"?

CRITICAL:
- ONLY return photoType = "other" if image is clearly NOT a bank receipt

Do NOT explain your reasoning or describe the image in prose. Do NOT include
any text before or after the JSON. Your entire response must be ONLY the
JSON object below, starting with { and ending with }.

{
  "photoType": "<bank name or other>",
  "amount": <number or null>,
  "sender_name": "<name or null>",
  "ref": "<ref or null>",
  "description": "<description>",
  "lang": "amharic" or "english"
}"""

    def _parse(raw: str, label: str) -> dict:
        cleaned = _strip_think_block(raw)
        cleaned = _extract_json_object(cleaned)
        parsed = json.loads(cleaned.strip())
        for field in ("sender_name", "ref"):
            if parsed.get(field) in ("null", "None", "", "N/A"):
                parsed[field] = None
        logger.info(f"[Screenshot] ✅ parsed via {label} | photoType={parsed.get('photoType')} amount={parsed.get('amount')}")
        return parsed

    nvidia_parsed = None
    try:
        text = await _call_nvidia_with_rotation(image_base64, prompt)
        logger.info(f"[Screenshot] Mistral raw response: {text[:300]!r}")
        nvidia_parsed = _parse(text, "Mistral")
    except Exception as e:
        logger.warning(f"[Screenshot] Mistral failed/unparseable: {e}")

    # Use Gemini if Mistral failed outright, OR if Mistral succeeded but flagged Amharic text
    needs_gemini = nvidia_parsed is None or nvidia_parsed.get("lang") == "amharic"

    if needs_gemini:
        try:
            reason = "detected Amharic" if nvidia_parsed else "Mistral failed"
            logger.info(f"[Screenshot] → Gemini fallback ({reason})")
            text2 = await _call_gemini_with_rotation(image_base64, prompt)
            logger.info(f"[Screenshot] Gemini raw response: {text2[:300]!r}")
            return _parse(text2, "Gemini")
        except Exception as e:
            logger.warning(f"[Screenshot] Gemini fallback failed: {e}")
            if nvidia_parsed is not None:
                # Mistral succeeded (even if Amharic) — better than nothing
                return nvidia_parsed

    if nvidia_parsed is not None:
        return nvidia_parsed

    logger.error("[Screenshot] Both Mistral and Gemini failed to produce a parseable result")
    return {"photoType": "other", "amount": None, "sender_name": None, "ref": None, "description": "Could not analyze"}


# ============================================================
# WINNER PHOTO ANALYZER — Mistral primary, Gemini fallback
# ============================================================

async def analyze_winner_photo(image_base64: str, settings: dict) -> dict:
    prize_1st = settings.get("prize_1st", 0)
    prize_2nd = settings.get("prize_2nd")
    prize_3rd = settings.get("prize_3rd")

    prizes_desc = f"1st prize: {prize_1st} ETB"
    if prize_2nd:
        prizes_desc += f", 2nd: {prize_2nd} ETB"
    if prize_3rd:
        prizes_desc += f", 3rd: {prize_3rd} ETB"

    prompt = f"""You are a lottery ticket analyzer for Ethiopian lottery.
Game prizes: {prizes_desc}

A REAL lottery ticket: small physical paper cubes with Amharic series label and numbers.
NOT lottery → return type "other": bank receipts, screenshots, phone screens.

CRITICAL ORDER RULES:
- If numbers arranged VERTICALLY: TOP = 1st, MIDDLE = 2nd, BOTTOM = 3rd
- If numbers arranged HORIZONTALLY: LEFT = 1st, MIDDLE = 2nd, RIGHT = 3rd

CONFIDENCE:
- Rate your confidence in the extracted numbers from 0 to 100.
- 100 = every digit is perfectly clear and unambiguous.
- Lower the score for any blur, glare, unusual angle, partial occlusion,
  or digits that could be confused with another digit (e.g. 6 vs 8, 3 vs 8, 1 vs 7).
- Be honest and self-critical — do not default to a high number.

Do NOT explain your reasoning or describe the image in prose. Do NOT include
any text before or after the JSON. Your entire response must be ONLY the
JSON object below, starting with {{ and ending with }}.

{{
  "type": "lottery" or "other",
  "first": <top number as integer or null>,
  "second": <middle number as integer or null>,
  "third": <bottom number as integer or null>,
  "confidence": <integer 0-100>
}}"""

    providers = [
        ("Mistral", _call_nvidia_with_rotation),
        ("Gemini", _call_gemini_with_rotation),
        ("Groq", _call_groq_vision_with_rotation),
    ]

    async def _try_provider(provider_name: str, call_fn) -> Optional[dict]:
        """Call one provider and parse its response. Returns a dict with
        keys {result, confidence, raw_parsed} on success, or None on any failure."""
        try:
            text = await call_fn(image_base64, prompt)
        except Exception as e:
            logger.warning(f"[Winner] {provider_name} call failed: {e}")
            return None

        try:
            cleaned = _strip_think_block(text)
            cleaned = _extract_json_object(cleaned)
            parsed = json.loads(cleaned.strip())
        except Exception as e:
            logger.warning(f"[Winner] {provider_name} returned unparseable JSON ({e})")
            return None

        logger.info(f"[Winner] {provider_name} parsed: {parsed}")

        if parsed.get("type") != "lottery":
            return {"result": None, "confidence": 100, "not_lottery": True}

        result = {}
        if parsed.get("first") is not None:
            result[1] = int(parsed["first"])
        if parsed.get("second") is not None:
            result[2] = int(parsed["second"])
        if parsed.get("third") is not None:
            result[3] = int(parsed["third"])
        if not result:
            return None

        try:
            confidence = int(parsed.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0
        return {"result": result, "confidence": confidence, "not_lottery": False}

    for i, (provider_name, call_fn) in enumerate(providers):
        outcome = await _try_provider(provider_name, call_fn)
        if outcome is None:
            continue  # this provider failed entirely — try the next one

        if outcome["not_lottery"]:
            return None  # valid classification (not a lottery photo)

        if outcome["confidence"] >= WINNER_CONFIDENCE_THRESHOLD:
            logger.info(f"[Winner] ✅ Analyzed via {provider_name} (confidence={outcome['confidence']}) | result={outcome['result']}")
            return outcome["result"]

        # Low confidence — get a second opinion from the remaining providers
        logger.info(f"[Winner] {provider_name} confidence={outcome['confidence']} < {WINNER_CONFIDENCE_THRESHOLD} — seeking a second opinion")
        for confirm_name, confirm_fn in providers[i + 1:]:
            confirm_outcome = await _try_provider(confirm_name, confirm_fn)
            if confirm_outcome is None or confirm_outcome["not_lottery"]:
                continue  # couldn't get a usable second opinion from this one — try the next
            if confirm_outcome["result"] == outcome["result"]:
                logger.info(f"[Winner] ✅ Confirmed by {confirm_name} | result={outcome['result']}")
                return outcome["result"]
            else:
                logger.warning(
                    f"[Winner] ⚠️ Disagreement: {provider_name}={outcome['result']} vs "
                    f"{confirm_name}={confirm_outcome['result']} — trusting {confirm_name}'s reading"
                )
                return confirm_outcome["result"]

        # No other provider could confirm or deny — fall back to the low-confidence result
        logger.warning(f"[Winner] Could not get a second opinion — using {provider_name}'s low-confidence result: {outcome['result']}")
        return outcome["result"]

    logger.error("[Winner] All providers (Mistral, Gemini, Groq) failed to produce a parseable result")
    return None


# ============================================================
# WINNER PHOTO HANDLER
# ============================================================

async def handle_winner_photo(bot, msg, settings: dict, group_id: int = None) -> bool:
    try:
        photo = msg.photo[-1]
        image_base64 = await download_image_as_base64(photo.file_id)

        winners = await analyze_winner_photo(image_base64, settings)
        if not winners:
            # Not a winner-ticket photo (or couldn't be read) — admin photos
            # aren't always meant to be winner results, so no text message.
            # Just leave a quiet 🔥 reaction on the photo so the admin can
            # notice at a glance if it *was* meant to be a winner photo.
            try:
                await bot.set_message_reaction(chat_id=msg.chat.id, message_id=msg.message_id, reaction=["🔥"])
            except Exception as e:
                logger.warning(f"[Winner] Could not set reaction: {e}")
            return False

        prize_map = {
            1: settings.get("prize_1st", 0),
            2: settings.get("prize_2nd"),
            3: settings.get("prize_3rd"),
        }
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        per_person = settings.get("numbers_per_person", 1)
        lines = ["🏆 Winners!\n"]
        _group_id = group_id or settings.get("group_id")

        for place in sorted(winners.keys()):
            number = winners[place]
            prize = prize_map.get(place)
            medal = medals.get(place, "🎖️")

            if not prize:
                lines.append(f"{medal} {place}ኛ: #{number} — prize አልተቀመጠም")
                continue

            if per_person > 1:
                from board import get_group_start
                lookup_number = get_group_start(number, per_person)
            else:
                lookup_number = number

            users = get_users_by_number(settings["id"], lookup_number)

            if not users:
                lines.append(f"{medal} {place}ኛ: #{number} — user አልተገኘም")
                continue

            split_prize = round(prize / len(users), 2)

            winner_parts = []
            for u in users:
                telegram_id = u["telegram_id"]
                user_name = u["user_name"]
                is_half = u["is_half"]

                add_winner_balance(settings["id"], telegram_id, split_prize, group_id=_group_id)
                save_winner(
                    settings["id"], place, telegram_id, user_name,
                    number, split_prize, group_id=_group_id
                )

                half_label = " (በግማሽ)" if is_half else ""
                winner_parts.append(f"{user_name}{half_label} → ETB {split_prize} ✅")

                try:
                    from ai_fallback import log_transaction
                    if _group_id:
                        log_transaction(
                            group_id=_group_id, game_id=settings["id"],
                            telegram_id=telegram_id, amount=split_prize,
                            reason="winner_prize", number=number,
                            done_by="system", balance_after=split_prize,
                        )
                except Exception as _log_err:
                    logger.warning(f"[log_transaction] Error: {_log_err}")

            if len(users) == 1:
                lines.append(f"{medal} {place}ኛ: #{number} — {winner_parts[0]}")
            else:
                lines.append(f"{medal} {place}ኛ: #{number} (prize ÷ {len(users)})")
                for part in winner_parts:
                    lines.append(f"   • {part}")

        announcement = "\n".join(lines)
        await msg.reply_text(announcement)

        return True

    except Exception as e:
        logger.error(f"[Winner] Handler error: {e}", exc_info=True)
        await msg.reply_text("❌ Error ተፈጥሯል።")
        return False


# ============================================================
# MATCH NOTIFICATION
# ============================================================

async def notify_match(bot, match_data: dict, reply_msg_id=None, chat_id=None, nekay_cb=None, success_msg: str = None, receipt_msg_id: int = None, receipt_chat_id: int = None):
    from board import build_board

    telegram_id = match_data["telegram_id"]
    amount = match_data["amount"]
    _group_id = match_data.get("group_id") or chat_id or GROUP_CHAT_ID

    result = confirm_payment(telegram_id, amount, group_id=_group_id)
    confirmed = result["confirmed"]
    remaining_balance = result["remaining_balance"]

    logger.info(f"[Match] ✅ TelegramID: {telegram_id} | ETB {amount} | confirmed: {len(confirmed)}")

    target_chat = _group_id

    if confirmed:
        final_msg = success_msg or random.choice(PAYMENT_SUCCESS_MESSAGES)
        if receipt_msg_id and receipt_chat_id:
            try:
                await bot.delete_message(chat_id=receipt_chat_id, message_id=receipt_msg_id)
            except Exception:
                pass
        if target_chat:
            if reply_msg_id:
                await bot.send_message(chat_id=target_chat, text=final_msg, reply_to_message_id=reply_msg_id)
            else:
                await bot.send_message(chat_id=target_chat, text=final_msg)
    else:
        settings_check = get_active_settings(group_id=_group_id)
        needed_msg = ""
        if settings_check:
            price_full = float(settings_check.get("price_full") or 0)
            price_half = float(settings_check.get("price_half") or 0)
            if remaining_balance < price_half and price_half > 0:
                short = price_half - remaining_balance
                needed_msg = f"\n⚠️ ቀሪ: ETB {short:.0f} ይላኩ (ለግማሽ)"
            elif remaining_balance < price_full:
                short = price_full - remaining_balance
                needed_msg = f"\n⚠️ ቀሪ: ETB {short:.0f} ይላኩ (ለሙሉ)"

        message = (
            f"💰 ETB {amount} ደረሰ።\n"
            f"💳 ባላንስ: ETB {remaining_balance}"
            + needed_msg
        )
        if receipt_msg_id and receipt_chat_id:
            try:
                await bot.edit_message_text(
                    chat_id=receipt_chat_id, message_id=receipt_msg_id, text=message
                )
            except Exception:
                try:
                    await bot.delete_message(chat_id=receipt_chat_id, message_id=receipt_msg_id)
                except Exception:
                    pass
                if target_chat:
                    if reply_msg_id:
                        await bot.send_message(chat_id=target_chat, text=message, reply_to_message_id=reply_msg_id)
                    else:
                        await bot.send_message(chat_id=target_chat, text=message)
        elif target_chat:
            if reply_msg_id:
                await bot.send_message(chat_id=target_chat, text=message, reply_to_message_id=reply_msg_id)
            else:
                await bot.send_message(chat_id=target_chat, text=message)

    if nekay_cb and confirmed:
        await nekay_cb(confirmed)

    try:
        from ai_fallback import log_transaction
        if confirmed and _group_id:
            settings_log = get_active_settings(group_id=_group_id)
            if settings_log:
                game_id_log = settings_log["id"]
                price_full_log = float(settings_log.get("price_full") or 0)
                price_half_log = float(settings_log.get("price_half") or 0)
                log_transaction(
                    group_id=_group_id, game_id=game_id_log,
                    telegram_id=telegram_id, amount=amount,
                    reason="payment_confirmed", done_by="user",
                    balance_after=remaining_balance,
                )
                for c in confirmed:
                    cost = price_half_log if c["is_half"] else price_full_log
                    reason = f"number_registered_{'half' if c['is_half'] else 'full'}"
                    log_transaction(
                        group_id=_group_id, game_id=game_id_log,
                        telegram_id=telegram_id, amount=-cost,
                        reason=reason, number=c["number"],
                        done_by="user", balance_after=remaining_balance,
                    )
    except Exception as _log_err:
        logger.warning(f"[log_transaction] Error: {_log_err}")

    if confirmed and target_chat:
        settings = get_active_settings(group_id=_group_id)
        if settings:
            game_id = settings["id"]
            taken = get_taken_numbers(game_id)
            paid = get_paid_numbers(game_id)
            board_text = build_board(settings, taken, paid)
            board_msg_id = settings.get("board_message_id")

            if board_msg_id:
                try:
                    await bot.edit_message_text(
                        chat_id=target_chat,
                        message_id=board_msg_id,
                        text=board_text
                    )
                except Exception:
                    new_msg = await bot.send_message(chat_id=target_chat, text=board_text)
                    from database import update_board_message_id
                    update_board_message_id(game_id, new_msg.message_id)


# ============================================================
# GROQ — አማርኛ ማብራሪያ
# ============================================================

async def describe_photo_in_amharic(description: str) -> str:
    try:
        messages = [{
            "role": "user",
            "content": (
                f'ይህ ምስል "{description}" ነው። '
                "በአማርኛ በ2-3 emoji ተጠቅሞ ምስሉ ምን እንደሆነ ብቻ አስረዳ። አጭር ሁን።"
            ),
        }]
        return await _call_groq_with_rotation(messages, max_tokens=100)
    except Exception as e:
        logger.error(f"[Describe] Error: {e}")
        return "ℹ️ ይህ ምስል የክፍያ ደረሰኝ አይደለም።"


# ============================================================
# WINNER CORRECTION (admin replies to a winner announcement with
# "#/ 10 20 31" to fix a misread number). Self-contained addition —
# does not touch any existing handler. Wiring into bot.py (detecting
# the reply + fetching `previous_winners` from the DB) comes next.
# ============================================================

WINNER_CORRECTION_RE = re.compile(r"^\s*#/\s*(\d+)(?:\s+(\d+))?(?:\s+(\d+))?\s*$")


def parse_winner_correction(text: str) -> Optional[list]:
    """Parse an admin correction command like '#/ 10 20 31'.
    Supports 1, 2, or 3 numbers depending on how many prize places the game has:
      '#/ 6'          -> only 1st place (single-winner game)
      '#/ 10 20'      -> 1st + 2nd
      '#/ 10 20 31'   -> 1st + 2nd + 3rd
    Returns a list of numbers in place order (index 0 = 1st place), or None
    if the text doesn't match the command format at all.
    """
    if not text:
        return None
    m = WINNER_CORRECTION_RE.match(text.strip())
    if not m:
        return None
    numbers = [int(g) for g in m.groups() if g is not None]
    return numbers if numbers else None


async def handle_winner_correction(bot, msg, previous_winners: list, settings: dict, group_id: int = None) -> bool:
    """Handle an admin reply-correction to a winner announcement.

    previous_winners: list of dicts describing what was previously paid out
    for this announcement, one entry per place that had a winner, e.g.:
        [
          {"place": 1, "number": 9,  "users": [
              {"telegram_id": 123, "user_name": "Abebe", "split_prize": 400.0}
          ]},
          {"place": 2, "number": 35, "users": [...]},
        ]
    The caller (bot.py) is responsible for fetching this from the database
    BEFORE calling this function, and for confirming the sender is an admin
    and is replying to a bot winner-announcement message.

    ⚠️ REQUIRES two new database.py helpers that don't exist yet — add these
    when database.py is shared:
      - reverse_winner_balance(game_id, telegram_id, amount, group_id=None)
            → subtracts `amount` from the user's balance (undo a wrong payout)
      - delete_winner(game_id, place, group_id=None)
            → removes the old winner record(s) for that place
    """
    from database import reverse_winner_balance, delete_winner  # new helpers — see note above

    numbers = parse_winner_correction(getattr(msg, "text", None) or getattr(msg, "caption", None) or "")
    if not numbers:
        return False  # not a correction command — caller should fall through to normal handling

    chat_id = msg.chat.id
    _group_id = group_id or chat_id
    game_id = settings["id"]

    prize_map = {
        1: settings.get("prize_1st", 0),
        2: settings.get("prize_2nd"),
        3: settings.get("prize_3rd"),
    }
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    per_person = settings.get("numbers_per_person", 1)

    prev_by_place = {w["place"]: w for w in (previous_winners or [])}
    lines = ["🏆 Winners (ተስተካክሏል)!\n"]

    for place, new_number in enumerate(numbers, start=1):
        prize = prize_map.get(place)
        medal = medals.get(place, "🎖️")

        # 1) Reverse whatever was previously (incorrectly) paid for this place
        old = prev_by_place.get(place)
        if old:
            for u in old.get("users", []):
                try:
                    reverse_winner_balance(game_id, u["telegram_id"], u["split_prize"], group_id=_group_id)
                    logger.info(f"[Correction] ↩️ Reversed ETB {u['split_prize']} from {u.get('user_name')} (place {place})")
                except Exception as e:
                    logger.error(f"[Correction] Failed to reverse balance for {u.get('telegram_id')}: {e}")
            try:
                delete_winner(game_id, place, group_id=_group_id)
            except Exception as e:
                logger.warning(f"[Correction] delete_winner failed for place {place}: {e}")

        # 2) Pay the corrected number — only if a real owner is found
        if not prize:
            lines.append(f"{medal} {place}ኛ: #{new_number} — prize አልተቀመጠም")
            continue

        if per_person > 1:
            from board import get_group_start
            lookup_number = get_group_start(new_number, per_person)
        else:
            lookup_number = new_number

        users = get_users_by_number(game_id, lookup_number)

        if not users:
            lines.append(f"{medal} {place}ኛ: #{new_number} — user አልተገኘም (ምንም አልተከፈለም)")
            continue

        split_prize = round(prize / len(users), 2)
        winner_parts = []

        for u in users:
            telegram_id = u["telegram_id"]
            user_name = u["user_name"]
            is_half = u["is_half"]

            add_winner_balance(game_id, telegram_id, split_prize, group_id=_group_id)
            save_winner(game_id, place, telegram_id, user_name, new_number, split_prize, group_id=_group_id)

            half_label = " (በግማሽ)" if is_half else ""
            winner_parts.append(f"{user_name}{half_label} → ETB {split_prize} ✅")

            try:
                from ai_fallback import log_transaction
                if _group_id:
                    log_transaction(
                        group_id=_group_id, game_id=game_id,
                        telegram_id=telegram_id, amount=split_prize,
                        reason="winner_prize_correction", number=new_number,
                        done_by="admin", balance_after=split_prize,
                    )
            except Exception as _log_err:
                logger.warning(f"[log_transaction] Error: {_log_err}")

        if len(users) == 1:
            lines.append(f"{medal} {place}ኛ: #{new_number} — {winner_parts[0]}")
        else:
            lines.append(f"{medal} {place}ኛ: #{new_number} (prize ÷ {len(users)})")
            for part in winner_parts:
                lines.append(f"   • {part}")

    announcement = "\n".join(lines)

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg.reply_to_message.message_id,
            text=announcement,
        )
    except Exception as e:
        logger.warning(f"[Correction] Could not edit original announcement, sending new message: {e}")
        await bot.send_message(chat_id=_group_id, text=announcement)

    return True


# ============================================================
# HELPERS
# ============================================================

async def download_image_as_base64(file_id: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        get_file_res = await client.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
            params={"file_id": file_id}
        )
        get_file_res.raise_for_status()
        file_path = get_file_res.json()["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        res = await client.get(file_url)
        res.raise_for_status()
        return base64.b64encode(res.content).decode("utf-8")
