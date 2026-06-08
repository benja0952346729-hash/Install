import os

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [int(os.environ.get("ADMIN_ID", "0"))]
DATABASE_URL = os.environ.get("DATABASE_URL")
GROUP_ID = int(os.environ.get("GROUP_ID", "0"))
