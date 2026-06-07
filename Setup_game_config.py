"""
Repo 1 ላይ ይሰራል — game_config table DB ላይ ያስቀምጣል።
trainer.py ከመሩጠቱ በፊት አንድ ጊዜ ብቻ ሩጡ።
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv(override=True)
DATABASE_URL = os.getenv("DATABASE_URL")

def setup_game_config():
    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor()

    # Table create
    cur.execute("""
        CREATE TABLE IF NOT EXISTS game_config (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)

    # Default values insert (already exists → skip)
    configs = [
        ("slots_total",         os.getenv("SLOTS_TOTAL",         "100")),
        ("slots_per_person",    os.getenv("SLOTS_PER_PERSON",    "5")),
        ("price_full",          os.getenv("PRICE_FULL",          "400")),
        ("price_half",          os.getenv("PRICE_HALF",          "200")),
        ("prize_1st",           os.getenv("PRIZE_1ST",           "5000")),
        ("prize_2nd",           os.getenv("PRIZE_2ND",           "1000")),
        ("prize_3rd",           os.getenv("PRIZE_3RD",           "400")),
        ("winners_count",       os.getenv("WINNERS_COUNT",       "3")),
        ("warning_minutes",     os.getenv("WARNING_MINUTES",     "2")),
        ("low_slots_threshold", os.getenv("LOW_SLOTS_THRESHOLD", "7")),
        ("cbe_account",         os.getenv("CBE_ACCOUNT",         "")),
        ("cbe_name",            os.getenv("CBE_NAME",            "")),
        ("awash_account",       os.getenv("AWASH_ACCOUNT",       "")),
        ("dashen_account",      os.getenv("DASHEN_ACCOUNT",      "")),
        ("tele_birr",           os.getenv("TELE_BIRR",           "")),
    ]

    for key, value in configs:
        cur.execute("""
            INSERT INTO game_config (key, value)
            VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """, (key, value))

    conn.commit()
    cur.close()
    conn.close()
    print("✅ game_config table ready!")
    print("📋 Config ያለው:")
    for k, v in configs:
        print(f"  {k}: {v}")

if __name__ == "__main__":
    setup_game_config()
