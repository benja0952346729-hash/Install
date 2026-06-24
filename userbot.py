"""
userbot.py — Telethon-based userbot commands
ወደ main.py ለማጨመር:

    from userbot import register_userbot_handlers, init_userbot_db

    # main() ውስጥ init_db() ቀጥሎ:
    init_userbot_db()

    # app handlers ከመጨመሩ በፊት:
    register_userbot_handlers(app)
"""

import asyncio
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import AddContactRequest
from telethon.tl.functions.channels import InviteToChannelRequest
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from database import get_conn
from config import ADMIN_IDS

logger = logging.getLogger(__name__)


# ============================================================
# DB INIT
# ============================================================

def init_userbot_db():
    """userbot tables ብቻ ይጨምራል - main.py init_db() ቀጥሎ ይጠራል"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS userbot_accounts (
            id SERIAL PRIMARY KEY,
            api_id BIGINT NOT NULL,
            api_hash TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            session TEXT DEFAULT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS userbot_groups (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            added_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ Userbot DB tables ready")


# ============================================================
# DB HELPERS
# ============================================================

def db_add_account(api_id: int, api_hash: str, phone: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_accounts (api_id, api_hash, phone)
        VALUES (%s, %s, %s)
        ON CONFLICT (phone) DO UPDATE SET api_id=%s, api_hash=%s
    """, (api_id, api_hash, phone, api_id, api_hash))
    conn.commit()
    cur.close()
    conn.close()


def db_list_accounts():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, phone, is_active, session FROM userbot_accounts ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def db_get_account(phone: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, api_id, api_hash, phone, session, is_active FROM userbot_accounts WHERE phone=%s",
        (phone,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "api_id": row[1], "api_hash": row[2],
        "phone": row[3], "session": row[4], "is_active": row[5]
    }


def db_save_session(phone: str, session: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE userbot_accounts SET session=%s WHERE phone=%s", (session, phone))
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


def db_add_group(username: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_groups (username)
        VALUES (%s) ON CONFLICT (username) DO NOTHING
    """, (username,))
    conn.commit()
    cur.close()
    conn.close()


def db_list_groups():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM userbot_groups ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def db_delete_group(username: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM userbot_groups WHERE username=%s", (username,))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# ADMIN CHECK
# ============================================================

def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


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
# GROUP ENTITY HELPER — @username ወይም group ID ሁለቱም ይሰራሉ
# ============================================================

def _parse_group(group_str: str):
    """@username ወይም -100xxxxxxx group ID ወደ entity argument ይቀይራል"""
    group_str = group_str.strip()
    try:
        return int(group_str)
    except ValueError:
        return group_str


# ============================================================
# CORE ACTIONS
# ============================================================

async def _add_contacts(account: dict, group_username: str, status_cb=None):
    """Group members ሁሉ contact ያደርጋቸዋል"""
    client = await _get_client(account)
    try:
        group = await client.get_entity(_parse_group(group_username))
        participants = await client.get_participants(group)
        total = len(participants)
        success = failed = 0

        for i, user in enumerate(participants):
            if user.bot:
                continue
            try:
                await client(AddContactRequest(
                    id=user.id,
                    first_name=user.first_name or "User",
                    last_name=user.last_name or "",
                    phone=user.phone or "",
                    add_phone_privacy_exception=False
                ))
                success += 1
            except Exception as e:
                failed += 1
                logger.warning(f"[AddContact] {user.id}: {e}")

            if status_cb and (i + 1) % 10 == 0:
                await status_cb(i + 1, total, success, failed)

            await asyncio.sleep(1)

        return success, failed
    finally:
        await client.disconnect()


async def _invite_to_group(account: dict, group_username: str, status_cb=None):
    """Contacts ሁሉ group ይጨምራቸዋል"""
    client = await _get_client(account)
    try:
        group = await client.get_entity(_parse_group(group_username))
        contacts = await client.get_contacts()
        total = len(contacts)
        success = failed = 0

        for i, contact in enumerate(contacts):
            try:
                await client(InviteToChannelRequest(
                    channel=group,
                    users=[contact.id]
                ))
                success += 1
            except Exception as e:
                failed += 1
                logger.warning(f"[Invite] {contact.id}: {e}")

            if status_cb and (i + 1) % 10 == 0:
                await status_cb(i + 1, total, success, failed)

            await asyncio.sleep(2)

        return success, failed
    finally:
        await client.disconnect()


async def _broadcast_dm(account: dict, group_username: str, message: str, status_cb=None):
    """Group members ሁሉ DM ይልካቸዋል"""
    client = await _get_client(account)
    try:
        group = await client.get_entity(_parse_group(group_username))
        participants = await client.get_participants(group)
        total = len(participants)
        success = failed = 0

        for i, user in enumerate(participants):
            if user.bot:
                continue
            try:
                await client.send_message(user.id, message)
                success += 1
            except Exception as e:
                failed += 1
                logger.warning(f"[Broadcast] {user.id}: {e}")

            if status_cb and (i + 1) % 10 == 0:
                await status_cb(i + 1, total, success, failed)

            await asyncio.sleep(2)

        return success, failed
    finally:
        await client.disconnect()


async def _send_to_group(account: dict, group_username: str, message: str):
    """Group ውስጥ message ይልካል"""
    client = await _get_client(account)
    try:
        await client.send_message(_parse_group(group_username), message)
    finally:
        await client.disconnect()


# ============================================================
# PENDING SESSIONS (phone verify)
# ============================================================

_pending_sessions: dict = {}


# ============================================================
# COMMAND HANDLERS
# ============================================================

async def cmd_addaccount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/addaccount api_id api_hash +phone"""
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=3)
    if len(args) < 4:
        await update.message.reply_text(
            "❌ Format:\n/addaccount api_id api_hash +phone\n\n"
            "ምሳሌ:\n/addaccount 12345 abc123 +251911234567"
        )
        return
    try:
        api_id = int(args[1])
        api_hash = args[2]
        phone = args[3]
        db_add_account(api_id, api_hash, phone)
        await update.message.reply_text(
            f"✅ Account {phone} ተጨመረ!\n\n"
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
    account = db_get_account(phone)
    if not account:
        await update.message.reply_text(f"❌ {phone} አልተገኘም! /addaccount ይጠቀም")
        return
    if account.get("session"):
        await update.message.reply_text(f"✅ {phone} session አለው! ዝግጁ ነው።")
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
        await update.message.reply_text(f"❌ {phone} pending session የለም! /startsession ይጠቀም")
        return
    try:
        await client.sign_in(phone=phone, code=code)
        session_str = client.session.save()
        db_save_session(phone, session_str)
        _pending_sessions.pop(phone, None)
        await update.message.reply_text(f"✅ {phone} verified! Session ተቀምጧል!")
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
    lines = ["📋 Accounts:\n"]
    for aid, phone, is_active, session in rows:
        status = "✅" if is_active else "❌"
        has_session = "🔑" if session else "⚠️ no session"
        lines.append(f"{status} {aid}. {phone} {has_session}")
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


async def cmd_addgroup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /addgroup @username")
        return
    db_add_group(args[1])
    await update.message.reply_text(f"✅ Group {args[1]} ተጨመረ!")


async def cmd_listgroups(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    rows = db_list_groups()
    if not rows:
        await update.message.reply_text("📭 Group የለም")
        return
    lines = ["📋 Groups:\n"]
    for gid, username in rows:
        lines.append(f"🔹 {gid}. {username}")
    await update.message.reply_text("\n".join(lines))


async def cmd_deletegroup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /deletegroup @username")
        return
    db_delete_group(args[1])
    await update.message.reply_text(f"✅ {args[1]} ተሰረዘ!")


async def cmd_addcontacts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=2)
    if len(args) < 3:
        await update.message.reply_text(
            "❌ Format: /addcontacts +phone @group\n"
            "ምሳሌ: /addcontacts +251911234567 @mybingo"
        )
        return

    phone, group_username = args[1], args[2]
    account = db_get_account(phone)
    if not account:
        await update.message.reply_text(f"❌ {phone} አልተገኘም!")
        return
    if not account.get("session"):
        await update.message.reply_text(f"❌ {phone} session የለም!\n/startsession {phone}")
        return

    status_msg = await update.message.reply_text("⏳ Contact እያደረገ ነው...")

    async def progress(current, total, success, failed):
        try:
            await status_msg.edit_text(
                f"⏳ እየሰራ ነው...\n📊 {current}/{total}\n✅ {success}\n❌ {failed}"
            )
        except Exception:
            pass

    try:
        success, failed = await _add_contacts(account, group_username, progress)
        await status_msg.edit_text(
            f"✅ ተጠናቀቀ!\n✅ Contact ሆኑ: {success}\n❌ አልሆኑም: {failed}"
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {e}")


async def cmd_inviteall(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=2)
    if len(args) < 3:
        await update.message.reply_text(
            "❌ Format: /inviteall +phone @group\n"
            "ምሳሌ: /inviteall +251911234567 @mybingo"
        )
        return

    phone, group_username = args[1], args[2]
    account = db_get_account(phone)
    if not account:
        await update.message.reply_text(f"❌ {phone} አልተገኘም!")
        return
    if not account.get("session"):
        await update.message.reply_text(f"❌ {phone} session የለም!\n/startsession {phone}")
        return

    status_msg = await update.message.reply_text("⏳ Invite እያደረገ ነው...")

    async def progress(current, total, success, failed):
        try:
            await status_msg.edit_text(
                f"⏳ እየሰራ ነው...\n📊 {current}/{total}\n✅ {success}\n❌ {failed}"
            )
        except Exception:
            pass

    try:
        success, failed = await _invite_to_group(account, group_username, progress)
        await status_msg.edit_text(
            f"✅ ተጠናቀቀ!\n✅ Invited: {success}\n❌ Failed: {failed}"
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {e}")


async def cmd_ubroadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=3)
    if len(args) < 4:
        await update.message.reply_text(
            "❌ Format: /ubroadcast +phone @group መልዕክት\n"
            "ምሳሌ: /ubroadcast +251911234567 @mybingo ሰላም!"
        )
        return

    phone, group_username, message = args[1], args[2], args[3]
    account = db_get_account(phone)
    if not account:
        await update.message.reply_text(f"❌ {phone} አልተገኘም!")
        return
    if not account.get("session"):
        await update.message.reply_text(f"❌ {phone} session የለም!\n/startsession {phone}")
        return

    status_msg = await update.message.reply_text("⏳ DM እየላከ ነው...")

    async def progress(current, total, success, failed):
        try:
            await status_msg.edit_text(
                f"⏳ እየሰራ ነው...\n📊 {current}/{total}\n✅ {success}\n❌ {failed}"
            )
        except Exception:
            pass

    try:
        success, failed = await _broadcast_dm(account, group_username, message, progress)
        await status_msg.edit_text(
            f"✅ ተጠናቀቀ!\n✅ Sent: {success}\n❌ Failed: {failed}"
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {e}")


async def cmd_usend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=3)
    if len(args) < 4:
        await update.message.reply_text(
            "❌ Format: /usend +phone @group መልዕክት\n"
            "ምሳሌ: /usend +251911234567 @mybingo ሰላም!"
        )
        return

    phone, group_username, message = args[1], args[2], args[3]
    account = db_get_account(phone)
    if not account:
        await update.message.reply_text(f"❌ {phone} አልተገኘም!")
        return
    if not account.get("session"):
        await update.message.reply_text(f"❌ {phone} session የለም!")
        return

    try:
        await _send_to_group(account, group_username, message)
        await update.message.reply_text(f"✅ {group_username} ላይ ተላከ!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_ubothelp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    text = (
        "🤖 Userbot Commands:\n\n"
        "👤 Accounts:\n"
        "/addaccount api_id api_hash +phone\n"
        "/startsession +phone\n"
        "/verifycode +phone code\n"
        "/verify2fa +phone password\n"
        "/listaccounts\n"
        "/deleteaccount +phone\n\n"
        "🏠 Groups:\n"
        "/addgroup @username\n"
        "/listgroups\n"
        "/deletegroup @username\n\n"
        "⚡ Actions:\n"
        "/addcontacts +phone @group\n"
        "  → Group members contact ያደርጋቸዋል\n\n"
        "/inviteall +phone @group\n"
        "  → Contacts group ይጨምራቸዋል\n\n"
        "/ubroadcast +phone @group መልዕክት\n"
        "  → Members ሁሉ DM ይልካቸዋል\n\n"
        "/usend +phone @group መልዕክት\n"
        "  → Group ውስጥ message ይልካል\n"
    )
    await update.message.reply_text(text)


# ============================================================
# REGISTER ALL HANDLERS — main.py ውስጥ አንድ ጊዜ ይጠራል
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
    app.add_handler(CommandHandler("addcontacts", cmd_addcontacts))
    app.add_handler(CommandHandler("inviteall", cmd_inviteall))
    app.add_handler(CommandHandler("ubroadcast", cmd_ubroadcast))
    app.add_handler(CommandHandler("usend", cmd_usend))
    app.add_handler(CommandHandler("ubothelp", cmd_ubothelp))
    logger.info("✅ Userbot handlers registered")
