"""
userbot2.py — Winner payment auto-listener (Telethon-based)

ፍሰት:
1. Main admin አንድ ጊዜ /setwinnerapi api_id api_hash ያስቀምጣል (ለሁሉም shared)
2. እያንዳንዱ group admin (private chat ላይ):
   /startsession2 +phone   → code ይላካል
   /verifycode2 +phone code → session ይፈጠራል፣ ይቀመጣል፣ listener ራሱ ይነሳል
   (2FA ካለ: /verify2fa2 +phone password)
ምንም external script ወይም manual session string paste አያስፈልግም።
"""

import asyncio
import logging
import re
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from database import get_conn, deduct_winner_balance, mark_winner_sent

logger = logging.getLogger(__name__)

# ============================================================
# DB INIT — global winner API config table
# ============================================================

def init_userbot2_db():
    """ሁለት ነገር ያረጋግጣል: group_admins.session_string column + winner_api_config table"""
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
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# WINNER API CONFIG (shared once by main admin)
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
    """group_admins table ላይ session_string ያላቸውን ሁሉ ያምጣ"""
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
    """group_admins table ላይ session_string ያስቀምጥ"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE group_admins SET session_string=%s
        WHERE group_id=%s AND telegram_id=%s
    """, (session_string, group_id, admin_id))
    conn.commit()
    cur.close()
    conn.close()


def get_unsent_winner_by_telegram_id(telegram_id: int, group_id: int) -> dict:
    """Winners table ላይ sent=FALSE ያለውን winner ያምጣ"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, game_id, place, user_name, prize
        FROM winners
        WHERE telegram_id=%s AND group_id=%s AND sent=FALSE
        ORDER BY created_at DESC
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


def get_sent_winner_by_telegram_id(telegram_id: int, group_id: int) -> dict:
    """Winners table ላይ sent=TRUE ያለውን winner ያምጣ (#/send edit አርጎ)"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, game_id, place, user_name, prize
        FROM winners
        WHERE telegram_id=%s AND group_id=%s AND sent=TRUE
        ORDER BY created_at DESC
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
# CAPTION PARSER
# ============================================================

def parse_caption(caption: str):
    """
    /300  → ("send", 300)
    #/300 → ("edit", 300)
    None  → None
    """
    if not caption:
        return None
    caption = caption.strip()
    edit_match = re.match(r'^#/(\d+(?:\.\d+)?)$', caption)
    if edit_match:
        return ("edit", float(edit_match.group(1)))
    send_match = re.match(r'^/(\d+(?:\.\d+)?)$', caption)
    if send_match:
        return ("send", float(send_match.group(1)))
    return None


# ============================================================
# PROCESS WINNER PAYMENT
# ============================================================

async def process_winner_payment(bot, admin_id: int, group_id: int,
                                  receiver_id: int, amount: float,
                                  is_edit: bool):
    """Winner payment ያስተናግዳል"""

    if is_edit:
        winner = get_sent_winner_by_telegram_id(receiver_id, group_id)
        if not winner:
            logger.info(f"[Userbot2] #/send — no sent winner found for {receiver_id} in group {group_id}")
            return

        game_id = winner["game_id"]
        old_prize = winner["prize"]
        difference = amount - old_prize

        if difference == 0:
            logger.info(f"[Userbot2] #/send — no change for {receiver_id}")
            return

        result = deduct_winner_balance(game_id, receiver_id, -difference, group_id=group_id)
        new_balance = result["new_balance"]

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE winners SET prize=%s WHERE game_id=%s AND telegram_id=%s AND group_id=%s
        """, (amount, game_id, receiver_id, group_id))
        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"[Userbot2] #/send edit — {winner['user_name']} | old={old_prize} new={amount} diff={difference} | balance={new_balance}")

        await _send_group_announcement(bot, group_id, winner, amount, new_balance, is_edit=True)

    else:
        winner = get_unsent_winner_by_telegram_id(receiver_id, group_id)
        if not winner:
            logger.info(f"[Userbot2] /send — no unsent winner found for {receiver_id} in group {group_id}")
            return

        game_id = winner["game_id"]

        result = deduct_winner_balance(game_id, receiver_id, amount, group_id=group_id)
        new_balance = result["new_balance"]
        mark_winner_sent(game_id, receiver_id, amount)

        logger.info(f"[Userbot2] /send — {winner['user_name']} | amount={amount} | balance={new_balance}")

        await _send_group_announcement(bot, group_id, winner, amount, new_balance, is_edit=False)


async def _send_group_announcement(bot, group_id: int, winner: dict,
                                    amount: float, new_balance: float, is_edit: bool):
    """Group ላይ announcement ይልካል"""
    try:
        place_label = {1: "1ኛ", 2: "2ኛ", 3: "3ኛ"}.get(winner["place"], f"{winner['place']}ኛ")
        edit_label = " (ተስተካከለ)" if is_edit else ""

        text = (
            f"💸 {place_label} winner ብር ተላከ!{edit_label}\n"
            f"👤 {winner['user_name']}\n"
            f"💰 ETB {amount}\n"
            f"💳 ቀሪ balance: ETB {new_balance}"
        )
        await bot.send_message(group_id, text)
    except Exception as e:
        logger.warning(f"[Userbot2] Group announcement error: {e}")


# ============================================================
# LISTENER CLIENT MANAGEMENT
# ============================================================

_active_clients = []
_pending_sessions2: dict = {}  # phone -> {"client":..., "user_id":..., "group_id":...}


async def _start_single_listener(bot, session: dict) -> bool:
    """አንድ admin session ላይ ብቻ listener ይነሳል (hot-start, restart ሳያስፈልግ)"""
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
                if not event.message.photo:
                    return

                caption = event.message.message or ""
                parsed = parse_caption(caption)
                if not parsed:
                    return

                action, amount = parsed
                is_edit = (action == "edit")

                receiver_id = event.message.peer_id.user_id if hasattr(event.message.peer_id, 'user_id') else None
                if not receiver_id:
                    peer = await event.get_chat()
                    receiver_id = peer.id

                await process_winner_payment(
                    bot=bot,
                    admin_id=_admin_id,
                    group_id=_group_id,
                    receiver_id=receiver_id,
                    amount=amount,
                    is_edit=is_edit,
                )

            except Exception as e:
                logger.error(f"[Userbot2] Handler error: {e}", exc_info=True)

        _active_clients.append(client)
        logger.info(f"[Userbot2] ✅ Listener started for admin {admin_id} | group {group_id}")
        return True

    except Exception as e:
        logger.error(f"[Userbot2] Failed to start for admin {admin_id}: {e}", exc_info=True)
        return False


async def start_winner_listeners(bot):
    """ቦት ሲነሳ ያሉትን session ሁሉ ይጭናል"""
    sessions = get_all_winner_sessions()
    if not sessions:
        logger.info("[Userbot2] No winner sender sessions found")
        return
    for s in sessions:
        await _start_single_listener(bot, s)


# ============================================================
# BOT COMMANDS
# ============================================================

def register_userbot2_handlers(app, bot):
    """bot.py ላይ winner-session commands ይጨምራል"""
    from telegram.ext import CommandHandler
    from telegram import Update
    from telegram.ext import ContextTypes
    from bot import is_admin, is_main_admin, get_admin_group_id

    # --------------------------------------------------------
    # /setwinnerapi — main admin ብቻ፣ አንድ ጊዜ
    # --------------------------------------------------------
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

    # --------------------------------------------------------
    # /startsession2 — እያንዳንዱ group admin (private chat ብቻ)
    # --------------------------------------------------------
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
            await update.message.reply_text(
                f"✅ Code ተላከ!\n\n/verifycode2 {phone} 12345"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    # --------------------------------------------------------
    # /verifycode2
    # --------------------------------------------------------
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

    # --------------------------------------------------------
    # /verify2fa2
    # --------------------------------------------------------
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

    # --------------------------------------------------------
    # Login ሲጠናቅ session ያስቀምጣል + listener ራሱ ይነሳል
    # --------------------------------------------------------
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
