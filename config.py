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

DATABASE_URL = DATABASE_URLS[0] if DATABASE_URLS else None
DB_ROW_LIMIT = int(os.environ.get("DB_ROW_LIMIT", "10000"))

# ============================================================
# TELEGRAM API — Telethon ለ Userbot
# ============================================================
TELEGRAM_API_ID = int(os.environ.get("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "")

# ============================================================
# GROQ API KEYS — እስከ 10 ይቻላል
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
# NVIDIA API KEYS — እስከ 10 ይቻላል
# ============================================================
NVIDIA_API_KEYS = [
    key.strip()
    for key in [
        os.environ.get(f"NVIDIA_API_KEY_{i}") or (os.environ.get("NVIDIA_API_KEY") if i == 1 else None)
        for i in range(1, 11)
    ]
    if key and key.strip()
]

# ============================================================
# JINA API KEYS — እስከ 10 ይቻላል
# ============================================================
JINA_API_KEYS = [
    key.strip()
    for key in [
        os.environ.get(f"JINA_API_KEY_{i}") or (os.environ.get("JINA_API_KEY") if i == 1 else None)
        for i in range(1, 11)
    ]
    if key and key.strip()
]

# ============================================================
# GROUP — Legacy
# ============================================================
GROUP_ID = int(os.environ.get("GROUP_ID", "0"))
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", str(os.environ.get("GROUP_ID", "0")))
