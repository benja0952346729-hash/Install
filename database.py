import psycopg2
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASS

def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )

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
    """)
    conn.commit()
    cur.close()
    conn.close()

def save_settings(data: dict):
    conn = get_conn()
    cur = conn.cursor()
    # Deactivate old settings
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
    cols = ["id","total_numbers","numbers_per_person","price_full","price_half",
            "prize_1st","prize_2nd","prize_3rd","payment_info",
            "board_message_id","remaining_message_id","is_active","created_at"]
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
    # Check existing
    cur.execute("""
        SELECT id, is_half, slot FROM registrations
        WHERE game_id=%s AND number=%s ORDER BY slot
    """, (game_id, number))
    existing = cur.fetchall()

    if not existing:
        # Empty slot
        cur.execute("""
            INSERT INTO registrations (game_id, user_id, user_name, number, is_half, slot)
            VALUES (%s, %s, %s, %s, %s, 1)
        """, (game_id, user_id, user_name, number, is_half))
        conn.commit()
        cur.close()
        conn.close()
        return "registered"

    if len(existing) == 1 and existing[0][1] == True and is_half:
        # First person took half, second person takes other half
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
    """Returns dict: number -> list of (user_name, is_half, slot)"""
    rows = get_registrations(game_id)
    result = {}
    for number, user_name, is_half, slot in rows:
        if number not in result:
            result[number] = []
        result[number].append((user_name, is_half, slot))
    return result
