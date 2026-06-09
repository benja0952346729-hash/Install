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
    # nekay
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
    # ሰርዝ/አውጣ
    "serzew": "ሰርዝ", "srez": "ሰርዝ", "serz": "ሰርዝ",
    "shitew": "ሽጠው", "shtew": "ሽጠው", "shitkhew": "ሽጠው", "shetek": "ሽጠው",
    "atfaw": "አጥፋው", "atfa": "አጥፋው", "yitfa": "ይጥፋ",
    "awta": "አውጣ", "awuta": "አውጣ",
    "alfeligm": "አልፈልግም", "alfelegim": "አልፈልግም", "alfelegm": "አልፈልግም",
    # ተነቀልኩ
    "tenekelku": "ተነቀልኩ", "teneklku": "ተነቀልኩ", "nekelku": "ተነቀልኩ",
    "qitr tenekelk": "ቁጥር ተነቀለ", "number tenekelk": "ቁጥር ተነቀለ",
    # ለምን ሸጥከው
    "lmin shitkhew": "ለምን ሸጥከው", "lmin shitkh": "ለምን ሸጥከው",
    "lmin shetek": "ለምን ሸጥህ", "lemin shetek": "ለምን ሸጥህ",
    "lmin tenklaleh": "ለምን ትነቅላለህ", "lmin tinklaleh": "ለምን ትነቅላለህ",
    "why shetek": "ለምን ሸጥህ", "why teneklaleh": "ለምን ትነቅላለህ",
    # ከፍዬ ነቀልክ
    "kefye nekelk": "ከፍዬ ነቀልክ", "kefye neklek": "ከፍዬ ነቀልክ",
    "tekeflo nekelk": "ተከፍሎ ነቀልክ", "tekefilo neklek": "ተከፍሎ ነቀልክ",
    "kefye shetk": "ከፍዬ ሸጥክ", "kefye shetkh": "ከፍዬ ሸጥክ",
    "likeyalew lmin": "ልክያለው ለምን", "likyalew lemin": "ልክያለው ለምን",
    "telkuwal lmin nekelk": "ተልኩዋል ለምን ነቀልክ",
    "telkual lmin": "ተልኩዋል ለምን",
    "like tineklaleh": "ልኬ ትነቅላለህ", "lke tinklaleh": "ልኬ ትነቅላለህ",
    "lkuwal lmin": "ልክያለው ለምን", "selkuwal lemin": "ልክያለው ለምን",
    "payment ale lmin": "ከፍዬ ሸጥክ", "lefkuwal lmin": "ልክያለው ለምን",
    # ሰላምታ
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
            "ነቃይ", "ተነቃይ", "ንቃይ", "ነቃዮች", "ሚሸጥ", "የተሸጠ",
        ],
        "verb_endings": ["አለ", "ዘርዝር", "ላክ", "ንገር", "ንገረኝ", "አሳውቀኝ", "አሳውቅ", "አሳይ"],
        "weight_keyword": 0.25,
        "weight_verb": 0.10,
    },

    "remaining_send": {
        "keywords": ["ቀሪ", "ቁጥር"],
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

    # ================================================================
    # ቁጥር ሰርዝ — "07 አልፈልግም / 07 ሽጠው / 07 አጥፋው / 07 ይጥፋ"
    # ================================================================
    "cancel_number": {
        "keywords": [
            "አልፈልግም", "ሽጠው", "አጥፋው", "ይጥፋ", "ሰርዝ", "አውጣ",
            "አጥፋልኝ", "ሰርዝልኝ", "አውጣልኝ",
        ],
        "verb_endings": ["ሽጠው", "አጥፋው", "ይጥፋ", "ሰርዝ", "አውጣ", "አልፈልግም"],
        "weight_keyword": 0.35,
        "weight_verb": 0.15,
    },

    # ================================================================
    # ተነቀልኩ — "ቁጥሬ ተነቀለ / ቁጥሬ ጠፋ"
    # ================================================================
    "complaint_removed": {
        "keywords": [
            "ተነቀልኩ", "ቁጥሬ ተነቀለ", "ቁጥሬ ጠፋ", "ቁጥሬ ሄደ",
            "ለምን ተነቀልኩ", "ተነቀልኩ እኮ",
        ],
        "verb_endings": ["ተነቀልኩ", "ተነቀለ", "ጠፋ", "ሄደ"],
        "weight_keyword": 0.35,
        "weight_verb": 0.15,
    },

    # ================================================================
    # ለምን ሸጥከው — "ለምን ሸጥህ / ለምን ትነቅላለህ / ለምን ሸጥከው"
    # ================================================================
    "complaint_why_sold": {
        "keywords": [
            "ለምን ሸጥከው", "ለምን ሸጠከው", "ለምን ትነቅላለህ",
            "ለምን ትሸጣለህ", "ለምን ሸጥህ", "ቁጥሬን ለምን ሸጥህ",
            "ቁጥሬን ለምን ነቀልክ",
        ],
        "verb_endings": ["ሸጥህ", "ሸጥከው", "ትነቅላለህ", "ትሸጣለህ", "ነቀልክ"],
        "weight_keyword": 0.35,
        "weight_verb": 0.15,
    },

    # ================================================================
    # ከፍዬ ነቀልክ — "ተከፍሎ ነቀልክ / ልክያለው ለምን / ተልኩዋል ለምን"
    # ================================================================
    "complaint_paid_removed": {
        "keywords": [
            "ከፍዬ ነቀልክ", "ተከፍሎ ነቀልክ", "ከፍዬ ሸጥክ",
            "ልክያለው እኮ ለምን ሸጥክ", "ተልኩዋል ለምን ነቀልክ",
            "ልክያለው ለምን", "ልኬ ትነቅላለህ",
            "ብሬ ተልኳል ለምን ነቀልክ", "ገንዘብ ልኬ ነቀልክ",
            "ከፈልኩ ለምን ሸጥክ", "payment ላኩ ለምን ሸጥክ",
            "ልኬ ሸጥክ", "ልኩዋል ለምን", "ተልኩዋል ሸጥክ",
            "ልክ ነው ለምን", "ተልኩዋል እኮ",
        ],
        "verb_endings": ["ነቀልክ", "ሸጥክ", "ትነቅላለህ", "ለምን"],
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
        "ቀሪ ቁጥሮች አሉ 🙏",
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

    # ቁጥር ሰርዝ — future (bot ይላካል)
    "cancel_number_ack": [
        "እሺ ተሰርዟል 🙏",
        "እሺ ተነቅሏል 🙏",
    ],

    # ተነቀልኩ — ቁጥሩ ሌላ ሰው ከያዘ
    "complaint_removed_taken": [
        "አዎ ገቢ ማረግ ረሳክ የጫወታው ባህሪ ነው 🙏",
        "ቤተሰብ ገቢ ሳታርግ ቁጥሩ ይለቀቃል 🙏",
        "ገቢ ማረግ ረሳህ ቤተሰብ የጫወታው ሕግ ነው 🙏",
    ],

    # ተነቀልኩ — ቁጥሩ ነቃይ list ውስጥ ካለ
    "complaint_removed_nekay": [
        "ተነቃይ list ውስጥ ገብቷል ገቢ አርገው ያረጋግጡ 🙏",
        "ቁጥርዎ ነቃይ ነው ገቢ አረጋግጡ 🙏",
        "ነቃይ ነው ቤተሰብ ቶሎ ገቢ አርጉ 🙏",
    ],

    # ለምን ሸጥከው
    "complaint_why_sold": [
        "ገቢ ተረሳ ቤተሰብ ምን ላርግ 🙏",
        "ቤተሰብ ገቢ ሳይደርስ ቁጥሩ ተለቀቀ ምን ላርግ 🙏",
        "ገቢ አልደረሰም ቤተሰብ ምን ላርግ 🙏",
    ],

    # ከፍዬ ነቀልክ
    "complaint_paid_removed": [
        "ቼክ አርግ ችግር ካለ ባለቤቱን አውራው 🙏",
        "ባለቤቱን አናግር ቼክ ያርጋል 🙏",
        "ችግር ካለ ባለቤቱን አውራው ቼክ ያርጋል 🙏",
        "ባለቤቱን አናግረው ቼክ ያርጋሉ 🙏",
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
    # SPECIFIC NUMBER QUERY — ቁጥር + አለ/ተያዘ pattern
    # ================================================================
    numbers_in_text = re.findall(r"\d+", text)
    translated_lower = translated.lower()
    normalized_lower = normalize_amharic(translated_lower)

    has_ale = "አለ" in normalized_lower
    has_teyaze = any(w in normalized_lower for w in ["ተያዘ", "ተይዞ", "ተይዙዋል"])

    if numbers_in_text and (has_ale or has_teyaze):
        return "specific_number_query", 1.0

    # ================================================================
    # CANCEL NUMBER — ቁጥር + ሰርዝ/ሽጠው/አጥፋው/ይጥፋ/አልፈልግም
    # ================================================================
    cancel_words = ["አልፈልግም", "ሽጠው", "አጥፋው", "ይጥፋ", "ሰርዝ", "አውጣ", "አጥፋልኝ", "ሰርዝልኝ"]
    has_cancel = any(normalize_amharic(w) in normalized_lower for w in cancel_words)
    if numbers_in_text and has_cancel:
        return "cancel_number", 1.0

    # ================================================================
    # CONTEXT GRADING — weighted formula per intent
    # ================================================================
    for intent_name, total in results.items():
        bonus = 0.0

        if numbers_in_text:
            if intent_name in ("booking", "specific_number_query", "cancel_number"):
                bonus += 0.15
            else:
                bonus -= 0.20

        if not numbers_in_text and intent_name == "booking":
            bonus -= 0.30

        if intent_name == "greeting" and not numbers_in_text:
            bonus += 0.10

        # complaint intents — ቁጥር ከሌለ score ይጨምር
        if intent_name in ("complaint_removed", "complaint_why_sold", "complaint_paid_removed") and not numbers_in_text:
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
    user_id: int = 0,
    registration_result: str = None,
    registered_numbers: list = None,
    failed_numbers: list = None,
) -> dict:

    THRESHOLD_RESPOND  = 0.70
    THRESHOLD_CONFUSED = 0.40

    result = {
        "reply": None,
        "resend_board": False,
        "resend_nekay": False,
        "resend_remaining": False,
        "cancel_number": None,   # int ቁጥር — bot.py ይሰርዛዋል
    }

    # ================================================================
    # REGISTRATION RESULT
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
        return result

    # ================================================================
    # INTENT DETECTION
    # ================================================================
    intent, score = detect_intent(text)

    if score < THRESHOLD_CONFUSED:
        return result
    if score < THRESHOLD_RESPOND:
        result["reply"] = "ምን ማለትህ ነው? 🙏"
        return result

    # ================================================================
    # INTENT: booking
    # ================================================================
    if intent == "booking":
        if countdown_seconds > 0:
            mins = countdown_seconds // 60
            secs = countdown_seconds % 60
            if mins >= 1:
                result["reply"] = f"ቲንሽ ይጠብቁ {mins} ደቂቃ ቀርቱዋል ያልከፈለ ሊወጣ 🙏"
            else:
                result["reply"] = f"{secs} ሴኮንድ ቀርቱዋል ቲንሽ ይጠብቁ ነቃይ ካለ አሳውቃለው 🙏"
        return result

    # ================================================================
    # INTENT: specific_number_query
    # ================================================================
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

    # ================================================================
    # INTENT: cancel_number — "07 አልፈልግም / 07 ሽጠው / 07 አጥፋው"
    # ================================================================
    if intent == "cancel_number":
        numbers_found = re.findall(r"\d+", text)
        if numbers_found:
            num = int(numbers_found[0])
            result["reply"] = random.choice(RESPONSES["cancel_number_ack"])
            result["cancel_number"] = num
        return result

    # ================================================================
    # INTENT: complaint_removed — "ተነቀልኩ / ቁጥሬ ጠፋ"
    # ================================================================
    if intent == "complaint_removed":
        numbers_found = re.findall(r"\d+", text)
        num = int(numbers_found[0]) if numbers_found else None

        if num and num in taken:
            # ሌላ ሰው ይዞታል
            result["reply"] = random.choice(RESPONSES["complaint_removed_taken"])
        elif num and any(num == n for n, _ in nekay_list):
            # ነቃይ list ውስጥ ነው
            result["reply"] = random.choice(RESPONSES["complaint_removed_nekay"])
        else:
            # ቁጥር ከሌለ — default
            result["reply"] = random.choice(RESPONSES["complaint_removed_taken"])
        return result

    # ================================================================
    # INTENT: complaint_why_sold — "ለምን ሸጥህ / ለምን ትነቅላለህ"
    # ================================================================
    if intent == "complaint_why_sold":
        result["reply"] = random.choice(RESPONSES["complaint_why_sold"])
        return result

    # ================================================================
    # INTENT: complaint_paid_removed — "ከፍዬ ነቀልክ / ልክያለው ለምን"
    # ================================================================
    if intent == "complaint_paid_removed":
        result["reply"] = random.choice(RESPONSES["complaint_paid_removed"])
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
