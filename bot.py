import logging
import os
import json
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from ai_client import call_ai
from board import load_board, save_board, reset_board, board_to_json_str, parse_ai_response

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
STATE_FILE = "state.json"


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"board_message_id": None}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


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
2. Reply text (group ላይ የሚላከው — አጭር)

ምሳሌ:
```json
{{
  "slots": {{
    "06": {{"name": "አበበ", "type": "full", "paid1": false, "paid2": false, "partner": null}}
  }},
  "game_active": true,
  "send_board": true,
  "new_game": false
}}
```
ቤተሰብ ገቢ! 🙏

---

## JSON Fields:
- `slots` → የተቀየሩ slots ብቻ
- `send_board` → true ከሆነ bot updated board group ላይ ይልካዋል (አሮጌውን ይሰርዛዋል)
- `new_game` → true ከሆነ አዲስ ባዶ game ይጀምራዋል
- `game_active` → game status

## Rules:
- Reply አጭር ይሁን
- User ቋንቋ ተቀበልና ተመሳሳይ ቋንቋ ምለስ
- send_board መቼ true እንደሚሆን README ይነግርሃል
"""


def build_board_text(board: dict) -> str:
    slots = board.get("slots", {})
    lines = []
    for block_start in range(1, 101, 5):
        for i in range(block_start, block_start + 5):
            slot_key = str(i).zfill(2)
            slot = slots.get(slot_key, {})
            name = slot.get("name")
            if not name:
                lines.append(f"{slot_key}#")
            else:
                paid1 = slot.get("paid1", False)
                paid2 = slot.get("paid2", False)
                partner = slot.get("partner")
                stype = slot.get("type", "full")
                if stype == "full":
                    check = "✅" if paid1 else ""
                    lines.append(f"{slot_key}# {name}{check}")
                else:
                    check1 = "✅" if paid1 else ""
                    if partner:
                        check2 = "✅" if paid2 else ""
                        lines.append(f"{slot_key}# {name}{check1}+{partner}{check2}")
                    else:
                        lines.append(f"{slot_key}# {name}{check1}+")
        lines.append("")
    return "\n".join(lines).strip()


NEW_GAME_HEADER = os.getenv("NEW_GAME_HEADER", """በ 400 ብር 5 ቁጥሮችን በተከታታይ በመያዝ እድሎን ይሞክሩ ለ 20 ሰው ብቻ ፈጣን ዕድል መልካም ዕድል

መደብ 👉በ 4️⃣0️⃣0️⃣ ብር
       👉ግማሽ 2️⃣0️⃣0️⃣ ብር

1ኛ 🥇5️⃣,0️⃣0️⃣0️⃣ ብር
2ኛ 🥈1000
3ኛ 🥇400

""")

NEW_GAME_FOOTER = os.getenv("NEW_GAME_FOOTER", """

CBE 1000641057146 biniyam dawit
አዋሽ  01335630641400
ዳሽን  5389857825011
ቴሌ ብር 0952346729""")


async def send_board(app: Application, board: dict, is_new_game: bool = False):
    if not GROUP_ID:
        logger.warning("GROUP_ID not set")
        return

    state = load_state()
    board_text = build_board_text(board)
    text = (NEW_GAME_HEADER + board_text + NEW_GAME_FOOTER) if is_new_game else board_text

    # አሮጌ board ይሰርዛዋል
    if state.get("board_message_id"):
        try:
            await app.bot.delete_message(chat_id=GROUP_ID, message_id=state["board_message_id"])
        except Exception:
            pass

    # አዲስ board ይልካዋል
    msg = await app.bot.send_message(chat_id=GROUP_ID, text=text)
    state["board_message_id"] = msg.message_id
    save_state(state)
    logger.info(f"Board sent (message_id={msg.message_id})")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    user = message.from_user
    first_name = user.first_name if user else "User"
    text = message.text.strip()

    board = load_board()
    board_json = board_to_json_str(board)

    user_input = f"""User: {first_name}
Message: {text}

Current Board JSON:
{board_json}"""

    logger.info(f"[{first_name}]: {text}")

    try:
        response = await call_ai(SYSTEM_PROMPT, user_input)
        logger.info(f"AI Response: {response[:300]}...")

        updated_data, reply_text = parse_ai_response(response)

        # Board JSON update
        if updated_data and "slots" in updated_data:
            board["slots"].update(updated_data["slots"])
            if "game_active" in updated_data:
                board["game_active"] = updated_data["game_active"]
            save_board(board)

        # New game
        if updated_data and updated_data.get("new_game"):
            board = reset_board()
            await send_board(context.application, board, is_new_game=True)
        # Board refresh
        elif updated_data and updated_data.get("send_board"):
            await send_board(context.application, board)

        if reply_text:
            await message.reply_text(reply_text)

    except Exception as e:
        logger.error(f"AI Error: {e}")
        await message.reply_text("ይቅርታ ትንሽ ችግር ተፈጥሯል። እንደገና ሞክር 🙏")


async def post_init(app: Application):
    board = load_board()
    slots = board.get("slots", {})
    has_game = any(s.get("name") for s in slots.values())

    if has_game:
        logger.info("Existing game — resending board.")
        await send_board(app, board)
    else:
        logger.info("No game — starting new game.")
        board = reset_board()
        await send_board(app, board, is_new_game=True)


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
