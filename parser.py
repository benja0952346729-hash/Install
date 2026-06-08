import re

HALF_WORDS = ["begmash", "gmash", "ግማሽ", "በግማሽ", "g", "ግ"]
FULL_WORDS = ["bemulu", "mulu", "በሙሉ", "ሙሉ"]
GLOBAL_HALF_WORDS = ["ሁሉንም በግማሽ", "ሁሉንም ግማሽ", "ሁሉም በግማሽ", "hulunm begmash", "hulunm gmash"]
GLOBAL_FULL_WORDS = ["ሁሉንም በሙሉ", "ሁሉንም ሙሉ", "ሁሉም ሙሉ", "hulunm bemulu", "hulunm mulu"]

def _is_half_word(w):
    return w.lower() in [h.lower() for h in HALF_WORDS]

def _is_full_word(w):
    return w.lower() in [f.lower() for f in FULL_WORDS]

def parse_numbers(text: str):
    original = text.strip()

    # Global full check (ሁሉንም ሙሉ - removes + from all)
    is_global_full = any(w in original for w in GLOBAL_FULL_WORDS)
    # Global half check (ሁሉንም በግማሽ - adds + to all)
    is_global_half = any(w in original for w in GLOBAL_HALF_WORDS)

    # Replace separators with space
    cleaned = re.sub(r"[,=/%&#]", " ", original)
    tokens = cleaned.split()

    numbers = []
    skip_indices = set()

    for i, token in enumerate(tokens):
        if i in skip_indices:
            continue

        token = token.strip()
        if not token or not re.search(r"\d", token):
            continue

        token_is_half = False
        token_is_full = False

        # number+halfword attached: 11gmash, 41ግ, 41g
        for hw in sorted(HALF_WORDS, key=len, reverse=True):
            m = re.match(r"^(\d+)" + re.escape(hw) + r"$", token, re.IGNORECASE)
            if m:
                token = m.group(1); token_is_half = True; break
            m2 = re.match(r"^" + re.escape(hw) + r"(\d+)$", token, re.IGNORECASE)
            if m2:
                token = m2.group(1); token_is_half = True; break

        # number+fullword attached: 11mulu
        if not token_is_half:
            for fw in sorted(FULL_WORDS, key=len, reverse=True):
                m = re.match(r"^(\d+)" + re.escape(fw) + r"$", token, re.IGNORECASE)
                if m:
                    token = m.group(1); token_is_full = True; break

        # trailing +: 52+
        if not token_is_half and not token_is_full and token.endswith("+"):
            token = token[:-1]; token_is_half = True

        # next standalone token is half/full word
        if not token_is_half and not token_is_full and i + 1 < len(tokens):
            nxt = tokens[i + 1].strip()
            if not re.search(r"\d", nxt):
                if _is_half_word(nxt):
                    token_is_half = True; skip_indices.add(i + 1)
                elif _is_full_word(nxt):
                    token_is_full = True; skip_indices.add(i + 1)

        num_match = re.search(r"(\d+)", token)
        if not num_match:
            continue

        num = int(num_match.group(1))
        num = max(1, num)
        numbers.append((num, token_is_half, token_is_full))

    if not numbers:
        return None

    # Check if last token is standalone full word (global full for all)
    last_tok = tokens[-1].strip().lower() if tokens else ""
    trailing_full_word = not re.search(r"\d", last_tok) and any(
        last_tok == fw.lower() for fw in ["bemulu", "mulu", "ሙሉ", "በሙሉ"]
    )
    if trailing_full_word:
        is_global_full = True

    # Apply global modifiers
    result = []
    for num, is_half, is_full in numbers:
        if is_global_full:
            is_half = False
        elif is_global_half:
            is_half = True
        # individual full overrides individual half
        if is_full:
            is_half = False
        result.append((num, is_half))

    # Ambiguous check (only when no global modifier)
    ambiguous = None
    ambiguous_number = None

    if not is_global_half and not is_global_full and len(result) > 1:
        last_num, last_half = result[-1]
        others_half = any(h for n, h in result[:-1])

        if last_half and not others_half:
            # Case 1: ends with standalone + → all_half ambiguous
            orig_end = original.rstrip()
            if orig_end.endswith("+"):
                ambiguous = "all_half"
                ambiguous_number = last_num
            else:
                # Case 2: ends with ግ/g/gmash attached → last_half ambiguous
                last_token = tokens[-1] if tokens else ""
                for hw in ["gmash", "begmash", "ግ", "g"]:
                    if re.match(r"^\d+" + re.escape(hw) + r"$", last_token, re.IGNORECASE):
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
