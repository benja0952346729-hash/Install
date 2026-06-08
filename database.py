import psycopg2
from datetime import datetime, timedelta
from config import DATABASE_URL


def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode='require')


def init_db():
    conn = get_conn()
    cur = conn.cursor()
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
            registered_at TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS sms_payments (
            id SERIAL PRIMARY KEY,
            ref_no TEXT UNIQUE NOT NULL,
            amount NUMERIC,
            pay_type TEXT,
            raw_sms TEXT,
            matched BOOLEAN DEFAULT FALSE,
            matched_data JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS screenshot_payments (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT,
            ref_no TEXT UNIQUE NOT NULL,
            pay_type TEXT,
            description TEXT,
            matched BOOLEAN DEFAULT FALSE,
            matched_data JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# GAME SETTINGS
# ============================================================

def save_settings(data: dict):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE game_settings SET is_active = FALSE")
    cur.execute("""
        INSERT INTO game_settings
        (total_numbers, numbers_per_person, price_full, price_half,
         prize_1st, prize_2nd, prize_3rd, payment_info)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        data["total_numbers"], data["numbers_per_person"],
        data["price_full"], data.get("price_half"),
        data["prize_1st"], data.get("prize_2nd"), data.get("prize_3rd"),
        data["payment_info"]
    ))
    game_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return game_id


def get_active_settings():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM game_settings WHERE is_active = TRUE ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    cols = ["id", "total_numbers", "numbers_per_person", "price_full", "price_half",
            "prize_1st", "prize_2nd", "prize_3rd", "payment_info",
            "board_message_id", "remaining_message_id", "is_active", "created_at"]
    return dict(zip(cols, row))


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


def register_number(game_id, user_id, user_name, number, is_half):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, is_half, slot FROM registrations
        WHERE game_id=%s AND number=%s ORDER BY slot
    """, (game_id, number))
    existing = cur.fetchall()

    if not existing:
        cur.execute("""
            INSERT INTO registrations (game_id, user_id, user_name, number, is_half, slot)
            VALUES (%s, %s, %s, %s, %s, 1)
        """, (game_id, user_id, user_name, number, is_half))
        conn.commit()
        cur.close()
        conn.close()
        return "registered"

    if len(existing) == 1 and existing[0][1] == True and is_half:
        cur.execute("""
            INSERT INTO registrations (game_id, user_id, user_name, number, is_half, slot)
            VALUES (%s, %s, %s, %s, %s, 2)
        """, (game_id, user_id, user_name, number, is_half))
        conn.commit()
        cur.close()
        conn.close()
        return "registered_half"

    cur.close()
    conn.close()
    return "taken"


def get_taken_numbers(game_id):
    rows = get_registrations(game_id)
    result = {}
    for number, user_name, is_half, slot in rows:
        if number not in result:
            result[number] = []
        result[number].append((user_name, is_half, slot))
    return result


# ============================================================
# SMS PAYMENTS
# ============================================================

def save_sms_payment(ref_no: str, amount, pay_type: str, raw_sms: str) -> dict:
    """
    SMS payment ያስቀምጣል። Screenshot ጋር match ካለ ያዛምዳል።
    """
    import json as _json
    conn = get_conn()
    cur = conn.cursor()

    # ቀደም ሲል screenshot ከተላከ match ያድርግ
    cur.execute("""
        SELECT id, telegram_id, ref_no, pay_type
        FROM screenshot_payments
        WHERE ref_no = %s AND matched = FALSE
    """, (ref_no,))
    screenshot = cur.fetchone()

    matched_data = None

    if screenshot:
        scr_id, telegram_id, scr_ref, scr_type = screenshot
        matched_data = {
            "telegram_id": telegram_id,
            "refNo": ref_no,
            "amount": amount,
            "type": pay_type,
        }
        matched_json = _json.dumps(matched_data)

        # SMS record ይፍጠር — matched=True
        cur.execute("""
            INSERT INTO sms_payments (ref_no, amount, pay_type, raw_sms, matched, matched_data)
            VALUES (%s, %s, %s, %s, TRUE, %s)
            ON CONFLICT (ref_no) DO UPDATE
            SET matched = TRUE, matched_data = EXCLUDED.matched_data
        """, (ref_no, amount, pay_type, raw_sms, matched_json))

        # Screenshot ን update ያድርግ
        cur.execute("""
            UPDATE screenshot_payments
            SET matched = TRUE, matched_data = %s
            WHERE id = %s
        """, (matched_json, scr_id))
    else:
        # Screenshot የለም — SMS ብቻ ያስቀምጥ
        cur.execute("""
            INSERT INTO sms_payments (ref_no, amount, pay_type, raw_sms)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (ref_no) DO NOTHING
        """, (ref_no, amount, pay_type, raw_sms))

    conn.commit()
    cur.close()
    conn.close()
    return {"matched": matched_data}


def get_sms_payment_by_ref(ref_no: str):
    """Ref number ያለ SMS payment ይፈልጋል"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, ref_no, amount, pay_type FROM sms_payments WHERE ref_no = %s", (ref_no,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "refNo": row[1], "amount": row[2], "type": row[3]}


# ============================================================
# SCREENSHOT PAYMENTS
# ============================================================

def save_screenshot_payment(telegram_id: int, ref_no: str, pay_type: str, description: str) -> dict:
    """
    Screenshot payment ያስቀምጣል። SMS ቀደም ሲል ከተላከ match ያድርግ።
    """
    import json as _json
    conn = get_conn()
    cur = conn.cursor()

    # ቀደም ሲል SMS ከተላከ match ያድርግ
    cur.execute("""
        SELECT id, ref_no, amount, pay_type
        FROM sms_payments
        WHERE ref_no = %s AND matched = FALSE
    """, (ref_no,))
    sms = cur.fetchone()

    matched_data = None

    if sms:
        sms_id, sms_ref, amount, sms_type = sms
        matched_data = {
            "telegram_id": telegram_id,
            "refNo": ref_no,
            "amount": amount,
            "type": sms_type,
        }
        matched_json = _json.dumps(matched_data)

        # Screenshot record ይፍጠር — matched=True
        cur.execute("""
            INSERT INTO screenshot_payments (telegram_id, ref_no, pay_type, description, matched, matched_data)
            VALUES (%s, %s, %s, %s, TRUE, %s)
            ON CONFLICT (ref_no) DO UPDATE
            SET matched = TRUE, matched_data = EXCLUDED.matched_data
        """, (telegram_id, ref_no, pay_type, description, matched_json))

        # SMS ን update ያድርግ
        cur.execute("""
            UPDATE sms_payments
            SET matched = TRUE, matched_data = %s
            WHERE id = %s
        """, (matched_json, sms_id))
    else:
        # SMS የለም — Screenshot ብቻ ያስቀምጥ
        cur.execute("""
            INSERT INTO screenshot_payments (telegram_id, ref_no, pay_type, description)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (ref_no) DO NOTHING
        """, (telegram_id, ref_no, pay_type, description))

    conn.commit()
    cur.close()
    conn.close()
    return {"matched": matched_data}


def is_ref_matched_already(ref_no: str) -> bool:
    """Ref number ቀደም ሲል matched ሆኗል?"""
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


# ============================================================
# CLEANUP
# ============================================================

def cleanup_old_payments(days: int = 7):
    """ያረጁ (unmatched) payment records ያጸዳል"""
    conn = get_conn()
    cur = conn.cursor()
    cutoff = datetime.now() - timedelta(days=days)

    cur.execute("""
        DELETE FROM sms_payments
        WHERE matched = FALSE AND created_at < %s
    """, (cutoff,))

    cur.execute("""
        DELETE FROM screenshot_payments
        WHERE matched = FALSE AND created_at < %s
    """, (cutoff,))

    conn.commit()
    cur.close()
    conn.close()
