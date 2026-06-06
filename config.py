import os
from dotenv import load_dotenv

load_dotenv(override=True)

# ─── AI API Keys (እስከ 50) ───────────────────────────────────────
API_KEYS = []
for i in range(1, 51):
    key = os.getenv(f"AI_API_KEY_{i}")
    if key:
        API_KEYS.append(key)

BASE_URL = os.getenv("AI_BASE_URL", "https://integrate.api.nvidia.com/v1")
MODEL    = os.getenv("AI_MODEL",    "deepseek-ai/deepseek-r1")

# ─── Database ────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")

# ─── Game Config ─────────────────────────────────────────────────
def get_game_config():
    """ሁሌ fresh ያነባዋል — .env ሲቀየር auto ይሠራል"""
    load_dotenv(override=True)
    return {
        # Board
        "slots_total":        int(os.getenv("SLOTS_TOTAL",        100)),
        "slots_per_person":   int(os.getenv("SLOTS_PER_PERSON",   5)),

        # Prices
        "price_full":         int(os.getenv("PRICE_FULL",         400)),
        "price_half":         int(os.getenv("PRICE_HALF",         200)),

        # Prizes
        "prize_1st":          int(os.getenv("PRIZE_1ST",          5000)),
        "prize_2nd":          int(os.getenv("PRIZE_2ND",          1000)),
        "prize_3rd":          int(os.getenv("PRIZE_3RD",          400)),
        "winners_count":      int(os.getenv("WINNERS_COUNT",      3)),

        # Timing
        "warning_minutes":    int(os.getenv("WARNING_MINUTES",    2)),

        # UI
        "low_slots_threshold": int(os.getenv("LOW_SLOTS_THRESHOLD", 7)),

        # Payment Accounts
        "cbe_account":   os.getenv("CBE_ACCOUNT"),
        "cbe_name":      os.getenv("CBE_NAME"),
        "awash_account": os.getenv("AWASH_ACCOUNT"),
        "dashen_account":os.getenv("DASHEN_ACCOUNT"),
        "tele_birr":     os.getenv("TELE_BIRR"),
    }

# ─── API Rotation ─────────────────────────────────────────────────
_current_key_index = 0

def get_api_key():
    if not API_KEYS:
        raise Exception("❌ API key የለም! .env ላይ AI_API_KEY_1 ጨምር")
    return API_KEYS[_current_key_index]

def rotate_key():
    global _current_key_index
    _current_key_index = (_current_key_index + 1) % len(API_KEYS)
    print(f"🔄 Key {_current_key_index + 1}/{len(API_KEYS)} ላይ ተዛወረ")

def call_ai(messages, system_prompt=None):
    """Rate limit ሲመጣ auto rotate ያደርጋል"""
    from openai import OpenAI

    if system_prompt:
        messages = [{"role": "system", "content": system_prompt}] + messages

    for attempt in range(len(API_KEYS)):
        try:
            client = OpenAI(api_key=get_api_key(), base_url=BASE_URL)
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                max_tokens=4096,
            )
            return response.choices[0].message.content
        except Exception as e:
            err = str(e).lower()
            if "rate limit" in err or "429" in err or "quota" in err:
                print(f"⚠️  Rate limit — key እቀይራለሁ... ({attempt+1}/{len(API_KEYS)})")
                rotate_key()
            else:
                raise e

    raise Exception("❌ ሁሉም keys limit ላይ ናቸው!")
