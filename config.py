import os

# ============================================================
# BOT TOKEN
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# ============================================================
# MAIN ADMINS — እስከ 5 ይቻላል
# ============================================================
ADMIN_IDS = [
    int(x.strip())
    for x in os.environ.get("ADMIN_IDS", "0").split(",")
    if x.strip()
][:5]

# ============================================================
# DATABASE URLs — 4 DB rotation
# ============================================================
DATABASE_URLS = [
    url.strip()
    for url in [
        os.environ.get("DATABASE_URL_1") or os.environ.get("DATABASE_URL"),
        os.environ.get("DATABASE_URL_2"),
        os.environ.get("DATABASE_URL_3"),
        os.environ.get("DATABASE_URL_4"),
    ]
    if url and url.strip()
]

# Backward compat
DATABASE_URL = DATABASE_URLS[0] if DATABASE_URLS else None

# DB row limit before rotating (ምን ያህል rows ሲሞላ ይዞራል)
DB_ROW_LIMIT = int(os.environ.get("DB_ROW_LIMIT", "10000"))

# ============================================================
# GROQ API KEYS — እስከ 10 ይቻላል (circular rotation 1→10→1)
# ============================================================
GROQ_API_KEYS = [
    key.strip()
    for key in [
        os.environ.get(f"GROQ_API_KEY_{i}") or (os.environ.get("GROQ_API_KEY") if i == 1 else None)
        for i in range(1, 11)
    ]
    if key and key.strip()
]

# ============================================================
# GROUP — Legacy (single group backward compat)
# ============================================================
GROUP_ID = int(os.environ.get("GROUP_ID", "0"))
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", str(os.environ.get("GROUP_ID", "0")))
