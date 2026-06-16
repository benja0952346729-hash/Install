import re
import math
import random
from collections import defaultdict
from rapidfuzz import fuzz

# ================================================================
# AMHARIC → LATIN TRANSLITERATOR
# ================================================================

FIDEL_TO_LATIN = {
    # ሀ family
    "ሀ": "ha", "ሁ": "hu", "ሂ": "hi", "ሃ": "ha", "ሄ": "he", "ህ": "h", "ሆ": "ho",
    "ሐ": "ha", "ሑ": "hu", "ሒ": "hi", "ሓ": "ha", "ሔ": "he", "ሕ": "h", "ሖ": "ho",
    # ለ family
    "ለ": "le", "ሉ": "lu", "ሊ": "li", "ላ": "la", "ሌ": "le", "ል": "l", "ሎ": "lo",
    # መ family
    "መ": "me", "ሙ": "mu", "ሚ": "mi", "ማ": "ma", "ሜ": "me", "ም": "m", "ሞ": "mo",
    # ሰ family
    "ሰ": "se", "ሱ": "su", "ሲ": "si", "ሳ": "sa", "ሴ": "se", "ስ": "s", "ሶ": "so",
    "ሠ": "se", "ሡ": "su", "ሢ": "si", "ሣ": "sa", "ሤ": "se", "ሥ": "s", "ሦ": "so",
    # ሸ family
    "ሸ": "she", "ሹ": "shu", "ሺ": "shi", "ሻ": "sha", "ሼ": "she", "ሽ": "sh", "ሾ": "sho",
    # ቀ family
    "ቀ": "qe", "ቁ": "qu", "ቂ": "qi", "ቃ": "qa", "ቄ": "qe", "ቅ": "q", "ቆ": "qo",
    "ቈ": "qo", "ቊ": "qu", "ቋ": "qua", "ቌ": "qe", "ቍ": "qu",
    # በ family
    "በ": "be", "ቡ": "bu", "ቢ": "bi", "ባ": "ba", "ቤ": "be", "ብ": "b", "ቦ": "bo",
    # ተ family
    "ተ": "te", "ቱ": "tu", "ቲ": "ti", "ታ": "ta", "ቴ": "te", "ት": "t", "ቶ": "to",
    # ቸ family
    "ቸ": "che", "ቹ": "chu", "ቺ": "chi", "ቻ": "cha", "ቼ": "che", "ች": "ch", "ቾ": "cho",
    # ነ family
    "ነ": "ne", "ኑ": "nu", "ኒ": "ni", "ና": "na", "ኔ": "ne", "ን": "n", "ኖ": "no",
    "ኘ": "nye", "ኙ": "nyu", "ኚ": "nyi", "ኛ": "nya", "ኜ": "nye", "ኝ": "ny", "ኞ": "nyo",
    # አ family
    "አ": "a", "ኡ": "u", "ኢ": "i", "ኣ": "a", "ኤ": "e", "እ": "e", "ኦ": "o",
    # ከ family
    "ከ": "ke", "ኩ": "ku", "ኪ": "ki", "ካ": "ka", "ኬ": "ke", "ክ": "k", "ኮ": "ko",
    # ወ family
    "ወ": "we", "ዉ": "wu", "ዊ": "wi", "ዋ": "wa", "ዌ": "we", "ው": "w", "ዎ": "wo",
    # የ family
    "የ": "ye", "ዩ": "yu", "ዪ": "yi", "ያ": "ya", "ዬ": "ye", "ይ": "y", "ዮ": "yo",
    # ደ family
    "ደ": "de", "ዱ": "du", "ዲ": "di", "ዳ": "da", "ዴ": "de", "ድ": "d", "ዶ": "do",
    # ዘ family
    "ዘ": "ze", "ዙ": "zu", "ዚ": "zi", "ዛ": "za", "ዜ": "ze", "ዝ": "z", "ዞ": "zo",
    # ዠ family
    "ዠ": "zhe", "ዡ": "zhu", "ዢ": "zhi", "ዣ": "zha", "ዤ": "zhe", "ዥ": "zh", "ዦ": "zho",
    # ጀ family
    "ጀ": "je", "ጁ": "ju", "ጂ": "ji", "ጃ": "ja", "ጄ": "je", "ጅ": "j", "ጆ": "jo",
    # ገ family
    "ገ": "ge", "ጉ": "gu", "ጊ": "gi", "ጋ": "ga", "ጌ": "ge", "ግ": "g", "ጎ": "go",
    # ጠ family
    "ጠ": "te", "ጡ": "tu", "ጢ": "ti", "ጣ": "ta", "ጤ": "te", "ጥ": "t", "ጦ": "to",
    # ጰ family
    "ጰ": "pe", "ጱ": "pu", "ጲ": "pi", "ጳ": "pa", "ጴ": "pe", "ጵ": "p", "ጶ": "po",
    # ጸ/ፀ family (same sound)
    "ጸ": "tse", "ጹ": "tsu", "ጺ": "tsi", "ጻ": "tsa", "ጼ": "tse", "ጽ": "ts", "ጾ": "tso",
    "ፀ": "tse", "ፁ": "tsu", "ፂ": "tsi", "ፃ": "tsa", "ፄ": "tse", "ፅ": "ts", "ፆ": "tso",
    # ፈ family
    "ፈ": "fe", "ፉ": "fu", "ፊ": "fi", "ፋ": "fa", "ፌ": "fe", "ፍ": "f", "ፎ": "fo",
    # ፐ family
    "ፐ": "pe", "ፑ": "pu", "ፒ": "pi", "ፓ": "pa", "ፔ": "pe", "ፕ": "p", "ፖ": "po",
    # punctuation
    "።": ".", "፣": ",", "፤": ";", "፥": ":", "፦": ":-", "፧": "?", "፨": "*",
}

def to_latin(text: str) -> str:
    """Convert any mix of Amharic + Latin text to unified Latin."""
    result = []
    for ch in text:
        if ch in FIDEL_TO_LATIN:
            result.append(FIDEL_TO_LATIN[ch])
        else:
            result.append(ch.lower())
    return "".join(result)


# ================================================================
# LATIN → AMHARIC KEYWORD MAP (kept for backward compat / display)
# ================================================================

LATIN_TO_AMHARIC = {
    "yaz": "ያዝ", "yazat": "ያዛት", "yazachew": "ያዛቸው",
    "tsafligni": "ፃፍልኝ", "tsaf": "ፃፍ", "yazligni": "ያዝልኝ",
    "mezgib": "መዝግብ", "mezgibat": "መዝግባት", "mezgibligni": "መዝግብልኝ",
    "qeri": "ቀሪ", "keri": "ቀሪ",
    "qitr": "ቁጥር", "kitr": "ቁጥር",
    "min ale": "ምን አለ",
    "sint qere": "ስንት ቀረ", "sint kere": "ስንት ቀረ",
    "sint ale": "ስንት አለ",
    "qeri ale": "ቀሪ አለ", "keri ale": "ቀሪ አለ",
    "qitr ale": "ቁጥር አለ", "kitr ale": "ቁጥር አለ",
    "yalteyaze": "ያልተያዘ", "yalteyazun": "ያልተያዙ",
    "nekay": "ነቃይ", "tenekay": "ተነቃይ", "nkay": "ነቃይ",
    "nekay ale": "ነቃይ አለ", "nekay zerzir": "ነቃይ ዘርዝር",
    "nekay neger": "ነቃይ ንገር", "nekay lak": "ነቃይ ላክ",
    "nekayoch": "ነቃዮች", "mishit ale": "ሚሸጥ አለ",
    "nekay zerzirligni": "ነቃይ ዘርዝርልኝ",
    "nekay negerign": "ነቃይ ንገረኝ",
    "nekay qitroch": "ነቃይ ቁጥሮች", "nekay kitroch": "ነቃይ ቁጥሮች",
    "tenekay ale": "ተነቃይ አለ",
    "nekay asayen": "ነቃይ አሳየኝ",
    "nekay asay": "ነቃይ አሳይ",
    "nekay asaygn": "ነቃይ አሳይ",
    "nekay awqegn": "ነቃይ አውቀኝ",
    "nekay asayi": "ነቃይ አሳይ",
    "hulunm teyazuwal": "ሁሉም ተይዘዋል",
    "hulunm teyaze": "ሁሉም ተያዘ",
    "hulunm alteyazum": "ሁሉም አልተያዙም",
    "qeri lak": "ቀሪ ላክ", "keri lak": "ቀሪ ላክ",
    "qitr lak": "ቁጥር ላክ", "kitr lak": "ቁጥር ላክ",
    "kutr lak": "ቁጥር ላክ", "cutr lak": "ቁጥር ላክ",
    "kutr ale": "ቁጥር አለ", "cutr ale": "ቁጥር አለ",
    "kutr": "ቁጥር", "cutr": "ቁጥር",
    "qeri asayen": "ቀሪ አሳየኝ", "keri asayen": "ቀሪ አሳየኝ",
    "tolo tolo qeri lak": "ቶሎ ቶሎ ቀሪ ላክ", "tolo tolo keri lak": "ቶሎ ቶሎ ቀሪ ላክ",
    "teyaze": "ተያዘ", "teyazo": "ተይዞ", "teyazuwal": "ተይዙዋል",
    "awo": "አዎ", "aydelem": "አይደለም",
    "tnx": "አመሰግናለሁ", "thanks": "አመሰግናለሁ",
    "ale": "አለ",
    "serzew": "ሰርዝ", "srez": "ሰርዝ", "serz": "ሰርዝ",
    "shitew": "ሽጠው", "shtew": "ሽጠው", "shitkhew": "ሽጠው", "shetek": "ሽጠው",
    "atfaw": "አጥፋው", "atfa": "አጥፋው", "yitfa": "ይጥፋ",
    "awta": "አውጣ", "awuta": "አውጣ",
    "alfeligm": "አልፈልግም", "alfelegim": "አልፈልግም", "alfelegm": "አልፈልግም",
    "tenekelku": "ተነቀልኩ", "teneklku": "ተነቀልኩ", "nekelku": "ተነቀልኩ",
    "qitr tenekelk": "ቁጥር ተነቀለ", "kitr tenekelk": "ቁጥር ተነቀለ",
    "number tenekelk": "ቁጥር ተነቀለ",
    "lmin shitkhew": "ለምን ሸጥከው", "lmin shitkh": "ለምን ሸጥከው",
    "lmin shetek": "ለምን ሸጥከው", "lemin shetek": "ለምን ሸጥከው",
    "lmin tenklaleh": "ለምን ትነቅላለህ", "lmin tinklaleh": "ለምን ትነቅላለህ",
    "why shetek": "ለምን ሸጥህ", "why teneklaleh": "ለምን ትነቅላለህ",
    "kefye nekelk": "ከፍዬ ነቀልክ", "kefye neklek": "ከፍዬ ነቀልክ",
    "tekeflo nekelk": "ተከፍሎ ነቀልክ", "tekefilo neklek": "ተከፍሎ ነቀልክ",
    "kefye shetk": "ከፍዬ ሸጥክ", "kefye shetkh": "ከፍዬ ሸጥክ",
    "likeyalew lmin": "ልክያለው ለምን", "likyalew lemin": "ልክያለው ለምን",
    "telkuwal lmin nekelk": "ተልኩዋል ለምን ነቀልክ",
    "telkual lmin": "ተልኩዋል ለምን",
    "like tineklaleh": "ልኬ ትነቅላለህ", "lke tinklaleh": "ልኬ ትነቅላለህ",
    "lkuwal lmin": "ልክያለው ለምን", "selkuwal lemin": "ልክያለው ለምን",
    "payment ale lmin": "ከፍዬ ሸጥክ", "lefkuwal lmin": "ልክያለው ለምን",
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
    "wede": "ወደ",
    "qeyir": "ቀይር", "keyir": "ቀይር",
    "qeyirew": "ቀይረው", "keyirew": "ቀይረው",
    "qeyirligni": "ቀይርልኝ", "keyirligni": "ቀይርልኝ",
    "lewet": "ለወጥ", "lewetew": "ለወጠው", "lewetligni": "ለወጥልኝ",
    "azawir": "አዛውር", "azawrew": "አዛውረው",
    "yihun": "ይሁን",
    "tew": "ተው",
    "arig": "አርግ", "arigew": "አርገው",
    "adrg": "አድርግ", "adrgew": "አድርገው",
    "change arig": "ቀይር አርግ",
    "change adrig": "ቀይር አድርግ",
    "change arigew": "ቀይር አርገው",
    "account lak": "አካውንት ላክ",
    "acount lak": "አካውንት ላክ",
    "account lai": "አካውንት ላኪ",
    "acount lai": "አካውንት ላኪ",
    "account info": "አካውንት ላክ",
    "acount info": "አካውንት ላክ",
    "account negeregn": "አካውንት ንገረኝ",
    "acount negeregn": "አካውንት ንገረኝ",
    "account asayen": "አካውንት አሳየኝ",
    "acount asayen": "አካውንት አሳየኝ",
    "account yetale": "አካውንት የታለ",
    "acount yetale": "አካውንት የታለ",
    "account ale": "አካውንት ካለ",
    "acount ale": "አካውንት ካለ",
    "nigid bank account": "ንግድ ባንክ አካውንት",
    "nigid bank lak": "ንግድ ባንክ ላክ",
    "nigid bank number": "ንግድ ባንክ ቁጥር",
    "nigid bank": "ንግድ ባንክ",
    "commercial bank": "ንግድ ባንክ",
    "bank account": "ባንክ አካውንት",
    "cbe account": "ሲቢኢ አካውንት",
    "cbe lak": "ሲቢኢ ላክ",
    "cbe number": "ሲቢኢ ቁጥር",
    "cbe": "ሲቢኢ",
    "telebirr account": "ቴሌብር አካውንት",
    "telebirr acount": "ቴሌብር አካውንት",
    "telebirr lak": "ቴሌብር ላክ",
    "telebirr number": "ቴሌብር ቁጥር",
    "telebirr": "ቴሌብር",
    "telebr account": "ቴሌብር አካውንት",
    "telebr lak": "ቴሌብር ላክ",
    "telebr number": "ቴሌብር ቁጥር",
    "telebr": "ቴሌብር",
    "awash account": "አዋሽ አካውንት",
    "awash acount": "አዋሽ አካውንት",
    "awash lak": "አዋሽ ላክ",
    "awash number": "አዋሽ ቁጥር",
    "awash numer": "አዋሽ ቁጥር",
    "awash": "አዋሽ",
    "payment number": "የሚከፈልበት ቁጥር",
    "payment info": "አካውንት ላክ",
    "yemikefelbew number": "የሚከፈልበት ቁጥር",
    "account": "አካውንት",
    "acount": "አካውንት",
    "acawnt": "አካውንት",
    "akownt": "አካውንት",
    "akawnt": "አካውንት",
    "akaunt": "አካውንት",
    "akount": "አካውንት",
    "acwnt": "አካውንት",
    "bemulu areg": "በሙሉ አርግ",
    "bemulu adrig": "በሙሉ አድርግ",
    "bemulu yihun": "በሙሉ ይሁን",
    "begmash areg": "በግማሽ አርግ",
    "begmash adrig": "በግማሽ አድርግ",
    "begmash yihun": "በግማሽ ይሁን",
    "gmash areg": "ግማሽ አርግ",
    "gmash yihun": "ግማሽ ይሁን",
    "mulu areg": "ሙሉ አርግ",
    "mulu yihun": "ሙሉ ይሁን",
    "lmin alyazkilgnim": "ለምን አልያዝክልኝም",
    "lmin altsafkilgnim": "ለምን አልፃፍክልኝም",
    "lmin almezegbkegnim": "ለምን አልመዘገብከኝም",
    "lmin qitire alteyazem": "ለምን ቁጥሬ አልተያዘም",
    "lmin kitire alteyazem": "ለምን ቁጥሬ አልተያዘም",
    "lmin algeba": "ለምን አልገባም",
    "lmin sayiyaz qere": "ለምን ሳይያዝ ቀረ",
    "lmin sayiyaz kere": "ለምን ሳይያዝ ቀረ",
    "lmin alteyazelign": "ለምን አልተያዘልኝም",
    "lmin altemezegebem": "ለምን አልተመዘገበም",
    "qitire lmin alteyazem": "ቁጥሬ ለምን አልተያዘም",
    "kitire lmin alteyazem": "ቁጥሬ ለምን አልተያዘም",
    "lmin alasgegabhegnim": "ለምን አላስገባኸኝም",
}


# ================================================================
# UNIFIED NORMALIZER  (Amharic OR Latin → Latin)
# ================================================================

def normalize_to_latin(text: str) -> str:
    """
    Converts any text (pure Amharic, pure Latin, or mixed) → unified Latin.
    Steps:
      1. Character-by-character: Ethiopic char → Latin via FIDEL_TO_LATIN
      2. Lowercase everything
      3. Collapse multiple spaces
    This replaces the old normalize_amharic() + translate_latin() pipeline.
    """
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
# CHANGE NUMBER PATTERN DETECTOR
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


# ================================================================
# TYPE CHANGE DETECTOR
# ================================================================

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
# INTENT EXAMPLES  (stored as Amharic — converted at build time)
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
    "greeting": [
        "ሰላም", "እንዴት ነህ", "ደና አደርክ", "ደና ዋልክ",
        "እንዴት አመሸህ", "ሰላም ዋልክ", "ሰላም አመሸህ",
        "በሰላም አደርክ", "እንዴት አረፈድክ", "ጤና ይስጥልኝ",
        "እንደምን ናችሁ", "እንደምን አላችሁ", "እንዴት ናችሁ",
        "ሰላም እንዴት ነህ", "ሰላም ወዳጄ", "ሰላምታ",
        "hi", "hello", "hey",
        "selam", "salam", "selem",
        "endet neh", "indet neh",
        "dena aderk", "dena walk",
        "tena yistilign",
        "endemen nachuh",
    ],
    "cancel_number": [
        "አልፈልግም", "ሽጠው", "አጥፋው", "ይጥፋ", "ሰርዝ", "አውጣ",
        "አጥፋልኝ", "ሰርዝልኝ", "አውጣልኝ",
        "ቁጥሩን ሰርዝ", "ቁጥሩን አጥፋ", "ቁጥሩን አውጣ",
        "አልፈለኩም", "አልፈልገውም", "አልፈልጋቸውም",
        "አያስፈልገኝም", "cancel ነው", "drop አርግ",
        "ትቼዋለሁ", "cancel አርግ", "ሰርዝልኝ ቁጥሩን",
        "alfeligm", "alfelegim", "alfelegm",
        "serzew", "srez", "serz",
        "atfaw", "atfa", "yitfa",
        "awta", "awuta",
        "cancel", "drop",
    ],
    "complaint_removed": [
        "ተነቀልኩ", "ቁጥሬ ተነቀለ", "ቁጥሬ ጠፋ", "ቁጥሬ ሄደ",
        "ለምን ተነቀልኩ", "ተነቀልኩ እኮ",
        "ቁጥሬ የለም", "ቁጥሬ ጠፋ ለምን", "ቁጥሬ ሄደ ለምን",
        "ቁጥሬ ተቀነሰ", "ቁጥሬ ተወሰደ ለምን",
        "ቁጥሬ ለምን ተነቀለ", "ቁጥሬ ለምን ጠፋ",
        "ቁጥሬ ለምን ሄደ", "ቁጥሬ ለምን ተወሰደ",
        "ቁጥሬ ተነቅሏል", "ቁጥሬ ጠፍቷል",
        "tenekelku", "teneklku", "nekelku",
        "number tenekelk", "number hede", "number yellem",
        "lmin tenekelku", "tenekelku eko",
        "lmin nekelku", "lmin tenekelk",
    ],
    "complaint_why_sold": [
        "ለምን ሸጥከው", "ለምን ሸጠከው", "ለምን ትነቅላለህ",
        "ለምን ትሸጣለህ", "ለምን ሸጥህ", "ቁጥሬን ለምን ሸጥህ",
        "ቁጥሬን ለምን ነቀልክ", "ለምን ቁጥሬን ሸጥከው",
        "ለምን ቁጥሬን ነቀልክ", "ቁጥሬ ለምን ሄደ",
        "lmin shitkhew", "lmin shitkh",
        "lmin shetek", "lemin shetek",
        "lmin tenklaleh", "lmin tinklaleh",
        "why shetek", "why teneklaleh",
    ],
    "complaint_paid_removed": [
        "ከፍዬ ነቀልክ", "ተከፍሎ ነቀልክ", "ከፍዬ ሸጥክ",
        "ልክያለው እኮ ለምን ሸጥክ", "ተልኩዋል ለምን ነቀልክ",
        "ልክያለው ለምን", "ልኬ ትነቅላለህ",
        "ብሬ ተልኳል ለምን ነቀልክ", "ገንዘብ ልኬ ነቀልክ",
        "ከፈልኩ ለምን ሸጥክ", "ልኩዋል ለምን", "ተልኩዋል ሸጥክ",
        "payment ላኩ ለምን ሸጥክ", "ከፍዬ ቁጥሬ ሄደ",
        "kefye nekelk", "kefye neklek",
        "tekeflo nekelk", "tekefilo neklek",
        "kefye shetk", "kefye shetkh",
        "likeyalew lmin", "likyalew lemin",
        "telkuwal lmin nekelk", "telkual lmin",
        "like tineklaleh", "lke tinklaleh",
        "lkuwal lmin", "selkuwal lemin",
        "payment ale lmin", "lefkuwal lmin",
    ],
    "change_number": [
        "ወደ ቀይር", "ቀይር", "ቀይረው", "ቀይርልኝ",
        "ለወጥ", "ለወጠው", "ለወጥልኝ", "አዛውር", "አዛውረው",
        "ቁጥሩን ቀይር", "ቁጥሩን ለወጥ", "ቁጥሬን ቀይርልኝ",
        "change አርግ", "ቁጥሩን change አርግ",
        "qeyir", "keyir", "qeyirew", "keyirew",
        "lewet", "lewetew", "azawir", "azawrew",
        "change arig", "change adrig",
        "wede qeyir", "wede keyir",
    ],
    "account_query": [
        "አካውንት", "አካውንት ላክ", "አካውንት ምንድን ነው",
        "ቴሌብር", "አዋሽ", "ሲቢኢ", "ንግድ ባንክ",
        "ቴሌብር ቁጥር", "አዋሽ ቁጥር", "ሲቢኢ ቁጥር",
        "የሚከፈልበት ቁጥር", "የባንክ ቁጥር", "ባንክ አካውንት",
        "ላኩ ወዴት", "ገንዘብ ወዴት ልላክ",
        "ቴሌብር አካውንት ስጠኝ", "ወዴት ልከፍል",
        "account lak", "acount lak",
        "account info", "acount info",
        "telebirr", "telebr",
        "awash", "cbe",
        "nigid bank", "commercial bank",
        "payment number", "payment info",
    ],
    "type_change": [
        "በሙሉ አርግ", "በሙሉ አድርግ", "በሙሉ ይሁን", "በሙሉ ቀይረው",
        "ሙሉ አርግ", "ሙሉ ይሁን",
        "በግማሽ አርግ", "በግማሽ አድርግ", "በግማሽ ይሁን", "በግማሽ ቀይረው",
        "ግማሽ አርግ", "ግማሽ ይሁን",
        "gmash areg", "bemulu areg", "begmash areg",
        "bemulu adrig", "begmash adrig",
        "bemulu yihun", "begmash yihun",
        "mulu areg", "mulu yihun",
    ],
    "why_not_registered": [
        "ለምን አልያዝክልኝም", "ለምን አልፃፍክልኝም", "ለምን አልመዘገብከኝም",
        "ለምን ቁጥሬ አልተያዘም", "ለምን ቁጥሩ አልተያዘም",
        "ቁጥሩ ለምን አልተያዘም", "ለምን አልገባም", "ለምን ሳይያዝ ቀረ",
        "ለምን አልያዘልኝም", "ለምን አልተመዘገበም",
        "ለምን አልተያዘልኝም", "ለምን አላስገባኸኝም",
        "lmin alyazkilgnim", "lmin altsafkilgnim",
        "lmin qitire alteyazem", "lmin kitire alteyazem",
        "lmin algeba",
        "lmin sayiyaz qere", "lmin sayiyaz kere",
        "lmin alteyazelign", "lmin altemezegebem",
        "lmin alasgegabhegnim",
    ],
}


# ================================================================
# N-GRAM ENGINE  (now operates on Latin)
# ================================================================

def get_ngrams(text: str, n: int = 2) -> list:
    """text is already Latin-normalized before calling this."""
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
            latin = normalize_to_latin(ex)   # ← unified normalizer
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
    latin = normalize_to_latin(text)    # ← unified normalizer
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


# ================================================================
# MODEL BUILD
# ================================================================

print("🔧 Building intent vectors...")
TFIDF_VECTORS, GLOBAL_IDF = build_tfidf(INTENT_EXAMPLES)
print(f"✅ Intent engine ready — {len(TFIDF_VECTORS)} intents loaded")


# ================================================================
# DETECT INTENT  (keyword guards also use normalize_to_latin)
# ================================================================

def detect_intent(text: str) -> tuple:
    latin = normalize_to_latin(text)
    numbers_in_text = re.findall(r"\d+", text)

    # ── account keywords ──────────────────────────────────────────
    ACCOUNT_KW_LAT = [
        "akawnt", "akaunt", "akount", "akawnt",
        "telebirr", "telebr", "awash", "cbe",
        "nigid bank", "bank akawnt",
        "yemikefelbew qitr", "yebank qitr",
    ]
    # Also check raw Amharic keywords that to_latin covers:
    ACCOUNT_KW_AMH_LAT = [
        normalize_to_latin("አካውንት"),
        normalize_to_latin("ቴሌብር"),
        normalize_to_latin("አዋሽ"),
        normalize_to_latin("ሲቢኢ"),
        normalize_to_latin("ንግድ ባንክ"),
        normalize_to_latin("የሚከፈልበት ቁጥር"),
        normalize_to_latin("የባንክ ቁጥር"),
    ]
    all_account_kw = ACCOUNT_KW_LAT + ACCOUNT_KW_AMH_LAT
    if any(kw in latin for kw in all_account_kw):
        return "account_query", 1.0

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
            normalize_to_latin("ቀይረው"),
            "areg", "adrig", "yihun", "qeyir", "qeyirew", "keyir", "keyirew",
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
    ] + ["alfeligm", "alfelegim", "alfelegm", "serzew", "serz", "atfaw", "atfa", "awta"]
    has_cancel = any(w in latin for w in CANCEL_LAT)
    if len(numbers_in_text) == 1 and has_cancel:
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
                          "change_number", "type_change"):
                bonus += 0.08
            elif intent != "account_query":
                bonus -= 0.10
        if not numbers_in_text and intent == "booking":
            bonus -= 0.15
        if intent == "greeting" and not numbers_in_text:
            bonus += 0.05
        if intent in ("complaint_removed", "complaint_why_sold",
                      "complaint_paid_removed") and not numbers_in_text:
            bonus += 0.05
        scores[intent] = max(0.0, scores[intent] + bonus)

    best_intent = max(scores, key=scores.get)
    best_score  = scores[best_intent]
    return best_intent, best_score


# ================================================================
# RESPONSES  (unchanged)
# ================================================================

RESPONSES = {
    "booking_success_normal": [
        "እሺ ገቢ 🙏", "እሺ ቤተሰብ 🙏", "እሺ ገቢ እንዳይረሳ 🙏", "እሺ ወዳጄ 🥰",
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
    "greeting": [
        "ፈጣሪ የተመሰገነ ይሁን 🙏", "ፈጣሪ የተመሰገነ ይሁን ወዳጄ 🙏",
        "ይመስገን እንዴት ነህ ወዳጄ 🙏", "ፈጣሪ ይመስገን እንኳን በደና መጣህ 🙏",
        "በጉጉት ስንጠብቅህ ነበር እንኳን በደና መጣህ 🙏", "ሰላም እንኳን በሰላም መጣህ 🙏",
    ],
    "greeting_help": [
        "በምን ላግዝህ? 🙏", "ምን እናግዝህ ትፈልጋለህ? 🙏",
    ],
    "cancel_number_ack": ["እሺ ተሰርዟል 🙏", "እሺ ተነቅሏል 🙏"],
    "complaint_removed_taken": [
        "አዎ ገቢ ማረግ ረሳክ የጫወታው ባህሪ ነው 🙏",
        "ቤተሰብ ገቢ ሳታርግ ቁጥሩ ይለቀቃል 🙏",
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
        "ቁጥሩ የእርስዎ አይደለም 🙏",
        "{from_num} የእርስዎ ቁጥር አይደለም 🙏",
    ],
    "change_number_target_taken": [
        "{to_num} ተይዟል ቤተሰብ ሌላ ምረጥ 🙏",
        "ቤተሰብ {to_num} ክፍት አይደለም ሌላ ምረጥ 🙏",
        "{to_num} ቀድሞ ተወስዷል 🙏",
    ],
    "change_number_target_paid": [
        "{to_num} ✅ ተከፍሏል መቀየር አይቻልም 🙏",
        "ቤተሰብ {to_num} paid ነው አይቀየርም 🙏",
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
}


# ================================================================
# MAIN RESPONDER  (logic unchanged — only normalizer calls updated)
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
) -> dict:

    THRESHOLD_RESPOND  = 0.25
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
    }

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
        return result

    intent, score = detect_intent(text)

    if score < THRESHOLD_CONFUSED:
        return result
    if score < THRESHOLD_RESPOND:
        return result

    if intent == "account_query":
        payment_info = settings.get("payment_info", "")
        if payment_info:
            result["reply"] = _extract_account_lines(payment_info)
        return result

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

    if intent == "why_not_registered":
        numbers_found = re.findall(r"\d+", text)
        target_num = int(numbers_found[0]) if numbers_found else None
        result["why_not_registered"] = {"number": target_num}
        return result

    if intent == "booking":
        if countdown_seconds > 0:
            mins = countdown_seconds // 60
            secs = countdown_seconds % 60
            if mins >= 1:
                result["reply"] = f"ቲንሽ ይጠብቁ {mins} ደቂቃ ቀርቱዋል ያልከፈለ ሊወጣ 🙏"
            else:
                result["reply"] = f"{secs} ሴኮንድ ቀርቱዋል ቲንሽ ይጠብቁ ነቃይ ካለ አሳውቃለው 🙏"
        return result

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

    if intent == "cancel_number":
        numbers_found = re.findall(r"\d+", text)
        if numbers_found:
            num = int(numbers_found[0])
            result["reply"] = random.choice(RESPONSES["cancel_number_ack"])
            result["cancel_number"] = num
        return result

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

    if intent == "complaint_why_sold":
        result["reply"] = random.choice(RESPONSES["complaint_why_sold"])
        return result

    if intent == "complaint_paid_removed":
        result["reply"] = random.choice(RESPONSES["complaint_paid_removed"])
        return result

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

    if intent == "remaining_send":
        result["reply"] = random.choice(RESPONSES["remaining_send_ack"])
        result["resend_remaining"] = True
        return result

    if intent == "remaining_query":
        result["resend_remaining"] = True
        return result

    if intent == "all_taken_query":
        if remaining_count == 0 and not nekay_list:
            return result
        elif nekay_list:
            result["reply"] = random.choice(RESPONSES["all_taken_nekay"])
        else:
            result["resend_remaining"] = True
        return result

    if intent == "greeting":
        msg = random.choice(RESPONSES["greeting"])
        if random.random() < 0.20:
            msg += " " + random.choice(RESPONSES["greeting_help"])
        result["reply"] = msg
        return result

    return result
