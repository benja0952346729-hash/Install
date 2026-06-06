import random
import json
import requests
from datetime import datetime, timedelta
from config import get_game_config, DATABASE_URL
from game_logic import Board, parse_request

cfg = get_game_config()

# ─── Sample Names ────────────────────────────────────────────────
AMHARIC_NAMES = [
    "አበበ", "አየለ", "ከበደ", "አልማዝ", "ሰላም", "ብርሃን", "ዮሃንስ", "ሄኖክ",
    "ናትናኤል", "ሚካኤል", "ሩት", "ማርያም", "ፍቅር", "ተወልደ", "ዳዊት", "ሳሙኤል",
    "እስቲፋኖስ", "ቤዛዊት", "ሙሉወርቅ", "ትዕግስት", "ፀጋዬ", "ገብሩ", "አስቴር",
    "ሕይወት", "ዘሪቱ", "ቃልኪዳን", "ኤፍሬም", "ቢኒያም", "ስምረት", "ዲና"
]

ENGLISH_NAMES = [
    "Abel", "Yonas", "Miki", "Sara", "Helen", "Biruk", "Nati", "Sam",
    "John", "Mary", "Alex", "Liya", "Eden", "Soli", "Bini"
]

ALL_NAMES = AMHARIC_NAMES + ENGLISH_NAMES

# ─── Request Styles ──────────────────────────────────────────────
def random_half_keyword():
    return random.choice(["+", "g", "gm", "gmash", "half", "÷", "ግ", "ግማሽ", "በግማሽ"])

def random_full_keyword():
    return random.choice(["ሙሉ", "mulu", "bemulu", "full", ""])

def format_block_request(block, is_half, lang="am"):
    """ሰው እንዴት ቁጥር እንደሚጠይቅ simulate"""
    sep = random.choice([" ", ",", "/"])
    kw  = random_half_keyword() if is_half else ""

    styles = [
        f"{block:02d}{kw}",
        f"{block}{kw}",
        f"{block:02d} {kw}".strip(),
    ]
    if lang == "en":
        styles += [f"{block} take", f"give me {block}"]
    else:
        styles += [f"{block} ያዝ", f"{block:02d} ያዝ"]

    return random.choice(styles)

# ─── Simulate 1 Game ─────────────────────────────────────────────
def simulate_game(game_id):
    board    = Board()
    events   = []
    cfg      = get_game_config()
    now      = datetime(2024, 1, 1) + timedelta(days=random.randint(0, 365))

    total_blocks = cfg["slots_total"] // cfg["slots_per_person"]
    used_names   = []

    def log(event_type, data):
        events.append({
            "game_id":    game_id,
            "event_type": event_type,
            "data":       data,
            "timestamp":  now.isoformat(),
        })

    # ── 1. Registration ──────────────────────────────────────────
    blocks = list(range(1, total_blocks + 1))
    random.shuffle(blocks)

    for block in blocks:
        name = random.choice(ALL_NAMES)
        lang = "en" if name in ENGLISH_NAMES else "am"
        is_half = random.random() < 0.25  # 25% ግማሽ

        # ተመሳሳይ ስም scenario
        if used_names and random.random() < 0.1:
            name = random.choice(used_names)

        # አጋር scenario
        partner = None
        if is_half and random.random() < 0.5:
            partner = random.choice(ALL_NAMES)

        success, reason = board.register(block, name, is_half, partner)

        if success:
            used_names.append(name)
            req = format_block_request(block, is_half, lang)

            # Bot response
            remaining_blocks = sum(1 for b in range(1, total_blocks+1) if board.is_block_free(b))
            if remaining_blocks == 0:
                bot_reply = "ተሞልቷል! ✅" if lang == "en" else "ጨዋታ ተሞልቷል 🙏"
            elif remaining_blocks <= cfg["low_slots_threshold"]:
                bot_reply = "Hurry up! 🙏" if lang == "en" else "እሺ ይፍጠን 🙏"
            else:
                bot_reply = random.choice([
                    "እሺ 🙏 ገቢ", "ቤተሰብ ገቢ 🙏", "ገቢ እንዳይረሳ 🙏"
                ]) if lang == "am" else random.choice([
                    "Done 🙏 registered", "Got it 🙏"
                ])

            log("registration", {
                "user_request": req,
                "block": block,
                "name": name,
                "is_half": is_half,
                "partner": partner,
                "bot_reply": bot_reply,
                "lang": lang,
            })

        else:
            log("registration_failed", {
                "block": block,
                "reason": reason,
                "bot_reply": "ተቀደምክ 🙏" if reason == "taken" else "ይቅርታ 🙏",
            })

        now += timedelta(minutes=random.randint(1, 10))

    # ── 2. Payment ───────────────────────────────────────────────
    for num, slot in board.slots.items():
        if not slot.is_taken:
            continue
        block = (num - 1) // cfg["slots_per_person"] + 1
        if num != board.get_block_start(block):
            continue

        # 80% ይከፍላሉ
        if random.random() < 0.8:
            amount = cfg["price_half"] if slot.is_half else cfg["price_full"]
            # አጋር ካለ አንዳንዴ ተናጠል ይከፍላሉ
            if slot.partner and random.random() < 0.5:
                amount = cfg["price_half"]

            updated, remaining = board.apply_payment(slot.name, amount)

            bot_reply = ""
            if remaining == 0:
                bot_reply = f"{slot.name} ✅ ገቢ 🙏"
            else:
                bot_reply = f"{slot.name} {remaining}ብር ቀርቷል ጨምር 🙏"

            log("payment", {
                "name": slot.name,
                "amount": amount,
                "updated_slots": updated,
                "remaining": remaining,
                "bot_reply": bot_reply,
            })

        now += timedelta(minutes=random.randint(1, 5))

    # ── 3. Unpaid Warning ─────────────────────────────────────────
    unpaid = board.get_unpaid_blocks()
    if unpaid:
        warning_text = "⚠️ 2 ደቂቃ ይቀራል! ያልከፈሉ:\n" + "\n".join(unpaid)
        log("unpaid_warning", {
            "unpaid_blocks": unpaid,
            "bot_message": warning_text,
        })

        # አንዳንዶቹ ይከፍላሉ፣ አንዳንዶቹ አይከፍሉም
        for b_str in unpaid:
            b = int(b_str.replace("+", ""))
            start = board.get_block_start(b)
            slot  = board.slots[start]
            if random.random() < 0.6:
                amount = cfg["price_half"] if "+" in b_str else cfg["price_full"]
                updated, _ = board.apply_payment(slot.name, amount)
                log("late_payment", {"block": b, "name": slot.name, "amount": amount})
            else:
                # Slot ይጠፋል
                for i in range(cfg["slots_per_person"]):
                    board.slots[start + i].__init__(start + i)
                log("slot_removed", {"block": b, "reason": "unpaid timeout"})

        now += timedelta(minutes=2)

    # ── 4. Winner Selection ──────────────────────────────────────
    taken_blocks = [
        b for b in range(1, total_blocks + 1)
        if not board.is_block_free(b)
    ]

    winners_count = min(cfg["winners_count"], len(taken_blocks))
    winner_blocks = random.sample(taken_blocks, winners_count)
    prizes        = [cfg["prize_1st"], cfg["prize_2nd"], cfg["prize_3rd"]]
    winner_names  = []

    for rank, block in enumerate(winner_blocks):
        start = board.get_block_start(block)
        name  = board.slots[start].name
        prize = prizes[rank] if rank < len(prizes) else 0
        winner_names.append(name)

        log("winner", {
            "rank": rank + 1,
            "block": block,
            "name": name,
            "prize": prize,
        })

    # ── 5. Winner Balance ─────────────────────────────────────────
    for rank, (block, name) in enumerate(zip(winner_blocks, winner_names)):
        prize      = prizes[rank] if rank < len(prizes) else 0
        sent       = random.randint(0, prize)  # admin ስንት እንደሚልክ random
        sent       = (sent // cfg["price_half"]) * cfg["price_half"]  # round to 200

        updated, removed, balance = board.apply_winner_balance(name, prize, sent)

        log("winner_balance", {
            "name": name,
            "prize": prize,
            "admin_sent": sent,
            "balance": balance,
            "auto_approved": updated,
            "auto_removed": removed,
            "admin_message": f"{rank+1}={sent}",
        })

    # ── 6. New Board ─────────────────────────────────────────────
    log("new_board", {
        "message": "አዲስ ጨዋታ ተጀምሯል 🎰",
        "board": board.display(),
    })

    return events

# ─── Neon HTTP API ───────────────────────────────────────────────
def get_neon_http_url():
    """postgresql:// → https:// Neon HTTP endpoint"""
    url = DATABASE_URL
    url = url.replace("postgresql://", "https://")
    url = url.replace("postgres://", "https://")
    # extract host
    parts = url.split("@")
    creds = parts[0].replace("https://", "")
    host_path = parts[1].split("/")[0]
    db = parts[1].split("/")[1].split("?")[0]
    user, password = creds.split(":")
    return f"https://{host_path}/sql", user, password, db

def neon_query(sql, params=None):
    """Neon HTTP API ይጠቀማል"""
    endpoint, user, password, db = get_neon_http_url()
    payload = {"query": sql, "params": params or []}
    resp = requests.post(
        endpoint,
        json=payload,
        auth=(user, password),
        headers={"Content-Type": "application/json"},
        timeout=30
    )
    return resp.json()

def create_table():
    neon_query("""
        CREATE TABLE IF NOT EXISTS training_events (
            id SERIAL PRIMARY KEY,
            game_id INTEGER,
            event_type TEXT,
            data JSONB,
            timestamp TIMESTAMP
        )
    """)

def save_events(events):
    for e in events:
        neon_query(
            "INSERT INTO training_events (game_id, event_type, data, timestamp) VALUES ($1, $2, $3, $4)",
            [e["game_id"], e["event_type"], json.dumps(e["data"], ensure_ascii=False), e["timestamp"]]
        )

# ─── Main ────────────────────────────────────────────────────────
def run_training(num_games=5000):
    print(f"🚀 {num_games} games simulation ጀምሯል...")

    create_table()
    total_events = 0

    for game_id in range(1, num_games + 1):
        events = simulate_game(game_id)
        save_events(events)
        total_events += len(events)

        if game_id % 500 == 0:
            print(f"✅ {game_id}/{num_games} games — {total_events} events")

    print(f"\n🎉 ተጠናቋል! {num_games} games, {total_events} events → PostgreSQL")

if __name__ == "__main__":
    run_training(5000)
