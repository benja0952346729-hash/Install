import asyncio
import logging
import re
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH
from database import get_conn, get_recent_winners_by_telegram_id, deduct_winner_balance, mark_winner_sent

logger = logging.getLogger(__name__)

# ============================================================
# DB FUNCTIONS
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
        # sent=TRUE winner ይፈልጋል
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

        # Difference ያሰላዋል — positive ከሆነ ይጨምራል negative ከሆነ ይቀንሳል
        result = deduct_winner_balance(game_id, receiver_id, -difference, group_id=group_id)
        new_balance = result["new_balance"]

        # Prize amount ያዘምናል
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE winners SET prize=%s WHERE game_id=%s AND telegram_id=%s AND group_id=%s
        """, (amount, game_id, receiver_id, group_id))
        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"[Userbot2] #/send edit — {winner['user_name']} | old={old_prize} new={amount} diff={difference} | balance={new_balance}")

        # Group announcement
        await _send_group_announcement(bot, group_id, winner, amount, new_balance, is_edit=True)

    else:
        # sent=FALSE winner ይፈልጋል
        winner = get_unsent_winner_by_telegram_id(receiver_id, group_id)
        if not winner:
            logger.info(f"[Userbot2] /send — no unsent winner found for {receiver_id} in group {group_id}")
            return

        game_id = winner["game_id"]

        result = deduct_winner_balance(game_id, receiver_id, amount, group_id=group_id)
        new_balance = result["new_balance"]
        mark_winner_sent(game_id, receiver_id, amount)

        logger.info(f"[Userbot2] /send — {winner['user_name']} | amount={amount} | balance={new_balance}")

        # Group announcement
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
# USERBOT2 CLIENT PER ADMIN
# ============================================================

_active_clients = []


async def start_winner_listeners(bot):
    """ሁሉም admin sessions load አርጎ listener ይጀምራል"""
    sessions = get_all_winner_sessions()
    if not sessions:
        logger.info("[Userbot2] No winner sender sessions found")
        return

    for s in sessions:
        group_id = s["group_id"]
        admin_id = s["admin_id"]
        session_string = s["session_string"]

        try:
            client = TelegramClient(
                StringSession(session_string),
                TELEGRAM_API_ID,
                TELEGRAM_API_HASH
            )
            await client.connect()

            if not await client.is_user_authorized():
                logger.warning(f"[Userbot2] Session not authorized for admin {admin_id}")
                continue

            # DM outgoing messages ያዳምጣል
            @client.on(events.MessageSent(outgoing=True))
            async def handler(event, _group_id=group_id, _admin_id=admin_id):
                try:
                    # ለ winner ብቻ — photo + caption
                    if not event.message.photo:
                        return

                    caption = event.message.message or ""
                    parsed = parse_caption(caption)
                    if not parsed:
                        return

                    action, amount = parsed
                    is_edit = (action == "edit")

                    # Receiver telegram ID
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

        except Exception as e:
            logger.error(f"[Userbot2] Failed to start for admin {admin_id}: {e}", exc_info=True)


# ============================================================
# BOT COMMANDS — /setsession2
# ============================================================

def register_userbot2_handlers(app, bot):
    """bot.py ላይ /setsession2 command ይጨምራል"""
    from telegram.ext import CommandHandler
    from telegram import Update
    from telegram.ext import ContextTypes
    from database import is_group_admin
    from bot import is_admin, get_admin_group_id

    async def handle_setsession2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        chat_type = update.effective_chat.type

        if chat_type != "private":
            await update.message.reply_text("❌ Private chat ብቻ ነው!")
            return

        group_id = get_admin_group_id(user_id)
        if not group_id:
            await update.message.reply_text("❌ Admin የሆንክበት group የለም!")
            return

        parts = update.message.text.strip().split()
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ ምሳሌ: /setsession2 YOUR_SESSION_STRING\n"
                "Session string ከ Telethon ያምጡ።"
            )
            return

        session_string = parts[1].strip()
        save_session_string(group_id, user_id, session_string)

        await update.message.reply_text("✅ Session string ተቀምጧል! Bot restart ያስፈልጋል።")

    app.add_handler(CommandHandler("setsession2", handle_setsession2))


def init_userbot2_db():
    """group_admins table ላይ session_string column ይጨምራል"""
    from database import get_conn
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        ALTER TABLE group_admins ADD COLUMN IF NOT EXISTS session_string TEXT;
    """)
    conn.commit()
    cur.close()
    conn.close()
