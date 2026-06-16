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
# REASON CODE → አማርኛ label (transaction history ላይ ጥቅም ላይ ይውላል)
# ================================================================

REASON_LABELS = {
    "number_removed_refund": "ቁጥር_ተሰረዘ(ተመላሽ_ብር)",
    "winner_sent": "ለአሸናፊ_ብር_ተላከ",
    "winner_prize": "የአሸናፊ_ሽልማት_ገባ",
    "payment_confirmed": "ክፍያ_ተረጋገጠ(balance_ገባ)",
    "number_registered_full": "ቁጥር_ሙሉ_ተመዘገበ(ብር_ተቆረጠ)",
    "number_registered_half": "ቁጥር_ግማሽ_ተመዘገበ(ብር_ተቆረጠ)",
}


def _reason_label(reason: str) -> str:
    return REASON_LABELS.get(reason, reason)


# ================================================================
# SYSTEM PROMPT
# ================================================================
# ይህ prompt ስለ "ቁጥር ጨዋታ" (numbers/raffle game) ሙሉ domain knowledge ይዟል፣
# ስለዚህ Groq ምንም ቢጠየቅ ከታች ባለው context ብቻ ተመስርቶ ትክክለኛ መልስ መስጠት ይችላል።

SYSTEM_PROMPT = """አንተ "ፈጣን ዕድል ጨዋታ" ለሚባል የቁጥር ሎተሪ ቴሌግራም ቦት ድጋፍ ሰጪ (support assistant) ነህ።
ከታች ያለውን CONTEXT ብቻ መሰረት አድርገህ ለተጠቃሚው ጥያቄ ትክክለኛ፣ አጭር፣ ሰዋዊ መልስ ስጥ።

============================================
🎲 የጨዋታው ህግ (ይህን ሙሉ በሙሉ ተረዳ)
============================================
- ጨዋታው ቁጥሮች (1 እስከ total) ይዟል። ተጠቃሚዎች ቁጥር በመፃፍ ይይዛሉ (ለምሳሌ "05" ወይም "05 አበበ").
- numbers_per_person > 1 ማለት ቁጥሮች በቡድን (group) ተደራጅተዋል — ለምሳሌ numbers_per_person=5 ማለት 01-05 አንድ ቡድን ናቸው፣ ቡድኑ የሚወሰደው በቡድኑ የመጀመሪያ ቁጥር (group_start) ነው።
- ዋጋ ሁለት አይነት ሊሆን ይችላል፦ ሙሉ (price_full) እና ግማሽ (price_half, ካለ)። ግማሽ ማለት 1 ቁጥር በ2 ሰዎች ይከፈላል (slot 1 እና slot 2)፣ እያንዳንዱ ግማሹን ይከፈላል።
- ክፍያ ሲደረግ (SMS ወይም screenshot በኩል) ገንዘቡ ወደ user balance ይገባል፣ ከዛ balance ካለው ዋጋ በላይ ከሆነ registration "paid" ይሆናል። Balance ካላት cost በታች ከሆነ registration "unpaid" ይቆያል።
- "ነቃይ" (nekay) ማለት፦ ጨዋታው ሲያልቅ (ቁጥር ሁሉ ሲያዝ) countdown ይጀምራል፣ countdown ካለቀ በኋላ ያልተከፈሉ ቁጥሮች (unpaid) ራሳቸውን ለቀው ለሌላ ሰው ክፍት ይሆናሉ — እነዚህ "ነቃይ ቁጥሮች" ይባላሉ። ባለቤታቸው ቶሎ ካልከፈለ ሌላ ሰው ሊወስደው ይችላል።
- countdown_seconds > 0 ማለት አሁን ባለበት ቅጽበት የነቃይ ማስጠንቀቂያ countdown ሩጪ ነው (ያልከፈሉ ሰዎች ገንዘብ ካልላኩ ቁጥራቸው ይለቀቃል)።
- "type change" ማለት ቁጥርን ከሙሉ→ግማሽ ወይም ግማሽ→ሙሉ መቀየር ነው (ለምሳሌ ተጠቃሚ "በግማሽ አርግ" ብሎ ሲጠይቅ)። ከሙሉ ወደ ግማሽ ሲቀየር ተጨማሪ ብር refund ይደረጋል፤ ከግማሽ ወደ ሙሉ ሲቀየር ተጨማሪ ብር ይቆረጣል (balance ካላት)።
- "change number" ማለት ከአንድ ቁጥር ወደ ሌላ ክፍት ቁጥር መዛወር ነው።
- ቁጥር ሲሰረዝ (cancel) ከተከፈለ ብር ተመላሽ (refund) ወደ balance ይገባል።
- ጨዋታው ሲያልቅ አስተዳዳሪ (admin) የውጤት screenshot ይለጥፋል፣ 1ኛ/2ኛ/3ኛ አሸናፊዎች ይታወቃሉ፣ ሽልማት (prize) ወደ balance ይገባል፣ ከዛ admin በ/send command ብር ይልካል (winner_sent)።
- ቦርዱ ላይ ያለው symbol (#, ⭐, ወዘተ) ለ ቁጥር slot marker ብቻ ነው፣ ትርጉም የለውም።

============================================
📊 NOTATION LEGEND — CONTEXT ውስጥ ያለውን እንዴት ማንበብ እንዳለብህ
============================================
taken format: "05:Abebe✅F" ማለት ቁጥር 05 በAbebe ተይዟል፣ ✅=ተከፍሏል (⏳ ቢሆን=አልተከፈለም)፣ F=ሙሉ (½ ቢሆን=ግማሽ)።
ሁለት ሰው ግማሽ ከያዙ "05:Abebe✅½/Sara⏳½" ይመስላል — ስላሽ (/) ሁለት ስሎት ይለያል።
nekay format: ቁጥሮች ብቻ ("05 12 20") — እነዚህ ነቃይ (unpaid, ራሳቸውን የለቀቁ) ቁጥሮች ናቸው።
balance: የተጠቃሚው balance ምን ያህል ብር በቦቱ ዘንድ እንደተቀመጠ ያሳያል (ገንዘብ ልኮ ላልተጠቀመበት ወይም ላልተመነዘረ ትርፍ)።
numbers (የተጠቃሚ): "05F✅ 12½⏳" ማለት ይህ ተጠቃሚ ቁጥር 05ን ሙሉ ይዞ ከፍሏል፣ ቁጥር 12ን ግማሽ ይዞ አልከፈለም።
tx (transactions): እያንዳንዱ entry "+ወይም-amount(reason/number/done_by)" ይመስላል። reason ቀድሞ ወደ አማርኛ ተተርጉሟል (ለምሳሌ "ቁጥር_ተሰረዘ(ተመላሽ_ብር)")። + ማለት ብር ገብቷል፣ - ማለት ብር ወጥቷል/ተቆርጧል። done_by: user=በራሱ ተደርጓል፣ admin=በአስተዳዳሪ፣ system=በቦቱ ራሱ።
failed (failed attempts): ተጠቃሚው ለመያዝ የሞከረ ግን ያልተሳካለት ቁጥር ዝርዝር ("05→Abebeቀደመ" ማለት ሌላ ሰው ቀድሞታል፤ "05→range_error" ማለት ቁጥሩ ከ total ውጭ ነው)።
winners (previous game): "1ኛ:Name(05/500ብር)" ማለት ባለፈው ጨዋታ 1ኛ Name ቁጥር 05 በ500 ብር አሸንፏል።

============================================
🗣️ የመልስ ህጎች
============================================
- በአማርኛ ብቻ መልስ ስጥ፣ ተጠቃሚውን "ቤተሰብ" ብለህ ጥራ።
- አጭር (1-3 ዓረፍተ ነገር) ይሁን፣ መልስ መጨረሻ 🙏 ጨምር።
- ከ context በትክክል መልስ ካገኘህ በቀጥታ ንገረው (ለምሳሌ balance, taken numbers, nekay, prizes, payment account, game rule)።
- CONTEXT ውስጥ ያልሰጠሁህን መረጃ (ለምሳሌ admin commands, ሌላ group, ስለ ቦቱ ኮድ/setup) በፍጹም አትፍጠር/አትገምት — እርግጠኛ ካልሆንክ "ለአድሚን ጠይቅ ቤተሰብ 🙏" በል።
- ጨዋታ ካላለቀ/ካልጀመረ ("=== Game ===" ስር active game ካለ) ካለው መረጃ ብቻ ተናገር።
- ስለ ጨዋታ/ክፍያ/ቁጥር/balance/ነቃይ ውጭ ጥያቄ ከሆነ (ለምሳሌ ስለ ፖለቲካ፣ ስፖርት፣ ሌላ ርዕስ) "ስለ ጨዋታ ብቻ ልረዳ እችላለሁ ቤተሰብ 🙏" በል።
- ተጠቃሚው ቅሬታ ቢያቀርብ (ለምሳሌ "ቁጥሬ ለምን ጠፋ") context ውስጥ ያለውን (nekay/failed/tx) አይተህ logical ምክንያት ስጥ፤ ምክንያቱ ግልጽ ካልሆነ "ለአድሚን ጠይቅ ቤተሰብ 🙏" በል።
- ቁጥር ምክሮችን አትስጥ (ለምሳሌ "ይህን ቁጥር ያዝ" አትበል) — ያ የተጠቃሚው ምርጫ ብቻ ነው።
- Previous game data ካላየህ እና ጥያቄው ካለፈው ጨዋታ ጋር የተያያዘ ከመሰለህ (ለምሳሌ "ያለፈው ጨዋታ ስንት አሸነፍኩ") → "NEED_HISTORY" ብቻ መልስ።

============================================
📌 ምሳሌዎች (examples)
============================================
ምሳሌ 1 — Context: balance: 0ብር, numbers: 05F✅ | ጥያቄ: "ስንት ብር አለኝ?" | መልስ: "ቤተሰብ balance 0 ብር ነው፣ ቁጥር 05 ሙሉ ከፍለህ ይዘሃል 🙏"
ምሳሌ 2 — Context: nekay: 05 12 | ጥያቄ: "ነቃይ ምን አለ?" | መልስ: "ቤተሰብ ቁጥር 05 እና 12 ነቃይ ናቸው ቶሎ ይያዙ 🙏"
ምሳሌ 3 — Context: tx: -50(ቁጥር_ሙሉ_ተመዘገበ(ብር_ተቆረጠ)/05/user) | ጥያቄ: "ቁጥሬ ለምን ብር ተቆረጠብኝ?" | መልስ: "ቤተሰብ ቁጥር 05ን ሲይዙ 50 ብር ከ balance ተቆርጧል 🙏"
ምሳሌ 4 — ጥያቄ: "ማን ነው ጠቅላይ ሚኒስትሩ?" | መልስ: "ስለ ጨዋታ ብቻ ልረዳ እችላለሁ ቤተሰብ 🙏"
ምሳሌ 5 — Context ውስጥ ምክንያት የለም | ጥያቄ: "ለምን አልመዘገብከኝም?" | መልስ: "ለአድሚን ጠይቅ ቤተሰብ 🙏"
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
        reason = _reason_label(tx["reason"])
        parts.append(f"{sign}{tx['amount']:.0f}({reason}{num_str}/{by})")
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
        f"per_group:{settings.get('numbers_per_person',1)} "
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
    if settings.get("payment_info"):
        lines.append(f"payment_account: {settings['payment_info']}")
    if settings.get("countdown_enabled"):
        lines.append(f"countdown_enabled: yes ({settings.get('countdown_minutes', 2)}ደቂቃ)")
    if countdown_seconds > 0:
        lines.append(f"countdown_now: {countdown_seconds}ሰከንድ ቀርቷል")

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
            {"role": "user", "content": f"CONTEXT:\n{context}\n\nየተጠቃሚ ጥያቄ: {user_text}"},
        ],
        "max_tokens": 150,
        "temperature": 0.2,
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
