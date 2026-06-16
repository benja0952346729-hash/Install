import os
import logging
import aiohttp
from database import get_conn, get_user_numbers, get_failed_attempts

# ================================================================
# GROQ KEY ROTATION — AI_GROQ_KEY_1 ... AI_GROQ_KEY_15
# ================================================================

_ai_groq_keys = []
for i in range(1, 16):
    key = os.environ.get(f"AI_GROQ_KEY_{i}", "")
    if key:
        _ai_groq_keys.append(key)

_ai_groq_index = 0


def _get_ai_groq_key() -> str:
    global _ai_groq_index
    if not _ai_groq_keys:
        return ""
    key = _ai_groq_keys[_ai_groq_index]
    _ai_groq_index = (_ai_groq_index + 1) % len(_ai_groq_keys)
    return key


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# ================================================================
# SYSTEM PROMPT
# ================================================================

SYSTEM_PROMPT = """አንተ የቁጥር ጨዋታ ቴሌግራም ቦት ነህ። context ሁሉ ተሰጥቶሃል።

== Style ==
- በአማርኛ ብቻ መልስ ስጥ
- ሁሌ "ቤተሰብ" ብለህ ጥራ
- አጭር (1-2 ዓረፍተ ነገር) ብቻ
- መልስ መጨረሻ 🙏 ጨምር
- ቀላልና ሞቅ ያለ ቃና

== የምሳሌ መልሶች ==
- "እሺ ቤተሰብ 🙏"
- "ቤተሰብ ቁጥር 05 ተይዟል 🙏"
- "ቤተሰብ 100 ብር balance አለህ 🙏"
- "ቤተሰብ ቁጥር 10 ጊዜ ስላለፈ ተነቅሏል 🙏"
- "ቤተሰብ ለአድሚን ጠይቅ 🙏"

== አስፈላጊ ህጎች ==
- ያልሰጠሁህን context አትፍጠር
- እርግጠኛ ካልሆንክ "ለአድሚን ጠይቅ ቤተሰብ 🙏" በል
- ስለ ጨዋታ ውጭ ጥያቄ "ስለ ጨዋታ ብቻ ልረዳ እችላለሁ ቤተሰብ 🙏" በል
- Previous game data ካላየህ እና ያስፈልጋል ብትል → "NEED_HISTORY" ብቻ በል
"""

# ================================================================
# COMPRESS HELPERS
# ================================================================

def _compress_taken(taken: dict, paid: dict) -> str:
    if not taken:
        return "none"
    parts = []
    for num in sorted(taken.keys()):
        slots = taken[num]
        slot_parts = []
        for name, is_half, slot in slots:
            is_paid = slot in paid.get(num, set())
            mark = "✅" if is_paid else "⏳"
            t = "½" if is_half else "F"
            slot_parts.append(f"{name}{mark}{t}")
        parts.append(f"{num:02d}:{'/'.join(slot_parts)}")
    return " ".join(parts)


def _compress_nekay(nekay_list: list) -> str:
    if not nekay_list:
        return "none"
    return " ".join(f"{n:02d}" for n, _ in nekay_list)


def _compress_transactions(transactions: list) -> str:
    if not transactions:
        return "none"
    parts = []
    for tx in transactions[-10:]:
        sign = "+" if tx["amount"] >= 0 else ""
        num_str = f"/{tx['number']:02d}" if tx.get("number") else ""
        by = tx.get("done_by", "sys")
        parts.append(f"{sign}{tx['amount']:.0f}({tx['reason']}{num_str}/{by})")
    return " ".join(parts)


# ================================================================
# CONTEXT BUILDERS
# ================================================================

def _get_user_transactions(group_id: int, game_id: int, telegram_id: int,
                            limit: int = 10) -> list:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT amount, reason, number, done_by, balance_after, created_at
            FROM balance_transactions
            WHERE group_id=%s AND game_id=%s AND telegram_id=%s
            ORDER BY created_at DESC LIMIT %s
        """, (group_id, game_id, telegram_id, limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "amount": float(r[0]), "reason": r[1], "number": r[2],
                "done_by": r[3], "balance_after": float(r[4]) if r[4] else None,
            }
            for r in rows
        ][::-1]
    except Exception as e:
        logging.warning(f"[AI] get_user_transactions error: {e}")
        return []


def _get_previous_game_data(group_id: int, current_game_id: int,
                             telegram_id: int) -> dict:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM game_settings
            WHERE group_id=%s AND id < %s
            ORDER BY id DESC LIMIT 1
        """, (group_id, current_game_id))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return {}

        prev_game_id = row[0]

        cur.execute("""
            SELECT place, user_name, number, prize
            FROM winners WHERE game_id=%s ORDER BY place
        """, (prev_game_id,))
        winners = [
            {"place": r[0], "name": r[1], "number": r[2], "prize": float(r[3] or 0)}
            for r in cur.fetchall()
        ]

        cur.execute("""
            SELECT amount, reason, number, done_by, balance_after
            FROM balance_transactions
            WHERE group_id=%s AND game_id=%s AND telegram_id=%s
            ORDER BY created_at DESC LIMIT 10
        """, (group_id, prev_game_id, telegram_id))
        tx_rows = cur.fetchall()
        transactions = [
            {
                "amount": float(r[0]), "reason": r[1], "number": r[2],
                "done_by": r[3], "balance_after": float(r[4]) if r[4] else None,
            }
            for r in tx_rows
        ][::-1]

        cur.close()
        conn.close()
        return {
            "game_id": prev_game_id,
            "winners": winners,
            "user_transactions": transactions,
        }
    except Exception as e:
        logging.warning(f"[AI] get_previous_game_data error: {e}")
        return {}


def _get_user_balance(group_id: int, telegram_id: int) -> float:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT balance FROM user_balance
            WHERE group_id=%s AND telegram_id=%s
        """, (group_id, telegram_id))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return float(row[0]) if row else 0.0
    except Exception as e:
        logging.warning(f"[AI] get_user_balance error: {e}")
        return 0.0


def build_context(
    settings: dict,
    taken: dict,
    paid: dict,
    nekay_list: list,
    remaining_count: int,
    countdown_seconds: int,
    user_id: int,
    game_id: int,
    include_history: bool = False,
) -> str:
    group_id = settings.get("group_id")
    lines = []

    lines.append("=== Game ===")
    lines.append(
        f"full:{settings.get('price_full',0)}ብር "
        f"half:{settings.get('price_half') or 'N/A'}ብር "
        f"total:{settings.get('total_numbers',0)} "
        f"remaining:{remaining_count}"
    )
    prizes = []
    if settings.get("prize_1st"): prizes.append(f"1ኛ:{settings['prize_1st']}")
    if settings.get("prize_2nd"): prizes.append(f"2ኛ:{settings['prize_2nd']}")
    if settings.get("prize_3rd"): prizes.append(f"3ኛ:{settings['prize_3rd']}")
    if prizes:
        lines.append("prize: " + " ".join(prizes))
    if settings.get("game_rule"):
        lines.append(f"rule: {settings['game_rule']}")
    if countdown_seconds > 0:
        lines.append(f"countdown: {countdown_seconds}ሰከንድ ቀርቷል")

    lines.append(f"taken: {_compress_taken(taken, paid)}")

    if nekay_list:
        lines.append(f"nekay: {_compress_nekay(nekay_list)}")

    if user_id and game_id and group_id:
        lines.append("=== User ===")

        try:
            user_nums = get_user_numbers(game_id, user_id)
            if user_nums:
                num_parts = []
                for number, is_half, slot, is_paid in user_nums:
                    t = "½" if is_half else "F"
                    p = "✅" if is_paid else "⏳"
                    num_parts.append(f"{number:02d}{t}{p}")
                lines.append("numbers: " + " ".join(num_parts))
            else:
                lines.append("numbers: none")
        except Exception as e:
            logging.warning(f"[AI] user_numbers error: {e}")

        balance = _get_user_balance(group_id, user_id)
        lines.append(f"balance: {balance}ብር")

        txs = _get_user_transactions(group_id, game_id, user_id)
        if txs:
            lines.append(f"tx: {_compress_transactions(txs)}")

        try:
            attempts = get_failed_attempts(game_id, user_id)
            if attempts:
                fa_parts = []
                for a in attempts[:3]:
                    if a["reason"] == "taken":
                        fa_parts.append(f"{a['number']:02d}→{a['slot1_name']}ቀደመ")
                    elif a["reason"] == "range":
                        fa_parts.append(f"{a['number']:02d}→range_error")
                lines.append("failed: " + " ".join(fa_parts))
        except Exception as e:
            logging.warning(f"[AI] failed_attempts error: {e}")

    if include_history and game_id and group_id and user_id:
        prev = _get_previous_game_data(group_id, game_id, user_id)
        if prev:
            lines.append("=== Previous Game ===")
            if prev.get("winners"):
                w_parts = [
                    f"{w['place']}ኛ:{w['name']}({w['number']:02d}/{w['prize']:.0f}ብር)"
                    for w in prev["winners"]
                ]
                lines.append("winners: " + " ".join(w_parts))
            if prev.get("user_transactions"):
                lines.append(f"user_tx: {_compress_transactions(prev['user_transactions'])}")
        else:
            lines.append("=== Previous Game: none ===")

    return "\n".join(lines)


# ================================================================
# GROQ CALLER
# ================================================================

async def _call_groq(context: str, user_text: str) -> str | None:
    api_key = _get_ai_groq_key()
    if not api_key:
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nጥያቄ: {user_text}"},
        ],
        "max_tokens": 120,
        "temperature": 0.5,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                GROQ_URL, headers=headers, json=payload,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status != 200:
                    logging.warning(f"[AI Groq] status {resp.status}")
                    return None
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip() or None
    except Exception as e:
        logging.warning(f"[AI Groq] Error: {e}")
        return None


# ================================================================
# MAIN ENTRY POINT
# ================================================================

async def get_ai_fallback(
    text: str,
    settings: dict,
    taken: dict,
    paid: dict,
    nekay_list: list,
    remaining_count: int,
    countdown_seconds: int,
    user_id: int = 0,
    game_id: int = 0,
) -> str | None:
    if not _ai_groq_keys:
        return None

    # Step 1 — current game only
    ctx = build_context(
        settings=settings,
        taken=taken,
        paid=paid,
        nekay_list=nekay_list,
        remaining_count=remaining_count,
        countdown_seconds=countdown_seconds,
        user_id=user_id,
        game_id=game_id,
        include_history=False,
    )
    reply = await _call_groq(ctx, text)

    if not reply:
        return None

    # Step 2 — previous game needed?
    if reply.strip() == "NEED_HISTORY":
        ctx2 = build_context(
            settings=settings,
            taken=taken,
            paid=paid,
            nekay_list=nekay_list,
            remaining_count=remaining_count,
            countdown_seconds=countdown_seconds,
            user_id=user_id,
            game_id=game_id,
            include_history=True,
        )
        reply = await _call_groq(ctx2, text)

    return reply


# ================================================================
# TRANSACTION LOGGER
# ================================================================

def log_transaction(
    group_id: int,
    game_id: int,
    telegram_id: int,
    amount: float,
    reason: str,
    number: int = None,
    done_by: str = "system",
    balance_after: float = None,
):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO balance_transactions
            (group_id, game_id, telegram_id, amount, reason, number, done_by, balance_after)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (group_id, game_id, telegram_id, amount, reason, number, done_by, balance_after))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.warning(f"[log_transaction] Error: {e}")
