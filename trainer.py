import random
import json
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from config import get_game_config, DATABASE_URL
from game_logic import Board

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

# ─── Helpers ─────────────────────────────────────────────────────
def random_half_keyword():
    return random.choice(["+", "g", "gm", "gmash", "half", "÷", "ግ", "ግማሽ", "በግማሽ"])

def format_block_request(block, is_half, lang="am"):
    kw = random_half_keyword() if is_half else ""
    styles = [f"{block:02d}{kw}", f"{block}{kw}"]
    if lang == "en":
        styles += [f"{block} take", f"give me {block}"]
    else:
        styles += [f"{block} ያዝ", f"{block:02d} ያዝ"]
    return random.choice(styles)

def display_board(board):
    cfg = get_game_config()
    lines = []
    for i in range(1, cfg["slots_total"] + 1):
        slot = board.slots[i]
        block_start = ((i-1) // cfg["slots_per_person"]) * cfg["slots_per_person"] + 1
        if i == block_start and slot.name:
            mark     = "✅" if slot.paid_main else ""
            reminder = "❓" if slot.reminder  else ""
            if slot.partner:
                pmark = "✅" if slot.paid_partner else ""
                lines.append(f"{i:02d}# {slot.name}{mark}{reminder}+ {slot.partner}{pmark}")
            elif slot.is_half:
                lines.append(f"{i:02d}# {slot.name}{mark}{reminder}+")
            else:
                lines.append(f"{i:02d}# {slot.name}{mark}{reminder}")
        else:
            lines.append(f"{i:02d}#")
    return "\n".join(lines)

def display_remaining(free_blocks, keyword="ቀሪ"):
    return keyword + "\n" + "\n".join(f"{b:02d}" for b in free_blocks)

# ─── Simulate 1 Game ─────────────────────────────────────────────
def simulate_game(game_id):
    board  = Board()
    events = []
    cfg    = get_game_config()
    now    = datetime(2024, 1, 1) + timedelta(days=random.randint(0, 365))

    total_blocks = cfg["slots_total"] // cfg["slots_per_person"]
    used_names   = []
    msg_count    = 0
    board_active = False  # 7 ቁጥር አልፏል?

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
        name    = random.choice(ALL_NAMES)
        lang    = "en" if name in ENGLISH_NAMES else "am"
        is_half = random.random() < 0.25

        if used_names and random.random() < 0.1:
            name = random.choice(used_names)

        partner = None
        if is_half and random.random() < 0.5:
            partner = random.choice(ALL_NAMES)

        success, reason = board.register(block, name, is_half, partner)

        if success:
            used_names.append(name)
            req         = format_block_request(block, is_half, lang)
            free_blocks = board.get_free_blocks()
            remaining   = len(free_blocks)

            # Bot reply
            if remaining == 0:
                bot_reply = "ጨዋታ ተሞልቷል 🙏" if lang == "am" else "Game is full 🙏"
            elif remaining <= cfg["low_slots_threshold"]:
                bot_reply = "እሺ ይፍጠን 🙏" if lang == "am" else "Hurry up! 🙏"
            else:
                bot_reply = random.choice(
                    ["እሺ 🙏 ገቢ", "ቤተሰብ ገቢ 🙏", "ገቢ እንዳይረሳ 🙏"]
                ) if lang == "am" else random.choice(
                    ["Done 🙏 registered", "Got it 🙏"]
                )

            log("registration", {
                "user_request": req, "block": block,
                "name": name, "is_half": is_half,
                "partner": partner, "bot_reply": bot_reply,
                "lang": lang, "remaining_blocks": remaining,
            })

            msg_count += 1

            # ── Board/ቀሪ trigger ──────────────────────────────
            keyword = random.choice(["ቀሪ", "ነቃይ"])

            if remaining == cfg["low_slots_threshold"]:
                # 7 ቁጥር ሲቀር — 1ኛ ጊዜ board + ቀሪ
                board_active = True
                msg_count    = 0
                log("board_with_remaining", {
                    "trigger":           "low_slots",
                    "board":             display_board(board),
                    "remaining":         display_remaining(free_blocks, keyword),
                    "remaining_keyword": keyword,
                    "free_count":        remaining,
                    "bot_action":        "send_board_and_remaining",
                })

            elif board_active:
                # ቀሪ → ሁሌ 1 message ሲመጣ ይሰረዛል
                log("remaining_update", {
                    "trigger":           "slot_taken",
                    "remaining":         display_remaining(free_blocks, keyword),
                    "remaining_keyword": keyword,
                    "bot_action":        "delete_old_remaining_send_new",
                })

                # 4 messages → board ይሰረዛል
                if msg_count >= 4:
                    msg_count = 0
                    log("board_move", {
                        "trigger":           "4_messages",
                        "board":             display_board(board),
                        "remaining":         display_remaining(free_blocks, keyword),
                        "remaining_keyword": keyword,
                        "bot_action":        "delete_old_board_send_new",
                    })

        else:
            log("registration_failed", {
                "block": block, "reason": reason,
                "bot_reply": "ተቀደምክ 🙏" if reason == "taken" else "ይቅርታ 🙏",
            })

        now += timedelta(minutes=random.randint(1, 10))

    # ── 2. Payment ───────────────────────────────────────────────
    for num, slot in board.slots.items():
        if not slot.is_taken:
            continue
        blk = (num - 1) // cfg["slots_per_person"] + 1
        if num != board.get_block_start(blk):
            continue
        if random.random() < 0.8:
            amount = cfg["price_half"] if slot.is_half else cfg["price_full"]
            if slot.partner and random.random() < 0.5:
                amount = cfg["price_half"]
            updated, rem = board.apply_payment(slot.name, amount)
            log("payment", {
                "name": slot.name, "amount": amount,
                "updated_slots": updated, "remaining": rem,
                "bot_reply": f"{slot.name} ✅ ገቢ 🙏" if rem == 0
                             else f"{slot.name} {rem}ብር ቀርቷል ጨምር 🙏",
            })
        now += timedelta(minutes=random.randint(1, 5))

    # ── 3. Unpaid Warning ─────────────────────────────────────────
    unpaid = board.get_unpaid_blocks()
    if unpaid:
        log("unpaid_warning", {
            "unpaid_blocks": unpaid,
            "bot_message":   "⚠️ 2 ደቂቃ ይቀራል! ያልከፈሉ:\n" + "\n".join(unpaid),
        })
        for b_str in unpaid:
            b     = int(b_str.replace("+", ""))
            start = board.get_block_start(b)
            slot  = board.slots[start]
            if random.random() < 0.6:
                amount = cfg["price_half"] if "+" in b_str else cfg["price_full"]
                board.apply_payment(slot.name, amount)
                log("late_payment", {"block": b, "name": slot.name, "amount": amount})
            else:
                for i in range(cfg["slots_per_person"]):
                    board.slots[start + i].__init__(start + i)
                log("slot_removed", {"block": b, "reason": "unpaid timeout"})
        now += timedelta(minutes=2)

    # ── 4. All Paid → መልካም ዕድል ─────────────────────────────────
    log("all_paid_board", {
        "board":       display_board(board),
        "bot_message": "🎰 ዕጣ ማውጫ ሰዓት ደረሰ! መልካም ዕድል 🙏",
        "bot_action":  "send_final_board_keep_forever",
    })

    # ── 5. Winner ────────────────────────────────────────────────
    taken   = [b for b in range(1, total_blocks+1) if not board.is_block_free(b)]
    w_count = min(cfg["winners_count"], len(taken))
    w_blocks= random.sample(taken, w_count)
    prizes  = [cfg["prize_1st"], cfg["prize_2nd"], cfg["prize_3rd"]]
    medals  = ["🥇 1ኛ", "🥈 2ኛ", "🥉 3ኛ"]
    w_names = []

    for rank, blk in enumerate(w_blocks):
        start = board.get_block_start(blk)
        name  = board.slots[start].name
        prize = prizes[rank] if rank < len(prizes) else 0
        w_names.append(name)
        log("winner", {
            "rank": rank+1, "block": blk, "name": name, "prize": prize,
            "bot_message": f"{medals[rank]}: {name} — {prize}ብር",
        })

    # ── 6. Winner Balance ─────────────────────────────────────────
    for rank, (blk, name) in enumerate(zip(w_blocks, w_names)):
        prize   = prizes[rank] if rank < len(prizes) else 0
        sent    = (random.randint(0, prize) // cfg["price_half"]) * cfg["price_half"]
        updated, removed, balance = board.apply_winner_balance(name, prize, sent)
        log("winner_balance", {
            "name": name, "prize": prize,
            "admin_sent": sent, "balance": balance,
            "auto_approved": updated, "auto_removed": removed,
            "admin_message": f"{rank+1}={sent}",
            "note": "✅ ብቻ ይጠፋል — slot/ስም አይጠፋም",
        })

    # ── 7. New Game ───────────────────────────────────────────────
    log("new_game", {
        "bot_message": "🎰 አዲስ ጨዋታ ተጀምሯል! መልካም ዕድል 🙏",
        "bot_action":  "send_new_empty_board",
    })

    return events

# ─── Database ────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(DATABASE_URL)

def setup_db():
    """Table ይፍጠር + አሮጌ data ያጸዳ"""
    print("📦 DB setup...")
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS training_events (
            id         SERIAL PRIMARY KEY,
            game_id    INTEGER,
            event_type TEXT,
            data       JSONB,
            timestamp  TIMESTAMP
        )
    """)
    # አሮጌ data ጥፋ — duplicate እንዳይሆን
    cur.execute("TRUNCATE TABLE training_events RESTART IDENTITY;")
    conn.commit()
    cur.close()
    conn.close()
    print("✅ DB ready — አሮጌ data ጠፍቷል!")

def save_events(events):
    if not events:
        return
    conn = get_conn()
    cur  = conn.cursor()
    psycopg2.extras.execute_values(
        cur,
        "INSERT INTO training_events (game_id, event_type, data, timestamp) VALUES %s",
        [(e["game_id"], e["event_type"],
          json.dumps(e["data"], ensure_ascii=False),
          e["timestamp"]) for e in events]
    )
    conn.commit()
    cur.close()
    conn.close()

# ─── Main ────────────────────────────────────────────────────────
def run_training(num_games=5000):
    print(f"🚀 {num_games} games simulation ጀምሯል...")
    setup_db()

    total_events = 0
    chunk_events = []
    CHUNK        = 100  # 100 games አንድ ጊዜ → DB

    for game_id in range(1, num_games + 1):
        events = simulate_game(game_id)
        chunk_events.extend(events)
        total_events += len(events)

        if game_id % CHUNK == 0:
            save_events(chunk_events)
            chunk_events = []
            print(f"✅ {game_id}/{num_games} ({int(game_id/num_games*100)}%) — {total_events} events", flush=True)

    # ቀሪ
    if chunk_events:
        save_events(chunk_events)

    print(f"\n🎉 ተጠናቋል! {num_games} games → {total_events} events → PostgreSQL")
    print(f"⏰ {datetime.now().strftime('%H:%M:%S')}")

if __name__ == "__main__":
    run_training(500)
