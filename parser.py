import re
import regex  # pip install regex — emoji support ለማስቻል

HALF_WORDS = ["begmash", "gmash", "ግማሽ", "በግማሽ", "g", "ግ"]
FULL_WORDS = ["bemulu", "mulu", "በሙሉ", "ሙሉ"]
GLOBAL_HALF_WORDS = ["ሁሉንም በግማሽ", "ሁሉንም ግማሽ", "ሁሉም በግማሽ", "hulunm begmash", "hulunm gmash"]
GLOBAL_FULL_WORDS = ["ሁሉንም በሙሉ", "ሁሉንም ሙሉ", "ሁሉም ሙሉ", "hulunm bemulu", "hulunm mulu"]

# ለውጥ 5 — NON_NAME_WORDS Fix
NON_NAME_WORDS = set([w.lower() for w in HALF_WORDS + FULL_WORDS + [
    "yaz", "yazligni", "ያዝ", "ፃፍ", "መዝግብ", "bel", "belaw", "በላቸው",
    "yaze", "yazat", "ble", "yibelachew", "yibelat",
    "awo", "aydelem", "yes", "no", "aha",
    # ቁጥር query words — ስም አይደሉም
    "አለ", "ale", "ቢል", "bill", "ነው", "new",
    "ተያዘ", "teyaze", "ክፍት", "kift", "yeteYaze", "alteYaze",
    "ወይ", "wey", "እንደ", "neger", "ንገር",
    "ቁጥር", "qitr", "kutr", "cutr", "qutr", "qtr", "ktr", "number", "nbr", "num",
    # ← ለውጥ 5: እነዚህ ተጨምረዋል
    "ያዝልኝ", "yazligni", "yazlgni", "yazlg",
    "ያዛት", "yazat",
    "ያዛቸው", "yazachew",
    "ፃፍልኝ", "tsafligni",
    "መዝግብልኝ", "mezgibligni",
    # separators — ስም እንዳይሆኑ
    "እና", "ena", "and", "ና", "na",
]])

def _is_half_word(w):
    return w.lower() in [h.lower() for h in HALF_WORDS]

def _is_full_word(w):
    return w.lower() in [f.lower() for f in FULL_WORDS]


# ================================================================
# ለውጥ 6 — _is_valid_name() helper
# ================================================================
def _is_valid_name(s: str) -> bool:
    """
    ስም valid ነው ወይ?
    - Emoji: 1+ ✅
    - ሌሎች: 2+ chars ✅
    """
    if not s:
        return False
    emoji_pattern = regex.compile(
        r'[\U0001F300-\U0001F9FF'
        r'\U00002600-\U000027BF'
        r'\U0001FA00-\U0001FA9F'
        r'\U00002700-\U000027BF'
        r'\U0001F000-\U0001F02F]+',
        regex.UNICODE
    )
    if emoji_pattern.search(s):
        return True  # emoji ካለ — length ሳይታይ ✅
    return len(s) >= 2  # Regular chars — 2+ ብቻ


# ================================================================
# PRE-TOKENIZER
# ================================================================

def _pre_tokenize(text: str) -> list:
    """
    Text → list of raw tokens.
    Concatenated ቁጥሮች ይሰበራሉ።
    """
    tokens = []

    # ለውጥ 7 — Separator Fix
    # Step 1: word separators (እና, and, ና) ወደ space
    text = re.sub(r'\bእና\b|\bና\b|\band\b', ' ', text, flags=re.IGNORECASE)
    # Step 2: symbol separators
    parts = re.sub(r'[,=/%&#?]', ' ', text).split()

    for part in parts:
        # Pure digits only (no letters) — try split into 2-digit chunks
        if re.match(r'^[\d\+]+$', part):
            sub = _split_pure_numbers(part)
            tokens.extend(sub)
        else:
            # Mixed (digits + letters) — split at digit→letter boundaries
            sub = _split_mixed(part)
            tokens.extend(sub)

    return tokens


def _split_pure_numbers(s: str) -> list:
    """
    Pure digit string (with optional +) → 2-digit chunks
    "1121"  → ["11","21"]
    "151"   → ["01","51"]
    "0121"  → ["01","21"]
    "11+51" → ["11+","51"]
    "11+51+"→ ["11+","51+"]
    """
    segments = []
    cur = ""
    for ch in s:
        if ch == '+':
            segments.append((cur, True))
            cur = ""
        else:
            cur += ch
    if cur:
        segments.append((cur, False))

    result = []
    for digits, has_plus in segments:
        if not digits:
            continue
        chunks = _chunk_digits(digits)
        for j, chunk in enumerate(chunks):
            is_last = (j == len(chunks) - 1)
            result.append(chunk + ('+' if (has_plus and is_last) else ''))

    return result if result else [s]


def _chunk_digits(digits: str) -> list:
    """
    Digits string → 2-digit chunks (single leading digit gets 0-padded)
    """
    if len(digits) <= 2:
        if len(digits) == 1:
            return [f"0{digits}"]
        return [digits]

    chunks = []
    i = 0
    if len(digits) % 2 == 1:
        chunks.append(f"0{digits[0]}")
        i = 1
    while i < len(digits):
        chunks.append(digits[i:i+2])
        i += 2
    return chunks


def _split_mixed(s: str) -> list:
    """
    Mixed string → split where digits end and non-digits begin or vice versa
    "21አበበ31ayele41+selemon" → ["21አበበ","31ayele","41+selemon"]
    """
    result = []
    current = ""

    i = 0
    while i < len(s):
        ch = s[i]
        if ch.isdigit() and current and not current[-1].isdigit() and current[-1] != '+':
            result.append(current)
            current = ch
        else:
            current += ch
        i += 1

    if current:
        result.append(current)

    return result if result else [s]


# ================================================================
# PARSE SINGLE TOKEN → (num, is_half, is_full, name)
# ================================================================

def _parse_token(tok: str):
    tok = tok.strip()
    if not tok or not re.search(r'\d', tok):
        return None

    is_half = False
    is_full = False
    name = None

    # attached half word: 11gmash, 41ግ
    for hw in sorted(HALF_WORDS, key=len, reverse=True):
        m = re.match(r'^(\d+)\+?' + re.escape(hw) + r'(.*)$', tok, re.IGNORECASE)
        if m:
            is_half = True
            rest = m.group(2).strip()
            tok = m.group(1)
            # ለውጥ 6: _is_valid_name() check ተጨምሯል
            if rest and rest.lower() not in NON_NAME_WORDS and _is_valid_name(rest):
                name = rest
            break
        m2 = re.match(r'^' + re.escape(hw) + r'(\d+)(.*)$', tok, re.IGNORECASE)
        if m2:
            is_half = True
            tok = m2.group(1)
            rest = m2.group(2).strip()
            if rest and rest.lower() not in NON_NAME_WORDS and _is_valid_name(rest):
                name = rest
            break

    # attached full word
    if not is_half:
        for fw in sorted(FULL_WORDS, key=len, reverse=True):
            m = re.match(r'^(\d+)' + re.escape(fw) + r'(.*)$', tok, re.IGNORECASE)
            if m:
                is_full = True
                rest = m.group(2).strip()
                tok = m.group(1)
                if rest and rest.lower() not in NON_NAME_WORDS and _is_valid_name(rest):
                    name = rest
                break

    # trailing +
    if not is_half and not is_full and tok.endswith('+'):
        tok = tok[:-1]
        is_half = True

    # number + + + name: "11+ayele", "41+selemon"
    if not is_half and not is_full:
        m = re.match(r'^(\d+)\+([^\d].+)$', tok)
        if m:
            is_half = True
            name_part = m.group(2).strip()
            if name_part.lower() not in NON_NAME_WORDS and _is_valid_name(name_part):
                name = name_part
            tok = m.group(1)

    # number + attached name: "21አበበ", "21selemon"
    if name is None:
        m = re.match(r'^(\d+)([^\d\+].+)$', tok)
        if m:
            name_part = m.group(2).strip()
            if name_part.lower() not in NON_NAME_WORDS and _is_valid_name(name_part):
                name = name_part
            tok = m.group(1)

    num_m = re.search(r'(\d+)', tok)
    if not num_m:
        return None

    num = int(num_m.group(1))
    num = max(1, num)
    return (num, is_half, is_full, name)


# ================================================================
# MAIN
# ================================================================

def parse_numbers(text: str):
    original = text.strip()

    is_global_full = any(w in original for w in GLOBAL_FULL_WORDS)
    is_global_half = any(w in original for w in GLOBAL_HALF_WORDS)

    tokens = _pre_tokenize(original)

    numbers = []
    skip_indices = set()

    i = 0
    while i < len(tokens):
        if i in skip_indices:
            i += 1
            continue

        tok = tokens[i]

        if not re.search(r'\d', tok):
            i += 1
            continue

        parsed = _parse_token(tok)
        if not parsed:
            i += 1
            continue

        num, is_half, is_full, name = parsed

        # next token: modifier or name
        if i + 1 < len(tokens):
            nxt = tokens[i + 1].strip()
            if not re.search(r'\d', nxt):
                nxt_lower = nxt.lower()
                if _is_half_word(nxt):
                    is_half = True
                    skip_indices.add(i + 1)
                    if i + 2 < len(tokens):
                        nxt2 = tokens[i + 2].strip()
                        if not re.search(r'\d', nxt2) and nxt2.lower() not in NON_NAME_WORDS and _is_valid_name(nxt2):
                            name = nxt2
                            skip_indices.add(i + 2)
                elif _is_full_word(nxt):
                    is_full = True
                    skip_indices.add(i + 1)
                    if i + 2 < len(tokens):
                        nxt2 = tokens[i + 2].strip()
                        if not re.search(r'\d', nxt2) and nxt2.lower() not in NON_NAME_WORDS and _is_valid_name(nxt2):
                            name = nxt2
                            skip_indices.add(i + 2)
                elif nxt_lower not in NON_NAME_WORDS and name is None and _is_valid_name(nxt):
                    name = nxt
                    skip_indices.add(i + 1)

        numbers.append((num, is_half, is_full, name))
        i += 1

    if not numbers:
        return None

    # ================================================================
    # QUERY GUARD
    # ================================================================
    QUERY_WORDS = [
        "አለ", "ale", "ቢል", "bill", "ነው", "yaze", "ተያዘ",
        "ክፍት", "kift", "ወይ", "wey", "teyaze", "new",
        "ቁጥር", "qitr", "kutr", "cutr", "qutr", "qtr", "ktr", "number", "nbr", "num",
    ]
    if len(numbers) == 1:
        _, _, _, nm = numbers[0]
        has_query = any(w.lower() in [t.lower() for t in tokens] for w in QUERY_WORDS)
        if has_query and nm is None:
            return None

    # trailing global full word
    last_tok = tokens[-1].strip().lower() if tokens else ""
    if not re.search(r'\d', last_tok) and any(last_tok == fw.lower() for fw in ["bemulu", "mulu", "ሙሉ", "በሙሉ"]):
        is_global_full = True

    result = []
    for num, is_half, is_full, name in numbers:
        if is_global_full:
            is_half = False
        elif is_global_half:
            is_half = True
        if is_full:
            is_half = False
        result.append((num, is_half, name))

    # ambiguous check
    ambiguous = None
    ambiguous_number = None

    if not is_global_half and not is_global_full and len(result) > 1:
        last_num, last_half, last_name = result[-1]
        others_half = any(h for n, h, nm in result[:-1])

        if last_half and not others_half:
            orig_end = original.rstrip()
            if orig_end.endswith('+'):
                ambiguous = "all_half"
                ambiguous_number = last_num
            else:
                last_token = tokens[-1] if tokens else ""
                for hw in ["gmash", "begmash", "ግ", "g"]:
                    if re.match(r'^\d+' + re.escape(hw) + r'$', last_token, re.IGNORECASE):
                        ambiguous = "last_half"
                        ambiguous_number = last_num
                        break

    return {
        "numbers": result,
        "ambiguous": ambiguous,
        "ambiguous_number": ambiguous_number
    }


def format_number(n: int) -> str:
    return f"{n:02d}"
