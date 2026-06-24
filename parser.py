import re
import difflib

HALF_WORDS = ["begmash", "gmash", "ግማሽ", "በግማሽ", "g", "ግ", "begmas", "ግማ", "half"]
FULL_WORDS = ["bemulu", "mulu", "በሙሉ", "ሙሉ"]
GLOBAL_HALF_WORDS = ["ሁሉንም በግማሽ", "ሁሉንም ግማሽ", "ሁሉም በግማሽ", "hulunm begmash", "hulunm gmash"]
GLOBAL_FULL_WORDS = ["ሁሉንም በሙሉ", "ሁሉንም ሙሉ", "ሁሉም ሙሉ", "hulunm bemulu", "hulunm mulu"]

PRICE_PREFIX_WORDS = ["በ", "be", "bet", "b"]

NON_NAME_WORDS = set([w.lower() for w in HALF_WORDS + FULL_WORDS + PRICE_PREFIX_WORDS + [
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
    "አርግ", "አርገው", "አድርግ", "አድርገው",
    "arig", "arigew", "argew", "adrg", "adrgew", "adrig", "adrigew",
    "yihun", "ይሁን", "ble", "ብለ",
    "say", "bil", "ብልህ", "blih",
]])

NEBER_WORDS = {"ነበር", "ነበረ", "nebere", "neber"}

# ── booking helper words — clear booking context ──────────────
BOOKING_HELPER_WORDS = {
    "ያዝ", "yaz", "ፃፍ", "tsaf", "መዝግብ", "mezgib",
    "ቢል", "bil", "በል", "bel", "say",
    "ያዛት", "yazat", "ያዛቸው", "yazachew",
    "ያዝልኝ", "yazligni",
    "ፃፍልኝ", "tsafligni",
    "ወንድሜ", "wendme", "ቤተሰብ", "beteseb",
    "አርግ", "arig", "አድርግ", "adrig",
    "ብለህ", "bleh", "ብለሽ", "blesh", "ብለ", "ble",
    "ወዳጄ", "wodaje",
}

# ── query words — number query አይደለም booking ──────────────────
QUERY_WORDS_SET = {
    "የማነው", "ለማን", "ተያዘ", "teyaze", "አለ ወይ",
    "yemanehu", "leman",
}

FUZZY_THRESHOLD = 70
FUZZY_MIN_LEN = 3


def _fuzzy_ratio(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio() * 100

def _fuzzy_match(token, candidates):
    tok_lower = token.lower()
    for cand in candidates:
        if tok_lower == cand.lower():
            return True
    if len(tok_lower) < FUZZY_MIN_LEN:
        return False
    for cand in candidates:
        if len(cand.lower()) < FUZZY_MIN_LEN:
            continue
        if _fuzzy_ratio(tok_lower, cand.lower()) >= FUZZY_THRESHOLD:
            return True
    return False

def _is_half_word(w): return _fuzzy_match(w, HALF_WORDS)
def _is_full_word(w): return _fuzzy_match(w, FULL_WORDS)
def _is_non_name_word(w): return _fuzzy_match(w, NON_NAME_WORDS)
def _is_price_prefix(w): return w.lower() in PRICE_PREFIX_WORDS
def _is_booking_helper(w): return w.strip().lower() in BOOKING_HELPER_WORDS

SEPARATOR_CHARS = set('+-/.,|*= \t\n')

def _is_symbol_name(s):
    if len(s) < 2: return False
    return bool(re.match(r'^[^\w\s]{2,}$', s))

def _is_valid_name(s):
    if not s: return False
    emoji_pattern = re.compile(
        r'[\U0001F300-\U0001F9FF\U00002600-\U000027BF'
        r'\U0001FA00-\U0001FA9F\U00002700-\U000027BF\U0001F000-\U0001F02F]+',
        re.UNICODE)
    if emoji_pattern.search(s): return True
    if _is_symbol_name(s): return True
    return len(s) >= 2

def _collect_name(tokens, start, skip_indices):
    parts = []
    i = start
    while i < len(tokens):
        if i in skip_indices: break
        tok = tokens[i].strip()
        if not tok: break
        if re.search(r'\d', tok): break
        if all(c in SEPARATOR_CHARS for c in tok): break
        tok_lower = tok.lower()
        if tok_lower in NEBER_WORDS: break
        if _is_half_word(tok) or _is_full_word(tok): break
        # booking helpers skip (don't add to name, don't stop)
        if _is_booking_helper(tok_lower):
            i += 1; continue
        if _is_non_name_word(tok): break
        parts.append(tok)
        i += 1
    if not parts: return None, start - 1
    return " ".join(parts), i - 1

def _pre_tokenize(text):
    text = re.sub(r'\bእና\b|\bና\b|\band\b', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'(?<!#)#(?!#)', ' ', text)
    text = re.sub(r'(\d+\+)(\d)', r'\1 \2', text)
    parts = re.sub(r'[,./&?*%]', ' ', text).split()
    tokens = []
    for part in parts:
        if re.match(r'^\d+=\d+$', part):
            left, right = part.split('=', 1)
            tokens.extend(_split_pure_numbers(left))
            tokens.append(f"__PRICE__{right}")
            continue
        if re.match(r'^[\d\+]+$', part):
            tokens.extend(_split_pure_numbers(part))
        else:
            m = re.match(r'^(be|bet|በ|b)(\d+)$', part, re.IGNORECASE)
            if m:
                tokens.append(f"__PRICE_PREFIX__{m.group(2)}")
                continue
            tokens.extend(_split_mixed(part))
    return tokens

def _split_pure_numbers(s):
    segments = []
    cur = ""
    for ch in s:
        if ch == '+':
            segments.append((cur, True)); cur = ""
        else:
            cur += ch
    if cur: segments.append((cur, False))
    result = []
    for digits, has_plus in segments:
        if not digits: continue
        chunks = _chunk_digits(digits)
        for j, chunk in enumerate(chunks):
            result.append(chunk + ('+' if (has_plus and j == len(chunks)-1) else ''))
    return result if result else [s]

def _chunk_digits(digits):
    if len(digits) <= 2:
        return [f"0{digits}" if len(digits) == 1 else digits]
    chunks = []
    i = 0
    if len(digits) % 2 == 1:
        chunks.append(f"0{digits[0]}"); i = 1
    while i < len(digits):
        chunks.append(digits[i:i+2]); i += 2
    return chunks

def _split_mixed(s):
    result = []; current = ""
    for ch in s:
        if ch.isdigit() and current and not current[-1].isdigit() and current[-1] != '+':
            result.append(current); current = ch
        else:
            current += ch
    if current: result.append(current)
    return result if result else [s]

def _parse_token(tok):
    tok = tok.strip()
    if not tok or not re.search(r'\d', tok): return None
    is_half = is_full = False; name = None

    for hw in sorted(HALF_WORDS, key=len, reverse=True):
        m = re.match(r'^(\d+)\+?' + re.escape(hw) + r'(.*)$', tok, re.IGNORECASE)
        if m:
            is_half = True; rest = m.group(2).strip(); tok = m.group(1)
            if rest and not _is_non_name_word(rest) and rest.lower() not in NEBER_WORDS and _is_valid_name(rest):
                name = rest
            break
        m2 = re.match(r'^' + re.escape(hw) + r'(\d+)(.*)$', tok, re.IGNORECASE)
        if m2:
            is_half = True; tok = m2.group(1); rest = m2.group(2).strip()
            if rest and not _is_non_name_word(rest) and rest.lower() not in NEBER_WORDS and _is_valid_name(rest):
                name = rest
            break

    if not is_half:
        for fw in sorted(FULL_WORDS, key=len, reverse=True):
            m = re.match(r'^(\d+)([^\d]*)' + re.escape(fw) + r'(.*)$', tok, re.IGNORECASE)
            if m:
                is_full = True; name_part = m.group(2).strip(); tok = m.group(1)
                if name_part and not _is_non_name_word(name_part) and name_part.lower() not in NEBER_WORDS and _is_valid_name(name_part):
                    name = name_part
                break

    if not is_half and not is_full and tok.endswith('+'):
        tok = tok[:-1]; is_half = True

    if not is_half and not is_full:
        m = re.match(r'^(\d+)\+([^\d].+)$', tok)
        if m:
            is_half = True; name_part = m.group(2).strip()
            if not _is_non_name_word(name_part) and name_part.lower() not in NEBER_WORDS and _is_valid_name(name_part):
                name = name_part
            tok = m.group(1)

    if name is None:
        m = re.match(r'^(\d+)([^\d\+].+)$', tok)
        if m:
            name_part = m.group(2).strip()
            for fw in sorted(FULL_WORDS, key=len, reverse=True):
                if fw.lower() in name_part.lower():
                    name_part = name_part.lower().replace(fw.lower(), '').strip(); is_full = True; break
            for hw in sorted(HALF_WORDS, key=len, reverse=True):
                if hw.lower() in name_part.lower():
                    name_part = name_part.lower().replace(hw.lower(), '').strip(); is_half = True; break
            if name_part and not _is_non_name_word(name_part) and name_part.lower() not in NEBER_WORDS and _is_valid_name(name_part):
                name = name_part
            tok = m.group(1)

    num_m = re.search(r'(\d+)', tok)
    if not num_m: return None
    return (max(1, int(num_m.group(1))), is_half, is_full, name)

def _scan_for_half_full(tokens, start, skip_indices):
    j = start
    while j < len(tokens):
        if j in skip_indices: j += 1; continue
        jtok = tokens[j].strip().lower()
        if jtok == '+': return "half", j
        elif _is_half_word(jtok): return "half", j
        elif _is_full_word(jtok): return "full", j
        elif _is_non_name_word(jtok) or jtok in NEBER_WORDS: j += 1; continue
        else: break
        j += 1
    return None, -1

def _resolve_price_type(amount, price_full, price_half):
    if price_half and price_half > 0:
        return "half" if abs(amount - price_half) <= abs(amount - price_full) else "full"
    return "full"


# ================================================================
# IS CLEAR PATTERN
# ================================================================

def _is_clear_booking_pattern(original, numbers, is_global_half, is_global_full, tokens):
    """
    True  → directly book (AI አያስፈልግም)
    False → AI ይጠራ
    """
    latin_orig = original.lower()

    # ── query words ካሉ → always AI ──────────────────────────────
    for qw in QUERY_WORDS_SET:
        if qw in latin_orig:
            return False

    # ── global half/full + ቁጥሮች ብቻ → clear ──────────────────────
    if is_global_half or is_global_full:
        return True

    # ── 2+ ቃል ስም ካለ → AI ──────────────────────────────────────
    for _, _, name in numbers:
        if name and len(name.split()) >= 2:
            return False

    # ── half/full word ካለ → ቀሪው booking context ነው → clear ──
    has_type_word = any(
        _is_half_word(t.strip()) or _is_full_word(t.strip())
        for t in tokens
        if not t.startswith("__") and not re.search(r'\d', t)
    )
    if has_type_word:
        return True

    # ── extra unknown words ይፈትሽ ──────────────────────────────
    name_parts = set()
    for _, _, name in numbers:
        if name:
            for w in name.lower().split():
                name_parts.add(w)

    for tok in tokens:
        if tok.startswith("__"): continue
        if re.search(r'\d', tok): continue
        t = tok.strip().lower()
        if not t or t in ('+', '-', '/'): continue
        if t in NEBER_WORDS: continue
        if _is_half_word(t) or _is_full_word(t): continue
        if _is_booking_helper(t): continue
        if _is_non_name_word(t): continue
        if t in name_parts: continue
        # unknown word → AI
        return False

    return True


# ================================================================
# MAIN
# ================================================================

def parse_numbers(text, price_full=None, price_half=None):
    original = text.strip()

    last_word = original.rstrip().split()[-1].lower() if original.rstrip().split() else ""
    if last_word in NEBER_WORDS:
        return None

    is_global_full = any(w in original for w in GLOBAL_FULL_WORDS)
    is_global_half = any(w in original for w in GLOBAL_HALF_WORDS)

    tokens = _pre_tokenize(original)
    numbers = []
    skip_indices = set()

    global_price_amount = None
    for idx, tok in enumerate(tokens):
        if tok.startswith("__PRICE_PREFIX__"):
            try:
                global_price_amount = float(tok.replace("__PRICE_PREFIX__", ""))
                skip_indices.add(idx)
            except ValueError:
                pass

    i = 0
    while i < len(tokens):
        if i in skip_indices: i += 1; continue
        tok = tokens[i]
        if tok.startswith("__PRICE__"): i += 1; continue

        if not re.search(r'\d', tok):
            tok_lower = tok.strip().lower()
            if _is_price_prefix(tok_lower) and i + 1 < len(tokens):
                nxt = tokens[i + 1]
                if re.match(r'^\d+$', nxt.strip()):
                    try:
                        global_price_amount = float(nxt.strip())
                        skip_indices.add(i); skip_indices.add(i + 1)
                    except ValueError:
                        pass
            i += 1; continue

        parsed = _parse_token(tok)
        if not parsed: i += 1; continue

        num, is_half, is_full, name = parsed
        name_from_token = name is not None

        inline_price = None
        if i + 1 < len(tokens) and tokens[i + 1].startswith("__PRICE__"):
            try:
                inline_price = float(tokens[i + 1].replace("__PRICE__", ""))
                skip_indices.add(i + 1)
            except ValueError:
                pass

        if inline_price is not None and price_full:
            ptype = _resolve_price_type(inline_price, price_full or 0, price_half or 0)
            is_half = (ptype == "half"); is_full = not is_half
        elif i + 1 < len(tokens):
            nxt = tokens[i + 1].strip()
            if not re.search(r'\d', nxt):
                nxt_lower = nxt.lower()
                if nxt_lower == '+':
                    is_half = True; skip_indices.add(i + 1)
                    if name is None:
                        collected, last_idx = _collect_name(tokens, i + 2, skip_indices)
                        if collected and _is_valid_name(collected):
                            name = collected
                            for idx in range(i + 2, last_idx + 1): skip_indices.add(idx)
                elif _is_half_word(nxt):
                    is_half = True; skip_indices.add(i + 1)
                    if name is None:
                        collected, last_idx = _collect_name(tokens, i + 2, skip_indices)
                        if collected and _is_valid_name(collected):
                            name = collected
                            for idx in range(i + 2, last_idx + 1): skip_indices.add(idx)
                    elif name_from_token:
                        name = None
                elif _is_full_word(nxt):
                    is_full = True; skip_indices.add(i + 1)
                    if name_from_token: name = None
                elif _is_price_prefix(nxt_lower) and i + 2 < len(tokens):
                    price_tok = tokens[i + 2].strip()
                    if re.match(r'^\d+$', price_tok):
                        try:
                            ip2 = float(price_tok)
                            skip_indices.add(i + 1); skip_indices.add(i + 2)
                            if price_full:
                                ptype = _resolve_price_type(ip2, price_full or 0, price_half or 0)
                                is_half = (ptype == "half"); is_full = not is_half
                        except ValueError:
                            pass
                elif _is_booking_helper(nxt_lower) and name is None:
                    # booking helper ስለሆነ skip አርጎ ቀጣዩን ስም ያስብስባል
                    skip_indices.add(i + 1)
                    if i + 2 < len(tokens):
                        collected, last_idx = _collect_name(tokens, i + 2, skip_indices)
                        if collected and _is_valid_name(collected):
                            name = collected
                            for idx in range(i + 2, last_idx + 1): skip_indices.add(idx)
                elif not _is_non_name_word(nxt_lower) and nxt_lower not in NEBER_WORDS and name is None:
                    collected, last_idx = _collect_name(tokens, i + 1, skip_indices)
                    if collected and _is_valid_name(collected):
                        name = collected
                        for idx in range(i + 1, last_idx + 1): skip_indices.add(idx)
                        modifier, mod_idx = _scan_for_half_full(tokens, last_idx + 1, skip_indices)
                        if modifier == "half":
                            is_half = True; skip_indices.add(mod_idx)
                        elif modifier == "full":
                            is_full = True; skip_indices.add(mod_idx); name = None

        numbers.append((num, is_half, is_full, name))
        i += 1

    if not numbers:
        return None

    QUERY_WORDS = [
        "አለ", "ale", "ነው", "yaze", "ተያዘ",
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

    if global_price_amount is not None and price_full:
        ptype = _resolve_price_type(global_price_amount, price_full or 0, price_half or 0)
        is_global_half = (ptype == "half"); is_global_full = not is_global_half

    result = []
    for num, is_half, is_full, name in numbers:
        if is_global_full: is_half = False
        elif is_global_half: is_half = True
        if is_full: is_half = False
        result.append((num, is_half, name))

    all_named = [(i, nm) for i, (_, _, nm) in enumerate(result) if nm]
    if len(all_named) == 1:
        only_idx, only_name = all_named[0]
        if only_idx == len(result) - 1:
            result = [(n, h, only_name) for n, h, _ in result]

    ambiguous = None; ambiguous_number = None
    if not is_global_half and not is_global_full and len(result) > 1:
        last_num, last_half, last_name = result[-1]
        others_half = any(h for n, h, nm in result[:-1])
        if last_half and not others_half:
            orig_end = original.rstrip()
            if orig_end.endswith('+'):
                ambiguous = "all_half"; ambiguous_number = last_num
            else:
                last_token = tokens[-1] if tokens else ""
                for hw in ["gmash", "begmash", "ግ", "g"]:
                    if re.match(r'^\d+' + re.escape(hw) + r'$', last_token, re.IGNORECASE):
                        ambiguous = "last_half"; ambiguous_number = last_num; break

    # ── IS CLEAR PATTERN ─────────────────────────────────────────
    is_clear = _is_clear_booking_pattern(
        original=original,
        numbers=result,
        is_global_half=is_global_half,
        is_global_full=is_global_full,
        tokens=tokens,
    )

    return {
        "numbers": result,
        "ambiguous": ambiguous,
        "ambiguous_number": ambiguous_number,
        "is_clear_pattern": is_clear,
    }


def format_number(n): return f"{n:02d}"


if __name__ == "__main__":
    tests = [
        # ── CLEAR ✅ ──
        ("11",                              True,  [(11, False, None)]),
        ("11+",                             True,  [(11, True,  None)]),
        ("11 21 31",                        True,  [(11, False, None), (21, False, None), (31, False, None)]),
        ("11 በግማሽ",                       True,  [(11, True,  None)]),
        ("11 በሙሉ",                         True,  [(11, False, None)]),
        ("11 አበበ",                          True,  [(11, False, "አበበ")]),
        ("ሁሉንም በሙሉ 11 21",                True,  [(11, False, None), (21, False, None)]),
        ("11/21/31",                        True,  [(11, False, None), (21, False, None), (31, False, None)]),
        ("11 21 31 ቢል",                    True,  [(11, False, None), (21, False, None), (31, False, None)]),
        ("11 ያዝ",                           True,  [(11, False, None)]),
        ("11+ አበበ",                         True,  [(11, True,  "አበበ")]),
        ("11 አበበ begmash",                  True,  [(11, True,  "አበበ")]),
        ("11 በሙሉ አበበ ብለህ ያዝ",             True,  [(11, False, None)]),
        ("11 21 31 ቢል",                    True,  [(11, False, None), (21, False, None), (31, False, None)]),
        ("11 say አበበ",                     True,  [(11, False, "አበበ")]),

        # ── AI ይጠራ ❌ ──
        ("11 አበበ ቢንያም",                   False, [(11, False, "አበበ ቢንያም")]),
        ("11 ሊወጣ ይችላል",                   False, None),
        ("11 ትላንትና ሳልይዝ ቀረው",            False, None),
        ("11 የማነው",                        False, None),
        ("11 በሙሉ አበበ ብልህ ያዝ ወንድሜ ቢል",   True,  [(11, False, None)]),
    ]

    print("=" * 60)
    passed = failed = 0
    for text, expected_clear, expected_nums in tests:
        result = parse_numbers(text, price_full=100, price_half=50)
        nums = result["numbers"] if result else None
        is_clear = result["is_clear_pattern"] if result else None

        nums_ok = (nums == expected_nums) if expected_nums is not None else (result is None or nums is not None)
        clear_ok = (is_clear == expected_clear) if result else True

        ok = nums_ok and clear_ok
        if ok: passed += 1
        else: failed += 1

        mark = "✅" if ok else "❌"
        clear_mark = "🟢 CLEAR" if is_clear else "🔴 AI"
        print(f"{mark} '{text}' → {clear_mark}")
        if not ok:
            if not nums_ok:
                print(f"   nums expected: {expected_nums}")
                print(f"   nums got:      {nums}")
            if not clear_ok:
                print(f"   clear expected: {expected_clear}")
                print(f"   clear got:      {is_clear}")

    print("=" * 60)
    print(f"PASSED: {passed}  FAILED: {failed}")
