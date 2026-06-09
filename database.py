import psycopg2
import json as _json
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
            is_paid BOOLEAN DEFAULT FALSE,
            registered_at TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS user_balance (
            id SERIAL PRIMARY KEY,
            game_id INT REFERENCES game_settings(id),
            telegram_id BIGINT,
            balance NUMERIC DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(game_id, telegram_id)
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

        CREATE TABLE IF NOT EXISTS winners (
            id SERIAL PRIMARY KEY,
            game_id INT REFERENCES game_settings(id),
            place INT,
            telegram_id BIGINT,
            user_name TEXT,
            number INT,
            prize NUMERIC,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(game_id, place)
        );

        CREATE TABLE IF NOT EXISTS screenshot_payments (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT,
            ref_no TEXT UNIQUE,
            pay_type TEXT,
            description TEXT,
            matched BOOLEAN DEFAULT FALSE,
            matched_data JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS is_paid BOOLEAN DEFAULT FALSE;")
    cur.execute("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS is_nekay BOOLEAN DEFAULT FALSE;")
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'screenshot_payments_ref_no_key'
            ) THEN
                ALTER TABLE screenshot_payments ADD CONSTRAINT screenshot_payments_ref_no_key UNIQUE (ref_no);
            END IF;
        END
        $$;
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


def register_number(game_id, user_id, user_name, number, is_half, force=False):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, is_half, slot FROM registrations
        WHERE game_id=%s AND number=%s ORDER BY slot
    """, (game_id, number))
    existing = cur.fetchall()

    cur.execute("SELECT price_full, price_half FROM game_settings WHERE id=%s", (game_id,))
    price_row = cur.fetchone()
    price_full = float(price_row[0] or 0)
    price_half = float(price_row[1] or 0)
    cost = price_half if is_half else price_full

    cur.execute("""
        SELECT balance FROM user_balance
        WHERE game_id=%s AND telegram_id=%s
    """, (game_id, user_id))
    bal_row = cur.fetchone()
    balance = float(bal_row[0]) if bal_row else 0.0
    can_pay = balance >= cost

    if force and existing:
        cur.execute("""
            UPDATE registrations
            SET user_id=%s, user_name=%s, is_half=%s, is_nekay=FALSE,
                is_paid=%s, registered_at=NOW()
            WHERE game_id=%s AND number=%s AND slot=1
        """, (user_id, user_name, is_half, can_pay, game_id, number))
        if not is_half:
            cur.execute("""
                DELETE FROM registrations
                WHERE game_id=%s AND number=%s AND slot=2
            """, (game_id, number))
        if can_pay:
            new_balance = balance - cost
            cur.execute("""
                UPDATE user_balance SET balance=%s, updated_at=NOW()
                WHERE game_id=%s AND telegram_id=%s
            """, (new_balance, game_id, user_id))
        conn.commit()
        cur.close()
        conn.close()
        return "registered"

    if not existing:
        cur.execute("""
            INSERT INTO registrations (game_id, user_id, user_name, number, is_half, slot, is_paid, is_nekay)
            VALUES (%s, %s, %s, %s, %s, 1, %s, FALSE)
        """, (game_id, user_id, user_name, number, is_half, can_pay))
        if can_pay:
            new_balance = balance - cost
            cur.execute("""
                UPDATE user_balance SET balance=%s, updated_at=NOW()
                WHERE game_id=%s AND telegram_id=%s
            """, (new_balance, game_id, user_id))
        conn.commit()
        cur.close()
        conn.close()
        return "registered"

    if len(existing) == 1 and existing[0][1] == True and is_half:
        cur.execute("""
            INSERT INTO registrations (game_id, user_id, user_name, number, is_half, slot, is_paid, is_nekay)
            VALUES (%s, %s, %s, %s, %s, 2, %s, FALSE)
        """, (game_id, user_id, user_name, number, is_half, can_pay))
        if can_pay:
            new_balance = balance - cost
            cur.execute("""
                UPDATE user_balance SET balance=%s, updated_at=NOW()
                WHERE game_id=%s AND telegram_id=%s
            """, (new_balance, game_id, user_id))
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
# PAYMENT CONFIRMATION
# ============================================================

def confirm_payment(telegram_id: int, amount: float) -> dict:
    conn = get_conn()
    cur = conn.cursor()

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

    cur.execute("""
        INSERT INTO user_balance (game_id, telegram_id, balance)
        VALUES (%s, %s, %s)
        ON CONFLICT (game_id, telegram_id)
        DO UPDATE SET balance = user_balance.balance + %s, updated_at = NOW()
        RETURNING balance
    """, (game_id, telegram_id, amount, amount))
    total_balance = float(cur.fetchone()[0])
    conn.commit()

    cur.execute("""
        SELECT id, number, is_half, slot
        FROM registrations
        WHERE game_id = %s AND user_id = %s AND is_paid = FALSE AND is_nekay = FALSE
        ORDER BY registered_at, slot
    """, (game_id, telegram_id))
    unpaid = cur.fetchall()

    confirmed = []
    remaining = total_balance

    for reg_id, number, is_half, slot in unpaid:
        cost = price_half if is_half else price_full
        if remaining >= cost:
            cur.execute("UPDATE registrations SET is_paid = TRUE WHERE id = %s", (reg_id,))
            remaining -= cost
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
        if remaining >= cost:
            cur.execute("""
                UPDATE registrations SET is_paid = TRUE, is_nekay = FALSE WHERE id = %s
            """, (reg_id,))
            remaining -= cost
            confirmed.append({"number": number, "is_half": is_half, "slot": slot})

    cur.execute("""
        UPDATE user_balance SET balance = %s, updated_at = NOW()
        WHERE game_id = %s AND telegram_id = %s
    """, (remaining, game_id, telegram_id))

    conn.commit()
    cur.close()
    conn.close()
    return {"confirmed": confirmed, "remaining_balance": remaining}


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
        SELECT number, slot
        FROM registrations
        WHERE game_id=%s AND is_paid=FALSE
        ORDER BY number, slot
    """, (game_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = {}
    for number, slot in rows:
        if number not in result:
            result[number] = set()
        result[number].add(slot)
    return [(n, slots) for n, slots in sorted(result.items())]


# ============================================================
# NEKAY
# ============================================================

def mark_nekay(game_id: int, number: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE registrations SET is_nekay=TRUE, is_paid=FALSE
        WHERE game_id=%s AND number=%s
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


def add_winner_balance(game_id: int, telegram_id: int, amount: float):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_balance (game_id, telegram_id, balance)
        VALUES (%s, %s, %s)
        ON CONFLICT (game_id, telegram_id)
        DO UPDATE SET balance = user_balance.balance + %s, updated_at = NOW()
    """, (game_id, telegram_id, amount, amount))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# ADMIN — NEW GAME CLEAR
# ============================================================

def clear_game(game_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM registrations WHERE game_id=%s", (game_id,))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# ADMIN — MANUAL REMOVE & PAY MARK
# ============================================================

def admin_remove_player(game_id: int, number: int, slot: int = None):
    conn = get_conn()
    cur = conn.cursor()
    if slot is None:
        cur.execute("""
            DELETE FROM registrations
            WHERE game_id=%s AND number=%s
        """, (game_id, number))
    else:
        cur.execute("""
            DELETE FROM registrations
            WHERE game_id=%s AND number=%s AND slot=%s
        """, (game_id, number, slot))
    conn.commit()
    cur.close()
    conn.close()


def admin_mark_paid(game_id: int, number: int, slot: int, paid: bool = True):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE registrations SET is_paid=%s
        WHERE game_id=%s AND number=%s AND slot=%s
    """, (paid, game_id, number, slot))
    conn.commit()
    cur.close()
    conn.close()


# ============================================================
# FUZZY MATCH
# ============================================================

def fuzzy_ref_match(ref1: str, ref2: str) -> bool:
    if not ref1 or not ref2:
        return False
    if ref1 == ref2:
        return True

    r1 = ref1.upper()
    r2 = ref2.upper()

    if len(r1) != len(r2):
        return False

    known_confusions = [('5', 'S'), ('0', 'O'), ('1', 'I')]

    def is_known(a, b):
        return any((a == x and b == y) or (a == y and b == x) for x, y in known_confusions)

    known_errors = 0
    unknown_errors = 0

    for c1, c2 in zip(r1, r2):
        if c1 == c2:
            continue
        if is_known(c1, c2):
            known_errors += 1
        else:
            unknown_errors += 1

        if unknown_errors >= 2:
            return False
        if known_errors > 2:
            return False
        if known_errors + unknown_errors > 2:
            return False

    return True


# ============================================================
# TRY MATCH
# ============================================================

def try_match(ref_no: str) -> dict:
    if not ref_no:
        return {"matched": None}

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, ref_no, amount, pay_type FROM sms_payments WHERE matched = FALSE")
    all_sms = cur.fetchall()

    cur.execute("SELECT id, telegram_id, ref_no FROM screenshot_payments WHERE matched = FALSE")
    all_screenshots = cur.fetchall()

    matched_data = None

    for sms_id, sms_ref, amount, pay_type in all_sms:
        for scr_id, telegram_id, scr_ref in all_screenshots:
            if fuzzy_ref_match(sms_ref, scr_ref):
                matched_data = {
                    "telegram_id": telegram_id,
                    "amount": float(amount),
                    "type": pay_type,
                    "refNo": sms_ref,
                    "screenshotRef": scr_ref,
                }
                matched_json = _json.dumps(matched_data)

                cur.execute("""
                    UPDATE sms_payments SET matched = TRUE, matched_data = %s WHERE id = %s
                """, (matched_json, sms_id))

                cur.execute("""
                    UPDATE screenshot_payments SET matched = TRUE, matched_data = %s WHERE id = %s
                """, (matched_json, scr_id))

                conn.commit()
                cur.close()
                conn.close()
                return {"matched": matched_data}

    conn.commit()
    cur.close()
    conn.close()
    return {"matched": None}


# ============================================================
# SMS PAYMENTS
# ============================================================

def save_sms_payment(ref_no: str, amount, pay_type: str, raw_sms: str) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sms_payments (ref_no, amount, pay_type, raw_sms, matched)
        VALUES (%s, %s, %s, %s, FALSE)
        ON CONFLICT (ref_no) DO UPDATE
            SET matched = FALSE
    """, (ref_no, amount, pay_type, raw_sms))
    conn.commit()
    cur.close()
    conn.close()
    return try_match(ref_no)


def get_sms_payment_by_ref(ref_no: str):
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
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO screenshot_payments (telegram_id, ref_no, pay_type, description, matched)
        VALUES (%s, %s, %s, %s, FALSE)
        ON CONFLICT (ref_no) DO UPDATE
            SET matched = FALSE,
                telegram_id = EXCLUDED.telegram_id
    """, (telegram_id, ref_no, pay_type, description))
    conn.commit()
    cur.close()
    conn.close()
    return try_match(ref_no)


def is_ref_matched_already(ref_no: str) -> bool:
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
# WINNER — GET BY PLACE & DEDUCT
# ============================================================

def get_winner_by_place(game_id: int, place: int) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT w.telegram_id, w.user_name, w.prize, ub.balance
        FROM winners w
        LEFT JOIN user_balance ub ON ub.game_id = w.game_id AND ub.telegram_id = w.telegram_id
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
    }


def save_winner(game_id: int, place: int, telegram_id: int, user_name: str, number: int, prize: float):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO winners (game_id, place, telegram_id, user_name, number, prize)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (game_id, place) DO UPDATE
            SET telegram_id=EXCLUDED.telegram_id,
                user_name=EXCLUDED.user_name,
                number=EXCLUDED.number,
                prize=EXCLUDED.prize
    """, (game_id, place, telegram_id, user_name, number, prize))
    conn.commit()
    cur.close()
    conn.close()


def deduct_winner_balance(game_id: int, telegram_id: int, amount: float) -> dict:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE user_balance SET balance = balance - %s, updated_at = NOW()
        WHERE game_id = %s AND telegram_id = %s
        RETURNING balance
    """, (amount, game_id, telegram_id))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return {"new_balance": 0, "nekay_numbers": []}

    new_balance = float(row[0])
    conn.commit()

    unpaid_numbers = []

    if new_balance < 0:
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

        remaining_debt = abs(new_balance)

        for reg_id, number, is_half, slot in paid_regs:
            if remaining_debt <= 0:
                break
            cost = price_half if is_half else price_full
            cur.execute("""
                UPDATE registrations SET is_paid = FALSE, is_nekay = FALSE WHERE id = %s
            """, (reg_id,))
            remaining_debt -= cost
            new_balance += cost
            unpaid_numbers.append(number)

        cur.execute("""
            UPDATE user_balance SET balance = %s, updated_at = NOW()
            WHERE game_id = %s AND telegram_id = %s
        """, (new_balance, game_id, telegram_id))
        conn.commit()

    cur.close()
    conn.close()
    return {"new_balance": new_balance, "nekay_numbers": []}


# ============================================================
# CLEANUP
# ============================================================

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
# USER NUMBERS — cancel_number intent
# ============================================================

def get_user_numbers(game_id: int, user_id: int) -> list:
    """
    የዚሁ user ሁሉም ቁጥሮች ይመልሳል
    returns: [(number, is_half, slot, is_paid), ...]
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT number, is_half, slot, is_paid
        FROM registrations
        WHERE game_id=%s AND user_id=%s
        ORDER BY number, slot
    """, (game_id, user_id))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def user_owns_number(game_id: int, user_id: int, number: int) -> bool:
    """
    User ይሄን ቁጥር ይዞ ወይ?
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM registrations
        WHERE game_id=%s AND user_id=%s AND number=%s
        LIMIT 1
    """, (game_id, user_id, number))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row is not None


def remove_number(game_id: int, user_id: int, number: int) -> bool:
    """
    User ቁጥሩን ይሰርዛል — balance refund ያደርጋል (is_paid=TRUE ከሆነ)
    returns: True ከተሰረዘ, False ከሌለ
    """
    conn = get_conn()
    cur = conn.cursor()

    # ቁጥሩ ለዚህ user ያለ ወይ?
    cur.execute("""
        SELECT id, is_half, slot, is_paid
        FROM registrations
        WHERE game_id=%s AND user_id=%s AND number=%s
        ORDER BY slot
    """, (game_id, user_id, number))
    rows = cur.fetchall()

    if not rows:
        cur.close()
        conn.close()
        return False

    # Price መጀመሪያ ጠይቅ
    cur.execute("SELECT price_full, price_half FROM game_settings WHERE id=%s", (game_id,))
    price_row = cur.fetchone()
    price_full = float(price_row[0] or 0)
    price_half = float(price_row[1] or 0)

    # Paid ከሆነ balance ይመለሳል
    refund = 0.0
    for reg_id, is_half, slot, is_paid in rows:
        if is_paid:
            refund += price_half if is_half else price_full

    # Delete registrations
    cur.execute("""
        DELETE FROM registrations
        WHERE game_id=%s AND user_id=%s AND number=%s
    """, (game_id, user_id, number))

    # Refund balance
    if refund > 0:
        cur.execute("""
            INSERT INTO user_balance (game_id, telegram_id, balance)
            VALUES (%s, %s, %s)
            ON CONFLICT (game_id, telegram_id)
            DO UPDATE SET balance = user_balance.balance + %s, updated_at = NOW()
        """, (game_id, user_id, refund, refund))

    conn.commit()
    cur.close()
    conn.close()
    return True
