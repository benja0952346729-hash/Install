import re
import os
import math
import random
import logging
from collections import defaultdict
from parser import parse_numbers

logger = logging.getLogger(__name__)

# ================================================================
# AMHARIC \u2192 LATIN TRANSLITERATOR
# ================================================================

FIDEL_TO_LATIN = {
    "\u1200": "ha", "\u1201": "hu", "\u1202": "hi", "\u1203": "ha", "\u1204": "he", "\u1205": "h", "\u1206": "ho",
    "\u1210": "ha", "\u1211": "hu", "\u1212": "hi", "\u1213": "ha", "\u1214": "he", "\u1215": "h", "\u1216": "ho",
    "\u1208": "le", "\u1209": "lu", "\u120a": "li", "\u120b": "la", "\u120c": "le", "\u120d": "l", "\u120e": "lo",
    "\u1218": "me", "\u1219": "mu", "\u121a": "mi", "\u121b": "ma", "\u121c": "me", "\u121d": "m", "\u121e": "mo",
    "\u1230": "se", "\u1231": "su", "\u1232": "si", "\u1233": "sa", "\u1234": "se", "\u1235": "s", "\u1236": "so",
    "\u1220": "se", "\u1221": "su", "\u1222": "si", "\u1223": "sa", "\u1224": "se", "\u1225": "s", "\u1226": "so",
    "\u1238": "she", "\u1239": "shu", "\u123a": "shi", "\u123b": "sha", "\u123c": "she", "\u123d": "sh", "\u123e": "sho",
    "\u1240": "qe", "\u1241": "qu", "\u1242": "qi", "\u1243": "qa", "\u1244": "qe", "\u1245": "q", "\u1246": "qo",
    "\u1248": "qo", "\u124a": "qu", "\u124b": "qua", "\u124c": "qe", "\u124d": "qu",
    "\u1260": "be", "\u1261": "bu", "\u1262": "bi", "\u1263": "ba", "\u1264": "be", "\u1265": "b", "\u1266": "bo",
    "\u1270": "te", "\u1271": "tu", "\u1272": "ti", "\u1273": "ta", "\u1274": "te", "\u1275": "t", "\u1276": "to",
    "\u1278": "che", "\u1279": "chu", "\u127a": "chi", "\u127b": "cha", "\u127c": "che", "\u127d": "ch", "\u127e": "cho",
    "\u1290": "ne", "\u1291": "nu", "\u1292": "ni", "\u1293": "na", "\u1294": "ne", "\u1295": "n", "\u1296": "no",
    "\u1298": "nye", "\u1299": "nyu", "\u129a": "nyi", "\u129b": "nya", "\u129c": "nye", "\u129d": "ny", "\u129e": "nyo",
    "\u12a0": "a", "\u12a1": "u", "\u12a2": "i", "\u12a3": "a", "\u12a4": "e", "\u12a5": "e", "\u12a6": "o",
    "\u12a8": "ke", "\u12a9": "ku", "\u12aa": "ki", "\u12ab": "ka", "\u12ac": "ke", "\u12ad": "k", "\u12ae": "ko",
    "\u12c8": "we", "\u12c9": "wu", "\u12ca": "wi", "\u12cb": "wa", "\u12cc": "we", "\u12cd": "w", "\u12ce": "wo",
    "\u12e8": "ye", "\u12e9": "yu", "\u12ea": "yi", "\u12eb": "ya", "\u12ec": "ye", "\u12ed": "y", "\u12ee": "yo",
    "\u12f0": "de", "\u12f1": "du", "\u12f2": "di", "\u12f3": "da", "\u12f4": "de", "\u12f5": "d", "\u12f6": "do",
    "\u12d8": "ze", "\u12d9": "zu", "\u12da": "zi", "\u12db": "za", "\u12dc": "ze", "\u12dd": "z", "\u12de": "zo",
    "\u12e0": "zhe", "\u12e1": "zhu", "\u12e2": "zhi", "\u12e3": "zha", "\u12e4": "zhe", "\u12e5": "zh", "\u12e6": "zho",
    "\u1300": "je", "\u1301": "ju", "\u1302": "ji", "\u1303": "ja", "\u1304": "je", "\u1305": "j", "\u1306": "jo",
    "\u1308": "ge", "\u1309": "gu", "\u130a": "gi", "\u130b": "ga", "\u130c": "ge", "\u130d": "g", "\u130e": "go",
    "\u1320": "te", "\u1321": "tu", "\u1322": "ti", "\u1323": "ta", "\u1324": "te", "\u1325": "t", "\u1326": "to",
    "\u1330": "pe", "\u1331": "pu", "\u1332": "pi", "\u1333": "pa", "\u1334": "pe", "\u1335": "p", "\u1336": "po",
    "\u1338": "tse", "\u1339": "tsu", "\u133a": "tsi", "\u133b": "tsa", "\u133c": "tse", "\u133d": "ts", "\u133e": "tso",
    "\u1340": "tse", "\u1341": "tsu", "\u1342": "tsi", "\u1343": "tsa", "\u1344": "tse", "\u1345": "ts", "\u1346": "tso",
    "\u1348": "fe", "\u1349": "fu", "\u134a": "fi", "\u134b": "fa", "\u134c": "fe", "\u134d": "f", "\u134e": "fo",
    "\u1350": "pe", "\u1351": "pu", "\u1352": "pi", "\u1353": "pa", "\u1354": "pe", "\u1355": "p", "\u1356": "po",
    "\u1362": ".", "\u1363": ",", "\u1364": ";", "\u1365": ":", "\u1366": ":-", "\u1367": "?", "\u1368": "*",
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
    r"\u1274\u120c\u1265\u122d\s*[:\-]?\s*\S+",
    r"\u12a0\u12cb\u123d\s*[:\-]?\s*\S+",
    r"\u1232\u1262\u12a2\s*[:\-]?\s*\S+",
    r"\u1295\u130d\u12f5\s*\u1263\u1295\u12ad\s*[:\-]?\s*\S+",
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
        "\u12eb\u12dd", "\u12eb\u12db\u1275", "\u12eb\u12db\u1278\u12cd", "\u1343\u134d\u120d\u129d", "\u1343\u134d", "\u12eb\u12dd\u120d\u129d",
        "\u1218\u12dd\u130d\u1265", "\u1218\u12dd\u130d\u1263\u1275", "\u1218\u12dd\u130d\u1265\u120d\u129d",
        "\u1241\u1325\u122d \u12eb\u12dd\u120d\u129d", "\u1343\u134d\u120d\u129d \u1241\u1325\u1229\u1295", "\u12ed\u1205\u1295 \u1241\u1325\u122d \u12eb\u12dd",
        "\u1208\u1294 \u12eb\u12dd\u120d\u129d", "register \u12a0\u122d\u130d\u120d\u129d", "book \u12a0\u122d\u130d",
        "\u1241\u1325\u1229\u1295 \u12a0\u1235\u1240\u121d\u1325\u120d\u129d", "\u1343\u134d \u1343\u134d", "\u12eb\u12dd\u120d\u129d \u12a5\u1263\u12ad\u1205",
        "\u1241\u1325\u1229\u1295 \u133b\u134d\u120d\u129d", "\u121d\u12dd\u1308\u1263 \u12a0\u122d\u130d\u120d\u129d", "\u121d\u12dd\u1308\u1263",
    ],
    "nekay_query": [
        "\u1290\u1243\u12ed", "\u1270\u1290\u1243\u12ed", "\u1290\u1243\u12ee\u127d", "\u121a\u1238\u1325 \u12a0\u1208",
        "\u1290\u1243\u12ed \u12a0\u1208", "\u1290\u1243\u12ed \u12d8\u122d\u12dd\u122d", "\u1290\u1243\u12ed \u1295\u1308\u122d",
        "\u1290\u1243\u12ed \u1241\u1325\u122e\u127d", "\u1270\u1290\u1243\u12ed \u12a0\u1208", "\u1290\u1243\u12ed \u12a0\u1233\u12ed",
        "\u1290\u1243\u12ed \u120b\u12ad", "\u1290\u1243\u12ed \u121d\u1295 \u12a0\u1208", "\u1290\u1243\u12ed \u12dd\u122d\u12dd\u122d \u1235\u1320\u129d",
        "\u121d\u1295 \u12eb\u1205\u120d \u1290\u1243\u12ed \u12a0\u1208", "\u1290\u1243\u12ed \u1241\u1325\u122d \u1235\u1295\u1275 \u1290\u12cd",
    ],
    "remaining_send": [
        "\u1240\u122a \u120b\u12ad", "\u1241\u1325\u122d \u120b\u12ad", "\u1240\u122a \u1241\u1325\u122e\u127d \u120b\u12ad",
        "\u1240\u122a \u12a0\u1233\u12e8\u129d", "\u1276\u120e \u1276\u120e \u1240\u122a \u120b\u12ad",
        "\u1240\u122a \u1241\u1325\u122e\u1279\u1295 \u120b\u12ad", "remaining \u120b\u12ad",
        "\u12eb\u120d\u1270\u12eb\u12d9 \u1241\u1325\u122e\u127d \u120b\u12ad", "\u12eb\u120d\u1270\u12eb\u12d9 \u1241\u1325\u122e\u1279\u1295 \u1235\u1320\u129d",
    ],
    "remaining_query": [
        "\u1240\u122a", "\u12eb\u120d\u1270\u12eb\u12d8", "\u12eb\u120d\u1270\u12eb\u12d9", "\u121d\u1295 \u12a0\u1208", "\u1235\u1295\u1275 \u1240\u1228",
        "\u1235\u1295\u1275 \u1241\u1325\u122e\u127d", "\u1235\u1295\u1275 \u12a0\u1208", "\u1241\u1325\u122d \u12a0\u1208", "\u1240\u122a \u12a0\u1208",
        "\u121d\u1295 \u121d\u1295 \u12a0\u1208", "\u1240\u122a \u1241\u1325\u122e\u127d \u121d\u1295 \u12a0\u1208", "\u1235\u1295\u1275 \u1241\u1325\u122d \u1240\u1228",
        "\u12eb\u120d\u1270\u12eb\u12d9 \u1241\u1325\u122e\u127d \u121d\u1295 \u12a0\u1208", "\u1240\u122a \u1241\u1325\u122e\u127d \u1235\u1295\u1275 \u1293\u1278\u12cd",
        "\u121d\u1295 \u12eb\u1205\u120d \u1240\u1228", "\u1240\u122a \u1241\u1325\u122e\u1279 \u121d\u1295\u12f5\u1295 \u1293\u1278\u12cd",
    ],
    "specific_number_query": [
        "\u1270\u12eb\u12d8", "\u1270\u12ed\u12de", "\u1270\u12ed\u12d9\u12cb\u120d", "\u12a0\u1208 \u12c8\u12ed", "\u12a0\u1208",
        "\u1241\u1325\u1229 \u1270\u12eb\u12d8 \u12c8\u12ed", "\u1241\u1325\u1229 \u12a0\u1208", "\u1241\u1325\u1229 \u12ad\u134d\u1275 \u1290\u12cd \u12c8\u12ed",
        "\u12ed\u1205 \u1241\u1325\u122d \u1270\u12c8\u1230\u12f0 \u12c8\u12ed", "\u1241\u1325\u1229 \u1290\u1343 \u1290\u12cd \u12c8\u12ed",
        "\u12ed\u1205 \u1241\u1325\u122d \u1270\u12eb\u12d8", "\u1241\u1325\u1229 available \u1290\u12cd \u12c8\u12ed",
    ],
    "all_taken_query": [
        "\u1201\u1209\u121d \u1270\u12ed\u12d8\u12cb\u120d", "\u1201\u1209\u121d \u1270\u12eb\u12d8", "\u1201\u1209\u121d \u12a0\u120d\u1270\u12eb\u12d9\u121d",
        "\u1201\u1209\u121d \u1241\u1325\u122e\u127d \u1270\u12eb\u12d9", "\u1201\u1209\u121d \u12a0\u1208\u1240", "\u1201\u1209\u121d \u1270\u12c8\u1230\u12f0",
    ],
    "cancel_number": [
        "\u12a0\u120d\u1348\u120d\u130d\u121d", "\u123d\u1320\u12cd", "\u12a0\u1325\u134b\u12cd", "\u12ed\u1325\u134b", "\u1230\u122d\u12dd", "\u12a0\u12cd\u1323",
        "\u12a0\u1325\u134b\u120d\u129d", "\u1230\u122d\u12dd\u120d\u129d", "\u12a0\u12cd\u1323\u120d\u129d",
        "\u1241\u1325\u1229\u1295 \u1230\u122d\u12dd", "\u1241\u1325\u1229\u1295 \u12a0\u1325\u134b", "\u1241\u1325\u1229\u1295 \u12a0\u12cd\u1323",
        "\u12a0\u120d\u1348\u1208\u12a9\u121d", "\u12a0\u120d\u1348\u120d\u1308\u12cd\u121d", "\u12a0\u120d\u1348\u120d\u130b\u1278\u12cd\u121d",
        "\u12a0\u12eb\u1235\u1348\u120d\u1308\u129d\u121d", "cancel \u1290\u12cd", "drop \u12a0\u122d\u130d",
        "\u1275\u127c\u12cb\u1208\u1201", "cancel \u12a0\u122d\u130d", "\u1230\u122d\u12dd\u120d\u129d \u1241\u1325\u1229\u1295",
    ],
    "complaint_removed": [
        "\u1270\u1290\u1240\u120d\u12a9", "\u1241\u1325\u122c \u1270\u1290\u1240\u1208", "\u1241\u1325\u122c \u1320\u134b", "\u1241\u1325\u122c \u1204\u12f0",
        "\u1208\u121d\u1295 \u1270\u1290\u1240\u120d\u12a9", "\u1270\u1290\u1240\u120d\u12a9 \u12a5\u12ae",
        "\u1241\u1325\u122c \u12e8\u1208\u121d", "\u1241\u1325\u122c \u1320\u134b \u1208\u121d\u1295", "\u1241\u1325\u122c \u1204\u12f0 \u1208\u121d\u1295",
        "\u1241\u1325\u122c \u1270\u1240\u1290\u1230", "\u1241\u1325\u122c \u1270\u12c8\u1230\u12f0 \u1208\u121d\u1295",
        "\u1241\u1325\u122c \u1208\u121d\u1295 \u1270\u1290\u1240\u1208", "\u1241\u1325\u122c \u1208\u121d\u1295 \u1320\u134b",
    ],
    "complaint_why_sold": [
        "\u1208\u121d\u1295 \u1238\u1325\u12a8\u12cd", "\u1208\u121d\u1295 \u1238\u1320\u12a8\u12cd", "\u1208\u121d\u1295 \u1275\u1290\u1245\u120b\u1208\u1205",
        "\u1208\u121d\u1295 \u1275\u1238\u1323\u1208\u1205", "\u1208\u121d\u1295 \u1238\u1325\u1205", "\u1241\u1325\u122c\u1295 \u1208\u121d\u1295 \u1238\u1325\u1205",
        "\u1241\u1325\u122c\u1295 \u1208\u121d\u1295 \u1290\u1240\u120d\u12ad", "\u1208\u121d\u1295 \u1241\u1325\u122c\u1295 \u1238\u1325\u1205",
    ],
    "complaint_paid_removed": [
        "\u12a8\u134d\u12ec \u1290\u1240\u120d\u12ad", "\u1270\u12a8\u134d\u120e \u1290\u1240\u120d\u12ad", "\u12a8\u134d\u12ec \u1238\u1325\u12ad",
        "\u120d\u12ad\u12eb\u1208\u12cd \u12a5\u12ae \u1208\u121d\u1295 \u1238\u1325\u12ad", "\u1270\u120d\u12a9\u12cb\u120d \u1208\u121d\u1295 \u1290\u1240\u120d\u12ad",
        "\u120d\u12ad\u12eb\u1208\u12cd \u1208\u121d\u1295", "\u120d\u12ac \u1275\u1290\u1245\u120b\u1208\u1205",
        "\u1265\u122c \u1270\u120d\u12b3\u120d \u1208\u121d\u1295 \u1290\u1240\u120d\u12ad", "\u1308\u1295\u12d8\u1265 \u120d\u12ac \u1290\u1240\u120d\u12ad",
        "\u12a8\u1348\u120d\u12a9 \u1208\u121d\u1295 \u1238\u1325\u12ad", "\u120d\u12a9\u12cb\u120d \u1208\u121d\u1295", "\u1270\u120d\u12a9\u12cb\u120d \u1238\u1325\u12ad",
    ],
    "change_number": [
        "\u12c8\u12f0 \u1240\u12ed\u122d", "\u1240\u12ed\u122d", "\u1240\u12ed\u1228\u12cd", "\u1240\u12ed\u122d\u120d\u129d",
        "\u1208\u12c8\u1325", "\u1208\u12c8\u1320\u12cd", "\u1208\u12c8\u1325\u120d\u129d", "\u12a0\u12db\u12cd\u122d", "\u12a0\u12db\u12cd\u1228\u12cd",
        "\u1241\u1325\u1229\u1295 \u1240\u12ed\u122d", "\u1241\u1325\u1229\u1295 \u1208\u12c8\u1325", "\u1241\u1325\u122c\u1295 \u1240\u12ed\u122d\u120d\u129d",
        "change \u12a0\u122d\u130d", "\u1241\u1325\u1229\u1295 change \u12a0\u122d\u130d",
    ],
    "account_query": [
        "\u12a0\u12ab\u12cd\u1295\u1275", "\u12a0\u12ab\u12cd\u1295\u1275 \u120b\u12ad", "\u12a0\u12ab\u12cd\u1295\u1275 \u121d\u1295\u12f5\u1295 \u1290\u12cd",
        "\u1274\u120c\u1265\u122d", "\u12a0\u12cb\u123d", "\u1232\u1262\u12a2", "\u1295\u130d\u12f5 \u1263\u1295\u12ad",
        "\u1274\u120c\u1265\u122d \u1241\u1325\u122d", "\u12a0\u12cb\u123d \u1241\u1325\u122d", "\u1232\u1262\u12a2 \u1241\u1325\u122d",
        "\u12e8\u121a\u12a8\u1348\u120d\u1260\u1275 \u1241\u1325\u122d", "\u12e8\u1263\u1295\u12ad \u1241\u1325\u122d", "\u1263\u1295\u12ad \u12a0\u12ab\u12cd\u1295\u1275",
        "\u120b\u12a9 \u12c8\u12f4\u1275", "\u1308\u1295\u12d8\u1265 \u12c8\u12f4\u1275 \u120d\u120b\u12ad",
        "\u1274\u120c\u1265\u122d \u12a0\u12ab\u12cd\u1295\u1275 \u1235\u1320\u129d", "\u12c8\u12f4\u1275 \u120d\u12a8\u134d\u120d",
    ],
    "type_change": [
        "\u1260\u1219\u1209 \u12a0\u122d\u130d", "\u1260\u1219\u1209 \u12a0\u12f5\u122d\u130d", "\u1260\u1219\u1209 \u12ed\u1201\u1295", "\u1260\u1219\u1209 \u1240\u12ed\u1228\u12cd",
        "\u1219\u1209 \u12a0\u122d\u130d", "\u1219\u1209 \u12ed\u1201\u1295",
        "\u1260\u130d\u121b\u123d \u12a0\u122d\u130d", "\u1260\u130d\u121b\u123d \u12a0\u12f5\u122d\u130d", "\u1260\u130d\u121b\u123d \u12ed\u1201\u1295", "\u1260\u130d\u121b\u123d \u1240\u12ed\u1228\u12cd",
        "\u130d\u121b\u123d \u12a0\u122d\u130d", "\u130d\u121b\u123d \u12ed\u1201\u1295",
    ],
    "why_not_registered": [
        "\u1208\u121d\u1295 \u12a0\u120d\u12eb\u12dd\u12ad\u120d\u129d\u121d", "\u1208\u121d\u1295 \u12a0\u120d\u1343\u134d\u12ad\u120d\u129d\u121d", "\u1208\u121d\u1295 \u12a0\u120d\u1218\u12d8\u1308\u1265\u12a8\u129d\u121d",
        "\u1208\u121d\u1295 \u1241\u1325\u122c \u12a0\u120d\u1270\u12eb\u12d8\u121d", "\u1208\u121d\u1295 \u1241\u1325\u1229 \u12a0\u120d\u1270\u12eb\u12d8\u121d",
        "\u1241\u1325\u1229 \u1208\u121d\u1295 \u12a0\u120d\u1270\u12eb\u12d8\u121d", "\u1208\u121d\u1295 \u12a0\u120d\u1308\u1263\u121d", "\u1208\u121d\u1295 \u1233\u12ed\u12eb\u12dd \u1240\u1228",
        "\u1208\u121d\u1295 \u12a0\u120d\u12eb\u12d8\u120d\u129d\u121d", "\u1208\u121d\u1295 \u12a0\u120d\u1270\u1218\u12d8\u1308\u1260\u121d",
    ],
    "price_query": [
        "\u1235\u1295\u1275 \u1290\u12cd", "\u1260 \u1235\u1295\u1275 \u1290\u12cd", "\u1235\u1295\u1275 \u1265\u122d \u1290\u12cd",
        "\u1263\u1208 \u1235\u1295\u1275 \u1290\u12cd", "\u1218\u12f0\u1265 \u1235\u1295\u1275 \u1290\u12cd", "\u1263\u1208 \u1235\u1295\u1275 \u1265\u122d \u1290\u12cd",
        "\u12cb\u130b \u1235\u1295\u1275 \u1290\u12cd", "\u12cb\u130b\u12cd \u1235\u1295\u1275 \u1290\u12cd", "\u121d\u1295 \u12eb\u1205\u120d \u1290\u12cd",
        "\u121d\u1295 \u12eb\u1205\u120d \u1265\u122d \u1290\u12cd", "\u1235\u1295\u1275 \u12eb\u1235\u12a8\u134d\u120b\u120d",
    ],
    "prize_query": [
        "\u12f0\u122b\u123d \u1235\u1295\u1275 \u1290\u12cd", "\u1235\u1295\u1275 \u12f0\u122b\u123d \u1290\u12cd", "\u1263\u1208 \u1235\u1295\u1275 \u12f0\u122b\u123d \u1290\u12cd",
        "\u123d\u120d\u121b\u1271 \u1235\u1295\u1275 \u1290\u12cd", "1\u129b \u123d\u120d\u121b\u1275 \u1235\u1295\u1275 \u1290\u12cd", "prize \u1235\u1295\u1275 \u1290\u12cd",
        "\u121d\u1295 \u12eb\u1205\u120d \u12f0\u122b\u123d \u1290\u12cd", "\u1235\u1295\u1275 \u1265\u122d \u12f0\u122b\u123d \u1290\u12cd",
    ],
    "players_query": [
        "\u1235\u1295\u1275 \u1230\u12cd \u1290\u12cd", "\u12a8\u1235\u1295\u1275 \u1230\u12cd \u130b\u122d \u1290\u12cd", "\u1208 \u1235\u1295\u1275 \u1230\u12cd \u1290\u12cd",
        "\u121d\u1295 \u12eb\u1205\u120d \u1230\u12cd \u1290\u12cd", "\u1235\u1295\u1275 \u1230\u12ce\u127d \u1293\u1278\u12cd",
        "\u1328\u12cb\u1273\u12cd \u1208\u1235\u1295\u1275 \u1230\u12cd \u1290\u12cd", "\u1235\u1295\u1275 \u1270\u132b\u12cb\u127e\u127d \u1293\u1278\u12cd",
    ],
    "players_remaining_query": [
        "\u1235\u1295\u1275 \u1230\u12cd \u1240\u1228", "\u1235\u1295\u1275 \u1230\u12cd \u1290\u12cd \u12e8\u1240\u1228\u12cd", "\u1235\u1295\u1275 \u1230\u12ce\u127d \u1240\u1229",
        "\u121d\u1295 \u12eb\u1205\u120d \u1230\u12cd \u1240\u1228", "\u1235\u1295\u1275 \u1230\u12cd \u12ed\u1240\u122b\u120d",
        "\u1240\u122a \u1230\u12cd \u1235\u1295\u1275 \u1290\u12cd", "\u1235\u1295\u1275 \u1230\u12cd \u12ed\u1240\u1228\u12cb\u120d",
    ],
    "payment_not_received": [
        "\u1265\u122d \u12a0\u120d\u12f0\u1228\u1230\u129d\u121d", "\u12a0\u120d\u1308\u1263\u120d\u129d\u121d", "\u1265\u122d \u12a0\u120d\u1308\u1263\u121d",
        "\u1265\u122d \u120b\u12ad\u120d\u129d", "\u1240\u122a \u1265\u122d \u120b\u12ad\u120d\u129d", "\u1208\u121d\u1295 \u12a0\u1275\u120d\u12ad\u121d",
        "\u1265\u122c\u1295 \u1208\u121d\u1295 \u12a0\u120b\u12ad\u121d", "\u1265\u122d \u1208\u121d\u1295 \u12a0\u120d\u1235\u1308\u1263\u1205\u121d",
        "\u1308\u1295\u12d8\u1264 \u12a0\u120d\u12f0\u1228\u1230\u129d\u121d", "\u1265\u122c \u12a0\u120d\u12f0\u1228\u1230\u121d", "\u1265\u122d \u12a0\u120d\u1270\u120b\u12a8\u121d",
    ],
    "result_query": [
        "\u12cd\u1324\u1275", "\u12cd\u1324\u1275 \u12a0\u1233\u12cd\u1240\u1295", "\u1235\u1295\u1275 \u1241\u1325\u122d \u12c8\u1323",
        "\u1235\u1295\u1275 \u12c8\u1323", "\u121d\u1295 \u1241\u1325\u122d \u12c8\u1323", "\u12cd\u1324\u1275 \u1235\u1295\u1275 \u1290\u12cd",
        "\u12e8\u12c8\u1323\u12cd \u1235\u1295\u1275 \u1241\u1325\u122d \u1290\u12cd", "\u12e8\u12c8\u1323\u12cd \u121d\u1295\u12f5\u1290\u12cd",
        "\u12cd\u1324\u1271 \u121d\u1295\u12f5\u1295 \u1290\u12cd", "\u12cd\u1324\u1271 \u121d\u1295 \u1290\u12cd",
    ],
    "my_numbers_query": [
        "\u121d\u1295 \u1241\u1325\u122d \u12eb\u12dd\u12ad\u120d\u129d", "\u1235\u1295\u1275 \u1241\u1325\u122e\u127d\u1295 \u1290\u12cd \u12e8\u12eb\u12dd\u12a9\u1275",
        "\u121d\u1295 \u1241\u1325\u122e\u127d \u12eb\u12dd\u12a9", "\u1235\u1295\u1275 \u1241\u1325\u122d \u12eb\u12dd\u12a9",
        "\u1235\u1295\u1275 \u1241\u1325\u122e\u127d \u1218\u12d8\u1308\u1265\u12ad\u120d\u129d", "\u121d\u1295 \u1241\u1325\u122e\u127d \u1293\u1278\u12cd \u12eb\u12d8\u12dd\u12a9\u1275",
        "\u12e8\u12eb\u12dd\u12a9\u1275 \u1241\u1325\u122e\u127d \u121d\u1295 \u121d\u1295 \u1293\u1278\u12cd", "\u1241\u1325\u122c \u121d\u1295 \u121d\u1295 \u1290\u12cd",
        "\u12eb\u12d8\u12dd\u12a9\u1275 \u1241\u1325\u122d \u121d\u1295 \u1290\u12cd", "\u121d\u1295 \u1241\u1325\u122e\u127d \u133b\u134d\u12ad\u120d\u129d",
        "\u1241\u1325\u122e\u127c \u121d\u1295 \u121d\u1295 \u1293\u1278\u12cd", "\u121d\u1295 \u1241\u1325\u122e\u127d \u1290\u12cd \u12eb\u12d8\u12dd\u12a9\u1275",
        "\u1241\u1325\u122e\u127c\u1295 \u1295\u1308\u1228\u129d", "\u1241\u1325\u122e\u127c\u1295 \u12a0\u1233\u12cd\u1240\u129d",
        "\u12e8\u12eb\u12dd\u12ad\u120d\u129d \u1241\u1325\u122d \u12a0\u1208", "\u1235\u1295\u1275 \u1241\u1325\u122d \u1290\u12cd \u12e8\u1294",
    ],
    "number_owner_query": [
        "01 \u12e8\u121b\u1290\u12cd", "06 \u1208\u121b\u1295 \u12eb\u12d8", "\u1208\u121b\u1295 \u12eb\u12d8", "\u1208\u121b\u1295 \u1218\u12d8\u1308\u1265\u12ad",
        "\u1208\u121b\u1295 \u12eb\u12dd\u12a8\u12cd", "\u12ed\u1205 \u1241\u1325\u122d \u1208\u121b\u1295 \u1270\u12eb\u12d8",
        "\u1241\u1325\u1229 \u1208\u121b\u1295 \u1290\u12cd", "\u1241\u1325\u1229 \u12e8\u121b\u1290\u12cd",
        "\u1208\u121b\u1295 \u12ed\u12dd\u12ad", "\u120b\u12ed \u121b\u1290\u12cd \u12e8\u1270\u1218\u12d8\u1308\u1260\u12cd", "\u120b\u12ed \u121b\u1290\u12cd \u12e8\u1270\u133b\u1348\u12cd",
        "\u12e8\u121b\u1295 \u1241\u1325\u122d \u1290\u12cd", "\u12e8\u121b\u1290\u12cd \u1241\u1325\u1229",
    ],
    "claim_ownership": [
        "11 \u12e8\u1294 \u1290\u12cd", "\u12e8\u1294 \u1290\u12cd", "11 \u12e8\u1294 \u1290\u12cd \u12a5\u1295\u12f4", "\u12e8\u1294 \u1290\u12cd \u12a5\u1295\u12f4",
        "11 \u12e8\u1294 \u1290\u12cd \u12a0\u12f0\u1208", "\u12e8\u1294 \u1290\u12cd \u12a0\u12f0\u1208",
    ],
    "link_request": [
        "\u120a\u1295\u12ad \u120b\u12ad\u120d\u129d", "\u120a\u1295\u12ad \u120b\u12ad", "link \u120b\u12ad\u120d\u129d", "link \u120b\u12ad",
        "\u120a\u1295\u12a9\u1295 \u120b\u12ad", "\u120a\u1295\u12ad \u1235\u1320\u129d", "group link \u120b\u12ad\u120d\u129d",
    ],
    "speed_request": [
        "\u132b\u12c8\u1273\u12cd \u12ed\u134d\u1320\u1295", "\u1348\u1320\u1295 \u1348\u1320\u1295 \u12a0\u122d\u1308\u12cd", "\u1348\u1323\u1295 \u12ed\u1201\u1295",
        "\u1276\u120e \u1276\u120e \u12a0\u132b\u12c8\u1270\u1295", "speed", "\u1348\u1320\u1295",
        "\u1276\u120e \u1276\u120e", "\u12ed\u134d\u1320\u1295", "\u134d\u1320\u1295",
    ],
    # \u2500\u2500 NEW INTENTS \u2500\u2500
    "balance_query": [
        "\u1235\u1295\u1275 \u1265\u122d \u12a0\u1208\u129d", "\u1235\u1295\u1275 \u1240\u122a \u12a0\u1208\u129d", "\u1235\u1295\u1275 \u1265\u122d \u12ed\u1240\u1228\u129b\u120d",
        "\u12a0\u1295\u1270\u130b \u1235\u1295\u1275 \u12a0\u1208\u129d", "\u1235\u1295\u1275 \u12a0\u1208\u129d", "\u1265\u122c \u1235\u1295\u1275 \u1290\u12cd",
        "balance \u1235\u1295\u1275 \u1290\u12cd", "\u121d\u1295 \u12eb\u1205\u120d \u1265\u122d \u12a0\u1208\u129d",
        "\u1240\u122a balance \u1235\u1295\u1275 \u1290\u12cd", "\u1235\u1295\u1275 \u1265\u122d \u12ed\u1240\u1228\u129b\u120d",
        "sint br alegn", "sint alegn", "balance sint new",
        "antenga sint alegn",
    ],
    "shortfall_query": [
        "\u1235\u1295\u1275 \u1265\u122d \u12ed\u1240\u122b\u120d", "\u1235\u1295\u1275 \u120d\u1328\u121d\u122d", "\u1235\u1295\u1275 \u120d\u1219\u120b",
        "\u1235\u1295\u1275 \u12ed\u130e\u120b\u120d", "\u1235\u1295\u1275 \u12eb\u1235\u1328\u121d\u122b\u120d", "\u121d\u1295 \u12eb\u1205\u120d \u12ed\u130e\u12f3\u120d",
        "\u1201\u1209\u121d \u2705 \u1208\u1218\u1206\u1295 \u1235\u1295\u1275", "\u1208\u1219\u1209 \u12ad\u134d\u12eb \u1235\u1295\u1275 \u12ed\u130e\u120b\u120d",
        "\u1235\u1295\u1275 \u1265\u122d \u120d\u1328\u121d\u122d \u1201\u1209\u121d \u12a5\u1295\u12f2\u1206\u1295",
        "sint lijevmer", "sint yigolal", "sint yasijemir",
        "sint limula",
    ],
    "winner_query": [
        "\u121b\u1295 \u12a0\u1238\u1290\u1348", "\u121b\u1290\u12cd \u12e8\u12d8\u130b\u12cd", "\u121b\u1295 \u12d8\u130b", "\u121b\u1295 \u1260\u120b",
        "\u121b\u1290\u12cd \u12e8\u1260\u120b\u12cd", "\u12a0\u1238\u1293\u134a\u12cd \u121b\u1295 \u1290\u12cd", "\u121b\u1295 \u1290\u12cd \u12eb\u1238\u1290\u1348\u12cd",
        "\u12d8\u130b\u12cd \u121b\u1295 \u1290\u12cd", "winner \u121b\u1295 \u1290\u12cd",
        "man asheneffe", "man zega", "man bela",
        "ashenafiw man new",
    ],
    "i_won_query": [
        "\u1208\u1294 \u12c8\u1323\u120d\u129d", "\u12a5\u1294 \u12a0\u1238\u1290\u134d\u12a9", "\u12e8\u1294 \u1241\u1325\u122d \u12c8\u1323",
        "\u12c8\u1323\u120d\u129d", "\u12a5\u1294 \u1260\u120b\u12cd", "\u12a5\u1294 \u12a0\u1238\u1290\u134d\u12a9",
        "\u12e8\u1294 \u1290\u12cd \u12eb\u1238\u1290\u1348\u12cd", "\u12a5\u1294 \u1290\u129d \u12eb\u1238\u1290\u134d\u12a9\u1275",
        "ene ashenefjku", "wetaleygn", "yene qitr weta",
        "ene belahu",
    ],
    "not_registered_complaint": [
        "11 \u1265\u12ec \u1290\u1260\u122d", "\u1208\u121d\u1295 \u12a0\u120d\u12eb\u12dd\u12ad\u120d\u129d\u121d 11", "21 \u12a0\u120d\u12eb\u12dd\u12ad\u120d\u129d\u121d",
        "\u1208\u121d\u1295 \u12a0\u120d\u12eb\u12dd\u12ad\u120d\u129d\u121d", "21 \u1208\u121d\u1295 \u12a0\u120d\u1218\u12d8\u1308\u1265\u12ad\u120d\u129d\u121d",
        "21 \u1240\u12f5\u121b\u1208\u12cd", "21 \u12e8\u1294 \u1290\u12cd", "21 \u12ed\u12e4 \u1290\u1260\u122d",
        "\u1241\u1325\u122c \u1270\u1240\u12f0\u1218", "\u1240\u12f5\u121e\u1265\u129b\u120d", "\u1240\u12f5\u121e\u1265\u129d",
        "lmin alyazkilgnim", "qedmalehu", "qedmobign",
        "yize neberku", "yene new", "qitre teqedeme",
    ],
    "payment_claim": [
        "\u120d\u12ac\u12eb\u1208\u12cd", "\u120d\u12aa\u12eb\u1208\u12cd", "\u120b\u12ad\u12eb\u1208\u12cd", "\u120d\u12ac\u120d\u1203\u1208\u12cd", "\u120d\u12ac\u12cb\u1208\u1201", "\u120d\u12ac\u12eb\u1208\u1201",
        "\u1270\u120d\u12b3\u120d", "\u120d\u12a9\u12a0\u1208\u12cd", "\u12f0\u122d\u1237\u120d", "\u120b\u12ad\u1201", "\u120b\u12a8\u12cd", "\u120b\u12a9\u120d\u1203\u1208\u12cd",
        "\u1308\u1295\u12d8\u1265 \u120d\u12ac\u12eb\u1208\u1201", "\u1265\u122d \u120d\u12ac\u12eb\u1208\u1201", "\u1308\u1295\u12d8\u1265 \u120d\u12ac\u120d\u1203\u1208\u12cd", "\u1265\u122c\u1295 \u120d\u12ac\u12eb\u1208\u1201",
        "\u1308\u1295\u12d8\u1264\u1295 \u120d\u12ac\u12eb\u1208\u1201", "\u1265\u122c \u1270\u120d\u12b3\u120d", "\u1308\u1295\u12d8\u1264 \u1270\u120d\u12b3\u120d", "\u1308\u1295\u12d8\u1265 \u1270\u120d\u12b3\u120d",
        "\u1308\u1262 \u12a0\u122d\u130c\u12eb\u1208\u12cd", "\u1308\u1262 \u12a0\u12f5\u122d\u130c\u12eb\u1208\u12cd", "\u1308\u1262 \u12a0\u122d\u130c\u12cb\u1208\u1201", "\u1308\u1262 \u12a0\u122d\u130c\u12eb\u1208\u1201",
        "\u12a8\u134d\u12eb\u1208\u12cd", "\u1270\u12a8\u134d\u12eb\u1208\u12cd", "\u12a8\u134d\u12eb\u1208\u1201", "\u12ad\u134d\u12eb \u1348\u133d\u121c\u12eb\u1208\u1201", "\u12ad\u134d\u12eb \u12a0\u12f5\u122d\u130c\u12eb\u1208\u1201",
        "\u1275\u122b\u1295\u1235\u1348\u122d \u12a0\u12f5\u122d\u130c\u12eb\u1208\u1201", "\u1275\u122b\u1295\u1235\u1348\u122d \u12a0\u1228\u130d\u12a9", "\u1308\u1295\u12d8\u1265 \u12a0\u1235\u1270\u120b\u120d\u134c\u12eb\u1208\u1201",
        "\u12a0\u1201\u1295 \u120b\u12ad\u1201", "\u12c8\u12f2\u12eb\u12cd\u1291 \u120b\u12ad\u1201", "\u1308\u1293 \u120b\u12ad\u1201", "\u120d\u12ac \u1328\u122d\u123b\u1208\u1201",
        "\u1308\u1263 \u12a0\u12ed\u12f0\u120d", "\u1308\u1265\u1277\u120d", "\u12f0\u1228\u1230 \u12a0\u12ed\u12f0\u120d", "\u1308\u1295\u12d8\u1261 \u12f0\u122d\u1237\u120d",
        "done", "sent", "send \u12a0\u1228\u130d\u12a9", "paid", "just sent", "sent it",
        "already sent", "money sent", "payment done", "\u2705",
        "\u120d\u12ad\u12eb\u1208\u12cd", "\u120d\u12ad\u12eb\u1208\u1201",
        "lkiyalew", "lkyalew", "derso", "gebi argeyalew", "lkeyalew",
        "genzeb lkiyalew", "br lkiyalew", "keflew", "tekefyalew",
        "wediaw lekhu", "ahun lekhu", "gebito", "derso ayidel",
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


print("\U0001f527 Building intent vectors...")
TFIDF_VECTORS, GLOBAL_IDF = build_tfidf(INTENT_EXAMPLES)
print(f"\u2705 Intent engine ready \u2014 {len(TFIDF_VECTORS)} intents loaded")


# ================================================================
# TF-IDF LATIN RETRY THRESHOLD (env-configurable)
# ================================================================
# Jina embedding model latin/transliterated \u133d\u1201\u134d \u120b\u12ed (\u1208\u121d\u1233\u120c "sint alegn")
# \u12f0\u12ab\u121b \u12cd\u1324\u1275 \u1235\u1208\u121a\u1230\u1325\u1363 Jina "unknown" \u1232\u1218\u120d\u1235 (\u130d\u1295 \u122b\u1231 \u1230\u122d\u1276 \u12a8\u1206\u1290 \u2014 available=True)
# \u12a5\u1293 \u133d\u1201\u1349 latin \u134a\u12f0\u120d \u12ab\u1208\u12cd\u1363 TF-IDF \u1201\u1208\u1270\u129b \u1219\u12a8\u122b (retry) \u12eb\u12f0\u122d\u130b\u120d\u1362 \u12cd\u1324\u1271 \u12a8\u12da\u1205
# threshold \u1260\u120b\u12ed \u12a8\u1206\u1290 TF-IDF intent \u1270\u1240\u1265\u120e \u1325\u1245\u121d \u120b\u12ed \u12ed\u12cd\u120b\u120d\u1362
#
# ENV OVERRIDE: TFIDF_LATIN_THRESHOLD env var \u12ab\u1208 \u12a8\u12db \u12ed\u1290\u1260\u1263\u120d (redeploy
# \u1233\u12eb\u1235\u1348\u120d\u130d \u1208 testing \u1241\u1325\u122d \u1218\u1240\u12eb\u12e8\u122d \u12a5\u1295\u12f2\u127b\u120d)\u1362 \u12ab\u120d\u1270\u1240\u1218\u1320 \u12c8\u12ed\u121d \u120d\u12ad \u12eb\u120d\u1206\u1290 \u12ab\u120d\u1206\u1290
# \u1290\u1263\u122a 0.60 \u12ed\u12eb\u12db\u120d\u1362
def _read_tfidf_latin_threshold() -> float:
    val = os.environ.get("TFIDF_LATIN_THRESHOLD")
    if val is None:
        return 0.60
    try:
        score = float(val)
        if not (0.0 <= score <= 1.0):
            logger.warning(
                f"[Responder] TFIDF_LATIN_THRESHOLD={val} range (0.0-1.0) \u12cd\u132a \u1290\u12cd \u2014 \u1290\u1263\u122a 0.60 \u12ed\u12eb\u12db\u120d"
            )
            return 0.60
        return score
    except ValueError:
        logger.warning(f"[Responder] TFIDF_LATIN_THRESHOLD='{val}' \u1241\u1325\u122d \u12a0\u12ed\u12f0\u1208\u121d \u2014 \u1290\u1263\u122a 0.60 \u12ed\u12eb\u12db\u120d")
        return 0.60


TFIDF_LATIN_THRESHOLD = _read_tfidf_latin_threshold()
logger.info(
    f"[Responder] TFIDF_LATIN_THRESHOLD = {TFIDF_LATIN_THRESHOLD} "
    f"(env override: {'yes' if os.environ.get('TFIDF_LATIN_THRESHOLD') else 'no, default'})"
)


def _has_latin_chars(text: str) -> bool:
    """\u133d\u1201\u1349 \u12cd\u1235\u1325 \u1262\u12eb\u1295\u1235 \u12a0\u1295\u12f5 latin \u134a\u12f0\u120d (a-z/A-Z) \u12ab\u1208 True \u12ed\u1218\u120d\u1233\u120d\u1362"""
    return bool(re.search(r"[a-zA-Z]", text))


# ================================================================
# DETECT INTENT (TF-IDF) \u2014 legacy/emergency-only path.
# get_response_async() \u12a8\u12a0\u1201\u1295 \u1260\u128b\u120b Jina \u1265\u127b \u12ed\u1320\u1240\u121b\u120d (booking \u12ab\u120d\u1206\u1290)\u1362
# \u12ed\u1205 function still used by: get_response() when intent isn't
# passed in externally (e.g. direct/manual calls, tests).
# ================================================================

# ================================================================
# PAYMENT CLAIM HELPERS \u2014 \u12ad\u134d\u12eb \u12a5\u1295\u12f0\u120b\u12a8 \u12e8\u121a\u1246\u1320\u1228\u12cd \u2705 \u1265\u127b \u1290\u12cd (\u120c\u120b emoji \u12a0\u12ed\u12f0\u1208\u121d)
# ================================================================

def _is_check_only(text: str) -> bool:
    """message \u2705 (\u12a0\u1295\u12f5 \u12c8\u12ed\u121d \u1265\u12d9) \u1265\u127b \u12a8\u1206\u1290 True."""
    t = text.replace("\ufe0f", "").replace("\u200d", "")
    t = "".join(t.split())
    return bool(t) and set(t) <= {"\u2705"}


def _is_emoji_only_not_check(text: str) -> bool:
    """\u134a\u12f0\u120d/\u1241\u1325\u122d \u12e8\u120c\u1208\u12cd (emoji \u1265\u127b) \u12a5\u1293 \u2705 \u12e8\u120c\u1208\u1260\u1275 message \u12a8\u1206\u1290 True."""
    t = text.replace("\ufe0f", "").replace("\u200d", "")
    return bool(t.strip()) and not any(ch.isalnum() for ch in t) and "\u2705" not in t


_CLAIM_AM = [normalize_to_latin(w) for w in (
    "\u120d\u12ad\u12eb\u1208\u12cd", "\u120d\u12ac\u12eb\u1208\u12cd", "\u120d\u12aa\u12eb\u1208\u12cd", "\u120b\u12ad\u12eb\u1208\u12cd",
    "\u120d\u12ad\u12eb\u1208\u1201", "\u120d\u12ac\u12eb\u1208\u1201", "\u120d\u12ac\u120d\u1203\u1208\u12cd", "\u120d\u12ac\u12cb\u1208\u1201",
)]
# "\u120d\u12ad\u12eb\u1208\u12cd \u12a5\u12ae \u1208\u121d\u1295 \u1238\u1325\u12ad" \u12d3\u12ed\u1290\u1275 \u1245\u122c\u1273\u12ce\u127d \u1245\u122c\u1273 \u1206\u1290\u12cd \u12ed\u1240\u1325\u120b\u1209 (claim \u12a0\u12ed\u1206\u1291\u121d)
_CLAIM_BLOCK = [normalize_to_latin(w) for w in ("\u1208\u121d\u1295", "\u1238\u1325", "\u1238\u1320", "\u1290\u1240\u120d", "\u1290\u1245\u120d")] + ["lemin"]


def _is_explicit_payment_claim(text: str) -> bool:
    """\u130d\u120d\u133d \u12e8 "\u120d\u12ac\u12eb\u1208\u12cd/\u120d\u12ad\u12eb\u1208\u12cd" \u12c8\u12ed\u121d \u2705 \u12ad\u134d\u12eb \u1218\u120b\u12ad \u1218\u130d\u1208\u132b (\u1241\u1325\u122d \u12c8\u12ed\u121d \u1245\u122c\u1273 \u1243\u120d \u12a8\u120c\u1208)."""
    if re.search(r"\d", text):
        return False
    if _is_check_only(text):
        return True
    latin = normalize_to_latin(text)
    if any(b in latin for b in _CLAIM_BLOCK):
        return False
    return any(k in latin for k in _CLAIM_AM)


def detect_intent(text: str) -> tuple:
    latin = normalize_to_latin(text)
    numbers_in_text = re.findall(r"\d+", text)

    # \u2500\u2500 9+ digit account number detection (FIX 2) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    _continuous_nums = re.findall(r'\b\d{9,}\b', text)
    if _continuous_nums:
        return "account_query", 1.0

    # \u2500\u2500 payment_claim ("\u120d\u12ac\u12eb\u1208\u12cd"/"done"/"\u2705") \u2014 booking numbers \u12a8\u120c\u1208 \u1265\u127b
    # fast-path \u1270\u1348\u1275\u123d (\u1241\u1325\u122d \u12ab\u1208 parse_numbers/booking flow \u1245\u12f5\u121a\u12eb \u12ed\u1291\u1228\u12cd)
    PAYMENT_CLAIM_KW = [
        normalize_to_latin("\u120d\u12ac\u12eb\u1208\u12cd"), normalize_to_latin("\u120d\u12aa\u12eb\u1208\u12cd"),
        normalize_to_latin("\u120d\u12ad\u12eb\u1208\u12cd"), normalize_to_latin("\u120d\u12ad\u12eb\u1208\u1201"),
        normalize_to_latin("\u120b\u12ad\u12eb\u1208\u12cd"), normalize_to_latin("\u120d\u12ac\u120d\u1203\u1208\u12cd"),
        normalize_to_latin("\u120d\u12ac\u12cb\u1208\u1201"), normalize_to_latin("\u120d\u12ac\u12eb\u1208\u1201"),
        normalize_to_latin("\u1270\u120d\u12b3\u120d"), normalize_to_latin("\u120d\u12a9\u12a0\u1208\u12cd"),
        normalize_to_latin("\u12f0\u122d\u1237\u120d"), normalize_to_latin("\u120b\u12ad\u1201"),
        normalize_to_latin("\u120b\u12a8\u12cd"), normalize_to_latin("\u120b\u12a9\u120d\u1203\u1208\u12cd"),
        normalize_to_latin("\u1308\u1295\u12d8\u1265 \u120d\u12ac\u12eb\u1208\u1201"), normalize_to_latin("\u1265\u122d \u120d\u12ac\u12eb\u1208\u1201"),
        normalize_to_latin("\u1265\u122c \u1270\u120d\u12b3\u120d"), normalize_to_latin("\u1308\u1295\u12d8\u1264 \u1270\u120d\u12b3\u120d"),
        normalize_to_latin("\u1308\u1262 \u12a0\u122d\u130c\u12eb\u1208\u12cd"), normalize_to_latin("\u1308\u1262 \u12a0\u12f5\u122d\u130c\u12eb\u1208\u12cd"),
        normalize_to_latin("\u1308\u1262 \u12a0\u122d\u130c\u12eb\u1208\u1201"),
        normalize_to_latin("\u12a8\u134d\u12eb\u1208\u12cd"), normalize_to_latin("\u1270\u12a8\u134d\u12eb\u1208\u12cd"),
        normalize_to_latin("\u12a8\u134d\u12eb\u1208\u1201"), normalize_to_latin("\u12ad\u134d\u12eb \u1348\u133d\u121c\u12eb\u1208\u1201"),
        normalize_to_latin("\u1275\u122b\u1295\u1235\u1348\u122d \u12a0\u12f5\u122d\u130c\u12eb\u1208\u1201"), normalize_to_latin("\u1308\u1295\u12d8\u1265 \u12a0\u1235\u1270\u120b\u120d\u134c\u12eb\u1208\u1201"),
        normalize_to_latin("\u12a0\u1201\u1295 \u120b\u12ad\u1201"), normalize_to_latin("\u12c8\u12f2\u12eb\u12cd\u1291 \u120b\u12ad\u1201"),
        normalize_to_latin("\u120d\u12ac \u1328\u122d\u123b\u1208\u1201"), normalize_to_latin("\u1308\u1295\u12d8\u1261 \u12f0\u122d\u1237\u120d"),
        "done", "sent", "paid", "just sent", "sent it", "already sent",
        "money sent", "payment done",
        "lkiyalew", "lkyalew", "derso", "lkeyalew", "keflew", "tekefyalew",
    ]
    text_stripped = text.strip()
    if _is_check_only(text_stripped) or any(kw in latin for kw in PAYMENT_CLAIM_KW):
        if not numbers_in_text:
            return "payment_claim", 1.0

    # \u2500\u2500 i_won_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    I_WON_KW = [
        normalize_to_latin("\u1208\u1294 \u12c8\u1323\u120d\u129d"),
        normalize_to_latin("\u12a5\u1294 \u12a0\u1238\u1290\u134d\u12a9"),
        normalize_to_latin("\u12e8\u1294 \u1241\u1325\u122d \u12c8\u1323"),
        normalize_to_latin("\u12c8\u1323\u120d\u129d"),
        normalize_to_latin("\u12a5\u1294 \u1260\u120b\u12cd"),
        normalize_to_latin("\u12eb\u1238\u1290\u134d\u12a9\u1275"),
        "ene ashenefjku", "wetaleygn", "yene qitr weta", "ene belahu",
    ]
    if any(kw in latin for kw in I_WON_KW):
        return "i_won_query", 1.0

    # \u2500\u2500 winner_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    WINNER_KW = [
        normalize_to_latin("\u121b\u1295 \u12a0\u1238\u1290\u1348"),
        normalize_to_latin("\u121b\u1295 \u12d8\u130b"),
        normalize_to_latin("\u121b\u1295 \u1260\u120b"),
        normalize_to_latin("\u121b\u1290\u12cd \u12e8\u12d8\u130b\u12cd"),
        normalize_to_latin("\u121b\u1290\u12cd \u12e8\u1260\u120b\u12cd"),
        normalize_to_latin("\u12a0\u1238\u1293\u134a\u12cd"),
        "man asheneffe", "man zega", "man bela", "ashenafiw",
    ]
    if any(kw in latin for kw in WINNER_KW):
        return "winner_query", 1.0

    # \u2500\u2500 balance_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    BALANCE_KW = [
        normalize_to_latin("\u1235\u1295\u1275 \u1265\u122d \u12a0\u1208\u129d"),
        normalize_to_latin("\u1235\u1295\u1275 \u1240\u122a \u12a0\u1208\u129d"),
        normalize_to_latin("\u12a0\u1295\u1270\u130b \u1235\u1295\u1275 \u12a0\u1208\u129d"),
        normalize_to_latin("\u1265\u122c \u1235\u1295\u1275 \u1290\u12cd"),
        normalize_to_latin("\u121d\u1295 \u12eb\u1205\u120d \u1265\u122d \u12a0\u1208\u129d"),
        normalize_to_latin("\u1240\u122a balance"),
        "antenga sint alegn", "balance sint", "sint br alegn",
    ]
    BALANCE_SINT_ALEGN = normalize_to_latin("\u1235\u1295\u1275 \u12a0\u1208\u129d")
    if any(kw in latin for kw in BALANCE_KW):
        return "balance_query", 1.0
    if BALANCE_SINT_ALEGN in latin and not numbers_in_text:
        return "balance_query", 1.0

    # \u2500\u2500 shortfall_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    SHORTFALL_KW = [
        normalize_to_latin("\u1235\u1295\u1275 \u120d\u1328\u121d\u122d"),
        normalize_to_latin("\u1235\u1295\u1275 \u120d\u1219\u120b"),
        normalize_to_latin("\u1235\u1295\u1275 \u12ed\u130e\u120b\u120d"),
        normalize_to_latin("\u1235\u1295\u1275 \u12eb\u1235\u1328\u121d\u122b\u120d"),
        normalize_to_latin("\u1235\u1295\u1275 \u1265\u122d \u12ed\u1240\u122b\u120d"),
        normalize_to_latin("\u1201\u1209\u121d \u2705 \u1208\u1218\u1206\u1295"),
        "sint lijevmer", "sint yigolal", "sint yasijemir", "sint limula",
    ]
    if any(kw in latin for kw in SHORTFALL_KW):
        return "shortfall_query", 1.0

    # \u2500\u2500 not_registered_complaint \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    NOT_REG_KW = [
        normalize_to_latin("\u1240\u12f5\u121b\u1208\u12cd"),
        normalize_to_latin("\u1240\u12f5\u121e\u1265\u129d"),
        normalize_to_latin("\u1240\u12f5\u121e\u1265\u129b\u120d"),
        normalize_to_latin("\u12ed\u12e4 \u1290\u1260\u122d"),
        normalize_to_latin("\u12e8\u1294 \u1290\u12cd"),
        normalize_to_latin("\u1265\u12ec \u1290\u1260\u122d"),
        "qedmalehu", "qedmobign", "yize neberku",
    ]
    NOT_REG_LMIN_KW = [
        normalize_to_latin("\u1208\u121d\u1295 \u12a0\u120d\u12eb\u12dd\u12ad\u120d\u129d\u121d"),
        normalize_to_latin("\u1208\u121d\u1295 \u12a0\u120d\u1218\u12d8\u1308\u1265\u12ad\u120d\u129d\u121d"),
        "lmin alyazkilgnim",
    ]
    if any(kw in latin for kw in NOT_REG_KW) and numbers_in_text:
        return "not_registered_complaint", 1.0
    if any(kw in latin for kw in NOT_REG_LMIN_KW) and numbers_in_text:
        return "not_registered_complaint", 1.0

    # \u2500\u2500 account keywords \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    ACCOUNT_KW_LAT = [
        "akawnt", "akaunt", "akount",
        "telebirr", "telebr", "awash", "cbe",
        "nigid bank", "bank akawnt",
    ]
    ACCOUNT_KW_AMH_LAT = [
        normalize_to_latin("\u12a0\u12ab\u12cd\u1295\u1275"),
        normalize_to_latin("\u1274\u120c\u1265\u122d"),
        normalize_to_latin("\u12a0\u12cb\u123d"),
        normalize_to_latin("\u1232\u1262\u12a2"),
        normalize_to_latin("\u1295\u130d\u12f5 \u1263\u1295\u12ad"),
        normalize_to_latin("\u12e8\u121a\u12a8\u1348\u120d\u1260\u1275 \u1241\u1325\u122d"),
        normalize_to_latin("\u12e8\u1263\u1295\u12ad \u1241\u1325\u122d"),
    ]
    if any(kw in latin for kw in ACCOUNT_KW_LAT + ACCOUNT_KW_AMH_LAT):
        return "account_query", 1.0

    # \u2500\u2500 link request \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    LINK_KW = [normalize_to_latin("\u120a\u1295\u12ad"), "link"]
    if any(kw in latin for kw in LINK_KW):
        return "link_request", 1.0

    # \u2500\u2500 speed request \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    SPEED_KW = [
        normalize_to_latin("\u12ed\u134d\u1320\u1295"),
        normalize_to_latin("\u1348\u1320\u1295 \u1348\u1320\u1295"),
        normalize_to_latin("\u134d\u1320\u1295"),
        "speed", "yiftsen", "fetsen",
    ]
    if any(kw in latin for kw in SPEED_KW):
        return "speed_request", 1.0

    # \u2500\u2500 my numbers query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    MY_NUM_KW = [
        normalize_to_latin("\u121d\u1295 \u1241\u1325\u122d \u12eb\u12dd\u12ad\u120d\u129d"),
        normalize_to_latin("\u1235\u1295\u1275 \u1241\u1325\u122e\u127d\u1295 \u1290\u12cd \u12e8\u12eb\u12dd\u12a9\u1275"),
        normalize_to_latin("\u121d\u1295 \u1241\u1325\u122e\u127d \u12eb\u12dd\u12a9"),
        normalize_to_latin("\u1241\u1325\u122e\u127c"),
        normalize_to_latin("\u12eb\u12d8\u12dd\u12a9\u1275 \u1241\u1325\u122d"),
        normalize_to_latin("\u121d\u1295 \u1241\u1325\u122e\u127d \u133b\u134d\u12ad\u120d\u129d"),
        normalize_to_latin("\u1241\u1325\u122e\u127c\u1295 \u1295\u1308\u1228\u129d"),
        normalize_to_latin("\u1241\u1325\u122e\u127c\u1295 \u12a0\u1233\u12cd\u1240\u129d"),
        normalize_to_latin("\u12e8\u12eb\u12dd\u12ad\u120d\u129d \u1241\u1325\u122d \u12a0\u1208"),
        normalize_to_latin("\u1235\u1295\u1275 \u1241\u1325\u122d \u1290\u12cd \u12e8\u1294"),
    ]
    if any(kw in latin for kw in MY_NUM_KW):
        return "my_numbers_query", 1.0

    # \u2500\u2500 claim ownership ("11 \u12e8\u1294 \u1290\u12cd") \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if numbers_in_text:
        CLAIM_KW = [
            normalize_to_latin("\u12e8\u1294 \u1290\u12cd"),
        ]
        if any(kw in latin for kw in CLAIM_KW):
            return "claim_ownership", 1.0

    # \u2500\u2500 number owner query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if numbers_in_text:
        OWNER_KW = [
            normalize_to_latin("\u1208\u121b\u1295 \u12eb\u12d8"),
            normalize_to_latin("\u1208\u121b\u1295 \u1290\u12cd"),
            normalize_to_latin("\u12e8\u121b\u1290\u12cd"),
            normalize_to_latin("\u1208\u121b\u1295 \u1270\u12eb\u12d8"),
            normalize_to_latin("\u1208\u121b\u1295 \u1218\u12d8\u1308\u1265\u12ad"),
        ]
        if any(kw in latin for kw in OWNER_KW):
            return "number_owner_query", 1.0

    # \u2500\u2500 change number \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if len(numbers_in_text) >= 2:
        change_result = detect_change_number(text)
        if change_result:
            return "change_number", 1.0

    # \u2500\u2500 type change \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    TYPE_FULL_LAT = [normalize_to_latin("\u1260\u1219\u1209"), normalize_to_latin("\u1219\u1209"), "bemulu", "mulu"]
    TYPE_HALF_LAT = [normalize_to_latin("\u1260\u130d\u121b\u123d"), normalize_to_latin("\u130d\u121b\u123d"), "begmash", "gmash"]
    has_type_full = any(w in latin for w in TYPE_FULL_LAT)
    has_type_half = any(w in latin for w in TYPE_HALF_LAT)
    if numbers_in_text and (has_type_full or has_type_half):
        TYPE_ACTION_LAT = [
            normalize_to_latin("\u12a0\u122d\u130d"), normalize_to_latin("\u12a0\u12f5\u122d\u130d"),
            normalize_to_latin("\u12ed\u1201\u1295"), normalize_to_latin("\u1240\u12ed\u122d"),
            "areg", "adrig", "yihun", "qeyir", "keyir",
        ]
        if any(w in latin for w in TYPE_ACTION_LAT):
            return "type_change", 1.0

    # \u2500\u2500 why not registered \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    WHY_NOT_LAT = [
        normalize_to_latin("\u1208\u121d\u1295 \u12a0\u120d\u12eb\u12dd"),
        normalize_to_latin("\u1208\u121d\u1295 \u12a0\u120d\u1343\u134d"),
        normalize_to_latin("\u1208\u121d\u1295 \u12a0\u120d\u1270\u12eb\u12d8"),
        normalize_to_latin("\u1208\u121d\u1295 \u12a0\u120d\u1308\u1263"),
        "lmin alyaz", "lmin altsaf", "lmin alteyaz", "lmin algeba",
    ]
    if any(w in latin for w in WHY_NOT_LAT):
        return "why_not_registered", 1.0

    # \u2500\u2500 result query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    RESULT_KW = [
        normalize_to_latin("\u12cd\u1324\u1275"),
        normalize_to_latin("\u1235\u1295\u1275 \u1241\u1325\u122d \u12c8\u1323"),
        normalize_to_latin("\u121d\u1295 \u1241\u1325\u122d \u12c8\u1323"),
        normalize_to_latin("\u12e8\u12c8\u1323\u12cd"),
        "wetset", "sint qitr weta", "min qitr weta",
    ]
    if any(kw in latin for kw in RESULT_KW):
        return "result_query", 1.0

    # \u2500\u2500 prize query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    PRIZE_KW = [
        normalize_to_latin("\u12f0\u122b\u123d"),
        normalize_to_latin("\u123d\u120d\u121b\u1275"),
        "derash", "shilmat", "prize",
    ]
    if any(kw in latin for kw in PRIZE_KW):
        return "prize_query", 1.0

    # \u2500\u2500 payment not received \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    PAYMENT_NOT_RECV = [
        normalize_to_latin("\u1265\u122d \u12a0\u120d\u12f0\u1228\u1230\u129d\u121d"),
        normalize_to_latin("\u12a0\u120d\u1308\u1263\u120d\u129d\u121d"),
        normalize_to_latin("\u1265\u122d \u12a0\u120d\u1308\u1263\u121d"),
        normalize_to_latin("\u1265\u122d \u120b\u12ad\u120d\u129d"),
        normalize_to_latin("\u1208\u121d\u1295 \u12a0\u1275\u120d\u12ad\u121d"),
        "br alderesegnim", "br algeba", "lemin atlikm",
    ]
    if any(kw in latin for kw in PAYMENT_NOT_RECV):
        return "payment_not_received", 1.0

    # \u2500\u2500 players remaining query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    PLAYERS_REM = [
        normalize_to_latin("\u1235\u1295\u1275 \u1230\u12cd \u1240\u1228"),
        normalize_to_latin("\u1235\u1295\u1275 \u1230\u12ce\u127d \u1240\u1229"),
        normalize_to_latin("\u1240\u122a \u1230\u12cd"),
        "sint sew qere", "qeri sew",
    ]
    if any(kw in latin for kw in PLAYERS_REM):
        return "players_remaining_query", 1.0

    # \u2500\u2500 players query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    PLAYERS_KW = [
        normalize_to_latin("\u1235\u1295\u1275 \u1230\u12cd \u1290\u12cd"),
        normalize_to_latin("\u12a8\u1235\u1295\u1275 \u1230\u12cd \u130b\u122d \u1290\u12cd"),
        "sint sew new", "kesint sew gar new",
    ]
    if any(kw in latin for kw in PLAYERS_KW):
        return "players_query", 1.0

    # \u2500\u2500 price query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    PRICE_KW = [
        normalize_to_latin("\u12cb\u130b \u1235\u1295\u1275"),
        normalize_to_latin("\u12cb\u130b\u12cd \u1235\u1295\u1275"),
        normalize_to_latin("\u121d\u1295 \u12eb\u1205\u120d \u1265\u122d"),
        normalize_to_latin("\u1235\u1295\u1275 \u12eb\u1235\u12a8\u134d\u120b\u120d"),
        "wagaw sint", "min yahil br",
    ]
    PRICE_SINT_NEW = normalize_to_latin("\u1235\u1295\u1275 \u1290\u12cd")
    if not numbers_in_text and PRICE_SINT_NEW in latin:
        return "price_query", 1.0
    if any(kw in latin for kw in PRICE_KW):
        return "price_query", 1.0

    # \u2500\u2500 specific number query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    ALE_LAT    = normalize_to_latin("\u12a0\u1208")
    TEYAZE_LAT = [normalize_to_latin(w) for w in ["\u1270\u12eb\u12d8", "\u1270\u12ed\u12de", "\u1270\u12ed\u12d9\u12cb\u120d"]]
    has_ale    = ALE_LAT in latin.split()
    has_teyaze = any(w in latin for w in TEYAZE_LAT)
    if numbers_in_text and (has_ale or has_teyaze):
        return "specific_number_query", 1.0

    # \u2500\u2500 cancel number \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    CANCEL_LAT = [
        normalize_to_latin(w) for w in
        ["\u12a0\u120d\u1348\u120d\u130d\u121d", "\u123d\u1320\u12cd", "\u12a0\u1325\u134b\u12cd", "\u12ed\u1325\u134b", "\u1230\u122d\u12dd", "\u12a0\u12cd\u1323", "\u12a0\u1325\u134b\u120d\u129d", "\u1230\u122d\u12dd\u120d\u129d"]
    ] + ["alfeligm", "alfelegim", "serzew", "serz", "atfaw", "atfa", "awta"]
    if len(numbers_in_text) == 1 and any(w in latin for w in CANCEL_LAT):
        return "cancel_number", 1.0

    # \u2500\u2500 TF-IDF cosine fallback \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

    # \u2500\u2500 FIX: confidence calibration \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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
        "\u12a5\u123a \u1308\u1262 \U0001f64f", "\u12a5\u123a \u1308\u1262 \u12a5\u1295\u12f3\u12ed\u1228\u1233 \U0001f64f",
        "\u12a5\u123a \u1308\u1262 \u1264\u1270\u1230\u1265 \U0001f64f", "\u12a5\u123a \U0001f64f \u1308\u1262 \u12ed\u120b\u12ad",
    ],
    "booking_success_paid": [
        "\u12a5\u123a \u1264\u1270\u1230\u1265 \U0001f64f", "\u12a5\u123a \u12c8\u12f3\u1304 \U0001f970",
    ],
    "booking_success_urgent": [
        "\u12a5\u123a \u1264\u1270\u1230\u1265 \u12ed\u134d\u1320\u1295 \U0001f64f", "\u12ed\u12dd\u1204\u120d\u1203\u1208\u12cd \u1264\u1270\u1230\u1265 \u12ed\u134d\u1320\u1295 \U0001f64f",
        "\u12a5\u123a \u1208\u132b\u12c8\u1273\u12cd \u12f5\u121d\u1240\u1275 \u12ed\u134d\u1320\u1295 \U0001f64f", "\u12a5\u123a \u1308\u1262 \U0001f64f",
    ],
    "booking_taken": [
        "\u1264\u1270\u1230\u1265 \u1270\u1240\u12f0\u121d\u12ad \U0001f64f", "\u12e8\u1208\u121d \u1264\u1270\u1230\u1265 \u120c\u120b \u121d\u1228\u1325 \U0001f64f",
        "\u1240\u12ed\u122d \u12e8\u1208\u121d \U0001f64f", "\u1270\u1240\u12f0\u121d\u12ad \U0001f64f \u12c8\u12f3\u1304", "\u1270\u12ed\u12d9\u12cb\u120d \u1240\u12ed\u122d \U0001f64f",
    ],
    "number_available": [
        "\u12a0\u12ce \u12a0\u1208 \u12ad\u134d\u1275 \u1290\u12cd \U0001f64f", "\u12a0\u1208 \u1264\u1270\u1230\u1265 \u12ad\u134d\u1275 \u1290\u12cd \U0001f64f", "\u12ad\u134d\u1275 \u1290\u12cd \u12eb\u12dd \U0001f64f",
    ],
    "number_taken": [
        "\u1270\u12ed\u12df\u120d \u1264\u1270\u1230\u1265 \U0001f64f", "\u12e8\u1208\u121d \u1270\u12c8\u1235\u12f7\u120d \U0001f64f", "\u1270\u1240\u12f0\u121d\u12ad \u1264\u1270\u1230\u1265 \U0001f64f",
    ],
    "nekay_exists": [
        "\u12a5\u123a \u1264\u1270\u1230\u1265 \u12a5\u1290\u12da\u12cd\u1275", "\u12a0\u1208 \u1264\u1270\u1230\u1265 \U0001f970",
        "\u12a5\u123a \u120d\u1348\u120d\u130d\u120d\u1205 \U0001f64f", "\u12a0\u1209 \u12e8\u1270\u12c8\u1230\u1291 \u1241\u1325\u122e\u127d",
    ],
    "nekay_none_remaining": [
        "\u1240\u122a \u1241\u1325\u122e\u127d \u12a0\u1209 \U0001f64f", "\u1264\u1270\u1230\u1265 \u12a0\u120b\u1208\u1240\u121d \u1240\u122a \u1241\u1325\u122e\u127d \u12a0\u1209 \U0001f64f",
    ],
    "nekay_all_done": [
        "\u1264\u1270\u1230\u1265 \u12e8\u1208\u121d \u12a0\u120d\u1241\u12cb\u120d \u1240\u1323\u12ed \u12ed\u121e\u12ad\u1229 \U0001f64f", "\u12a0\u1208\u1240 \U0001f64f", "\u1264\u1270\u1230\u1265 \u12a0\u12cd\u1295 \u1308\u1293 \u12a0\u1208\u1240 \U0001f64f",
    ],
    "remaining_send_ack": ["\u12a5\u123a \U0001f64f"],
    "all_taken_nekay": ["\u12a0\u12ce \u1270\u12ed\u12d8\u12cb\u120d \u1290\u1243\u12ed \u1320\u1265\u1245 \u1264\u1270\u1230\u1265 \U0001f64f"],
    "cancel_number_ack": ["\u12a5\u123a \u1270\u1230\u122d\u12df\u120d \U0001f64f", "\u12a5\u123a \u1270\u1290\u1245\u120f\u120d \U0001f64f"],
    "complaint_removed_taken": [
        "\u12a0\u12ce \u1308\u1262 \u121b\u1228\u130d \u1228\u1233\u12ad \u12e8\u132b\u12c8\u1273\u12cd \u1263\u1205\u122a \u1290\u12cd \U0001f64f",
        "\u1264\u1270\u1230\u1265 \u1308\u1262 \u1233\u1273\u122d\u130d \u1241\u1325\u1209 \u12ed\u1208\u1240\u1243\u120d \U0001f64f",
        "\u1308\u1262 \u121b\u1228\u130d \u1228\u1233\u1205 \u1264\u1270\u1230\u1265 \u12e8\u132b\u12c8\u1273\u12cd \u1215\u130d \u1290\u12cd \U0001f64f",
    ],
    "complaint_removed_nekay": [
        "\u1270\u1290\u1243\u12ed list \u12cd\u1235\u1325 \u1308\u1265\u1277\u120d \u1308\u1262 \u12a0\u122d\u12f0\u12cd \u12eb\u1228\u130b\u130d\u1321 \U0001f64f",
        "\u1241\u1325\u122d\u12ce \u1290\u1243\u12ed \u1290\u12cd \u1308\u1262 \u12a0\u1228\u130b\u130d\u1321 \U0001f64f",
        "\u1290\u1243\u12ed \u1290\u12cd \u1264\u1270\u1230\u1265 \u1276\u120e \u1308\u1262 \u12a0\u122d\u1309 \U0001f64f",
    ],
    "complaint_why_sold": [
        "\u1308\u1262 \u1270\u1228\u1233 \u1264\u1270\u1230\u1265 \u121d\u1295 \u120b\u122d\u130d \U0001f64f",
        "\u1264\u1270\u1230\u1265 \u1308\u1262 \u1233\u12ed\u12f0\u122d\u1235 \u1241\u1325\u1229 \u1270\u1208\u1240\u1240 \u121d\u1295 \u120b\u122d\u130d \U0001f64f",
        "\u1308\u1262 \u12a0\u120d\u12f0\u1228\u1230\u121d \u1264\u1270\u1230\u1265 \u121d\u1295 \u120b\u122d\u130d \U0001f64f",
    ],
    "complaint_paid_removed": [
        "\u127c\u12ad \u12a0\u122d\u130d \u127d\u130d\u122d \u12ab\u1208 \u1263\u1208\u1264\u1271\u1295 \u12a0\u12cd\u122b\u12cd \U0001f64f",
        "\u1263\u1208\u1264\u1271\u1295 \u12a0\u1293\u130d\u122d \u127c\u12ad \u12eb\u122d\u130b\u120d \U0001f64f",
        "\u127d\u130d\u122d \u12ab\u1208 \u1263\u1208\u1264\u1271\u1295 \u12a0\u12cd\u122b\u12cd \u127c\u12ad \u12eb\u122d\u130b\u120d \U0001f64f",
        "\u1263\u1208\u1264\u1271\u1295 \u12a0\u1293\u130d\u1228\u12cd \u127c\u12ad \u12eb\u122d\u130b\u1209 \U0001f64f",
    ],
    "change_number_ack": [
        "\u12a5\u123a\U0001f64f {from_num} \u12c8\u12f0 {to_num} \u1240\u12ed\u122d\u12eb\u1208\u12cd",
        "\u12a5\u123a \u1264\u1270\u1230\u1265\U0001f64f {from_num} \u12c8\u12f0 {to_num} \u1270\u1240\u12ed\u122f\u120d",
        "\u1270\u1240\u12ed\u122f\u120d\U0001f64f {from_num} \u2192 {to_num}",
    ],
    "change_number_not_yours": [
        "\u1241\u1325\u1209 \u12e8\u12a5\u122d\u1235\u12ce \u12a0\u12ed\u12f0\u1208\u121d \U0001f64f",
        "{from_num} \u12e8\u12a5\u122d\u1235\u12ce \u1241\u1325\u122d \u12a0\u12ed\u12f0\u1208\u121d \U0001f64f",
    ],
    "change_number_target_taken": [
        "{to_num} \u1270\u12ed\u12df\u120d \u1264\u1270\u1230\u1265 \u120c\u120b \u121d\u1228\u1325 \U0001f64f",
        "\u1264\u1270\u1230\u1265 {to_num} \u12ad\u134d\u1275 \u12a0\u12ed\u12f0\u1208\u121d \u120c\u120b \u121d\u1228\u1325 \U0001f64f",
    ],
    "change_number_invalid": [
        "\u1241\u1325\u1229 \u1275\u12ad\u12ad\u120d \u12a0\u12ed\u12f0\u1208\u121d \U0001f64f", "\u12eb \u1241\u1325\u122d \u12e8\u1208\u121d \U0001f64f",
    ],
    "type_change_ack": [
        "\u12a5\u123a \U0001f64f", "\u12a5\u123a \u1264\u1270\u1230\u1265 \U0001f64f", "\u1270\u1240\u12ed\u122f\u120d \U0001f64f",
    ],
    "type_change_conflict": [
        "\u1241\u1325\u1229 {num} slot 2 \u1270\u12ed\u12df\u120d \u1218\u1240\u12e8\u122d \u12a0\u12ed\u127b\u120d\u121d \U0001f64f",
        "{num} \u120c\u120b \u1230\u12cd slot 2 \u120b\u12ed \u12a0\u1208 \U0001f64f",
    ],
    "type_change_not_yours": [
        "\u1241\u1325\u1229 \u12e8\u12a5\u122d\u1235\u12ce \u12a0\u12ed\u12f0\u1208\u121d \U0001f64f",
        "{num} \u12e8\u12a5\u122d\u1235\u12ce \u1241\u1325\u122d \u12a0\u12ed\u12f0\u1208\u121d \U0001f64f",
    ],
    "why_not_registered_taken": [
        "{num} \u2014 {name} \u1240\u12f0\u121d\u1205 ({type}) \u2014 {time} \U0001f64f",
        "\u1264\u1270\u1230\u1265 {num} \u1240\u12f5\u121e \u1270\u12c8\u1235\u12f7\u120d \u2014 {name} ({type}) {time} \U0001f64f",
    ],
    "why_not_registered_taken_both": [
        "{num} \u2014 slot1: {name1} ({type1}), slot2: {name2} \u2014 {time} \U0001f64f",
    ],
    "why_not_registered_range": [
        "{num} \u12a8 total \u1241\u1325\u122e\u127d \u12cd\u132d \u1290\u12cd \U0001f64f",
        "\u1241\u1325\u122d {num} \u12e8\u1208\u121d \U0001f64f",
    ],
    "why_not_registered_none": [
        "\u1218\u127c \u1290\u12cd \u1264\u1270\u1230\u1265 \U0001f64f \u1270\u1233\u1235\u1270\u1203\u120d \u127c\u12ad \u12a0\u12f5\u122d\u130d",
        "\u1264\u1270\u1230\u1265 \u12eb \u1241\u1325\u122d \u121e\u12ad\u1228\u1203\u120d \u12a0\u120b\u12cd\u1245\u121d \u127c\u12ad \u12a0\u12f5\u122d\u130d \U0001f64f",
    ],
    "winner_greeting": [
        "\u12a5\u1295\u12b3\u1295 \u12f0\u1235 \u12a0\u1208\u12ad \u12c8\u12f3\u1304 \U0001f970",
        "congraaaaa \u1264\u1270\u1230\u1265 \U0001f970",
        "\u1261\u121d \u1261\u121d \u1348\u1290\u12f3 congraaaa \U0001f389",
        "\u1348\u1290\u12f3 \u1264\u1270\u1230\u1265 \u12a5\u1295\u12b3\u1295 \u12f0\u1235 \u12a0\u1208\u12ad \U0001f970",
        "champion \u12a5\u1295\u12b3\u1295 \u12f0\u1235 \u12a0\u1208\u12ad \U0001f3c6\U0001f970",
    ],
    "nekay_countdown_wait": [
        "\u1264\u1270\u1230\u1265 \u1275\u1295\u123d \u12ed\u1320\u1265\u1241 \u1290\u1243\u12ed \u120b\u12c8\u1323 \u1290\u12cd \U0001f64f",
    ],
    "price_query_full_only": [
        "{price_full} \u1265\u122d \u1290\u12cd \U0001f64f",
        "\u1264\u1271 {price_full} \u1265\u122d \u1290\u12cd \U0001f64f",
        "{price_full} \u1265\u122d \u1290\u12cd \u1264\u1270\u1230\u1265 \U0001f64f",
    ],
    "price_query_full_and_half": [
        "\u1219\u1209 {price_full} \u1265\u122d\u1363 \u130d\u121b\u123d {price_half} \u1265\u122d \u1290\u12cd \U0001f64f",
        "{price_full} \u1265\u122d \u1219\u1209 / {price_half} \u1265\u122d \u130d\u121b\u123d \u1290\u12cd \U0001f64f",
    ],
    "prize_query": [
        "{prize_1st} \u12f0\u122b\u123d \u1290\u12cd \u1264\u1270\u1230\u1265 \U0001f64f",
        "1\u129b {prize_1st} \u1265\u122d \u12f0\u122b\u123d \u1290\u12cd \U0001f64f",
    ],
    "players_query": [
        "{players_count} \u1230\u12cd \u1290\u12cd \u1264\u1270\u1230\u1265 \U0001f64f",
        "\u1328\u12cb\u1273\u12cd \u1208{players_count} \u1230\u12cd \u1290\u12cd \U0001f64f",
    ],
    "players_remaining_query": [
        "{players_remaining} \u1230\u12cd \u1240\u1228 \u1264\u1270\u1230\u1265 \U0001f64f",
        "\u1240\u122a {players_remaining} \u1230\u12cd \u12a0\u1208 \U0001f64f",
    ],
    "payment_not_received": [
        "\u127d\u130d\u122d \u12ab\u1208 \u12a0\u132b\u12cb\u1279\u1295 \u1260\u12cd\u1235\u1325 \u12a0\u12cd\u122b\u12cd \U0001f64f",
        "\u1263\u1208\u1264\u1271\u1295 \u1260\u12cd\u1235\u1325 \u12a0\u1293\u130d\u122d \u12ed\u1348\u1273\u12cb\u120d \U0001f64f",
    ],
    "result_query_waiting": [
        "\u12cd\u1324\u1275 \u12a5\u12e8\u1270\u120b\u12a8 \u1290\u12cd \u1275\u1295\u123d \u12ed\u1320\u1265\u1241 \U0001f64f",
        "\u1275\u1295\u123d \u12ed\u1320\u1265\u1241 \u12cd\u1324\u1275 \u12ed\u120b\u12ab\u120d \U0001f64f",
    ],
    "result_query_show": [
        "\U0001f947 1\u129b: {first}\n\U0001f948 2\u129b: {second}\n\U0001f949 3\u129b: {third}",
        "\u12cd\u1324\u1275 \U0001f3c6\n1\u129b: {first}\n2\u129b: {second}\n3\u129b: {third}",
    ],
    "result_query_none": [
        "\u1308\u1293 \u12cd\u1324\u1275 \u12e8\u1208\u121d \u1264\u1270\u1230\u1265 \U0001f64f",
        "\u12cd\u1324\u1275 \u12a0\u120d\u1270\u120b\u12a8\u121d \u1264\u1270\u1230\u1265 \U0001f64f",
    ],
    "my_numbers_none": [
        "\u121d\u1295\u121d \u1241\u1325\u122d \u12a0\u120d\u1270\u12eb\u12d8\u120d\u1205\u121d \u1264\u1270\u1230\u1265 \U0001f64f",
        "\u1241\u1325\u122d \u12a0\u120d\u12eb\u12dd\u12ad\u121d \u1264\u1270\u1230\u1265 \U0001f64f",
    ],
    "my_numbers_show": [
        "{numbers_text} \u1270\u12ed\u12de\u120d\u1203\u120d \u1264\u1270\u1230\u1265 \U0001f64f",
        "\u12e8\u12eb\u12dd\u12ab\u1278\u12cd: {numbers_text} \u1264\u1270\u1230\u1265 \U0001f64f",
    ],
    "number_owner_show": [
        "\u1208 {name} \u1270\u12eb\u12d8 \u1264\u1270\u1230\u1265 \U0001f64f",
        "{name} \u12eb\u12d8\u12cb\u120d \u1264\u1270\u1230\u1265 \U0001f64f",
    ],
    "number_owner_yours": [
        "\u1264\u1270\u1230\u1265 \U0001f64f \u12ed\u12dd\u1204\u120d\u1203\u1208\u12cd \u12eb\u1295\u1270 \u1290\u12cd",
        "\u12eb\u1295\u1270 \u1290\u12cd \u1264\u1270\u1230\u1265 \U0001f64f",
    ],
    "number_owner_multi": [
        "{owners_text} \u1264\u1270\u1230\u1265 \U0001f64f",
    ],
    "number_owner_free": [
        "\u12ad\u134d\u1275 \u1290\u12cd \u12eb\u12dd \U0001f64f",
        "\u121d\u1295\u121d \u1230\u12cd \u12a0\u120d\u12eb\u12d8\u12cd\u121d \u12eb\u12dd \U0001f64f",
    ],
    "claim_ownership_yes": [
        "\u12a0\u12ce \u1264\u1270\u1230\u1265 \U0001f64f",
    ],
    "claim_ownership_no": [
        "\u1264\u1270\u1230\u1265 \u12eb\u1295\u1270 \u12a0\u12f0\u1208\u121d \u12e8 {name} \u1290\u12cd \U0001f64f",
    ],
    "link_request": [
        "\u12a5\u123a \u1260\u12cd\u1235\u1325 \u12a5\u120d\u12ad\u120d\u1203\u1208\u1201 \U0001f64f",
        "\u12a5\u123a \u1264\u1270\u1230\u1265 \u1260\u12cd\u1235\u1325 \u12a5\u120d\u12ab\u1208\u1201 \U0001f64f",
    ],
    "speed_request": [
        "\u12a5\u123a \U0001f64f \u12a5\u12e8\u121e\u12a8\u122d\u12a9 \u1290\u12cd",
        "\u12a5\u123a \u1264\u1270\u1230\u1265 \U0001f64f \u12a5\u12e8\u121e\u12a8\u122d\u12a9 \u1290\u12cd",
    ],
    # \u2500\u2500 NEW RESPONSES \u2500\u2500
    "balance_show": [
        "{balance} \u1265\u122d \u12a5\u1294\u130b \u12a0\u1208\u12ad \u1264\u1270\u1230\u1265 \U0001f64f",
        "\u1264\u1270\u1230\u1265 {balance} \u1265\u122d \u12a0\u1208\u1205 \U0001f64f",
    ],
    "balance_zero": [
        "0 \u1265\u122d \u12a0\u1208\u12ad \u1264\u1270\u1230\u1265 \U0001f64f",
        "\u1264\u1270\u1230\u1265 balance \u12e8\u1208\u1205\u121d \U0001f64f",
    ],
    "shortfall_show": [
        "\u1264\u1270\u1230\u1265 {numbers_text} \u2705 \u12a5\u1295\u12f2\u1206\u1295 {shortfall} \u1265\u122d \u12eb\u1235\u1348\u120d\u130b\u120d \U0001f64f",
        "{shortfall} \u1265\u122d \u12eb\u1235\u1328\u121d\u122d\u1203\u120d \u1264\u1270\u1230\u1265 ({numbers_text}) \U0001f64f",
    ],
    "shortfall_all_paid": [
        "\u1201\u1209\u121d \u2705 \u1290\u12cd \u1264\u1270\u1230\u1265 \u121d\u1295\u121d \u12a0\u12eb\u1235\u1348\u120d\u130d\u121d \U0001f64f",
        "\u1264\u1270\u1230\u1265 \u1201\u1209\u121d \u1270\u12a8\u134d\u120f\u120d \u2705 \U0001f64f",
    ],
    "shortfall_no_numbers": [
        "\u1241\u1325\u122d \u12a0\u120d\u12eb\u12dd\u12ad\u121d \u1264\u1270\u1230\u1265 \U0001f64f",
    ],
    "winner_show": [
        "\U0001f947 1\u129b\u1361 {first}\n\U0001f948 2\u129b\u1361 {second}\n\U0001f949 3\u129b\u1361 {third} \U0001f64f",
        "\u12a0\u1238\u1293\u134a\u12ce\u1279 \U0001f3c6\n1\u129b\u1361 {first}\n2\u129b\u1361 {second}\n3\u129b\u1361 {third} \U0001f64f",
    ],
    "winner_show_one": [
        "\U0001f947 1\u129b\u1361 {first} \U0001f64f",
    ],
    "winner_show_two": [
        "\U0001f947 1\u129b\u1361 {first}\n\U0001f948 2\u129b\u1361 {second} \U0001f64f",
    ],
    "winner_none": [
        "\u1308\u1293 \u12a0\u120d\u1270\u12c8\u1230\u1290\u121d \u1264\u1270\u1230\u1265 \U0001f64f",
        "\u12cd\u1324\u1275 \u12a0\u120d\u12c8\u1323\u121d \u1264\u1270\u1230\u1265 \U0001f64f",
    ],
    "i_won_yes": [
        "\u1264\u1270\u1230\u1265 \u12a0\u12ce {place}\u129b \u12c8\u1276\u120d\u1203\u120d \U0001f64f",
        "\u12a0\u12ce \u1264\u1270\u1230\u1265 {place}\u129b \u1206\u1290\u1203\u120d \U0001f3c6\U0001f64f",
    ],
    "i_won_no": [
        "\u1264\u1270\u1230\u1265 \u12a0\u120b\u1238\u1290\u134d\u12ad\u121d \U0001f64f\n\U0001f947 1\u129b\u1361 {first}\n\U0001f948 2\u129b\u1361 {second}\n\U0001f949 3\u129b\u1361 {third}",
        "\u12a0\u120b\u1238\u1290\u134d\u12ad\u121d \u1264\u1270\u1230\u1265 \U0001f64f\n1\u129b\u1361 {first}\n2\u129b\u1361 {second}\n3\u129b\u1361 {third}",
    ],
    "i_won_no_winners": [
        "\u1264\u1270\u1230\u1265 \u12a0\u120b\u1238\u1290\u134d\u12ad\u121d \u12c8\u12ed\u121d \u12cd\u1324\u1275 \u1308\u1293 \u12a0\u120d\u12c8\u1323\u121d \U0001f64f",
    ],
    "not_registered_taken": [
        "{num} \u2014 \u12a0\u1260\u1260 \u1235\u1208\u1240\u12f0\u1218\u12ad \u1290\u12cd \u1264\u1270\u1230\u1265 \U0001f64f",
        "\u1264\u1270\u1230\u1265 {num} {name} \u1240\u12f5\u121e\u1203\u120d \U0001f64f",
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
    """payment_info \u12cd\u1235\u1325 \u12eb\u1209 account numbers \u12eb\u12c8\u1323\u120d"""
    lines = payment_info.strip().split("\n")
    accounts = []
    bank_patterns = [
        (r"CBE", "CBE"),
        (r"Telebirr|Tele|\u1274\u120c\u1265\u122d", "Telebirr"),
        (r"Awash|\u12a0\u12cb\u123d", "Awash"),
        (r"Dashen|\u12f3\u123d\u1295", "Dashen"),
        (r"BOA|Abyssinia|\u12a0\u1262\u1232\u1292\u12eb", "BOA"),
        (r"Wegagen|\u12c8\u130b\u1308\u1295", "Wegagen"),
        (r"Nib|\u1295\u1265", "Nib"),
        (r"United|\u12e9\u1293\u12ed\u1275\u12f5", "United"),
        (r"Oromia|\u12a6\u122e\u121a\u12eb", "Oromia"),
        (r"Amhara|\u12a0\u121b\u122b", "Amhara"),
        (r"Coopbank|\u12ae\u1355", "Coopbank"),
        (r"Bunna|\u1261\u1293", "Bunna"),
        (r"Berhan|\u1265\u122d\u1203\u1295", "Berhan"),
        (r"Zemen|\u12d8\u1218\u1295", "Zemen"),
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
    """Returns: 'exact', 'close', or 'no_match'. close = 2 digit \u12c8\u12ed\u121d \u1260\u1273\u127d \u120d\u12e9\u1290\u1275"""
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
    # \u2500\u2500 params \u2500\u2500
    user_balance: float = None,
    failed_attempts: list = None,
    is_paid: bool = None,
    # \u2500\u2500 intent \u12a8\u12cd\u132a (\u1208\u121d\u1233\u120c Jina) \u1232\u120b\u12ad \u1325\u1245\u121d \u120b\u12ed \u12ed\u12cd\u120b\u120d \u2500\u2500
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
                    msg = msg.replace("\U0001f64f", f" {user_name} \U0001f64f").replace("\U0001f970", f" {user_name} \U0001f970")
                result["reply"] = msg
            elif remaining_count <= 7:
                result["reply"] = random.choice(RESPONSES["booking_success_urgent"])
            else:
                msg = random.choice(RESPONSES["booking_success_normal"])
                if user_name and random.random() < 0.07:
                    msg = msg.replace("\U0001f64f", f" {user_name} \U0001f64f").replace("\U0001f970", f" {user_name} \U0001f970")
                result["reply"] = msg
        elif registration_result == "taken":
            result["reply"] = random.choice(RESPONSES["booking_taken"])
        return result

    # \u2500\u2500 intent \u12a8\u12cd\u132a \u12ab\u120d\u1218\u1323 \u1265\u127b TF-IDF detect_intent() \u1270\u1320\u1240\u121d \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent is None:
        intent, score = detect_intent(text)
        if score < THRESHOLD_CONFUSED:
            return result
        if score < THRESHOLD_RESPOND:
            return result
    # intent \u12a8\u12cd\u132a (Jina) \u12a8\u1218\u1323 threshold \u12f5\u130b\u121a \u12a0\u12ed\u1348\u1270\u123d\u121d \u2014
    # Jina's own JINA_MIN_SCORE already gated it in jina_brain.py

    # \u2500\u2500 payment_claim ("\u120d\u12ac\u12eb\u1208\u12cd"/"done"/"\u2705") \u2014 reply \u122b\u1231 bot.py \u12cd\u1235\u1325
    # handle_payment_claim() \u1270\u1320\u1245\u121e \u12ed\u1230\u122b\u120d (fingerprint lookup \u1235\u1208\u121a\u12eb\u1235\u1348\u120d\u130d)\u1363
    # \u1235\u1208\u12da\u1205 \u12a5\u12da\u1205 \u121d\u1295\u121d \u133d\u1201\u134d \u12a0\u1295\u1230\u1325\u121d\u1363 flag \u1265\u127b \u12a5\u1293\u1290\u1233\u1208\u1295
    if intent == "payment_claim":
        result["payment_claim"] = True
        return result

    # \u2500\u2500 balance_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "balance_query":
        bal = user_balance if user_balance is not None else (user_unpaid_balance or 0.0)
        if bal > 0:
            result["reply"] = random.choice(RESPONSES["balance_show"]).format(
                balance=int(bal)
            )
        else:
            result["reply"] = random.choice(RESPONSES["balance_zero"])
        return result

    # \u2500\u2500 shortfall_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

    # \u2500\u2500 winner_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "winner_query":
        if not recent_winners:
            result["reply"] = random.choice(RESPONSES["winner_none"])
            return result
        w = recent_winners
        def fmt_winner(w_item):
            return f"{w_item['user_name']} ({w_item['number']:02d})" if w_item.get("number") else w_item.get("user_name", "\u2014")
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
                second=fmt_winner(w[1]) if len(w) > 1 else "\u2014",
                third=fmt_winner(w[2]) if len(w) > 2 else "\u2014",
            )
        return result

    # \u2500\u2500 i_won_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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
                return f"{w_item['user_name']} ({w_item['number']:02d})" if w_item.get("number") else w_item.get("user_name", "\u2014")
            w = recent_winners
            result["reply"] = random.choice(RESPONSES["i_won_no"]).format(
                first=fmt_w(w[0]) if len(w) > 0 else "\u2014",
                second=fmt_w(w[1]) if len(w) > 1 else "\u2014",
                third=fmt_w(w[2]) if len(w) > 2 else "\u2014",
            )
        return result

    # \u2500\u2500 not_registered_complaint \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

    # \u2500\u2500 account_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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
                result["reply"] = f"\u12a0\u12ce \u1275\u12ad\u12ad\u120d \u1290\u12cd {best_match['bank']} account \u1290\u12cd \U0001f64f"
            elif best_match_type == "close":
                result["reply"] = f"\u1275\u1295\u123d \u1270\u1233\u1235\u1270\u1203\u120d\u1363 {best_match['bank']} account {best_match['account']} \u1290\u12cd \U0001f64f"
            else:
                result["reply"] = "\u12a5\u123a \u1208\u12a0\u132b\u12cb\u1279 \u1260\u12cd\u1235\u1325 \u120b\u12ad\u1208\u1275 \u1264\u1270\u1230\u1265 \U0001f64f"
        elif payment_info:
            result["reply"] = _extract_account_lines(payment_info)
        return result

    # \u2500\u2500 link_request \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "link_request":
        result["reply"] = random.choice(RESPONSES["link_request"])
        return result

    # \u2500\u2500 speed_request \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "speed_request":
        result["reply"] = random.choice(RESPONSES["speed_request"])
        return result

    # \u2500\u2500 my_numbers_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

    # \u2500\u2500 number_owner_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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
                    half_suffix = " (\u1260\u130d\u121b\u123d)" if is_half_owner else ""
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
                        lines.append(f"{num:02d} \u2014 \u12ad\u134d\u1275 \u1290\u12cd")
                    else:
                        slot1 = next((e for e in entry if e[2] == 1), entry[0])
                        owner_name = _first_name(slot1[0])
                        is_half_owner = slot1[1]
                        half_suffix = " (\u1260\u130d\u121b\u123d)" if is_half_owner else ""
                        if user_name and any(name == user_name for name, _, _, _, _ in entry):
                            lines.append(f"{num:02d} \u2014 \u12eb\u1295\u1270 \u1290\u12cd{half_suffix}")
                        else:
                            lines.append(f"{num:02d} \u2014 \u1208 {owner_name}{half_suffix}")
                owners_text = "\n".join(lines)
                result["reply"] = random.choice(RESPONSES["number_owner_multi"]).format(
                    owners_text=owners_text
                )
        return result

    # \u2500\u2500 claim_ownership \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "claim_ownership":
        numbers_found = re.findall(r"\d+", text)
        if numbers_found:
            num = int(numbers_found[0])
            entry = taken.get(num, [])
            if not entry:
                return result
            slot1 = next((e for e in entry if e[2] == 1), entry[0])
            is_half_owner = slot1[1]
            half_suffix = " (\u1260\u130d\u121b\u123d)" if is_half_owner else ""
            if user_name and any(name == user_name for name, _, _, _, _ in entry):
                result["reply"] = random.choice(RESPONSES["claim_ownership_yes"]) + half_suffix
            else:
                owner_name = _first_name(slot1[0])
                result["reply"] = random.choice(RESPONSES["claim_ownership_no"]).format(
                    name=owner_name
                )
        return result

    # \u2500\u2500 change_number \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

    # \u2500\u2500 type_change \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

    # \u2500\u2500 why_not_registered \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "why_not_registered":
        numbers_found = re.findall(r"\d+", text)
        target_num = int(numbers_found[0]) if numbers_found else None
        result["why_not_registered"] = {"number": target_num}
        return result

    # \u2500\u2500 booking \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "booking":
        if countdown_seconds > 0:
            mins = countdown_seconds // 60
            secs = countdown_seconds % 60
            if mins >= 1:
                result["reply"] = f"\u1272\u1295\u123d \u12ed\u1320\u1265\u1241 {mins} \u12f0\u1242\u1243 \u1240\u122d\u1271\u12cb\u120d \u12eb\u120d\u12a8\u1348\u1208 \u120a\u12c8\u1323 \U0001f64f"
            else:
                result["reply"] = f"{secs} \u1234\u12ae\u1295\u12f5 \u1240\u122d\u1271\u12cb\u120d \u1272\u1295\u123d \u12ed\u1320\u1265\u1241 \u1290\u1243\u12ed \u12ab\u1208 \u12a0\u1233\u12cd\u1243\u1208\u12cd \U0001f64f"
        return result

    # \u2500\u2500 specific_number_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

    # \u2500\u2500 cancel_number \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "cancel_number":
        numbers_found = re.findall(r"\d+", text)
        if numbers_found:
            num = int(numbers_found[0])
            result["reply"] = random.choice(RESPONSES["cancel_number_ack"])
            result["cancel_number"] = num
        return result

    # \u2500\u2500 complaint_removed \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

    # \u2500\u2500 complaint_why_sold \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "complaint_why_sold":
        result["reply"] = random.choice(RESPONSES["complaint_why_sold"])
        return result

    # \u2500\u2500 complaint_paid_removed \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "complaint_paid_removed":
        result["reply"] = random.choice(RESPONSES["complaint_paid_removed"])
        return result

    # \u2500\u2500 nekay_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

    # \u2500\u2500 remaining_send \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "remaining_send":
        result["reply"] = random.choice(RESPONSES["remaining_send_ack"])
        result["resend_remaining"] = True
        return result

    # \u2500\u2500 remaining_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "remaining_query":
        result["resend_remaining"] = True
        return result

    # \u2500\u2500 all_taken_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "all_taken_query":
        if remaining_count == 0 and not nekay_list:
            return result
        elif nekay_list:
            result["reply"] = random.choice(RESPONSES["all_taken_nekay"])
        else:
            result["resend_remaining"] = True
        return result

    # \u2500\u2500 price_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
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

    # \u2500\u2500 prize_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "prize_query":
        prize_1st = settings.get("prize_1st", 0)
        result["reply"] = random.choice(RESPONSES["prize_query"]).format(
            prize_1st=prize_1st
        )
        return result

    # \u2500\u2500 players_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "players_query":
        total_numbers = settings.get("total_numbers", 0)
        numbers_per_person = settings.get("numbers_per_person", 1)
        players_count = total_numbers // numbers_per_person if numbers_per_person else total_numbers
        result["reply"] = random.choice(RESPONSES["players_query"]).format(
            players_count=players_count
        )
        return result

    # \u2500\u2500 players_remaining_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "players_remaining_query":
        numbers_per_person = settings.get("numbers_per_person", 1)
        players_remaining = remaining_count // numbers_per_person if numbers_per_person else remaining_count
        result["reply"] = random.choice(RESPONSES["players_remaining_query"]).format(
            players_remaining=players_remaining
        )
        return result

    # \u2500\u2500 payment_not_received \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "payment_not_received":
        result["reply"] = random.choice(RESPONSES["payment_not_received"])
        return result

    # \u2500\u2500 result_query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    if intent == "result_query":
        total_numbers = settings.get("total_numbers", 0)
        paid_count = len(paid)
        nearly_done = (paid_count >= total_numbers - 3) or (countdown_seconds > 0)
        if nearly_done:
            result["reply"] = random.choice(RESPONSES["result_query_waiting"])
        elif recent_winners:
            w = recent_winners
            first  = f"{w[0]['number']:02d}" if len(w) > 0 and w[0].get("number") else "\u2014"
            second = f"{w[1]['number']:02d}" if len(w) > 1 and w[1].get("number") else "\u2014"
            third  = f"{w[2]['number']:02d}" if len(w) > 2 and w[2].get("number") else "\u2014"
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
# TF-IDF/Jina \u1201\u1208\u1271\u121d \u12ab\u120d\u1270\u1233\u12a9 \u1260\u128b\u120b \u12c8\u12f0 NVIDIA DeepSeek Flash \u12e8\u121a\u120b\u12a8\u12cd
# "game_data" \u1275\u1295\u123d \u1270\u12db\u121b\u1305 slice \u1265\u127b \u12a5\u1295\u12f2\u1206\u1295 (\u1219\u1209 game state \u1233\u12ed\u1206\u1295) \u12ed\u1205
# helper kwargs \u12cd\u1235\u1325 \u12ab\u1209\u1275 \u120b\u12ed \u1265\u127b \u1275\u1295\u123d dict \u12ed\u1308\u1290\u1263\u120d\u1362

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
# ASYNC WRAPPER \u2014 booking \u12ab\u120d\u1206\u1290 Jina \u2192 (latin \u12a8\u1206\u1290) TF-IDF retry \u2192
# AI fallback \u12e8\u121a\u120d \u1245\u12f0\u121d \u1270\u12a8\u1270\u120d \u12ed\u12a8\u1270\u120b\u120d
# ================================================================

async def _get_response_async_inner(text: str, **kwargs) -> dict:
    """
    get_response() async version:
      1. \u133d\u1201\u1349 \u130d\u120d\u1345 booking pattern \u12a8\u1206\u1290 (parser.parse_numbers \u2192
         is_clear_pattern=True) \u2192 intent detection \u1328\u122d\u1236 \u12a0\u12ed\u121e\u12a8\u122d\u121d\u1364
         \u1263\u12f6 result \u1270\u1218\u120d\u1236 bot.py \u122b\u1231 parse_numbers/process_registration
         flow \u12ed\u1228\u12a8\u1260\u12cb\u120d (\u120d\u12ad \u12ab\u1208\u1348\u12cd \u1263\u1205\u122a \u130b\u122d \u1270\u1218\u1233\u1233\u12ed)\u1362
      2. booking \u12ab\u120d\u1206\u1290 (\u12c8\u12ed\u121d ambiguous \u12a8\u1206\u1290) \u2192 Jina embedding \u1218\u1300\u1218\u122a\u12eb
         \u12ed\u121e\u12a8\u122b\u120d\u1362
           a) Jina \u1260\u122b\u1235 \u1218\u1270\u121b\u1218\u1295 intent \u1218\u120d\u1236 \u12a8\u1206\u1290 (\u2265 JINA_MIN_SCORE) \u2192
              \u12eb intent \u1325\u1245\u121d \u120b\u12ed \u12ed\u12cd\u120b\u120d\u1362
           b) Jina "unknown" \u1262\u1218\u120d\u1235 \u130d\u1295 \u122b\u1231 \u1230\u122d\u1276 \u12a8\u1206\u1290 (available=True) \u12a5\u1293
              \u133d\u1201\u1349 latin \u134a\u12f0\u120d \u12ab\u1208\u12cd (transliterated Amharic\u1363 Jina \u1260\u12da\u1205
              \u120b\u12ed \u12f0\u12ab\u121b \u1235\u1208\u1206\u1290) \u2192 TF-IDF \u1201\u1208\u1270\u129b \u1219\u12a8\u122b \u12eb\u12f0\u122d\u130b\u120d
              (TFIDF_LATIN_THRESHOLD\u1363 default 0.60)\u1362 \u12cd\u1324\u1271 threshold
              \u1260\u120b\u12ed \u12a8\u1206\u1290 TF-IDF intent \u1325\u1245\u121d \u120b\u12ed \u12ed\u12cd\u120b\u120d\u1362
           c) Jina \u122b\u1231 \u1328\u122d\u1236 \u120a\u1230\u122b \u12ab\u120d\u127b\u1208 (available=False \u2014 rate limit,
              API/network error) \u12c8\u12ed\u121d ready \u12ab\u120d\u1206\u1290 \u2192 TF-IDF \u1219\u1209 \u1241\u1325\u1325\u122d
              \u12ed\u12ed\u12db\u120d (legacy detect_intent() thresholds\u1363 0.40/0.12)
              \u12a5\u1295\u12f0 primary detector\u1362
      3. \u12a8\u120b\u12ed \u12eb\u1209\u1275 \u1201\u1209 \u12cd\u1324\u1275 \u12eb\u120b\u1218\u1321 \u12a8\u1206\u1290 (Jina unknown + latin \u12eb\u120d\u1206\u1290 \u12c8\u12ed\u121d
         latin retry \u12f0\u12ab\u121b \u12cd\u1324\u1275 \u12ab\u1218\u1323) \u2192 context-aware NVIDIA fallback
         (ai_fallback.get_ai_fallback) \u12e8\u1218\u1328\u1228\u123b \u12a0\u121b\u122b\u132d \u1206\u1296 \u12ed\u121e\u12a8\u122b\u120d\u1362

    \u1235\u12ac\u1273\u121b \u12cd\u1324\u1275 \u1263\u1308\u1298 \u1241\u1325\u122d (Jina/TF-IDF resolved \u12c8\u12ed\u121d AI fallback resolved)
    save_context() \u12ed\u1320\u122b\u120d\u1363 \u1235\u1208\u12da\u1205 \u1240\u1323\u12ed follow-up \u1325\u12eb\u1244 \u12ed\u1205\u1295 context \u12eb\u1308\u129b\u120d\u1362
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

    # \u2500\u2500 STEP 1: \u130d\u120d\u1345 booking pattern \u12a8\u1206\u1290 \u2192 intent detection skip \u2500\u2500
    price_full = float(settings.get("price_full") or 0)
    price_half = float(settings.get("price_half") or 0)
    try:
        parsed = parse_numbers(text, price_full=price_full, price_half=price_half)
    except Exception as e:
        logger.warning(f"[parse_numbers] Error: {e}")
        parsed = None

    if parsed and parsed.get("is_clear_pattern", True):
        return dict(empty_result)

    # \u2500\u2500 STEP 2: booking \u12ab\u120d\u1206\u1290 \u2192 Jina \u1218\u1300\u1218\u122a\u12eb \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    from jina_brain import jina_detect_intent, jina_is_ready

    if jina_is_ready():
        try:
            jina_intent, jina_score, jina_available = await jina_detect_intent(text)
        except Exception as e:
            logger.warning(f"[Jina] detect error: {e}")
            jina_intent, jina_score, jina_available = "unknown", 0.0, False

        # \u2705 2a: Jina \u1260\u122b\u1235 \u1218\u1270\u121b\u1218\u1295 intent \u1218\u120d\u1237\u120d \u2192 \u1270\u1320\u1240\u121d
        if jina_intent != "unknown":
            result = get_response(text=text, intent=jina_intent, score=jina_score, **kwargs)
            _save_context_safe(jina_intent, result.get("reply"))
            return result

        # \u26a0\ufe0f 2b: Jina \u1230\u122d\u1277\u120d \u130d\u1295 "unknown" \u1218\u1208\u1230 (\u12dd\u1245\u1270\u129b score) \u2014
        # latin \u133d\u1201\u134d \u12a8\u1206\u1290 TF-IDF \u1201\u1208\u1270\u129b \u1219\u12a8\u122b \u12eb\u12f5\u122d\u130d
        if jina_available and _has_latin_chars(text):
            tfidf_intent, tfidf_score = detect_intent(text)
            if tfidf_score >= TFIDF_LATIN_THRESHOLD:
                logger.info(
                    f"[Responder] \U0001f524 Latin retry via TF-IDF | text='{text[:40]}' | "
                    f"intent={tfidf_intent}({tfidf_score:.3f}) \u2265 {TFIDF_LATIN_THRESHOLD}"
                )
                result = get_response(text=text, intent=tfidf_intent, score=tfidf_score, **kwargs)
                _save_context_safe(tfidf_intent, result.get("reply"))
                return result

        # \u274c 2c: Jina \u122b\u1231 \u1219\u1209 \u1208\u1219\u1209 \u12c8\u12f5\u124b\u120d (rate limit/API/network error)
        # \u2192 TF-IDF \u1219\u1209 \u1241\u1325\u1325\u122d \u12ed\u12eb\u12dd (legacy thresholds \u1260\u122b\u1231 \u1260 get_response \u12cd\u1235\u1325)
        if not jina_available:
            logger.warning(
                f"[Responder] \U0001f6a8 Jina completely down \u2014 TF-IDF full control | text='{text[:40]}'"
            )
            tfidf_intent, tfidf_score = detect_intent(text)
            result = get_response(text=text, intent=tfidf_intent, score=tfidf_score, **kwargs)
            _save_context_safe(tfidf_intent, result.get("reply"))
            return result

        # \u2193 Jina available \u130d\u1295 (latin \u12a0\u12ed\u12f0\u1208\u121d \u12c8\u12ed\u121d TF-IDF \u12f0\u12ab\u121b) \u2192 STEP 3 (AI fallback)

    else:
        # Jina ready \u12ab\u120d\u1206\u1290 (init \u12a0\u120d\u1270\u1233\u12ab\u121d/keys \u12e8\u1209\u121d) \u2192 TF-IDF \u1219\u1209 \u1241\u1325\u1325\u122d
        logger.warning(f"[Responder] \U0001f6a8 Jina not ready \u2014 TF-IDF full control | text='{text[:40]}'")
        tfidf_intent, tfidf_score = detect_intent(text)
        result = get_response(text=text, intent=tfidf_intent, score=tfidf_score, **kwargs)
        _save_context_safe(tfidf_intent, result.get("reply"))
        return result

    # \u2500\u2500 STEP 3: Jina "unknown" (available, non-latin \u12c8\u12ed\u121d latin retry \u12f0\u12ab\u121b) \u2192 AI fallback (last resort) \u2500\u2500
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


async def get_response_async(text: str, **kwargs) -> dict:
    """
    Wrapper: (1) \u130d\u120d\u133d "\u120d\u12ac\u12eb\u1208\u12cd/\u120d\u12ad\u12eb\u1208\u12cd/\u2705" \u12ad\u134d\u12eb \u1218\u130d\u1208\u132b Jina \u12a8\u1218\u1320\u122b\u1271 \u1260\u134a\u1275 \u1260\u1240\u1325\u1273
    payment_claim \u12ed\u1206\u1293\u120d (\u12a8\u12da\u1205 \u1260\u134a\u1275 Jina "\u127c\u12ad \u12a0\u122d\u130d \u1263\u1208\u1264\u1271\u1295 \u12a0\u12cd\u122b\u12cd" \u12c8\u12f0\u121a\u120d \u1245\u122c\u1273
    \u1218\u120d\u1235 \u12ed\u12c8\u1235\u12f0\u12cd \u1290\u1260\u122d)\u1362 (2) emoji \u1265\u127b (\u2705 \u12e8\u120c\u1208\u12cd) message \u12ad\u134d\u12eb \u12a5\u1295\u12f0\u120b\u12a8 \u12a0\u12ed\u1246\u1320\u122d\u121d\u1362
    """
    if _is_explicit_payment_claim(text):
        return get_response(text=text, intent="payment_claim", score=1.0, **kwargs)

    result = await _get_response_async_inner(text, **kwargs)
    if result.get("payment_claim") and _is_emoji_only_not_check(text):
        result = dict(result)
        result["payment_claim"] = False
    return result
