"""
jina_brain.py
=============
Jina embedding fallback brain ለ responder.py intent detection።
TF-IDF score ዝቅ ሲሆን (< 0.40) ብቻ ይጠራል።
Multi-key rotation ይደግፋል — config.py ውስጥ ካለው JINA_API_KEYS ይጠቀማል።

Setup:
    pip install httpx

.env ውስጥ ጨምር:
    JINA_API_KEY_1=jina_xxxxxxxxxxxx
    JINA_API_KEY_2=jina_xxxxxxxxxxxx   ← optional
    ...እስከ 10
"""

import math
import logging

import httpx

logger = logging.getLogger(__name__)

# ================================================================
# CONFIG
# ================================================================

JINA_MODEL = "jina-embeddings-v3"
JINA_URL   = "https://api.jina.ai/v1/embeddings"
JINA_TASK  = "text-matching"

# TF-IDF score ከዚህ በታች ሲሆን ብቻ Jina ይጠራል
JINA_FALLBACK_THRESHOLD = 0.40

# Jina minimum similarity score — ከዚህ በታች ከሆነ "unknown" ይመልሳል
JINA_MIN_SCORE = 0.45

# ================================================================
# KEY ROTATION — payment.py ያለውን style ይጠቀማል
# ================================================================

_jina_keys: list[str] = []
_jina_index = 0

def _next_key() -> str:
    """Round-robin ሆኖ ቀጣዩን key ይመልሳል — payment.py style።"""
    global _jina_index
    if not _jina_keys:
        raise RuntimeError("Jina brain not initialized — await init_jina_brain() first")
    key = _jina_keys[_jina_index]
    _jina_index = (_jina_index + 1) % len(_jina_keys)
    return key

# ================================================================
# IN-MEMORY STORE
# ================================================================

_intent_embeddings: dict[str, list[list[float]]] = {}
_is_ready = False

# ================================================================
# COSINE SIMILARITY
# ================================================================

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

# ================================================================
# JINA API CALL — ASYNC (httpx)
# ================================================================

async def _get_embeddings_async(texts: list[str]) -> list[list[float]]:
    """
    Jina API ን ጠርቶ embeddings ያመጣል።
    Key rotation ተጠቅሞ ይጠራል — rate limit ሲደርስ ቀጣዩ key ይጠቀማል።
    """
    api_key = _next_key()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": JINA_MODEL,
        "input": texts,
        "task": JINA_TASK,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(JINA_URL, json=payload, headers=headers)

        # Rate limit ሲደርስ ቀጣዩ key ሞክር
        if resp.status_code == 429:
            logger.warning("⚠️  Jina rate limit — rotating key...")
            api_key = _next_key()
            headers["Authorization"] = f"Bearer {api_key}"
            resp = await client.post(JINA_URL, json=payload, headers=headers)

        resp.raise_for_status()
        data = resp.json()

    items = sorted(data["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in items]

# ================================================================
# INITIALIZE — bot start ላይ አንድ ጊዜ ብቻ ይጠራል
# ================================================================

async def init_jina_brain(intent_examples: dict, api_keys: list[str]) -> bool:
    """
    INTENT_EXAMPLES ን ተጠቅሞ embeddings ይሠራል።
    Bot start ላይ አንድ ጊዜ ብቻ ይጠራ።

    Usage (bot.py ወይም main.py ውስጥ):
        from jina_brain import init_jina_brain
        from responder import INTENT_EXAMPLES
        from config import JINA_API_KEYS
        await init_jina_brain(INTENT_EXAMPLES, JINA_API_KEYS)
    """
    global _intent_embeddings, _is_ready, _jina_keys, _jina_index

    if not api_keys:
        logger.warning("⚠️  JINA_API_KEYS የለም — Jina brain disabled")
        return False

    _jina_keys = api_keys
    _jina_index = 0
    logger.info(f"🔑 Jina keys loaded: {len(api_keys)} key(s)")
    logger.info("🧠 Jina brain initializing...")

    try:
        for intent, examples in intent_examples.items():
            if not examples:
                continue

            embeddings = await _get_embeddings_async(examples)
            _intent_embeddings[intent] = embeddings
            logger.info(f"  ✅ {intent}: {len(embeddings)} examples embedded")

        _is_ready = True
        total = sum(len(v) for v in _intent_embeddings.values())
        logger.info(f"🎉 Jina brain ready — {len(_intent_embeddings)} intents, {total} embeddings")
        return True

    except Exception as e:
        logger.error(f"❌ Jina brain init failed: {e}")
        _is_ready = False
        return False

# ================================================================
# DETECT INTENT VIA JINA — ASYNC
# ================================================================

async def jina_detect_intent(text: str) -> tuple[str, float]:
    """
    Jina embedding ተጠቅሞ intent ይመርጣል።
    Returns: (intent, score)

    ከ responder.py detect_intent() ጋር እንዴት ያጣምሩታል:
        intent, score = detect_intent(text)
        if score < 0.40 and jina_is_ready():
            intent, score = await jina_detect_intent(text)
    """
    if not _is_ready or not _intent_embeddings:
        return "unknown", 0.0

    try:
        query_emb = (await _get_embeddings_async([text]))[0]

        best_intent = "unknown"
        best_score  = 0.0

        for intent, embeddings in _intent_embeddings.items():
            intent_score = max(_cosine(query_emb, emb) for emb in embeddings)
            if intent_score > best_score:
                best_score  = intent_score
                best_intent = intent

        if best_score < JINA_MIN_SCORE:
            return "unknown", best_score

        return best_intent, best_score

    except Exception as e:
        logger.error(f"❌ Jina detect failed: {e}")
        return "unknown", 0.0


def jina_is_ready() -> bool:
    return _is_ready
