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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

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
        CREATE TABLE IF NOT EXISTS userbot_admins (
            user_id BIGINT PRIMARY KEY,
            added_by BIGINT NOT NULL,
            added_at TIMESTAMP DEFAULT NOW()
        )
    """)

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
            is_listener BOOLEAN DEFAULT FALSE,
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
            group_id BIGINT UNIQUE,
            group_name TEXT DEFAULT NULL,
            is_source BOOLEAN DEFAULT FALSE,
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS userbot_blocked_users (
            user_id BIGINT PRIMARY KEY,
            blocked_at TIMESTAMP DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS userbot_daily_adds (
            account_label CHAR(1) NOT NULL,
            add_date DATE NOT NULL DEFAULT CURRENT_DATE,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (account_label, add_date)
        )
    """)

    cur.execute("""
        ALTER TABLE userbot_accounts
        ADD COLUMN IF NOT EXISTS label CHAR(1) UNIQUE
    """)
    cur.execute("""
        ALTER TABLE userbot_accounts
        ADD COLUMN IF NOT EXISTS flood_until TIMESTAMP DEFAULT NULL
    """)
    cur.execute("""
        ALTER TABLE userbot_accounts
        ADD COLUMN IF NOT EXISTS is_listener BOOLEAN DEFAULT FALSE
    """)

    cur.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='userbot_groups' AND column_name='username'
            ) THEN
                ALTER TABLE userbot_groups DROP COLUMN username;
            END IF;
        END $$;
    """)

    cur.execute("""
        ALTER TABLE userbot_groups
        ADD COLUMN IF NOT EXISTS group_id BIGINT UNIQUE
    """)
    cur.execute("""
        ALTER TABLE userbot_groups
        ADD COLUMN IF NOT EXISTS group_name TEXT DEFAULT NULL
    """)
    cur.execute("""
        ALTER TABLE userbot_groups
        ADD COLUMN IF NOT EXISTS is_source BOOLEAN DEFAULT FALSE
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_groups_source
        ON userbot_groups(group_id)
        WHERE is_source = TRUE
    """)

    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ Userbot DB tables ready")


# ============================================================
# ADMIN DB HELPERS
# ============================================================

def db_add_uadmin(user_id: int, added_by: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_admins (user_id, added_by)
        VALUES (%s, %s)
        ON CONFLICT (user_id) DO NOTHING
    """, (user_id, added_by))
    conn.commit()
    cur.close()
    conn.close()


def db_remove_uadmin(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM userbot_admins WHERE user_id=%s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()


def db_list_uadmins():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, added_by, added_at FROM userbot_admins ORDER BY added_at")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def db_is_uadmin(user_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM userbot_admins WHERE user_id=%s", (user_id,))
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists


# ============================================================
# ADMIN CHECK
# ============================================================

def _is_main_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _is_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    return db_is_uadmin(user_id)


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
    cur.execute("SELECT id, label, phone, is_active, session, flood_until, is_listener FROM userbot_accounts ORDER BY label")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def db_get_account_by_label(label: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, label, api_id, api_hash, phone, session, is_active, flood_until, is_listener FROM userbot_accounts WHERE label=%s",
        (label,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "label": row[1], "api_id": row[2], "api_hash": row[3],
        "phone": row[4], "session": row[5], "is_active": row[6], "flood_until": row[7],
        "is_listener": row[8]
    }


def db_get_account_by_phone(phone: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, label, api_id, api_hash, phone, session, is_active, flood_until, is_listener FROM userbot_accounts WHERE phone=%s",
        (phone,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "label": row[1], "api_id": row[2], "api_hash": row[3],
        "phone": row[4], "session": row[5], "is_active": row[6], "flood_until": row[7],
        "is_listener": row[8]
    }


def db_get_all_accounts():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, label, api_id, api_hash, phone, session, is_active, flood_until, is_listener FROM userbot_accounts WHERE is_active=TRUE ORDER BY label"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {"id": r[0], "label": r[1], "api_id": r[2], "api_hash": r[3],
         "phone": r[4], "session": r[5], "is_active": r[6], "flood_until": r[7],
         "is_listener": r[8]}
        for r in rows
    ]


def db_get_all_listeners():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, label, api_id, api_hash, phone, session, is_active, flood_until, is_listener FROM userbot_accounts WHERE is_active=TRUE AND is_listener=TRUE ORDER BY label"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {"id": r[0], "label": r[1], "api_id": r[2], "api_hash": r[3],
         "phone": r[4], "session": r[5], "is_active": r[6], "flood_until": r[7],
         "is_listener": r[8]}
        for r in rows
    ]


def db_set_listener(phone: str, is_listener: bool):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE userbot_accounts SET is_listener=%s WHERE phone=%s", (is_listener, phone))
    conn.commit()
    cur.close()
    conn.close()


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


def db_add_group(group_id: int, group_name: str = None, is_source: bool = False):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_groups (group_id, group_name, is_source)
        VALUES (%s, %s, %s)
        ON CONFLICT (group_id) DO UPDATE SET
            group_name=COALESCE(EXCLUDED.group_name, userbot_groups.group_name),
            is_source=CASE WHEN EXCLUDED.is_source THEN TRUE ELSE userbot_groups.is_source END
    """, (group_id, group_name, is_source))
    conn.commit()
    cur.close()
    conn.close()


def db_list_groups():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, group_id, group_name, is_source FROM userbot_groups WHERE group_id IS NOT NULL ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def db_set_group_source(group_id: int, is_source: bool):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE userbot_groups SET is_source=%s WHERE group_id=%s", (is_source, group_id))
    conn.commit()
    cur.close()
    conn.close()


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


def db_mark_user_blocked(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_blocked_users (user_id) VALUES (%s)
        ON CONFLICT DO NOTHING
    """, (user_id,))
    conn.commit()
    cur.close()
    conn.close()


def db_get_all_blocked() -> set:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM userbot_blocked_users")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {r[0] for r in rows}


def db_cleanup_old_messages(hours: int = 24):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM userbot_recent_messages
        WHERE sent_at < NOW() - INTERVAL '%s hours'
    """, (hours,))
    conn.commit()
    cur.close()
    conn.close()


DAILY_ADD_LIMIT = 170


def db_get_daily_add_count(label: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT count FROM userbot_daily_adds
        WHERE account_label=%s AND add_date=CURRENT_DATE
    """, (label,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else 0


def db_increment_daily_add(label: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_daily_adds (account_label, add_date, count)
        VALUES (%s, CURRENT_DATE, 1)
        ON CONFLICT (account_label, add_date) DO UPDATE SET count = userbot_daily_adds.count + 1
    """, (label,))
    conn.commit()
    cur.close()
    conn.close()


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
        if a["session"]
        and not a.get("is_listener")
        and (a["flood_until"] is None or a["flood_until"] < now)
        and db_get_daily_add_count(a["label"]) < DAILY_ADD_LIMIT
    ]
    if not available:
        return None
    account = available[_rr_index % len(available)]
    _rr_index += 1
    return account


# ============================================================
# ADMIN CACHE
# ============================================================

_admin_cache: dict = {}


async def _is_admin_or_owner(client, user_id: int, group_id: int) -> bool:
    cache_key = (user_id, group_id)
    if cache_key in _admin_cache:
        return _admin_cache[cache_key]
    try:
        participant = await client.get_permissions(group_id, user_id)
        result = participant.is_admin or participant.is_creator
    except Exception as e:
        logger.warning(f"[AutoAdd-DEBUG] get_permissions failed for user={user_id} group={group_id}: {e}")
        result = False
    _admin_cache[cache_key] = result
    return result


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
# NORMALIZE HELPERS
# ============================================================

def _normalize_chat_id(event) -> int:
    peer = event.message.peer_id
    if hasattr(peer, 'channel_id'):
        return int(f"-100{peer.channel_id}")
    elif hasattr(peer, 'chat_id'):
        return int(f"-{peer.chat_id}")
    return event.chat_id


def _normalize_source_id(gid) -> int:
    s = str(abs(int(gid)))
    if not s.startswith("100"):
        s = "100" + s
    return int(f"-{s}")


# ============================================================
# CORE ACTIONS
# ============================================================

async def _contact_and_add_by_sender(account: dict, sender, target_group_id: int):
    """
    ✅ FIX: sender object (ሌላ client's cache object) ቀጥታ አይተላለፍም ለ InviteToChannelRequest።
    Worker ራሱ user_id ተጠቅሞ own session ላይ resolve ያደርጋል፦
      STEP 1: worker's own cache ላይ ቀድሞ ካለ (worker ራሱ group's member ቢሆን) → ቀጥታ ይሰራል
      STEP 2: cache ላይ ከሌለ → AddContactRequest ይሞከር (phone ካለ access_hash ይፈጠራል)
      STEP 3: ድጋሚ resolve ይሞከር
      STEP 4: ምንም ካልሰራ → privacy-restricted, graceful skip
    """
    client = await _get_client(account)
    try:
        user_id = sender.id
        first_name = sender.first_name or "User"
        last_name = sender.last_name or ""
        phone = sender.phone or ""

        # ✅ STEP 1 — worker's own cache (e.g. worker ራሱ ያ group's member ቢሆን)
        resolved_user = None
        try:
            resolved_user = await client.get_entity(user_id)
            logger.info(f"[Resolve] ✅ [{account['label']}] {user_id} resolved from own cache")
        except Exception as e:
            logger.info(f"[Resolve] [{account['label']}] {user_id} not in cache yet: {e}")

        # ✅ STEP 2 — contact ለማድረግ ይሞከር (access_hash ይፈጥራል)
        if not resolved_user:
            if not db_is_user_contacted(user_id, account["label"]):
                try:
                    await client(AddContactRequest(
                        id=user_id,
                        first_name=first_name,
                        last_name=last_name,
                        phone=phone,
                        add_phone_privacy_exception=False
                    ))
                    db_mark_user_contacted(user_id, account["label"])
                    logger.info(f"[Contact] ✅ [{account['label']}] contacted {user_id}")
                except FloodWaitError as e:
                    db_set_flood(account["phone"], e.seconds)
                    logger.warning(f"[Contact] Flood {account['label']}: {e.seconds}s")
                    return
                except Exception as e:
                    logger.warning(f"[Contact] [{account['label']}] {user_id}: {e}")

            # ✅ STEP 3 — contact ካደረገ በኋላ ድጋሚ resolve
            try:
                resolved_user = await client.get_entity(user_id)
                logger.info(f"[Resolve] ✅ [{account['label']}] {user_id} resolved after contact")
            except Exception as e:
                logger.warning(f"[Resolve] [{account['label']}] still cannot resolve {user_id}: {e}")

        # ✅ STEP 4 — ምንም ካልሰራ → privacy restricted, skip
        if not resolved_user:
            logger.warning(f"[Add] [{account['label']}] ⏭ user {user_id} unresolvable — privacy restricted, skip")
            return

        if not db_is_user_added(user_id, target_group_id):
            try:
                group = await client.get_entity(target_group_id)
                await client(InviteToChannelRequest(channel=group, users=[resolved_user]))
                db_mark_user_added(user_id, target_group_id)
                db_increment_daily_add(account["label"])
                logger.info(f"✅ Added {user_id} → {target_group_id}")
            except FloodWaitError as e:
                db_set_flood(account["phone"], e.seconds)
                logger.warning(f"[Add] Flood {account['label']}: {e.seconds}s")
            except Exception as e:
                logger.warning(f"[Add] [{account['label']}] {user_id}: {e}")
        else:
            logger.info(f"[AutoAdd-DEBUG] ⏭ user={user_id} already added to {target_group_id} — skip add step")
    finally:
        await client.disconnect()


# ============================================================
# ✅ NEW — WORKER AUTO-JOIN TO SOURCE GROUP
# Source group connect (✅) ሲደረግ workers (a-e) auto-add ይደረጋሉ
# ወደ source group፣ 15-25s random gap ይዘው (Telegram flood ageda)
# ============================================================

async def _add_workers_to_source_group(group_id: int):
    """
    Listener ራሱ workers (non-listener accounts) ወደ source group ይጨምራል፣
    ቀድሞ member ያልሆኑትን ብቻ፣ 15-25s gap በመካከል።
    """
    listeners = db_get_all_listeners()
    if not listeners:
        logger.warning("[WorkerAutoJoin] ⚠️ listener account የለም — workers አይታከሉም")
        return

    accounts = db_get_all_accounts()
    workers = [a for a in accounts if not a.get("is_listener") and a.get("session")]

    if not workers:
        logger.info("[WorkerAutoJoin] ⏭ worker accounts የለም")
        return

    listener_account = listeners[0]
    listener_client = await _get_client(listener_account)
    try:
        try:
            group_entity = await listener_client.get_entity(group_id)
        except Exception as e:
            logger.warning(f"[WorkerAutoJoin] ❌ listener cannot resolve group {group_id}: {e}")
            return

        # ✅ Source group's current members ይፍተሽ — ቀድሞ ያሉ workers skip
        existing_member_ids = set()
        try:
            async for participant in listener_client.iter_participants(group_entity):
                existing_member_ids.add(participant.id)
        except Exception as e:
            logger.warning(f"[WorkerAutoJoin] ⚠️ cannot list participants: {e}")

        added_count = 0
        skipped_count = 0

        for worker in workers:
            try:
                worker_client = await _get_client(worker)
                try:
                    worker_me = await worker_client.get_me()
                    worker_user_id = worker_me.id
                finally:
                    await worker_client.disconnect()

                if worker_user_id in existing_member_ids:
                    logger.info(f"[WorkerAutoJoin] ⏭ [{worker['label']}] already in source group — skip")
                    skipped_count += 1
                    continue

                # ✅ Listener ራሱ worker'ን ይጨምር
                worker_input = await listener_client.get_entity(worker_user_id)
                await listener_client(InviteToChannelRequest(channel=group_entity, users=[worker_input]))
                added_count += 1
                logger.info(f"[WorkerAutoJoin] ✅ [{worker['label']}] added to source group {group_id}")

            except FloodWaitError as e:
                db_set_flood(listener_account["phone"], e.seconds)
                logger.warning(f"[WorkerAutoJoin] Flood on listener: {e.seconds}s — stopping")
                break
            except Exception as e:
                logger.warning(f"[WorkerAutoJoin] ❌ [{worker['label']}] failed: {e}")

            # ✅ 15-25s random gap — Telegram flood ageda
            gap = random.uniform(15, 25)
            logger.info(f"[WorkerAutoJoin] ⏳ waiting {gap:.1f}s before next worker...")
            await asyncio.sleep(gap)

        logger.info(f"[WorkerAutoJoin] 🏁 done — added: {added_count}, skipped: {skipped_count}")

    finally:
        await listener_client.disconnect()


# ============================================================
# AUTO-DETECT GROUPS
# ============================================================

async def _auto_detect_groups(account: dict):
    client = await _get_client(account)
    count = 0
    try:
        async for dialog in client.iter_dialogs():
            if dialog.is_group or dialog.is_channel:
                normalized_id = _normalize_source_id(dialog.id)
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO userbot_groups (group_id, group_name, is_source)
                    VALUES (%s, %s, FALSE)
                    ON CONFLICT (group_id) DO UPDATE SET
                        group_name=COALESCE(EXCLUDED.group_name, userbot_groups.group_name)
                """, (normalized_id, dialog.name))
                conn.commit()
                cur.close()
                conn.close()
                count += 1
        logger.info(f"✅ [{account['label']}] auto-detected {count} groups")
    except Exception as e:
        logger.warning(f"[AutoDetect] {account['label']}: {e}")
    finally:
        await client.disconnect()


async def _sync_all_account_groups():
    listeners = db_get_all_listeners()
    for account in listeners:
        if account.get("session"):
            await _auto_detect_groups(account)


# ============================================================
# TELETHON EVENT LISTENERS — ✅ source groups ብቻ
# ✅ DEBUG logs ለ event trigger ማረጋገጥ ተጨምሯል
# ============================================================

_telethon_clients = []


async def _reload_listeners():
    global _telethon_clients
    for client in _telethon_clients:
        try:
            await client.disconnect()
        except Exception:
            pass
    _telethon_clients = []

    await _sync_all_account_groups()

    groups = db_list_groups()
    source_ids = [_normalize_source_id(g[1]) for g in groups if g[3]]

    if not source_ids:
        logger.warning("[Reload] ⚠️ source group የለም — listeners አይጀምሩም")
        return

    logger.info(f"[Reload] ✅ source groups: {source_ids}")

    listeners = db_get_all_listeners()
    for account in listeners:
        if not account.get("session"):
            continue
        try:
            client = TelegramClient(
                StringSession(account["session"]),
                account["api_id"],
                account["api_hash"]
            )
            await client.start()

            # ✅ DEBUG: client ራሱ source entity resolve ይቻል/አይቻል
            for sid in source_ids:
                try:
                    entity = await client.get_entity(sid)
                    logger.info(f"[AutoAdd-DEBUG] ✅ [{account['label']}] resolved entity for {sid}: {getattr(entity, 'title', entity)}")
                except Exception as e:
                    logger.warning(f"[AutoAdd-DEBUG] ❌ [{account['label']}] CANNOT resolve entity for {sid}: {e}")

            # ✅ DEBUG: ምንም filter ሳይኖር ALL messages
            @client.on(events.NewMessage())
            async def debug_any_handler(event, acc=account):
                try:
                    raw_chat_id = event.chat_id
                    normalized = _normalize_chat_id(event)
                    logger.info(
                        f"[AutoAdd-DEBUG] 🟡 [{acc['label']}] ANY message seen | "
                        f"raw_chat_id={raw_chat_id} | normalized={normalized} | "
                        f"is_source_match={normalized in source_ids}"
                    )
                except Exception as e:
                    logger.warning(f"[AutoAdd-DEBUG] debug_any_handler error: {e}")

            # ✅ source groups ብቻ ያዳምጣል (ኦርጅናል logic)
            @client.on(events.NewMessage(chats=source_ids))
            async def handler(event, acc=account):
                try:
                    chat_id = _normalize_chat_id(event)

                    logger.info(f"[AutoAdd] 📨 msg from chat {chat_id}")

                    sender = await event.get_sender()
                    if not sender:
                        logger.info("[AutoAdd-DEBUG] ⏭ sender is None — skip")
                        return
                    if sender.bot:
                        logger.info(f"[AutoAdd-DEBUG] ⏭ sender {sender.id} is bot — skip")
                        return
                    if sender.is_self:
                        logger.info("[AutoAdd-DEBUG] ⏭ sender is self — skip")
                        return

                    user_id = sender.id
                    logger.info(f"[AutoAdd] 👤 user {user_id} ({sender.first_name})")

                    check_client = await _get_client(acc)
                    try:
                        is_adm = await _is_admin_or_owner(check_client, user_id, chat_id)
                        if is_adm:
                            logger.info(f"[AutoAdd] ⏭ user {user_id} is admin/owner — skip")
                            return
                    finally:
                        await check_client.disconnect()

                    db_record_message(user_id, chat_id)

                    target_str = db_get_setting("target_group_id")
                    if not target_str:
                        logger.warning("[AutoAdd] ⚠️ target_group_id አልተቀመጠም!")
                        return

                    target_group_id = int(target_str)

                    if db_is_user_added(user_id, target_group_id):
                        logger.info(f"[AutoAdd] ⏭ user {user_id} already added — skip")
                        return

                    auto_add = db_get_setting("auto_add_enabled") or "true"
                    if auto_add == "false":
                        logger.info("[AutoAdd] ⏭ auto_add disabled — skip")
                        return

                    chosen = get_next_account()
                    if not chosen:
                        logger.warning("[AutoAdd] ⚠️ available worker account የለም!")
                        return

                    logger.info(f"[AutoAdd] ⚙️ using [{chosen['label']}] to add {user_id}")
                    await asyncio.sleep(random.uniform(2, 5))
                    await _contact_and_add_by_sender(chosen, sender, target_group_id)

                except Exception as e:
                    logger.warning(f"[AutoAdd] ❌ Error: {e}", exc_info=True)

            _telethon_clients.append(client)
            logger.info(f"✅ Listener reloaded: [{account['label']}] {account['phone']}")
        except Exception as e:
            logger.warning(f"[Reload] {account['phone']}: {e}")


async def _cleanup_loop():
    while True:
        await asyncio.sleep(3600)
        db_cleanup_old_messages(24)
        logger.info("✅ Old messages cleaned up")


async def start_listeners():
    asyncio.create_task(_cleanup_loop())
    await _reload_listeners()


# ============================================================
# PENDING SESSIONS
# ============================================================

_pending_sessions: dict = {}


# ============================================================
# COMMAND HANDLERS
# ============================================================

async def cmd_adduadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_main_admin(update.effective_user.id):
        await update.message.reply_text("❌ Main admin ብቻ ነው!")
        return
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /adduadmin user_id")
        return
    try:
        user_id = int(args[1])
        db_add_uadmin(user_id, update.effective_user.id)
        await update.message.reply_text(f"✅ {user_id} userbot admin ሆነ!")
    except ValueError:
        await update.message.reply_text("❌ User ID ቁጥር መሆን አለበት!")


async def cmd_removeuadmin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_main_admin(update.effective_user.id):
        await update.message.reply_text("❌ Main admin ብቻ ነው!")
        return
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /removeuadmin user_id")
        return
    try:
        user_id = int(args[1])
        db_remove_uadmin(user_id)
        await update.message.reply_text(f"✅ {user_id} userbot admin ተወጣ!")
    except ValueError:
        await update.message.reply_text("❌ User ID ቁጥር መሆን አለበት!")


async def cmd_listuadmins(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_main_admin(update.effective_user.id):
        await update.message.reply_text("❌ Main admin ብቻ ነው!")
        return
    rows = db_list_uadmins()
    if not rows:
        await update.message.reply_text("📭 Userbot admin የለም")
        return
    lines = ["👥 Userbot Admins:\n"]
    for user_id, added_by, added_at in rows:
        at = added_at.strftime("%m/%d %H:%M") if added_at else "?"
        lines.append(f"🔹 {user_id} (by {added_by}) — {at}")
    await update.message.reply_text("\n".join(lines))


async def cmd_setuserapi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_main_admin(update.effective_user.id):
        await update.message.reply_text("❌ Main admin ብቻ ነው!")
        return
    args = update.message.text.split(maxsplit=2)
    if len(args) < 3:
        await update.message.reply_text("❌ Format: /setuserapi api_id api_hash")
        return
    try:
        api_id = int(args[1])
        api_hash = args[2]
        db_set_setting("userbot_api_id", str(api_id))
        db_set_setting("userbot_api_hash", api_hash)
        await update.message.reply_text(
            f"✅ Worker API ተቀምጧል!\n🆔 {api_id}\n🔑 {api_hash}"
        )
    except ValueError:
        await update.message.reply_text("❌ api_id ቁጥር መሆን አለበት!")


async def cmd_setuserapi2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_main_admin(update.effective_user.id):
        await update.message.reply_text("❌ Main admin ብቻ ነው!")
        return
    args = update.message.text.split(maxsplit=2)
    if len(args) < 3:
        await update.message.reply_text("❌ Format: /setuserapi2 api_id api_hash")
        return
    try:
        api_id = int(args[1])
        api_hash = args[2]
        db_set_setting("userbot_api_id2", str(api_id))
        db_set_setting("userbot_api_hash2", api_hash)
        await update.message.reply_text(
            f"✅ Listener API ተቀምጧል!\n🆔 {api_id}\n🔑 {api_hash}"
        )
    except ValueError:
        await update.message.reply_text("❌ api_id ቁጥር መሆን አለበት!")


def _get_api_for_account(is_listener: bool) -> tuple:
    if is_listener:
        api_id2 = db_get_setting("userbot_api_id2")
        api_hash2 = db_get_setting("userbot_api_hash2")
        if api_id2 and api_hash2:
            return int(api_id2), api_hash2
    api_id = db_get_setting("userbot_api_id")
    api_hash = db_get_setting("userbot_api_hash")
    if api_id and api_hash:
        return int(api_id), api_hash
    return None, None


async def cmd_addaccount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=2)
    if len(args) < 3:
        await update.message.reply_text(
            "❌ Format:\n/addaccount label +phone\n\n"
            "ምሳሌ:\n/addaccount a +251911234567\n\n"
            "⚠️ API ቀድሞ /setuserapi ተቀምጦ መሆን አለበት!"
        )
        return
    try:
        label = args[1].lower()
        phone = args[2]
        api_id, api_hash = _get_api_for_account(is_listener=False)
        if not api_id or not api_hash:
            await update.message.reply_text(
                "❌ API አልተቀመጠም!\n/setuserapi api_id api_hash ይጠቀም"
            )
            return
        db_add_account(label, api_id, api_hash, phone)
        await update.message.reply_text(
            f"✅ Account [{label}] {phone} ተጨመረ!\n\n"
            f"Session ለማስጀመር:\n/startsession {phone}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_startsession(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split()
    phone = None
    for arg in args[1:]:
        if arg.startswith("+"):
            phone = arg
            break
    if not phone:
        await update.message.reply_text("❌ Format: /startsession +phone")
        return

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


async def cmd_setlistener(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /setlistener +phone")
        return
    phone = args[1]
    account = db_get_account_by_phone(phone)
    if not account:
        await update.message.reply_text(f"❌ {phone} አልተገኘም!")
        return
    db_set_listener(phone, True)

    api_id2, api_hash2 = _get_api_for_account(is_listener=True)
    if api_id2 and api_hash2:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE userbot_accounts SET api_id=%s, api_hash=%s WHERE phone=%s",
            (api_id2, api_hash2, phone)
        )
        conn.commit()
        cur.close()
        conn.close()
        api_note = "\n🔑 Listener API ተቀምጧል"
    else:
        api_note = "\n⚠️ Listener API የለም — Worker API ይጠቀማል"

    await update.message.reply_text(
        f"✅ [{account['label']}] {phone} → Listener ሆነ!{api_note}\n🔄 Reloading..."
    )
    asyncio.create_task(_reload_listeners())


async def cmd_unsetlistener(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /unsetlistener +phone")
        return
    phone = args[1]
    account = db_get_account_by_phone(phone)
    if not account:
        await update.message.reply_text(f"❌ {phone} አልተገኘም!")
        return
    db_set_listener(phone, False)
    await update.message.reply_text(f"✅ [{account['label']}] {phone} → Worker ሆነ!\n🔄 Reloading...")
    asyncio.create_task(_reload_listeners())


async def cmd_listaccounts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    rows = db_list_accounts()
    if not rows:
        await update.message.reply_text("📭 Account የለም")
        return
    now = datetime.now()
    lines = ["📋 Accounts:\n"]
    for aid, label, phone, is_active, session, flood_until, is_listener in rows:
        status = "✅" if is_active else "❌"
        has_session = "🔑" if session else "⚠️ no session"
        role = "👂 Listener" if is_listener else "⚙️ Worker"
        flood = ""
        if flood_until and flood_until > now:
            remaining = int((flood_until - now).total_seconds() / 60)
            flood = f" 🚫 flood {remaining}min"
        daily = db_get_daily_add_count(label) if not is_listener else 0
        daily_str = f" [{daily}/{DAILY_ADD_LIMIT}]" if not is_listener else ""
        lines.append(f"{status} [{label}] {phone} {has_session} {role}{daily_str}{flood}")
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
        group_name = None
        account = get_next_account()
        if account:
            try:
                client = await _get_client(account)
                try:
                    entity = await client.get_entity(group_id)
                    group_name = getattr(entity, "title", None)
                finally:
                    await client.disconnect()
            except Exception:
                group_name = None

        db_add_group(group_id, group_name, is_source=False)
        name_str = f"📛 ስም: {group_name}\n" if group_name else ""
        await update.message.reply_text(
            f"✅ Group ተጨመረ!\n{name_str}🆔 ID: {group_id}\n\n"
            f"Source group ለማድረግ /listgroups ላይ ✅ ን ጫን"
        )
    except ValueError:
        await update.message.reply_text("❌ Group ID ቁጥር መሆን አለበት!")


async def cmd_syncgroups(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    msg = await update.message.reply_text("🔄 Groups እየሳነቀ ነው...")
    await _sync_all_account_groups()
    await msg.edit_text("✅ Groups synced! /listgroups ይጫን")


# ============================================================
# LISTGROUPS — PAGINATED
# ============================================================

PAGE_SIZE = 20


async def cmd_listgroups(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    await _show_groups_list(update.message, edit=False, page=0)


async def _show_groups_list(message, edit: bool = False, page: int = 0):
    rows = db_list_groups()
    active_group = db_get_setting("active_group_id")
    target_group = db_get_setting("target_group_id")
    auto_add_on = (db_get_setting("auto_add_enabled") or "true") == "true"

    if not rows:
        text = "📭 Group የለም\n\n/syncgroups — userbot ያለባቸውን ሁሉ ያምጣ"
        try:
            if edit:
                await message.edit_text(text)
            else:
                await message.reply_text(text)
        except Exception:
            pass
        return

    total = len(rows)
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    page_rows = rows[start: start + PAGE_SIZE]

    auto_status = "🟢 ON" if auto_add_on else "🔴 OFF"
    lines = [f"🤖 Auto-Add: {auto_status}\n📋 Groups ({start+1}-{start+len(page_rows)}/{total}):\n"]
    keyboard = []

    for i, (gid, group_id, group_name, is_source) in enumerate(page_rows):
        num = start + i + 1
        tags = []
        if str(group_id) == active_group:
            tags.append("🟢")
        if str(group_id) == target_group:
            tags.append("🎯")
        tag_str = " ".join(tags)
        name_str = (group_name or str(group_id))[:22]
        source_icon = "✅" if is_source else "⬜"
        lines.append(f"#{num} {source_icon} {name_str} {tag_str}")

        if is_source:
            connect_btn = InlineKeyboardButton(
                f"#{num} 🔴 Disconnect",
                callback_data=f"grp_disconnect:{group_id}:{page}"
            )
        else:
            connect_btn = InlineKeyboardButton(
                f"#{num} ✅ Connect",
                callback_data=f"grp_connect:{group_id}:{page}"
            )
        remove_btn = InlineKeyboardButton("❌", callback_data=f"grp_remove:{group_id}:{page}")
        keyboard.append([connect_btn, remove_btn])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"grp_page:{page-1}"))
    nav_row.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="grp_noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"grp_page:{page+1}"))
    keyboard.append(nav_row)

    toggle_btn = InlineKeyboardButton(
        "🔴 Pause Auto-Add" if auto_add_on else "🟢 Resume Auto-Add",
        callback_data="grp_autoadd_toggle"
    )
    keyboard.append([InlineKeyboardButton("🔄 Sync", callback_data="grp_sync"), toggle_btn])

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "\n".join(lines)

    try:
        if edit:
            await message.edit_text(text, reply_markup=reply_markup)
        else:
            await message.reply_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"[listgroups] {e}")
        try:
            await message.reply_text(text, reply_markup=reply_markup)
        except Exception:
            pass


async def cb_group_action(update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not _is_admin(query.from_user.id):
        await query.answer("❌ Admin ብቻ!")
        return

    await query.answer()
    data = query.data

    if data == "grp_sync":
        await query.edit_message_text("🔄 Syncing...")
        await _sync_all_account_groups()
        await _show_groups_list(query.message, edit=True, page=0)
        return

    if data == "grp_autoadd_toggle":
        current = (db_get_setting("auto_add_enabled") or "true") == "true"
        db_set_setting("auto_add_enabled", "false" if current else "true")
        await _show_groups_list(query.message, edit=True, page=0)
        return

    if data == "grp_noop":
        return

    if data.startswith("grp_page:"):
        page = int(data.split(":")[1])
        await _show_groups_list(query.message, edit=True, page=page)
        return

    parts = data.split(":")
    action = parts[0]
    group_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0

    if action == "grp_connect":
        db_set_group_source(group_id, True)
        # ✅ source group ሲጨመር listeners reload ያድርግ
        asyncio.create_task(_reload_listeners())
        # ✅ NEW: workers (a-e) ወደ source group auto-add ይደረጋሉ (15-25s gap)
        asyncio.create_task(_add_workers_to_source_group(group_id))
    elif action == "grp_disconnect":
        db_set_group_source(group_id, False)
        # ✅ source group ሲወጣ listeners reload ያድርግ
        asyncio.create_task(_reload_listeners())
    elif action == "grp_remove":
        db_delete_group(group_id)

    await _show_groups_list(query.message, edit=True, page=page)


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

    def clean_caption(text):
        if not text:
            return ""
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            return parts[1] if len(parts) > 1 else ""
        return text

    try:
        client = await _get_client(account)
        try:
            if msg.photo:
                file = await msg.bot.get_file(msg.photo[-1].file_id)
                bio = await file.download_as_bytearray()
                import io
                await client.send_file(group_id, io.BytesIO(bytes(bio)), caption=clean_caption(msg.caption))
            elif msg.video:
                file = await msg.bot.get_file(msg.video.file_id)
                bio = await file.download_as_bytearray()
                import io
                await client.send_file(group_id, io.BytesIO(bytes(bio)), caption=clean_caption(msg.caption))
            elif msg.document:
                file = await msg.bot.get_file(msg.document.file_id)
                bio = await file.download_as_bytearray()
                import io
                await client.send_file(group_id, io.BytesIO(bytes(bio)), caption=clean_caption(msg.caption))
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


async def _do_broadcast(msg, users: list, status_msg):
    total = len(users)
    success = failed = 0
    delay = (2 * 3600) / max(total, 1)

    for i, user_id in enumerate(users):
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
                    text = msg.text
                    if text.startswith("/broadcast"):
                        parts = text.split(maxsplit=1)
                        text = parts[1] if len(parts) > 1 else ""
                    if text:
                        await client.send_message(user_id, text)
                success += 1
            finally:
                await client.disconnect()
        except FloodWaitError as e:
            db_set_flood(account["phone"], e.seconds)
            failed += 1
        except Exception as e:
            err = str(e).lower()
            if "blocked" in err or "privacy" in err:
                db_mark_user_blocked(user_id)
            else:
                logger.warning(f"[Broadcast] {user_id}: {e}")
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


async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return

    recent_users = db_get_recent_users(hours=2)
    if not recent_users:
        await update.message.reply_text("📭 ባለፉት 2 ሰዓት message የላኩ users የሉም")
        return

    blocked = db_get_all_blocked()
    recent_users = [u for u in recent_users if u not in blocked]
    if not recent_users:
        await update.message.reply_text("📭 Broadcast ላኪ users የሉም")
        return

    total = len(recent_users)
    status_msg = await update.message.reply_text(
        f"📤 Broadcast እየጀመረ ነው...\n👥 Users: {total}"
    )
    asyncio.create_task(_do_broadcast(update.message, recent_users, status_msg))


async def cmd_myapi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT label, api_id, api_hash, phone FROM userbot_accounts")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        await update.message.reply_text("📭 Account የለም")
        return
    lines = ["🔑 Account Details:\n"]
    for label, api_id, api_hash, phone in rows:
        lines.append(
            f"📱 {phone}\n"
            f"🏷 Label: {label}\n"
            f"🆔 API_ID: {api_id}\n"
            f"🔑 API_HASH: {api_hash}"
        )
    await update.message.reply_text("\n".join(lines))


async def cmd_ubothelp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    active_group = db_get_setting("active_group_id") or "❌ አልተቀመጠም"
    target_group = db_get_setting("target_group_id") or "❌ አልተቀመጠም"
    accounts = db_list_accounts()
    groups = db_list_groups()
    now = datetime.now()

    acc_lines = []
    for _, label, phone, is_active, session, flood_until, is_listener in accounts:
        status = "✅" if is_active else "❌"
        has_session = "🔑" if session else "⚠️"
        role = "👂" if is_listener else "⚙️"
        flood = ""
        if flood_until and flood_until > now:
            remaining = int((flood_until - now).total_seconds() / 60)
            flood = f" 🚫{remaining}min"
        daily = db_get_daily_add_count(label) if not is_listener else 0
        daily_str = f" [{daily}/{DAILY_ADD_LIMIT}]" if not is_listener else ""
        acc_lines.append(f"  {status}{role}[{label}] {phone} {has_session}{daily_str}{flood}")

    source_groups = [g for g in groups if g[3]]
    grp_lines = []
    for _, group_id, group_name, is_source in source_groups:
        tags = []
        if str(group_id) == active_group:
            tags.append("🟢")
        if str(group_id) == target_group:
            tags.append("🎯")
        name_str = f" — {group_name}" if group_name else ""
        grp_lines.append(f"  ✅ {group_id}{name_str} {''.join(tags)}")

    auto_add_on = (db_get_setting("auto_add_enabled") or "true") == "true"
    auto_status = "🟢 ON" if auto_add_on else "🔴 OFF"

    uadmins = db_list_uadmins()
    uadmin_lines = [f"  🔹 {r[0]}" for r in uadmins] if uadmins else ["  📭 የለም"]

    api_id1 = db_get_setting("userbot_api_id") or "❌ አልተቀመጠም"
    api_id2 = db_get_setting("userbot_api_id2") or "❌ አልተቀመጠም"

    text = (
        "🤖 Userbot Status & Commands\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"🤖 Auto-Add: {auto_status}\n"
        f"🟢 Active Group: {active_group}\n"
        f"🎯 Target Group: {target_group}\n\n"
        f"🔑 API (Worker): {api_id1}\n"
        f"🔑 API (Listener): {api_id2}\n\n"
        "👤 Accounts:\n" +
        ("\n".join(acc_lines) if acc_lines else "  📭 የለም") +
        f"\n\n🏠 Source Groups ({len(source_groups)}/{len(groups)}):\n" +
        ("\n".join(grp_lines) if grp_lines else "  📭 የለም") +
        "\n\n👥 Userbot Admins:\n" +
        "\n".join(uadmin_lines) +
        "\n\n━━━━━━━━━━━━━━━━\n"
        "⚙️ Setup:\n"
        "/setuserapi api_id api_hash\n"
        "/setuserapi2 api_id api_hash\n"
        "/addaccount a +phone\n"
        "/startsession +phone\n"
        "/verifycode +phone code\n"
        "/verify2fa +phone password\n"
        "/setlistener +phone\n"
        "/unsetlistener +phone\n"
        "/listaccounts\n"
        "/deleteaccount +phone\n"
        "/myapi\n\n"
        "/listgroups\n"
        "/syncgroups\n"
        "/addgroup -100xxxxxxx\n"
        "/deletegroup -100xxxxxxx\n\n"
        "/setactivegroup -100xxxxxxx\n"
        "/settargetgroup -100xxxxxxx\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "⚡ Send:\n"
        "/a /b /c /d /e መልዕክት\n\n"
        "📢 Broadcast:\n"
        "/broadcast መልዕክት\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "👥 Admin (main admin ብቻ):\n"
        "/adduadmin user_id\n"
        "/removeuadmin user_id\n"
        "/listuadmins\n"
    )
    await update.message.reply_text(text)


async def cmd_status2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_ubothelp(update, ctx)


# ============================================================
# REGISTER ALL HANDLERS
# ============================================================

def register_userbot_handlers(app):
    app.add_handler(CommandHandler("adduadmin", cmd_adduadmin))
    app.add_handler(CommandHandler("removeuadmin", cmd_removeuadmin))
    app.add_handler(CommandHandler("listuadmins", cmd_listuadmins))
    app.add_handler(CommandHandler("setuserapi", cmd_setuserapi))
    app.add_handler(CommandHandler("setuserapi2", cmd_setuserapi2))
    app.add_handler(CommandHandler("addaccount", cmd_addaccount))
    app.add_handler(CommandHandler("startsession", cmd_startsession))
    app.add_handler(CommandHandler("verifycode", cmd_verifycode))
    app.add_handler(CommandHandler("verify2fa", cmd_verify2fa))
    app.add_handler(CommandHandler("listaccounts", cmd_listaccounts))
    app.add_handler(CommandHandler("deleteaccount", cmd_deleteaccount))
    app.add_handler(CommandHandler("setlistener", cmd_setlistener))
    app.add_handler(CommandHandler("unsetlistener", cmd_unsetlistener))
    app.add_handler(CommandHandler("addgroup", cmd_addgroup))
    app.add_handler(CommandHandler("syncgroups", cmd_syncgroups))
    app.add_handler(CommandHandler("listgroups", cmd_listgroups))
    app.add_handler(CommandHandler("deletegroup", cmd_deletegroup))
    app.add_handler(CommandHandler("setactivegroup", cmd_setactivegroup))
    app.add_handler(CommandHandler("settargetgroup", cmd_settargetgroup))
    app.add_handler(CommandHandler("a", cmd_a))
    app.add_handler(CommandHandler("b", cmd_b))
    app.add_handler(CommandHandler("c", cmd_c))
    app.add_handler(CommandHandler("d", cmd_d))
    app.add_handler(CommandHandler("e", cmd_e))
    app.add_handler(CommandHandler("myapi", cmd_myapi))
    app.add_handler(CommandHandler("ubothelp", cmd_ubothelp))
    app.add_handler(CommandHandler("status2", cmd_status2))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CallbackQueryHandler(cb_group_action, pattern="^grp_"))

    logger.info("✅ Userbot handlers registered")
