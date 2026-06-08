import json
import os
import re

BOARD_FILE = "board.json"

EMPTY_BOARD = {str(i).zfill(2): {"name": None, "type": None, "paid1": False, "paid2": False, "partner": None}
               for i in range(1, 101)}

def load_board() -> dict:
    if os.path.exists(BOARD_FILE):
        with open(BOARD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"slots": EMPTY_BOARD.copy(), "game_active": True}

def save_board(board: dict):
    with open(BOARD_FILE, "w", encoding="utf-8") as f:
        json.dump(board, f, ensure_ascii=False, indent=2)

def reset_board():
    board = {"slots": EMPTY_BOARD.copy(), "game_active": True}
    save_board(board)
    return board

def board_to_json_str(board: dict) -> str:
    return json.dumps(board, ensure_ascii=False)

def parse_ai_response(response: str) -> tuple[dict | None, str]:
    """
    AI response ከ JSON እና reply text ለያያቸዋል።
    Returns: (updated_board_or_None, reply_text)
    """
    # JSON block ይፈልጋዋል ```json ... ``` ወይም { ... }
    json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
    if json_match:
        json_str = json_match.group(1)
        reply = response.replace(json_match.group(0), "").strip()
    else:
        # Raw JSON ይፈልጋዋል
        json_match = re.search(r'(\{[\s\S]*\})', response)
        if json_match:
            json_str = json_match.group(1)
            reply = response.replace(json_match.group(0), "").strip()
        else:
            return None, response.strip()

    try:
        board = json.loads(json_str)
        return board, reply
    except json.JSONDecodeError:
        return None, response.strip()
