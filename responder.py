import re
import os
import math
import random
import logging
from collections import defaultdict
from parser import parse_numbers

logger = logging.getLogger(__name__)

# ================================================================
# AMHARIC → LATIN TRANSLITERATOR
# ================================================================

FIDEL_TO_LATIN = {
    "ሀ": "ha", "ሁ": "hu", "ሂ": "hi", "ሃ": "ha", "ሄ": "he", "ህ": "h", "ሆ": "ho",
    "ሐ": "ha", "ሑ": "hu", "ሒ": "hi", "ሓ": "ha", "ሔ": "he", "ሕ": "h", "ሖ": "ho",
    "ለ": "le", "ሉ": "lu", "ሊ": "li", "ላ": "la", "ሌ": "le", "ል": "l", "ሎ": "lo",
    "መ": "me", "ሙ": "mu", "ሚ": "mi", "ማ": "ma", "ሜ": "me", "ም": "m", "ሞ": "mo",
    "ሰ": "se", "ሱ": "su", "ሲ": "si", "ሳ": "sa", "ሴ": "se", "ስ": "s", "ሶ": "so",
    "ሠ": "se", "ሡ": "su", "ሢ": "si", "ሣ": "sa", "ሤ": "se", "ሥ": "s", "ሦ": "so",
    "ሸ": "she", "ሹ": "shu", "ሺ": "shi", "ሻ": "sha", "ሼ": "she", "ሽ": "sh", "ሾ": "sho",
    "ቀ": "qe", "ቁ": "qu", "ቂ": "qi", "ቃ": "qa", "ቄ": "qe", "ቅ": "q", "ቆ": "qo",
    "ቈ": "qo", "ቊ": "qu", "ቋ": "qua", "ቌ": "qe", "ቍ": "qu",
    "በ": "be", "ቡ": "bu", "ቢ": "bi", "ባ": "ba", "ቤ": "be", "ብ": "b", "ቦ": "bo",
    "ተ": "te", "ቱ": "tu", "ቲ": "ti", "ታ": "ta", "ቴ": "te", "ት": "t", "ቶ": "to",
    "ቸ": "che", "ቹ": "chu", "ቺ": "chi", "ቻ": "cha", "ቼ": "che", "ች": "ch", "ቾ": "cho",
    "ነ": "ne", "ኑ": "nu", "ኒ": "ni", "ና": "na", "ኔ": "ne", "ን": "n", "ኖ": "no",
    "ኘ": "nye", "ኙ": "nyu", "ኚ": "nyi", "ኛ": "nya", "ኜ": "nye", "ኝ": "ny", "ኞ": "nyo",
    "አ": "a", "ኡ": "u", "ኢ": "i", "ኣ": "a", "ኤ": "e", "እ": "e", "ኦ": "o",
    "ከ": "ke", "ኩ": "ku", "ኪ": "ki", "ካ": "ka", "ኬ": "ke", "ክ": "k", "ኮ": "ko",
    "ወ": "we", "ዉ": "wu", "ዊ": "wi", "ዋ": "wa", "ዌ": "we", "ው": "w", "ዎ": "wo",
    "የ": "ye", "ዩ": "yu", "ዪ": "yi", "ያ": "ya", "ዬ": "ye", "ይ": "y", "ዮ": "yo",
    "ደ": "de", "ዱ": "du", "ዲ": "di", "ዳ": "da", "ዴ": "de", "ድ": "d", "ዶ": "do",
    "ዘ": "ze", "ዙ": "zu", "ዚ": "zi", "ዛ": "za", "ዜ": "ze", "ዝ": "z", "ዞ": "zo",
    "ዠ": "zhe", "ዡ": "zhu", "ዢ": "zhi", "ዣ": "zha", "ዤ": "zhe", "ዥ": "zh", "ዦ": "zho",
    "ጀ": "je", "ጁ": "ju", "ጂ": "ji", "ጃ": "ja", "ጄ": "je", "ጅ": "j", "ጆ": "jo",
    "ገ": "ge", "ጉ": "gu", "ጊ": "gi", "ጋ": "ga", "ጌ": "ge", "ግ": "g", "ጎ": "go",
    "ጠ": "te", "ጡ": "tu", "ጢ": "ti", "ጣ": "ta", "ጤ": "te", "ጥ": "t", "ጦ": "to",
    "ጰ": "pe", "ጱ": "pu", "ጲ": "pi", "ጳ": "pa", "ጴ": "pe", "ጵ": "p", "ጶ": "po",
    "ጸ": "tse", "ጹ": "tsu", "ጺ": "tsi", "ጻ": "tsa", "ጼ": "tse", "ጽ": "ts", "ጾ": "tso",
    "ፀ": "tse", "ፁ": "tsu", "ፂ": "tsi", "ፃ": "tsa", "ፄ": "tse", "ፅ": "ts", "ፆ": "tso",
    "ፈ": "fe", "ፉ": "fu", "ፊ": "fi", "ፋ": "fa", "ፌ": "fe", "ፍ": "f", "ፎ": "fo",
    "ፐ": "pe", "ፑ": "pu", "ፒ": "pi", "ፓ": "pa", "ፔ": "pe", "ፕ": "p", "ፖ": "po",
    "።": ".", "፣": ",", "፤": ";", "፥": ":", "፦": ":-", "፧": "?", "፨": "*",
}


def to_latin(text: str) -> str:
    result = []
    for ch in text:
        if ch in FIDEL_TO_LATIN:
            result.append(FIDEL_TO_LATIN[ch])
        else:
            result.append(ch.lower())
    return "".join(result)


def normalize_to_latin(text: str) -> str:
    result = []
    for ch in text:
        if ch in FIDEL_TO_LATIN:
            result.append(FIDEL_TO_LATIN[ch])
        else:
            result.append(ch.lower())
    normalized = "".join(result)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


# ================================================================
# ACCOUNT LINE EXTRACTOR
# ================================================================

ACCOUNT_PATTERNS = [
    r"CBE\s*[:\-]?\s*\S+",
    r"Telebirr\s*[:\-]?\s*\S+",
    r"Tele\s*[:\-]?\s*\S+",
    r"Awash\s*[:\-]?\s*\S+",
    r"ቴሌብር\s*[:\-]?\s*\S+",
    r"አዋሽ\s*[:\-]?\s*\S+",
    r"ሲቢኢ\s*[:\-]?\s*\S+",
    r"ንግድ\s*ባንክ\s*[:\-]?\s*\S+",
    r"\d{10,}",
]


def _extract_account_lines(payment_info: str) -> str:
    if not payment_info:
        return ""
    lines = payment_info.strip().split("\n")
    account_lines = [
        line.strip() for line in lines
        if line.strip() and any(
            re.search(p, line.strip(), re.IGNORECASE)
            for p in ACCOUNT_PATTERNS
        )
    ]
    return "\n".join(account_lines) if account_lines else payment_info.strip()


# ================================================================
# CHANGE NUMBER / TYPE CHANGE DETECTORS
# ================================================================

CHANGE_CANCEL_WORDS_LAT = ["alfelegm", "alfeligm", "tew", "atfa", "atfaw", "serz", "serzew"]
CHANGE_CONFIRM_WORDS_LAT = [
    "qeyir", "qeyirew", "qeyirligni", "yihun",
    "areg", "aregew", "adrig", "adrigew", "change",
    "lewet", "lewetew", "lewetligni", "azawir", "azawrew",
]
CHANGE_WEDE_WORDS_LAT = ["wede", "to"]


def detect_change_number(text: str):
    latin = normalize_to_latin(text)
    nums = re.findall(r"\d+", text)
    if len(nums) < 2:
        return None
    from_num = int(nums[0])
    to_num = int(nums[1])
    for wede in CHANGE_WEDE_WORDS_LAT:
        if wede in latin.split():
            return (from_num, to_num)
    has_cancel  = any(w in latin for w in CHANGE_CANCEL_WORDS_LAT)
    has_confirm = any(w in latin for w in CHANGE_CONFIRM_WORDS_LAT)
    if has_cancel and has_confirm:
        return (from_num, to_num)
    if has_cancel and ("new" in latin or "ne" in latin.split()):
        return (from_num, to_num)
    return None


def detect_type_change(text: str):
    latin = normalize_to_latin(text)
    TYPE_FULL_WORDS_LAT = ["bemulu", "mulu"]
    TYPE_HALF_WORDS_LAT = ["begmash", "gmash"]
    is_full = any(w in latin for w in TYPE_FULL_WORDS_LAT)
    is_half = any(w in latin for w in TYPE_HALF_WORDS_LAT)
    if not is_full and not is_half:
        return None
    nums = [int(n) for n in re.findall(r"\d+", text)]
    if not nums:
        return None
    target = "full" if is_full else "half"
    return (nums, target)


# ================================================================
# INTENT EXAMPLES
# ================================================================

INTENT_EXAMPLES = {
    "booking": [
        "ያዝ", "ያዛት", "ያዛቸው", "ፃፍልኝ", "ፃፍ", "ያዝልኝ",
        "መዝግብ", "መዝግባት", "መዝግብልኝ",
        "ቁጥር ያዝልኝ", "ፃፍልኝ ቁጥሩን", "ይህን ቁጥር ያዝ",
        "ለኔ ያዝልኝ", "register አርግልኝ", "book አርግ",
        "ቁጥሩን አስቀምጥልኝ", "ፃፍ ፃፍ", "ያዝልኝ እባክህ",
        "ቁጥሩን ጻፍልኝ", "ምዝገባ አርግልኝ", "ምዝገባ",
    ],
    "nekay_query": [
        "ነቃይ", "ተነቃይ", "ነቃዮች", "ሚሸጥ አለ",
        "ነቃይ አለ", "ነቃይ ዘርዝር", "ነቃይ ንገር",
        "ነቃይ ቁጥሮች", "ተነቃይ አለ", "ነቃይ አሳይ",
        "ነቃይ ላክ", "ነቃይ ምን አለ", "ነቃይ ዝርዝር ስጠኝ",
        "ምን ያህል ነቃይ አለ", "ነቃይ ቁጥር ስንት ነው",
    ],
    "remaining_send": [
        "ቀሪ ላክ", "ቁጥር ላክ", "ቀሪ ቁጥሮች ላክ",
        "ቀሪ አሳየኝ", "ቶሎ ቶሎ ቀሪ ላክ",
        "ቀሪ ቁጥሮቹን ላክ", "remaining ላክ",
        "ያልተያዙ ቁጥሮች ላክ", "ያልተያዙ ቁጥሮቹን ስጠኝ",
    ],
    "remaining_query": [
        "ቀሪ", "ያልተያዘ", "ያልተያዙ", "ምን አለ", "ስንት ቀረ",
        "ስንት ቁጥሮች", "ስንት አለ", "ቁጥር አለ", "ቀሪ አለ",
        "ምን ምን አለ", "ቀሪ ቁጥሮች ምን አለ", "ስንት ቁጥር ቀረ",
        "ያልተያዙ ቁጥሮች ምን አለ", "ቀሪ ቁጥሮች ስንት ናቸው",
        "ምን ያህል ቀረ", "ቀሪ ቁጥሮቹ ምንድን ናቸው",
    ],
    "specific_number_query": [
        "ተያዘ", "ተይዞ", "ተይዙዋል", "አለ ወይ", "አለ",
        "ቁጥሩ ተያዘ ወይ", "ቁጥሩ አለ", "ቁጥሩ ክፍት ነው ወይ",
        "ይህ ቁጥር ተወሰደ ወይ", "ቁጥሩ ነፃ ነው ወይ",
        "ይህ ቁጥር ተያዘ", "ቁጥሩ available ነው ወይ",
    ],
    "all_taken_query": [
        "ሁሉም ተይዘዋል", "ሁሉም ተያዘ", "ሁሉም አልተያዙም",
        "ሁሉም ቁጥሮች ተያዙ", "ሁሉም አለቀ", "ሁሉም ተወሰደ",
    ],
    "cancel_number": [
        "አልፈልግም", "ሽጠው", "አጥፋው", "ይጥፋ", "ሰርዝ", "አውጣ",
        "አጥፋልኝ", "ሰርዝልኝ", "አውጣልኝ",
        "ቁጥሩን ሰርዝ", "ቁጥሩን አጥፋ", "ቁጥሩን አውጣ",
        "አልፈለኩም", "አልፈልገውም", "አልፈልጋቸውም",
        "አያስፈልገኝም", "cancel ነው", "drop አርግ",
        "ትቼዋለሁ", "cancel አርግ", "ሰርዝልኝ ቁጥሩን",
    ],
    "complaint_removed": [
        "ተነቀልኩ", "ቁጥሬ ተነቀለ", "ቁጥሬ ጠፋ", "ቁጥሬ ሄደ",
        "ለምን ተነቀልኩ", "ተነቀልኩ እኮ",
        "ቁጥሬ የለም", "ቁጥሬ ጠፋ ለምን", "ቁጥሬ ሄደ ለምን",
        "ቁጥሬ ተቀነሰ", "ቁጥሬ ተወሰደ ለምን",
        "ቁጥሬ ለምን ተነቀለ", "ቁጥሬ ለምን ጠፋ",
    ],
    "complaint_why_sold": [
        "ለምን ሸጥከው", "ለምን ሸጠከው", "ለምን ትነቅላለህ",
        "ለምን ትሸጣለህ", "ለምን ሸጥህ", "ቁጥሬን ለምን ሸጥህ",
        "ቁጥሬን ለምን ነቀልክ", "ለምን ቁጥሬን ሸጥህ",
    ],
    "complaint_paid_removed": [
        "ከፍዬ ነቀልክ", "ተከፍሎ ነቀልክ", "ከፍዬ ሸጥክ",
        "ልክያለው እኮ ለምን ሸጥክ", "ተልኩዋል ለምን ነቀልክ",
        "ልክያለው ለምን", "ልኬ ትነቅላለህ",
        "ብሬ ተልኳል ለምን ነቀልክ", "ገንዘብ ልኬ ነቀልክ",
        "ከፈልኩ ለምን ሸጥክ", "ልኩዋል ለምን", "ተልኩዋል ሸጥክ",
    ],
    "change_number": [
        "ወደ ቀይር", "ቀይር", "ቀይረው", "ቀይርልኝ",
        "ለወጥ", "ለወጠው", "ለወጥልኝ", "አዛውር", "አዛውረው",
        "ቁጥሩን ቀይር", "ቁጥሩን ለወጥ", "ቁጥሬን ቀይርልኝ",
        "change አርግ", "ቁጥሩን change አርግ",
    ],
    "account_query": [
        "አካውንት", "አካውንት ላክ", "አካውንት ምንድን ነው",
        "ቴሌብር", "አዋሽ", "ሲቢኢ", "ንግድ ባንክ",
        "ቴሌብር ቁጥር", "አዋሽ ቁጥር", "ሲቢኢ ቁጥር",
        "የሚከፈልበት ቁጥር", "የባንክ ቁጥር", "ባንክ አካውንት",
        "ላኩ ወዴት", "ገንዘብ ወዴት ልላክ",
        "ቴሌብር አካውንት ስጠኝ", "ወዴት ልከፍል",
    ],
    "type_change": [
        "በሙሉ አርግ", "በሙሉ አድርግ", "በሙሉ ይሁን", "በሙሉ ቀይረው",
        "ሙሉ አርግ", "ሙሉ ይሁን",
        "በግማሽ አርግ", "በግማሽ አድርግ", "በግማሽ ይሁን", "በግማሽ ቀይረው",
        "ግማሽ አርግ", "ግማሽ ይሁን",
    ],
    "why_not_registered": [
        "ለምን አልያዝክልኝም", "ለምን አልፃፍክልኝም", "ለምን አልመዘገብከኝም",
        "ለምን ቁጥሬ አልተያዘም", "ለምን ቁጥሩ አልተያዘም",
        "ቁጥሩ ለምን አልተያዘም", "ለምን አልገባም", "ለምን ሳይያዝ ቀረ",
        "ለምን አልያዘልኝም", "ለምን አልተመዘገበም",
    ],
    "price_query": [
        "ስንት ነው", "በ ስንት ነው", "ስንት ብር ነው",
        "ባለ ስንት ነው", "መደብ ስንት ነው", "ባለ ስንት ብር ነው",
        "ዋጋ ስንት ነው", "ዋጋው ስንት ነው", "ምን ያህል ነው",
        "ምን ያህል ብር ነው", "ስንት ያስከፍላል",
    ],
    "prize_query": [
        "ደራሽ ስንት ነው", "ስንት ደራሽ ነው", "ባለ ስንት ደራሽ ነው",
        "ሽልማቱ ስንት ነው", "1ኛ ሽልማት ስንት ነው", "prize ስንት ነው",
        "ምን ያህል ደራሽ ነው", "ስንት ብር ደራሽ ነው",
    ],
    "players_query": [
        "ስንት ሰው ነው", "ከስንት ሰው ጋር ነው", "ለ ስንት ሰው ነው",
        "ምን ያህል ሰው ነው", "ስንት ሰዎች ናቸው",
        "ጨዋታው ለስንት ሰው ነው", "ስንት ተጫዋቾች ናቸው",
    ],
    "players_remaining_query": [
        "ስንት ሰው ቀረ", "ስንት ሰው ነው የቀረው", "ስንት ሰዎች ቀሩ",
        "ምን ያህል ሰው ቀረ", "ስንት ሰው ይቀራል",
        "ቀሪ ሰው ስንት ነው", "ስንት ሰው ይቀረዋል",
    ],
    "payment_not_received": [
        "ብር አልደረሰኝም", "አልገባልኝም", "ብር አልገባም",
        "ብር ላክልኝ", "ቀሪ ብር ላክልኝ", "ለምን አትልክም",
        "ብሬን ለምን አላክም", "ብር ለምን አልስገባህም",
        "ገንዘቤ አልደረሰኝም", "ብሬ አልደረሰም", "ብር አልተላከም",
    ],
    "result_query": [
        "ውጤት", "ውጤት አሳውቀን", "ስንት ቁጥር ወጣ",
        "ስንት ወጣ", "ምን ቁጥር ወጣ", "ውጤት ስንት ነው",
        "የወጣው ስንት ቁጥር ነው", "የወጣው ምንድነው",
        "ውጤቱ ምንድን ነው", "ውጤቱ ምን ነው",
    ],
    "my_numbers_query": [
        "ምን ቁጥር ያዝክልኝ", "ስንት ቁጥሮችን ነው የያዝኩት",
        "ምን ቁጥሮች ያዝኩ", "ስንት ቁጥር ያዝኩ",
        "ስንት ቁጥሮች መዘገብክልኝ", "ምን ቁጥሮች ናቸው ያዘዝኩት",
        "የያዝኩት ቁጥሮች ምን ምን ናቸው", "ቁጥሬ ምን ምን ነው",
        "ያዘዝኩት ቁጥር ምን ነው", "ምን ቁጥሮች ጻፍክልኝ",
        "ቁጥሮቼ ምን ምን ናቸው", "ምን ቁጥሮች ነው ያዘዝኩት",
        "ቁጥሮቼን ንገረኝ", "ቁጥሮቼን አሳውቀኝ",
        "የያዝክልኝ ቁጥር አለ", "ስንት ቁጥር ነው የኔ",
    ],
    "number_owner_query": [
        "01 የማነው", "06 ለማን ያዘ", "ለማን ያዘ", "ለማን መዘገብክ",
        "ለማን ያዝከው", "ይህ ቁጥር ለማን ተያዘ",
        "ቁጥሩ ለማን ነው", "ቁጥሩ የማነው",
        "ለማን ይዝክ", "ላይ ማነው የተመዘገበው", "ላይ ማነው የተጻፈው",
        "የማን ቁጥር ነው", "የማነው ቁጥሩ",
    ],
    "claim_ownership": [
        "11 የኔ ነው", "የኔ ነው", "11 የኔ ነው እንዴ", "የኔ ነው እንዴ",
        "11 የኔ ነው አደለ", "የኔ ነው አደለ",
    ],
    "link_request": [
        "ሊንክ ላክልኝ", "ሊንክ ላክ", "link ላክልኝ", "link ላክ",
        "ሊንኩን ላክ", "ሊንክ ስጠኝ", "group link ላክልኝ",
    ],
    "speed_request": [
        "ጫወታው ይፍጠን", "ፈጠን ፈጠን አርገው", "ፈጣን ይሁን",
        "ቶሎ ቶሎ አጫወተን", "speed", "ፈጠን",
        "ቶሎ ቶሎ", "ይፍጠን", "ፍጠን",
    ],
    # ── NEW INTENTS ──
    "balance_query": [
        "ስንት ብር አለኝ", "ስንት ቀሪ አለኝ", "ስንት ብር ይቀረኛል",
        "አንተጋ ስንት አለኝ", "ስንት አለኝ", "ብሬ ስንት ነው",
        "balance ስንት ነው", "ምን ያህል ብር አለኝ",
        "ቀሪ balance ስንት ነው", "ስንት ብር ይቀረኛል",
        "sint br alegn", "sint alegn", "balance sint new",
        "antenga sint alegn",
    ],
    "shortfall_query": [
        "ስንት ብር ይቀራል", "ስንት ልጨምር", "ስንት ልሙላ",
        "ስንት ይጎላል", "ስንት ያስጨምራል", "ምን ያህል ይጎዳል",
        "ሁሉም ✅ ለመሆን ስንት", "ለሙሉ ክፍያ ስንት ይጎላል",
        "ስንት ብር ልጨምር ሁሉም እንዲሆን",
        "sint lijevmer", "sint yigolal", "sint yasijemir",
        "sint limula",
    ],
    "winner_query": [
        "ማን አሸነፈ", "ማነው የዘጋው", "ማን ዘጋ", "ማን በላ",
        "ማነው የበላው", "አሸናፊው ማን ነው", "ማን ነው ያሸነፈው",
        "ዘጋው ማን ነው", "winner ማን ነው",
        "man asheneffe", "man zega", "man bela",
        "ashenafiw man new",
    ],
    "i_won_query": [
        "ለኔ ወጣልኝ", "እኔ አሸነፍኩ", "የኔ ቁጥር ወጣ",
        "ወጣልኝ", "እኔ በላው", "እኔ አሸነፍኩ",
        "የኔ ነው ያሸነፈው", "እኔ ነኝ ያሸነፍኩት",
        "ene ashenefjku", "wetaleygn", "yene qitr weta",
        "ene belahu",
    ],
    "not_registered_complaint": [
        "11 ብዬ ነበር", "ለምን አልያዝክልኝም 11", "21 አልያዝክልኝም",
        "ለምን አልያዝክልኝም", "21 ለምን አልመዘገብክልኝም",
        "21 ቀድማለው", "21 የኔ ነው", "21 ይዤ ነበር",
        "ቁጥሬ ተቀደመ", "ቀድሞብኛል", "ቀድሞብኝ",
        "lmin alyazkilgnim", "qedmalehu", "qedmobign",
        "yize neberku", "yene new", "qitre teqedeme",
    ],
    "payment_claim": [
        "ልኬያለው", "ልኪያለው", "ላክያለው", "ልኬልሃለው",
        "ተልኳል", "ልኩአለው", "ደርሷል", "ላክሁ", "ላከው",
        "ገቢ አርጌያለው", "ገቢ አድርጌያለው", "ከፍያለው", "ተከፍያለው",
        "done", "sent", "send አረግኩ", "paid", "✅",
        "lkiyalew", "lkyalew", "derso", "gebi argeyalew",
    ],
}


# ================================================================
# N-GRAM ENGINE
# ================================================================

def get_ngrams(text: str, n: int = 2) -> list:
    tokens = text.split()
    ngrams = []
    for token in tokens:
        for i in range(len(token) - n + 1):
            ngrams.append(token[i:i+n])
    ngrams.extend(tokens)
    return ngrams


def build_tfidf(intent_examples: dict):
    intent_ngrams = {}
    for intent, examples in intent_examples.items():
        all_ngrams = []
        for ex in examples:
            latin = normalize_to_latin(ex)
            all_ngrams.extend(get_ngrams(latin))
        intent_ngrams[intent] = all_ngrams

    vocab = set()
    for ngrams in intent_ngrams.values():
        vocab.update(ngrams)
    vocab = sorted(vocab)

    vectors = {}
    for intent, ngrams in intent_ngrams.items():
        vec = defaultdict(float)
        total = len(ngrams)
        if total == 0:
            vectors[intent] = vec
            continue
        for ng in ngrams:
            vec[ng] += 1.0 / total
        vectors[intent] = vec

    idf = {}
    num_intents = len(intent_ngrams)
    for ng in vocab:
        doc_count = sum(1 for ngrams in intent_ngrams.values() if ng in ngrams)
        idf[ng] = math.log((num_intents + 1) / (doc_count + 1)) + 1.0

    tfidf_vectors = {}
    for intent, tf_vec in vectors.items():
        tfidf_vec = {}
        for ng, tf_val in tf_vec.items():
            tfidf_vec[ng] = tf_val * idf.get(ng, 1.0)
        tfidf_vectors[intent] = tfidf_vec

    return tfidf_vectors, idf


def text_to_vector(text: str, idf: dict) -> dict:
    latin = normalize_to_latin(text)
    ngrams = get_ngrams(latin)
    vec = defaultdict(float)
    total = len(ngrams)
    if total == 0:
        return vec
    for ng in ngrams:
        vec[ng] += 1.0 / total
    tfidf_vec = {}
    for ng, tf_val in vec.items():
        tfidf_vec[ng] = tf_val * idf.get(ng, 1.0)
    return tfidf_vec


def cosine_similarity(vec_a: dict, vec_b: dict) -> float:
    if not vec_a or not vec_b:
        return 0.0
    common_keys = set(vec_a.keys()) & set(vec_b.keys())
    dot = sum(vec_a[k] * vec_b[k] for k in common_keys)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


print("🔧 Building intent vectors...")
TFIDF_VECTORS, GLOBAL_IDF = build_tfidf(INTENT_EXAMPLES)
print(f"✅ Intent engine ready — {len(TFIDF_VECTORS)} intents loaded")


# ================================================================
# TF-IDF LATIN RETRY THRESHOLD (env-configurable)
# ================================================================
# Jina embedding model latin/transliterated ጽሁፍ ላይ (ለምሳሌ "sint alegn")
# ደካማ ውጤት ስለሚሰጥ፣ Jina "unknown" ሲመልስ (ግን ራሱ ሰርቶ ከሆነ — available=True)
# እና ጽሁፉ latin ፊደል ካለው፣ TF-IDF ሁለተኛ ሙከራ (retry) ያደርጋል። ውጤቱ ከዚህ
# threshold በላይ ከሆነ TF-IDF intent ተቀብሎ ጥቅም ላይ ይውላል።
#
# ENV OVERRIDE: TFIDF_LATIN_THRESHOLD env var ካለ ከዛ ይነበባል (redeploy
# ሳያስፈልግ ለ testing ቁጥር መቀያየር እንዲቻል)። ካልተቀመጠ ወይም ልክ ያልሆነ ካልሆነ
# ነባሪ 0.60 ይያዛል።
def _read_tfidf_latin_threshold() -> float:
    val = os.environ.get("TFIDF_LATIN_THRESHOLD")
    if val is None:
        return 0.60
    try:
        score = float(val)
        if not (0.0 <= score <= 1.0):
            logger.warning(
                f"[Responder] TFIDF_LATIN_THRESHOLD={val} range (0.0-1.0) ውጪ ነው — ነባሪ 0.60 ይያዛል"
            )
            return 0.60
        return score
    except ValueError:
        logger.warning(f"[Responder] TFIDF_LATIN_THRESHOLD='{val}' ቁጥር አይደለም — ነባሪ 0.60 ይያዛል")
        return 0.60


TFIDF_LATIN_THRESHOLD = _read_tfidf_latin_threshold()
logger.info(
    f"[Responder] TFIDF_LATIN_THRESHOLD = {TFIDF_LATIN_THRESHOLD} "
    f"(env override: {'yes' if os.environ.get('TFIDF_LATIN_THRESHOLD') else 'no, default'})"
)


def _has_latin_chars(text: str) -> bool:
    """ጽሁፉ ውስጥ ቢያንስ አንድ latin ፊደል (a-z/A-Z) ካለ True ይመልሳል።"""
    return bool(re.search(r"[a-zA-Z]", text))


# ================================================================
# DETECT INTENT (TF-IDF) — legacy/emergency-only path.
# get_response_async() ከአሁን በኋላ Jina ብቻ ይጠቀማል (booking ካልሆነ)።
# ይህ function still used by: get_response() when intent isn't
# passed in externally (e.g. direct/manual calls, tests).
# ================================================================

def detect_intent(text: str) -> tuple:
    latin = normalize_to_latin(text)
    numbers_in_text = re.findall(r"\d+", text)

    # ── 9+ digit account number detection (FIX 2) ────────────────
    _continuous_nums = re.findall(r'\b\d{9,}\b', text)
    if _continuous_nums:
        return "account_query", 1.0

    # ── payment_claim ("ልኬያለው"/"done"/"✅") — booking numbers ከሌለ ብቻ
    # fast-path ተፈትሽ (ቁጥር ካለ parse_numbers/booking flow ቅድሚያ ይኑረው)
    PAYMENT_CLAIM_KW = [
        normalize_to_latin("ልኬያለው"), normalize_to_latin("ልኪያለው"),
        normalize_to_latin("ላክያለው"), normalize_to_latin("ልኬልሃለው"),
        normalize_to_latin("ተልኳል"), normalize_to_latin("ልኩአለው"),
        normalize_to_latin("ደርሷል"), normalize_to_latin("ላክሁ"),
        normalize_to_latin("ላከው"), normalize_to_latin("ገቢ አርጌያለው"),
        normalize_to_latin("ገቢ አድርጌያለው"), normalize_to_latin("ከፍያለው"),
        normalize_to_latin("ተከፍያለው"),
        "done", "sent", "paid", "lkiyalew", "lkyalew", "derso",
    ]
    text_stripped = text.strip()
    if text_stripped in ("✅",) or any(kw in latin for kw in PAYMENT_CLAIM_KW):
        if not numbers_in_text:
            return "payment_claim", 1.0

    # ── i_won_query ───────────────────────────────────────────────
    I_WON_KW = [
        normalize_to_latin("ለኔ ወጣልኝ"),
        normalize_to_latin("እኔ አሸነፍኩ"),
        normalize_to_latin("የኔ ቁጥር ወጣ"),
        normalize_to_latin("ወጣልኝ"),
        normalize_to_latin("እኔ በላው"),
        normalize_to_latin("ያሸነፍኩት"),
        "ene ashenefjku", "wetaleygn", "yene qitr weta", "ene belahu",
    ]
    if any(kw in latin for kw in I_WON_KW):
        return "i_won_query", 1.0

    # ── winner_query ──────────────────────────────────────────────
    WINNER_KW = [
        normalize_to_latin("ማን አሸነፈ"),
        normalize_to_latin("ማን ዘጋ"),
        normalize_to_latin("ማን በላ"),
        normalize_to_latin("ማነው የዘጋው"),
        normalize_to_latin("ማነው የበላው"),
        normalize_to_latin("አሸናፊው"),
        "man asheneffe", "man zega", "man bela", "ashenafiw",
    ]
    if any(kw in latin for kw in WINNER_KW):
        return "winner_query", 1.0

    # ── balance_query ─────────────────────────────────────────────
    BALANCE_KW = [
        normalize_to_latin("ስንት ብር አለኝ"),
        normalize_to_latin("ስንት ቀሪ አለኝ"),
        normalize_to_latin("አንተጋ ስንት አለኝ"),
        normalize_to_latin("ብሬ ስንት ነው"),
        normalize_to_latin("ምን ያህል ብር አለኝ"),
        normalize_to_latin("ቀሪ balance"),
        "antenga sint alegn", "balance sint", "sint br alegn",
    ]
    BALANCE_SINT_ALEGN = normalize_to_latin("ስንት አለኝ")
    if any(kw in latin for kw in BALANCE_KW):
        return "balance_query", 1.0
    if BALANCE_SINT_ALEGN in latin and not numbers_in_text:
        return "balance_query", 1.0

    # ── shortfall_query ───────────────────────────────────────────
    SHORTFALL_KW = [
        normalize_to_latin("ስንት ልጨምር"),
        normalize_to_latin("ስንት ልሙላ"),
        normalize_to_latin("ስንት ይጎላል"),
        normalize_to_latin("ስንት ያስጨምራል"),
        normalize_to_latin("ስንት ብር ይቀራል"),
        normalize_to_latin("ሁሉም ✅ ለመሆን"),
        "sint lijevmer", "sint yigolal", "sint yasijemir", "sint limula",
    ]
    if any(kw in latin for kw in SHORTFALL_KW):
        return "shortfall_query", 1.0

    # ── not_registered_complaint ──────────────────────────────────
    NOT_REG_KW = [
        normalize_to_latin("ቀድማለው"),
        normalize_to_latin("ቀድሞብኝ"),
        normalize_to_latin("ቀድሞብኛል"),
        normalize_to_latin("ይዤ ነበር"),
        normalize_to_latin("የኔ ነው"),
        normalize_to_latin("ብዬ ነበር"),
        "qedmalehu", "qedmobign", "yize neberku",
    ]
    NOT_REG_LMIN_KW = [
        normalize_to_latin("ለምን አልያዝክልኝም"),
        normalize_to_latin("ለምን አልመዘገብክልኝም"),
        "lmin alyazkilgnim",
    ]
    if any(kw in latin for kw in NOT_REG_KW) and numbers_in_text:
        return "not_registered_complaint", 1.0
    if any(kw in latin for kw in NOT_REG_LMIN_KW) and numbers_in_text:
        return "not_registered_complaint", 1.0

    # ── account keywords ──────────────────────────────────────────
    ACCOUNT_KW_LAT = [
        "akawnt", "akaunt", "akount",
        "telebirr", "telebr", "awash", "cbe",
        "nigid bank", "bank akawnt",
    ]
    ACCOUNT_KW_AMH_LAT = [
        normalize_to_latin("አካውንት"),
        normalize_to_latin("ቴሌብር"),
        normalize_to_latin("አዋሽ"),
        normalize_to_latin("ሲቢኢ"),
        normalize_to_latin("ንግድ ባንክ"),
        normalize_to_latin("የሚከፈልበት ቁጥር"),
        normalize_to_latin("የባንክ ቁጥር"),
    ]
    if any(kw in latin for kw in ACCOUNT_KW_LAT + ACCOUNT_KW_AMH_LAT):
        return "account_query", 1.0

    # ── link request ──────────────────────────────────────────────
    LINK_KW = [normalize_to_latin("ሊንክ"), "link"]
    if any(kw in latin for kw in LINK_KW):
        return "link_request", 1.0

    # ── speed request ─────────────────────────────────────────────
    SPEED_KW = [
        normalize_to_latin("ይፍጠን"),
        normalize_to_latin("ፈጠን ፈጠን"),
        normalize_to_latin("ፍጠን"),
        "speed", "yiftsen", "fetsen",
    ]
    if any(kw in latin for kw in SPEED_KW):
        return "speed_request", 1.0

    # ── my numbers query ──────────────────────────────────────────
    MY_NUM_KW = [
        normalize_to_latin("ምን ቁጥር ያዝክልኝ"),
        normalize_to_latin("ስንት ቁጥሮችን ነው የያዝኩት"),
        normalize_to_latin("ምን ቁጥሮች ያዝኩ"),
        normalize_to_latin("ቁጥሮቼ"),
        normalize_to_latin("ያዘዝኩት ቁጥር"),
        normalize_to_latin("ምን ቁጥሮች ጻፍክልኝ"),
        normalize_to_latin("ቁጥሮቼን ንገረኝ"),
        normalize_to_latin("ቁጥሮቼን አሳውቀኝ"),
        normalize_to_latin("የያዝክልኝ ቁጥር አለ"),
        normalize_to_latin("ስንት ቁጥር ነው የኔ"),
    ]
    if any(kw in latin for kw in MY_NUM_KW):
        return "my_numbers_query", 1.0

    # ── claim ownership ("11 የኔ ነው") ────────────────────────────────
    if numbers_in_text:
        CLAIM_KW = [
            normalize_to_latin("የኔ ነው"),
        ]
        if any(kw in latin for kw in CLAIM_KW):
            return "claim_ownership", 1.0

    # ── number owner query ────────────────────────────────────────
    if numbers_in_text:
        OWNER_KW = [
            normalize_to_latin("ለማን ያዘ"),
            normalize_to_latin("ለማን ነው"),
            normalize_to_latin("የማነው"),
            normalize_to_latin("ለማን ተያዘ"),
            normalize_to_latin("ለማን መዘገብክ"),
        ]
        if any(kw in latin for kw in OWNER_KW):
            return "number_owner_query", 1.0

    # ── change number ─────────────────────────────────────────────
    if len(numbers_in_text) >= 2:
        change_result = detect_change_number(text)
        if change_result:
            return "change_number", 1.0

    # ── type change ───────────────────────────────────────────────
    TYPE_FULL_LAT = [normalize_to_latin("በሙሉ"), normalize_to_latin("ሙሉ"), "bemulu", "mulu"]
    TYPE_HALF_LAT = [normalize_to_latin("በግማሽ"), normalize_to_latin("ግማሽ"), "begmash", "gmash"]
    has_type_full = any(w in latin for w in TYPE_FULL_LAT)
    has_type_half = any(w in latin for w in TYPE_HALF_LAT)
    if numbers_in_text and (has_type_full or has_type_half):
        TYPE_ACTION_LAT = [
            normalize_to_latin("አርግ"), normalize_to_latin("አድርግ"),
            normalize_to_latin("ይሁን"), normalize_to_latin("ቀይር"),
            "areg", "adrig", "yihun", "qeyir", "keyir",
        ]
        if any(w in latin for w in TYPE_ACTION_LAT):
            return "type_change", 1.0

    # ── why not registered ────────────────────────────────────────
    WHY_NOT_LAT = [
        normalize_to_latin("ለምን አልያዝ"),
        normalize_to_latin("ለምን አልፃፍ"),
        normalize_to_latin("ለምን አልተያዘ"),
        normalize_to_latin("ለምን አልገባ"),
        "lmin alyaz", "lmin altsaf", "lmin alteyaz", "lmin algeba",
    ]
    if any(w in latin for w in WHY_NOT_LAT):
        return "why_not_registered", 1.0

    # ── result query ──────────────────────────────────────────────
    RESULT_KW = [
        normalize_to_latin("ውጤት"),
        normalize_to_latin("ስንት ቁጥር ወጣ"),
        normalize_to_latin("ምን ቁጥር ወጣ"),
        normalize_to_latin("የወጣው"),
        "wetset", "sint qitr weta", "min qitr weta",
    ]
    if any(kw in latin for kw in RESULT_KW):
        return "result_query", 1.0

    # ── prize query ───────────────────────────────────────────────
    PRIZE_KW = [
        normalize_to_latin("ደራሽ"),
        normalize_to_latin("ሽልማት"),
        "derash", "shilmat", "prize",
    ]
    if any(kw in latin for kw in PRIZE_KW):
        return "prize_query", 1.0

    # ── payment not received ──────────────────────────────────────
    PAYMENT_NOT_RECV = [
        normalize_to_latin("ብር አልደረሰኝም"),
        normalize_to_latin("አልገባልኝም"),
        normalize_to_latin("ብር አልገባም"),
        normalize_to_latin("ብር ላክልኝ"),
        normalize_to_latin("ለምን አትልክም"),
        "br alderesegnim", "br algeba", "lemin atlikm",
    ]
    if any(kw in latin for kw in PAYMENT_NOT_RECV):
        return "payment_not_received", 1.0

    # ── players remaining query ───────────────────────────────────
    PLAYERS_REM = [
        normalize_to_latin("ስንት ሰው ቀረ"),
        normalize_to_latin("ስንት ሰዎች ቀሩ"),
        normalize_to_latin("ቀሪ ሰው"),
        "sint sew qere", "qeri sew",
    ]
    if any(kw in latin for kw in PLAYERS_REM):
        return "players_remaining_query", 1.0

    # ── players query ─────────────────────────────────────────────
    PLAYERS_KW = [
        normalize_to_latin("ስንት ሰው ነው"),
        normalize_to_latin("ከስንት ሰው ጋር ነው"),
        "sint sew new", "kesint sew gar new",
    ]
    if any(kw in latin for kw in PLAYERS_KW):
        return "players_query", 1.0

    # ── price query ───────────────────────────────────────────────
    PRICE_KW = [
        normalize_to_latin("ዋጋ ስንት"),
        normalize_to_latin("ዋጋው ስንት"),
        normalize_to_latin("ምን ያህል ብር"),
        normalize_to_latin("ስንት ያስከፍላል"),
        "wagaw sint", "min yahil br",
    ]
    PRICE_SINT_NEW = normalize_to_latin("ስንት ነው")
    if not numbers_in_text and PRICE_SINT_NEW in latin:
        return "price_query", 1.0
    if any(kw in latin for kw in PRICE_KW):
        return "price_query", 1.0

    # ── specific number query ─────────────────────────────────────
    ALE_LAT    = normalize_to_latin("አለ")
    TEYAZE_LAT = [normalize_to_latin(w) for w in ["ተያዘ", "ተይዞ", "ተይዙዋል"]]
    has_ale    = ALE_LAT in latin.split()
    has_teyaze = any(w in latin for w in TEYAZE_LAT)
    if numbers_in_text and (has_ale or has_teyaze):
        return "specific_number_query", 1.0

    # ── cancel number ─────────────────────────────────────────────
    CANCEL_LAT = [
        normalize_to_latin(w) for w in
        ["አልፈልግም", "ሽጠው", "አጥፋው", "ይጥፋ", "ሰርዝ", "አውጣ", "አጥፋልኝ", "ሰርዝልኝ"]
    ] + ["alfeligm", "alfelegim", "serzew", "serz", "atfaw", "atfa", "awta"]
    if len(numbers_in_text) == 1 and any(w in latin for w in CANCEL_LAT):
        return "cancel_number", 1.0

    # ── TF-IDF cosine fallback ────────────────────────────────────
    query_vec = text_to_vector(text, GLOBAL_IDF)
    scores = {}
    for intent, intent_vec in TFIDF_VECTORS.items():
        scores[intent] = cosine_similarity(query_vec, intent_vec)

    for intent in list(scores.keys()):
        bonus = 0.0
        if numbers_in_text:
            if intent in ("booking", "specific_number_query", "cancel_number",
                          "change_number", "type_change", "not_registered_complaint"):
                bonus += 0.08
            elif intent not in ("account_query", "price_query", "prize_query",
                                "players_query", "players_remaining_query",
                                "result_query", "balance_query", "shortfall_query",
                                "payment_not_received", "number_owner_query",
                                "my_numbers_query", "winner_query", "i_won_query",
                                "claim_ownership", "payment_claim"):
                bonus -= 0.10
        if not numbers_in_text and intent == "booking":
            bonus -= 0.15
        if intent in ("complaint_removed", "complaint_why_sold",
                      "complaint_paid_removed") and not numbers_in_text:
            bonus += 0.05
        scores[intent] = max(0.0, scores[intent] + bonus)

    # ── FIX: confidence calibration ────────────────────────────────
    sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
    best_intent, best_score = sorted_scores[0]
    second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0
    MARGIN_MIN = 0.06
    if best_score - second_score < MARGIN_MIN:
        best_score = min(best_score, 0.20)
    return best_intent, best_score


# ================================================================
# RESPONSES
# ================================================================

RESPONSES = {
    "booking_success_normal": [
        "እሺ ገቢ 🙏", "እሺ ገቢ እንዳይረሳ 🙏",
        "እሺ ገቢ ቤተሰብ 🙏", "እሺ 🙏 ገቢ ይላክ",
    ],
    "booking_success_paid": [
        "እሺ ቤተሰብ 🙏", "እሺ ወዳጄ 🥰",
    ],
    "booking_success_urgent": [
        "እሺ ቤተሰብ ይፍጠን 🙏", "ይዝሄልሃለው ቤተሰብ ይፍጠን 🙏",
        "እሺ ለጫወታው ድምቀት ይፍጠን 🙏", "እሺ ገቢ 🙏",
    ],
    "booking_taken": [
        "ቤተሰብ ተቀደምክ 🙏", "የለም ቤተሰብ ሌላ ምረጥ 🙏",
        "ቀይር የለም 🙏", "ተቀደምክ 🙏 ወዳጄ", "ተይዙዋል ቀይር 🙏",
    ],
    "number_available": [
        "አዎ አለ ክፍት ነው 🙏", "አለ ቤተሰብ ክፍት ነው 🙏", "ክፍት ነው ያዝ 🙏",
    ],
    "number_taken": [
        "ተይዟል ቤተሰብ 🙏", "የለም ተወስዷል 🙏", "ተቀደምክ ቤተሰብ 🙏",
    ],
    "nekay_exists": [
        "እሺ ቤተሰብ እነዚውት", "አለ ቤተሰብ 🥰",
        "እሺ ልፈልግልህ 🙏", "አሉ የተወሰኑ ቁጥሮች",
    ],
    "nekay_none_remaining": [
        "ቀሪ ቁጥሮች አሉ 🙏", "ቤተሰብ አላለቀም ቀሪ ቁጥሮች አሉ 🙏",
    ],
    "nekay_all_done": [
        "ቤተሰብ የለም አልቁዋል ቀጣይ ይሞክሩ 🙏", "አለቀ 🙏", "ቤተሰብ አውን ገና አለቀ 🙏",
    ],
    "remaining_send_ack": ["እሺ 🙏"],
    "all_taken_nekay": ["አዎ ተይዘዋል ነቃይ ጠብቅ ቤተሰብ 🙏"],
    "cancel_number_ack": ["እሺ ተሰርዟል 🙏", "እሺ ተነቅሏል 🙏"],
    "complaint_removed_taken": [
        "አዎ ገቢ ማረግ ረሳክ የጫወታው ባህሪ ነው 🙏",
        "ቤተሰብ ገቢ ሳታርግ ቁጥሉ ይለቀቃል 🙏",
        "ገቢ ማረግ ረሳህ ቤተሰብ የጫወታው ሕግ ነው 🙏",
    ],
    "complaint_removed_nekay": [
        "ተነቃይ list ውስጥ ገብቷል ገቢ አርደው ያረጋግጡ 🙏",
        "ቁጥርዎ ነቃይ ነው ገቢ አረጋግጡ 🙏",
        "ነቃይ ነው ቤተሰብ ቶሎ ገቢ አርጉ 🙏",
    ],
    "complaint_why_sold": [
        "ገቢ ተረሳ ቤተሰብ ምን ላርግ 🙏",
        "ቤተሰብ ገቢ ሳይደርስ ቁጥሩ ተለቀቀ ምን ላርግ 🙏",
        "ገቢ አልደረሰም ቤተሰብ ምን ላርግ 🙏",
    ],
    "complaint_paid_removed": [
        "ቼክ አርግ ችግር ካለ ባለቤቱን አውራው 🙏",
        "ባለቤቱን አናግር ቼክ ያርጋል 🙏",
        "ችግር ካለ ባለቤቱን አውራው ቼክ ያርጋል 🙏",
        "ባለቤቱን አናግረው ቼክ ያርጋሉ 🙏",
    ],
    "change_number_ack": [
        "እሺ🙏 {from_num} ወደ {to_num} ቀይርያለው",
        "እሺ ቤተሰብ🙏 {from_num} ወደ {to_num} ተቀይሯል",
        "ተቀይሯል🙏 {from_num} → {to_num}",
    ],
    "change_number_not_yours": [
        "ቁጥሉ የእርስዎ አይደለም 🙏",
        "{from_num} የእርስዎ ቁጥር አይደለም 🙏",
    ],
    "change_number_target_taken": [
        "{to_num} ተይዟል ቤተሰብ ሌላ ምረጥ 🙏",
        "ቤተሰብ {to_num} ክፍት አይደለም ሌላ ምረጥ 🙏",
    ],
    "change_number_invalid": [
        "ቁጥሩ ትክክል አይደለም 🙏", "ያ ቁጥር የለም 🙏",
    ],
    "type_change_ack": [
        "እሺ 🙏", "እሺ ቤተሰብ 🙏", "ተቀይሯል 🙏",
    ],
    "type_change_conflict": [
        "ቁጥሩ {num} slot 2 ተይዟል መቀየር አይቻልም 🙏",
        "{num} ሌላ ሰው slot 2 ላይ አለ 🙏",
    ],
    "type_change_not_yours": [
        "ቁጥሩ የእርስዎ አይደለም 🙏",
        "{num} የእርስዎ ቁጥር አይደለም 🙏",
    ],
    "why_not_registered_taken": [
        "{num} — {name} ቀደምህ ({type}) — {time} 🙏",
        "ቤተሰብ {num} ቀድሞ ተወስዷል — {name} ({type}) {time} 🙏",
    ],
    "why_not_registered_taken_both": [
        "{num} — slot1: {name1} ({type1}), slot2: {name2} — {time} 🙏",
    ],
    "why_not_registered_range": [
        "{num} ከ total ቁጥሮች ውጭ ነው 🙏",
        "ቁጥር {num} የለም 🙏",
    ],
    "why_not_registered_none": [
        "መቼ ነው ቤተሰብ 🙏 ተሳስተሃል ቼክ አድርግ",
        "ቤተሰብ ያ ቁጥር ሞክረሃል አላውቅም ቼክ አድርግ 🙏",
    ],
    "winner_greeting": [
        "እንኳን ደስ አለክ ወዳጄ 🥰",
        "congraaaaa ቤተሰብ 🥰",
        "ቡም ቡም ፈነዳ congraaaa 🎉",
        "ፈነዳ ቤተሰብ እንኳን ደስ አለክ 🥰",
        "champion እንኳን ደስ አለክ 🏆🥰",
    ],
    "nekay_countdown_wait": [
        "ቤተሰብ ትንሽ ይጠብቁ ነቃይ ላወጣ ነው 🙏",
    ],
    "price_query_full_only": [
        "{price_full} ብር ነው 🙏",
        "ቤቱ {price_full} ብር ነው 🙏",
        "{price_full} ብር ነው ቤተሰብ 🙏",
    ],
    "price_query_full_and_half": [
        "ሙሉ {price_full} ብር፣ ግማሽ {price_half} ብር ነው 🙏",
        "{price_full} ብር ሙሉ / {price_half} ብር ግማሽ ነው 🙏",
    ],
    "prize_query": [
        "{prize_1st} ደራሽ ነው ቤተሰብ 🙏",
        "1ኛ {prize_1st} ብር ደራሽ ነው 🙏",
    ],
    "players_query": [
        "{players_count} ሰው ነው ቤተሰብ 🙏",
        "ጨዋታው ለ{players_count} ሰው ነው 🙏",
    ],
    "players_remaining_query": [
        "{players_remaining} ሰው ቀረ ቤተሰብ 🙏",
        "ቀሪ {players_remaining} ሰው አለ 🙏",
    ],
    "payment_not_received": [
        "ችግር ካለ አጫዋቹን በውስጥ አውራው 🙏",
        "ባለቤቱን በውስጥ አናግር ይፈታዋል 🙏",
    ],
    "result_query_waiting": [
        "ውጤት እየተላከ ነው ትንሽ ይጠብቁ 🙏",
        "ትንሽ ይጠብቁ ውጤት ይላካል 🙏",
    ],
    "result_query_show": [
        "🥇 1ኛ: {first}\n🥈 2ኛ: {second}\n🥉 3ኛ: {third}",
        "ውጤት 🏆\n1ኛ: {first}\n2ኛ: {second}\n3ኛ: {third}",
    ],
    "result_query_none": [
        "ገና ውጤት የለም ቤተሰብ 🙏",
        "ውጤት አልተላከም ቤተሰብ 🙏",
    ],
    "my_numbers_none": [
        "ምንም ቁጥር አልተያዘልህም ቤተሰብ 🙏",
        "ቁጥር አልያዝክም ቤተሰብ 🙏",
    ],
    "my_numbers_show": [
        "{numbers_text} ተይዞልሃል ቤተሰብ 🙏",
        "የያዝካቸው: {numbers_text} ቤተሰብ 🙏",
    ],
    "number_owner_show": [
        "ለ {name} ተያዘ ቤተሰብ 🙏",
        "{name} ያዘዋል ቤተሰብ 🙏",
    ],
    "number_owner_yours": [
        "ቤተሰብ 🙏 ይዝሄልሃለው ያንተ ነው",
        "ያንተ ነው ቤተሰብ 🙏",
    ],
    "number_owner_multi": [
        "{owners_text} ቤተሰብ 🙏",
    ],
    "number_owner_free": [
        "ክፍት ነው ያዝ 🙏",
        "ምንም ሰው አልያዘውም ያዝ 🙏",
    ],
    "claim_ownership_yes": [
        "አዎ ቤተሰብ 🙏",
    ],
    "claim_ownership_no": [
        "ቤተሰብ ያንተ አደለም የ {name} ነው 🙏",
    ],
    "link_request": [
        "እሺ በውስጥ እልክልሃለሁ 🙏",
        "እሺ ቤተሰብ በውስጥ እልካለሁ 🙏",
    ],
    "speed_request": [
        "እሺ 🙏 እየሞከርኩ ነው",
        "እሺ ቤተሰብ 🙏 እየሞከርኩ ነው",
    ],
    # ── NEW RESPONSES ──
    "balance_show": [
        "{balance} ብር እኔጋ አለክ ቤተሰብ 🙏",
        "ቤተሰብ {balance} ብር አለህ 🙏",
    ],
    "balance_zero": [
        "0 ብር አለክ ቤተሰብ 🙏",
        "ቤተሰብ balance የለህም 🙏",
    ],
    "shortfall_show": [
        "ቤተሰብ {numbers_text} ✅ እንዲሆን {shortfall} ብር ያስፈልጋል 🙏",
        "{shortfall} ብር ያስጨምርሃል ቤተሰብ ({numbers_text}) 🙏",
    ],
    "shortfall_all_paid": [
        "ሁሉም ✅ ነው ቤተሰብ ምንም አያስፈልግም 🙏",
        "ቤተሰብ ሁሉም ተከፍሏል ✅ 🙏",
    ],
    "shortfall_no_numbers": [
        "ቁጥር አልያዝክም ቤተሰብ 🙏",
    ],
    "winner_show": [
        "🥇 1ኛ፡ {first}\n🥈 2ኛ፡ {second}\n🥉 3ኛ፡ {third} 🙏",
        "አሸናፊዎቹ 🏆\n1ኛ፡ {first}\n2ኛ፡ {second}\n3ኛ፡ {third} 🙏",
    ],
    "winner_show_one": [
        "🥇 1ኛ፡ {first} 🙏",
    ],
    "winner_show_two": [
        "🥇 1ኛ፡ {first}\n🥈 2ኛ፡ {second} 🙏",
    ],
    "winner_none": [
        "ገና አልተወሰነም ቤተሰብ 🙏",
        "ውጤት አልወጣም ቤተሰብ 🙏",
    ],
    "i_won_yes": [
        "ቤተሰብ አዎ {place}ኛ ወቶልሃል 🙏",
        "አዎ ቤተሰብ {place}ኛ ሆነሃል 🏆🙏",
    ],
    "i_won_no": [
        "ቤተሰብ አላሸነፍክም 🙏\n🥇 1ኛ፡ {first}\n🥈 2ኛ፡ {second}\n🥉 3ኛ፡ {third}",
        "አላሸነፍክም ቤተሰብ 🙏\n1ኛ፡ {first}\n2ኛ፡ {second}\n3ኛ፡ {third}",
    ],
    "i_won_no_winners": [
        "ቤተሰብ አላሸነፍክም ወይም ውጤት ገና አልወጣም 🙏",
    ],
    "not_registered_taken": [
        "{num} — አበበ ስለቀደመክ ነው ቤተሰብ 🙏",
        "ቤተሰብ {num} {name} ቀድሞሃል 🙏",
    ],
}


# ================================================================
# FIRST NAME HELPER
# ================================================================

def _first_name(full_name: str) -> str:
    if not full_name:
        return full_name
    return full_name.strip().split()[0] if full_name.strip().split() else full_name


def _parse_payment_info_accounts(payment_info: str) -> list:
    """payment_info ውስጥ ያሉ account numbers ያወጣል"""
    lines = payment_info.strip().split("\n")
    accounts = []
    bank_patterns = [
        (r"CBE", "CBE"),
        (r"Telebirr|Tele|ቴሌብር", "Telebirr"),
        (r"Awash|አዋሽ", "Awash"),
        (r"Dashen|ዳሽን", "Dashen"),
        (r"BOA|Abyssinia|አቢሲኒያ", "BOA"),
        (r"Wegagen|ወጋገን", "Wegagen"),
        (r"Nib|ንብ", "Nib"),
        (r"United|ዩናይትድ", "United"),
        (r"Oromia|ኦሮሚያ", "Oromia"),
        (r"Amhara|አማራ", "Amhara"),
        (r"Coopbank|ኮፕ", "Coopbank"),
        (r"Bunna|ቡና", "Bunna"),
        (r"Berhan|ብርሃን", "Berhan"),
        (r"Zemen|ዘመን", "Zemen"),
    ]
    for line in lines:
        nums = re.findall(r'\d{8,}', line)
        if not nums:
            continue
        bank_name = "Bank"
        for pattern, name in bank_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                bank_name = name
                break
        for num in nums:
            accounts.append({"bank": bank_name, "account": num})
    return accounts


def _fuzzy_account_match(user_num: str, known_num: str) -> str:
    """Returns: 'exact', 'close', or 'no_match'. close = 2 digit ወይም በታች ልዩነት"""
    if user_num == known_num:
        return "exact"
    if abs(len(user_num) - len(known_num)) > 2:
        return "no_match"
    if len(user_num) == len(known_num):
        diff = sum(1 for a, b in zip(user_num, known_num) if a != b)
        if diff <= 2:
            return "close"
    return "no_match"


# ================================================================
# MY NUMBERS FORMAT HELPER
# ================================================================

def _format_my_numbers(user_numbers: list) -> str:
    seen = {}
    for number, is_half, slot, is_paid in user_numbers:
        if slot == 1:
            seen[number] = is_half
        elif number not in seen:
            seen[number] = True

    if not seen:
        return ""

    parts = []
    nums_sorted = sorted(seen.keys())

    for num in nums_sorted:
        is_half = seen[num]
        if is_half:
            parts.append(f"{num:02d}+")
        else:
            parts.append(f"{num:02d}")

    return " ".join(parts)


# ================================================================
# SHORTFALL CALCULATOR
# ================================================================

def _calculate_shortfall(user_numbers: list, settings: dict, user_balance: float) -> dict:
    price_full = float(settings.get("price_full") or 0)
    price_half = float(settings.get("price_half") or 0)

    unpaid_numbers = []
    total_unpaid_cost = 0.0

    seen_slots = {}
    for number, is_half, slot, is_paid in user_numbers:
        if slot == 1:
            seen_slots[number] = {"is_half": is_half, "is_paid": is_paid}
        elif number not in seen_slots:
            seen_slots[number] = {"is_half": True, "is_paid": is_paid}

    for number, data in seen_slots.items():
        if not data["is_paid"]:
            cost = price_half if data["is_half"] else price_full
            total_unpaid_cost += cost
            unpaid_numbers.append((number, data["is_half"]))

    shortfall = max(0.0, total_unpaid_cost - user_balance)

    unpaid_text_parts = []
    for num, is_half in unpaid_numbers:
        if is_half:
            unpaid_text_parts.append(f"{num:02d}+")
        else:
            unpaid_text_parts.append(f"{num:02d}")

    return {
        "shortfall": shortfall,
        "unpaid_numbers": unpaid_numbers,
        "unpaid_text": " ".join(unpaid_text_parts),
        "all_paid": len(unpaid_numbers) == 0,
    }


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
    user_id: int = 0,
    registration_result: str = None,
    registered_numbers: list = None,
    failed_numbers: list = None,
    recent_winners: list = None,
    user_unpaid_balance: float = None,
    user_numbers: list = None,
    # ── params ──
    user_balance: float = None,
    failed_attempts: list = None,
    is_paid: bool = None,
    # ── intent ከውጪ (ለምሳሌ Jina) ሲላክ ጥቅም ላይ ይውላል ──
    intent: str = None,
    score: float = None,
) -> dict:

    THRESHOLD_RESPOND  = 0.40
    THRESHOLD_CONFUSED = 0.12

    result = {
        "reply": None,
        "resend_board": False,
        "resend_nekay": False,
        "resend_remaining": False,
        "cancel_number": None,
        "change_number": None,
        "type_change": None,
        "why_not_registered": None,
        "my_numbers_query": False,
        "number_owner_query": None,
        "payment_claim": False,
    }

    if registration_result is not None:
        if registration_result in ("registered", "registered_half"):
            if is_paid:
                msg = random.choice(RESPONSES["booking_success_paid"])
                if user_name and random.random() < 0.07:
                    msg = msg.replace("🙏", f" {user_name} 🙏").replace("🥰", f" {user_name} 🥰")
                result["reply"] = msg
            elif remaining_count <= 7:
                result["reply"] = random.choice(RESPONSES["booking_success_urgent"])
            else:
                msg = random.choice(RESPONSES["booking_success_normal"])
                if user_name and random.random() < 0.07:
                    msg = msg.replace("🙏", f" {user_name} 🙏").replace("🥰", f" {user_name} 🥰")
                result["reply"] = msg
        elif registration_result == "taken":
            result["reply"] = random.choice(RESPONSES["booking_taken"])
        return result

    # ── intent ከውጪ ካልመጣ ብቻ TF-IDF detect_intent() ተጠቀም ──────────
    if intent is None:
        intent, score = detect_intent(text)
        if score < THRESHOLD_CONFUSED:
            return result
        if score < THRESHOLD_RESPOND:
            return result
    # intent ከውጪ (Jina) ከመጣ threshold ድጋሚ አይፈተሽም —
    # Jina's own JINA_MIN_SCORE already gated it in jina_brain.py

    # ── payment_claim ("ልኬያለው"/"done"/"✅") — reply ራሱ bot.py ውስጥ
    # handle_payment_claim() ተጠቅሞ ይሰራል (fingerprint lookup ስለሚያስፈልግ)፣
    # ስለዚህ እዚህ ምንም ጽሁፍ አንሰጥም፣ flag ብቻ እናነሳለን
    if intent == "payment_claim":
        result["payment_claim"] = True
        return result

    # ── balance_query ─────────────────────────────────────────────
    if intent == "balance_query":
        bal = user_balance if user_balance is not None else (user_unpaid_balance or 0.0)
        if bal > 0:
            result["reply"] = random.choice(RESPONSES["balance_show"]).format(
                balance=int(bal)
            )
        else:
            result["reply"] = random.choice(RESPONSES["balance_zero"])
        return result

    # ── shortfall_query ───────────────────────────────────────────
    if intent == "shortfall_query":
        if not user_numbers:
            result["reply"] = random.choice(RESPONSES["shortfall_no_numbers"])
            return result
        bal = user_balance if user_balance is not None else (user_unpaid_balance or 0.0)
        sf = _calculate_shortfall(user_numbers, settings, bal)
        if sf["all_paid"]:
            result["reply"] = random.choice(RESPONSES["shortfall_all_paid"])
        else:
            result["reply"] = random.choice(RESPONSES["shortfall_show"]).format(
                numbers_text=sf["unpaid_text"],
                shortfall=int(sf["shortfall"]),
            )
        return result

    # ── winner_query ──────────────────────────────────────────────
    if intent == "winner_query":
        if not recent_winners:
            result["reply"] = random.choice(RESPONSES["winner_none"])
            return result
        w = recent_winners
        def fmt_winner(w_item):
            return f"{w_item['user_name']} ({w_item['number']:02d})" if w_item.get("number") else w_item.get("user_name", "—")
        if len(w) == 1:
            result["reply"] = random.choice(RESPONSES["winner_show_one"]).format(
                first=fmt_winner(w[0])
            )
        elif len(w) == 2:
            result["reply"] = random.choice(RESPONSES["winner_show_two"]).format(
                first=fmt_winner(w[0]),
                second=fmt_winner(w[1]),
            )
        else:
            result["reply"] = random.choice(RESPONSES["winner_show"]).format(
                first=fmt_winner(w[0]),
                second=fmt_winner(w[1]) if len(w) > 1 else "—",
                third=fmt_winner(w[2]) if len(w) > 2 else "—",
            )
        return result

    # ── i_won_query ───────────────────────────────────────────────
    if intent == "i_won_query":
        if not recent_winners:
            result["reply"] = random.choice(RESPONSES["i_won_no_winners"])
            return result
        user_place = None
        for w in recent_winners:
            if w.get("telegram_id") == user_id:
                user_place = w["place"]
                break
        if user_place:
            place_label = {1: "1", 2: "2", 3: "3"}.get(user_place, str(user_place))
            result["reply"] = random.choice(RESPONSES["i_won_yes"]).format(place=place_label)
        else:
            def fmt_w(w_item):
                return f"{w_item['user_name']} ({w_item['number']:02d})" if w_item.get("number") else w_item.get("user_name", "—")
            w = recent_winners
            result["reply"] = random.choice(RESPONSES["i_won_no"]).format(
                first=fmt_w(w[0]) if len(w) > 0 else "—",
                second=fmt_w(w[1]) if len(w) > 1 else "—",
                third=fmt_w(w[2]) if len(w) > 2 else "—",
            )
        return result

    # ── not_registered_complaint ──────────────────────────────────
    if intent == "not_registered_complaint":
        numbers_found = re.findall(r"\d+", text)
        if numbers_found and failed_attempts:
            num = int(numbers_found[0])
            attempt = next((a for a in failed_attempts if a["number"] == num), None)
            if attempt and attempt["reason"] == "taken" and attempt.get("slot1_name"):
                name = attempt["slot1_name"]
                result["reply"] = random.choice(RESPONSES["not_registered_taken"]).format(
                    num=f"{num:02d}",
                    name=name,
                )
        return result

    # ── account_query ─────────────────────────────────────────────
    if intent == "account_query":
        payment_info = settings.get("payment_info", "")
        numbers_in_text_9 = re.findall(r'\d{9,}', text)

        if numbers_in_text_9 and payment_info:
            user_num = numbers_in_text_9[0]
            known_accounts = _parse_payment_info_accounts(payment_info)

            best_match = None
            best_match_type = "no_match"

            for acc in known_accounts:
                match_type = _fuzzy_account_match(user_num, acc["account"])
                if match_type == "exact":
                    best_match = acc
                    best_match_type = "exact"
                    break
                elif match_type == "close" and best_match_type != "exact":
                    best_match = acc
                    best_match_type = "close"

            if best_match_type == "exact":
                result["reply"] = f"አዎ ትክክል ነው {best_match['bank']} account ነው 🙏"
            elif best_match_type == "close":
                result["reply"] = f"ትንሽ ተሳስተሃል፣ {best_match['bank']} account {best_match['account']} ነው 🙏"
            else:
                result["reply"] = "እሺ ለአጫዋቹ በውስጥ ላክለት ቤተሰብ 🙏"
        elif payment_info:
            result["reply"] = _extract_account_lines(payment_info)
        return result

    # ── link_request ──────────────────────────────────────────────
    if intent == "link_request":
        result["reply"] = random.choice(RESPONSES["link_request"])
        return result

    # ── speed_request ─────────────────────────────────────────────
    if intent == "speed_request":
        result["reply"] = random.choice(RESPONSES["speed_request"])
        return result

    # ── my_numbers_query ──────────────────────────────────────────
    if intent == "my_numbers_query":
        if user_numbers is not None:
            if not user_numbers:
                result["reply"] = random.choice(RESPONSES["my_numbers_none"])
            else:
                numbers_text = _format_my_numbers(user_numbers)
                if numbers_text:
                    result["reply"] = random.choice(RESPONSES["my_numbers_show"]).format(
                        numbers_text=numbers_text
                    )
                else:
                    result["reply"] = random.choice(RESPONSES["my_numbers_none"])
        else:
            result["my_numbers_query"] = True
        return result

    # ── number_owner_query ────────────────────────────────────────
    if intent == "number_owner_query":
        numbers_found = re.findall(r"\d+", text)
        if numbers_found:
            if len(numbers_found) == 1:
                num = int(numbers_found[0])
                entry = taken.get(num, [])
                if not entry:
                    result["reply"] = random.choice(RESPONSES["number_owner_free"])
                else:
                    slot1 = next((e for e in entry if e[2] == 1), entry[0])
                    owner_name = _first_name(slot1[0])
                    is_half_owner = slot1[1]
                    half_suffix = " (በግማሽ)" if is_half_owner else ""
                    if user_name and any(name == user_name for name, _, _, _, _ in entry):
                        msg = random.choice(RESPONSES["number_owner_yours"])
                        result["reply"] = msg + half_suffix
                    else:
                        msg = random.choice(RESPONSES["number_owner_show"]).format(
                            name=owner_name
                        )
                        result["reply"] = msg + half_suffix
            else:
                lines = []
                for n_str in numbers_found:
                    num = int(n_str)
                    entry = taken.get(num, [])
                    if not entry:
                        lines.append(f"{num:02d} — ክፍት ነው")
                    else:
                        slot1 = next((e for e in entry if e[2] == 1), entry[0])
                        owner_name = _first_name(slot1[0])
                        is_half_owner = slot1[1]
                        half_suffix = " (በግማሽ)" if is_half_owner else ""
                        if user_name and any(name == user_name for name, _, _, _, _ in entry):
                            lines.append(f"{num:02d} — ያንተ ነው{half_suffix}")
                        else:
                            lines.append(f"{num:02d} — ለ {owner_name}{half_suffix}")
                owners_text = "\n".join(lines)
                result["reply"] = random.choice(RESPONSES["number_owner_multi"]).format(
                    owners_text=owners_text
                )
        return result

    # ── claim_ownership ──────────────────────────────────────────
    if intent == "claim_ownership":
        numbers_found = re.findall(r"\d+", text)
        if numbers_found:
            num = int(numbers_found[0])
            entry = taken.get(num, [])
            if not entry:
                return result
            slot1 = next((e for e in entry if e[2] == 1), entry[0])
            is_half_owner = slot1[1]
            half_suffix = " (በግማሽ)" if is_half_owner else ""
            if user_name and any(name == user_name for name, _, _, _, _ in entry):
                result["reply"] = random.choice(RESPONSES["claim_ownership_yes"]) + half_suffix
            else:
                owner_name = _first_name(slot1[0])
                result["reply"] = random.choice(RESPONSES["claim_ownership_no"]).format(
                    name=owner_name
                )
        return result

    # ── change_number ─────────────────────────────────────────────
    if intent == "change_number":
        change_result = detect_change_number(text)
        if change_result:
            from_num, to_num = change_result
            total = settings.get("total_numbers", 0)
            def fmt(n): return f"{n:02d}"
            if to_num < 1 or to_num > total or from_num < 1 or from_num > total:
                result["reply"] = random.choice(RESPONSES["change_number_invalid"])
                return result
            result["change_number"] = {"from": from_num, "to": to_num}
            result["reply"] = random.choice(RESPONSES["change_number_ack"]).format(
                from_num=fmt(from_num), to_num=fmt(to_num)
            )
        return result

    # ── type_change ───────────────────────────────────────────────
    if intent == "type_change":
        type_result = detect_type_change(text)
        if type_result:
            nums, target = type_result
            num = nums[0]
            if num not in taken:
                return result
            result["type_change"] = {"numbers": nums, "target": target}
            result["reply"] = random.choice(RESPONSES["type_change_ack"])
        return result

    # ── why_not_registered ────────────────────────────────────────
    if intent == "why_not_registered":
        numbers_found = re.findall(r"\d+", text)
        target_num = int(numbers_found[0]) if numbers_found else None
        result["why_not_registered"] = {"number": target_num}
        return result

    # ── booking ───────────────────────────────────────────────────
    if intent == "booking":
        if countdown_seconds > 0:
            mins = countdown_seconds // 60
            secs = countdown_seconds % 60
            if mins >= 1:
                result["reply"] = f"ቲንሽ ይጠብቁ {mins} ደቂቃ ቀርቱዋል ያልከፈለ ሊወጣ 🙏"
            else:
                result["reply"] = f"{secs} ሴኮንድ ቀርቱዋል ቲንሽ ይጠብቁ ነቃይ ካለ አሳውቃለው 🙏"
        return result

    # ── specific_number_query ─────────────────────────────────────
    if intent == "specific_number_query":
        numbers_found = re.findall(r"\d+", text)
        if numbers_found:
            num = int(numbers_found[0])
            entry = taken.get(num, [])
            if entry:
                result["reply"] = random.choice(RESPONSES["number_taken"])
            else:
                total = settings.get("total_numbers", 0)
                if num < 1 or num > total:
                    result["reply"] = random.choice(RESPONSES["number_taken"])
                else:
                    result["reply"] = random.choice(RESPONSES["number_available"])
        else:
            result["resend_remaining"] = True
        return result

    # ── cancel_number ─────────────────────────────────────────────
    if intent == "cancel_number":
        numbers_found = re.findall(r"\d+", text)
        if numbers_found:
            num = int(numbers_found[0])
            result["reply"] = random.choice(RESPONSES["cancel_number_ack"])
            result["cancel_number"] = num
        return result

    # ── complaint_removed ─────────────────────────────────────────
    if intent == "complaint_removed":
        numbers_found = re.findall(r"\d+", text)
        num = int(numbers_found[0]) if numbers_found else None
        if num and num in taken:
            result["reply"] = random.choice(RESPONSES["complaint_removed_taken"])
        elif num and any(num == n for n, _ in nekay_list):
            result["reply"] = random.choice(RESPONSES["complaint_removed_nekay"])
        else:
            result["reply"] = random.choice(RESPONSES["complaint_removed_taken"])
        return result

    # ── complaint_why_sold ────────────────────────────────────────
    if intent == "complaint_why_sold":
        result["reply"] = random.choice(RESPONSES["complaint_why_sold"])
        return result

    # ── complaint_paid_removed ────────────────────────────────────
    if intent == "complaint_paid_removed":
        result["reply"] = random.choice(RESPONSES["complaint_paid_removed"])
        return result

    # ── nekay_query ───────────────────────────────────────────────
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

    # ── remaining_send ────────────────────────────────────────────
    if intent == "remaining_send":
        result["reply"] = random.choice(RESPONSES["remaining_send_ack"])
        result["resend_remaining"] = True
        return result

    # ── remaining_query ───────────────────────────────────────────
    if intent == "remaining_query":
        result["resend_remaining"] = True
        return result

    # ── all_taken_query ───────────────────────────────────────────
    if intent == "all_taken_query":
        if remaining_count == 0 and not nekay_list:
            return result
        elif nekay_list:
            result["reply"] = random.choice(RESPONSES["all_taken_nekay"])
        else:
            result["resend_remaining"] = True
        return result

    # ── price_query ───────────────────────────────────────────────
    if intent == "price_query":
        price_full = settings.get("price_full", 0)
        price_half = settings.get("price_half")
        if price_half:
            result["reply"] = random.choice(RESPONSES["price_query_full_and_half"]).format(
                price_full=price_full, price_half=price_half
            )
        else:
            result["reply"] = random.choice(RESPONSES["price_query_full_only"]).format(
                price_full=price_full
            )
        return result

    # ── prize_query ───────────────────────────────────────────────
    if intent == "prize_query":
        prize_1st = settings.get("prize_1st", 0)
        result["reply"] = random.choice(RESPONSES["prize_query"]).format(
            prize_1st=prize_1st
        )
        return result

    # ── players_query ─────────────────────────────────────────────
    if intent == "players_query":
        total_numbers = settings.get("total_numbers", 0)
        numbers_per_person = settings.get("numbers_per_person", 1)
        players_count = total_numbers // numbers_per_person if numbers_per_person else total_numbers
        result["reply"] = random.choice(RESPONSES["players_query"]).format(
            players_count=players_count
        )
        return result

    # ── players_remaining_query ───────────────────────────────────
    if intent == "players_remaining_query":
        numbers_per_person = settings.get("numbers_per_person", 1)
        players_remaining = remaining_count // numbers_per_person if numbers_per_person else remaining_count
        result["reply"] = random.choice(RESPONSES["players_remaining_query"]).format(
            players_remaining=players_remaining
        )
        return result

    # ── payment_not_received ──────────────────────────────────────
    if intent == "payment_not_received":
        result["reply"] = random.choice(RESPONSES["payment_not_received"])
        return result

    # ── result_query ──────────────────────────────────────────────
    if intent == "result_query":
        total_numbers = settings.get("total_numbers", 0)
        paid_count = len(paid)
        nearly_done = (paid_count >= total_numbers - 3) or (countdown_seconds > 0)
        if nearly_done:
            result["reply"] = random.choice(RESPONSES["result_query_waiting"])
        elif recent_winners:
            w = recent_winners
            first  = f"{w[0]['number']:02d}" if len(w) > 0 and w[0].get("number") else "—"
            second = f"{w[1]['number']:02d}" if len(w) > 1 and w[1].get("number") else "—"
            third  = f"{w[2]['number']:02d}" if len(w) > 2 and w[2].get("number") else "—"
            result["reply"] = random.choice(RESPONSES["result_query_show"]).format(
                first=first, second=second, third=third
            )
        else:
            result["reply"] = random.choice(RESPONSES["result_query_none"])
        return result

    return result


# ================================================================
# CONTEXT-DATA SLICE BUILDER (for ai_fallback.get_ai_fallback)
# ================================================================
# TF-IDF/Jina ሁለቱም ካልተሳኩ በኋላ ወደ NVIDIA DeepSeek Flash የሚላከው
# "game_data" ትንሽ ተዛማጅ slice ብቻ እንዲሆን (ሙሉ game state ሳይሆን) ይህ
# helper kwargs ውስጥ ካሉት ላይ ብቻ ትንሽ dict ይገነባል።

def _build_game_data_slice(kwargs: dict) -> dict:
    slice_data = {}
    recent_winners = kwargs.get("recent_winners")
    if recent_winners:
        slice_data["recent_winners"] = [
            {
                "place": w.get("place"),
                "user_name": w.get("user_name"),
                "number": w.get("number"),
                "prize": w.get("prize"),
            }
            for w in recent_winners
        ]
    user_numbers = kwargs.get("user_numbers")
    if user_numbers:
        slice_data["user_numbers"] = [
            {"number": n, "is_half": h, "is_paid": p}
            for (n, h, _slot, p) in user_numbers
        ]
    remaining_count = kwargs.get("remaining_count")
    if remaining_count is not None:
        slice_data["remaining_count"] = remaining_count
    settings = kwargs.get("settings") or {}
    if settings.get("total_numbers"):
        slice_data["total_numbers"] = settings.get("total_numbers")
        slice_data["price_full"] = settings.get("price_full")
        slice_data["price_half"] = settings.get("price_half")
    return slice_data


# ================================================================
# ASYNC WRAPPER — booking ካልሆነ Jina → (latin ከሆነ) TF-IDF retry →
# AI fallback የሚል ቅደም ተከተል ይከተላል
# ================================================================

async def get_response_async(text: str, **kwargs) -> dict:
    """
    get_response() async version:
      1. ጽሁፉ ግልፅ booking pattern ከሆነ (parser.parse_numbers →
         is_clear_pattern=True) → intent detection ጨርሶ አይሞከርም፤
         ባዶ result ተመልሶ bot.py ራሱ parse_numbers/process_registration
         flow ይረከበዋል (ልክ ካለፈው ባህሪ ጋር ተመሳሳይ)።
      2. booking ካልሆነ (ወይም ambiguous ከሆነ) → Jina embedding መጀመሪያ
         ይሞከራል።
           a) Jina በራስ መተማመን intent መልሶ ከሆነ (≥ JINA_MIN_SCORE) →
              ያ intent ጥቅም ላይ ይውላል።
           b) Jina "unknown" ቢመልስ ግን ራሱ ሰርቶ ከሆነ (available=True) እና
              ጽሁፉ latin ፊደል ካለው (transliterated Amharic፣ Jina በዚህ
              ላይ ደካማ ስለሆነ) → TF-IDF ሁለተኛ ሙከራ ያደርጋል
              (TFIDF_LATIN_THRESHOLD፣ default 0.60)። ውጤቱ threshold
              በላይ ከሆነ TF-IDF intent ጥቅም ላይ ይውላል።
           c) Jina ራሱ ጨርሶ ሊሰራ ካልቻለ (available=False — rate limit,
              API/network error) ወይም ready ካልሆነ → TF-IDF ሙሉ ቁጥጥር
              ይይዛል (legacy detect_intent() thresholds፣ 0.40/0.12)
              እንደ primary detector።
      3. ከላይ ያሉት ሁሉ ውጤት ያላመጡ ከሆነ (Jina unknown + latin ያልሆነ ወይም
         latin retry ደካማ ውጤት ካመጣ) → context-aware NVIDIA fallback
         (ai_fallback.get_ai_fallback) የመጨረሻ አማራጭ ሆኖ ይሞከራል።

    ስኬታማ ውጤት ባገኘ ቁጥር (Jina/TF-IDF resolved ወይም AI fallback resolved)
    save_context() ይጠራል፣ ስለዚህ ቀጣይ follow-up ጥያቄ ይህን context ያገኛል።
    """
    user_id = kwargs.get("user_id", 0)
    settings = kwargs.get("settings") or {}
    group_id = settings.get("group_id")

    empty_result = {
        "reply": None,
        "resend_board": False,
        "resend_nekay": False,
        "resend_remaining": False,
        "cancel_number": None,
        "change_number": None,
        "type_change": None,
        "why_not_registered": None,
        "my_numbers_query": False,
        "number_owner_query": None,
        "payment_claim": False,
    }

    def _save_context_safe(used_intent: str, reply: str):
        if reply and user_id and group_id:
            try:
                from ai_fallback import save_context
                save_context(
                    user_id, group_id, used_intent,
                    _build_game_data_slice(kwargs), reply,
                )
            except Exception:
                pass

    # ── STEP 1: ግልፅ booking pattern ከሆነ → intent detection skip ──
    price_full = float(settings.get("price_full") or 0)
    price_half = float(settings.get("price_half") or 0)
    try:
        parsed = parse_numbers(text, price_full=price_full, price_half=price_half)
    except Exception as e:
        logger.warning(f"[parse_numbers] Error: {e}")
        parsed = None

    if parsed and parsed.get("is_clear_pattern", True):
        return dict(empty_result)

    # ── STEP 2: booking ካልሆነ → Jina መጀመሪያ ──────────────────────
    from jina_brain import jina_detect_intent, jina_is_ready

    if jina_is_ready():
        try:
            jina_intent, jina_score, jina_available = await jina_detect_intent(text)
        except Exception as e:
            logger.warning(f"[Jina] detect error: {e}")
            jina_intent, jina_score, jina_available = "unknown", 0.0, False

        # ✅ 2a: Jina በራስ መተማመን intent መልሷል → ተጠቀም
        if jina_intent != "unknown":
            result = get_response(text=text, intent=jina_intent, score=jina_score, **kwargs)
            _save_context_safe(jina_intent, result.get("reply"))
            return result

        # ⚠️ 2b: Jina ሰርቷል ግን "unknown" መለሰ (ዝቅተኛ score) —
        # latin ጽሁፍ ከሆነ TF-IDF ሁለተኛ ሙከራ ያድርግ
        if jina_available and _has_latin_chars(text):
            tfidf_intent, tfidf_score = detect_intent(text)
            if tfidf_score >= TFIDF_LATIN_THRESHOLD:
                logger.info(
                    f"[Responder] 🔤 Latin retry via TF-IDF | text='{text[:40]}' | "
                    f"intent={tfidf_intent}({tfidf_score:.3f}) ≥ {TFIDF_LATIN_THRESHOLD}"
                )
                result = get_response(text=text, intent=tfidf_intent, score=tfidf_score, **kwargs)
                _save_context_safe(tfidf_intent, result.get("reply"))
                return result

        # ❌ 2c: Jina ራሱ ሙሉ ለሙሉ ወድቋል (rate limit/API/network error)
        # → TF-IDF ሙሉ ቁጥጥር ይያዝ (legacy thresholds በራሱ በ get_response ውስጥ)
        if not jina_available:
            logger.warning(
                f"[Responder] 🚨 Jina completely down — TF-IDF full control | text='{text[:40]}'"
            )
            tfidf_intent, tfidf_score = detect_intent(text)
            result = get_response(text=text, intent=tfidf_intent, score=tfidf_score, **kwargs)
            _save_context_safe(tfidf_intent, result.get("reply"))
            return result

        # ↓ Jina available ግን (latin አይደለም ወይም TF-IDF ደካማ) → STEP 3 (AI fallback)

    else:
        # Jina ready ካልሆነ (init አልተሳካም/keys የሉም) → TF-IDF ሙሉ ቁጥጥር
        logger.warning(f"[Responder] 🚨 Jina not ready — TF-IDF full control | text='{text[:40]}'")
        tfidf_intent, tfidf_score = detect_intent(text)
        result = get_response(text=text, intent=tfidf_intent, score=tfidf_score, **kwargs)
        _save_context_safe(tfidf_intent, result.get("reply"))
        return result

    # ── STEP 3: Jina "unknown" (available, non-latin ወይም latin retry ደካማ) → AI fallback (last resort) ──
    if user_id and group_id:
        try:
            from ai_fallback import get_ai_fallback, save_context
            game_data = _build_game_data_slice(kwargs)
            ai_reply = await get_ai_fallback(
                text=text, user_id=user_id, group_id=group_id,
                game_data=game_data or None,
            )
            if ai_reply:
                save_context(user_id, group_id, "ai_fallback", game_data, ai_reply)
                res = dict(empty_result)
                res["reply"] = ai_reply
                return res
        except Exception as e:
            logger.warning(f"[AI Fallback] Error: {e}")

    return dict(empty_result)
