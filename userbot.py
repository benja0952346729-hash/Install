"""
userbot.py — Telethon-based userbot commands
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import AddContactRequest
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.errors import FloodWaitError
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from database import get_conn
from config import ADMIN_IDS

logger = logging.getLogger(__name__)


# ============================================================
# DB INIT
# ============================================================

def init_userbot_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS userbot_accounts (
            id SERIAL PRIMARY KEY,
            label CHAR(1) NOT NULL UNIQUE,
            api_id BIGINT NOT NULL,
            api_hash TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            session TEXT DEFAULT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            flood_until TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS userbot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS userbot_groups (
            id SERIAL PRIMARY KEY,
            group_id BIGINT NOT NULL UNIQUE,
            added_at TIMESTAMP DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS userbot_added_users (
            user_id BIGINT NOT NULL,
            group_id BIGINT NOT NULL,
            PRIMARY KEY (user_id, group_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS userbot_contacted_users (
            user_id BIGINT NOT NULL,
            account_label CHAR(1) NOT NULL,
            PRIMARY KEY (user_id, account_label)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS userbot_recent_messages (
            user_id BIGINT NOT NULL,
            group_id BIGINT NOT NULL,
            sent_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (user_id, group_id)
        )
    """)

    # ✅ FIX — አሮጌ userbot_accounts table ላይ label እና flood_until columns ካልሆኑ ይጨምራቸዋል
    cur.execute("""
        ALTER TABLE userbot_accounts
        ADD COLUMN IF NOT EXISTS label CHAR(1) UNIQUE
    """)
    cur.execute("""
        ALTER TABLE userbot_accounts
        ADD COLUMN IF NOT EXISTS flood_until TIMESTAMP DEFAULT NULL
    """)
    # ✅ FIX — አሮጌ userbot_groups table username column ካለ group_id ይጨምራል
    cur.execute("""
        ALTER TABLE userbot_groups
        ADD COLUMN IF NOT EXISTS group_id BIGINT UNIQUE
    """)

    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ Userbot DB tables ready")


# ============================================================
# DB HELPERS
# ============================================================

def db_add_account(label: str, api_id: int, api_hash: str, phone: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_accounts (label, api_id, api_hash, phone)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (phone) DO UPDATE SET api_id=%s, api_hash=%s, label=%s
    """, (label, api_id, api_hash, phone, api_id, api_hash, label))
    conn.commit()
    cur.close()
    conn.close()


def db_list_accounts():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, label, phone, is_active, session, flood_until FROM userbot_accounts ORDER BY label")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def db_get_account_by_label(label: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, label, api_id, api_hash, phone, session, is_active, flood_until FROM userbot_accounts WHERE label=%s",
        (label,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "label": row[1], "api_id": row[2], "api_hash": row[3],
        "phone": row[4], "session": row[5], "is_active": row[6], "flood_until": row[7]
    }


def db_get_account_by_phone(phone: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, label, api_id, api_hash, phone, session, is_active, flood_until FROM userbot_accounts WHERE phone=%s",
        (phone,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "label": row[1], "api_id": row[2], "api_hash": row[3],
        "phone": row[4], "session": row[5], "is_active": row[6], "flood_until": row[7]
    }


def db_get_all_accounts():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, label, api_id, api_hash, phone, session, is_active, flood_until FROM userbot_accounts WHERE is_active=TRUE ORDER BY label"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {"id": r[0], "label": r[1], "api_id": r[2], "api_hash": r[3],
         "phone": r[4], "session": r[5], "is_active": r[6], "flood_until": r[7]}
        for r in rows
    ]


def db_save_session(phone: str, session: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE userbot_accounts SET session=%s WHERE phone=%s", (session, phone))
    conn.commit()
    cur.close()
    conn.close()


def db_set_flood(phone: str, seconds: int):
    conn = get_conn()
    cur = conn.cursor()
    until = datetime.now() + timedelta(seconds=seconds)
    cur.execute("UPDATE userbot_accounts SET flood_until=%s WHERE phone=%s", (until, phone))
    conn.commit()
    cur.close()
    conn.close()


def db_delete_account(phone: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM userbot_accounts WHERE phone=%s", (phone,))
    conn.commit()
    cur.close()
    conn.close()


def db_set_setting(key: str, value: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_settings (key, value) VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value=%s
    """, (key, value, value))
    conn.commit()
    cur.close()
    conn.close()


def db_get_setting(key: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM userbot_settings WHERE key=%s", (key,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None


def db_add_group(group_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_groups (group_id) VALUES (%s)
        ON CONFLICT (group_id) DO NOTHING
    """, (group_id,))
    conn.commit()
    cur.close()
    conn.close()


def db_list_groups():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, group_id FROM userbot_groups WHERE group_id IS NOT NULL ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def db_delete_group(group_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM userbot_groups WHERE group_id=%s", (group_id,))
    conn.commit()
    cur.close()
    conn.close()


def db_is_user_added(user_id: int, group_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM userbot_added_users WHERE user_id=%s AND group_id=%s",
        (user_id, group_id)
    )
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists


def db_mark_user_added(user_id: int, group_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_added_users (user_id, group_id) VALUES (%s, %s)
        ON CONFLICT DO NOTHING
    """, (user_id, group_id))
    conn.commit()
    cur.close()
    conn.close()


def db_is_user_contacted(user_id: int, account_label: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM userbot_contacted_users WHERE user_id=%s AND account_label=%s",
        (user_id, account_label)
    )
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists


def db_mark_user_contacted(user_id: int, account_label: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_contacted_users (user_id, account_label) VALUES (%s, %s)
        ON CONFLICT DO NOTHING
    """, (user_id, account_label))
    conn.commit()
    cur.close()
    conn.close()


def db_record_message(user_id: int, group_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_recent_messages (user_id, group_id, sent_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (user_id, group_id) DO UPDATE SET sent_at=NOW()
    """, (user_id, group_id))
    conn.commit()
    cur.close()
    conn.close()


def db_get_recent_users(hours: int = 2):
    conn = get_conn()
    cur = conn.cursor()
    since = datetime.now() - timedelta(hours=hours)
    cur.execute(
        "SELECT DISTINCT user_id FROM userbot_recent_messages WHERE sent_at >= %s",
        (since,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [r[0] for r in rows]


# ============================================================
# ROUND ROBIN
# ============================================================

_rr_index = 0


def get_next_account():
    global _rr_index
    accounts = db_get_all_accounts()
    now = datetime.now()
    available = [
        a for a in accounts
        if a["session"] and (a["flood_until"] is None or a["flood_until"] < now)
    ]
    if not available:
        return None
    account = available[_rr_index % len(available)]
    _rr_index += 1
    return account


# ============================================================
# TELETHON CLIENT
# ============================================================

async def _get_client(account: dict) -> TelegramClient:
    session = account.get("session") or ""
    client = TelegramClient(
        StringSession(session),
        account["api_id"],
        account["api_hash"]
    )
    await client.connect()
    return client


# ============================================================
# CORE ACTIONS
# ============================================================

async def _send_to_group(account: dict, group_id: int, message=None, media=None):
    client = await _get_client(account)
    try:
        if media:
            await client.send_file(group_id, media, caption=message or "")
        else:
            await client.send_message(group_id, message)
    finally:
        await client.disconnect()


async def _contact_and_add(account: dict, user_id: int, target_group_id: int):
    client = await _get_client(account)
    try:
        user = await client.get_entity(user_id)

        if not db_is_user_contacted(user_id, account["label"]):
            try:
                await client(AddContactRequest(
                    id=user_id,
                    first_name=user.first_name or "User",
                    last_name=user.last_name or "",
                    phone=user.phone or "",
                    add_phone_privacy_exception=False
                ))
                db_mark_user_contacted(user_id, account["label"])
            except FloodWaitError as e:
                db_set_flood(account["phone"], e.seconds)
                logger.warning(f"[Contact] Flood {account['label']}: {e.seconds}s")
                return
            except Exception as e:
                logger.warning(f"[Contact] {user_id}: {e}")

        if not db_is_user_added(user_id, target_group_id):
            try:
                group = await client.get_entity(target_group_id)
                await client(InviteToChannelRequest(channel=group, users=[user_id]))
                db_mark_user_added(user_id, target_group_id)
            except FloodWaitError as e:
                db_set_flood(account["phone"], e.seconds)
                logger.warning(f"[Add] Flood {account['label']}: {e.seconds}s")
            except Exception as e:
                logger.warning(f"[Add] {user_id}: {e}")
    finally:
        await client.disconnect()


# ============================================================
# TELETHON EVENT LISTENERS
# ============================================================

_telethon_clients = []


async def start_listeners():
    global _telethon_clients
    accounts = db_get_all_accounts()

    for account in accounts:
        if not account.get("session"):
            continue
        try:
            client = TelegramClient(
                StringSession(account["session"]),
                account["api_id"],
                account["api_hash"]
            )
            await client.start()

            @client.on(events.NewMessage)
            async def handler(event, acc=account):
                try:
                    chat_id = event.chat_id
                    groups = db_list_groups()
                    group_ids = [g[1] for g in groups]

                    if chat_id not in group_ids:
                        return

                    sender = await event.get_sender()
                    if not sender or sender.bot:
                        return

                    user_id = sender.id
                    db_record_message(user_id, chat_id)

                    target_str = db_get_setting("target_group_id")
                    if not target_str:
                        return

                    target_group_id = int(target_str)

                    if db_is_user_added(user_id, target_group_id):
                        return

                    chosen = get_next_account()
                    if not chosen:
                        return

                    await asyncio.sleep(random.uniform(2, 5))
                    await _contact_and_add(chosen, user_id, target_group_id)

                except Exception as e:
                    logger.warning(f"[AutoAdd] {e}")

            _telethon_clients.append(client)
            logger.info(f"✅ Listener started: {account['label']} {account['phone']}")
        except Exception as e:
            logger.warning(f"[Listener] {account['phone']}: {e}")


# ============================================================
# PENDING SESSIONS
# ============================================================

_pending_sessions: dict = {}


# ============================================================
# ADMIN CHECK
# ============================================================

def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ============================================================
# COMMAND HANDLERS
# ============================================================

async def cmd_addaccount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/addaccount a api_id api_hash +phone"""
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=4)
    if len(args) < 5:
        await update.message.reply_text(
            "❌ Format:\n/addaccount label api_id api_hash +phone\n\n"
            "ምሳሌ:\n/addaccount a 12345 abc123 +251911234567"
        )
        return
    try:
        label = args[1].lower()
        api_id = int(args[2])
        api_hash = args[3]
        phone = args[4]
        db_add_account(label, api_id, api_hash, phone)
        await update.message.reply_text(
            f"✅ Account [{label}] {phone} ተጨመረ!\n\n"
            f"Session ለማስጀመር:\n/startsession {phone}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_startsession(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/startsession +phone"""
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /startsession +phone")
        return

    phone = args[1]
    account = db_get_account_by_phone(phone)
    if not account:
        await update.message.reply_text(f"❌ {phone} አልተገኘም!")
        return
    if account.get("session"):
        await update.message.reply_text(f"✅ {phone} session አለው!")
        return

    await update.message.reply_text(f"📱 {phone} ላይ code እየላከ ነው...")
    try:
        client = TelegramClient(StringSession(), account["api_id"], account["api_hash"])
        await client.connect()
        await client.send_code_request(phone)
        _pending_sessions[phone] = client
        await update.message.reply_text(
            f"✅ Code ተላከ!\n\nCode ለማስገባት:\n/verifycode {phone} 12345"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_verifycode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/verifycode +phone code"""
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=2)
    if len(args) < 3:
        await update.message.reply_text("❌ Format: /verifycode +phone code")
        return

    phone, code = args[1], args[2]
    client = _pending_sessions.get(phone)
    if not client:
        await update.message.reply_text(f"❌ {phone} pending session የለም!")
        return
    try:
        await client.sign_in(phone=phone, code=code)
        session_str = client.session.save()
        db_save_session(phone, session_str)
        _pending_sessions.pop(phone, None)
        await update.message.reply_text(f"✅ {phone} verified!")
    except Exception as e:
        if "password" in str(e).lower():
            await update.message.reply_text(
                f"🔐 2FA password ያስፈልጋል!\n/verify2fa {phone} yourpassword"
            )
        else:
            await update.message.reply_text(f"❌ Error: {e}")


async def cmd_verify2fa(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/verify2fa +phone password"""
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=2)
    if len(args) < 3:
        await update.message.reply_text("❌ Format: /verify2fa +phone password")
        return

    phone, password = args[1], args[2]
    client = _pending_sessions.get(phone)
    if not client:
        await update.message.reply_text(f"❌ {phone} pending session የለም!")
        return
    try:
        await client.sign_in(password=password)
        session_str = client.session.save()
        db_save_session(phone, session_str)
        _pending_sessions.pop(phone, None)
        await update.message.reply_text(f"✅ {phone} 2FA verified!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_listaccounts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    rows = db_list_accounts()
    if not rows:
        await update.message.reply_text("📭 Account የለም")
        return
    now = datetime.now()
    lines = ["📋 Accounts:\n"]
    for aid, label, phone, is_active, session, flood_until in rows:
        status = "✅" if is_active else "❌"
        has_session = "🔑" if session else "⚠️ no session"
        flood = ""
        if flood_until and flood_until > now:
            remaining = int((flood_until - now).total_seconds() / 60)
            flood = f" 🚫 flood {remaining}min"
        lines.append(f"{status} [{label}] {phone} {has_session}{flood}")
    await update.message.reply_text("\n".join(lines))


async def cmd_deleteaccount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /deleteaccount +phone")
        return
    db_delete_account(args[1])
    await update.message.reply_text(f"✅ {args[1]} ተሰረዘ!")


async def cmd_setactivegroup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /setactivegroup -100xxxxxxx")
        return
    try:
        group_id = int(args[1])
        db_set_setting("active_group_id", str(group_id))
        await update.message.reply_text(f"✅ Active group set: {group_id}")
    except ValueError:
        await update.message.reply_text("❌ Group ID ቁጥር መሆን አለበት!")


async def cmd_settargetgroup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /settargetgroup -100xxxxxxx")
        return
    try:
        group_id = int(args[1])
        db_set_setting("target_group_id", str(group_id))
        await update.message.reply_text(f"✅ Target group set: {group_id}")
    except ValueError:
        await update.message.reply_text("❌ Group ID ቁጥር መሆን አለበት!")


async def cmd_addgroup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /addgroup -100xxxxxxx")
        return
    try:
        group_id = int(args[1])
        db_add_group(group_id)
        await update.message.reply_text(f"✅ Group {group_id} ተጨመረ!")
    except ValueError:
        await update.message.reply_text("❌ Group ID ቁጥር መሆን አለበት!")


async def cmd_listgroups(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    rows = db_list_groups()
    active_group = db_get_setting("active_group_id")
    target_group = db_get_setting("target_group_id")
    if not rows:
        await update.message.reply_text("📭 Group የለም")
        return
    lines = ["📋 Groups:\n"]
    for gid, group_id in rows:
        tags = []
        if str(group_id) == active_group:
            tags.append("🟢 active")
        if str(group_id) == target_group:
            tags.append("🎯 target")
        tag_str = " ".join(tags)
        lines.append(f"🔹 {gid}. {group_id} {tag_str}")
    await update.message.reply_text("\n".join(lines))


async def cmd_deletegroup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /deletegroup -100xxxxxxx")
        return
    try:
        group_id = int(args[1])
        db_delete_group(group_id)
        await update.message.reply_text(f"✅ {group_id} ተሰረዘ!")
    except ValueError:
        await update.message.reply_text("❌ Group ID ቁጥር መሆን አለበት!")


async def _handle_usend(update: Update, label: str):
    if not _is_admin(update.effective_user.id):
        return

    account = db_get_account_by_label(label)
    if not account:
        await update.message.reply_text(f"❌ Account [{label}] አልተገኘም!")
        return
    if not account.get("session"):
        await update.message.reply_text(f"❌ Account [{label}] session የለም!")
        return

    active_group_str = db_get_setting("active_group_id")
    if not active_group_str:
        await update.message.reply_text("❌ Active group አልተቀመጠም!\n/setactivegroup -100xxxxxxx")
        return

    group_id = int(active_group_str)
    msg = update.message

    try:
        client = await _get_client(account)
        try:
            if msg.photo:
                file = await msg.bot.get_file(msg.photo[-1].file_id)
                bio = await file.download_as_bytearray()
                import io
                await client.send_file(group_id, io.BytesIO(bytes(bio)), caption=msg.caption or "")
            elif msg.video:
                file = await msg.bot.get_file(msg.video.file_id)
                bio = await file.download_as_bytearray()
                import io
                await client.send_file(group_id, io.BytesIO(bytes(bio)), caption=msg.caption or "")
            elif msg.document:
                file = await msg.bot.get_file(msg.document.file_id)
                bio = await file.download_as_bytearray()
                import io
                await client.send_file(group_id, io.BytesIO(bytes(bio)), caption=msg.caption or "")
            elif msg.sticker:
                file = await msg.bot.get_file(msg.sticker.file_id)
                bio = await file.download_as_bytearray()
                import io
                await client.send_file(group_id, io.BytesIO(bytes(bio)))
            elif msg.text:
                text_parts = msg.text.split(maxsplit=1)
                text = text_parts[1] if len(text_parts) > 1 else ""
                if not text:
                    await msg.reply_text("❌ መልዕክት ይጻፍ!")
                    return
                await client.send_message(group_id, text)
            else:
                await msg.reply_text("❌ የማይደገፍ media አይነት!")
                return

            await msg.reply_text(f"✅ [{label}] → {group_id} ተላከ!")
        finally:
            await client.disconnect()
    except Exception as e:
        await msg.reply_text(f"❌ Error: {e}")


async def cmd_a(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _handle_usend(update, "a")

async def cmd_b(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _handle_usend(update, "b")

async def cmd_c(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _handle_usend(update, "c")

async def cmd_d(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _handle_usend(update, "d")

async def cmd_e(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _handle_usend(update, "e")


async def handle_admin_dm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin bot ላይ DM ሲልክ → ባለፉት 2 ሰዓት active users ሁሉ ይላካል"""
    if not _is_admin(update.effective_user.id):
        return
    if update.effective_chat.type != "private":
        return

    # ✅ FIX — command ከሆነ userbot/bot handlers ይይዙታል
    if update.message and update.message.text and update.message.text.startswith("/"):
        return

    recent_users = db_get_recent_users(hours=2)
    if not recent_users:
        await update.message.reply_text("📭 ባለፉት 2 ሰዓት message የላኩ users የሉም")
        return

    total = len(recent_users)
    status_msg = await update.message.reply_text(
        f"📤 Broadcast እየጀመረ ነው...\n👥 Users: {total}"
    )

    msg = update.message
    success = failed = 0
    delay = (2 * 3600) / max(total, 1)

    for i, user_id in enumerate(recent_users):
        account = get_next_account()
        if not account:
            await status_msg.edit_text("❌ Available account የለም!")
            return

        try:
            client = await _get_client(account)
            try:
                if msg.photo:
                    file = await msg.bot.get_file(msg.photo[-1].file_id)
                    bio = await file.download_as_bytearray()
                    import io
                    await client.send_file(user_id, io.BytesIO(bytes(bio)), caption=msg.caption or "")
                elif msg.video:
                    file = await msg.bot.get_file(msg.video.file_id)
                    bio = await file.download_as_bytearray()
                    import io
                    await client.send_file(user_id, io.BytesIO(bytes(bio)), caption=msg.caption or "")
                elif msg.document:
                    file = await msg.bot.get_file(msg.document.file_id)
                    bio = await file.download_as_bytearray()
                    import io
                    await client.send_file(user_id, io.BytesIO(bytes(bio)), caption=msg.caption or "")
                elif msg.text:
                    await client.send_message(user_id, msg.text)
                success += 1
            finally:
                await client.disconnect()
        except FloodWaitError as e:
            db_set_flood(account["phone"], e.seconds)
            failed += 1
        except Exception as e:
            logger.warning(f"[Broadcast DM] {user_id}: {e}")
            failed += 1

        if (i + 1) % 10 == 0:
            try:
                await status_msg.edit_text(
                    f"⏳ እየሰራ ነው...\n📊 {i+1}/{total}\n✅ {success}\n❌ {failed}"
                )
            except Exception:
                pass

        await asyncio.sleep(delay + random.uniform(1, 3))

    await status_msg.edit_text(
        f"✅ Broadcast ተጠናቀቀ!\n👥 Total: {total}\n✅ Sent: {success}\n❌ Failed: {failed}"
    )


async def cmd_ubothelp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    active_group = db_get_setting("active_group_id") or "❌ አልተቀመጠም"
    target_group = db_get_setting("target_group_id") or "❌ አልተቀመጠም"
    accounts = db_list_accounts()
    groups = db_list_groups()
    now = datetime.now()

    acc_lines = []
    for _, label, phone, is_active, session, flood_until in accounts:
        status = "✅" if is_active else "❌"
        has_session = "🔑" if session else "⚠️"
        flood = ""
        if flood_until and flood_until > now:
            remaining = int((flood_until - now).total_seconds() / 60)
            flood = f" 🚫{remaining}min"
        acc_lines.append(f"  {status}[{label}] {phone} {has_session}{flood}")

    grp_lines = []
    for _, group_id in groups:
        tags = []
        if str(group_id) == active_group:
            tags.append("🟢")
        if str(group_id) == target_group:
            tags.append("🎯")
        grp_lines.append(f"  🔹{group_id} {''.join(tags)}")

    text = (
        "🤖 Userbot Status & Commands\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"🟢 Active Group: {active_group}\n"
        f"🎯 Target Group: {target_group}\n\n"
        "👤 Accounts:\n" +
        ("\n".join(acc_lines) if acc_lines else "  📭 የለም") +
        "\n\n🏠 Groups:\n" +
        ("\n".join(grp_lines) if grp_lines else "  📭 የለም") +
        "\n\n━━━━━━━━━━━━━━━━\n"
        "⚙️ Setup:\n"
        "/addaccount a api_id api_hash +phone\n"
        "/startsession +phone\n"
        "/verifycode +phone code\n"
        "/verify2fa +phone password\n"
        "/listaccounts\n"
        "/deleteaccount +phone\n\n"
        "/addgroup -100xxxxxxx\n"
        "/listgroups\n"
        "/deletegroup -100xxxxxxx\n\n"
        "/setactivegroup -100xxxxxxx\n"
        "  → /a /b /c /d ለሚልኩበት group\n\n"
        "/settargetgroup -100xxxxxxx\n"
        "  → Auto add ለሚሄድበት group\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "⚡ Send:\n"
        "/a መልዕክት (ወይም photo/video/sticker)\n"
        "/b /c /d /e መልዕክት\n\n"
        "📢 Broadcast:\n"
        "Bot ላይ DM ይላኩ → ባለፉት 2 ሰዓት\n"
        "active users ሁሉ ይደርሳቸዋል\n"
    )
    await update.message.reply_text(text)


async def cmd_status2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_ubothelp(update, ctx)


# ============================================================
# REGISTER ALL HANDLERS
# ============================================================

def register_userbot_handlers(app):
    app.add_handler(CommandHandler("addaccount", cmd_addaccount))
    app.add_handler(CommandHandler("startsession", cmd_startsession))
    app.add_handler(CommandHandler("verifycode", cmd_verifycode))
    app.add_handler(CommandHandler("verify2fa", cmd_verify2fa))
    app.add_handler(CommandHandler("listaccounts", cmd_listaccounts))
    app.add_handler(CommandHandler("deleteaccount", cmd_deleteaccount))
    app.add_handler(CommandHandler("addgroup", cmd_addgroup))
    app.add_handler(CommandHandler("listgroups", cmd_listgroups))
    app.add_handler(CommandHandler("deletegroup", cmd_deletegroup))
    app.add_handler(CommandHandler("setactivegroup", cmd_setactivegroup))
    app.add_handler(CommandHandler("settargetgroup", cmd_settargetgroup))
    app.add_handler(CommandHandler("a", cmd_a))
    app.add_handler(CommandHandler("b", cmd_b))
    app.add_handler(CommandHandler("c", cmd_c))
    app.add_handler(CommandHandler("d", cmd_d))
    app.add_handler(CommandHandler("e", cmd_e))
    app.add_handler(CommandHandler("ubothelp", cmd_ubothelp))
    app.add_handler(CommandHandler("status2", cmd_status2))

    # ✅ FIX — command check አለው ስለዚህ /listaccounts ወዘተ አይጠልፈውም
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.User(ADMIN_IDS),
        handle_admin_dm
    ))

    logger.info("✅ Userbot handlers registered")
