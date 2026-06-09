from parser import format_number

def build_board(settings: dict, taken: dict, paid: dict = None) -> str:
    total = settings["total_numbers"]
    per_person = settings["numbers_per_person"]
    price_full = settings["price_full"]
    price_half = settings.get("price_half")
    prize_1st = settings["prize_1st"]
    prize_2nd = settings.get("prize_2nd")
    prize_3rd = settings.get("prize_3rd")
    payment_info = settings["payment_info"]

    if paid is None:
        paid = {}

    lines = []

    lines.append("🎲 ፈጣን ዕድል ጨዋታ")
    lines.append(f"💰 ዋጋ: {price_full} ብር" + (f" | ግማሽ: {price_half} ብር" if price_half else ""))
    lines.append(f"🥇 1ኛ: {prize_1st} ብር")
    if prize_2nd:
        lines.append(f"🥈 2ኛ: {prize_2nd} ብር")
    if prize_3rd:
        lines.append(f"🥉 3ኛ: {prize_3rd} ብር")
    lines.append("")

    if per_person == 1:
        for n in range(1, total + 1):
            label = format_number(n)
            entry = taken.get(n, [])
            paid_slots = paid.get(n, set())
            if not entry:
                lines.append(f"{label}#")
            else:
                display = _format_entry(entry, paid_slots)
                lines.append(f"{label}# {display}")
    else:
        n = 1
        while n <= total:
            group_start = n
            group_end = min(n + per_person - 1, total)

            label = format_number(group_start)
            entry = taken.get(group_start, [])
            paid_slots = paid.get(group_start, set())
            if not entry:
                lines.append(f"{label}#")
            else:
                display = _format_entry(entry, paid_slots)
                lines.append(f"{label}# {display}")

            for sub in range(group_start + 1, group_end + 1):
                lines.append(f"{format_number(sub)}#")

            lines.append("")
            n += per_person

    lines.append("─────────────────")
    lines.append(payment_info)

    return "\n".join(lines)


def _format_entry(entry: list, paid_slots: set = None) -> str:
    if paid_slots is None:
        paid_slots = set()

    if len(entry) == 1:
        name, is_half, slot = entry[0]
        check = "✅" if slot in paid_slots else ""
        if is_half:
            return f"{name}{check}+"
        else:
            return f"{name}{check}"

    elif len(entry) == 2:
        name1, _, slot1 = entry[0]
        name2, _, slot2 = entry[1]
        check1 = "✅" if slot1 in paid_slots else ""
        check2 = "✅" if slot2 in paid_slots else ""
        return f"{name1}{check1}+{name2}{check2}"

    return ""


def get_group_start(number: int, per_person: int) -> int:
    return ((number - 1) // per_person) * per_person + 1


def build_remaining(settings: dict, taken: dict) -> str:
    total = settings["total_numbers"]
    per_person = settings["numbers_per_person"]

    remaining = []

    if per_person == 1:
        for n in range(1, total + 1):
            entry = taken.get(n, [])
            if not entry:
                remaining.append((n, False))
            elif len(entry) == 1 and entry[0][1]:
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


def build_warning(seconds_left: int) -> str:
    """
    Board ሲሞላ የሚወጣ warning — ቁጥሮች የለም
    """
    mins = seconds_left // 60
    secs = seconds_left % 60
    time_str = f"{mins}:{secs:02d}"
    return f"⚠️ ያልከፈላችሁ ክፈሉ!\n⏱ {time_str} ቀርቷል"


def build_nekay(unpaid: list) -> str:
    """
    ጊዜ ካለቀ በኋላ ነቃይ message
    unpaid = [(number, is_half), ...]
    """
    lines = ["⚠️ ነቃይ!"]
    for number, is_half in unpaid:
        label = format_number(number)
        lines.append(f"{label}+" if is_half else label)
    return "\n".join(lines)
