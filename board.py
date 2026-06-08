from parser import format_number

def build_board(settings: dict, taken: dict) -> str:
    """
    Board message ይሰራል።
    taken = {number: [(user_name, is_half, slot), ...]}
    """
    total = settings["total_numbers"]
    per_person = settings["numbers_per_person"]
    price_full = settings["price_full"]
    price_half = settings.get("price_half")
    prize_1st = settings["prize_1st"]
    prize_2nd = settings.get("prize_2nd")
    prize_3rd = settings.get("prize_3rd")
    payment_info = settings["payment_info"]

    lines = []

    # ── ላይ: Game Rules ──
    lines.append("🎲 ፈጣን ዕድል ጨዋታ")
    lines.append(f"💰 ዋጋ: {price_full} ብር" + (f" | ግማሽ: {price_half} ብር" if price_half else ""))
    lines.append(f"🥇 1ኛ: {prize_1st} ብር")
    if prize_2nd:
        lines.append(f"🥈 2ኛ: {prize_2nd} ብር")
    if prize_3rd:
        lines.append(f"🥉 3ኛ: {prize_3rd} ብር")
    lines.append("")

    # ── ቁጥሮች ──
    if per_person == 1:
        # Simple board - እያንዳንዱ ቁጥር
        for n in range(1, total + 1):
            label = format_number(n)
            entry = taken.get(n, [])
            if not entry:
                lines.append(f"{label}#")
            else:
                display = _format_entry(entry)
                lines.append(f"{label}# {display}")
    else:
        # Group board - በ per_person ቡድን
        n = 1
        while n <= total:
            group_start = n
            group_end = min(n + per_person - 1, total)

            # Group leader (first number)
            label = format_number(group_start)
            entry = taken.get(group_start, [])
            if not entry:
                lines.append(f"{label}#")
            else:
                display = _format_entry(entry)
                lines.append(f"{label}# {display}")

            # Rest of group (no name)
            for sub in range(group_start + 1, group_end + 1):
                lines.append(f"{format_number(sub)}#")

            lines.append("")
            n += per_person

    # ── ታች: Payment Info ──
    lines.append("─────────────────")
    lines.append(payment_info)

    return "\n".join(lines)

def _format_entry(entry: list) -> str:
    """
    entry = [(user_name, is_half, slot), ...]
    01# አበበ       → ሙሉ
    01# አበበ+      → ግማሽ (ሌላ ሰው ሊሞላ)
    01# አበበ+አየለ  → ሁለቱም ግማሽ
    """
    if len(entry) == 1:
        name, is_half, _ = entry[0]
        return f"{name}+" if is_half else name
    elif len(entry) == 2:
        name1 = entry[0][0]
        name2 = entry[1][0]
        return f"{name1}+{name2}"
    return ""

def get_group_start(number: int, per_person: int) -> int:
    """ቁጥሩ የሚገኝበት group የመጀመሪያ ቁጥር ይመልሳል"""
    return ((number - 1) // per_person) * per_person + 1

def build_remaining(settings: dict, taken: dict) -> str:
    """ቀሪ ቁጥሮች message ይሰራል"""
    total = settings["total_numbers"]
    per_person = settings["numbers_per_person"]

    remaining = []

    if per_person == 1:
        for n in range(1, total + 1):
            entry = taken.get(n, [])
            if not entry:
                remaining.append((n, False))
            elif len(entry) == 1 and entry[0][1]:  # ግማሽ ብቻ
                remaining.append((n, True))
    else:
        n = 1
        while n <= total:
            group_start = n
            entry = taken.get(group_start, [])
            if not entry:
                remaining.append((group_start, False))
            elif len(entry) == 1 and entry[0][1]:
                remaining.append((group_start, True))
            n += per_person

    if not remaining:
        return None

    lines = ["⚠️ ቀሪ ቁጥሮች!"]
    for num, is_half in remaining:
        label = format_number(num)
        lines.append(f"{label}+" if is_half else label)

    return "\n".join(lines)

def count_remaining(settings: dict, taken: dict) -> int:
    """ቀሪ blocks ስንት እንደሆኑ ይቆጥራል"""
    total = settings["total_numbers"]
    per_person = settings["numbers_per_person"]
    count = 0

    if per_person == 1:
        for n in range(1, total + 1):
            entry = taken.get(n, [])
            if not entry or (len(entry) == 1 and entry[0][1]):
                count += 1
    else:
        n = 1
        while n <= total:
            entry = taken.get(n, [])
            if not entry or (len(entry) == 1 and entry[0][1]):
                count += 1
            n += per_person

    return count
