import os

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "0").split(",") if x.strip()]
DATABASE_URL = os.environ.get("DATABASE_URL")
GROUP_ID = int(os.environ.get("GROUP_ID", "0"))
GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", str(os.environ.get("GROUP_ID", "0")))
