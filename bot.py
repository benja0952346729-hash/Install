import asyncio
import logging
import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from ai_client import call_ai
from board import load_board, save_board, reset_board, board_to_json_str, parse_ai_response

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")

# README ሲጀምር አንድ ጊዜ ያነባዋል
def load_readme() -> str:
    for name in ["README.md", "readme.md", "Readme.md"]:
        if os.path.exists(name):
            with open(name, "r", encoding="utf-8") as f:
                return f.read()
    raise FileNotFoundError("README.md not found!")

README = load_readme()
logger.info("README.md loaded successfully.")

SYSTEM_PROMPT = f"""
{README}

---

## 🤖 Response Format (REQUIRED)

ሁሌ ሁለት ክፍል ይስጥ:

1. Updated board JSON (```json ``` ውስጥ)
2. Reply text (group ላይ የሚላከው)

ምሳሌ:
```json
{{
  "slots": {{
    "06": {{"name": "አበበ", "type": "full", "paid1": false, "paid2": false, "partner": null}}
  }},
  "game_active": true
}}
```
ቤተሰብ ገቢ! 🙏

---

Rules:
- JSON ውስጥ የተቀየሩ slots ብቻ ይመልስ (ሙሉ board አይደለም)
- Board text (01# አበበ format) ሲጠይቁ ብቻ ስጥ
- Reply አጭር ይሁን
- User ቋንቋ ተቀበልና ተመሳሳይ ቋንቋ ምለስ
"""


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    user = message.from_user
    first_name = user.first_name if user else "User"
    text = message.text.strip()

    # Board load
    board = load_board()
    board_json = board_to_json_str(board)

    user_input = f"""
User: {first_name}
Message: {text}

Current Board JSON:
{board_json}
"""

    logger.info(f"[{first_name}]: {text}")

    try:
        response = await call_ai(SYSTEM_PROMPT, user_input)
        logger.info(f"AI Response: {response[:200]}...")

        updated_slots, reply_text = parse_ai_response(response)

        # Board update
        if updated_slots and "slots" in updated_slots:
            board["slots"].update(updated_slots["slots"])
            if "game_active" in updated_slots:
                board["game_active"] = updated_slots["game_active"]
            save_board(board)
            logger.info("Board updated.")

        # New game reset
        if updated_slots and updated_slots.get("new_game"):
            reset_board()
            logger.info("New game started — board reset.")

        if reply_text:
            await message.reply_text(reply_text)

    except Exception as e:
        logger.error(f"AI Error: {e}")
        await message.reply_text("ይቅርታ ትንሽ ችግር ተፈጥሯል። እንደገና ሞክር 🙏")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
