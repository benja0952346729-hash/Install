"""
jina_brain.py
=============
Jina embedding fallback brain ለ responder.py intent detection።
TF-IDF score ዝቅ ሲሆን (< 0.40) ብቻ ይጠራል።
Multi-key rotation ይደግፋል።
DB caching + hash-based auto re-embed ይደግፋል።

Setup:
    pip install httpx
"""

import math
import hashlib
import json
import logging

import httpx

from database import get_conn

logger = logging.getLogger(__name__)

# ================================================================
# CONFIG
# ================================================================

JINA_MODEL      = "jina-embeddings-v3"
JINA_URL        = "https://api.jina.ai/v1/embeddings"
JINA_TASK       = "text-matching"
JINA_BATCH_SIZE = 500

# TF-IDF score ከዚህ በታች ሲሆን ብቻ Jina ይጠራል
JINA_FALLBACK_THRESHOLD = 0.40

# Jina minimum similarity score
JINA_MIN_SCORE = 0.45

# ================================================================
# KEY ROTATION
# ================================================================

_jina_keys: list[str] = []
_jina_index = 0

def _next_key() -> str:
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
# HASH — INTENT_EXAMPLES ተቀይሯል?
# ================================================================

def _compute_hash(intent_examples: dict) -> str:
    """INTENT_EXAMPLES content hash ይሰራል።"""
    content = json.dumps(intent_examples, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(content.encode("utf-8")).hexdigest()

# ================================================================
# DB — CREATE TABLE
# ================================================================

def _ensure_table():
    """jina_embeddings table ካልሆነ ይፈጥራል።"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS jina_embeddings (
            id SERIAL PRIMARY KEY,
            intent TEXT NOT NULL,
            example_index INTEGER NOT NULL,
            embedding JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(intent, example_index)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS jina_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

# ================================================================
# DB — LOAD / SAVE / CLEAR
# ================================================================

def _load_hash_from_db() -> str | None:
    """DB ላይ የተቀመጠውን hash ያወጣል።"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT value FROM jina_meta WHERE key='intent_hash'")
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logger.warning(f"[JinaBrain] Hash load error: {e}")
        return None

def _save_hash_to_db(hash_str: str):
    """Hash ን DB ላይ ይቀምጣል።"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO jina_meta (key, value, updated_at)
            VALUES ('intent_hash', %s, NOW())
            ON CONFLICT (key) DO UPDATE SET value=%s, updated_at=NOW()
        """, (hash_str, hash_str))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"[JinaBrain] Hash save error: {e}")

def _load_embeddings_from_db(intent_examples: dict) -> dict[str, list[list[float]]] | None:
    """DB ከ embeddings ያወጣል።"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT intent, example_index, embedding
            FROM jina_embeddings
            ORDER BY intent, example_index
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return None

        result = {}
        for intent, idx, emb in rows:
            if intent not in result:
                result[intent] = []
            result[intent].append(emb)

        # ሁሉም intents አሉ?
        for intent in intent_examples:
            if intent not in result:
                return None

        return result
    except Exception as e:
        logger.warning(f"[JinaBrain] Load from DB error: {e}")
        return None

def _save_embeddings_to_db(intent_embeddings: dict[str, list[list[float]]]):
    """Embeddings ን DB ላይ ይቀምጣል።"""
    try:
        conn = get_conn()
        cur = conn.cursor()

        # አስቀድሞ ያሉትን ያጸዳል
        cur.execute("DELETE FROM jina_embeddings")

        for intent, embeddings in intent_embeddings.items():
            for idx, emb in enumerate(embeddings):
                cur.execute("""
                    INSERT INTO jina_embeddings (intent, example_index, embedding)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (intent, example_index) DO UPDATE SET embedding=%s
                """, (intent, idx, json.dumps(emb), json.dumps(emb)))

        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ Embeddings saved to DB")
    except Exception as e:
        logger.warning(f"[JinaBrain] Save to DB error: {e}")

# ================================================================
# JINA API CALL — ASYNC BATCH
# ================================================================

async def _get_embeddings_async(texts: list[str]) -> list[list[float]]:
    """
    Jina API ን ጠርቶ embeddings ያመጣል።
    Key rotation ተጠቅሞ ይጠራል።
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

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(JINA_URL, json=payload, headers=headers)

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
# INITIALIZE
# ================================================================

async def init_jina_brain(intent_examples: dict, api_keys: list[str]) -> bool:
    """
    Bot start ላይ አንድ ጊዜ ብቻ ይጠራ።
    Hash ተቀይሯል? → re-embed። አልተቀየረም? → DB load።
    """
    global _intent_embeddings, _is_ready, _jina_keys, _jina_index

    if not api_keys:
        logger.warning("⚠️  JINA_API_KEYS የለም — Jina brain disabled")
        return False

    _jina_keys = api_keys
    _jina_index = 0
    logger.info(f"🔑 Jina keys loaded: {len(api_keys)} key(s)")

    # Table ይፈጥራል
    _ensure_table()

    # Hash ያወዳድራል
    current_hash = _compute_hash(intent_examples)
    db_hash = _load_hash_from_db()

    if db_hash == current_hash:
        # DB ካ load ያደርጋል
        logger.info("✅ Intent examples unchanged — loading from DB...")
        cached = _load_embeddings_from_db(intent_examples)
        if cached:
            _intent_embeddings = cached
            _is_ready = True
            total = sum(len(v) for v in _intent_embeddings.values())
            import sys
            emb_size = total * 1024 * 4
            logger.info(f"💾 Embedding RAM: ~{emb_size / 1024:.1f} KB ({total} embeddings)")
            logger.info(f"🎉 Jina brain ready (from DB) — {len(_intent_embeddings)} intents, {total} embeddings")
            return True
        else:
            logger.info("⚠️  DB cache incomplete — re-embedding...")

    # Re-embed
    logger.info(f"🧠 Jina brain initializing... embedding {sum(len(v) for v in intent_examples.values())} texts")

    try:
        # ሁሉም texts + intent map
        all_texts = []
        intent_map = []
        for intent, examples in intent_examples.items():
            for ex in examples:
                all_texts.append(ex)
                intent_map.append(intent)

        total_texts = len(all_texts)
        all_embeddings = []
        processed = 0

        # Batch processing
        for i in range(0, total_texts, JINA_BATCH_SIZE):
            batch = all_texts[i:i + JINA_BATCH_SIZE]
            batch_embeddings = await _get_embeddings_async(batch)
            all_embeddings.extend(batch_embeddings)
            processed += len(batch)
            logger.info(f"  📦 {processed}/{total_texts} embedded...")

        # Intent map ላይ ያስቀምጣል
        new_embeddings: dict[str, list[list[float]]] = {}
        for idx, (intent, emb) in enumerate(zip(intent_map, all_embeddings)):
            if intent not in new_embeddings:
                new_embeddings[intent] = []
            new_embeddings[intent].append(emb)

        _intent_embeddings = new_embeddings
        _is_ready = True

        # DB ላይ ይቀምጣል
        _save_embeddings_to_db(_intent_embeddings)
        _save_hash_to_db(current_hash)

        total = sum(len(v) for v in _intent_embeddings.values())
        emb_size = total * 1024 * 4
        logger.info(f"💾 Embedding RAM: ~{emb_size / 1024:.1f} KB ({total} embeddings)")
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
