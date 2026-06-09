import re
import random
from rapidfuzz import fuzz

# ================================================================
# AMHARIC NORMALIZER — Fidel Family
# ================================================================

FIDEL_MAP = {
    "ሀ": "ሀ", "ሁ": "ሀ", "ሂ": "ሀ", "ሃ": "ሀ", "ሄ": "ሀ", "ህ": "ሀ", "ሆ": "ሀ",
    "ለ": "ለ", "ሉ": "ለ", "ሊ": "ለ", "ላ": "ለ", "ሌ": "ለ", "ል": "ለ", "ሎ": "ለ",
    "ሐ": "ሀ", "ሑ": "ሀ", "ሒ": "ሀ", "ሓ": "ሀ", "ሔ": "ሀ", "ሕ": "ሀ", "ሖ": "ሀ",
    "መ": "መ", "ሙ": "መ", "ሚ": "መ", "ማ": "መ", "ሜ": "መ", "ም": "መ", "ሞ": "መ",
    "ሰ": "ሰ", "ሱ": "ሰ", "ሲ": "ሰ", "ሳ": "ሰ", "ሴ": "ሰ", "ስ": "ሰ", "ሶ": "ሰ",
    "ሸ": "ሸ", "ሹ": "ሸ", "ሺ": "ሸ", "ሻ": "ሸ", "ሼ": "ሸ", "ሽ": "ሸ", "ሾ": "ሸ",
    "ቀ": "ቀ", "ቁ": "ቀ", "ቂ": "ቀ", "ቃ": "ቀ", "ቄ": "ቀ", "ቅ": "ቀ", "ቆ": "ቀ",
    "ቈ": "ቀ", "ቊ": "ቀ", "ቋ": "ቀ", "ቌ": "ቀ", "ቍ": "ቀ",
    "በ": "በ", "ቡ": "በ", "ቢ": "በ", "ባ": "በ", "ቤ": "በ", "ብ": "በ", "ቦ": "በ",
    "ተ": "ተ", "ቱ": "ተ", "ቲ": "ተ", "ታ": "ተ", "ቴ": "ተ", "ት": "ተ", "ቶ": "ተ",
    "ቸ": "ቸ", "ቹ": "ቸ", "ቺ": "ቸ", "ቻ": "ቸ", "ቼ": "ቸ", "ች": "ቸ", "ቾ": "ቸ",
    "ነ": "ነ", "ኑ": "ነ", "ኒ": "ነ", "ና": "ነ", "ኔ": "ነ", "ን": "ነ", "ኖ": "ነ",
    "ኘ": "ነ", "ኙ": "ነ", "ኚ": "ነ", "ኛ": "ነ", "ኜ": "ነ", "ኝ": "ነ", "ኞ": "ነ",
    "አ": "አ", "ኡ": "አ", "ኢ": "አ", "ኣ": "አ", "ኤ": "አ", "እ": "አ", "ኦ": "አ",
    "ከ": "ከ", "ኩ": "ከ", "ኪ": "ከ", "ካ": "ከ", "ኬ": "ከ", "ክ": "ከ", "ኮ": "ከ",
    "ወ": "ወ", "ዉ": "ወ", "ዊ": "ወ", "ዋ": "ወ", "ዌ": "ወ", "ው": "ወ", "ዎ": "ወ",
    "የ": "የ", "ዩ": "የ", "ዪ": "የ", "ያ": "የ", "ዬ": "የ", "ይ": "የ", "ዮ": "የ",
    "ደ": "ደ", "ዱ": "ደ", "ዲ": "ደ", "ዳ": "ደ", "ዴ": "ደ", "ድ": "ደ", "ዶ": "ደ",
    "ጀ": "ጀ", "ጁ": "ጀ", "ጂ": "ጀ", "ጃ": "ጀ", "ጄ": "ጀ", "ጅ": "ጀ", "ጆ": "ጀ",
    "ገ": "ገ", "ጉ": "ገ", "ጊ": "ገ", "ጋ": "ገ", "ጌ": "ገ", "ግ": "ገ", "ጎ": "ገ",
    "ጠ": "ጠ", "ጡ": "ጠ", "ጢ": "ጠ", "ጣ": "ጠ", "ጤ": "ጠ", "ጥ": "ጠ", "ጦ": "ጠ",
    "ጰ": "ጰ", "ጱ": "ጰ", "ጲ": "ጰ", "ጳ": "ጰ", "ጴ": "ጰ", "ጵ": "ጰ", "ጶ": "ጰ",
    "ጸ": "ጸ", "ጹ": "ጸ", "ጺ": "ጸ", "ጻ": "ጸ", "ጼ": "ጸ", "ጽ": "ጸ", "ጾ": "ጸ",
    "ፀ": "ጸ", "ፁ": "ጸ", "ፂ": "ጸ", "ፃ": "ጸ", "ፄ": "ጸ", "ፅ": "ጸ", "ፆ": "ጸ",
    "ፈ": "ፈ", "ፉ": "ፈ", "ፊ": "ፈ", "ፋ": "ፈ", "ፌ": "ፈ", "ፍ": "ፈ", "ፎ": "ፈ",
    "ፐ": "ፐ", "ፑ": "ፐ", "ፒ": "ፐ", "ፓ": "ፐ", "ፔ": "ፐ", "ፕ": "ፐ", "ፖ": "ፐ",
    "ዘ": "ዘ", "ዙ": "ዘ", "ዚ": "ዘ", "ዛ": "ዘ", "ዜ": "ዘ", "ዝ": "ዘ", "ዞ": "ዘ",
    "ዠ": "ዠ", "ዡ": "ዠ", "ዢ": "ዠ", "ዣ": "ዠ", "ዤ": "ዠ", "ዥ": "ዠ", "ዦ": "ዠ",
    "ሠ": "ሰ", "ሡ": "ሰ", "ሢ": "ሰ", "ሣ": "ሰ", "ሤ": "ሰ", "ሥ": "ሰ", "ሦ": "ሰ",
}

def normalize_amharic(text: str) -> str:
    return "".join(FIDEL_MAP.get(ch, ch) for ch in text)


# ================================================================
# LATIN → AMHARIC KEYWORD MAP
# ================================================================

LATIN_TO_AMHARIC = {
    "yaz": "ያዝ", "yazat": "ያዛት", "yazachew": "ያዛቸው",
    "tsafligni": "ፃፍልኝ", "tsaf": "ፃፍ", "yazligni": "ያዝልኝ",
    "mezgib": "መዝግብ", "mezgibat": "መዝግባት", "mezgibligni": "መዝግብልኝ",
    "qeri": "ቀሪ", "qitr": "ቁጥር", "min ale": "ምን አለ",
    "sint qere": "ስንት ቀረ", "sint ale": "ስንት አለ",
    "qeri ale": "ቀሪ አለ", "qitr ale": "ቁጥር አለ",
    "yalteyaze": "ያልተያዘ", "yalteyazun": "ያልተያዙ",
    # nekay — ሙሉ
    "nekay": "ነቃይ", "tenekay": "ተነቃይ", "nkay": "ነቃይ",
    "nekay ale": "ነቃይ አለ", "nekay zerzir": "ነቃይ ዘርዝር",
    "nekay neger": "ነቃይ ንገር", "nekay lak": "ነቃይ ላክ",
    "nekayoch": "ነቃዮች", "mishit ale": "ሚሸጥ አለ",
    "nekay zerzirligni": "ነቃይ ዘርዝርልኝ",
    "nekay negerign": "ነቃይ ንገረኝ",
    "nekay qitroch": "ነቃይ ቁጥሮች",
    "tenekay ale": "ተነቃይ አለ",
    "nekay asayen": "ነቃይ አሳየኝ",
    "nekay awqegn": "ነቃይ አውቀኝ",
    "hulunm teyazuwal": "ሁሉም ተይዘዋል",
    "hulunm teyaze": "ሁሉም ተያዘ",
    "hulunm alteyazum": "ሁሉም አልተያዙም",
    "qeri lak": "ቀሪ ላክ", "qitr lak": "ቁጥር ላክ",
    "qeri asayen": "ቀሪ አሳየኝ",
    "tolo tolo qeri lak": "ቶሎ ቶሎ ቀሪ ላክ",
    "teyaze": "ተያዘ", "teyazo": "ተይዞ", "teyazuwal": "ተይዙዋል",
    "awo": "አዎ", "aydelem": "አይደለም",
    "tnx": "አመሰግናለሁ", "thanks": "አመሰግናለሁ",
    "ale": "አለ",
    # ሰላምታ — Latin
    "selam": "ሰላም", "salam": "ሰላም", "selem": "ሰላም", "selaam": "ሰላም",
    "hi": "ሰላም", "hay": "ሰላም", "hello": "ሰላም", "helo": "ሰላም",
    "endet neh": "እንዴት ነህ", "endet ne": "እንዴት ነህ", "indet neh": "እንዴት ነህ",
    "dena aderk": "ደና አደርክ", "dena adek": "ደና አደርክ", "dena adrk": "ደና አደርክ",
    "dena walk": "ደና ዋልክ",
    "endet amesheh": "እንዴት አመሸህ", "indet amesheh": "እንዴት አመሸህ",
    "selam amesheh": "ሰላም አመሸህ",
    "beselam aderk": "በሰላም አደርክ", "beselam adek": "በሰላም አደርክ",
    "endet arefedek": "እንዴት አረፈድክ", "indet arefedek": "እንዴት አረፈድክ",
    "tena yistilign": "ጤና ይስጥልኝ", "tena yistligni": "ጤና ይስጥልኝ",
    "endemen nachuh": "እንደምን ናችሁ", "endemen nacuh": "እንደምን ናችሁ",
}

def translate_latin(text: str) -> str:
    result = text.lower()
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
        "keywords": ["ተያዘ", "ተይዞ", "ተይዙዋል", "አለ ወይ", "አለ"],
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

    "greeting": {
        "keywords": [
            "ሰላም", "እንዴት ነህ", "ደና አደርክ", "ደና ዋልክ",
            "እንዴት አመሸህ", "ሰላም ዋልክ", "ሰላም አመሸህ",
            "በሰላም አደርክ", "እንዴት አረፈድክ", "ጤና ይስጥልኝ",
            "እንደምን ናችሁ", "እንደምን አላችሁ", "እንዴት ናችሁ",
        ],
        "verb_endings": ["ነህ", "ዋልክ", "አደርክ", "አመሸህ", "አረፈድክ", "ናችሁ", "አላችሁ"],
        "weight_keyword": 0.35,
        "weight_verb": 0.15,
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

    "number_available": [
        "አዎ አለ ክፍት ነው 🙏",
        "አለ ቤተሰብ ክፍት ነው 🙏",
        "ክፍት ነው ያዝ 🙏",
    ],

    "number_taken": [
        "ተይዟል ቤተሰብ 🙏",
        "የለም ተወስዷል 🙏",
        "ተቀደምክ ቤተሰብ 🙏",
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

    "greeting": [
        "ፈጣሪ የተመሰገነ ይሁን 🙏",
        "ፈጣሪ የተመሰገነ ይሁን ወዳጄ 🙏",
        "ይመስገን እንዴት ነህ ወዳጄ 🙏",
        "ፈጣሪ ይመስገን እንኳን በደና መጣህ 🙏",
        "በጉጉት ስንጠብቅህ ነበር እንኳን በደና መጣህ 🙏",
        "ሰላም እንኳን በሰላም መጣህ 🙏",
    ],

    "greeting_help": [
        "በምን ላግዝህ? 🙏",
        "ምን እናግዝህ ትፈልጋለህ? 🙏",
    ],
}


# ================================================================
# SCORING ENGINE
# ================================================================

FUZZING_THRESHOLD = 70

def _fuzzy_score(text: str, keyword: str) -> float:
    score = fuzz.partial_ratio(text.lower(), keyword.lower())
    return score / 100.0

def _keyword_score(normalized: str, keywords: list) -> float:
    best = 0.0
    for kw in keywords:
        norm_kw = normalize_amharic(kw)
        if norm_kw in normalized:
            return 1.0
        fs = _fuzzy_score(normalized, norm_kw)
        if fs > best:
            best = fs
    return best if best >= (FUZZING_THRESHOLD / 100.0) else 0.0

def _verb_score(normalized: str, verb_endings: list) -> float:
    for v in verb_endings:
        norm_v = normalize_amharic(v)
        if norm_v in normalized:
            return 1.0
        if _fuzzy_score(normalized, norm_v) >= (FUZZING_THRESHOLD / 100.0):
            return 0.7
    return 0.0

def detect_intent(text: str) -> tuple:
    translated = translate_latin(text)
    normalized = normalize_amharic(translated)

    results = {}
    for intent_name, config in INTENTS.items():
        w_norm = 0.30
        w_fuzz = 0.35
        w_kw   = config["weight_keyword"]
        w_verb = config["weight_verb"]

        norm_score = 1.0 if any(
            normalize_amharic(kw) in normalized
            for kw in config["keywords"]
        ) else 0.5

        fuzz_score = _keyword_score(normalized, config["keywords"])

        kw_score = 1.0 if any(
            normalize_amharic(kw) in normalized
            for kw in config["keywords"]
        ) else fuzz_score

        verb_score = _verb_score(normalized, config["verb_endings"])

        total = (
            w_norm * norm_score +
            w_fuzz * fuzz_score +
            w_kw   * kw_score +
            w_verb * verb_score
        )

        results[intent_name] = total

    # ================================================================
    # SPECIFIC NUMBER QUERY — ቁጥር + አለ pattern (e.g. "06 ale", "21 አለ")
    # ================================================================
    numbers_in_text = re.findall(r"\d+", text)
    translated_lower = translated.lower()
    has_ale = "አለ" in normalize_amharic(translated_lower) or "ale" in text.lower()

    if numbers_in_text and has_ale:
        return "specific_number_query", 1.0

    # ================================================================
    # CONTEXT GRADING — weighted formula per intent
    # ================================================================
    for intent_name, total in results.items():
        bonus = 0.0

        # ቁጥር አለ → booking / specific_number_query ብቻ ይጠቀም
        if numbers_in_text:
            if intent_name in ("booking", "specific_number_query"):
                bonus += 0.15
            else:
                bonus -= 0.20

        # ቁጥር የለም → booking score ይቀንስ
        if not numbers_in_text and intent_name == "booking":
            bonus -= 0.30

        # greeting — ቁጥር ከሌለ score ይጨምር
        if intent_name == "greeting" and not numbers_in_text:
            bonus += 0.10

        results[intent_name] = max(0.0, total + bonus)

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
    nekay_list: list,
    remaining_count: int,
    countdown_seconds: int,
    user_name: str = "",
    registration_result: str = None,   # "registered" | "registered_half" | "taken" | "out_of_range" | None
    registered_numbers: list = None,   # [(num, is_half), ...]
    failed_numbers: list = None,       # [num, ...]
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

    result = {
        "reply": None,
        "resend_board": False,
        "resend_nekay": False,
        "resend_remaining": False,
    }

    # ================================================================
    # REGISTRATION RESULT — parser.py ካስገባ በኋላ result ሲመጣ
    # ================================================================
    if registration_result is not None:
        if registration_result in ("registered", "registered_half"):
            if remaining_count <= 7:
                result["reply"] = random.choice(RESPONSES["booking_success_urgent"])
            else:
                msg = random.choice(RESPONSES["booking_success_normal"])
                if user_name and random.random() < 0.07:
                    msg = msg.replace("🙏", f" {user_name} 🙏").replace("🥰", f" {user_name} 🥰")
                result["reply"] = msg
        elif registration_result == "taken":
            result["reply"] = random.choice(RESPONSES["booking_taken"])
        # out_of_range ወይም ሌላ — silent
        return result

    # ================================================================
    # INTENT DETECTION — registration result ከሌለ
    # ================================================================
    intent, score = detect_intent(text)

    if score < THRESHOLD_CONFUSED:
        return result
    if score < THRESHOLD_RESPOND:
        result["reply"] = "ምን ማለትህ ነው? 🙏"
        return result

    # ================================================================
    # INTENT: booking — parser ይሰራዋል፣ registration_result ይመጣል
    # ================================================================
    if intent == "booking":
        if countdown_seconds > 0:
            mins = countdown_seconds // 60
            secs = countdown_seconds % 60
            if mins >= 1:
                result["reply"] = f"ቲንሽ ይጠብቁ {mins} ደቂቃ ቀርቱዋል ያልከፈለ ሊወጣ 🙏"
            else:
                result["reply"] = f"{secs} ሴኮንድ ቀርቱዋል ቲንሽ ይጠብቁ ነቃይ ካለ አሳውቃለው 🙏"
        # reply=None — process_registration registration_result ይልካል
        return result

    # ================================================================
    # INTENT: specific_number_query — "06 አለ?" / "06 ale"
    # ================================================================
    if intent == "specific_number_query":
        numbers_found = re.findall(r"\d+", text)
        if numbers_found:
            num = int(numbers_found[0])
            entry = taken.get(num, [])
            if entry:
                result["reply"] = random.choice(RESPONSES["number_taken"])
            else:
                # range check
                total = settings.get("total_numbers", 0)
                if num < 1 or num > total:
                    result["reply"] = random.choice(RESPONSES["number_taken"])
                else:
                    result["reply"] = random.choice(RESPONSES["number_available"])
        else:
            result["resend_remaining"] = True
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
    # INTENT: all_taken_query
    # ================================================================
    if intent == "all_taken_query":
        if remaining_count == 0 and not nekay_list:
            return result
        elif nekay_list:
            result["reply"] = random.choice(RESPONSES["all_taken_nekay"])
        else:
            result["resend_remaining"] = True
        return result

    # ================================================================
    # INTENT: greeting
    # ================================================================
    if intent == "greeting":
        msg = random.choice(RESPONSES["greeting"])
        if random.random() < 0.20:
            msg += " " + random.choice(RESPONSES["greeting_help"])
        result["reply"] = msg
        return result

    return result
