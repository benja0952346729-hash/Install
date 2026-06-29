"""
userbot2.py — Winner payment auto-listener (Telethon-based) [FIXED]

ፍሰት:
1. Main admin አንድ ጊዜ /setwinnerapi api_id api_hash ያስቀምጣል (ለሁሉም shared)
2. እያንዳንዱ group admin (private chat ላይ):
   /startsession2 +phone   → code ይላካል
   /verifycode2 +phone code → session ይፈጠራል፣ ይቀመጣል፣ listener ራሱ ይነሳል
   (2FA ካለ: /verify2fa2 +phone password)

Payment logic:
- Photo (no caption) + winner (sent ወይም unsent) → AI analyzes screenshot → send, balance ይቀነሳል
- #/300 reply to photo   + sent winner             → correct AI amount → balance adjust
- URL outgoing           + winner (sent ወይም unsent) → fetch amount → send
- Normal chat / not winner                          → ምንም አይሰራም
"""

import asyncio
import logging
import re
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from database import get_conn, deduct_winner_balance, mark_winner_sent

from handlers import (
    analyze_screenshot,
    fetch_payment_data_from_url,
    download_image_as_base64,
)

logger = logging.getLogger(__name__)

# ============================================================
# DB INIT
# ============================================================

def init_userbot2_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        ALTER TABLE group_admins ADD COLUMN IF NOT EXISTS session_string TEXT;
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS winner_api_config (
            id INT PRIMARY KEY DEFAULT 1,
            api_id BIGINT NOT NULL,
            api_hash TEXT NOT NULL,
            CHECK (id = 1)
        )
    """)
    # FIX: photo_id → last processed payment amount ለ #/ correction
    cur.execute("""
        CREATE TABLE IF NOT EXISTS winner_photo_amounts (
            photo_id BIGINT PRIMARY KEY,
            telegram_id BIGINT NOT NULL,
            group_id BIGINT NOT NULL,
            ai_amount FLOAT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# WINNER API CONFIG
# ============================================================

def save_winner_api(api_id: int, api_hash: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO winner_api_config (id, api_id, api_hash)
        VALUES (1, %s, %s)
        ON CONFLICT (id) DO UPDATE SET api_id=%s, api_hash=%s
    """, (api_id, api_hash, api_id, api_hash))
    conn.commit()
    cur.close()
    conn.close()


def get_winner_api():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT api_id, api_hash FROM winner_api_config WHERE id=1")
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None, None
    return row[0], row[1]


# ============================================================
# GROUP ADMIN SESSION HELPERS
# ============================================================

def get_all_winner_sessions() -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT ga.group_id, ga.telegram_id, ga.session_string
        FROM group_admins ga
        WHERE ga.session_string IS NOT NULL AND ga.session_string != ''
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"group_id": r[0], "admin_id": r[1], "session_string": r[2]} for r in rows]


def save_session_string(group_id: int, admin_id: int, session_string: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE group_admins SET session_string=%s
        WHERE group_id=%s AND telegram_id=%s
    """, (session_string, group_id, admin_id))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# WINNER LOOKUP
# ============================================================

def get_unsent_winner_by_telegram_id(telegram_id: int, group_id: int) -> dict:
    """Winners table ላይ sent=FALSE ያለውን winner ያምጣ"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, game_id, place, user_name, prize
        FROM winners
        WHERE telegram_id=%s AND group_id=%s AND sent=FALSE
        ORDER BY place ASC, created_at DESC
        LIMIT 1
    """, (telegram_id, group_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "game_id": row[1],
        "place": row[2],
        "user_name": row[3],
        "prize": float(row[4]) if row[4] else 0,
    }


def get_any_winner_by_telegram_id(telegram_id: int, group_id: int) -> dict:
    """
    FIX #1 + #3: sent=FALSE ወይም sent=TRUE ያለውን winner ያምጣ
    ብዙ places ካሉ → lowest place (1ኛ) ይምጣ
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, game_id, place, user_name, prize, sent
        FROM winners
        WHERE telegram_id=%s AND group_id=%s
        ORDER BY place ASC, created_at DESC
        LIMIT 1
    """, (telegram_id, group_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "game_id": row[1],
        "place": row[2],
        "user_name": row[3],
        "prize": float(row[4]) if row[4] else 0,
        "sent": row[5],
    }


def get_all_winners_by_telegram_id(telegram_id: int, group_id: int) -> list:
    """
    FIX #3: አንድ user ብዙ places ካሸነፈ ሁሉንም ያምጣ
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, game_id, place, user_name, prize, sent
        FROM winners
        WHERE telegram_id=%s AND group_id=%s
        ORDER BY place ASC
    """, (telegram_id, group_id))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "id": r[0],
            "game_id": r[1],
            "place": r[2],
            "user_name": r[3],
            "prize": float(r[4]) if r[4] else 0,
            "sent": r[5],
        }
        for r in rows
    ]


def get_sent_winner_by_telegram_id(telegram_id: int, group_id: int) -> dict:
    """Winners table ላይ sent=TRUE ያለውን winner ያምጣ (lowest place)"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, game_id, place, user_name, prize
        FROM winners
        WHERE telegram_id=%s AND group_id=%s AND sent=TRUE
        ORDER BY place ASC, created_at DESC
        LIMIT 1
    """, (telegram_id, group_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "game_id": row[1],
        "place": row[2],
        "user_name": row[3],
        "prize": float(row[4]) if row[4] else 0,
    }


# ============================================================
# PHOTO AMOUNT TRACKING (for #/ correction)
# ============================================================

def save_photo_amount(photo_id: int, telegram_id: int, group_id: int, ai_amount: float):
    """AI ያነበበውን amount ለ photo_id ያስቀምጥ"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO winner_photo_amounts (photo_id, telegram_id, group_id, ai_amount)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (photo_id) DO UPDATE SET ai_amount=%s
    """, (photo_id, telegram_id, group_id, ai_amount, ai_amount))
    conn.commit()
    cur.close()
    conn.close()


def get_photo_amount(photo_id: int) -> dict:
    """photo_id ላይ AI ያነበበውን amount ያምጣ"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT telegram_id, group_id, ai_amount
        FROM winner_photo_amounts
        WHERE photo_id=%s
    """, (photo_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {"telegram_id": row[0], "group_id": row[1], "ai_amount": row[2]}


# ============================================================
# CAPTION PARSER — #/300 only
# ============================================================

def parse_edit_caption(caption: str):
    """
    #/300 → 300.0
    ሌላ  → None
    """
    if not caption:
        return None
    caption = caption.strip()
    edit_match = re.match(r'^#/(\d+(?:\.\d+)?)$', caption)
    if edit_match:
        return float(edit_match.group(1))
    return None


# ============================================================
# PROCESS WINNER PAYMENT — FIXED
# ============================================================

async def process_winner_payment(bot, group_id: int,
                                  receiver_id: int, amount: float,
                                  is_edit: bool = False,
                                  photo_ai_amount: float = None):
    """
    FIX #1: sent=TRUE ከሆነም ይቀጥላል (extra payment)
    FIX #3: አንድ user ብዙ places ካሸነፈ → total deduct, lowest place announce
    FIX #2: is_edit=True → photo_ai_amount vs actual → diff adjust
    """

    if is_edit:
        # #/ correction: reply photo ላይ AI ያነበበው vs actual
        if photo_ai_amount is None:
            logger.warning(f"[Userbot2] edit — no photo_ai_amount provided for {receiver_id}")
            return

        winner = get_any_winner_by_telegram_id(receiver_id, group_id)
        if not winner:
            logger.info(f"[Userbot2] edit — no winner for {receiver_id} in group {group_id}")
            return

        # diff = actual - ai_read → positive means more to deduct, negative means refund
        diff = amount - photo_ai_amount
        if diff == 0:
            logger.info(f"[Userbot2] edit — no change for {receiver_id}")
            return

        game_id = winner["game_id"]
        result = deduct_winner_balance(game_id, receiver_id, diff, group_id=group_id)
        new_balance = result["new_balance"]

        logger.info(
            f"[Userbot2] edit correction | {winner['user_name']} | "
            f"ai_read={photo_ai_amount} actual={amount} diff={diff} | balance={new_balance}"
        )
        await _send_group_announcement(bot, group_id, winner, amount, new_balance, is_edit=True)

    else:
        # FIX #3: ሁሉም winners ያምጣ (ብዙ place ካሸነፈ)
        all_winners = get_all_winners_by_telegram_id(receiver_id, group_id)
        if not all_winners:
            logger.info(f"[Userbot2] send — no winner for {receiver_id} in group {group_id}")
            return

        # Lowest place (1ኛ) announcement ይጠቀም
        primary_winner = all_winners[0]  # already sorted by place ASC
        game_id = primary_winner["game_id"]

        # FIX #1 + #3: ሁሉንም winners deduct ባንዴ
        result = deduct_winner_balance(game_id, receiver_id, amount, group_id=group_id)
        new_balance = result["new_balance"]

        # mark all unsent winners as sent
        for w in all_winners:
            if not w["sent"]:
                mark_winner_sent(w["game_id"], receiver_id, w["prize"])

        logger.info(
            f"[Userbot2] send | {primary_winner['user_name']} | "
            f"places={[w['place'] for w in all_winners]} | amount={amount} | balance={new_balance}"
        )
        await _send_group_announcement(bot, group_id, primary_winner, amount, new_balance, is_edit=False)


async def _send_group_announcement(bot, group_id: int, winner: dict,
                                    amount: float, new_balance: float, is_edit: bool):
    try:
        place_label = {1: "1ኛ", 2: "2ኛ", 3: "3ኛ"}.get(winner["place"], f"{winner['place']}ኛ")
        edit_label = " (ተስተካከለ)" if is_edit else ""

        text = (
            f"💸 {place_label} winner ብር ተላከ!{edit_label}\n"
            f"👤 {winner['user_name']}\n"
            f"💰 ETB {amount}\n"
            f"💳 ቀሪ balance: ETB {new_balance}"
        )

        logger.info(
            f"[Userbot2] Sending announcement to group {group_id} | "
            f"winner={winner['user_name']} | amount={amount} | is_edit={is_edit}"
        )

        await bot.send_message(chat_id=group_id, text=text)
        logger.info(f"[Userbot2] ✅ Announcement sent successfully to group {group_id}")

    except Exception as e:
        logger.error(
            f"[Userbot2] ❌ Group announcement FAILED | group={group_id} | "
            f"winner={winner.get('user_name')} | amount={amount} | error={e}",
            exc_info=True
        )


# ============================================================
# LISTENER CLIENT MANAGEMENT
# ============================================================

_active_clients = []
_pending_sessions2: dict = {}
_processed_photo_ids: set = set()


async def _start_single_listener(bot, session: dict) -> bool:
    group_id = session["group_id"]
    admin_id = session["admin_id"]
    session_string = session["session_string"]

    api_id, api_hash = get_winner_api()
    if not api_id or not api_hash:
        logger.warning("[Userbot2] Winner API አልተቀመጠም — /setwinnerapi ይጠቀሙ")
        return False

    try:
        client = TelegramClient(StringSession(session_string), api_id, api_hash)
        await client.connect()

        if not await client.is_user_authorized():
            logger.warning(f"[Userbot2] Session not authorized for admin {admin_id}")
            return False

        @client.on(events.NewMessage(outgoing=True))
        async def handler(event, _group_id=group_id, _admin_id=admin_id):
            try:
                msg = event.message
                caption = (msg.message or "").strip()
                has_photo = bool(msg.photo)

                # receiver_id
                receiver_id = None
                if hasattr(msg.peer_id, 'user_id'):
                    receiver_id = msg.peer_id.user_id
                else:
                    peer = await event.get_chat()
                    receiver_id = peer.id

                if not receiver_id:
                    logger.debug(f"[Userbot2] receiver_id ጠፍቷል — skip")
                    return

                logger.debug(
                    f"[Userbot2] Outgoing msg | receiver={receiver_id} | "
                    f"has_photo={has_photo} | caption='{caption[:30]}'"
                )

                # ── FIX #2: #/ correction — reply to photo ብቻ ──────────
                edit_amount = parse_edit_caption(caption)
                if edit_amount is not None and not has_photo:
                    # reply_to ያለ photo id ያምጣ
                    replied_photo_id = None
                    if msg.reply_to and msg.reply_to.reply_to_msg_id:
                        try:
                            replied_msg = await client.get_messages(
                                msg.peer_id,
                                ids=msg.reply_to.reply_to_msg_id
                            )
                            if replied_msg and replied_msg.photo:
                                replied_photo_id = replied_msg.photo.id
                        except Exception as e:
                            logger.warning(f"[Userbot2] Could not get replied message: {e}")

                    if not replied_photo_id:
                        logger.info(f"[Userbot2] #/ without reply to photo — skip")
                        return

                    # ያ photo ላይ AI ያነበበውን amount ያምጣ
                    photo_data = get_photo_amount(replied_photo_id)
                    if not photo_data:
                        logger.info(f"[Userbot2] #/ replied photo not in DB — skip")
                        return

                    logger.info(
                        f"[Userbot2] Edit correction | photo={replied_photo_id} | "
                        f"ai_read={photo_data['ai_amount']} | actual={edit_amount} | receiver={receiver_id}"
                    )
                    await process_winner_payment(
                        bot=bot,
                        group_id=_group_id,
                        receiver_id=receiver_id,
                        amount=edit_amount,
                        is_edit=True,
                        photo_ai_amount=photo_data["ai_amount"],
                    )
                    return

                # ── FIX #1 + #3: photo — sent ወይም unsent winner ─────────
                if has_photo and not caption:
                    photo_uid = msg.photo.id
                    if photo_uid in _processed_photo_ids:
                        logger.info(f"[Userbot2] photo {photo_uid} already processed — skip")
                        return
                    _processed_photo_ids.add(photo_uid)

                    logger.info(f"[Userbot2] Photo detected | receiver={receiver_id} | checking winner...")

                    # FIX #1: sent ወይም unsent — ሁሉም winner ያምጣ
                    all_winners = get_all_winners_by_telegram_id(receiver_id, _group_id)
                    if not all_winners:
                        logger.info(f"[Userbot2] photo — no winner for {receiver_id}, skip AI")
                        return

                    logger.info(
                        f"[Userbot2] Winner(s) found: {[w['user_name'] for w in all_winners]} | calling AI analyze..."
                    )

                    image_base64 = await _download_tg_photo(client, msg)
                    if not image_base64:
                        logger.error(f"[Userbot2] ❌ Photo download failed for receiver={receiver_id}")
                        return

                    analysis = await analyze_screenshot(image_base64)
                    if not analysis:
                        logger.warning(f"[Userbot2] ❌ AI analyze returned None for receiver={receiver_id}")
                        return

                    amount = analysis.get("amount")
                    if not amount:
                        logger.warning(
                            f"[Userbot2] ❌ AI could not find amount | analysis={analysis}"
                        )
                        return

                    amount = float(amount)
                    logger.info(
                        f"[Userbot2] AI found amount={amount} for {all_winners[0]['user_name']}"
                    )

                    # FIX #2: AI amount ለ #/ correction ያስቀምጥ
                    save_photo_amount(photo_uid, receiver_id, _group_id, amount)

                    await process_winner_payment(
                        bot=bot,
                        group_id=_group_id,
                        receiver_id=receiver_id,
                        amount=amount,
                        is_edit=False,
                    )
                    return

                # ── URL in text ───────────────────────────────────────────
                if not has_photo and caption:
                    url_match = re.search(r'https?://[^\s]+', caption)
                    if url_match:
                        logger.info(f"[Userbot2] URL detected | receiver={receiver_id} | checking winner...")

                        # FIX #1: sent ወይም unsent winner ያምጣ
                        all_winners = get_all_winners_by_telegram_id(receiver_id, _group_id)
                        if not all_winners:
                            logger.info(f"[Userbot2] URL — no winner for {receiver_id}, skip")
                            return

                        url = url_match.group(0)
                        logger.info(f"[Userbot2] Fetching payment data from URL: {url}")
                        payment_data = await fetch_payment_data_from_url(url)
                        if not payment_data or not payment_data.get("amount"):
                            logger.warning(
                                f"[Userbot2] ❌ URL fetch — no amount | url={url} | data={payment_data}"
                            )
                            return

                        amount = float(payment_data["amount"])
                        logger.info(
                            f"[Userbot2] URL amount={amount} for {all_winners[0]['user_name']}"
                        )
                        await process_winner_payment(
                            bot=bot,
                            group_id=_group_id,
                            receiver_id=receiver_id,
                            amount=amount,
                            is_edit=False,
                        )
                        return

            except Exception as e:
                logger.error(f"[Userbot2] ❌ Handler error: {e}", exc_info=True)

        _active_clients.append(client)
        logger.info(f"[Userbot2] ✅ Listener started for admin {admin_id} | group {group_id}")
        return True

    except Exception as e:
        logger.error(
            f"[Userbot2] ❌ Failed to start listener for admin {admin_id}: {e}",
            exc_info=True
        )
        return False


async def _download_tg_photo(client: TelegramClient, msg) -> str:
    import base64
    import io
    try:
        buf = io.BytesIO()
        await client.download_media(msg, file=buf)
        buf.seek(0)
        data = buf.read()
        logger.info(f"[Userbot2] Photo downloaded successfully | size={len(data)} bytes")
        return base64.b64encode(data).decode("utf-8")
    except Exception as e:
        logger.error(f"[Userbot2] ❌ Photo download error: {e}", exc_info=True)
        return None


async def start_winner_listeners(bot):
    sessions = get_all_winner_sessions()
    if not sessions:
        logger.info("[Userbot2] No winner sender sessions found")
        return
    logger.info(f"[Userbot2] Loading {len(sessions)} session(s)...")
    for s in sessions:
        await _start_single_listener(bot, s)


# ============================================================
# BOT COMMANDS
# ============================================================

def register_userbot2_handlers(app, bot):
    from telegram.ext import CommandHandler
    from telegram import Update
    from telegram.ext import ContextTypes
    from bot import is_admin, is_main_admin, get_admin_group_id

    async def handle_setwinnerapi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not is_main_admin(update.effective_user.id):
            await update.message.reply_text("❌ Main admin ብቻ ነው!")
            return

        parts = update.message.text.strip().split(maxsplit=2)
        if len(parts) < 3:
            await update.message.reply_text(
                "❌ ምሳሌ: /setwinnerapi 12345678 abcdef0123456789\n"
                "(api_id እና api_hash ከ my.telegram.org)"
            )
            return

        try:
            api_id = int(parts[1])
        except ValueError:
            await update.message.reply_text("❌ api_id ቁጥር መሆን አለበት!")
            return

        api_hash = parts[2].strip()
        save_winner_api(api_id, api_hash)
        await update.message.reply_text(
            f"✅ Winner API ተቀምጧል!\n🆔 {api_id}\n🔑 {api_hash}\n\n"
            f"እያንዳንዱ group admin አሁን /startsession2 +phone መጠቀም ይችላል።"
        )

    async def handle_startsession2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if update.effective_chat.type != "private":
            await update.message.reply_text("❌ Private chat ብቻ ነው!")
            return

        group_id = get_admin_group_id(user_id)
        if not group_id:
            await update.message.reply_text("❌ Admin የሆንክበት group የለም!")
            return

        api_id, api_hash = get_winner_api()
        if not api_id or not api_hash:
            await update.message.reply_text(
                "❌ Winner API አልተቀመጠም! Main admin በመጀመሪያ /setwinnerapi ማድረግ አለበት።"
            )
            return

        parts = update.message.text.strip().split()
        phone = None
        for p in parts[1:]:
            if p.startswith("+"):
                phone = p
                break
        if not phone:
            await update.message.reply_text("❌ ምሳሌ: /startsession2 +251911223344")
            return

        await update.message.reply_text(f"📱 {phone} ላይ code እየላከ ነው...")
        try:
            client = TelegramClient(StringSession(), api_id, api_hash)
            await client.connect()
            await client.send_code_request(phone)
            _pending_sessions2[phone] = {"client": client, "user_id": user_id, "group_id": group_id}
            await update.message.reply_text(f"✅ Code ተላከ!\n\n/verifycode2 {phone} 12345")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def handle_verifycode2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != "private":
            await update.message.reply_text("❌ Private chat ብቻ ነው!")
            return

        parts = update.message.text.strip().split(maxsplit=2)
        if len(parts) < 3:
            await update.message.reply_text("❌ ምሳሌ: /verifycode2 +251911223344 12345")
            return

        phone, code = parts[1], parts[2]
        pending = _pending_sessions2.get(phone)
        if not pending:
            await update.message.reply_text(f"❌ {phone} pending session የለም! /startsession2 ድጋሚ ሞክር")
            return

        client = pending["client"]
        try:
            await client.sign_in(phone=phone, code=code)
            await _finish_login(update, client, phone, pending)
        except SessionPasswordNeededError:
            await update.message.reply_text(
                f"🔐 2FA አለው!\n/verify2fa2 {phone} የራስህ_password"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def handle_verify2fa2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != "private":
            await update.message.reply_text("❌ Private chat ብቻ ነው!")
            return

        parts = update.message.text.strip().split(maxsplit=2)
        if len(parts) < 3:
            await update.message.reply_text("❌ ምሳሌ: /verify2fa2 +251911223344 yourpassword")
            return

        phone, password = parts[1], parts[2]
        pending = _pending_sessions2.get(phone)
        if not pending:
            await update.message.reply_text(f"❌ {phone} pending session የለም! /startsession2 ድጋሚ ሞክር")
            return

        client = pending["client"]
        try:
            await client.sign_in(password=password)
            await _finish_login(update, client, phone, pending)
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    async def _finish_login(update: Update, client: TelegramClient, phone: str, pending: dict):
        session_string = client.session.save()
        group_id = pending["group_id"]
        admin_id = pending["user_id"]

        save_session_string(group_id, admin_id, session_string)
        _pending_sessions2.pop(phone, None)

        started = await _start_single_listener(
            bot, {"group_id": group_id, "admin_id": admin_id, "session_string": session_string}
        )

        if started:
            await update.message.reply_text(
                f"✅ {phone} verified!\n🟢 Listener ራሱ ተነስቷል — ምንም restart አያስፈልግም።"
            )
        else:
            await update.message.reply_text(
                f"✅ {phone} verified እና session ተቀምጧል፣ ግን listener ማስነሳት አልተቻለም።\n"
                f"⚠️ Logs ያረጋግጡ ወይም bot restart ያድርጉ።"
            )

    app.add_handler(CommandHandler("setwinnerapi", handle_setwinnerapi))
    app.add_handler(CommandHandler("startsession2", handle_startsession2))
    app.add_handler(CommandHandler("verifycode2", handle_verifycode2))
    app.add_handler(CommandHandler("verify2fa2", handle_verify2fa2))

    logger.info("✅ Userbot2 handlers registered")
