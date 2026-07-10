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
            game_id INT,
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
            game_id INT,
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
            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'winners_game_id_place_key'
                    ) THEN
                        ALTER TABLE winners DROP CONSTRAINT winners_game_id_place_key;
                    END IF;
                END
                $$;
            """)
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'winners_game_id_place_telegram_id_key'
                    ) THEN
                        ALTER TABLE winners ADD CONSTRAINT winners_game_id_place_telegram_id_key
                        UNIQUE (game_id, place, telegram_id);
                    END IF;
                END
                $$;
            """)
            cur.execute("ALTER TABLE winners ADD COLUMN IF NOT EXISTS sent BOOLEAN DEFAULT FALSE;")
            cur.execute("ALTER TABLE winners ADD COLUMN IF NOT EXISTS group_id BIGINT;")
            cur.execute("ALTER TABLE winners ADD COLUMN IF NOT EXISTS sent_amount NUMERIC DEFAULT 0;")
            cur.execute("ALTER TABLE game_settings ADD COLUMN IF NOT EXISTS group_id BIGINT;")
            cur.execute("ALTER TABLE game_settings ADD COLUMN IF NOT EXISTS countdown_enabled BOOLEAN DEFAULT TRUE;")
            cur.execute("ALTER TABLE game_settings ADD COLUMN IF NOT EXISTS countdown_minutes NUMERIC DEFAULT 2;")
            cur.execute("ALTER TABLE game_settings ADD COLUMN IF NOT EXISTS game_rule TEXT;")
            cur.execute("ALTER TABLE game_settings ADD COLUMN IF NOT EXISTS slot_symbol TEXT DEFAULT '#';")
            cur.execute("ALTER TABLE game_settings ADD COLUMN IF NOT EXISTS show_all_slots BOOLEAN DEFAULT FALSE;")
            cur.execute("ALTER TABLE game_settings ADD COLUMN IF NOT EXISTS pre_wipe_snapshot JSONB;")
            cur.execute("ALTER TABLE game_settings ADD COLUMN IF NOT EXISTS profit_per_game NUMERIC DEFAULT 0;")
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
            cur.execute("ALTER TABLE sms_payments ADD COLUMN IF NOT EXISTS game_id INT;")
            cur.execute("ALTER TABLE screenshot_payments ADD COLUMN IF NOT EXISTS game_id INT;")
            cur.execute("ALTER TABLE screenshot_payments ADD COLUMN IF NOT EXISTS amount NUMERIC;")
            cur.execute("ALTER TABLE screenshot_payments ADD COLUMN IF NOT EXISTS sender_name TEXT;")

            # ✅ Fingerprint feature — SMS ላይ phone/account last-4 digit መያዝ
            cur.execute("ALTER TABLE sms_payments ADD COLUMN IF NOT EXISTS phone_last4 TEXT;")
            cur.execute("ALTER TABLE sms_payments ADD COLUMN IF NOT EXISTS account_last4 TEXT;")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_payment_fingerprints (
                    id SERIAL PRIMARY KEY,
                    group_id BIGINT NOT NULL,
                    telegram_id BIGINT NOT NULL,
                    full_name TEXT,
                    phone_last4 TEXT,
                    account_last4 TEXT,
                    pay_type TEXT,
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(group_id, telegram_id, pay_type)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS payment_claims (
                    id SERIAL PRIMARY KEY,
                    group_id BIGINT NOT NULL,
                    game_id INT,
                    telegram_id BIGINT NOT NULL,
                    claim_chat_id BIGINT,
                    claim_message_id BIGINT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)

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
                CREATE TABLE IF NOT EXISTS winner_photos (
                    id SERIAL PRIMARY KEY,
                    photo_unique_id TEXT NOT NULL UNIQUE,
                    group_id BIGINT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS complete_stickers (
                    id SERIAL PRIMARY KEY,
                    file_id TEXT NOT NULL,
                    added_at TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS jina_embeddings (
                    id SERIAL PRIMARY KEY,
                    intent TEXT NOT NULL,
                    example_index INTEGER NOT NULL,
                    embedding JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(intent, example_index)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS jina_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)

            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            import logging
            logging.warning(f"[init_db] DB {i} error: {e}")


# ============================================================
# WINNER PHOTO DEDUP
# ============================================================

def is_winner_photo_used(photo_unique_id: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM winner_photos WHERE photo_unique_id=%s", (photo_unique_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row is not None


def save_winner_photo(photo_unique_id: str, group_id: int = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO winner_photos (photo_unique_id, group_id)
        VALUES (%s, %s)
        ON CONFLICT (photo_unique_id) DO NOTHING
    """, (photo_unique_id, group_id))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# ADMIN — NAME OVERRIDE (reply-to-user "#name <name>")
# ============================================================
# Admin ተጠቃሚ መልእክት reply አድርጎ "#name <ስም>" ቢልክ፣ ያ ተጠቃሚ ከዚያ በኋላ
# ቁጥር በሚይዝበት ጊዜ ሁሉ (parsed_name/telegram username ምንም ይሁኑ) override
# ስሙ ብቻ ጥቅም ላይ ይውላል። "#name" ብቻ (ስም ሳይከተል) ከላከ override ይጠፋል እና
# ወደ ነባሩ ስም-መለያ logic ይመለሳል (parsed_name ራሱ አይነካም)።

def set_name_override(group_id: int, telegram_id: int, name: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS name_overrides (
            id SERIAL PRIMARY KEY,
            group_id BIGINT NOT NULL,
            telegram_id BIGINT NOT NULL,
            override_name TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(group_id, telegram_id)
        )
    """)
    cur.execute("""
        INSERT INTO name_overrides (group_id, telegram_id, override_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (group_id, telegram_id) DO UPDATE
            SET override_name=EXCLUDED.override_name, updated_at=NOW()
    """, (group_id, telegram_id, name))
    conn.commit()
    cur.close()
    conn.close()


def get_name_override(group_id: int, telegram_id: int):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT override_name FROM name_overrides
            WHERE group_id=%s AND telegram_id=%s
        """, (group_id, telegram_id))
        row = cur.fetchone()
    except Exception:
        row = None
    cur.close()
    conn.close()
    return row[0] if row else None


def clear_name_override(group_id: int, telegram_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS name_overrides (
            id SERIAL PRIMARY KEY,
            group_id BIGINT NOT NULL,
            telegram_id BIGINT NOT NULL,
            override_name TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(group_id, telegram_id)
        )
    """)
    cur.execute("DELETE FROM name_overrides WHERE group_id=%s AND telegram_id=%s", (group_id, telegram_id))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# USER PAYMENT FINGERPRINTS — "ልኬያለው" (text-only payment claims)
# ራስ-ሰር ለማዛመድ የሚያገለግል fingerprint (phone/account last-4 + ስም)።
# አንድ user ቀድሞ screenshot/SMS/##-admin-paste በኩል ተመዝግቦ ከሆነ፣ ቀጣይ ጊዜ
# "ልኬያለው"/"done"/"✅" ብቻ ቢል በዚህ fingerprint ራስ-ሰር ይዛመዳል።
# ============================================================

def _ensure_fingerprint_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_payment_fingerprints (
            id SERIAL PRIMARY KEY,
            group_id BIGINT NOT NULL,
            telegram_id BIGINT NOT NULL,
            full_name TEXT,
            phone_last4 TEXT,
            account_last4 TEXT,
            pay_type TEXT,
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(group_id, telegram_id, pay_type)
        )
    """)


def save_user_fingerprint(group_id: int, telegram_id: int, full_name: str = None,
                           phone_last4: str = None, account_last4: str = None,
                           pay_type: str = None):
    """
    ክፍያ በተሳካ ሁኔታ ሲረጋገጥ (notify_match/admin-##-paste በኩል) ይጠራል።
    telegram_id ቀድሞ fingerprint ካለው (ተመሳሳይ pay_type) ይዘምናል፣ ካልሆነ
    አዲስ ይፈጠራል። ባዶ/None fields ነባሩን አይደመስሱም (COALESCE)።
    """
    if not group_id or not telegram_id:
        return
    conn = get_conn()
    cur = conn.cursor()
    _ensure_fingerprint_table(cur)
    cur.execute("""
        INSERT INTO user_payment_fingerprints
            (group_id, telegram_id, full_name, phone_last4, account_last4, pay_type)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (group_id, telegram_id, pay_type) DO UPDATE
            SET full_name=COALESCE(EXCLUDED.full_name, user_payment_fingerprints.full_name),
                phone_last4=COALESCE(EXCLUDED.phone_last4, user_payment_fingerprints.phone_last4),
                account_last4=COALESCE(EXCLUDED.account_last4, user_payment_fingerprints.account_last4),
                updated_at=NOW()
    """, (group_id, telegram_id, full_name, phone_last4, account_last4, pay_type or ""))
    conn.commit()
    cur.close()
    conn.close()


def delete_user_fingerprint(group_id: int, telegram_id: int):
    """##cancel — admin የተሳሳተ fingerprint ካስቀመጠ ያ user's fingerprint(s) ሁሉ ይጠፋሉ።"""
    conn = get_conn()
    cur = conn.cursor()
    _ensure_fingerprint_table(cur)
    cur.execute("""
        DELETE FROM user_payment_fingerprints WHERE group_id=%s AND telegram_id=%s
    """, (group_id, telegram_id))
    conn.commit()
    cur.close()
    conn.close()


def _get_group_fingerprints(cur, group_id: int) -> list:
    cur.execute("""
        SELECT telegram_id, full_name, phone_last4, account_last4, pay_type
        FROM user_payment_fingerprints WHERE group_id=%s
    """, (group_id,))
    return cur.fetchall()


def find_user_by_fingerprint(group_id: int, sender_name: str = None,
                              phone_last4: str = None, account_last4: str = None) -> int:
    """
    SMS ላይ ካለው ስም እና last4 (phone ወይም account) ጋር **ሁለቱም** የሚመሳሰል
    fingerprint ካለው ብቻ ያ telegram_id ይመልሳል፣ አንዱ ብቻ (ስም ብቻ ወይም last4
    ብቻ) በቂ አይደለም — ደህንነት ለማጠናከር። ካልተገኘ None ይመልሳል።
    """
    if not group_id:
        return None
    if not sender_name or not (phone_last4 or account_last4):
        return None
    conn = get_conn()
    cur = conn.cursor()
    _ensure_fingerprint_table(cur)
    rows = _get_group_fingerprints(cur, group_id)
    cur.close()
    conn.close()

    if not rows:
        return None

    for telegram_id, full_name, fp_phone, fp_account, pay_type in rows:
        if not full_name or not _names_match(sender_name, full_name):
            continue
        last4_ok = (
            (phone_last4 and fp_phone and phone_last4 == fp_phone) or
            (account_last4 and fp_account and account_last4 == fp_account)
        )
        if last4_ok:
            return telegram_id

    return None


def find_unmatched_sms_for_user(group_id: int, sender_name: str = None,
                                 phone_last4: str = None, account_last4: str = None,
                                 game_id: int = None):
    """
    payment_claim ("ልኬያለው") ሲመጣ፣ ይህ user's fingerprint ጋር የሚመሳሰል
    unmatched sms_payments row ካለ ይመልሳል (dict) እና ያንን SMS record
    ወዲያውኑ ያጠፋል (duplicate/re-match እንዳይፈጠር) — ልክ እንደ find_matching_sms
    ስልት። ካልተገኘ None ይመልሳል።
    """
    if not group_id:
        return None
    conn = get_conn()
    cur = conn.cursor()

    if game_id is not None:
        cur.execute("""
            SELECT id, ref_no, amount, sender_name, pay_type, phone_last4, account_last4
            FROM sms_payments
            WHERE matched=FALSE AND group_id=%s AND (game_id=%s OR game_id IS NULL)
            ORDER BY created_at ASC
        """, (group_id, game_id))
    else:
        cur.execute("""
            SELECT id, ref_no, amount, sender_name, pay_type, phone_last4, account_last4
            FROM sms_payments
            WHERE matched=FALSE AND group_id=%s AND game_id IS NULL
            ORDER BY created_at ASC
        """, (group_id,))
    candidates = cur.fetchall()

    if not candidates:
        cur.close()
        conn.close()
        return None

    # ✅ ደህንነት ማጠናከሪያ: last4 (phone ወይም account) እና ስም **ሁለቱም**
    # መመሳሰል አለባቸው — አንዱ ብቻ በቂ አይደለም
    chosen = None
    if sender_name and (phone_last4 or account_last4):
        for row in candidates:
            sms_id, ref, amount, sms_sender, sms_type, sms_phone, sms_account = row
            if not sms_sender or not _names_match(sender_name, sms_sender):
                continue
            last4_ok = (
                (phone_last4 and sms_phone and phone_last4 == sms_phone) or
                (account_last4 and sms_account and account_last4 == sms_account)
            )
            if last4_ok:
                chosen = row
                break

    if not chosen:
        cur.close()
        conn.close()
        return None

    sms_id, ref, amount, sms_sender, sms_type, sms_phone, sms_account = chosen
    cur.execute("DELETE FROM sms_payments WHERE id=%s", (sms_id,))
    conn.commit()
    cur.close()
    conn.close()

    return {
        "id": sms_id,
        "amount": float(amount),
        "type": sms_type,
        "sender_name": sms_sender,
    }


# ============================================================
# PENDING PAYMENT CLAIMS — user "ልኬያለው" ብሎ ጽሁፍ ብቻ ሲልክ ገና SMS
# ካልደረሰ (screenshot_payments style) pending ሆኖ ይቀመጣል፣ SMS ሲደርስ
# fingerprint via ራስ-ሰር ይዛመዳል፣ ኦርጅናል "ልኬያለው" message ላይ reply
# ተደርጎ amount ይነገራል።
# ============================================================

def _ensure_payment_claims_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payment_claims (
            id SERIAL PRIMARY KEY,
            group_id BIGINT NOT NULL,
            game_id INT,
            telegram_id BIGINT NOT NULL,
            claim_chat_id BIGINT,
            claim_message_id BIGINT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)


def save_payment_claim(group_id: int, telegram_id: int, claim_chat_id: int,
                        claim_message_id: int, game_id: int = None):
    """
    User "ልኬያለው" ብሎ ሲል SMS ገና ካልደረሰ ይህ ይጠራል። ቀድሞ pending claim ካለው
    ለዚህ ተጠቃሚ (አሮጌው) ይተካል — አንድ ጊዜ ብቻ አንድ pending claim ይኖራል
    (ልክ screenshot_payments እንደሚያደርገው)።
    """
    conn = get_conn()
    cur = conn.cursor()
    _ensure_payment_claims_table(cur)
    cur.execute("""
        DELETE FROM payment_claims WHERE group_id=%s AND telegram_id=%s
    """, (group_id, telegram_id))
    cur.execute("""
        INSERT INTO payment_claims (group_id, game_id, telegram_id, claim_chat_id, claim_message_id)
        VALUES (%s, %s, %s, %s, %s)
    """, (group_id, game_id, telegram_id, claim_chat_id, claim_message_id))
    conn.commit()
    cur.close()
    conn.close()


def delete_payment_claim(group_id: int, telegram_id: int):
    """ይህ user's pending payment claim (ካለ) ያጠፋል — ##paste ስኬታማ ከሆነ ወይም ##cancel ሲጠየቅ ይጠቅማል።"""
    conn = get_conn()
    cur = conn.cursor()
    _ensure_payment_claims_table(cur)
    cur.execute("""
        DELETE FROM payment_claims WHERE group_id=%s AND telegram_id=%s
    """, (group_id, telegram_id))
    conn.commit()
    cur.close()
    conn.close()


def delete_pending_screenshot_payment(group_id: int, telegram_id: int):
    """
    ✅ Stale-cleanup: user screenshot/URL ልኮ pending screenshot_payments
    ውስጥ ተቀምጦ ከነበረ፣ ግን ገንዘቡ በሌላ ዘዴ (ለምሳሌ "ልኬያለው" fingerprint via
    ወይም admin ##paste) ቀድሞ ከተረጋገጠ፣ ያ leftover unmatched screenshot
    record stale ሆኖ እንዳይቀር ያጠፋል።
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM screenshot_payments WHERE group_id=%s AND telegram_id=%s AND matched=FALSE
    """, (group_id, telegram_id))
    conn.commit()
    cur.close()
    conn.close()


def clear_payment_claims(group_id: int):
    """/newgame ወይም pre-booking wipe ላይ ሁሉንም pending claims ለዚህ group ያጸዳል።"""
    conn = get_conn()
    cur = conn.cursor()
    _ensure_payment_claims_table(cur)
    cur.execute("DELETE FROM payment_claims WHERE group_id=%s", (group_id,))
    conn.commit()
    cur.close()
    conn.close()


def find_payment_claim_by_fingerprint(group_id: int, sender_name: str = None,
                                       phone_last4: str = None, account_last4: str = None):
    """
    SMS ሲደርስ (handle_sms_webhook) ይህ ይጠራል። ያሉትን pending payment_claims
    ሁሉ ፈልጎ፣ እያንዳንዱ claim's telegram_id ያለውን fingerprint (ስም + last4
    ሁለቱም — ደህንነት ለማጠናከር) ካመሳሰለ ያንን claim ይመልሳል (dict) እና ወዲያውኑ
    ያጠፋዋል (duplicate re-match እንዳይፈጠር)። ካልተገኘ None ይመልሳል።
    """
    if not group_id or not sender_name or not (phone_last4 or account_last4):
        return None

    conn = get_conn()
    cur = conn.cursor()
    _ensure_payment_claims_table(cur)
    cur.execute("""
        SELECT id, telegram_id, claim_chat_id, claim_message_id
        FROM payment_claims WHERE group_id=%s ORDER BY created_at ASC
    """, (group_id,))
    claims = cur.fetchall()

    if not claims:
        cur.close()
        conn.close()
        return None

    _ensure_fingerprint_table(cur)
    fp_rows = _get_group_fingerprints(cur, group_id)
    fp_by_user = {}
    for telegram_id, full_name, fp_phone, fp_account, pay_type in fp_rows:
        fp_by_user.setdefault(telegram_id, []).append((full_name, fp_phone, fp_account))

    chosen = None
    for claim_id, telegram_id, claim_chat_id, claim_message_id in claims:
        for full_name, fp_phone, fp_account in fp_by_user.get(telegram_id, []):
            if not full_name or not _names_match(sender_name, full_name):
                continue
            last4_ok = (
                (phone_last4 and fp_phone and phone_last4 == fp_phone) or
                (account_last4 and fp_account and account_last4 == fp_account)
            )
            if last4_ok:
                chosen = (claim_id, telegram_id, claim_chat_id, claim_message_id)
                break
        if chosen:
            break

    if not chosen:
        cur.close()
        conn.close()
        return None

    claim_id, telegram_id, claim_chat_id, claim_message_id = chosen
    cur.execute("DELETE FROM payment_claims WHERE id=%s", (claim_id,))
    conn.commit()
    cur.close()
    conn.close()

    return {
        "telegram_id": telegram_id,
        "claim_chat_id": claim_chat_id,
        "claim_message_id": claim_message_id,
    }


# ============================================================
# ADMIN — OWNERSHIP REASSIGNMENT (reply-to-user "#/ NUM NUM+SLOT")
# ============================================================

def admin_set_owner(game_id: int, number: int, new_user_id: int, slot: int = None) -> bool:
    """
    ነባር registration ላይ user_id ብቻ ይቀይራል (user_name/is_paid/is_half ሳይነካ)።
    ባለቤቱ manual/board-edit ስም ገብቶ ተመዝግቦ ከሆነ ግን telegram user_id
    ካልተያያዘ፣ admin reply-ochenን ተጠቅሞ ትክክለኛውን ባለቤት ለማያያዝ ይጠቅማል።
    slot ካልተሰጠ ያ ቁጥር ላይ ያሉትን ሁሉንም slots ይቀይራል።
    ቁጥር ካልተገኘ False ይመልሳል።
    """
    conn = get_conn()
    cur = conn.cursor()
    if slot is not None:
        cur.execute("""
            UPDATE registrations SET user_id=%s
            WHERE game_id=%s AND number=%s AND slot=%s
        """, (new_user_id, game_id, number, slot))
    else:
        cur.execute("""
            UPDATE registrations SET user_id=%s
            WHERE game_id=%s AND number=%s
        """, (new_user_id, game_id, number))
    found = cur.rowcount > 0
    conn.commit()
    cur.close()
    conn.close()
    return found


# ============================================================
# NEW — ADMIN REPLY-TO-USER "እሺ/eshi NUM[+SLOT][✅] ..." REPLACEMENT
# (reply-to-user's own "ተይዞብሃል" attempt message — reassigns BOTH
# owner AND displayed name, optionally marks paid). Kept as its own
# function (separate from admin_set_owner above) so the existing
# "#/ NUM" ownership-only reassignment behavior is left untouched.
# ============================================================

def admin_replace_owner(game_id: int, number: int, new_user_id: int, new_user_name: str,
                         slot: int = None, mark_paid: bool = False) -> bool:
    """
    ነባር registration ላይ user_id እና user_name ሁለቱንም ይቀይራል (board ላይ አዲሱ
    ስም እንዲታይ)። mark_paid=True ከሆነ is_paid=TRUE ተብሎ ይመዘገባል፣ ካልሆነ
    is_paid=FALSE ይሆናል (አዲሱ ባለቤት ገና ስላልከፈለ)። slot ካልተሰጠ ያ ቁጥር ላይ
    ያሉትን ሁሉንም slots ይቀይራል። ቁጥር ካልተገኘ False ይመልሳል።
    """
    conn = get_conn()
    cur = conn.cursor()
    if slot is not None:
        cur.execute("""
            UPDATE registrations SET user_id=%s, user_name=%s, is_paid=%s, is_nekay=FALSE
            WHERE game_id=%s AND number=%s AND slot=%s
        """, (new_user_id, new_user_name, mark_paid, game_id, number, slot))
    else:
        cur.execute("""
            UPDATE registrations SET user_id=%s, user_name=%s, is_paid=%s, is_nekay=FALSE
            WHERE game_id=%s AND number=%s
        """, (new_user_id, new_user_name, mark_paid, game_id, number))
    found = cur.rowcount > 0
    conn.commit()
    cur.close()
    conn.close()
    return found


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
# PRE-BOOKING MEDIA
# ============================================================

def add_prebooking_media(file_id: str, media_type: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prebooking_media (
            id SERIAL PRIMARY KEY,
            file_id TEXT NOT NULL,
            media_type TEXT NOT NULL,
            added_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        INSERT INTO prebooking_media (file_id, media_type) VALUES (%s, %s)
    """, (file_id, media_type))
    conn.commit()
    cur.close()
    conn.close()


def get_prebooking_media() -> list:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, file_id, media_type, added_at FROM prebooking_media ORDER BY added_at ASC")
        rows = cur.fetchall()
    except Exception:
        rows = []
    cur.close()
    conn.close()
    return [{"id": r[0], "file_id": r[1], "media_type": r[2], "added_at": r[3]} for r in rows]


def remove_prebooking_media_by_index(index: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM prebooking_media ORDER BY added_at ASC")
        rows = cur.fetchall()
        if index < 1 or index > len(rows):
            cur.close()
            conn.close()
            return False
        target_id = rows[index - 1][0]
        cur.execute("DELETE FROM prebooking_media WHERE id=%s", (target_id,))
        conn.commit()
    except Exception:
        pass
    cur.close()
    conn.close()
    return True


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
        cur.execute("""
            DELETE FROM sms_payments
            WHERE matched=FALSE AND group_id=%s
        """, (group_id,))
        cur.execute("""
            DELETE FROM screenshot_payments
            WHERE matched=FALSE AND group_id=%s
        """, (group_id,))
    else:
        cur.execute("UPDATE game_settings SET is_active = FALSE")
    cur.execute("""
        INSERT INTO game_settings
        (total_numbers, numbers_per_person, price_full, price_half,
         prize_1st, prize_2nd, prize_3rd, payment_info, group_id,
         countdown_enabled, countdown_minutes, game_rule, slot_symbol,
         show_all_slots, profit_per_game)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        data.get("show_all_slots", False),
        data.get("profit_per_game", 0),
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
            "game_rule", "slot_symbol", "show_all_slots", "pre_wipe_snapshot",
            "profit_per_game"]
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


def register_number(game_id, user_id, user_name, number, is_half, force=False, allow_toggle=True, is_parsed_name=False, force_slot=None):
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
    # FIX: force_slot (06+1 / 06+2 slot-specific nekay) ሁልጊዜ half cost ነው
    cost = price_half if (is_half or force_slot is not None) else price_full

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
        # FIX: force_slot ካለ (06+1/06+2 slot-specific nekay)፣ ያንን slot
        # ብቻ ይተካል፣ ሌላውን slot (የቀድሞ ባለቤት) አይነካውም። is_nekay=TRUE ባለበት
        # slot ላይ ብቻ ይሰራል (ደህንነት)።
        if force_slot is not None:
            cur.execute("""
                UPDATE registrations
                SET user_id=%s, user_name=%s, is_half=TRUE, is_nekay=FALSE,
                    is_paid=%s, pending_upgrade=FALSE, registered_at=NOW()
                WHERE game_id=%s AND number=%s AND slot=%s AND is_nekay=TRUE
            """, (user_id, user_name, can_pay, game_id, number, force_slot))
            if cur.rowcount == 0:
                # ያ slot is_nekay=TRUE ሆኖ አልተገኘም (ምናልባት ቀድሞ ተይዞ/ተቀይሮ) —
                # taken እንደሆነ ይመለስ
                conn.commit()
                cur.close()
                conn.close()
                return "taken"
            if can_pay:
                _deduct_balance(cur, group_id, user_id, cost, prize_balance, carry_balance)
            conn.commit()
            cur.close()
            conn.close()
            return "registered_half"

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

    # FIX: user_id=0 (admin bulk "/register <name>" placeholder — ገና ለ real
    # telegram account ያልተያያዘ) ብዙ የተለያዩ ስሞች ተመሳሳይ telegram_id=0 ስር ስለሚወድቁ፣
    # ማንኛውም user_id=0 registration ከዚህ ራስ-ሰር balance-drain (FIFO) ውጪ ይቀራል —
    # ልክ እንደ handle_newgame/handle_setgame ውስጥ ያለው ነባር "user_id != 0" ንድፍ
    # (ስለዚህ የተለያዩ ስሞች እርስ በርስ ክፍያ አይደራረቡም)። Admin "#/ NUM" ተጠቅሞ ትክክለኛውን
    # real telegram_id ካያያዘ በኋላ ብቻ ነው ራስ-ሰር confirm_payment ለዚያ registration
    # የሚሰራው። ይህ ለ real (non-zero) telegram_id ምንም ለውጥ አያመጣም።
    if telegram_id == 0:
        cur.close()
        conn.close()
        return {"confirmed": [], "remaining_balance": carry_balance + prize_balance}

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
# NEKAY
# ============================================================

def mark_nekay(game_id: int, number: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE registrations
        SET is_nekay=TRUE
        WHERE game_id=%s AND number=%s AND is_paid=FALSE
    """, (game_id, number))
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


def get_nekay_numbers(game_id: int) -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT number, slot, is_half
        FROM registrations
        WHERE game_id=%s AND is_nekay=TRUE
        ORDER BY number, slot
    """, (game_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = {}
    for number, slot, is_half in rows:
        if number not in result:
            result[number] = set()
        result[number].add(slot)
    return [(n, slots) for n, slots in sorted(result.items())]


def admin_set_nekay(game_id: int, numbers: list) -> dict:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE registrations
        SET is_nekay=FALSE
        WHERE game_id=%s AND is_nekay=TRUE
    """, (game_id,))

    empty_numbers = []

    for number, is_half in numbers:
        cur.execute("""
            SELECT id FROM registrations
            WHERE game_id=%s AND number=%s
        """, (game_id, number))
        rows = cur.fetchall()

        if not rows:
            empty_numbers.append((number, is_half))
            continue

        cur.execute("""
            UPDATE registrations
            SET is_nekay=TRUE
            WHERE game_id=%s AND number=%s
        """, (game_id, number))

    conn.commit()
    cur.close()
    conn.close()
    return {"empty_numbers": empty_numbers}


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


def get_users_by_number(game_id: int, number: int) -> list:
    """
    ✅ FIX: pre-booking ሲጀምር (handle_video_chat_started) registrations
    በጸጥታ ይጠፋሉ። Winner photo ገና ውጤቱ ካልታወቀ በፊት ይህ ቢፈጠር፣ live
    registrations ምንም ስለማይገኝ "user አልተገኘም" ይሆናል። ስለዚህ live ውጤት ባዶ
    ከሆነ፣ ከመጥፋቱ በፊት የተቀመጠውን game_settings.pre_wipe_snapshot ላይ
    ተመልክቶ ትክክለኛውን ባለቤት ያገኛል። ይህ ማንኛውም caller (handlers.py፣
    userbot2.py፣ ወዘተ) ራሱ ምንም ሳይቀየር በራሱ ይጠቀማል።
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, user_name, slot, is_half FROM registrations
        WHERE game_id=%s AND number=%s
        ORDER BY slot ASC
    """, (game_id, number))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    live = [{"telegram_id": r[0], "user_name": r[1], "slot": r[2], "is_half": r[3]} for r in rows]
    if live:
        return live

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT pre_wipe_snapshot FROM game_settings WHERE id=%s", (game_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row or not row[0]:
        return []

    snapshot = row[0]
    if isinstance(snapshot, str):
        try:
            snapshot = _json.loads(snapshot)
        except Exception:
            return []

    entry = snapshot.get(str(number))
    return entry if entry else []


def save_registrations_snapshot(game_id: int):
    """
    Fix: pre-booking ሲጀምር (handle_video_chat_started) registrations
    በጸጥታ ይጠፋሉ። Winner photo ገና ውጤቱ ካልታወቀ በፊት ይህ ቢፈጠር፣ winner
    lookup ምንም ማግኘት ስለማይችል "user አልተገኘም" ይሆናል። ስለዚህ ከመጥፋቱ በፊት
    ነባሩን registrations ሙሉ በሙሉ (number→users mapping) snapshot አድርጎ
    game_settings.pre_wipe_snapshot ላይ ያስቀምጣል። ነባሩ wipe logic ራሱ
    ምንም አልተነካም — ይህ ተጨማሪ safety net ብቻ ነው።
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT number, user_id, user_name, slot, is_half
        FROM registrations WHERE game_id=%s
    """, (game_id,))
    rows = cur.fetchall()

    snapshot = {}
    for number, user_id, user_name, slot, is_half in rows:
        key = str(number)
        snapshot.setdefault(key, []).append({
            "telegram_id": user_id,
            "user_name": user_name,
            "slot": slot,
            "is_half": is_half,
        })

    cur.execute("""
        UPDATE game_settings SET pre_wipe_snapshot=%s WHERE id=%s
    """, (_json.dumps(snapshot), game_id))
    conn.commit()
    cur.close()
    conn.close()


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


def get_winners_by_place(game_id: int, place: int) -> list:
    """
    FIX: get_winner_by_place ራሱ አንድ row ብቻ ይመልሳል፣ 2+ ሰዎች
    በተመሳሳይ ቦታ (tie) ቢያሸንፉ አንዱን ብቻ ይዞ ሌላውን ይተወዋል።
    ይህ function ሁሉንም tied winners list አርጎ ይመልሳል።
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT w.telegram_id, w.user_name, w.prize,
               COALESCE(ub.balance, 0) as balance, w.group_id
        FROM winners w
        LEFT JOIN user_balance ub ON ub.group_id = w.group_id AND ub.telegram_id = w.telegram_id
        WHERE w.game_id = %s AND w.place = %s
        ORDER BY w.created_at ASC
    """, (game_id, place))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "telegram_id": r[0],
            "user_name": r[1],
            "prize": float(r[2]) if r[2] else 0,
            "balance": float(r[3]) if r[3] else 0,
            "group_id": r[4],
        }
        for r in rows
    ]


def save_winner(game_id: int, place: int, telegram_id: int, user_name: str,
                number: int, prize: float, group_id: int = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO winners (game_id, place, telegram_id, user_name, number, prize, group_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (game_id, place, telegram_id) DO UPDATE
            SET user_name=EXCLUDED.user_name,
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
               COALESCE(ub.balance, 0) as balance, w.sent,
               w.telegram_id, w.number
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
        "created_at": r[3], "balance": float(r[4] or 0), "sent": r[5],
        "telegram_id": r[6], "number": r[7]
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
        UPDATE winners SET sent=TRUE, sent_amount=%s WHERE game_id=%s AND telegram_id=%s
    """, (amount, game_id, telegram_id))
    conn.commit()
    cur.close()
    conn.close()


def get_recent_winner_for_user(group_id: int, telegram_id: int, hours: int = 24) -> dict:
    """
    Fix: group-chat #/<amount> reply ለ winner ክፍያ ማረጋገጫ ለመጠቀም፣ ይህ ሰው
    በዚህ group ላይ በቅርብ ጊዜ (default 24 ሰዓት) real winner መሆኑን ያረጋግጣል
    (ልክ /winners command እንደሚያደርገው) — active game_id ገና ተቀይሮ ቢሆንም እንኳ
    (ለምሳሌ admin /setgame ካደረገ) ያለፈውን winner ማግኘት ይችላል።

    ✅ FIX: ነባሩ prize_balance carry-over ስርዓት (clear_prize_balance 2-cycle)
    ራሱ እውነተኛው ገደብ ሆኖ ያገለግላል — ተጫዋቹ prize_balance > 0 ገና ካለው ብቻ
    ይገኛል (ማለትም ገንዘቡ ገና ካልጸዳ)። ስለዚህ round 1 ላይ ያሸነፈ ሰው round 3 ላይ
    (2 newgame cycles አልፎ prize_balance ቀድሞ ከጸዳ) አይገኝም — ግን round 2 ላይ
    ያሸነፈ ሰው round 3 ላይ (still within carry window) በትክክል ይገኛል።
    """
    conn = get_conn()
    cur = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=hours)
    cur.execute("""
        SELECT w.game_id, w.place, w.prize, w.sent_amount
        FROM winners w
        JOIN user_balance ub ON ub.group_id = w.group_id AND ub.telegram_id = w.telegram_id
        WHERE w.group_id=%s AND w.telegram_id=%s
          AND w.created_at >= %s
          AND ub.prize_balance > 0
        ORDER BY w.created_at DESC LIMIT 1
    """, (group_id, telegram_id, cutoff))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "game_id": row[0],
        "place": row[1],
        "prize": float(row[2] or 0),
        "sent_amount": float(row[3] or 0),
    }


def get_recent_winners_for_user(group_id: int, telegram_id: int, hours: int = 24) -> list:
    """
    FIX: "#<amount>" ክፍያ ላይ አንድ ሰው ብዙ places (ለምሳሌ 2ኛ እና 3ኛ፣ ወይም 1ኛ እና
    2ኛ) በአንድ ጊዜ ካሸነፈ ሁሉንም ያምጣ (ልክ እንደ userbot2.py's
    get_all_winners_by_telegram_id style) — admin ነጠላ ቁጥር ሲልክ ሁሉንም
    tied ቦታዎች ድምር አድርጎ በአንድ payment እንዲይዝ። ከ get_recent_winner_for_user
    ጋር ተመሳሳይ eligibility check (prize_balance > 0, ባለፉት `hours` ውስጥ)
    ይጠቀማል፣ ግን LIMIT 1 ሳይሆን ሁሉንም tied records ይመልሳል።
    """
    conn = get_conn()
    cur = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=hours)
    cur.execute("""
        SELECT w.game_id, w.place, w.prize, w.sent_amount
        FROM winners w
        JOIN user_balance ub ON ub.group_id = w.group_id AND ub.telegram_id = w.telegram_id
        WHERE w.group_id=%s AND w.telegram_id=%s
          AND w.created_at >= %s
          AND ub.prize_balance > 0
        ORDER BY w.place ASC, w.created_at DESC
    """, (group_id, telegram_id, cutoff))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "game_id": r[0],
            "place": r[1],
            "prize": float(r[2] or 0),
            "sent_amount": float(r[3] or 0),
        }
        for r in rows
    ]


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


def reverse_winner_balance(game_id: int, telegram_id: int, amount: float, group_id: int = None):
    """
    Winner correction ጊዜ ቀደም ብሎ የተሰጠ wrong prize ያቀንስ።
    prize_balance ቀደም ተጨምሮ ነበር — ስለዚህ ዳግም ይቀነሳል።
    """
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
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return

    carry_balance = float(row[0])
    prize_balance = float(row[1])

    # prize_balance ካለ ከዛ ቀንስ፣ ካለቀ carry_balance ላይ ቀንስ
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
    cur.close()
    conn.close()


def delete_winner(game_id: int, place: int, group_id: int = None):
    """
    Winner correction ጊዜ ያሮጌውን winner record ያስወግዳል።
    ቀጣዩ save_winner ትክክለኛውን winner ይጽፋል።
    """
    conn = get_conn()
    cur = conn.cursor()
    if group_id:
        cur.execute("""
            DELETE FROM winners WHERE game_id=%s AND place=%s AND group_id=%s
        """, (game_id, place, group_id))
    else:
        cur.execute("""
            DELETE FROM winners WHERE game_id=%s AND place=%s
        """, (game_id, place))
    conn.commit()
    cur.close()
    conn.close()



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


def clear_carry_balance(group_id: int):
    """
    Fix: /newgame በተጀመረ ቁጥር carry_balance (ተጫዋቾች manually ያስቀመጡት ተራ ገንዘብ)
    ሙሉ በሙሉ ይጸዳል። prize_balance/winner_carried carry-over logic (ከላይ ያለው
    clear_prize_balance) አልተነካም — ይህ function ከ clear_prize_balance ቀጥሎ
    ብቻ ይጠራል። group_id የግድ ጥቅም ላይ ይውላል፣ ሌላ group's balances አይነካም።
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE user_balance
        SET carry_balance=0,
            balance=prize_balance,
            updated_at=NOW()
        WHERE group_id=%s
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

    # ✅ FIX: game_id → group_id ፈልግ፣ ያልተዛመደ (unmatched) sms/screenshot payments ጽዳ
    cur.execute("SELECT group_id FROM game_settings WHERE id=%s", (game_id,))
    row = cur.fetchone()
    group_id = row[0] if row else None

    if group_id:
        cur.execute("""
            DELETE FROM sms_payments
            WHERE matched=FALSE AND group_id=%s
        """, (group_id,))
        cur.execute("""
            DELETE FROM screenshot_payments
            WHERE matched=FALSE AND group_id=%s
        """, (group_id,))
        cur.execute("""
            DELETE FROM payment_claims
            WHERE group_id=%s
        """, (group_id,))

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
# USER BALANCE
# ============================================================

def get_user_balance(group_id: int, telegram_id: int) -> float:
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
    except Exception:
        return 0.0


# ============================================================
# PAYMENT MATCHING
# ============================================================

AMOUNT_TOLERANCE = 20


def _normalize_ref_for_match(ref: str) -> str:
    """
    ✅ Ref numbers ላይ ቅድሚያ የሚሰጠው exact match ነው (ደህንነት ስለሆነ ሰፊ fuzzy
    አልተደረገም) — ግን screenshot (vision AI) ላይ በተለምዶ የሚፈጠሩ OCR ስህተቶች
    (0↔O, 1↔I, 5↔S) ብቻ በጣም ጠባብ በሆነ መንገድ normalize ይደረጋሉ ከዚያ ንፅፅር
    ይደረጋል። stored ref_no ራሱ (DB ውስጥ) ምንም አይነካም — ንፅፅር ጊዜ ብቻ ጥቅም ላይ
    ይውላል።
    """
    if not ref:
        return ref
    r = ref.strip().upper()
    r = r.replace("O", "0").replace("I", "1").replace("S", "5")
    return r


def _refs_match(ref1: str, ref2: str) -> bool:
    """
    Normalize አድርጎ ካነጻጸረ በኋላ እንኳ 1 character ብቻ ልዩነት ካለ (Levenshtein
    distance ≤ 1) — ለምሳሌ AI/OCR አንድ digit ብቻ ቢሳሳት — still match ተብሎ
    ይቆጠራል። ከ1 በላይ ልዩነት ካለ ግን ፈጽሞ አይመሳሰልም (ደህንነት ለማስጠበቅ — 2 የተለያዩ
    እውነተኛ ግብይቶች በአጋጣሚ እንዳይምታቱ)።
    """
    if not ref1 or not ref2:
        return False
    n1, n2 = _normalize_ref_for_match(ref1), _normalize_ref_for_match(ref2)
    if n1 == n2:
        return True
    if abs(len(n1) - len(n2)) > 1:
        return False
    return _levenshtein(n1, n2) <= 1


def _normalize_name(name: str) -> set:
    if not name:
        return set()
    cleaned = re.sub(r"[^a-zA-Z\u1200-\u137F\s]", "", name.lower())
    return set(w for w in cleaned.split() if len(w) > 1)


def _levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        s1, s2 = s2, s1
    if not s2:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j] + (c1 != c2), curr[j] + 1, prev[j + 1] + 1))
        prev = curr
    return prev[-1]


def _names_match(name1: str, name2: str) -> bool:
    n1, n2 = _normalize_name(name1), _normalize_name(name2)
    if not n1 or not n2:
        return False
    if n1 & n2:
        return True
    for w1 in n1:
        for w2 in n2:
            if len(w1) < 4 or len(w2) < 4:
                continue
            if _levenshtein(w1, w2) <= 2:
                return True
    return False


def save_sms_payment(amount, sender_name: str, ref: str, sms_type: str, raw_sms: str, group_id: int = None,
                      game_id: int = None, phone_last4: str = None, account_last4: str = None) -> dict:
    conn = get_conn()
    cur = conn.cursor()

    # group_id ከሌለ insert ብቻ እናድርግ — match አንሞክር
    if not group_id:
        cur.execute("""
            INSERT INTO sms_payments (group_id, game_id, ref_no, amount, sender_name, pay_type, raw_sms, matched, phone_last4, account_last4)
            VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, %s, %s)
        """, (group_id, game_id, ref, amount, sender_name, sms_type, raw_sms, phone_last4, account_last4))
        conn.commit()
        cur.close()
        conn.close()
        return {"matched": None}

    cur.execute("""
        INSERT INTO sms_payments (group_id, game_id, ref_no, amount, sender_name, pay_type, raw_sms, matched, phone_last4, account_last4)
        VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, %s, %s)
        RETURNING id
    """, (group_id, game_id, ref, amount, sender_name, sms_type, raw_sms, phone_last4, account_last4))
    sms_id = cur.fetchone()[0]
    conn.commit()

    # screenshot_payments ውስጥ candidate ፈልግ
    if game_id is not None:
        cur.execute("""
            SELECT id, telegram_id, ref_no, amount, sender_name, receipt_chat_id, receipt_message_id
            FROM screenshot_payments
            WHERE matched=FALSE AND group_id=%s
              AND (game_id=%s OR game_id IS NULL)
              AND amount BETWEEN %s AND %s
            ORDER BY created_at ASC
        """, (group_id, game_id, float(amount) - AMOUNT_TOLERANCE, float(amount) + AMOUNT_TOLERANCE))
    else:
        cur.execute("""
            SELECT id, telegram_id, ref_no, amount, sender_name, receipt_chat_id, receipt_message_id
            FROM screenshot_payments
            WHERE matched=FALSE AND group_id=%s
              AND game_id IS NULL
              AND amount BETWEEN %s AND %s
            ORDER BY created_at ASC
        """, (group_id, float(amount) - AMOUNT_TOLERANCE, float(amount) + AMOUNT_TOLERANCE))

    candidates = cur.fetchall()
    chosen = None

    # 1️⃣ Ref match
    if ref:
        for scr_id, telegram_id, scr_ref, scr_amount, scr_sender, scr_chat_id, scr_msg_id in candidates:
            if scr_ref and _refs_match(scr_ref, ref):
                chosen = (scr_id, telegram_id, scr_sender, scr_chat_id, scr_msg_id)
                break

    # 2️⃣ Name match — ስም ከሌለ match አናደርግም
    if not chosen:
        if sender_name:
            for scr_id, telegram_id, scr_ref, scr_amount, scr_sender, scr_chat_id, scr_msg_id in candidates:
                if _names_match(sender_name, scr_sender):
                    chosen = (scr_id, telegram_id, scr_sender, scr_chat_id, scr_msg_id)
                    break

    matched_data = None
    if chosen:
        scr_id, telegram_id, scr_sender, scr_chat_id, scr_msg_id = chosen
        # ✅ Match ሆነ — ሁለቱንም DELETE
        cur.execute("DELETE FROM sms_payments WHERE id=%s", (sms_id,))
        cur.execute("DELETE FROM screenshot_payments WHERE id=%s", (scr_id,))
        conn.commit()
        matched_data = {
            "telegram_id": telegram_id,
            "amount": float(amount),
            "type": sms_type,
            "sender_name": sender_name or scr_sender,
            "group_id": group_id,
            "receipt_chat_id": scr_chat_id,
            "receipt_message_id": scr_msg_id,
            "phone_last4": phone_last4,
            "account_last4": account_last4,
        }

    cur.close()
    conn.close()
    return {"matched": matched_data}


def find_matching_sms(telegram_id: int, amount, sender_name: str, ref: str, pay_type: str, group_id: int = None, game_id: int = None):
    # group_id ከሌለ match አናደርግም
    if not group_id:
        return None

    conn = get_conn()
    cur = conn.cursor()

    # ✅ game_id None ሲሆን IS NULL ተጠቀም
    if game_id is not None:
        cur.execute("""
            SELECT id, ref_no, amount, sender_name, pay_type, phone_last4, account_last4
            FROM sms_payments
            WHERE matched=FALSE
              AND group_id=%s
              AND (game_id=%s OR game_id IS NULL)
              AND amount BETWEEN %s AND %s
            ORDER BY created_at ASC
        """, (group_id, game_id, float(amount) - AMOUNT_TOLERANCE, float(amount) + AMOUNT_TOLERANCE))
    else:
        cur.execute("""
            SELECT id, ref_no, amount, sender_name, pay_type, phone_last4, account_last4
            FROM sms_payments
            WHERE matched=FALSE
              AND group_id=%s
              AND game_id IS NULL
              AND amount BETWEEN %s AND %s
            ORDER BY created_at ASC
        """, (group_id, float(amount) - AMOUNT_TOLERANCE, float(amount) + AMOUNT_TOLERANCE))

    candidates = cur.fetchall()

    if not candidates:
        cur.close()
        conn.close()
        return None

    chosen = None

    # 1️⃣ Ref match
    if ref:
        for sms_id, sms_ref, sms_amount, sms_sender, sms_type, sms_phone, sms_account in candidates:
            if sms_ref and _refs_match(sms_ref, ref):
                chosen = (sms_id, sms_amount, sms_type, sms_sender, sms_phone, sms_account)
                break

    # 2️⃣ Name match — ስም ከሌለ match አናደርግም
    if not chosen and sender_name:
        for sms_id, sms_ref, sms_amount, sms_sender, sms_type, sms_phone, sms_account in candidates:
            if _names_match(sender_name, sms_sender):
                chosen = (sms_id, sms_amount, sms_type, sms_sender, sms_phone, sms_account)
                break

    if not chosen:
        cur.close()
        conn.close()
        return None

    sms_id, sms_amount, sms_type, sms_sender, sms_phone, sms_account = chosen

    # ✅ Match ሆነ — sms record DELETE
    cur.execute("DELETE FROM sms_payments WHERE id=%s", (sms_id,))
    conn.commit()
    cur.close()
    conn.close()

    return {
        "id": sms_id,
        "amount": float(sms_amount),
        "type": sms_type,
        "sender_name": sender_name or sms_sender,
        "phone_last4": sms_phone,
        "account_last4": sms_account,
    }


def save_screenshot_payment(telegram_id: int, amount, sender_name: str,
                             ref: str, pay_type: str, description: str, group_id: int = None, game_id: int = None,
                             receipt_chat_id: int = None, receipt_message_id: int = None) -> dict:
    import uuid
    conn = get_conn()
    cur = conn.cursor()

    # receipt columns ካሌሉ ይጨምር
    cur.execute("ALTER TABLE screenshot_payments ADD COLUMN IF NOT EXISTS receipt_chat_id BIGINT;")
    cur.execute("ALTER TABLE screenshot_payments ADD COLUMN IF NOT EXISTS receipt_message_id BIGINT;")

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

    safe_ref = ref if ref else str(uuid.uuid4())

    cur.execute("""
        INSERT INTO screenshot_payments
        (group_id, game_id, telegram_id, ref_no, amount, sender_name, pay_type, description, matched, receipt_chat_id, receipt_message_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, %s)
    """, (group_id, game_id, telegram_id, safe_ref, amount, sender_name, pay_type, description, receipt_chat_id, receipt_message_id))

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
        SELECT 1 FROM sms_payments WHERE ref_no = %s
        UNION
        SELECT 1 FROM screenshot_payments WHERE ref_no = %s
    """, (ref_no, ref_no))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row is not None


def cleanup_old_payments(days: int = 7):
    conn = get_conn()
    cur = conn.cursor()
    cutoff = datetime.now() - timedelta(days=days)
    cur.execute("DELETE FROM sms_payments WHERE created_at < %s", (cutoff,))
    cur.execute("DELETE FROM screenshot_payments WHERE created_at < %s", (cutoff,))
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


def clear_balance_by_telegram_id(group_id: int, telegram_id: int) -> bool:
    """
    NEW: winner-🔥-reaction feature — ልክ እንደ /clearbalance @username ግን
    በቀጥታ telegram_id ተጠቅሞ (ስም lookup ሳያስፈልግ) የአንድ ሰው ብቻ balance ያጸዳል።
    Board/registrations/paid status ላይ ምንም ተጽዕኖ የለውም — user_balance ብቻ ነው
    የሚነካው (ልክ እንደ clear_balance_by_username/clear_balance_all)።
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE user_balance SET balance=0, carry_balance=0, prize_balance=0, updated_at=NOW()
        WHERE telegram_id=%s AND group_id=%s
    """, (telegram_id, group_id))
    updated = cur.rowcount > 0
    conn.commit()
    cur.close()
    conn.close()
    return updated


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
