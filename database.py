import psycopg2
import json as _json
import re
from datetime import datetime, timedelta
from config import DATABASE_URLS, DB_ROW_LIMIT

# ============================================================
# DB CONNECTION MANAGER — 4 DB rotation
# ============================================================

_current_db_index = 0


def get_all_db_urls():
    return DATABASE_URLS


def get_current_db_index():
    return _current_db_index


def set_current_db_index(index: int):
    global _current_db_index
    _current_db_index = index % len(DATABASE_URLS)


def get_conn(db_index: int = None):
    idx = db_index if db_index is not None else _current_db_index
    url = DATABASE_URLS[idx]
    return psycopg2.connect(url, sslmode='require')


def get_db_row_count(db_index: int) -> int:
    try:
        conn = get_conn(db_index)
        cur = conn.cursor()
        cur.execute("""
            SELECT SUM(n_live_tup) FROM pg_stat_user_tables
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()
        return int(row[0] or 0)
    except Exception:
        return 0


def check_and_rotate_db():
    global _current_db_index
    count = get_db_row_count(_current_db_index)
    if count >= DB_ROW_LIMIT and len(DATABASE_URLS) > 1:
        next_index = (_current_db_index + 1) % len(DATABASE_URLS)
        _migrate_active_game(_current_db_index, next_index)
        _current_db_index = next_index
        return True
    return False


def _migrate_active_game(from_idx: int, to_idx: int):
    try:
        from_conn = get_conn(from_idx)
        to_conn = get_conn(to_idx)
        from_cur = from_conn.cursor()
        to_cur = to_conn.cursor()

        _init_db_conn(to_conn, to_cur)

        from_cur.execute("SELECT * FROM game_settings WHERE is_active = TRUE ORDER BY id DESC LIMIT 1")
        settings_row = from_cur.fetchone()
        if not settings_row:
            return

        from_cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='game_settings' ORDER BY ordinal_position")
        cols = [r[0] for r in from_cur.fetchall()]
        settings_dict = dict(zip(cols, settings_row))
        game_id = settings_dict["id"]

        to_cur.execute("UPDATE game_settings SET is_active = FALSE")
        to_cur.execute("""
            INSERT INTO game_settings
            (total_numbers, numbers_per_person, price_full, price_half,
             prize_1st, prize_2nd, prize_3rd, payment_info,
             board_message_id, remaining_message_id, group_id, is_active)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
            RETURNING id
        """, (
            settings_dict["total_numbers"], settings_dict["numbers_per_person"],
            settings_dict["price_full"], settings_dict.get("price_half"),
            settings_dict["prize_1st"], settings_dict.get("prize_2nd"),
            settings_dict.get("prize_3rd"), settings_dict["payment_info"],
            settings_dict.get("board_message_id"), settings_dict.get("remaining_message_id"),
            settings_dict.get("group_id"),
        ))
        new_game_id = to_cur.fetchone()[0]

        from_cur.execute("SELECT * FROM registrations WHERE game_id=%s", (game_id,))
        regs = from_cur.fetchall()
        from_cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='registrations' ORDER BY ordinal_position")
        reg_cols = [r[0] for r in from_cur.fetchall()]
        for reg in regs:
            rd = dict(zip(reg_cols, reg))
            to_cur.execute("""
                INSERT INTO registrations
                (game_id, user_id, user_name, number, is_half, slot, is_paid, is_nekay, pending_upgrade)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (new_game_id, rd["user_id"], rd["user_name"], rd["number"],
                  rd["is_half"], rd["slot"], rd["is_paid"], rd.get("is_nekay", False),
                  rd.get("pending_upgrade", False)))

        from_cur.execute("SELECT * FROM user_balance WHERE group_id=%s", (settings_dict.get("group_id"),))
        balances = from_cur.fetchall()
        for bal in balances:
            to_cur.execute("""
                INSERT INTO user_balance (group_id, telegram_id, balance, carry_balance, prize_balance)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (group_id, telegram_id) DO UPDATE
                    SET balance=EXCLUDED.balance,
                        carry_balance=EXCLUDED.carry_balance,
                        prize_balance=EXCLUDED.prize_balance
            """, (settings_dict.get("group_id"), bal[2], bal[3], bal[4], bal[5]))

        from_cur.execute("SELECT * FROM winners WHERE game_id=%s", (game_id,))
        winners = from_cur.fetchall()
        for w in winners:
            to_cur.execute("""
                INSERT INTO winners (game_id, place, telegram_id, user_name, number, prize, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
            """, (new_game_id, w[2], w[3], w[4], w[5], w[6], w[7]))

        to_conn.commit()
        from_cur.close()
        from_conn.close()
        to_cur.close()
        to_conn.close()

    except Exception as e:
        import logging
        logging.error(f"[DB Migration] Error: {e}", exc_info=True)


def _init_db_conn(conn, cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS game_settings (
            id SERIAL PRIMARY KEY,
            total_numbers INT,
            numbers_per_person INT,
            price_full INT,
            price_half INT,
            prize_1st INT,
            prize_2nd INT,
            prize_3rd INT,
            payment_info TEXT,
            board_message_id BIGINT,
            remaining_message_id BIGINT,
            group_id BIGINT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS registrations (
            id SERIAL PRIMARY KEY,
            game_id INT REFERENCES game_settings(id),
            user_id BIGINT,
            user_name TEXT,
            number INT,
            is_half BOOLEAN DEFAULT FALSE,
            slot INT DEFAULT 1,
            is_paid BOOLEAN DEFAULT FALSE,
            is_nekay BOOLEAN DEFAULT FALSE,
            pending_upgrade BOOLEAN DEFAULT FALSE,
            registered_at TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS user_balance (
            id SERIAL PRIMARY KEY,
            group_id BIGINT NOT NULL,
            telegram_id BIGINT,
            balance NUMERIC DEFAULT 0,
            carry_balance NUMERIC DEFAULT 0,
            prize_balance NUMERIC DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(group_id, telegram_id)
        );

        CREATE TABLE IF NOT EXISTS sms_payments (
            id SERIAL PRIMARY KEY,
            group_id BIGINT,
            ref_no TEXT,
            amount NUMERIC,
            sender_name TEXT,
            pay_type TEXT,
            raw_sms TEXT,
            matched BOOLEAN DEFAULT FALSE,
            matched_data JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS winners (
            id SERIAL PRIMARY KEY,
            game_id INT REFERENCES game_settings(id),
            place INT,
            telegram_id BIGINT,
            user_name TEXT,
            number INT,
            prize NUMERIC,
            sent BOOLEAN DEFAULT FALSE,
            group_id BIGINT,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(game_id, place)
        );

        CREATE TABLE IF NOT EXISTS screenshot_payments (
            id SERIAL PRIMARY KEY,
            group_id BIGINT,
            telegram_id BIGINT,
            ref_no TEXT,
            amount NUMERIC,
            sender_name TEXT,
            pay_type TEXT,
            description TEXT,
            matched BOOLEAN DEFAULT FALSE,
            matched_data JSONB,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(group_id, telegram_id, ref_no)
        );

        CREATE TABLE IF NOT EXISTS failed_attempts (
            id SERIAL PRIMARY KEY,
            game_id INT REFERENCES game_settings(id),
            user_id BIGINT,
            number INT,
            reason TEXT,
            taken_by_slot1 TEXT,
            taken_by_slot2 TEXT,
            taken_type_slot1 TEXT,
            taken_type_slot2 TEXT,
            attempted_at TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS groups (
            id SERIAL PRIMARY KEY,
            group_id BIGINT UNIQUE NOT NULL,
            group_name TEXT,
            is_enabled BOOLEAN DEFAULT FALSE,
            enabled_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS group_admins (
            id SERIAL PRIMARY KEY,
            group_id BIGINT NOT NULL,
            telegram_id BIGINT NOT NULL,
            added_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(group_id, telegram_id)
        );

        CREATE TABLE IF NOT EXISTS group_members (
            id SERIAL PRIMARY KEY,
            group_id BIGINT NOT NULL,
            username TEXT NOT NULL,
            first_seen TIMESTAMP DEFAULT NOW(),
            last_seen TIMESTAMP DEFAULT NOW(),
            is_read BOOLEAN DEFAULT FALSE,
            UNIQUE(group_id, username)
        );

        CREATE TABLE IF NOT EXISTS group_activity (
            id SERIAL PRIMARY KEY,
            group_id BIGINT NOT NULL,
            messages INT DEFAULT 0,
            registrations INT DEFAULT 0,
            payments INT DEFAULT 0,
            last_active TIMESTAMP DEFAULT NOW(),
            date DATE DEFAULT CURRENT_DATE,
            UNIQUE(group_id, date)
        );

        CREATE TABLE IF NOT EXISTS complete_stickers (
            id SERIAL PRIMARY KEY,
            file_id TEXT NOT NULL,
            added_at TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()


def init_db():
    for i in range(len(DATABASE_URLS)):
        try:
            conn = get_conn(i)
            cur = conn.cursor()
            _init_db_conn(conn, cur)

            cur.execute("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS is_paid BOOLEAN DEFAULT FALSE;")
            cur.execute("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS is_nekay BOOLEAN DEFAULT FALSE;")
            cur.execute("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS pending_upgrade BOOLEAN DEFAULT FALSE;")
            cur.execute("ALTER TABLE winners ADD COLUMN IF NOT EXISTS greeted BOOLEAN DEFAULT FALSE;")
            cur.execute("ALTER TABLE winners ADD COLUMN IF NOT EXISTS sent BOOLEAN DEFAULT FALSE;")
            cur.execute("ALTER TABLE winners ADD COLUMN IF NOT EXISTS group_id BIGINT;")
            cur.execute("ALTER TABLE game_settings ADD COLUMN IF NOT EXISTS group_id BIGINT;")
            cur.execute("ALTER TABLE game_settings ADD COLUMN IF NOT EXISTS countdown_enabled BOOLEAN DEFAULT TRUE;")
            cur.execute("ALTER TABLE game_settings ADD COLUMN IF NOT EXISTS countdown_minutes NUMERIC DEFAULT 2;")
            cur.execute("ALTER TABLE game_settings ADD COLUMN IF NOT EXISTS game_rule TEXT;")
            cur.execute("ALTER TABLE game_settings ADD COLUMN IF NOT EXISTS slot_symbol TEXT DEFAULT '#';")
            cur.execute("ALTER TABLE groups ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;")
            cur.execute("ALTER TABLE user_balance ADD COLUMN IF NOT EXISTS group_id BIGINT;")
            cur.execute("ALTER TABLE user_balance ADD COLUMN IF NOT EXISTS carry_balance NUMERIC DEFAULT 0;")
            cur.execute("ALTER TABLE user_balance ADD COLUMN IF NOT EXISTS prize_balance NUMERIC DEFAULT 0;")
            cur.execute("ALTER TABLE sms_payments ADD COLUMN IF NOT EXISTS group_id BIGINT;")
            cur.execute("ALTER TABLE screenshot_payments ADD COLUMN IF NOT EXISTS group_id BIGINT;")

            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'user_balance_game_id_telegram_id_key'
                    ) THEN
                        ALTER TABLE user_balance DROP CONSTRAINT user_balance_game_id_telegram_id_key;
                    END IF;
                END
                $$;
            """)
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'user_balance_group_id_telegram_id_key'
                    ) THEN
                        ALTER TABLE user_balance ADD CONSTRAINT user_balance_group_id_telegram_id_key
                        UNIQUE (group_id, telegram_id);
                    END IF;
                END
                $$;
            """)

            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'sms_payments_ref_no_key'
                    ) THEN
                        ALTER TABLE sms_payments DROP CONSTRAINT sms_payments_ref_no_key;
                    END IF;
                END
                $$;
            """)
            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'screenshot_payments_ref_no_key'
                    ) THEN
                        ALTER TABLE screenshot_payments DROP CONSTRAINT screenshot_payments_ref_no_key;
                    END IF;
                END
                $$;
            """)

            cur.execute("ALTER TABLE sms_payments ALTER COLUMN ref_no DROP NOT NULL;")
            cur.execute("ALTER TABLE sms_payments ADD COLUMN IF NOT EXISTS sender_name TEXT;")
            cur.execute("ALTER TABLE screenshot_payments ADD COLUMN IF NOT EXISTS amount NUMERIC;")
            cur.execute("ALTER TABLE screenshot_payments ADD COLUMN IF NOT EXISTS sender_name TEXT;")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS warning_media (
                    id SERIAL PRIMARY KEY,
                    minutes NUMERIC NOT NULL UNIQUE,
                    file_id TEXT NOT NULL,
                    media_type TEXT DEFAULT 'photo',
                    added_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS balance_transactions (
                    id SERIAL PRIMARY KEY,
                    group_id BIGINT NOT NULL,
                    game_id INT NOT NULL,
                    telegram_id BIGINT NOT NULL,
                    amount NUMERIC NOT NULL,
                    reason TEXT NOT NULL,
                    number INT,
                    done_by TEXT DEFAULT 'system',
                    balance_after NUMERIC,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_bal_tx_user
                ON balance_transactions(group_id, telegram_id, game_id)
            """)
            cur.execute("""
                ALTER TABLE user_balance ADD COLUMN IF NOT EXISTS winner_carried BOOLEAN DEFAULT FALSE;
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS complete_stickers (
                    id SERIAL PRIMARY KEY,
                    file_id TEXT NOT NULL,
                    added_at TIMESTAMP DEFAULT NOW()
                )
            """)

            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            import logging
            logging.warning(f"[init_db] DB {i} error: {e}")


# ============================================================
# COMPLETE STICKERS
# ============================================================

def add_complete_sticker(file_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO complete_stickers (file_id) VALUES (%s)
    """, (file_id,))
    conn.commit()
    cur.close()
    conn.close()


def get_complete_stickers() -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, file_id, added_at FROM complete_stickers ORDER BY added_at ASC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "file_id": r[1], "added_at": r[2]} for r in rows]


def remove_complete_sticker_by_index(index: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM complete_stickers ORDER BY added_at ASC")
    rows = cur.fetchall()
    if index < 1 or index > len(rows):
        cur.close()
        conn.close()
        return False
    target_id = rows[index - 1][0]
    cur.execute("DELETE FROM complete_stickers WHERE id=%s", (target_id,))
    conn.commit()
    cur.close()
    conn.close()
    return True


# ============================================================
# GROUP MANAGEMENT
# ============================================================

def enable_group(group_id: int, group_name: str = None) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO groups (group_id, group_name, is_enabled, enabled_at)
        VALUES (%s, %s, TRUE, NOW())
        ON CONFLICT (group_id) DO UPDATE
            SET is_enabled=TRUE, enabled_at=NOW(),
                group_name=COALESCE(EXCLUDED.group_name, groups.group_name)
    """, (group_id, group_name))
    conn.commit()
    cur.close()
    conn.close()
    return True


def disable_group(group_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE groups SET is_enabled=FALSE WHERE group_id=%s", (group_id,))
    conn.commit()
    cur.close()
    conn.close()
    return True


def is_group_enabled(group_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT is_enabled FROM groups WHERE group_id=%s", (group_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return bool(row and row[0])


def get_enabled_groups() -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT group_id, group_name, enabled_at
        FROM groups WHERE is_enabled=TRUE ORDER BY enabled_at DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"group_id": r[0], "group_name": r[1], "enabled_at": r[2]} for r in rows]


def register_group(group_id: int, group_name: str = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO groups (group_id, group_name, is_enabled)
        VALUES (%s, %s, FALSE)
        ON CONFLICT (group_id) DO UPDATE
            SET group_name=COALESCE(EXCLUDED.group_name, groups.group_name)
    """, (group_id, group_name))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# GROUP ADMIN MANAGEMENT
# ============================================================

def add_group_admin(group_id: int, telegram_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO group_admins (group_id, telegram_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
    """, (group_id, telegram_id))
    conn.commit()
    cur.close()
    conn.close()
    return True


def remove_group_admin(group_id: int, telegram_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM group_admins WHERE group_id=%s AND telegram_id=%s", (group_id, telegram_id))
    conn.commit()
    cur.close()
    conn.close()
    return True


def is_group_admin(group_id: int, telegram_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM group_admins WHERE group_id=%s AND telegram_id=%s
    """, (group_id, telegram_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row is not None


def get_group_admins(group_id: int) -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT telegram_id FROM group_admins WHERE group_id=%s", (group_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [r[0] for r in rows]


# ============================================================
# USERNAME TRACKING
# ============================================================

def track_username(group_id: int, username: str):
    if not username or username.strip() == "":
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO group_members (group_id, username, first_seen, last_seen, is_read)
        VALUES (%s, %s, NOW(), NOW(), FALSE)
        ON CONFLICT (group_id, username) DO UPDATE
            SET last_seen=NOW(), is_read=FALSE
    """, (group_id, username.strip()))
    conn.commit()
    cur.close()
    conn.close()


def get_usernames(group_id: int) -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT username, is_read, last_seen
        FROM group_members
        WHERE group_id=%s
        ORDER BY last_seen DESC
    """, (group_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"username": r[0], "is_read": r[1], "last_seen": r[2]} for r in rows]


def mark_usernames_read(group_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE group_members SET is_read=TRUE WHERE group_id=%s", (group_id,))
    conn.commit()
    cur.close()
    conn.close()


def clear_usernames(group_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM group_members WHERE group_id=%s", (group_id,))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# GROUP ACTIVITY TRACKING
# ============================================================

def log_activity(group_id: int, messages: int = 0, registrations: int = 0, payments: int = 0):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO group_activity (group_id, messages, registrations, payments, last_active, date)
        VALUES (%s, %s, %s, %s, NOW(), CURRENT_DATE)
        ON CONFLICT (group_id, date) DO UPDATE
            SET messages = group_activity.messages + EXCLUDED.messages,
                registrations = group_activity.registrations + EXCLUDED.registrations,
                payments = group_activity.payments + EXCLUDED.payments,
                last_active = NOW()
    """, (group_id, messages, registrations, payments))
    conn.commit()
    cur.close()
    conn.close()


def get_activity(group_id: int = None) -> list:
    conn = get_conn()
    cur = conn.cursor()
    if group_id:
        cur.execute("""
            SELECT group_id, SUM(messages), SUM(registrations), SUM(payments), MAX(last_active)
            FROM group_activity
            WHERE group_id=%s
            GROUP BY group_id
        """, (group_id,))
    else:
        cur.execute("""
            SELECT ga.group_id, SUM(ga.messages), SUM(ga.registrations), SUM(ga.payments), MAX(ga.last_active),
                   g.group_name
            FROM group_activity ga
            LEFT JOIN groups g ON g.group_id = ga.group_id
            WHERE g.is_enabled = TRUE
            GROUP BY ga.group_id, g.group_name
            ORDER BY MAX(ga.last_active) DESC
        """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if group_id:
        return [{"group_id": r[0], "messages": r[1], "registrations": r[2], "payments": r[3], "last_active": r[4]} for r in rows]
    return [{"group_id": r[0], "messages": r[1], "registrations": r[2], "payments": r[3], "last_active": r[4], "group_name": r[5]} for r in rows]


# ============================================================
# DB STATUS
# ============================================================

def get_db_status() -> list:
    result = []
    for i, url in enumerate(DATABASE_URLS):
        try:
            count = get_db_row_count(i)
            is_active = (i == _current_db_index)
            result.append({
                "index": i + 1,
                "row_count": count,
                "limit": DB_ROW_LIMIT,
                "is_active": is_active,
                "is_full": count >= DB_ROW_LIMIT,
                "percent": round((count / DB_ROW_LIMIT) * 100, 1) if DB_ROW_LIMIT > 0 else 0
            })
        except Exception:
            result.append({"index": i + 1, "row_count": -1, "is_active": False, "error": True})
    return result


def clear_db_data(db_index: int):
    conn = get_conn(db_index - 1)
    cur = conn.cursor()
    cur.execute("DELETE FROM registrations")
    cur.execute("DELETE FROM user_balance")
    cur.execute("DELETE FROM winners")
    cur.execute("DELETE FROM sms_payments")
    cur.execute("DELETE FROM screenshot_payments")
    cur.execute("DELETE FROM failed_attempts")
    cur.execute("DELETE FROM group_activity")
    cur.execute("UPDATE game_settings SET is_active=FALSE")
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# GAME SETTINGS
# ============================================================

def save_settings(data: dict, group_id: int = None):
    conn = get_conn()
    cur = conn.cursor()
    if group_id:
        cur.execute("UPDATE game_settings SET is_active = FALSE WHERE group_id=%s", (group_id,))
    else:
        cur.execute("UPDATE game_settings SET is_active = FALSE")
    cur.execute("""
        INSERT INTO game_settings
        (total_numbers, numbers_per_person, price_full, price_half,
         prize_1st, prize_2nd, prize_3rd, payment_info, group_id,
         countdown_enabled, countdown_minutes, game_rule, slot_symbol)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        data["total_numbers"], data["numbers_per_person"],
        data["price_full"], data.get("price_half"),
        data["prize_1st"], data.get("prize_2nd"), data.get("prize_3rd"),
        data["payment_info"], group_id,
        data.get("countdown_enabled", True),
        data.get("countdown_minutes", 2),
        data.get("game_rule") or None,
        data.get("slot_symbol") or "#",
    ))
    game_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return game_id


def get_active_settings(group_id: int = None):
    conn = get_conn()
    cur = conn.cursor()
    if group_id:
        cur.execute("""
            SELECT * FROM game_settings
            WHERE is_active = TRUE AND group_id=%s
            ORDER BY id DESC LIMIT 1
        """, (group_id,))
    else:
        cur.execute("""
            SELECT * FROM game_settings
            WHERE is_active = TRUE ORDER BY id DESC LIMIT 1
        """)
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    cols = ["id", "total_numbers", "numbers_per_person", "price_full", "price_half",
            "prize_1st", "prize_2nd", "prize_3rd", "payment_info",
            "board_message_id", "remaining_message_id", "group_id",
            "is_active", "created_at", "countdown_enabled", "countdown_minutes",
            "game_rule", "slot_symbol"]
    return dict(zip(cols, row))


def update_countdown_settings(game_id: int, enabled: bool, minutes: float):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE game_settings
        SET countdown_enabled=%s, countdown_minutes=%s
        WHERE id=%s
    """, (enabled, minutes, game_id))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# WARNING MEDIA
# ============================================================

def set_warning_media(minutes: float, file_id: str, media_type: str, set_by: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO warning_media (minutes, file_id, media_type)
        VALUES (%s, %s, %s)
        ON CONFLICT (minutes) DO UPDATE
            SET file_id=EXCLUDED.file_id,
                media_type=EXCLUDED.media_type,
                added_at=NOW()
    """, (minutes, file_id, media_type))
    conn.commit()
    cur.close()
    conn.close()


def get_warning_media(minutes: float) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT minutes, file_id, media_type
        FROM warning_media
        ORDER BY ABS(minutes - %s) ASC
        LIMIT 1
    """, (minutes,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {"minutes": float(row[0]), "file_id": row[1], "media_type": row[2]}


def get_all_warning_media() -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT minutes, file_id, media_type FROM warning_media ORDER BY minutes")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"minutes": float(r[0]), "file_id": r[1], "media_type": r[2]} for r in rows]


def delete_warning_media(minutes: float):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM warning_media WHERE minutes=%s", (minutes,))
    conn.commit()
    cur.close()
    conn.close()


def update_board_message_id(game_id, msg_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE game_settings SET board_message_id=%s WHERE id=%s", (msg_id, game_id))
    conn.commit()
    cur.close()
    conn.close()


def update_remaining_message_id(game_id, msg_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE game_settings SET remaining_message_id=%s WHERE id=%s", (msg_id, game_id))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# REGISTRATIONS
# ============================================================

def get_registrations(game_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT number, user_name, is_half, slot
        FROM registrations WHERE game_id=%s ORDER BY number, slot
    """, (game_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def register_number(game_id, user_id, user_name, number, is_half, force=False, allow_toggle=True, is_parsed_name=False):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT user_name, is_half, slot FROM registrations
        WHERE game_id=%s AND number=%s ORDER BY slot
    """, (game_id, number))
    existing = cur.fetchall()

    cur.execute("SELECT price_full, price_half, group_id FROM game_settings WHERE id=%s", (game_id,))
    price_row = cur.fetchone()
    price_full = float(price_row[0] or 0)
    price_half = float(price_row[1] or 0)
    group_id = price_row[2]
    cost = price_half if is_half else price_full

    cur.execute("""
        SELECT balance, carry_balance, prize_balance FROM user_balance
        WHERE group_id=%s AND telegram_id=%s
    """, (group_id, user_id))
    bal_row = cur.fetchone()
    carry_balance = float(bal_row[1]) if bal_row else 0.0
    prize_balance = float(bal_row[2]) if bal_row else 0.0
    total_balance = carry_balance + prize_balance
    can_pay = total_balance >= cost

    if force and existing:
        cur.execute("""
            UPDATE registrations
            SET user_id=%s, user_name=%s, is_half=%s, is_nekay=FALSE,
                is_paid=%s, pending_upgrade=FALSE, registered_at=NOW()
            WHERE game_id=%s AND number=%s AND slot=1
        """, (user_id, user_name, is_half, can_pay, game_id, number))
        if not is_half:
            cur.execute("DELETE FROM registrations WHERE game_id=%s AND number=%s AND slot=2", (game_id, number))
        if can_pay:
            _deduct_balance(cur, group_id, user_id, cost, prize_balance, carry_balance)
        conn.commit()
        cur.close()
        conn.close()
        return "registered"

    if not existing:
        cur.execute("""
            INSERT INTO registrations (game_id, user_id, user_name, number, is_half, slot, is_paid, is_nekay, pending_upgrade)
            VALUES (%s, %s, %s, %s, %s, 1, %s, FALSE, FALSE)
        """, (game_id, user_id, user_name, number, is_half, can_pay))
        if can_pay:
            _deduct_balance(cur, group_id, user_id, cost, prize_balance, carry_balance)
        conn.commit()
        cur.close()
        conn.close()
        return "registered"

    cur.execute("""
        SELECT user_id, user_name FROM registrations
        WHERE game_id=%s AND number=%s AND slot=1
    """, (game_id, number))
    owner_row = cur.fetchone()
    if owner_row and owner_row[0] == user_id:
        old_name = owner_row[1]
        if is_parsed_name and user_name and user_name.strip() != old_name:
            cur.execute("""
                UPDATE registrations SET user_name=%s
                WHERE game_id=%s AND number=%s AND user_id=%s
            """, (user_name.strip(), game_id, number, user_id))
            conn.commit()

        cur.close()
        conn.close()
        if not allow_toggle:
            target = "half" if is_half else "full"
        elif is_half:
            current_is_half = existing[0][1]
            target = "full" if current_is_half else "half"
        else:
            target = "full"
        return change_number_type(game_id, user_id, number, target)

    if len(existing) == 1 and existing[0][1] == True:
        is_half = True
        cost = price_half
        can_pay = total_balance >= cost
        cur.execute("""
            INSERT INTO registrations (game_id, user_id, user_name, number, is_half, slot, is_paid, is_nekay, pending_upgrade)
            VALUES (%s, %s, %s, %s, %s, 2, %s, FALSE, FALSE)
        """, (game_id, user_id, user_name, number, is_half, can_pay))
        if can_pay:
            _deduct_balance(cur, group_id, user_id, cost, prize_balance, carry_balance)
        conn.commit()
        cur.close()
        conn.close()
        return "registered_half"

    conn.commit()
    cur.close()
    conn.close()
    save_failed_attempt(game_id, user_id, number, "taken", taken={number: existing})
    return "taken"


def _deduct_balance(cur, group_id: int, user_id: int, cost: float, prize_balance: float, carry_balance: float):
    if prize_balance >= cost:
        new_prize = prize_balance - cost
        new_carry = carry_balance
    else:
        new_prize = 0
        new_carry = carry_balance - (cost - prize_balance)

    new_total = new_carry + new_prize
    cur.execute("""
        UPDATE user_balance
        SET balance=%s, carry_balance=%s, prize_balance=%s, updated_at=NOW()
        WHERE group_id=%s AND telegram_id=%s
    """, (new_total, new_carry, new_prize, group_id, user_id))


def get_taken_numbers(game_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT number, user_name, is_half, slot, is_paid, pending_upgrade
        FROM registrations WHERE game_id=%s ORDER BY number, slot
    """, (game_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = {}
    for number, user_name, is_half, slot, is_paid, pending_upgrade in rows:
        if number not in result:
            result[number] = []
        result[number].append((user_name, is_half, slot, is_paid, pending_upgrade))
    return result


def all_numbers_paid(game_id: int, settings: dict) -> bool:
    taken = get_taken_numbers(game_id)
    total = settings["total_numbers"]
    per_person = settings["numbers_per_person"]

    if per_person == 1:
        number_range = range(1, total + 1)
    else:
        number_range = range(1, total + 1, per_person)

    for n in number_range:
        entry = taken.get(n, [])
        if not entry:
            return False
        for name, is_half, slot, is_paid, pending_upgrade in entry:
            if not is_paid or pending_upgrade:
                return False
        if len(entry) == 1 and entry[0][1]:
            return False

    return True


# ============================================================
# PAYMENT CONFIRMATION
# ============================================================

def confirm_payment(telegram_id: int, amount: float, group_id: int = None) -> dict:
    conn = get_conn()
    cur = conn.cursor()

    if group_id:
        cur.execute("""
            SELECT id, price_full, price_half
            FROM game_settings WHERE is_active = TRUE AND group_id=%s ORDER BY id DESC LIMIT 1
        """, (group_id,))
    else:
        cur.execute("""
            SELECT id, price_full, price_half
            FROM game_settings WHERE is_active = TRUE ORDER BY id DESC LIMIT 1
        """)
    game_row = cur.fetchone()
    if not game_row:
        cur.close()
        conn.close()
        return {"confirmed": [], "remaining_balance": amount}

    game_id, price_full, price_half = game_row
    price_full = float(price_full or 0)
    price_half = float(price_half or 0)

    _group_id = group_id
    if not _group_id:
        cur.execute("SELECT group_id FROM game_settings WHERE id=%s", (game_id,))
        r = cur.fetchone()
        _group_id = r[0] if r else None

    cur.execute("""
        INSERT INTO user_balance (group_id, telegram_id, balance, carry_balance, prize_balance)
        VALUES (%s, %s, %s, %s, 0)
        ON CONFLICT (group_id, telegram_id)
        DO UPDATE SET
            carry_balance = user_balance.carry_balance + %s,
            balance = user_balance.balance + %s,
            updated_at = NOW()
        RETURNING carry_balance, prize_balance
    """, (_group_id, telegram_id, amount, amount, amount, amount))
    row = cur.fetchone()
    carry_balance = float(row[0])
    prize_balance = float(row[1])
    conn.commit()

    remaining_prize = prize_balance
    remaining_carry = carry_balance
    confirmed = []

    cur.execute("""
        SELECT id, number, is_half, slot
        FROM registrations
        WHERE game_id = %s AND user_id = %s AND is_paid = TRUE AND pending_upgrade = TRUE
        ORDER BY registered_at
    """, (game_id, telegram_id))
    pending_upgrades = cur.fetchall()

    for reg_id, number, is_half, slot in pending_upgrades:
        cost = price_half
        total_remaining = remaining_prize + remaining_carry
        if total_remaining >= cost:
            cur.execute("UPDATE registrations SET pending_upgrade=FALSE, is_nekay=FALSE WHERE id=%s", (reg_id,))
            if remaining_prize >= cost:
                remaining_prize -= cost
            else:
                diff = cost - remaining_prize
                remaining_prize = 0
                remaining_carry -= diff
            confirmed.append({"number": number, "is_half": False, "slot": slot})

    cur.execute("""
        SELECT id, number, is_half, slot
        FROM registrations
        WHERE game_id = %s AND user_id = %s AND is_paid = FALSE AND is_nekay = FALSE
        ORDER BY registered_at, slot
    """, (game_id, telegram_id))
    unpaid = cur.fetchall()

    for reg_id, number, is_half, slot in unpaid:
        cost = price_half if is_half else price_full
        total_remaining = remaining_prize + remaining_carry
        if total_remaining >= cost:
            cur.execute("UPDATE registrations SET is_paid=TRUE, pending_upgrade=FALSE WHERE id=%s", (reg_id,))
            if remaining_prize >= cost:
                remaining_prize -= cost
            else:
                diff = cost - remaining_prize
                remaining_prize = 0
                remaining_carry -= diff
            confirmed.append({"number": number, "is_half": is_half, "slot": slot})

    cur.execute("""
        SELECT id, number, is_half, slot
        FROM registrations
        WHERE game_id = %s AND user_id = %s AND is_paid = FALSE AND is_nekay = TRUE
        ORDER BY registered_at, slot
    """, (game_id, telegram_id))
    nekay_unpaid = cur.fetchall()

    for reg_id, number, is_half, slot in nekay_unpaid:
        cost = price_half if is_half else price_full
        total_remaining = remaining_prize + remaining_carry
        if total_remaining >= cost:
            cur.execute("UPDATE registrations SET is_paid=TRUE, is_nekay=FALSE, pending_upgrade=FALSE WHERE id=%s", (reg_id,))
            if remaining_prize >= cost:
                remaining_prize -= cost
            else:
                diff = cost - remaining_prize
                remaining_prize = 0
                remaining_carry -= diff
            confirmed.append({"number": number, "is_half": is_half, "slot": slot})

    new_total = remaining_carry + remaining_prize
    cur.execute("""
        UPDATE user_balance
        SET balance=%s, carry_balance=%s, prize_balance=%s, updated_at=NOW()
        WHERE group_id=%s AND telegram_id=%s
    """, (new_total, remaining_carry, remaining_prize, _group_id, telegram_id))

    conn.commit()
    cur.close()
    conn.close()

    if confirmed and _group_id:
        try:
            log_activity(_group_id, payments=1)
        except Exception:
            pass

    return {"confirmed": confirmed, "remaining_balance": new_total}


def get_paid_numbers(game_id: int) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT number, slot FROM registrations
        WHERE game_id = %s AND is_paid = TRUE
    """, (game_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = {}
    for number, slot in rows:
        if number not in result:
            result[number] = set()
        result[number].add(slot)
    return result


# ============================================================
# UNPAID NUMBERS
# ============================================================

def get_unpaid_numbers(game_id: int) -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT number, slot, is_half, pending_upgrade
        FROM registrations
        WHERE game_id=%s AND (is_paid=FALSE OR pending_upgrade=TRUE)
        ORDER BY number, slot
    """, (game_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = {}
    for number, slot, is_half, pending_upgrade in rows:
        if number not in result:
            result[number] = set()
        if pending_upgrade:
            result[number].add(2)
        else:
            result[number].add(slot)
    return [(n, slots) for n, slots in sorted(result.items())]


# ============================================================
# NEKAY — FIX 2a
# ============================================================

def mark_nekay(game_id: int, number: int):
    conn = get_conn()
    cur = conn.cursor()
    # is_paid=FALSE ያላቸው → is_nekay=TRUE
    cur.execute("""
        UPDATE registrations
        SET is_nekay=TRUE
        WHERE game_id=%s AND number=%s AND is_paid=FALSE
    """, (game_id, number))
    # pending_upgrade=TRUE ያላቸው → is_half=TRUE + is_nekay=TRUE + pending_upgrade=FALSE
    cur.execute("""
        UPDATE registrations
        SET is_nekay=TRUE,
            is_half=TRUE,
            pending_upgrade=FALSE
        WHERE game_id=%s AND number=%s AND is_paid=TRUE AND pending_upgrade=TRUE
    """, (game_id, number))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# WINNER FUNCTIONS
# ============================================================

def get_user_by_number(game_id: int, number: int) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, user_name FROM registrations
        WHERE game_id=%s AND number=%s
        ORDER BY is_paid DESC, slot ASC
        LIMIT 1
    """, (game_id, number))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {"telegram_id": row[0], "user_name": row[1]}


def add_winner_balance(game_id: int, telegram_id: int, amount: float, group_id: int = None):
    conn = get_conn()
    cur = conn.cursor()
    _group_id = group_id
    if not _group_id:
        cur.execute("SELECT group_id FROM game_settings WHERE id=%s", (game_id,))
        r = cur.fetchone()
        _group_id = r[0] if r else None
    cur.execute("""
        INSERT INTO user_balance (group_id, telegram_id, balance, carry_balance, prize_balance, winner_carried)
        VALUES (%s, %s, %s, 0, %s, FALSE)
        ON CONFLICT (group_id, telegram_id)
        DO UPDATE SET
            prize_balance = user_balance.prize_balance + %s,
            balance = user_balance.balance + %s,
            winner_carried = FALSE,
            updated_at = NOW()
    """, (_group_id, telegram_id, amount, amount, amount, amount))
    conn.commit()
    cur.close()
    conn.close()


def get_winner_by_place(game_id: int, place: int) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT w.telegram_id, w.user_name, w.prize,
               COALESCE(ub.balance, 0) as balance, w.group_id
        FROM winners w
        LEFT JOIN user_balance ub ON ub.group_id = w.group_id AND ub.telegram_id = w.telegram_id
        WHERE w.game_id = %s AND w.place = %s
    """, (game_id, place))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "telegram_id": row[0],
        "user_name": row[1],
        "prize": float(row[2]) if row[2] else 0,
        "balance": float(row[3]) if row[3] else 0,
        "group_id": row[4],
    }


def save_winner(game_id: int, place: int, telegram_id: int, user_name: str,
                number: int, prize: float, group_id: int = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO winners (game_id, place, telegram_id, user_name, number, prize, group_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (game_id, place) DO UPDATE
            SET telegram_id=EXCLUDED.telegram_id,
                user_name=EXCLUDED.user_name,
                number=EXCLUDED.number,
                prize=EXCLUDED.prize,
                group_id=EXCLUDED.group_id
    """, (game_id, place, telegram_id, user_name, number, prize, group_id))
    conn.commit()
    cur.close()
    conn.close()


def get_recent_winners(group_id: int, hours: int = 24) -> list:
    conn = get_conn()
    cur = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=hours)
    cur.execute("""
        SELECT w.place, w.user_name, w.prize, w.created_at,
               COALESCE(ub.balance, 0) as balance, w.sent
        FROM winners w
        LEFT JOIN user_balance ub ON ub.group_id = w.group_id AND ub.telegram_id = w.telegram_id
        WHERE w.group_id=%s AND w.created_at >= %s
        ORDER BY w.created_at DESC
    """, (group_id, cutoff))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{
        "place": r[0], "user_name": r[1], "prize": float(r[2] or 0),
        "created_at": r[3], "balance": float(r[4] or 0), "sent": r[5]
    } for r in rows]


def cleanup_old_winners():
    conn = get_conn()
    cur = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=24)
    cur.execute("""
        DELETE FROM winners w
        USING user_balance ub
        WHERE w.telegram_id = ub.telegram_id
          AND w.group_id = ub.group_id
          AND w.created_at < %s
          AND COALESCE(ub.balance, 0) <= 0
    """, (cutoff,))
    conn.commit()
    cur.close()
    conn.close()


def mark_winner_sent(game_id: int, telegram_id: int, amount: float):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE winners SET sent=TRUE WHERE game_id=%s AND telegram_id=%s
    """, (game_id, telegram_id))
    conn.commit()
    cur.close()
    conn.close()


def deduct_winner_balance(game_id: int, telegram_id: int, amount: float, group_id: int = None) -> dict:
    conn = get_conn()
    cur = conn.cursor()

    _group_id = group_id
    if not _group_id:
        cur.execute("SELECT group_id FROM game_settings WHERE id=%s", (game_id,))
        r = cur.fetchone()
        _group_id = r[0] if r else None

    cur.execute("""
        SELECT carry_balance, prize_balance FROM user_balance
        WHERE group_id=%s AND telegram_id=%s
    """, (_group_id, telegram_id))
    bal_row = cur.fetchone()
    if not bal_row:
        cur.close()
        conn.close()
        return {"new_balance": 0, "nekay_numbers": []}

    carry_balance = float(bal_row[0])
    prize_balance = float(bal_row[1])

    if prize_balance >= amount:
        new_prize = prize_balance - amount
        new_carry = carry_balance
    else:
        new_prize = 0
        new_carry = carry_balance - (amount - prize_balance)

    new_total = new_carry + new_prize

    cur.execute("""
        UPDATE user_balance
        SET balance=%s, carry_balance=%s, prize_balance=%s, updated_at=NOW()
        WHERE group_id=%s AND telegram_id=%s
    """, (new_total, new_carry, new_prize, _group_id, telegram_id))
    conn.commit()

    unpaid_numbers = []

    if new_carry < 0:
        cur.execute("SELECT price_full, price_half FROM game_settings WHERE id=%s", (game_id,))
        price_row = cur.fetchone()
        price_full = float(price_row[0] or 0)
        price_half = float(price_row[1] or 0)

        cur.execute("""
            SELECT id, number, is_half, slot
            FROM registrations
            WHERE game_id = %s AND user_id = %s AND is_paid = TRUE AND is_nekay = FALSE
            ORDER BY
                CASE WHEN is_half THEN %s ELSE %s END ASC,
                registered_at DESC
        """, (game_id, telegram_id, price_half, price_full))
        paid_regs = cur.fetchall()

        remaining_debt = abs(new_carry)
        for reg_id, number, is_half, slot in paid_regs:
            if remaining_debt <= 0:
                break
            cost = price_half if is_half else price_full
            cur.execute("UPDATE registrations SET is_paid=FALSE, is_nekay=FALSE WHERE id=%s", (reg_id,))
            remaining_debt -= cost
            new_carry += cost
            unpaid_numbers.append(number)

        new_total = new_carry + new_prize
        cur.execute("""
            UPDATE user_balance
            SET balance=%s, carry_balance=%s, prize_balance=%s, updated_at=NOW()
            WHERE group_id=%s AND telegram_id=%s
        """, (new_total, new_carry, new_prize, _group_id, telegram_id))
        conn.commit()

    cur.close()
    conn.close()
    return {"new_balance": new_total, "nekay_numbers": unpaid_numbers}


# ============================================================
# CLEAR PRIZE BALANCE ON NEW GAME
# ============================================================

def clear_prize_balance(group_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE user_balance
        SET prize_balance=0,
            balance=carry_balance,
            updated_at=NOW()
        WHERE group_id=%s AND winner_carried=TRUE
    """, (group_id,))
    cur.execute("""
        UPDATE user_balance
        SET winner_carried=TRUE,
            updated_at=NOW()
        WHERE group_id=%s AND winner_carried=FALSE AND prize_balance > 0
    """, (group_id,))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# ADMIN — CLEAR, REMOVE, PAY
# ============================================================

def clear_game(game_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM registrations WHERE game_id=%s", (game_id,))
    conn.commit()
    cur.close()
    conn.close()


def admin_remove_player(game_id: int, number: int, slot: int = None):
    conn = get_conn()
    cur = conn.cursor()
    if slot is None:
        cur.execute("DELETE FROM registrations WHERE game_id=%s AND number=%s", (game_id, number))
    else:
        cur.execute("DELETE FROM registrations WHERE game_id=%s AND number=%s AND slot=%s", (game_id, number, slot))
    conn.commit()
    cur.close()
    conn.close()


def admin_mark_paid(game_id: int, number: int, slot: int, is_paid: bool = True):
    conn = get_conn()
    cur = conn.cursor()

    if not is_paid:
        cur.execute("""
            UPDATE registrations SET is_paid=%s
            WHERE game_id=%s AND number=%s AND slot=%s
        """, (is_paid, game_id, number, slot))
        conn.commit()
        cur.close()
        conn.close()
        return

    cur.execute("""
        SELECT r.user_id, r.is_half, r.is_paid,
               gs.price_full, gs.price_half, gs.group_id
        FROM registrations r
        JOIN game_settings gs ON gs.id = r.game_id
        WHERE r.game_id=%s AND r.number=%s AND r.slot=%s
    """, (game_id, number, slot))
    row = cur.fetchone()

    if not row:
        cur.close()
        conn.close()
        return

    user_id, is_half, already_paid, price_full, price_half, group_id = row
    price_full = float(price_full or 0)
    price_half = float(price_half or 0)

    cur.execute("""
        UPDATE registrations SET is_paid=TRUE, pending_upgrade=FALSE
        WHERE game_id=%s AND number=%s AND slot=%s
    """, (game_id, number, slot))

    if already_paid or not user_id or user_id == 0:
        conn.commit()
        cur.close()
        conn.close()
        return

    cost = price_half if is_half else price_full

    cur.execute("""
        SELECT carry_balance, prize_balance FROM user_balance
        WHERE group_id=%s AND telegram_id=%s
    """, (group_id, user_id))
    bal_row = cur.fetchone()
    if not bal_row:
        conn.commit()
        cur.close()
        conn.close()
        return

    carry_balance = float(bal_row[0])
    prize_balance = float(bal_row[1])
    total_balance = carry_balance + prize_balance

    if total_balance <= 0:
        conn.commit()
        cur.close()
        conn.close()
        return

    deduct = min(cost, total_balance)
    _deduct_balance(cur, group_id, user_id, deduct, prize_balance, carry_balance)

    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# TYPE CHANGE
# ============================================================

def change_number_type(game_id: int, user_id: int, number: int, target: str) -> dict:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, is_half, slot, is_paid, pending_upgrade
        FROM registrations
        WHERE game_id=%s AND user_id=%s AND number=%s
        ORDER BY slot
    """, (game_id, user_id, number))
    rows = cur.fetchall()

    if not rows:
        cur.close()
        conn.close()
        return {"status": "not_yours"}

    cur.execute("SELECT price_full, price_half, group_id FROM game_settings WHERE id=%s", (game_id,))
    price_row = cur.fetchone()
    price_full = float(price_row[0] or 0)
    price_half = float(price_row[1] or 0)
    group_id = price_row[2]

    cur.execute("""
        SELECT carry_balance, prize_balance FROM user_balance
        WHERE group_id=%s AND telegram_id=%s
    """, (group_id, user_id))
    bal_row = cur.fetchone()
    carry_balance = float(bal_row[0]) if bal_row else 0.0
    prize_balance = float(bal_row[1]) if bal_row else 0.0
    total_balance = carry_balance + prize_balance

    reg_id, is_half, slot, is_paid, is_pending = rows[0]

    if target == "half" and not is_half:
        if len(rows) > 1:
            cur.close()
            conn.close()
            return {"status": "conflict"}

        cur.execute("UPDATE registrations SET is_half=TRUE, pending_upgrade=FALSE WHERE id=%s", (reg_id,))

        if is_paid and not is_pending:
            refund = price_full - price_half
            if refund > 0:
                new_carry = carry_balance + refund
                new_prize = prize_balance
                new_total = new_carry + new_prize

                cur.execute("""
                    UPDATE user_balance
                    SET carry_balance=%s, balance=%s, updated_at=NOW()
                    WHERE group_id=%s AND telegram_id=%s
                """, (new_carry, new_total, group_id, user_id))

                cur.execute("""
                    SELECT id, number, is_half, slot
                    FROM registrations
                    WHERE game_id=%s AND user_id=%s AND is_paid=FALSE AND number != %s
                    ORDER BY registered_at, slot
                """, (game_id, user_id, number))
                unpaid_own = cur.fetchall()

                remaining_carry = new_carry
                remaining_prize = new_prize
                for reg_id2, reg_num, reg_is_half, reg_slot in unpaid_own:
                    cost2 = price_half if reg_is_half else price_full
                    if remaining_carry + remaining_prize >= cost2:
                        cur.execute("UPDATE registrations SET is_paid=TRUE WHERE id=%s", (reg_id2,))
                        if remaining_prize >= cost2:
                            remaining_prize -= cost2
                        else:
                            diff = cost2 - remaining_prize
                            remaining_prize = 0
                            remaining_carry -= diff

                new_total2 = remaining_carry + remaining_prize
                cur.execute("""
                    UPDATE user_balance
                    SET carry_balance=%s, prize_balance=%s, balance=%s, updated_at=NOW()
                    WHERE group_id=%s AND telegram_id=%s
                """, (remaining_carry, remaining_prize, new_total2, group_id, user_id))

        elif not is_paid:
            if total_balance >= price_half:
                cur.execute("UPDATE registrations SET is_paid=TRUE WHERE id=%s", (reg_id,))
                _deduct_balance(cur, group_id, user_id, price_half, prize_balance, carry_balance)
                is_paid = True

        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok", "refund": 0, "charge": 0, "is_paid": is_paid}

    if target == "full" and is_half:
        charge = price_full - price_half
        if total_balance >= charge:
            cur.execute("""
                UPDATE registrations SET is_half=FALSE, is_paid=TRUE, is_nekay=FALSE, pending_upgrade=FALSE
                WHERE id=%s
            """, (reg_id,))
            _deduct_balance(cur, group_id, user_id, charge, prize_balance, carry_balance)

            cur.execute("""
                SELECT carry_balance, prize_balance FROM user_balance
                WHERE group_id=%s AND telegram_id=%s
            """, (group_id, user_id))
            updated_bal = cur.fetchone()
            if updated_bal:
                rem_carry = float(updated_bal[0])
                rem_prize = float(updated_bal[1])

                cur.execute("""
                    SELECT id, number, is_half, slot
                    FROM registrations
                    WHERE game_id=%s AND user_id=%s AND is_paid=FALSE AND number != %s
                    ORDER BY registered_at, slot
                """, (game_id, user_id, number))
                unpaid_own = cur.fetchall()

                for reg_id2, reg_num, reg_is_half, reg_slot in unpaid_own:
                    cost2 = price_half if reg_is_half else price_full
                    if rem_carry + rem_prize >= cost2:
                        cur.execute("UPDATE registrations SET is_paid=TRUE WHERE id=%s", (reg_id2,))
                        if rem_prize >= cost2:
                            rem_prize -= cost2
                        else:
                            diff = cost2 - rem_prize
                            rem_prize = 0
                            rem_carry -= diff

                new_total2 = rem_carry + rem_prize
                cur.execute("""
                    UPDATE user_balance
                    SET carry_balance=%s, prize_balance=%s, balance=%s, updated_at=NOW()
                    WHERE group_id=%s AND telegram_id=%s
                """, (rem_carry, rem_prize, new_total2, group_id, user_id))

            conn.commit()
            cur.close()
            conn.close()
            return {"status": "ok", "refund": 0, "charge": charge, "is_paid": True}

        else:
            if is_paid:
                # ሁኔታ 2 — paid half, balance ከሌለ → pending_upgrade
                cur.execute("""
                    UPDATE registrations
                    SET is_half=FALSE, is_nekay=FALSE, pending_upgrade=TRUE
                    WHERE id=%s
                """, (reg_id,))
                conn.commit()
                cur.close()
                conn.close()
                return {"status": "ok", "refund": 0, "charge": charge, "is_paid": True, "pending_upgrade": True}
            else:
                # ሁኔታ 1 — unpaid half, balance ከሌለ → ምንም ምልክት የለም
                cur.execute("""
                    UPDATE registrations
                    SET is_half=FALSE, is_nekay=FALSE, pending_upgrade=FALSE
                    WHERE id=%s
                """, (reg_id,))
                conn.commit()
                cur.close()
                conn.close()
                return {"status": "ok", "refund": 0, "charge": charge, "is_paid": False, "pending_upgrade": False}

    cur.close()
    conn.close()
    return {"status": "no_change", "refund": 0, "charge": 0, "is_paid": is_paid}
# ============================================================
# FAILED ATTEMPTS
# ============================================================

def save_failed_attempt(game_id: int, user_id: int, number: int, reason: str, taken: dict = None):
    conn = get_conn()
    cur = conn.cursor()
    slot1_name = slot2_name = slot1_type = slot2_type = None
    if reason == "taken" and taken:
        entry = taken.get(number, [])
        for name, is_half, slot in entry:
            if slot == 1:
                slot1_name = name
                slot1_type = "half" if is_half else "full"
            elif slot == 2:
                slot2_name = name
                slot2_type = "half"
    cur.execute("""
        INSERT INTO failed_attempts
        (game_id, user_id, number, reason, taken_by_slot1, taken_by_slot2, taken_type_slot1, taken_type_slot2)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (game_id, user_id, number, reason, slot1_name, slot2_name, slot1_type, slot2_type))
    conn.commit()
    cur.close()
    conn.close()


def get_failed_attempts(game_id: int, user_id: int, number: int = None) -> list:
    conn = get_conn()
    cur = conn.cursor()
    if number:
        cur.execute("""
            SELECT number, reason, taken_by_slot1, taken_by_slot2,
                   taken_type_slot1, taken_type_slot2, attempted_at
            FROM failed_attempts
            WHERE game_id=%s AND user_id=%s AND number=%s
            ORDER BY attempted_at DESC LIMIT 1
        """, (game_id, user_id, number))
    else:
        cur.execute("""
            SELECT DISTINCT ON (number) number, reason, taken_by_slot1, taken_by_slot2,
                   taken_type_slot1, taken_type_slot2, attempted_at
            FROM failed_attempts
            WHERE game_id=%s AND user_id=%s
            ORDER BY number, attempted_at DESC
        """, (game_id, user_id))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"number": r[0], "reason": r[1], "slot1_name": r[2], "slot2_name": r[3],
             "slot1_type": r[4], "slot2_type": r[5], "attempted_at": r[6]} for r in rows]


# ============================================================
# PAYMENT MATCHING
# ============================================================

AMOUNT_TOLERANCE = 20


def _normalize_name(name: str) -> set:
    if not name:
        return set()
    cleaned = re.sub(r"[^a-zA-Z\u1200-\u137F\s]", "", name.lower())
    return set(w for w in cleaned.split() if len(w) > 1)


def _names_match(name1: str, name2: str) -> bool:
    n1, n2 = _normalize_name(name1), _normalize_name(name2)
    if not n1 or not n2:
        return False
    if n1 & n2:
        return True
    for w1 in n1:
        for w2 in n2:
            if len(w1) > 3 and len(w2) > 3:
                shorter = min(len(w1), len(w2))
                longer = max(len(w1), len(w2))
                if shorter / longer >= 0.8 and w1[:3] == w2[:3]:
                    return True
    return False


def save_sms_payment(amount, sender_name: str, ref: str, sms_type: str, raw_sms: str, group_id: int = None) -> dict:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO sms_payments (group_id, ref_no, amount, sender_name, pay_type, raw_sms, matched)
        VALUES (%s, %s, %s, %s, %s, %s, FALSE)
        RETURNING id
    """, (group_id, ref, amount, sender_name, sms_type, raw_sms))
    sms_id = cur.fetchone()[0]
    conn.commit()

    if group_id:
        cur.execute("""
            SELECT id, telegram_id, ref_no, amount, sender_name
            FROM screenshot_payments
            WHERE matched=FALSE AND group_id=%s
              AND amount BETWEEN %s AND %s
            ORDER BY created_at ASC
        """, (group_id, float(amount) - AMOUNT_TOLERANCE, float(amount) + AMOUNT_TOLERANCE))
    else:
        cur.execute("""
            SELECT id, telegram_id, ref_no, amount, sender_name
            FROM screenshot_payments
            WHERE matched=FALSE
              AND amount BETWEEN %s AND %s
            ORDER BY created_at ASC
        """, (float(amount) - AMOUNT_TOLERANCE, float(amount) + AMOUNT_TOLERANCE))
    candidates = cur.fetchall()

    chosen = None
    if ref:
        for scr_id, telegram_id, scr_ref, scr_amount, scr_sender in candidates:
            if scr_ref and scr_ref == ref:
                chosen = (scr_id, telegram_id, scr_sender)
                break
    if not chosen and sender_name:
        for scr_id, telegram_id, scr_ref, scr_amount, scr_sender in candidates:
            if _names_match(sender_name, scr_sender):
                chosen = (scr_id, telegram_id, scr_sender)
                break
    if not chosen and len(candidates) == 1:
        scr_id, telegram_id, scr_ref, scr_amount, scr_sender = candidates[0]
        chosen = (scr_id, telegram_id, scr_sender)

    matched_data = None
    if chosen:
        scr_id, telegram_id, scr_sender = chosen
        cur.execute("UPDATE sms_payments SET matched=TRUE WHERE id=%s", (sms_id,))
        cur.execute("UPDATE screenshot_payments SET matched=TRUE WHERE id=%s", (scr_id,))
        conn.commit()
        matched_data = {
            "telegram_id": telegram_id,
            "amount": float(amount),
            "type": sms_type,
            "sender_name": sender_name or scr_sender,
            "group_id": group_id,
        }

    cur.close()
    conn.close()
    return {"matched": matched_data}


def find_matching_sms(telegram_id: int, amount, sender_name: str, ref: str, pay_type: str, group_id: int = None):
    conn = get_conn()
    cur = conn.cursor()
    if group_id:
        cur.execute("""
            SELECT id, ref_no, amount, sender_name, pay_type
            FROM sms_payments
            WHERE matched=FALSE AND group_id=%s
              AND amount BETWEEN %s AND %s
            ORDER BY created_at ASC
        """, (group_id, float(amount) - AMOUNT_TOLERANCE, float(amount) + AMOUNT_TOLERANCE))
    else:
        cur.execute("""
            SELECT id, ref_no, amount, sender_name, pay_type
            FROM sms_payments
            WHERE matched=FALSE
              AND amount BETWEEN %s AND %s
            ORDER BY created_at ASC
        """, (float(amount) - AMOUNT_TOLERANCE, float(amount) + AMOUNT_TOLERANCE))
    candidates = cur.fetchall()
    cur.close()
    conn.close()

    if not candidates:
        return None

    if ref:
        for sms_id, sms_ref, sms_amount, sms_sender, sms_type in candidates:
            if sms_ref and sms_ref == ref:
                return {"id": sms_id, "amount": float(sms_amount), "type": sms_type,
                        "sender_name": sender_name or sms_sender}

    if sender_name:
        for sms_id, sms_ref, sms_amount, sms_sender, sms_type in candidates:
            if _names_match(sender_name, sms_sender):
                return {"id": sms_id, "amount": float(sms_amount), "type": sms_type,
                        "sender_name": sender_name or sms_sender}

    if len(candidates) == 1:
        sms_id, sms_ref, sms_amount, sms_sender, sms_type = candidates[0]
        return {"id": sms_id, "amount": float(sms_amount), "type": sms_type,
                "sender_name": sender_name or sms_sender}

    return None


def mark_sms_as_used(sms_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE sms_payments SET matched=TRUE WHERE id=%s", (sms_id,))
    conn.commit()
    cur.close()
    conn.close()


def is_sms_already_used(sms_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT matched FROM sms_payments WHERE id=%s", (sms_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return bool(row and row[0])


def save_screenshot_payment(telegram_id: int, amount, sender_name: str,
                             ref: str, pay_type: str, description: str, group_id: int = None) -> dict:
    import uuid
    conn = get_conn()
    cur = conn.cursor()

    if group_id:
        cur.execute("""
            DELETE FROM screenshot_payments
            WHERE telegram_id=%s AND group_id=%s AND matched=FALSE
        """, (telegram_id, group_id))
    else:
        cur.execute("""
            DELETE FROM screenshot_payments
            WHERE telegram_id=%s AND matched=FALSE
        """, (telegram_id,))

    safe_ref = ref if (pay_type == "Telebirr" and ref) else str(uuid.uuid4())

    cur.execute("""
        INSERT INTO screenshot_payments
        (group_id, telegram_id, ref_no, amount, sender_name, pay_type, description, matched)
        VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
    """, (group_id, telegram_id, safe_ref, amount, sender_name, pay_type, description))

    conn.commit()
    cur.close()
    conn.close()
    return {"matched": None}


def get_sms_payment_by_ref(ref_no: str):
    if not ref_no:
        return None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, ref_no, amount, sender_name, pay_type
        FROM sms_payments WHERE ref_no = %s
    """, (ref_no,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "refNo": row[1],
        "amount": float(row[2]) if row[2] is not None else None,
        "sender_name": row[3], "type": row[4],
    }


def is_ref_matched_already(ref_no: str) -> bool:
    if not ref_no:
        return False
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM sms_payments WHERE ref_no = %s AND matched = TRUE
        UNION
        SELECT 1 FROM screenshot_payments WHERE ref_no = %s AND matched = TRUE
    """, (ref_no, ref_no))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row is not None


def cleanup_old_payments(days: int = 7):
    conn = get_conn()
    cur = conn.cursor()
    cutoff = datetime.now() - timedelta(days=days)
    cur.execute("DELETE FROM sms_payments WHERE matched = FALSE AND created_at < %s", (cutoff,))
    cur.execute("DELETE FROM screenshot_payments WHERE matched = FALSE AND created_at < %s", (cutoff,))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# USER NUMBERS
# ============================================================

def get_user_numbers(game_id: int, user_id: int) -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT number, is_half, slot, is_paid
        FROM registrations WHERE game_id=%s AND user_id=%s ORDER BY number, slot
    """, (game_id, user_id))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def user_owns_number(game_id: int, user_id: int, number: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM registrations WHERE game_id=%s AND user_id=%s AND number=%s LIMIT 1",
                (game_id, user_id, number))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row is not None


def remove_number(game_id: int, user_id: int, number: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, is_half, slot, is_paid, pending_upgrade FROM registrations
        WHERE game_id=%s AND user_id=%s AND number=%s ORDER BY slot
    """, (game_id, user_id, number))
    rows = cur.fetchall()
    if not rows:
        cur.close()
        conn.close()
        return False
    cur.execute("SELECT price_full, price_half, group_id FROM game_settings WHERE id=%s", (game_id,))
    price_row = cur.fetchone()
    price_full = float(price_row[0] or 0)
    price_half = float(price_row[1] or 0)
    group_id = price_row[2]

    refund = 0
    for r in rows:
        reg_id, r_is_half, r_slot, r_is_paid, r_pending = r
        if r_is_paid:
            if r_pending:
                refund += price_half
            elif r_is_half:
                refund += price_half
            else:
                refund += price_full

    cur.execute("DELETE FROM registrations WHERE game_id=%s AND user_id=%s AND number=%s", (game_id, user_id, number))

    if refund > 0:
        cur.execute("""
            SELECT carry_balance, prize_balance FROM user_balance
            WHERE group_id=%s AND telegram_id=%s
        """, (group_id, user_id))
        bal_row = cur.fetchone()
        carry_balance = float(bal_row[0]) if bal_row else 0.0
        prize_balance = float(bal_row[1]) if bal_row else 0.0

        new_carry = carry_balance + refund
        new_total = new_carry + prize_balance

        cur.execute("""
            INSERT INTO user_balance (group_id, telegram_id, balance, carry_balance, prize_balance)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (group_id, telegram_id)
            DO UPDATE SET carry_balance=%s, balance=%s, updated_at=NOW()
        """, (group_id, user_id, new_total, new_carry, prize_balance, new_carry, new_total))

        # FIX 2b — pending_upgrade=TRUE ያላቸውን ጨምሮ ሁሉንም unpaid ይከፍላል
        cur.execute("""
            SELECT id, number, is_half, slot, pending_upgrade
            FROM registrations
            WHERE game_id=%s AND user_id=%s AND (is_paid=FALSE OR pending_upgrade=TRUE)
            ORDER BY registered_at, slot
        """, (game_id, user_id))
        unpaid = cur.fetchall()

        remaining_carry = new_carry
        remaining_prize = prize_balance
        for reg_id, reg_number, reg_is_half, reg_slot, reg_pending in unpaid:
            cost = price_half if (reg_is_half or reg_pending) else price_full
            total_remaining = remaining_carry + remaining_prize
            if total_remaining >= cost:
                cur.execute("""
                    UPDATE registrations SET is_paid=TRUE, pending_upgrade=FALSE
                    WHERE id=%s
                """, (reg_id,))
                if remaining_prize >= cost:
                    remaining_prize -= cost
                else:
                    diff = cost - remaining_prize
                    remaining_prize = 0
                    remaining_carry -= diff

        new_total = remaining_carry + remaining_prize
        cur.execute("""
            UPDATE user_balance
            SET balance=%s, carry_balance=%s, prize_balance=%s, updated_at=NOW()
            WHERE group_id=%s AND telegram_id=%s
        """, (new_total, remaining_carry, remaining_prize, group_id, user_id))

    conn.commit()
    cur.close()
    conn.close()
    return True


# ============================================================
# WINNER GREETING
# ============================================================

def get_ungreeted_winner(game_id: int, telegram_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM winners
        WHERE telegram_id=%s AND place=1 AND greeted=FALSE AND game_id != %s
        ORDER BY game_id DESC LIMIT 1
    """, (telegram_id, game_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row is not None


def mark_winner_greeted(telegram_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE winners SET greeted=TRUE WHERE telegram_id=%s AND place=1 AND greeted=FALSE", (telegram_id,))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# BALANCE CLEAR
# ============================================================

def clear_balance_all(group_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE user_balance SET balance=0, carry_balance=0, prize_balance=0, updated_at=NOW()
        WHERE group_id=%s
    """, (group_id,))
    conn.commit()
    cur.close()
    conn.close()


def clear_balance_by_username(group_id: int, username: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT gm.username, r.user_id
        FROM group_members gm
        JOIN registrations r ON r.user_name = gm.username
        JOIN game_settings gs ON gs.id = r.game_id
        WHERE gm.group_id=%s AND LOWER(gm.username)=LOWER(%s)
        LIMIT 1
    """, (group_id, username.lstrip("@")))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return False
    user_id = row[1]
    cur.execute("""
        UPDATE user_balance SET balance=0, carry_balance=0, prize_balance=0, updated_at=NOW()
        WHERE telegram_id=%s AND group_id=%s
    """, (user_id, group_id))
    conn.commit()
    cur.close()
    conn.close()
    return True


# ============================================================
# GROUP ON/OFF
# ============================================================

def set_group_active(group_id: int, is_active: bool):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE groups SET is_active=%s WHERE group_id=%s", (is_active, group_id))
    if cur.rowcount == 0:
        cur.execute("""
            INSERT INTO groups (group_id, is_enabled, is_active)
            VALUES (%s, TRUE, %s)
            ON CONFLICT (group_id) DO UPDATE SET is_active=EXCLUDED.is_active
        """, (group_id, is_active))
    conn.commit()
    cur.close()
    conn.close()


def is_group_active(group_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT is_active FROM groups WHERE group_id=%s", (group_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row is None:
        return False
    return bool(row[0]) if row[0] is not None else True


# ============================================================
# REPORT
# ============================================================

def save_game_report(group_id: int, game_id: int, total_bet: float,
                     prize_total: float, profit: float, registered_count: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS game_reports (
            id SERIAL PRIMARY KEY,
            group_id BIGINT NOT NULL,
            game_id INT,
            total_bet NUMERIC DEFAULT 0,
            prize_total NUMERIC DEFAULT 0,
            profit NUMERIC DEFAULT 0,
            registered_count INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        INSERT INTO game_reports
        (group_id, game_id, total_bet, prize_total, profit, registered_count)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (group_id, game_id, total_bet, prize_total, profit, registered_count))
    conn.commit()
    cur.close()
    conn.close()


def get_report(group_id: int) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=24)

    try:
        cur.execute("""
            SELECT COUNT(*), COALESCE(SUM(total_bet),0),
                   COALESCE(SUM(prize_total),0), COALESCE(SUM(profit),0),
                   COALESCE(SUM(registered_count),0)
            FROM game_reports
            WHERE group_id=%s AND created_at >= %s
        """, (group_id, cutoff))
        row = cur.fetchone()
        games_count = int(row[0] or 0)
        total_bet = float(row[1] or 0)
        prize_total = float(row[2] or 0)
        profit = float(row[3] or 0)
        registered_count = int(row[4] or 0)
    except Exception:
        games_count = total_bet = prize_total = profit = registered_count = 0

    cur.execute("""
        SELECT gs.id, gs.price_full, gs.price_half,
               gs.prize_1st, gs.prize_2nd, gs.prize_3rd,
               gs.numbers_per_person, gs.total_numbers
        FROM game_settings gs
        WHERE gs.group_id=%s AND gs.is_active=TRUE
        ORDER BY gs.id DESC LIMIT 1
    """, (group_id,))
    active = cur.fetchone()

    active_data = None
    if active:
        (game_id, price_full, price_half,
         prize_1st, prize_2nd, prize_3rd,
         per_person, total_numbers) = active

        price_full = float(price_full or 0)
        prize_total = float((prize_1st or 0) + (prize_2nd or 0) + (prize_3rd or 0))

        cur.execute("""
            SELECT COUNT(DISTINCT number) FROM registrations WHERE game_id=%s
        """, (game_id,))
        filled_groups = cur.fetchone()[0] or 0

        cur.execute("SELECT COUNT(*) FROM registrations WHERE game_id=%s", (game_id,))
        total_slots = cur.fetchone()[0] or 0

        total_bet = filled_groups * price_full
        active_profit = total_bet - prize_total if total_slots >= 15 else 0

        active_data = {
            "game_id": game_id,
            "total_slots": total_slots,
            "filled_groups": filled_groups,
            "total_bet": total_bet,
            "prize_total": prize_total,
            "profit": active_profit,
            "counted": total_slots >= 15,
        }

    cur.close()
    conn.close()

    return {
        "games_count": games_count,
        "total_bet": total_bet,
        "prize_total": prize_total,
        "profit": profit,
        "registered_count": registered_count,
        "active": active_data,
    }


def cleanup_old_reports():
    conn = get_conn()
    cur = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=24)
    try:
        cur.execute("DELETE FROM game_reports WHERE created_at < %s", (cutoff,))
        conn.commit()
    except Exception:
        pass
    cur.close()
    conn.close()


def calculate_game_profit(game_id: int) -> dict:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT price_full, price_half, prize_1st, prize_2nd, prize_3rd,
               numbers_per_person, total_numbers, group_id
        FROM game_settings WHERE id=%s
    """, (game_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return {}

    price_full, price_half, prize_1st, prize_2nd, prize_3rd, \
        per_person, total_numbers, group_id = row

    price_full = float(price_full or 0)
    prize_total = float((prize_1st or 0) + (prize_2nd or 0) + (prize_3rd or 0))

    cur.execute("""
        SELECT COUNT(DISTINCT number) FROM registrations WHERE game_id=%s
    """, (game_id,))
    filled_groups = cur.fetchone()[0] or 0

    cur.execute("SELECT COUNT(*) FROM registrations WHERE game_id=%s", (game_id,))
    registered_count = cur.fetchone()[0] or 0

    total_bet = filled_groups * price_full
    profit = total_bet - prize_total

    cur.close()
    conn.close()

    return {
        "game_id": game_id,
        "group_id": group_id,
        "filled_groups": filled_groups,
        "total_bet": total_bet,
        "prize_total": prize_total,
        "profit": profit,
        "registered_count": registered_count,
        "counted": registered_count >= 15,
    }
