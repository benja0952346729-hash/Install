import re
import math
import random
from collections import defaultdict
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
    "nekay": "ነቃይ", "tenekay": "ተነቃይ", "nkay": "ነቃይ",
    "nekay ale": "ነቃይ አለ", "nekay zerzir": "ነቃይ ዘርዝር",
    "nekay neger": "ነቃይ ንገር", "nekay lak": "ነቃይ ላክ",
    "nekayoch": "ነቃዮች", "mishit ale": "ሚሸጥ አለ",
    "nekay zerzirligni": "ነቃይ ዘርዝርልኝ",
    "nekay negerign": "ነቃይ ንገረኝ",
    "nekay qitroch": "ነቃይ ቁጥሮች",
    "tenekay ale": "ተነቃይ አለ",
    "nekay asayen": "ነቃይ አሳየኝ",
    "nekay asay": "ነቃይ አሳይ",
    "nekay asaygn": "ነቃይ አሳይ",
    "nekay awqegn": "ነቃይ አውቀኝ",
    "nekay asayi": "ነቃይ አሳይ",
    "hulunm teyazuwal": "ሁሉም ተይዘዋል",
    "hulunm teyaze": "ሁሉም ተያዘ",
    "hulunm alteyazum": "ሁሉም አልተያዙም",
    "qeri lak": "ቀሪ ላክ", "qitr lak": "ቁጥር ላክ",
    "kutr lak": "ቁጥር ላክ", "cutr lak": "ቁጥር ላክ",
    "kutr ale": "ቁጥር አለ", "cutr ale": "ቁጥር አለ",
    "kutr": "ቁጥር", "cutr": "ቁጥር",
    "qeri asayen": "ቀሪ አሳየኝ",
    "tolo tolo qeri lak": "ቶሎ ቶሎ ቀሪ ላክ",
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
    "qitr tenekelk": "ቁጥር ተነቀለ", "number tenekelk": "ቁጥር ተነቀለ",
    "lmin shitkhew": "ለምን ሸጥከው", "lmin shitkh": "ለምን ሸጥከው",
    "lmin shetek": "ለምን ሸጥህ", "lemin shetek": "ለምን ሸጥህ",
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
    "qeyir": "ቀይር", "qeyirew": "ቀይረው", "qeyirligni": "ቀይርልኝ",
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
    "lmin algeba": "ለምን አልገባም",
    "lmin sayiyaz qere": "ለምን ሳይያዝ ቀረ",
    "lmin alteyazelign": "ለምን አልተያዘልኝም",
    "lmin altemezegebem": "ለምን አልተመዘገበም",
    "qitire lmin alteyazem": "ቁጥሬ ለምን አልተያዘም",
    "lmin alasgegabhegnim": "ለምን አላስገባኸኝም",
}

def translate_latin(text: str) -> str:
    result = text.lower()
    for lat, amh in sorted(LATIN_TO_AMHARIC.items(), key=lambda x: -len(x[0])):
        result = result.replace(lat, amh)
    return result


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

CHANGE_CANCEL_WORDS = ["አልፈልግም", "ተው", "አጥፋ", "አጥፋው", "ሰርዝ", "ሰርዝልኝ"]
CHANGE_CONFIRM_WORDS = [
    "ቀይር", "ቀይረው", "ቀይርልኝ", "ይሁን",
    "አርግ", "አርገው", "አድርግ", "አድርገው", "change",
    "ለወጥ", "ለወጠው", "ለወጥልኝ", "አዛውር", "አዛውረው",
]
CHANGE_WEDE_WORDS = ["ወደ", "to"]

def detect_change_number(text: str):
    translated = translate_latin(text)
    normalized = normalize_amharic(translated)
    lower = normalized.lower()
    nums = re.findall(r"\d+", text)
    if len(nums) < 2:
        return None
    from_num = int(nums[0])
    to_num = int(nums[1])
    for wede in CHANGE_WEDE_WORDS:
        norm_wede = normalize_amharic(wede)
        if norm_wede in lower:
            return (from_num, to_num)
    has_cancel = any(normalize_amharic(w) in lower for w in CHANGE_CANCEL_WORDS)
    has_confirm = any(normalize_amharic(w) in lower for w in CHANGE_CONFIRM_WORDS)
    if has_cancel and has_confirm:
        return (from_num, to_num)
    if has_cancel:
        if "ነው" in lower or "new" in text.lower():
            return (from_num, to_num)
    return None


# ================================================================
# TYPE CHANGE DETECTOR
# ================================================================

def detect_type_change(text: str):
    translated = translate_latin(text)
    normalized = normalize_amharic(translated)
    lower = normalized.lower()

    TYPE_FULL_WORDS = ["በሙሉ", "ሙሉ"]
    TYPE_HALF_WORDS = ["በግማሽ", "ግማሽ"]

    is_full = any(normalize_amharic(w) in lower for w in TYPE_FULL_WORDS)
    is_half = any(normalize_amharic(w) in lower for w in TYPE_HALF_WORDS)

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
    "greeting": [
        "ሰላም", "እንዴት ነህ", "ደና አደርክ", "ደና ዋልክ",
        "እንዴት አመሸህ", "ሰላም ዋልክ", "ሰላም አመሸህ",
        "በሰላም አደርክ", "እንዴት አረፈድክ", "ጤና ይስጥልኝ",
        "እንደምን ናችሁ", "እንደምን አላችሁ", "እንዴት ናችሁ",
        "ሰላም እንዴት ነህ", "ሰላም ወዳጄ", "ሰላምታ",
        "hi", "hello", "hey", "ሰላም ነህ",
    ],
    "cancel_number": [
        "አልፈልግም", "ሽጠው", "አጥፋው", "ይጥፋ", "ሰርዝ", "አውጣ",
        "አጥፋልኝ", "ሰርዝልኝ", "አውጣልኝ",
        "ቁጥሩን ሰርዝ", "ቁጥሩን አጥፋ", "ቁጥሩን አውጣ",
        "አልፈለኩም", "አልፈልገውም", "አልፈልጋቸውም",
        "አያስፈልገኝም", "cancel ነው", "drop አርግ",
        "ትቼዋለሁ", "አልፈልገውም ቁጥሩን",
        "አልፈልገውም", "cancel አርግ", "ሰርዝልኝ ቁጥሩን",
        "ቁጥሩን አልፈልግም", "ቁጥሩን ሰርዝልኝ",
    ],
    "complaint_removed": [
        "ተነቀልኩ", "ቁጥሬ ተነቀለ", "ቁጥሬ ጠፋ", "ቁጥሬ ሄደ",
        "ለምን ተነቀልኩ", "ተነቀልኩ እኮ",
        "ቁጥሬ የለም", "ቁጥሬ ጠፋ ለምን", "ቁጥሬ ሄደ ለምን",
        "ቁጥሬ ተቀነሰ", "ቁጥሬ ተወሰደ ለምን",
    ],
    "complaint_why_sold": [
        "ለምን ሸጥከው", "ለምን ሸጠከው", "ለምን ትነቅላለህ",
        "ለምን ትሸጣለህ", "ለምን ሸጥህ", "ቁጥሬን ለምን ሸጥህ",
        "ቁጥሬን ለምን ነቀልክ", "ለምን ቁጥሬን ሸጥከው",
        "ለምን ቁጥሬን ነቀልክ", "ቁጥሬ ለምን ሄደ",
    ],
    "complaint_paid_removed": [
        "ከፍዬ ነቀልክ", "ተከፍሎ ነቀልክ", "ከፍዬ ሸጥክ",
        "ልክያለው እኮ ለምን ሸጥክ", "ተልኩዋል ለምን ነቀልክ",
        "ልክያለው ለምን", "ልኬ ትነቅላለህ",
        "ብሬ ተልኳል ለምን ነቀልክ", "ገንዘብ ልኬ ነቀልክ",
        "ከፈልኩ ለምን ሸጥክ", "ልኩዋል ለምን", "ተልኩዋል ሸጥክ",
        "ልኬ ሸጥክ", "ተልኩዋል እኮ",
        "payment ላኩ ለምን ሸጥክ", "ከፍዬ ቁጥሬ ሄደ",
        "ብር ልኬ ቁጥሬ ጠፋ",
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
        "ላኩ ወዴት", "ገንዘብ ወዴት ልላክ", "payment info",
        "ቴሌብር አካውንት ስጠኝ", "ቴሌብር ቁጥርህን ላክ",
        "አዋሽ አካውንት ስጠኝ", "ወዴት ልከፍል",
    ],
    "type_change": [
        "በሙሉ አርግ", "በሙሉ አድርግ", "በሙሉ ይሁን", "በሙሉ ቀይረው",
        "በሙሉ አርጋት", "ሙሉ አርግ", "ሙሉ ይሁን",
        "በግማሽ አርግ", "በግማሽ አድርግ", "በግማሽ ይሁን", "በግማሽ ቀይረው",
        "በግማሽ አርጋት", "ግማሽ አርግ", "ግማሽ ይሁን",
        "gmash areg", "bemulu areg", "begmash areg",
        "06 bemulu", "11 begmash", "09 11 begmash",
        "11 21 bemulu qeyirew",
        "gmash +argewo", "06+ argewo",
        "11በሙሉ", "05በሙሉ", "11በግማሽ", "05በግማሽ",
    ],
    "why_not_registered": [
        "ለምን አልያዝክልኝም", "ለምን አልፃፍክልኝም", "ለምን አልመዘገብከኝም",
        "ለምን ቁጥሬ አልተያዘም", "ለምን ቁጥሩ አልተያዘም",
        "ቁጥሩ ለምን አልተያዘም", "ለምን አልገባም", "ለምን ሳይያዝ ቀረ",
        "ለምን አልያዘልኝም", "ለምን አልተመዘገበም",
        "ቁጥሬ ለምን አልተያዘም", "ለምን አልተያዘልኝም",
        "ቁጥሩ ሳይያዝ ቀረ ለምን", "ለምን አላስገባኸኝም",
        "ለምን ቁጥሬን አልያዝህልኝም",
        "lmin alyazkilgnim", "lmin altsafkilgnim",
        "lmin almezegbkegnim", "lmin qitire alteyazem",
        "lmin algeba", "lmin sayiyaz qere",
        "lmin alteyazelign", "lmin altemezegebem",
        "qitire lmin alteyazem", "lmin alasgegabhegnim",
        "why aliyazkilign", "why alteyaze",
        "why did you not register", "not registered lmin",
        "lmin register aladergehlign",
        "qitre lmin sayiyaz qere",
    ],
}


# ================================================================
# N-GRAM ENGINE
# ================================================================

def get_ngrams(text: str, n: int = 2) -> list:
    text = normalize_amharic(text)
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
            translated = translate_latin(ex)
            normalized = normalize_amharic(translated)
            all_ngrams.extend(get_ngrams(normalized))
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
    translated = translate_latin(text)
    normalized = normalize_amharic(translated)
    ngrams = get_ngrams(normalized)

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
# DETECT INTENT
# ================================================================

def detect_intent(text: str) -> tuple:
    translated = translate_latin(text)
    normalized = normalize_amharic(translated)
    normalized_lower = normalized.lower()
    numbers_in_text = re.findall(r"\d+", text)

    account_keywords_direct = [
        "አካውንት", "አካንት", "ቴሌብር", "አዋሽ", "ሲቢኢ",
        "ንግድ ባንክ", "ባንክ አካውንት", "የሚከፈልበት ቁጥር", "የባንክ ቁጥር",
    ]
    if any(normalize_amharic(kw) in normalized_lower for kw in account_keywords_direct):
        return "account_query", 1.0

    if len(numbers_in_text) >= 2:
        change_result = detect_change_number(text)
        if change_result:
            return "change_number", 1.0

    TYPE_FULL_WORDS = ["በሙሉ", "ሙሉ", "bemulu", "mulu"]
    TYPE_HALF_WORDS = ["በግማሽ", "ግማሽ", "begmash", "gmash"]
    has_type_full = any(normalize_amharic(w) in normalized_lower for w in TYPE_FULL_WORDS)
    has_type_half = any(normalize_amharic(w) in normalized_lower for w in TYPE_HALF_WORDS)

    if numbers_in_text and (has_type_full or has_type_half):
        TYPE_ACTION_WORDS = [
            "አርግ", "አድርግ", "ይሁን", "ቀይር", "ቀይረው",
            "areg", "adrig", "yihun", "qeyir", "qeyirew",
        ]
        has_action = any(
            normalize_amharic(w) in normalized_lower
            for w in TYPE_ACTION_WORDS
        )
        if has_action:
            return "type_change", 1.0

    WHY_NOT_REG_WORDS = [
        "ለምን አልያዝ", "ለምን አልፃፍ", "ለምን አልመዘገብ",
        "ለምን አልተያዘ", "ለምን አልገባ", "lmin alyaz", "lmin altsaf",
    ]
    if any(normalize_amharic(w) in normalized_lower for w in WHY_NOT_REG_WORDS):
        return "why_not_registered", 1.0

    has_ale = "አለ" in normalized_lower
    has_teyaze = any(w in normalized_lower for w in ["ተያዘ", "ተይዞ", "ተይዙዋል"])
    if numbers_in_text and (has_ale or has_teyaze):
        return "specific_number_query", 1.0

    cancel_words = ["አልፈልግም", "ሽጠው", "አጥፋው", "ይጥፋ", "ሰርዝ", "አውጣ", "አጥፋልኝ", "ሰርዝልኝ"]
    has_cancel = any(normalize_amharic(w) in normalized_lower for w in cancel_words)
    if len(numbers_in_text) == 1 and has_cancel:
        return "cancel_number", 1.0

    query_vec = text_to_vector(text, GLOBAL_IDF)
    scores = {}
    for intent, intent_vec in TFIDF_VECTORS.items():
        sim = cosine_similarity(query_vec, intent_vec)
        scores[intent] = sim

    for intent in list(scores.keys()):
        bonus = 0.0
        if numbers_in_text:
            if intent in ("booking", "specific_number_query", "cancel_number",
                          "change_number", "type_change"):
                bonus += 0.08
            elif intent == "account_query":
                pass
            else:
                bonus -= 0.10
        if not numbers_in_text and intent == "booking":
            bonus -= 0.15
        if intent == "greeting" and not numbers_in_text:
            bonus += 0.05
        if intent in ("complaint_removed", "complaint_why_sold", "complaint_paid_removed") and not numbers_in_text:
            bonus += 0.05
        scores[intent] = max(0.0, scores[intent] + bonus)

    best_intent = max(scores, key=scores.get)
    best_score = scores[best_intent]

    return best_intent, best_score


# ================================================================
# RESPONSES
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
        "እሺ 🙏",
        "እሺ ቤተሰብ 🙏",
        "ተቀይሯል 🙏",
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
) -> dict:

    THRESHOLD_RESPOND  = 0.18
    THRESHOLD_CONFUSED = 0.08

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
        result["reply"] = "ምን ማለትህ ነው? 🙏"
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
