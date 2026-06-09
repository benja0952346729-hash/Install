import re
import random
from rapidfuzz import fuzz

# ================================================================
# AMHARIC NORMALIZER — Fidel Family
# ================================================================

FIDEL_MAP = {
    # ሀ ቤተሰብ
    "ሀ": "ሀ", "ሁ": "ሀ", "ሂ": "ሀ", "ሃ": "ሀ", "ሄ": "ሀ", "ህ": "ሀ", "ሆ": "ሀ",
    # ለ ቤተሰብ
    "ለ": "ለ", "ሉ": "ለ", "ሊ": "ለ", "ላ": "ለ", "ሌ": "ለ", "ል": "ለ", "ሎ": "ለ",
    # ሐ ቤተሰብ
    "ሐ": "ሀ", "ሑ": "ሀ", "ሒ": "ሀ", "ሓ": "ሀ", "ሔ": "ሀ", "ሕ": "ሀ", "ሖ": "ሀ",
    # መ ቤተሰብ
    "መ": "መ", "ሙ": "መ", "ሚ": "መ", "ማ": "መ", "ሜ": "መ", "ም": "መ", "ሞ": "መ",
    # ሰ ቤተሰብ
    "ሰ": "ሰ", "ሱ": "ሰ", "ሲ": "ሰ", "ሳ": "ሰ", "ሴ": "ሰ", "ስ": "ሰ", "ሶ": "ሰ",
    # ሸ ቤተሰብ
    "ሸ": "ሸ", "ሹ": "ሸ", "ሺ": "ሸ", "ሻ": "ሸ", "ሼ": "ሸ", "ሽ": "ሸ", "ሾ": "ሸ",
    # ቀ ቤተሰብ
    "ቀ": "ቀ", "ቁ": "ቀ", "ቂ": "ቀ", "ቃ": "ቀ", "ቄ": "ቀ", "ቅ": "ቀ", "ቆ": "ቀ",
    # ቈ ቤተሰብ
    "ቈ": "ቀ", "ቊ": "ቀ", "ቋ": "ቀ", "ቌ": "ቀ", "ቍ": "ቀ",
    # በ ቤተሰብ
    "በ": "በ", "ቡ": "በ", "ቢ": "በ", "ባ": "በ", "ቤ": "በ", "ብ": "በ", "ቦ": "በ",
    # ተ ቤተሰብ
    "ተ": "ተ", "ቱ": "ተ", "ቲ": "ተ", "ታ": "ተ", "ቴ": "ተ", "ት": "ተ", "ቶ": "ተ",
    # ቸ ቤተሰብ
    "ቸ": "ቸ", "ቹ": "ቸ", "ቺ": "ቸ", "ቻ": "ቸ", "ቼ": "ቸ", "ች": "ቸ", "ቾ": "ቸ",
    # ነ ቤተሰብ
    "ነ": "ነ", "ኑ": "ነ", "ኒ": "ነ", "ና": "ነ", "ኔ": "ነ", "ን": "ነ", "ኖ": "ነ",
    # ኘ ቤተሰብ
    "ኘ": "ነ", "ኙ": "ነ", "ኚ": "ነ", "ኛ": "ነ", "ኜ": "ነ", "ኝ": "ነ", "ኞ": "ነ",
    # አ ቤተሰብ
    "አ": "አ", "ኡ": "አ", "ኢ": "አ", "ኣ": "አ", "ኤ": "አ", "እ": "አ", "ኦ": "አ",
    # ከ ቤተሰብ
    "ከ": "ከ", "ኩ": "ከ", "ኪ": "ከ", "ካ": "ከ", "ኬ": "ከ", "ክ": "ከ", "ኮ": "ከ",
    # ወ ቤተሰብ
    "ወ": "ወ", "ዉ": "ወ", "ዊ": "ወ", "ዋ": "ወ", "ዌ": "ወ", "ው": "ወ", "ዎ": "ወ",
    # የ ቤተሰብ
    "የ": "የ", "ዩ": "የ", "ዪ": "የ", "ያ": "የ", "ዬ": "የ", "ይ": "የ", "ዮ": "የ",
    # ደ ቤተሰብ
    "ደ": "ደ", "ዱ": "ደ", "ዲ": "ደ", "ዳ": "ደ", "ዴ": "ደ", "ድ": "ደ", "ዶ": "ደ",
    # ጀ ቤተሰብ
    "ጀ": "ጀ", "ጁ": "ጀ", "ጂ": "ጀ", "ጃ": "ጀ", "ጄ": "ጀ", "ጅ": "ጀ", "ጆ": "ጀ",
    # ገ ቤተሰብ
    "ገ": "ገ", "ጉ": "ገ", "ጊ": "ገ", "ጋ": "ገ", "ጌ": "ገ", "ግ": "ገ", "ጎ": "ገ",
    # ጠ ቤተሰብ
    "ጠ": "ጠ", "ጡ": "ጠ", "ጢ": "ጠ", "ጣ": "ጠ", "ጤ": "ጠ", "ጥ": "ጠ", "ጦ": "ጠ",
    # ጰ ቤተሰብ
    "ጰ": "ጰ", "ጱ": "ጰ", "ጲ": "ጰ", "ጳ": "ጰ", "ጴ": "ጰ", "ጵ": "ጰ", "ጶ": "ጰ",
    # ጸ ቤተሰብ
    "ጸ": "ጸ", "ጹ": "ጸ", "ጺ": "ጸ", "ጻ": "ጸ", "ጼ": "ጸ", "ጽ": "ጸ", "ጾ": "ጸ",
    # ፀ ቤተሰብ (= ጸ)
    "ፀ": "ጸ", "ፁ": "ጸ", "ፂ": "ጸ", "ፃ": "ጸ", "ፄ": "ጸ", "ፅ": "ጸ", "ፆ": "ጸ",
    # ፈ ቤተሰብ
    "ፈ": "ፈ", "ፉ": "ፈ", "ፊ": "ፈ", "ፋ": "ፈ", "ፌ": "ፈ", "ፍ": "ፈ", "ፎ": "ፈ",
    # ፐ ቤተሰብ
    "ፐ": "ፐ", "ፑ": "ፐ", "ፒ": "ፐ", "ፓ": "ፐ", "ፔ": "ፐ", "ፕ": "ፐ", "ፖ": "ፐ",
    # ዘ ቤተሰብ
    "ዘ": "ዘ", "ዙ": "ዘ", "ዚ": "ዘ", "ዛ": "ዘ", "ዜ": "ዘ", "ዝ": "ዘ", "ዞ": "ዘ",
    # ዠ ቤተሰብ
    "ዠ": "ዠ", "ዡ": "ዠ", "ዢ": "ዠ", "ዣ": "ዠ", "ዤ": "ዠ", "ዥ": "ዠ", "ዦ": "ዠ",
    # ፘ ቤተሰብ
    "ሠ": "ሰ", "ሡ": "ሰ", "ሢ": "ሰ", "ሣ": "ሰ", "ሤ": "ሰ", "ሥ": "ሰ", "ሦ": "ሰ",
}

def normalize_amharic(text: str) -> str:
    """Fidel family normalization — ሁሀሂሃሄህሆ → ሁሉም ሀ"""
    return "".join(FIDEL_MAP.get(ch, ch) for ch in text)


# ================================================================
# LATIN → AMHARIC KEYWORD MAP
# ================================================================

LATIN_TO_AMHARIC = {
    # Booking
    "yaz": "ያዝ", "yazat": "ያዛት", "yazachew": "ያዛቸው",
    "tsafligni": "ፃፍልኝ", "tsaf": "ፃፍ", "yazligni": "ያዝልኝ",
    "mezgib": "መዝግብ", "mezgibat": "መዝግባት", "mezgibligni": "መዝግብልኝ",
    # ቀሪ
    "qeri": "ቀሪ", "qitr": "ቁጥር", "min ale": "ምን አለ",
    "sint qere": "ስንት ቀረ", "sint ale": "ስንት አለ",
    "qeri ale": "ቀሪ አለ", "qitr ale": "ቁጥር አለ",
    "yalteyaze": "ያልተያዘ", "yalteyazun": "ያልተያዙ",
    # ነቃይ
    "nekay": "ነቃይ", "tenekay": "ተነቃይ", "nkay": "ነቃይ",
    "nekay ale": "ነቃይ አለ", "nekay zerzir": "ነቃይ ዘርዝር",
    "nekay neger": "ነቃይ ንገር", "nekay lak": "ነቃይ ላክ",
    "nekayoch": "ነቃዮች", "mishit ale": "ሚሸጥ አለ",
    # ሁሉም
    "hulunm teyazuwal": "ሁሉም ተይዘዋል",
    "hulunm teyaze": "ሁሉም ተያዘ",
    "hulunm alteyazum": "ሁሉም አልተያዙም",
    # ቀሪ ላክ
    "qeri lak": "ቀሪ ላክ", "qitr lak": "ቁጥር ላክ",
    "qeri asayen": "ቀሪ አሳየኝ",
    "tolo tolo qeri lak": "ቶሎ ቶሎ ቀሪ ላክ",
    # ተያዘ
    "teyaze": "ተያዘ", "teyazo": "ተይዞ", "teyazuwal": "ተይዙዋል",
    # አዎ/አይደለም
    "awo": "አዎ", "aydelem": "አይደለም",
    "selam": "ሰላም", "tnx": "አመሰግናለሁ", "thanks": "አመሰግናለሁ",
}

def translate_latin(text: str) -> str:
    """Latin keywords → አማርኛ ይቀይር"""
    result = text.lower()
    # ረዥም phrases መጀመሪያ
    for lat, amh in sorted(LATIN_TO_AMHARIC.items(), key=lambda x: -len(x[0])):
        result = result.replace(lat, amh)
    return result


# ================================================================
# INTENT DEFINITIONS
# ================================================================

INTENTS = {

    "booking": {
        "keywords": [
            "ያዝ", "ያዛት", "ያዛቸው", "ፃፍልኝ", "ፃፍ", "ያዝልኝ",
            "መዝግብ", "መዝግባት", "መዝግብልኝ"
        ],
        "verb_endings": ["ያዝ", "ፃፍ", "መዝግብ", "ያዛ", "ፃፍልኝ"],
        "weight_keyword": 0.25,
        "weight_verb": 0.15,
    },

    "nekay_query": {
        "keywords": [
            "ነቃይ", "ተነቃይ", "ንቃይ", "ነቃዮች",
            "ሚሸጥ", "የተሸጠ",
        ],
        "verb_endings": ["አለ", "ዘርዝር", "ላክ", "ንገር", "ንገረኝ", "አሳውቀኝ", "አሳውቅ"],
        "weight_keyword": 0.25,
        "weight_verb": 0.10,
    },

    "remaining_send": {
        "keywords": [
            "ቀሪ", "ቁጥር",
        ],
        "verb_endings": ["ላክ", "እየላክ", "አሳየኝ", "አሳየን"],
        "weight_keyword": 0.25,
        "weight_verb": 0.15,
    },

    "remaining_query": {
        "keywords": [
            "ቀሪ", "ያልተያዘ", "ያልተያዙ", "ያልተመዘገበ",
            "ምን አለ", "ምን ምን አለ", "ስንት ቀረ",
            "ስንት ቁጥሮች", "ስንት አለ", "ስንት ቁጥር",
            "ቁጥር አለ", "ቀሪ አለ",
        ],
        "verb_endings": ["አለ", "አሉ", "ቀረ", "ይኖር"],
        "weight_keyword": 0.25,
        "weight_verb": 0.10,
    },

    "specific_number_query": {
        "keywords": ["ተያዘ", "ተይዞ", "ተይዙዋል", "አለ ወይ"],
        "verb_endings": ["ተያዘ", "ተይዞ", "አለ", "አለ ወይ"],
        "weight_keyword": 0.25,
        "weight_verb": 0.15,
    },

    "all_taken_query": {
        "keywords": ["ሁሉም ተይዘዋል", "ሁሉም ተያዘ", "ሁሉም አልተያዙም"],
        "verb_endings": ["ተይዘዋል", "ተያዘ", "አልተያዙም"],
        "weight_keyword": 0.25,
        "weight_verb": 0.10,
    },
}


# ================================================================
# RESPONSES
# ================================================================

RESPONSES = {

    "booking_success_normal": [
        "እሺ ገቢ 🙏",
        "እሺ ቤተሰብ 🙏",
        "እሺ ገቢ እንዳይረሳ 🙏",
        "እሺ ወዳጄ 🥰",
    ],

    "booking_success_urgent": [
        "እሺ ቤተሰብ ይፍጠን 🙏",
        "ይዝሄልሃለው ቤተሰብ ይፍጠን 🙏",
        "እሺ ለጫወታው ድምቀት ይፍጠን 🙏",
        "እሺ ገቢ 🙏",
    ],

    "booking_taken": [
        "ቤተሰብ ተቀደምክ 🙏",
        "የለም ቤተሰብ ሌላ ምረጥ 🙏",
        "ቀይር የለም 🙏",
        "ተቀደምክ 🙏 ወዳጄ",
        "ተይዙዋል ቀይር 🙏",
    ],

    "nekay_exists": [
        "እሺ ቤተሰብ እነዚውት",
        "አለ ቤተሰብ 🥰",
        "እሺ ልፈልግልህ 🙏",
        "አሉ የተወሰኑ ቁጥሮች",
    ],

    "nekay_none_remaining": [
        "ቀሪ ቁጥሮች አሉ",
        "ቤተሰብ አላለቀም ቀሪ ቁጥሮች አሉ 🙏",
    ],

    "nekay_all_done": [
        "ቤተሰብ የለም አልቁዋል ቀጣይ ይሞክሩ 🙏",
        "አለቀ 🙏",
        "ቤተሰብ አውን ገና አለቀ 🙏",
    ],

    "remaining_send_ack": [
        "እሺ 🙏",
    ],

    "all_taken_nekay": [
        "አዎ ተይዘዋል ነቃይ ጠብቅ ቤተሰብ 🙏",
    ],
}


# ================================================================
# SCORING ENGINE
# ================================================================

FUZZING_THRESHOLD = 75  # rapidfuzz score threshold

def _fuzzy_score(text: str, keyword: str) -> float:
    """rapidfuzz partial ratio → 0.0 - 1.0"""
    score = fuzz.partial_ratio(text.lower(), keyword.lower())
    return score / 100.0

def _keyword_score(normalized: str, keywords: list) -> float:
    """keyword match score"""
    best = 0.0
    for kw in keywords:
        norm_kw = normalize_amharic(kw)
        # Direct match
        if norm_kw in normalized:
            return 1.0
        # Fuzzy match
        fs = _fuzzy_score(normalized, norm_kw)
        if fs > best:
            best = fs
    return best if best >= (FUZZING_THRESHOLD / 100.0) else 0.0

def _verb_score(normalized: str, verb_endings: list) -> float:
    """verb ending match score"""
    for v in verb_endings:
        norm_v = normalize_amharic(v)
        if norm_v in normalized:
            return 1.0
        if _fuzzy_score(normalized, norm_v) >= (FUZZING_THRESHOLD / 100.0):
            return 0.7
    return 0.0

def detect_intent(text: str) -> tuple:
    """
    Returns (intent_name, score) — highest scoring intent
    """
    # Step 1: Latin → አማርኛ
    translated = translate_latin(text)

    # Step 2: Normalize amharic
    normalized = normalize_amharic(translated)

    # Step 3: score each intent
    results = {}
    for intent_name, config in INTENTS.items():
        w_norm = 0.30
        w_fuzz = 0.35
        w_kw   = config["weight_keyword"]
        w_verb = config["weight_verb"]

        # Normalize score — ቁምፊ ካለ 1.0
        norm_score = 1.0 if any(
            normalize_amharic(kw) in normalized
            for kw in config["keywords"]
        ) else 0.5

        # Fuzzy score — best keyword
        fuzz_score = _keyword_score(normalized, config["keywords"])

        # Keyword score
        kw_score = 1.0 if any(
            normalize_amharic(kw) in normalized
            for kw in config["keywords"]
        ) else fuzz_score

        # Verb score
        verb_score = _verb_score(normalized, config["verb_endings"])

        total = (
            w_norm * norm_score +
            w_fuzz * fuzz_score +
            w_kw   * kw_score +
            w_verb * verb_score
        )

        results[intent_name] = total

    best_intent = max(results, key=results.get)
    best_score  = results[best_intent]

    return best_intent, best_score


# ================================================================
# MAIN RESPONDER
# ================================================================

def get_response(
    text: str,
    settings: dict,
    taken: dict,
    paid: dict,
    nekay_list: list,          # [(number, is_half), ...]
    remaining_count: int,
    countdown_seconds: int,    # 0 = no countdown
    user_name: str = "",
) -> dict:
    """
    Returns:
        {
          "reply": str or None,
          "resend_board": bool,
          "resend_nekay": bool,
          "resend_remaining": bool,
        }
    """

    THRESHOLD_RESPOND  = 0.70
    THRESHOLD_CONFUSED = 0.40

    intent, score = detect_intent(text)

    result = {
        "reply": None,
        "resend_board": False,
        "resend_nekay": False,
        "resend_remaining": False,
    }

    # Score ዝቅ ካለ — ignore ወይም confused
    if score < THRESHOLD_CONFUSED:
        return result
    if score < THRESHOLD_RESPOND:
        result["reply"] = "ምን ማለትህ ነው? 🙏"
        return result

    # ================================================================
    # INTENT: booking
    # ================================================================
    if intent == "booking":
        # Countdown እየሄደ ሳለ
        if countdown_seconds > 0:
            mins = countdown_seconds // 60
            secs = countdown_seconds % 60
            if mins >= 1:
                result["reply"] = f"ቲንሽ ይጠብቁ {mins} ደቂቃ ቀርቱዋል ያልከፈለ ሊወጣ 🙏"
            else:
                result["reply"] = f"{secs} ሴኮንድ ቀርቱዋል ቲንሽ ይጠብቁ ነቃይ ካለ አሳውቃለው 🙏"
            return result

        # ሁሉም ✅ paid — ignore
        if remaining_count == 0 and not nekay_list:
            return result

        # Normal booking — parser.py ይሰራዋል
        # እዚህ booking confirm መልስ ብቻ
        if remaining_count <= 7:
            msg = random.choice(RESPONSES["booking_success_urgent"])
        else:
            msg = random.choice(RESPONSES["booking_success_normal"])
            # 7% ስም ጋር
            if user_name and random.random() < 0.07:
                msg = msg.replace("🙏", f" {user_name} 🙏").replace("🥰", f" {user_name} 🥰")

        result["reply"] = msg
        return result

    # ================================================================
    # INTENT: nekay_query
    # ================================================================
    if intent == "nekay_query":
        if nekay_list:
            result["reply"] = random.choice(RESPONSES["nekay_exists"])
            result["resend_nekay"] = True
        elif remaining_count > 0:
            result["reply"] = random.choice(RESPONSES["nekay_none_remaining"])
            result["resend_remaining"] = True
        else:
            result["reply"] = random.choice(RESPONSES["nekay_all_done"])
        return result

    # ================================================================
    # INTENT: remaining_send
    # ================================================================
    if intent == "remaining_send":
        result["reply"] = random.choice(RESPONSES["remaining_send_ack"])
        result["resend_remaining"] = True
        return result

    # ================================================================
    # INTENT: remaining_query
    # ================================================================
    if intent == "remaining_query":
        result["resend_remaining"] = True
        return result

    # ================================================================
    # INTENT: specific_number_query
    # ================================================================
    if intent == "specific_number_query":
        # ቁጥር ከ text ውስጥ ይውሰድ
        numbers_found = re.findall(r"\d+", text)
        if numbers_found:
            num = int(numbers_found[0])
            entry = taken.get(num, [])
            if entry:
                owner = entry[0][0]
                result["reply"] = f"{num:02d} ለ {owner} ተያዘ"
            else:
                result["reply"] = "አዎ አለ ክፍት ነው"
        else:
            result["resend_remaining"] = True
        return result

    # ================================================================
    # INTENT: all_taken_query
    # ================================================================
    if intent == "all_taken_query":
        all_paid = remaining_count == 0 and not nekay_list
        if all_paid:
            # ignore
            return result
        elif nekay_list:
            result["reply"] = random.choice(RESPONSES["all_taken_nekay"])
        else:
            result["resend_remaining"] = True
        return result

    return result
