"""
userbot.py — Telethon-based userbot commands

⚠️ CHANGE (per owner request): this module now uses its OWN dedicated
Postgres database (USERBOT_DATABASE_URL), completely separate from the
main lottery DB in database.py. This is for isolation/simplicity — userbot
traffic/load/schema never touches lottery data, and the two can be
backed up, migrated, or wiped independently.

⚠️ CHANGE: DB calls inside the per-message "hot path" (functions that run
automatically for every message in a source group: _get_client, handler,
_contact_and_add_by_sender, _reload_listeners, _add_workers_to_source_group,
_auto_detect_groups, _sync_all_account_groups, _spam_recovery_loop,
_cleanup_loop, _do_broadcast) are now wrapped in asyncio.to_thread so they
no longer block the shared asyncio event loop (which also runs bot.py's
screenshot/winner-photo AI analysis). Admin-only command handlers
(cmd_addaccount, cmd_listgroups, etc.) were left untouched since they only
run when an admin explicitly issues a command — negligible impact, and
touching them adds risk with no real benefit.

⚠️ CHANGE (per owner request, July 2026): removed the listener/worker role
split entirely. Every account now listens to its OWN assigned source
group(s) and adds users to the target group itself — no handoff to a
separate "worker" account. This avoids the pattern where an account with
no shared group with the target user tries to add them (which Telegram
was flagging as spam and killing sessions for). Source groups are now
assigned to specific accounts (round-robin by default, or manually via
the per-account view in /listgroups), and duplicate adds across accounts
are prevented with an atomic DB-level claim.
"""

import os
import asyncio
import logging
import random
from datetime import datetime, timedelta
import psycopg2
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import AddContactRequest
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.errors import FloodWaitError, PeerFloodError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

from config import ADMIN_IDS

logger = logging.getLogger(__name__)

# ============================================================
# DEDICATED USERBOT DB CONNECTION (separate from database.py)
# ============================================================

USERBOT_DATABASE_URL = os.environ.get("USERBOT_DATABASE_URL")


def get_conn():
    """userbot.py's own dedicated Postgres connection. Deliberately NOT the
    same connection as database.py's get_conn() — lottery data and userbot
    data live in two separate Postgres instances now."""
    if not USERBOT_DATABASE_URL:
        raise RuntimeError("USERBOT_DATABASE_URL ያልተቀመጠም! Railway/env ላይ አክል።")
    return psycopg2.connect(USERBOT_DATABASE_URL)


# ============================================================
# DB INIT
# ============================================================

def init_userbot_db():
    conn = get_conn()
    conn.autocommit = True
    cur = conn.cursor()

    def run(sql: str, label: str):
        """Run one DDL statement in isolation, commit it immediately, and
        log success/failure so a single bad statement never silently
        aborts the rest of the migration (or hides which step broke)."""
        try:
            cur.execute(sql)
            logger.info(f"[DB-Migrate] ✅ {label}")
        except Exception as e:
            logger.error(f"[DB-Migrate] ❌ {label}: {e}")

    run("""
        CREATE TABLE IF NOT EXISTS userbot_admins (
            user_id BIGINT PRIMARY KEY,
            added_by BIGINT NOT NULL,
            added_at TIMESTAMP DEFAULT NOW()
        )
    """, "create userbot_admins")

    run("""
        CREATE TABLE IF NOT EXISTS userbot_accounts (
            id SERIAL PRIMARY KEY,
            owner_id BIGINT NOT NULL DEFAULT 0,
            label CHAR(1) NOT NULL,
            api_id BIGINT NOT NULL,
            api_hash TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            session TEXT DEFAULT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            flood_until TIMESTAMP DEFAULT NULL,
            spam_until TIMESTAMP DEFAULT NULL,
            is_listener BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(owner_id, label)
        )
    """, "create userbot_accounts")

    run("""
        ALTER TABLE userbot_accounts
        ADD COLUMN IF NOT EXISTS owner_id BIGINT NOT NULL DEFAULT 0
    """, "userbot_accounts.owner_id backfill")

    run("""
        CREATE TABLE IF NOT EXISTS userbot_settings (
            owner_id BIGINT NOT NULL DEFAULT 0,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (owner_id, key)
        )
    """, "create userbot_settings")

    run("""
        ALTER TABLE userbot_settings
        ADD COLUMN IF NOT EXISTS owner_id BIGINT NOT NULL DEFAULT 0
    """, "userbot_settings.owner_id backfill")

    run("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'userbot_settings_pkey'
                AND conrelid = 'userbot_settings'::regclass
                AND array_length(conkey, 1) = 2
            ) THEN
                ALTER TABLE userbot_settings DROP CONSTRAINT IF EXISTS userbot_settings_pkey;
                ALTER TABLE userbot_settings ADD PRIMARY KEY (owner_id, key);
            END IF;
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END $$;
    """, "userbot_settings composite PK fix")

    run("""
        CREATE TABLE IF NOT EXISTS userbot_groups (
            id SERIAL PRIMARY KEY,
            owner_id BIGINT NOT NULL DEFAULT 0,
            group_id BIGINT,
            group_name TEXT DEFAULT NULL,
            is_source BOOLEAN DEFAULT FALSE,
            added_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(owner_id, group_id)
        )
    """, "create userbot_groups")

    run("""
        ALTER TABLE userbot_groups
        ADD COLUMN IF NOT EXISTS owner_id BIGINT NOT NULL DEFAULT 0
    """, "userbot_groups.owner_id backfill")

    run("""
        CREATE TABLE IF NOT EXISTS userbot_added_users (
            user_id BIGINT NOT NULL,
            group_id BIGINT NOT NULL,
            PRIMARY KEY (user_id, group_id)
        )
    """, "create userbot_added_users")

    run("""
        CREATE TABLE IF NOT EXISTS userbot_contacted_users (
            user_id BIGINT NOT NULL,
            account_label CHAR(1) NOT NULL,
            PRIMARY KEY (user_id, account_label)
        )
    """, "create userbot_contacted_users")

    run("""
        CREATE TABLE IF NOT EXISTS userbot_recent_messages (
            user_id BIGINT NOT NULL,
            group_id BIGINT NOT NULL,
            sent_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (user_id, group_id)
        )
    """, "create userbot_recent_messages")

    run("""
        CREATE TABLE IF NOT EXISTS userbot_blocked_users (
            user_id BIGINT PRIMARY KEY,
            blocked_at TIMESTAMP DEFAULT NOW()
        )
    """, "create userbot_blocked_users")

    run("""
        CREATE TABLE IF NOT EXISTS userbot_daily_adds (
            account_label CHAR(1) NOT NULL,
            add_date DATE NOT NULL DEFAULT CURRENT_DATE,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (account_label, add_date)
        )
    """, "create userbot_daily_adds")

    run("""
        ALTER TABLE userbot_accounts
        ADD COLUMN IF NOT EXISTS label CHAR(1) UNIQUE
    """, "userbot_accounts.label backfill")
    run("""
        ALTER TABLE userbot_accounts
        ADD COLUMN IF NOT EXISTS flood_until TIMESTAMP DEFAULT NULL
    """, "userbot_accounts.flood_until backfill")
    run("""
        ALTER TABLE userbot_accounts
        ADD COLUMN IF NOT EXISTS spam_until TIMESTAMP DEFAULT NULL
    """, "userbot_accounts.spam_until backfill")
    run("""
        ALTER TABLE userbot_accounts
        ADD COLUMN IF NOT EXISTS is_listener BOOLEAN DEFAULT FALSE
    """, "userbot_accounts.is_listener backfill (column kept for backward compat, no longer used)")

    run("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='userbot_groups' AND column_name='username'
            ) THEN
                ALTER TABLE userbot_groups DROP COLUMN username;
            END IF;
        END $$;
    """, "userbot_groups drop legacy username column")

    run("""
        ALTER TABLE userbot_groups
        ADD COLUMN IF NOT EXISTS group_id BIGINT UNIQUE
    """, "userbot_groups.group_id backfill")
    run("""
        ALTER TABLE userbot_groups
        ADD COLUMN IF NOT EXISTS group_name TEXT DEFAULT NULL
    """, "userbot_groups.group_name backfill")
    run("""
        ALTER TABLE userbot_groups
        ADD COLUMN IF NOT EXISTS is_source BOOLEAN DEFAULT FALSE
    """, "userbot_groups.is_source backfill")

    run("""
        CREATE INDEX IF NOT EXISTS idx_groups_source
        ON userbot_groups(group_id)
        WHERE is_source = TRUE
    """, "idx_groups_source index")

    run("""
        CREATE UNIQUE INDEX IF NOT EXISTS userbot_groups_owner_group_uidx
        ON userbot_groups (owner_id, group_id)
    """, "userbot_groups (owner_id, group_id) unique index")

    run("""
        CREATE UNIQUE INDEX IF NOT EXISTS userbot_accounts_owner_label_uidx
        ON userbot_accounts (owner_id, label)
    """, "userbot_accounts (owner_id, label) unique index")

    # --- NEW: per-account group assignment. A group can be assigned to
    # one or more accounts (usually one, via round-robin, but an admin
    # can manually assign several accounts to the same group from the
    # per-account view in /listgroups). Each assigned account listens
    # to that group independently and adds users itself. ---
    run("""
        CREATE TABLE IF NOT EXISTS userbot_group_accounts (
            owner_id BIGINT NOT NULL DEFAULT 0,
            group_id BIGINT NOT NULL,
            label CHAR(1) NOT NULL,
            assigned_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (owner_id, group_id, label)
        )
    """, "create userbot_group_accounts")

    cur.close()
    conn.close()
    logger.info("✅ Userbot DB tables ready (dedicated DB)")


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
        logger.info(f"[AdminCheck] user_id={user_id} → main admin ✅")
        return True
    result = db_is_uadmin(user_id)
    logger.info(f"[AdminCheck] user_id={user_id} → uadmin={result}")
    return result


# ============================================================
# DB HELPERS — ACCOUNTS
# ============================================================

def db_add_account(owner_id: int, label: str, api_id: int, api_hash: str, phone: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_accounts (owner_id, label, api_id, api_hash, phone)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (phone) DO UPDATE SET api_id=%s, api_hash=%s, label=%s, owner_id=%s
    """, (owner_id, label, api_id, api_hash, phone, api_id, api_hash, label, owner_id))
    conn.commit()
    cur.close()
    conn.close()


def db_list_accounts(owner_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, label, phone, is_active, session, flood_until, spam_until FROM userbot_accounts WHERE owner_id=%s ORDER BY label", (owner_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def db_get_account_by_label(owner_id: int, label: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, label, api_id, api_hash, phone, session, is_active, flood_until, spam_until FROM userbot_accounts WHERE owner_id=%s AND label=%s",
        (owner_id, label)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "label": row[1], "api_id": row[2], "api_hash": row[3],
        "phone": row[4], "session": row[5], "is_active": row[6],
        "flood_until": row[7], "spam_until": row[8]
    }


def db_get_account_by_phone(phone: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, label, api_id, api_hash, phone, session, is_active, flood_until, spam_until FROM userbot_accounts WHERE phone=%s",
        (phone,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "label": row[1], "api_id": row[2], "api_hash": row[3],
        "phone": row[4], "session": row[5], "is_active": row[6],
        "flood_until": row[7], "spam_until": row[8]
    }


def db_get_all_accounts(owner_id: int):
    """All active accounts with a session. There is no more listener/worker
    role split — every account listens to its own assigned groups (see
    userbot_group_accounts) and adds users itself."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, label, api_id, api_hash, phone, session, is_active, flood_until, spam_until FROM userbot_accounts WHERE owner_id=%s AND is_active=TRUE ORDER BY label",
        (owner_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {"id": r[0], "label": r[1], "api_id": r[2], "api_hash": r[3],
         "phone": r[4], "session": r[5], "is_active": r[6],
         "flood_until": r[7], "spam_until": r[8]}
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


def db_set_spam(phone: str):
    conn = get_conn()
    cur = conn.cursor()
    until = datetime.now() + timedelta(hours=24)
    cur.execute("UPDATE userbot_accounts SET spam_until=%s, is_active=FALSE WHERE phone=%s", (until, phone))
    conn.commit()
    cur.close()
    conn.close()


def db_clear_spam(phone: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE userbot_accounts SET spam_until=NULL, is_active=TRUE WHERE phone=%s", (phone,))
    conn.commit()
    cur.close()
    conn.close()


def db_get_spam_accounts(owner_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, label, api_id, api_hash, phone, session, is_active, flood_until, spam_until "
        "FROM userbot_accounts WHERE owner_id=%s AND spam_until IS NOT NULL ORDER BY label",
        (owner_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {"id": r[0], "label": r[1], "api_id": r[2], "api_hash": r[3],
         "phone": r[4], "session": r[5], "is_active": r[6],
         "flood_until": r[7], "spam_until": r[8]}
        for r in rows
    ]


def db_delete_account(phone: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM userbot_accounts WHERE phone=%s", (phone,))
    conn.commit()
    cur.close()
    conn.close()


def db_set_setting(owner_id: int, key: str, value: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_settings (owner_id, key, value) VALUES (%s, %s, %s)
        ON CONFLICT (owner_id, key) DO UPDATE SET value=%s
    """, (owner_id, key, value, value))
    conn.commit()
    cur.close()
    conn.close()


def db_get_setting(owner_id: int, key: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM userbot_settings WHERE owner_id=%s AND key=%s", (owner_id, key))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None


def db_add_group(owner_id: int, group_id: int, group_name: str = None, is_source: bool = False):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_groups (owner_id, group_id, group_name, is_source)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (owner_id, group_id) DO UPDATE SET
            group_name=COALESCE(EXCLUDED.group_name, userbot_groups.group_name),
            is_source=CASE WHEN EXCLUDED.is_source THEN TRUE ELSE userbot_groups.is_source END
    """, (owner_id, group_id, group_name, is_source))
    conn.commit()
    cur.close()
    conn.close()


def db_list_groups(owner_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, group_id, group_name, is_source FROM userbot_groups WHERE owner_id=%s AND group_id IS NOT NULL ORDER BY id", (owner_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def db_set_group_source(owner_id: int, group_id: int, is_source: bool):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE userbot_groups SET is_source=%s WHERE owner_id=%s AND group_id=%s", (is_source, owner_id, group_id))
    conn.commit()
    cur.close()
    conn.close()


def db_delete_group(owner_id: int, group_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM userbot_groups WHERE owner_id=%s AND group_id=%s", (owner_id, group_id))
    cur.execute("DELETE FROM userbot_group_accounts WHERE owner_id=%s AND group_id=%s", (owner_id, group_id))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# DB HELPERS — PER-ACCOUNT GROUP ASSIGNMENT (NEW)
# ============================================================

def db_assign_group_to_account(owner_id: int, group_id: int, label: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_group_accounts (owner_id, group_id, label)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
    """, (owner_id, group_id, label))
    conn.commit()
    cur.close()
    conn.close()


def db_unassign_group_from_account(owner_id: int, group_id: int, label: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM userbot_group_accounts WHERE owner_id=%s AND group_id=%s AND label=%s",
        (owner_id, group_id, label)
    )
    conn.commit()
    cur.close()
    conn.close()


def db_get_labels_for_group(owner_id: int, group_id: int) -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT label FROM userbot_group_accounts WHERE owner_id=%s AND group_id=%s ORDER BY label",
        (owner_id, group_id)
    )
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def db_get_groups_for_account(owner_id: int, label: str) -> list:
    """Group IDs this specific account is assigned to listen on."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT g.group_id FROM userbot_groups g
        JOIN userbot_group_accounts ga
          ON ga.owner_id = g.owner_id AND ga.group_id = g.group_id
        WHERE g.owner_id=%s AND g.is_source=TRUE AND ga.label=%s
    """, (owner_id, label))
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def db_get_group_assignment_map(owner_id: int) -> dict:
    """group_id -> [labels] for display purposes (e.g. /listgroups)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT group_id, label FROM userbot_group_accounts WHERE owner_id=%s", (owner_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    mapping = {}
    for gid, label in rows:
        mapping.setdefault(gid, []).append(label)
    for gid in mapping:
        mapping[gid].sort()
    return mapping


_group_assign_rr_index = 0


def db_auto_assign_group(owner_id: int, group_id: int):
    """Round-robin: pick the next account (a → b → c → a...) among
    accounts that currently have a session, and assign this group to it.
    Returns the assigned label, or None if no accounts are available."""
    global _group_assign_rr_index
    accounts = [a for a in db_get_all_accounts(owner_id) if a.get("session")]
    if not accounts:
        return None
    account = accounts[_group_assign_rr_index % len(accounts)]
    _group_assign_rr_index += 1
    db_assign_group_to_account(owner_id, group_id, account["label"])
    return account["label"]


# ============================================================
# DB HELPERS — MISC
# ============================================================

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


def db_try_claim_user(user_id: int, target_group_id: int) -> bool:
    """Atomically claim a user for adding to target_group_id. Returns True
    if THIS call won the claim (no other account has claimed/added this
    user for this target yet), False if it was already claimed. This
    reuses userbot_added_users as both the "claim" and the final "added"
    marker — a row existing means "someone is handling this or already
    added them". Call db_release_claim() if the add attempt then fails,
    so the user can be retried later."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_added_users (user_id, group_id) VALUES (%s, %s)
        ON CONFLICT DO NOTHING
    """, (user_id, target_group_id))
    won = cur.rowcount > 0
    conn.commit()
    cur.close()
    conn.close()
    return won


def db_release_claim(user_id: int, target_group_id: int):
    """Release a claim after a failed add attempt, so the user isn't
    permanently (and incorrectly) marked as 'added'."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM userbot_added_users WHERE user_id=%s AND group_id=%s",
        (user_id, target_group_id)
    )
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
# RAW-SQL HELPERS (used only from hot-path async functions, so their
# whole body runs inside asyncio.to_thread at the call site)
# ============================================================

def _sql_distinct_owner_ids_with_spam():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT owner_id FROM userbot_accounts WHERE spam_until IS NOT NULL")
    owner_ids = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return owner_ids


def _sql_distinct_owner_ids_with_accounts(owner_id: int = None):
    conn = get_conn()
    cur = conn.cursor()
    if owner_id:
        cur.execute("SELECT DISTINCT owner_id FROM userbot_accounts WHERE is_active=TRUE AND owner_id=%s", (owner_id,))
    else:
        cur.execute("SELECT DISTINCT owner_id FROM userbot_accounts WHERE is_active=TRUE")
    owner_ids = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return owner_ids


def _sql_upsert_detected_group(owner_id: int, normalized_id: int, name: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO userbot_groups (owner_id, group_id, group_name, is_source)
        VALUES (%s, %s, %s, FALSE)
        ON CONFLICT (owner_id, group_id) DO UPDATE SET
            group_name=COALESCE(EXCLUDED.group_name, userbot_groups.group_name)
    """, (owner_id, normalized_id, name))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# ROUND ROBIN (DM broadcast only — unrelated to source-group assignment)
# ============================================================

_dm_rr_index = 0


def get_dm_accounts(owner_id: int) -> list:
    """DM ለመላክ የሚጠቀሙ accounts — formula based"""
    accounts = [a for a in db_get_all_accounts(owner_id) if a.get("session")]
    total = len(accounts)
    if total <= 5:
        return []
    if total <= 9:
        dm_count = total - 5
    else:
        dm_count = total // 2
    return accounts[:dm_count]


def get_next_dm_account(owner_id: int):
    global _dm_rr_index
    dm_accounts = get_dm_accounts(owner_id)
    if not dm_accounts:
        return None
    account = dm_accounts[_dm_rr_index % len(dm_accounts)]
    _dm_rr_index += 1
    return account


def get_any_account(owner_id: int):
    """Used only by admin commands that need *some* account with a
    session to look up group info (e.g. /addgroup, /syncgroups) — not
    part of the add pipeline any more."""
    accounts = [a for a in db_get_all_accounts(owner_id) if a.get("session")]
    return accounts[0] if accounts else None


# ============================================================
# ADMIN NOTIFY
# ============================================================

_bot_app = None


def set_bot_app(app):
    global _bot_app
    _bot_app = app


async def _notify_admins(text: str):
    if not _bot_app:
        return
    for admin_id in ADMIN_IDS:
        try:
            await _bot_app.bot.send_message(admin_id, text)
        except Exception:
            pass


# ============================================================
# ADMIN CACHE
# ============================================================

_admin_cache: dict = {}


async def _is_admin_or_owner(client, user, group_id: int) -> bool:
    """Checks whether `user` (a resolved Telethon User entity, or a bare
    user_id as a fallback) is an admin/creator of group_id. IMPORTANT:
    pass the already-resolved `sender` object from the event that
    triggered this check — not a bare id looked up on a fresh/different
    client — since a brand-new client instance has no cached access_hash
    for that user and get_permissions() will fail with 'Could not find
    the input entity'. `client` should be the SAME client that received
    the message (already a member of the group, already saw the sender)."""
    user_id = user.id if hasattr(user, "id") else user
    cache_key = (user_id, group_id)
    if cache_key in _admin_cache:
        return _admin_cache[cache_key]
    try:
        participant = await client.get_permissions(group_id, user)
        result = participant.is_admin or participant.is_creator
    except Exception as e:
        logger.warning(f"[AutoAdd-DEBUG] get_permissions failed for user={user_id} group={group_id}: {e}")
        result = False
    _admin_cache[cache_key] = result
    return result


# ============================================================
# PER-ACCOUNT LOCKS — serialize add attempts made by the SAME account
# so two messages arriving at nearly the same moment (in this account's
# assigned group, or in two of its assigned groups) can never race each
# other into simultaneously trying to add/contact/invite. Combined with
# the atomic DB claim (db_try_claim_user) this also protects against two
# DIFFERENT accounts racing on the same user.
# ============================================================

_account_locks: dict = {}


def _get_account_lock(label: str) -> asyncio.Lock:
    if label not in _account_locks:
        _account_locks[label] = asyncio.Lock()
    return _account_locks[label]


# ============================================================
# TELETHON CLIENT  (hot path — wrapped in to_thread)
# ============================================================

async def _get_client(account: dict, owner_id: int = 0) -> TelegramClient:
    session = account.get("session") or ""
    client = TelegramClient(
        StringSession(session),
        account["api_id"],
        account["api_hash"]
    )
    await client.connect()
    logger.info(f"[_get_client] 🔌 [{account.get('label')}] connected")

    try:
        target_link = await asyncio.to_thread(db_get_setting, owner_id, "target_group_link")
        target_str = await asyncio.to_thread(db_get_setting, owner_id, "target_group_id")
        target = target_link if target_link else (int(target_str) if target_str else None)
        if target:
            await client.get_entity(target)
            logger.info(f"[_get_client] ✅ [{account.get('label')}] target group cached: {target}")
        else:
            logger.warning(f"[_get_client] ⚠️ [{account.get('label')}] target_group አልተቀመጠም")
    except Exception as e:
        logger.warning(f"[_get_client] ❌ [{account.get('label')}] target group cache failed: {e}")

    try:
        my_group_ids = await asyncio.to_thread(db_get_groups_for_account, owner_id, account.get("label"))
        if my_group_ids:
            for gid in my_group_ids:
                try:
                    await client.get_input_entity(gid)
                    logger.info(f"[_get_client] ✅ [{account.get('label')}] source group cached: {gid}")
                except Exception as e:
                    logger.warning(f"[_get_client] ❌ [{account.get('label')}] source {gid} cache failed: {e}")
        else:
            logger.info(f"[_get_client] ℹ️ [{account.get('label')}] this account has no assigned source groups")
    except Exception as e:
        logger.warning(f"[_get_client] ❌ [{account.get('label')}] source groups error: {e}")

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
# CORE ACTIONS  (hot path — wrapped in to_thread)
# ============================================================

async def _contact_and_add_by_sender(account: dict, sender, target_group_id: int, owner_id: int = 0, client=None):
    """Adds `sender` to the target group using `account`.

    If `client` is passed in, it is the SAME already-connected client that
    is actively listening for messages on this account's assigned
    group(s) — it is reused here and is NEVER disconnected by this
    function, since disconnecting it would kill that account's listener.
    A client only gets disconnected here if this function created its
    own (client=None), e.g. when called from a context with no live
    listener client at hand.
    """
    own_client = client is None
    if own_client:
        client = await _get_client(account, owner_id)
    try:
        user_id = sender.id
        first_name = sender.first_name or "User"
        last_name = sender.last_name or ""
        phone = sender.phone or ""

        logger.info(f"[Add] [{account['label']}] starting add for user={user_id} → target={target_group_id}")

        resolved_user = None
        try:
            resolved_user = await client.get_entity(user_id)
            logger.info(f"[Resolve] ✅ [{account['label']}] {user_id} resolved from own cache")
        except Exception as e:
            # The sender object itself came from this same client's event,
            # so it's already a valid resolved entity even if a fresh
            # get_entity() lookup can't re-derive it — use it directly
            # instead of failing here.
            logger.info(f"[Resolve] [{account['label']}] {user_id} not resolvable via get_entity, using event's sender object directly: {e}")
            resolved_user = sender

        if not resolved_user:
            already_contacted = await asyncio.to_thread(db_is_user_contacted, user_id, account["label"])
            if not already_contacted:
                try:
                    await client(AddContactRequest(
                        id=user_id,
                        first_name=first_name,
                        last_name=last_name,
                        phone=phone,
                        add_phone_privacy_exception=False
                    ))
                    await asyncio.to_thread(db_mark_user_contacted, user_id, account["label"])
                    logger.info(f"[Contact] ✅ [{account['label']}] contacted {user_id}")
                except FloodWaitError as e:
                    await asyncio.to_thread(db_set_flood, account["phone"], e.seconds)
                    logger.warning(f"[Contact] 🚫 Flood [{account['label']}]: {e.seconds}s")
                    await asyncio.to_thread(db_release_claim, user_id, target_group_id)
                    return
                except PeerFloodError:
                    await asyncio.to_thread(db_set_spam, account["phone"])
                    logger.warning(f"[Contact] 🚫 SPAM BAN [{account['label']}]")
                    await _notify_admins(f"⚠️ Account [{account['label']}] {account['phone']} spam ban ሆነ!\n24 ሰዓት በኋላ auto-check ይጀምራል።")
                    await asyncio.to_thread(db_release_claim, user_id, target_group_id)
                    return
                except Exception as e:
                    logger.warning(f"[Contact] ❌ [{account['label']}] {user_id}: {e}")

            try:
                resolved_user = await client.get_entity(user_id)
                logger.info(f"[Resolve] ✅ [{account['label']}] {user_id} resolved after contact")
            except Exception as e:
                logger.warning(f"[Resolve] ⚠️ [{account['label']}] still cannot re-resolve {user_id}, falling back to sender object: {e}")
                resolved_user = sender

        if not resolved_user:
            logger.warning(f"[Add] ⏭ [{account['label']}] user {user_id} unresolvable — skip")
            await asyncio.to_thread(db_release_claim, user_id, target_group_id)
            return

        try:
            target_link = await asyncio.to_thread(db_get_setting, owner_id, "target_group_link")
            target = target_link if target_link else target_group_id
            group = await client.get_entity(target)
            logger.info(f"[Add] ✅ [{account['label']}] target group resolved: {target}")

            await client(InviteToChannelRequest(channel=group, users=[resolved_user]))
            await asyncio.to_thread(db_increment_daily_add, account["label"])
            logger.info(f"[Add] ✅✅ [{account['label']}] user {user_id} → {target_group_id} SUCCESS!")
        except FloodWaitError as e:
            await asyncio.to_thread(db_set_flood, account["phone"], e.seconds)
            logger.warning(f"[Add] 🚫 Flood [{account['label']}]: {e.seconds}s")
            await asyncio.to_thread(db_release_claim, user_id, target_group_id)
        except PeerFloodError:
            await asyncio.to_thread(db_set_spam, account["phone"])
            logger.warning(f"[Add] 🚫 SPAM BAN [{account['label']}]")
            await _notify_admins(f"⚠️ Account [{account['label']}] {account['phone']} spam ban ሆነ!\n24 ሰዓት በኋላ auto-check ይጀምራል።")
            await asyncio.to_thread(db_release_claim, user_id, target_group_id)
        except Exception as e:
            logger.warning(f"[Add] ❌ [{account['label']}] user={user_id} target={target_group_id}: {e}")
            await asyncio.to_thread(db_release_claim, user_id, target_group_id)
    finally:
        if own_client:
            await client.disconnect()
            logger.info(f"[_get_client] 🔌 [{account.get('label')}] disconnected")


# ============================================================
# SPAM RECOVERY LOOP  (hot path — wrapped in to_thread)
# ============================================================

async def _spam_recovery_loop():
    """24hr በኋላ every 5hr spam accounts ን test ያደርጋል"""
    while True:
        await asyncio.sleep(5 * 3600)  # every 5 ሰዓት
        try:
            owner_ids = await asyncio.to_thread(_sql_distinct_owner_ids_with_spam)
            spam_accounts = []
            for oid in owner_ids:
                spam_accounts.extend(await asyncio.to_thread(db_get_spam_accounts, oid))
            now = datetime.now()
            for account in spam_accounts:
                if not account.get("session"):
                    continue
                spam_until = account.get("spam_until")
                if spam_until and spam_until > now:
                    remaining = int((spam_until - now).total_seconds() / 3600)
                    logger.info(f"[SpamCheck] ⏳ [{account['label']}] still waiting {remaining}hr")
                    continue

                logger.info(f"[SpamCheck] 🔍 [{account['label']}] testing...")
                try:
                    client = TelegramClient(
                        StringSession(account["session"]),
                        account["api_id"],
                        account["api_hash"]
                    )
                    await client.connect()
                    try:
                        await client.send_message("@SpamBot", "/start")
                        await asyncio.sleep(2)
                        await asyncio.to_thread(db_clear_spam, account["phone"])
                        logger.info(f"[SpamCheck] ✅ [{account['label']}] spam ban ተነሳ!")
                        await _notify_admins(f"✅ Account [{account['label']}] {account['phone']} spam ban ተነሳ! እንደገና active ሆነ።")
                    except PeerFloodError:
                        logger.info(f"[SpamCheck] ❌ [{account['label']}] still spam banned")
                    except Exception as e:
                        logger.warning(f"[SpamCheck] [{account['label']}] test error: {e}")
                    finally:
                        await client.disconnect()
                except Exception as e:
                    logger.warning(f"[SpamCheck] [{account['label']}] connect error: {e}")
        except Exception as e:
            logger.warning(f"[SpamCheck] loop error: {e}")


# ============================================================
# ADD ACCOUNTS TO SOURCE GROUP  (hot path — wrapped in to_thread)
# Only invites the accounts that are ASSIGNED to this group (via
# userbot_group_accounts) — not every account. An account must be a
# member of a group to receive its messages or resolve its senders, so
# whichever account(s) are assigned to a group must physically join it.
# ============================================================

async def _add_assigned_accounts_to_source_group(group_id: int, owner_id: int, labels: list):
    if not labels:
        logger.info(f"[AutoJoin] ⏭ group={group_id} has no assigned accounts yet")
        return

    all_accounts = {a["label"]: a for a in await asyncio.to_thread(db_get_all_accounts, owner_id) if a.get("session")}
    assigned = [all_accounts[l] for l in labels if l in all_accounts]
    if not assigned:
        logger.warning(f"[AutoJoin] ⚠️ none of the assigned labels {labels} have a live session")
        return

    # Use the first assigned account (or any account that can already
    # resolve the group) as the "inviter" that performs the invites.
    inviter = assigned[0]
    inviter_client = await _get_client(inviter, owner_id)
    try:
        try:
            group_entity = await inviter_client.get_entity(group_id)
        except Exception as e:
            logger.warning(f"[AutoJoin] ❌ [{inviter['label']}] cannot resolve group {group_id} — it must already be a member for the invite flow to work: {e}")
            return

        existing_member_ids = set()
        try:
            async for participant in inviter_client.iter_participants(group_entity):
                existing_member_ids.add(participant.id)
        except Exception as e:
            logger.warning(f"[AutoJoin] ⚠️ cannot list participants: {e}")

        added = skipped = failed = 0
        for acc in assigned:
            if acc["label"] == inviter["label"]:
                skipped += 1
                continue
            try:
                acc_client = await _get_client(acc, owner_id)
                try:
                    me = await acc_client.get_me()
                    acc_user_id = me.id
                finally:
                    await acc_client.disconnect()

                if acc_user_id in existing_member_ids:
                    skipped += 1
                    continue

                try:
                    acc_input = await inviter_client.get_entity(acc_user_id)
                except Exception as e:
                    logger.warning(f"[AutoJoin] ❌ [{acc['label']}] cannot resolve: {e}")
                    failed += 1
                    continue

                await inviter_client(InviteToChannelRequest(channel=group_entity, users=[acc_input]))
                added += 1
                logger.info(f"[AutoJoin] ✅✅ [{acc['label']}] added to source group {group_id}")

            except FloodWaitError as e:
                await asyncio.to_thread(db_set_flood, inviter["phone"], e.seconds)
                logger.warning(f"[AutoJoin] 🚫 Flood: {e.seconds}s")
                break
            except Exception as e:
                failed += 1
                logger.warning(f"[AutoJoin] ❌ [{acc['label']}] failed: {e}")

            await asyncio.sleep(random.uniform(15, 25))

        logger.info(f"[AutoJoin] 🏁 group={group_id} added:{added} skipped:{skipped} failed:{failed}")

    finally:
        await inviter_client.disconnect()


# ============================================================
# AUTO-DETECT GROUPS  (hot path — wrapped in to_thread)
# ============================================================

async def _auto_detect_groups(account: dict, owner_id: int = 0):
    client = await _get_client(account, owner_id)
    count = 0
    try:
        async for dialog in client.iter_dialogs():
            if dialog.is_group or dialog.is_channel:
                normalized_id = _normalize_source_id(dialog.id)
                await asyncio.to_thread(_sql_upsert_detected_group, owner_id, normalized_id, dialog.name)
                count += 1
        logger.info(f"✅ [{account['label']}] auto-detected {count} groups")
    except Exception as e:
        logger.warning(f"[AutoDetect] {account['label']}: {e}")
    finally:
        await client.disconnect()


async def _sync_all_account_groups(owner_id: int = None):
    owner_ids = await asyncio.to_thread(_sql_distinct_owner_ids_with_accounts, owner_id)
    for oid in owner_ids:
        accounts = await asyncio.to_thread(db_get_all_accounts, oid)
        for account in accounts:
            if account.get("session"):
                await _auto_detect_groups(account, oid)


# ============================================================
# TELETHON EVENT LISTENERS  (hot path — wrapped in to_thread)
# Every account attaches a listener ONLY for the group(s) assigned to
# IT (db_get_groups_for_account) — not for every source group. When a
# message arrives, the SAME client/account resolves the sender, checks
# admin status, and — if eligible — adds the sender to the target group
# ITSELF (no handoff to another account).
# ============================================================

_telethon_clients = []


async def _reload_listeners(owner_id: int = None):
    global _telethon_clients
    for client in _telethon_clients:
        try:
            await client.disconnect()
        except Exception:
            pass
    _telethon_clients = []

    await _sync_all_account_groups(owner_id)

    owner_ids = await asyncio.to_thread(_sql_distinct_owner_ids_with_accounts, owner_id)

    for oid in owner_ids:
        accounts = await asyncio.to_thread(db_get_all_accounts, oid)

        for account in accounts:
            if not account.get("session"):
                continue

            my_group_ids = await asyncio.to_thread(db_get_groups_for_account, oid, account["label"])
            if not my_group_ids:
                logger.info(f"[Reload] ℹ️ [{account['label']}] owner={oid} — no assigned source groups, skipping listener")
                continue

            source_ids = [_normalize_source_id(g) for g in my_group_ids]
            logger.info(f"[Reload] ✅ [{account['label']}] owner={oid} assigned source groups: {source_ids}")

            try:
                client = TelegramClient(
                    StringSession(account["session"]),
                    account["api_id"],
                    account["api_hash"]
                )
                await client.start()

                for sid in source_ids:
                    try:
                        entity = await client.get_entity(sid)
                        logger.info(f"[AutoAdd-DEBUG] ✅ [{account['label']}] resolved entity for {sid}: {getattr(entity, 'title', entity)}")
                    except Exception as e:
                        logger.warning(f"[AutoAdd-DEBUG] ❌ [{account['label']}] CANNOT resolve entity for {sid} — this account may not be a member yet: {e}")

                @client.on(events.NewMessage(chats=source_ids))
                async def handler(event, acc=account, o=oid, my_client_holder=[None]):
                    # my_client_holder trick avoids a stale-closure issue —
                    # 'client' below refers to the client this handler is
                    # bound to via the decorator, which is correct as-is
                    # since each account gets its own client/handler pair
                    # inside this loop iteration.
                    try:
                        chat_id = _normalize_chat_id(event)
                        logger.info(f"[AutoAdd] 📨 [{acc['label']}] msg from chat {chat_id}")

                        sender = await event.get_sender()
                        if not sender or sender.bot or sender.is_self:
                            return

                        user_id = sender.id
                        logger.info(f"[AutoAdd] 👤 [{acc['label']}] user {user_id} ({sender.first_name})")

                        # Use the SAME client (already a member of this
                        # group, already has the sender resolved via the
                        # event) — never spin up a second client for this.
                        is_adm = await _is_admin_or_owner(client, sender, chat_id)
                        if is_adm:
                            return

                        await asyncio.to_thread(db_record_message, user_id, chat_id)

                        target_str = await asyncio.to_thread(db_get_setting, o, "target_group_id")
                        if not target_str:
                            return
                        target_group_id = int(target_str)

                        already_added = await asyncio.to_thread(db_is_user_added, user_id, target_group_id)
                        if already_added:
                            return

                        auto_add = (await asyncio.to_thread(db_get_setting, o, "auto_add_enabled")) or "true"
                        if auto_add == "false":
                            return

                        daily_limit_str = await asyncio.to_thread(db_get_setting, o, "daily_limit")
                        if not daily_limit_str:
                            logger.info("[AutoAdd] ⏭ daily_limit አልተቀመጠም — auto add skip")
                            return
                        daily_limit = int(daily_limit_str)

                        # Everything from here on is serialized per-account:
                        # if two messages land for THIS account at nearly
                        # the same instant (same group or two of its
                        # assigned groups), only one runs the add logic at
                        # a time — the second waits for the lock, then
                        # re-checks fresh state (daily count, already_added)
                        # before proceeding, so it can't double-fire.
                        lock = _get_account_lock(acc["label"])
                        async with lock:
                            # Re-check under the lock — state may have
                            # changed while we were waiting for it.
                            already_added_2 = await asyncio.to_thread(db_is_user_added, user_id, target_group_id)
                            if already_added_2:
                                return

                            fresh_acc = await asyncio.to_thread(db_get_account_by_label, o, acc["label"])
                            if not fresh_acc or not fresh_acc.get("session"):
                                return

                            now = datetime.now()
                            if fresh_acc.get("flood_until") and fresh_acc["flood_until"] > now:
                                logger.info(f"[AutoAdd] ⏭ [{acc['label']}] in flood-wait — skip")
                                return
                            if fresh_acc.get("spam_until") and fresh_acc["spam_until"] > now:
                                logger.info(f"[AutoAdd] ⏭ [{acc['label']}] spam-banned — skip")
                                return

                            current_count = await asyncio.to_thread(db_get_daily_add_count, acc["label"])
                            if current_count >= daily_limit:
                                logger.info(f"[AutoAdd] ⏭ [{acc['label']}] hit daily limit ({current_count}/{daily_limit}) — skip")
                                return

                            # Atomic cross-account claim — protects
                            # against a DIFFERENT account (assigned to a
                            # different group) racing on the same user.
                            claimed = await asyncio.to_thread(db_try_claim_user, user_id, target_group_id)
                            if not claimed:
                                logger.info(f"[AutoAdd] ⏭ user={user_id} already claimed by another account — skip")
                                return

                            logger.info(f"[AutoAdd] ⚙️ [{acc['label']}] adding {user_id} (self — no handoff)")
                            await asyncio.sleep(random.uniform(2, 5))
                            await _contact_and_add_by_sender(fresh_acc, sender, target_group_id, o, client=client)

                    except Exception as e:
                        logger.warning(f"[AutoAdd] ❌ [{acc.get('label')}] Error: {e}", exc_info=True)

                _telethon_clients.append(client)
                logger.info(f"✅ Listener reloaded: [{account['label']}] {account['phone']} owner={oid}")
            except Exception as e:
                logger.warning(f"[Reload] {account['phone']}: {e}")


async def _cleanup_loop():
    while True:
        await asyncio.sleep(3600)
        await asyncio.to_thread(db_cleanup_old_messages, 24)
        logger.info("✅ Old messages cleaned up")


async def start_listeners():
    asyncio.create_task(_cleanup_loop())
    asyncio.create_task(_spam_recovery_loop())
    asyncio.create_task(_reload_listeners())


# ============================================================
# PENDING SESSIONS
# ============================================================

_pending_sessions: dict = {}


# ============================================================
# COMMAND HANDLERS
# (admin-triggered only, infrequent — left as direct sync DB calls
# on purpose, see module docstring at top)
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
    if not _is_admin(update.effective_user.id):
        return
    owner_id = update.effective_user.id
    args = update.message.text.split(maxsplit=2)
    if len(args) < 3:
        await update.message.reply_text("❌ Format: /setuserapi api_id api_hash")
        return
    try:
        api_id = int(args[1])
        api_hash = args[2]
        db_set_setting(owner_id, "userbot_api_id", str(api_id))
        db_set_setting(owner_id, "userbot_api_hash", api_hash)
        await update.message.reply_text(f"✅ API ተቀምጧል!\n🆔 {api_id}\n🔑 {api_hash}")
    except ValueError:
        await update.message.reply_text("❌ api_id ቁጥር መሆን አለበት!")


def _get_api(owner_id: int) -> tuple:
    """Single shared API config for all accounts — there's no more
    listener/worker role split, so there's no need for a second API set."""
    api_id = db_get_setting(owner_id, "userbot_api_id")
    api_hash = db_get_setting(owner_id, "userbot_api_hash")
    if api_id and api_hash:
        return int(api_id), api_hash
    return None, None


async def cmd_addaccount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    owner_id = update.effective_user.id
    args = update.message.text.split(maxsplit=2)
    if len(args) < 3:
        await update.message.reply_text("❌ Format:\n/addaccount label +phone")
        return
    try:
        label = args[1].lower()
        phone = args[2]
        api_id, api_hash = _get_api(owner_id)
        if not api_id or not api_hash:
            await update.message.reply_text("❌ API አልተቀመጠም! /setuserapi api_id api_hash")
            return
        db_add_account(owner_id, label, api_id, api_hash, phone)
        await update.message.reply_text(f"✅ Account [{label}] {phone} ተጨመረ!\n\n/startsession {phone}")
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
        await update.message.reply_text(f"✅ Code ተላከ!\n\n/verifycode {phone} 12345")
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
            await update.message.reply_text(f"🔐 2FA!\n/verify2fa {phone} yourpassword")
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


async def cmd_setlimit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    owner_id = update.effective_user.id
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /setlimit 50")
        return
    try:
        limit = int(args[1])
        db_set_setting(owner_id, "daily_limit", str(limit))
        await update.message.reply_text(f"✅ Daily limit set: {limit} per account")
    except ValueError:
        await update.message.reply_text("❌ ቁጥር መሆን አለበት!")


async def cmd_listaccounts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    owner_id = update.effective_user.id
    rows = db_list_accounts(owner_id)
    if not rows:
        await update.message.reply_text("📭 Account የለም")
        return
    now = datetime.now()
    assignment_map = db_get_group_assignment_map(owner_id)
    lines = ["📋 Accounts:\n"]
    for aid, label, phone, is_active, session, flood_until, spam_until in rows:
        status = "✅" if is_active else "❌"
        has_session = "🔑" if session else "⚠️ no session"
        flood = ""
        spam = ""
        if flood_until and flood_until > now:
            remaining = int((flood_until - now).total_seconds() / 60)
            flood = f" 🌊 flood {remaining}min"
        if spam_until:
            if spam_until > now:
                remaining_hr = int((spam_until - now).total_seconds() / 3600)
                spam = f" 🚫 spam {remaining_hr}hr"
            else:
                spam = " 🔍 spam check pending"
        daily = db_get_daily_add_count(label)
        daily_limit_str = db_get_setting(owner_id, "daily_limit") or "?"
        my_groups = sum(1 for gid, labels in assignment_map.items() if label in labels)
        lines.append(f"{status} [{label}] {phone} {has_session} 🏠{my_groups} groups [{daily}/{daily_limit_str}]{flood}{spam}")
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
    owner_id = update.effective_user.id
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /setactivegroup -100xxxxxxx")
        return
    try:
        group_id = int(args[1])
        db_set_setting(owner_id, "active_group_id", str(group_id))
        await update.message.reply_text(f"✅ Active group set: {group_id}")
    except ValueError:
        await update.message.reply_text("❌ Group ID ቁጥር መሆን አለበት!")


async def cmd_settargetgroup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    owner_id = update.effective_user.id
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /settargetgroup -100xxxxxxx")
        return
    try:
        group_id = int(args[1])
        db_set_setting(owner_id, "target_group_id", str(group_id))
        await update.message.reply_text(f"✅ Target group set: {group_id}")
    except ValueError:
        await update.message.reply_text("❌ Group ID ቁጥር መሆን አለበት!")


async def cmd_settargetlink(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    owner_id = update.effective_user.id
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /settargetlink https://t.me/+xxx")
        return
    db_set_setting(owner_id, "target_group_link", args[1])
    await update.message.reply_text(f"✅ Target link ተቀምጧል: {args[1]}")


async def cmd_addgroup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info(f"[Command] /addgroup called by {update.effective_user.id}")
    if not _is_admin(update.effective_user.id):
        return
    owner_id = update.effective_user.id
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /addgroup -100xxxxxxx")
        return
    try:
        group_id = int(args[1])
        group_name = None
        account = get_any_account(owner_id)
        if account:
            try:
                client = await _get_client(account, owner_id)
                try:
                    entity = await client.get_entity(group_id)
                    group_name = getattr(entity, "title", None)
                finally:
                    await client.disconnect()
            except Exception:
                group_name = None

        db_add_group(owner_id, group_id, group_name, is_source=False)
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
    owner_id = update.effective_user.id
    msg = await update.message.reply_text("🔄 Groups እየሳነቀ ነው...")
    await _sync_all_account_groups(owner_id)
    await msg.edit_text("✅ Groups synced! /listgroups ይጫን")


# ============================================================
# LISTGROUPS — PAGINATED, WITH PER-ACCOUNT VIEW
#
# Default view: shows every group with the labels of whichever
# account(s) are currently assigned to it, e.g. "✅ MyGroup [a]".
# Tapping "👤 View: a" switches into per-account mode, filtered/annotated
# for account [a] specifically — toggling a group there assigns/unassigns
# ONLY account [a] to that group (other accounts' assignments to the same
# group are untouched, so a group CAN have several accounts on it).
# ============================================================

PAGE_SIZE = 20


async def cmd_listgroups(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info(f"[Command] /listgroups called by {update.effective_user.id}")
    if not _is_admin(update.effective_user.id):
        return
    owner_id = update.effective_user.id
    await _show_groups_list(update.message, edit=False, page=0, owner_id=owner_id, view_label=None)


def _account_labels(owner_id: int) -> list:
    return sorted([a["label"] for a in db_get_all_accounts(owner_id)])


async def _show_groups_list(message, edit: bool = False, page: int = 0, owner_id: int = 0, view_label: str = None):
    rows = db_list_groups(owner_id)
    active_group = db_get_setting(owner_id, "active_group_id")
    target_group = db_get_setting(owner_id, "target_group_id")
    target_link = db_get_setting(owner_id, "target_group_link")
    auto_add_on = (db_get_setting(owner_id, "auto_add_enabled") or "true") == "true"
    assignment_map = db_get_group_assignment_map(owner_id)
    all_labels = _account_labels(owner_id)

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
    link_str = f"\n🔗 Target Link: {target_link}" if target_link else ""

    if view_label:
        header = f"🤖 Auto-Add: {auto_status}{link_str}\n👤 Account [{view_label}] view — ✅ ማለት ይህ group በ[{view_label}] ይሰራል\n📋 Groups ({start+1}-{start+len(page_rows)}/{total}):\n"
    else:
        header = f"🤖 Auto-Add: {auto_status}{link_str}\n📋 Groups ({start+1}-{start+len(page_rows)}/{total}):\n"

    lines = [header]
    keyboard = []

    for i, (gid, group_id, group_name, is_source) in enumerate(page_rows):
        num = start + i + 1
        tags = []
        if str(group_id) == active_group:
            tags.append("🟢")
        if str(group_id) == target_group:
            tags.append("🎯")
        assigned_labels = assignment_map.get(group_id, [])
        if assigned_labels:
            tags.append(f"[{','.join(assigned_labels)}]")
        tag_str = " ".join(tags)
        name_str = (group_name or str(group_id))[:20]

        if view_label:
            is_mine = view_label in assigned_labels
            source_icon = "✅" if is_mine else "⬜"
            lines.append(f"#{num} {source_icon} {name_str} {tag_str}")
            toggle_btn = InlineKeyboardButton(
                f"#{num} {'🔴 Remove' if is_mine else '✅ Assign'} [{view_label}]",
                callback_data=f"grp_toggle:{view_label}:{group_id}:{page}"
            )
            remove_btn = InlineKeyboardButton("❌", callback_data=f"grp_remove:{group_id}:{page}")
            keyboard.append([toggle_btn, remove_btn])
        else:
            source_icon = "✅" if is_source else "⬜"
            lines.append(f"#{num} {source_icon} {name_str} {tag_str}")
            if is_source:
                connect_btn = InlineKeyboardButton(f"#{num} 🔴 Disconnect", callback_data=f"grp_disconnect:{group_id}:{page}")
            else:
                connect_btn = InlineKeyboardButton(f"#{num} ✅ Connect (auto-assign)", callback_data=f"grp_connect:{group_id}:{page}")
            remove_btn = InlineKeyboardButton("❌", callback_data=f"grp_remove:{group_id}:{page}")
            keyboard.append([connect_btn, remove_btn])

    nav_row = []
    view_prefix = f"grp_view:{view_label}:" if view_label else "grp_page:"
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"{view_prefix}{page-1}"))
    nav_row.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="grp_noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"{view_prefix}{page+1}"))
    keyboard.append(nav_row)

    # Account-view switcher row
    account_row = []
    if view_label:
        account_row.append(InlineKeyboardButton("🌐 All (overview)", callback_data="grp_view_all:0"))
    for lbl in all_labels:
        icon = "👤" if lbl != view_label else "🔵"
        account_row.append(InlineKeyboardButton(f"{icon}{lbl}", callback_data=f"grp_view:{lbl}:0"))
    if account_row:
        # Telegram keyboards look better with rows of ~4 buttons
        for i in range(0, len(account_row), 4):
            keyboard.append(account_row[i:i+4])

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
    owner_id = query.from_user.id
    data = query.data

    if data == "grp_sync":
        await query.edit_message_text("🔄 Syncing...")
        await _sync_all_account_groups(owner_id)
        await _show_groups_list(query.message, edit=True, page=0, owner_id=owner_id, view_label=None)
        return

    if data == "grp_autoadd_toggle":
        current = (db_get_setting(owner_id, "auto_add_enabled") or "true") == "true"
        db_set_setting(owner_id, "auto_add_enabled", "false" if current else "true")
        await _show_groups_list(query.message, edit=True, page=0, owner_id=owner_id, view_label=None)
        return

    if data == "grp_noop":
        return

    if data.startswith("grp_view_all:"):
        page = int(data.split(":")[1])
        await _show_groups_list(query.message, edit=True, page=page, owner_id=owner_id, view_label=None)
        return

    if data.startswith("grp_view:"):
        _, label, page_str = data.split(":")
        await _show_groups_list(query.message, edit=True, page=int(page_str), owner_id=owner_id, view_label=label)
        return

    if data.startswith("grp_page:"):
        page = int(data.split(":")[1])
        await _show_groups_list(query.message, edit=True, page=page, owner_id=owner_id, view_label=None)
        return

    if data.startswith("grp_toggle:"):
        _, label, group_id_str, page_str = data.split(":")
        group_id = int(group_id_str)
        page = int(page_str)
        currently_assigned = label in db_get_labels_for_group(owner_id, group_id)
        if currently_assigned:
            db_unassign_group_from_account(owner_id, group_id, label)
        else:
            db_assign_group_to_account(owner_id, group_id, label)
            db_set_group_source(owner_id, group_id, True)
            asyncio.create_task(_add_assigned_accounts_to_source_group(group_id, owner_id, [label]))
        # If a group has no accounts left assigned, it's no longer a
        # live source group.
        if not db_get_labels_for_group(owner_id, group_id):
            db_set_group_source(owner_id, group_id, False)
        asyncio.create_task(_reload_listeners(owner_id))
        await _show_groups_list(query.message, edit=True, page=page, owner_id=owner_id, view_label=label)
        return

    parts = data.split(":")
    action = parts[0]
    group_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0

    if action == "grp_connect":
        # Auto-assign round-robin (a → b → c → a...) among accounts with
        # a live session, then join that account to the group and start
        # its listener.
        assigned_label = db_auto_assign_group(owner_id, group_id)
        if assigned_label:
            db_set_group_source(owner_id, group_id, True)
            asyncio.create_task(_reload_listeners(owner_id))
            asyncio.create_task(_add_assigned_accounts_to_source_group(group_id, owner_id, [assigned_label]))
        else:
            await query.answer("❌ Session ያለው account የለም!", show_alert=True)
    elif action == "grp_disconnect":
        # Fully disconnect — remove ALL accounts assigned to this group.
        for lbl in db_get_labels_for_group(owner_id, group_id):
            db_unassign_group_from_account(owner_id, group_id, lbl)
        db_set_group_source(owner_id, group_id, False)
        asyncio.create_task(_reload_listeners(owner_id))
    elif action == "grp_remove":
        db_delete_group(owner_id, group_id)

    await _show_groups_list(query.message, edit=True, page=page, owner_id=owner_id, view_label=None)


async def cmd_deletegroup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    owner_id = update.effective_user.id
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("❌ Format: /deletegroup -100xxxxxxx")
        return
    try:
        group_id = int(args[1])
        db_delete_group(owner_id, group_id)
        await update.message.reply_text(f"✅ {group_id} ተሰረዘ!")
    except ValueError:
        await update.message.reply_text("❌ Group ID ቁጥር መሆን አለበት!")


async def _handle_usend(update: Update, label: str):
    if not _is_admin(update.effective_user.id):
        return

    owner_id = update.effective_user.id
    account = db_get_account_by_label(owner_id, label)
    if not account:
        await update.message.reply_text(f"❌ Account [{label}] አልተገኘም!")
        return
    if not account.get("session"):
        await update.message.reply_text(f"❌ Account [{label}] session የለም!")
        return

    active_group_str = db_get_setting(owner_id, "active_group_id")
    if not active_group_str:
        await update.message.reply_text("❌ Active group አልተቀመጠም!")
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
        client = await _get_client(account, owner_id)
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


async def _do_broadcast(msg, users: list, status_msg, owner_id: int = 0):
    """Loops over potentially many users — wrapped in to_thread since a
    large broadcast list would otherwise hold the event loop hostage for
    its whole duration via repeated blocking DB calls between sends."""
    total = len(users)
    success = failed = 0

    dm_accounts = await asyncio.to_thread(get_dm_accounts, owner_id)
    if not dm_accounts:
        await status_msg.edit_text("❌ DM accounts አልተሟሉም! ቢያንስ 6 accounts ያስፈልጋሉ።")
        return

    for i, user_id in enumerate(users):
        account = await asyncio.to_thread(get_next_dm_account, owner_id)
        if not account:
            await status_msg.edit_text("❌ Available DM account የለም!")
            return

        try:
            client = await _get_client(account, owner_id)
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
            await asyncio.to_thread(db_set_flood, account["phone"], e.seconds)
            failed += 1
        except PeerFloodError:
            await asyncio.to_thread(db_set_spam, account["phone"])
            await _notify_admins(f"⚠️ Account [{account['label']}] {account['phone']} spam ban ሆነ!")
            failed += 1
        except Exception as e:
            err = str(e).lower()
            if "blocked" in err or "privacy" in err:
                await asyncio.to_thread(db_mark_user_blocked, user_id)
            else:
                logger.warning(f"[Broadcast] {user_id}: {e}")
            failed += 1

        if (i + 1) % 10 == 0:
            try:
                await status_msg.edit_text(f"⏳ እየሰራ ነው...\n📊 {i+1}/{total}\n✅ {success}\n❌ {failed}")
            except Exception:
                pass

        await asyncio.sleep(random.uniform(5, 10))

    await status_msg.edit_text(f"✅ Broadcast ተጠናቀቀ!\n👥 Total: {total}\n✅ Sent: {success}\n❌ Failed: {failed}")


async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return

    owner_id = update.effective_user.id
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
    status_msg = await update.message.reply_text(f"📤 Broadcast እየጀምር ነው...\n👥 Users: {total}")
    asyncio.create_task(_do_broadcast(update.message, recent_users, status_msg, owner_id))


async def cmd_myapi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info(f"[Command] /myapi called by {update.effective_user.id}")
    if not _is_admin(update.effective_user.id):
        return
    owner_id = update.effective_user.id
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT label, api_id, api_hash, phone FROM userbot_accounts WHERE owner_id=%s", (owner_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        await update.message.reply_text("📭 Account የለም")
        return
    lines = ["🔑 Account Details:\n"]
    for label, api_id, api_hash, phone in rows:
        lines.append(f"📱 {phone}\n🏷 Label: {label}\n🆔 API_ID: {api_id}\n🔑 API_HASH: {api_hash}")
    await update.message.reply_text("\n".join(lines))


async def cmd_ubothelp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.info(f"[Command] /ubothelp (or /status2) called by {update.effective_user.id}")
    if not _is_admin(update.effective_user.id):
        return
    owner_id = update.effective_user.id
    active_group = db_get_setting(owner_id, "active_group_id") or "❌ አልተቀመጠም"
    target_group = db_get_setting(owner_id, "target_group_id") or "❌ አልተቀመጠም"
    target_link = db_get_setting(owner_id, "target_group_link") or "❌ አልተቀመጠም"
    daily_limit = db_get_setting(owner_id, "daily_limit") or "❌ አልተቀመጠም"
    accounts = db_list_accounts(owner_id)
    groups = db_list_groups(owner_id)
    assignment_map = db_get_group_assignment_map(owner_id)
    now = datetime.now()

    acc_lines = []
    for _, label, phone, is_active, session, flood_until, spam_until in accounts:
        status = "✅" if is_active else "❌"
        has_session = "🔑" if session else "⚠️"
        flood = ""
        spam = ""
        if flood_until and flood_until > now:
            remaining = int((flood_until - now).total_seconds() / 60)
            flood = f" 🌊{remaining}min"
        if spam_until:
            if spam_until > now:
                remaining_hr = int((spam_until - now).total_seconds() / 3600)
                spam = f" 🚫spam {remaining_hr}hr"
            else:
                spam = " 🔍checking"
        daily = db_get_daily_add_count(label)
        my_groups = sum(1 for gid, labels in assignment_map.items() if label in labels)
        acc_lines.append(f"  {status}[{label}] {phone} {has_session} 🏠{my_groups} [{daily}/{daily_limit}]{flood}{spam}")

    source_groups = [g for g in groups if g[3]]
    grp_lines = []
    for _, group_id, group_name, is_source in source_groups:
        tags = []
        if str(group_id) == active_group:
            tags.append("🟢")
        if str(group_id) == target_group:
            tags.append("🎯")
        assigned_labels = assignment_map.get(group_id, [])
        labels_str = f"[{','.join(assigned_labels)}]" if assigned_labels else "[unassigned]"
        name_str = f" — {group_name}" if group_name else ""
        grp_lines.append(f"  ✅ {group_id}{name_str} {labels_str} {''.join(tags)}")

    auto_add_on = (db_get_setting(owner_id, "auto_add_enabled") or "true") == "true"
    auto_status = "🟢 ON" if auto_add_on else "🔴 OFF"
    uadmins = db_list_uadmins()
    uadmin_lines = [f"  🔹 {r[0]}" for r in uadmins] if uadmins else ["  📭 የለም"]
    api_id1 = db_get_setting(owner_id, "userbot_api_id") or "❌ አልተቀመጠም"

    text = (
        "🤖 Userbot Status & Commands\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"🤖 Auto-Add: {auto_status}\n"
        f"🟢 Active Group: {active_group}\n"
        f"🎯 Target Group: {target_group}\n"
        f"🔗 Target Link: {target_link}\n"
        f"📊 Daily Limit: {daily_limit} per account\n\n"
        f"🔑 API: {api_id1}\n\n"
        "👤 Accounts (each listens to its own assigned groups & adds itself):\n" +
        ("\n".join(acc_lines) if acc_lines else "  📭 የለም") +
        f"\n\n🏠 Source Groups ({len(source_groups)}/{len(groups)}):\n" +
        ("\n".join(grp_lines) if grp_lines else "  📭 የለም") +
        "\n\n👥 Userbot Admins:\n" +
        "\n".join(uadmin_lines) +
        "\n\n━━━━━━━━━━━━━━━━\n"
        "⚙️ Setup:\n"
        "/setuserapi api_id api_hash\n"
        "/addaccount a +phone\n"
        "/startsession +phone\n"
        "/verifycode +phone code\n"
        "/verify2fa +phone password\n"
        "/listaccounts\n"
        "/deleteaccount +phone\n"
        "/myapi\n\n"
        "/listgroups  (👤 buttons switch to per-account assign view)\n"
        "/syncgroups\n"
        "/addgroup -100xxxxxxx\n"
        "/deletegroup -100xxxxxxx\n\n"
        "/setactivegroup -100xxxxxxx\n"
        "/settargetgroup -100xxxxxxx\n"
        "/settargetlink https://t.me/+xxx\n"
        "/setlimit 50\n\n"
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
# GLOBAL ERROR HANDLER — so failures are visible in logs
# ============================================================

async def _global_error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    """PTB swallows unhandled exceptions unless an error handler is
    registered (that's the 'No error handlers are registered' warning).
    This logs the full traceback so real causes show up in Railway logs
    instead of the command just silently doing nothing."""
    logger.error(
        f"‼️ [UnhandledError] update={update} error={context.error}",
        exc_info=context.error
    )
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                f"❌ Internal error: {context.error}"
            )
    except Exception:
        pass


# ============================================================
# REGISTER ALL HANDLERS
# ============================================================

def register_userbot_handlers(app):
    set_bot_app(app)

    app.add_handler(CommandHandler("adduadmin", cmd_adduadmin))
    app.add_handler(CommandHandler("removeuadmin", cmd_removeuadmin))
    app.add_handler(CommandHandler("listuadmins", cmd_listuadmins))
    app.add_handler(CommandHandler("setuserapi", cmd_setuserapi))
    app.add_handler(CommandHandler("addaccount", cmd_addaccount))
    app.add_handler(CommandHandler("startsession", cmd_startsession))
    app.add_handler(CommandHandler("verifycode", cmd_verifycode))
    app.add_handler(CommandHandler("verify2fa", cmd_verify2fa))
    app.add_handler(CommandHandler("listaccounts", cmd_listaccounts))
    app.add_handler(CommandHandler("deleteaccount", cmd_deleteaccount))
    app.add_handler(CommandHandler("addgroup", cmd_addgroup))
    app.add_handler(CommandHandler("syncgroups", cmd_syncgroups))
    app.add_handler(CommandHandler("listgroups", cmd_listgroups))
    app.add_handler(CommandHandler("deletegroup", cmd_deletegroup))
    app.add_handler(CommandHandler("setactivegroup", cmd_setactivegroup))
    app.add_handler(CommandHandler("settargetgroup", cmd_settargetgroup))
    app.add_handler(CommandHandler("settargetlink", cmd_settargetlink))
    app.add_handler(CommandHandler("setlimit", cmd_setlimit))
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

    app.add_error_handler(_global_error_handler)

    logger.info("✅ Userbot handlers registered (no listener/worker split — each account handles its own assigned groups)")
