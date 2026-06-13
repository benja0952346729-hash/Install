import re
import regex  # pip install regex — emoji support ለማስቻል

HALF_WORDS = ["begmash", "gmash", "ግማሽ", "በግማሽ", "g", "ግ", "begmas", "ግማ", "half"]
FULL_WORDS = ["bemulu", "mulu", "በሙሉ", "ሙሉ"]
GLOBAL_HALF_WORDS = ["ሁሉንም በግማሽ", "ሁሉንም ግማሽ", "ሁሉም በግማሽ", "hulunm begmash", "hulunm gmash"]
GLOBAL_FULL_WORDS = ["ሁሉንም በሙሉ", "ሁሉንም ሙሉ", "ሁሉም ሙሉ", "hulunm bemulu", "hulunm mulu"]

NON_NAME_WORDS = set([w.lower() for w in HALF_WORDS + FULL_WORDS + [
    "yaz", "yazligni", "ያዝ", "ፃፍ", "መዝግብ", "bel", "belaw", "በላቸው",
    "yaze", "yazat", "ble", "yibelachew", "yibelat",
    "awo", "aydelem", "yes", "no", "aha",
    "አለ", "ale", "ቢል", "bill", "ነው", "new",
    "ተያዘ", "teyaze", "ክፍት", "kift", "yeteYaze", "alteYaze",
    "ወይ", "wey", "እንደ", "neger", "ንገር",
    "ቁጥር", "qitr", "kutr", "cutr", "qutr", "qtr", "ktr", "number", "nbr", "num",
    "ያዝልኝ", "yazligni", "yazlgni", "yazlg",
    "ያዛት", "yazat", "ያዛቸው", "yazachew",
    "ፃፍልኝ", "tsafligni", "መዝግብልኝ", "mezgibligni",
    "እና", "ena", "and", "ና", "na",
    "በል", "ብለህ", "ብለሽ", "ብለው",
    "bel", "bleh", "blesh", "blew",
]])

NEBER_WORDS = {"ነበር", "ነበረ", "nebere", "neber"}


def _is_half_word(w):
    return w.lower() in [h.lower() for h in HALF_WORDS]

def _is_full_word(w):
    return w.lower() in [f.lower() for f in FULL_WORDS]


SEPARATOR_CHARS = set('+-/.,|*= \t\n')

def _is_symbol_name(s: str) -> bool:
    if len(s) < 2:
        return False
    return bool(re.match(r'^[^\w\s]{2,}$', s))


def _is_valid_name(s: str) -> bool:
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
        return True
    if _is_symbol_name(s):
        return True
    return len(s) >= 2


def _collect_name(tokens: list, start: int, skip_indices: set) -> tuple:
    parts = []
    i = start
    while i < len(tokens):
        if i in skip_indices:
            break
        tok = tokens[i].strip()
        if not tok:
            break
        if re.search(r'\d', tok):
            break
        if all(c in SEPARATOR_CHARS for c in tok):
            break
        tok_lower = tok.lower()
        if tok_lower in NEBER_WORDS:
            break
        if tok_lower in NON_NAME_WORDS:
            break
        if _is_half_word(tok) or _is_full_word(tok):
            break
        parts.append(tok)
        i += 1

    if not parts:
        return None, start - 1

    name = " ".join(parts)
    return name, i - 1


def _pre_tokenize(text: str) -> list:
    tokens = []
    text = re.sub(r'\bእና\b|\bና\b|\band\b', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'(?<!#)#(?!#)', ' ', text)
    text = re.sub(r'(\d+\+)(\d)', r'\1 \2', text)
    parts = re.sub(r'[,=/&?*]', ' ', text).split()

    for part in parts:
        if re.match(r'^[\d\+]+$', part):
            sub = _split_pure_numbers(part)
            tokens.extend(sub)
        else:
            sub = _split_mixed(part)
            tokens.extend(sub)

    return tokens


def _split_pure_numbers(s: str) -> list:
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


def _parse_token(tok: str):
    tok = tok.strip()
    if not tok or not re.search(r'\d', tok):
        return None

    is_half = False
    is_full = False
    name = None

    for hw in sorted(HALF_WORDS, key=len, reverse=True):
        m = re.match(r'^(\d+)\+?' + re.escape(hw) + r'(.*)$', tok, re.IGNORECASE)
        if m:
            is_half = True
            rest = m.group(2).strip()
            tok = m.group(1)
            if rest and rest.lower() not in NON_NAME_WORDS and rest.lower() not in NEBER_WORDS and _is_valid_name(rest):
                name = rest
            break
        m2 = re.match(r'^' + re.escape(hw) + r'(\d+)(.*)$', tok, re.IGNORECASE)
        if m2:
            is_half = True
            tok = m2.group(1)
            rest = m2.group(2).strip()
            if rest and rest.lower() not in NON_NAME_WORDS and rest.lower() not in NEBER_WORDS and _is_valid_name(rest):
                name = rest
            break

    if not is_half:
        for fw in sorted(FULL_WORDS, key=len, reverse=True):
            m = re.match(r'^(\d+)([^\d]*)' + re.escape(fw) + r'(.*)$', tok, re.IGNORECASE)
            if m:
                is_full = True
                name_part = m.group(2).strip()
                tok = m.group(1)
                if name_part and name_part.lower() not in NON_NAME_WORDS and name_part.lower() not in NEBER_WORDS and _is_valid_name(name_part):
                    name = name_part
                break

    if not is_half and not is_full and tok.endswith('+'):
        tok = tok[:-1]
        is_half = True

    if not is_half and not is_full:
        m = re.match(r'^(\d+)\+([^\d].+)$', tok)
        if m:
            is_half = True
            name_part = m.group(2).strip()
            if name_part.lower() not in NON_NAME_WORDS and name_part.lower() not in NEBER_WORDS and _is_valid_name(name_part):
                name = name_part
            tok = m.group(1)

    if name is None:
        m = re.match(r'^(\d+)([^\d\+].+)$', tok)
        if m:
            name_part = m.group(2).strip()
            for fw in sorted(FULL_WORDS, key=len, reverse=True):
                if fw.lower() in name_part.lower():
                    name_part = name_part.lower().replace(fw.lower(), '').strip()
                    is_full = True
                    break
            for hw in sorted(HALF_WORDS, key=len, reverse=True):
                if hw.lower() in name_part.lower():
                    name_part = name_part.lower().replace(hw.lower(), '').strip()
                    is_half = True
                    break
            if name_part and name_part.lower() not in NON_NAME_WORDS and name_part.lower() not in NEBER_WORDS and _is_valid_name(name_part):
                name = name_part
            tok = m.group(1)

    num_m = re.search(r'(\d+)', tok)
    if not num_m:
        return None

    num = int(num_m.group(1))
    num = max(1, num)
    return (num, is_half, is_full, name)


def _scan_for_half_full(tokens: list, start: int, skip_indices: set):
    """start index ጀምሮ remaining tokens ውስጥ half/full word ይፈልጋል"""
    j = start
    while j < len(tokens):
        if j in skip_indices:
            j += 1
            continue
        jtok = tokens[j].strip().lower()
        if jtok == '+':
            return "half", j
        elif _is_half_word(jtok):
            return "half", j
        elif _is_full_word(jtok):
            return "full", j
        elif jtok in NON_NAME_WORDS or jtok in NEBER_WORDS:
            j += 1
            continue
        else:
            break
        j += 1
    return None, -1


def parse_numbers(text: str):
    original = text.strip()

    stripped = original.rstrip()
    last_word = stripped.split()[-1].lower() if stripped.split() else ""
    if last_word in NEBER_WORDS:
        return None

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

        if i + 1 < len(tokens):
            nxt = tokens[i + 1].strip()
            if not re.search(r'\d', nxt):
                nxt_lower = nxt.lower()
                if nxt_lower == '+':
                    is_half = True
                    skip_indices.add(i + 1)
                    if name is None:
                        collected, last_idx = _collect_name(tokens, i + 2, skip_indices)
                        if collected and _is_valid_name(collected):
                            name = collected
                            for idx in range(i + 2, last_idx + 1):
                                skip_indices.add(idx)
                elif _is_half_word(nxt):
                    is_half = True
                    skip_indices.add(i + 1)
                    if name is None:
                        collected, last_idx = _collect_name(tokens, i + 2, skip_indices)
                        if collected and _is_valid_name(collected):
                            name = collected
                            for idx in range(i + 2, last_idx + 1):
                                skip_indices.add(idx)
                elif _is_full_word(nxt):
                    is_full = True
                    skip_indices.add(i + 1)
                elif nxt_lower not in NON_NAME_WORDS and nxt_lower not in NEBER_WORDS and name is None:
                    collected, last_idx = _collect_name(tokens, i + 1, skip_indices)
                    if collected and _is_valid_name(collected):
                        name = collected
                        for idx in range(i + 1, last_idx + 1):
                            skip_indices.add(idx)
                        # FIX: name collect ካደረገ በኋላ remaining tokens ውስጥ half/full ፈልግ
                        modifier, mod_idx = _scan_for_half_full(tokens, last_idx + 1, skip_indices)
                        if modifier == "half":
                            is_half = True
                            skip_indices.add(mod_idx)
                        elif modifier == "full":
                            is_full = True
                            skip_indices.add(mod_idx)

        numbers.append((num, is_half, is_full, name))
        i += 1

    if not numbers:
        return None

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


if __name__ == "__main__":
    tests = [
        ("11 አበበ ቢንያም በል",        [(11, False, "አበበ ቢንያም")]),
        ("21 ማርቆስ ሰለሞን",           [(21, False, "ማርቆስ ሰለሞን")]),
        ("41 stotto lemu",          [(41, False, "stotto lemu")]),
        ("41##",                    [(41, False, "##")]),
        ("41%%",                    [(41, False, "%%")]),
        ("11 አበበ ቢንያም ነበር",        None),
        ("11 ነበር",                  None),
        ("11 nebere",               None),
        ("11 አበበ 21 ሰለሞን",         [(11, False, "አበበ"), (21, False, "ሰለሞን")]),
        ("11+ አበበ",                 [(11, True,  "አበበ")]),
        ("11 ብለህ",                  [(11, False, None)]),
        ("12አበበ በሙሉ",               [(12, False, None)]),
        ("12አበበ begmash",           [(12, True,  None)]),
        ("11 አበበ በሙሉ",              [(11, False, None)]),
        ("11 አበበ ብለህ በሙሉ ያዝ",      [(11, False, None)]),
        # NEW FIXES
        ("11 አበበ begmash",          [(11, True,  "አበበ")]),
        ("11 አበበ ግማሽ",             [(11, True,  "አበበ")]),
        ("11 አበበ ግ",               [(11, True,  "አበበ")]),
        ("11 አበበ g",               [(11, True,  "አበበ")]),
        ("03 አበበ ብለህ በግማሽ ያዝ",    [(3,  True,  "አበበ")]),
        ("03 አበበ ብለህ begmash ያዝ",  [(3,  True,  "አበበ")]),
        ("01 አበበ +",               [(1,  True,  "አበበ")]),
        ("05 ሰለሞን +",              [(5,  True,  "ሰለሞን")]),
    ]

    print("=" * 50)
    for text, expected in tests:
        result = parse_numbers(text)
        nums = result["numbers"] if result else None
        ok = "✅" if nums == expected else "❌"
        print(f"{ok} '{text}'")
        if nums != expected:
            print(f"   expected: {expected}")
            print(f"   got:      {nums}")
    print("=" * 50)
