import os
import re
import json
import base64
import logging
from typing import Optional
from config import BOT_TOKEN, GROUP_CHAT_ID, GROQ_API_KEYS
import httpx
from groq import Groq
from database import (
    save_sms_payment,
    save_screenshot_payment,
    get_sms_payment_by_ref,
    is_ref_matched_already,
    cleanup_old_payments,
    confirm_payment,
    get_paid_numbers,
    get_active_settings,
    get_taken_numbers,
    get_user_by_number,
    add_winner_balance,
    save_winner,
    log_activity,
    find_matching_sms,        # አዲስ — amount range + sender name ይፈልጋል
    mark_sms_as_used,         # አዲስ — match ሲሆን used ያደርጋል
)

logger = logging.getLogger(__name__)

# ============================================================
# GROQ KEY ROTATION
# ============================================================

_groq_index = 0
_groq_clients = [Groq(api_key=key) for key in GROQ_API_KEYS] if GROQ_API_KEYS else []


def _get_groq_client() -> Groq:
    global _groq_index
    if not _groq_clients:
        raise RuntimeError("GROQ_API_KEY ያልተቀመጠ!")
    client = _groq_clients[_groq_index]
    _groq_index = (_groq_index + 1) % len(_groq_clients)
    return client


def _call_groq_with_rotation(call_fn, max_retries: int = None):
    if max_retries is None:
        max_retries = len(_groq_clients) if _groq_clients else 1
    last_err = None
    for _ in range(max_retries):
        try:
            client = _get_groq_client()
            return call_fn(client)
        except Exception as e:
            err_str = str(e).lower()
            if "rate" in err_str or "limit" in err_str or "429" in err_str:
                last_err = e
                continue
            raise
    raise last_err or RuntimeError("All Groq keys exhausted")


# ============================================================
# SMS PARSER — Groq based
# ============================================================

async def parse_sms(sms: str) -> Optional[dict]:
    """
    Groq ተጠቅሞ SMS ይፈትሻል።
    Returns:
      {
        "is_incoming": bool,
        "type": "Telebirr" | "CBE" | "Awash" | "BOA" | "Other",
        "amount": float,          # እኔጋ የደረሰው ብር
        "sender_name": str|None,  # የላኪ ስም (ካለ)
        "ref": str|None,          # transaction ref (Telebirr ብቻ)
        "has_url": bool,          # URL አለ?
        "url": str|None,          # URL (ካለ)
      }
    """
    prompt = """You are an Ethiopian bank SMS parser.

Analyze this SMS and extract payment information.

Rules:
- is_incoming: true only if money was RECEIVED (credited, received). false if money was SENT (transferred, debited).
- type: "Telebirr", "CBE", "Awash", "BOA", or "Other"
- amount: the amount received (not including service charges/VAT)
- sender_name: name of who sent the money (if mentioned). null if not found.
- ref: transaction reference number. Only extract if Telebirr (transaction number). null for others.
- url: any URL found in the SMS. null if none.

Respond ONLY in this exact JSON format with no extra text:
{
  "is_incoming": true or false,
  "type": "CBE" or "Telebirr" or "Awash" or "BOA" or "Other",
  "amount": <number or null>,
  "sender_name": "<name or null>",
  "ref": "<ref or null>",
  "url": "<url or null>"
}"""

    try:
        response = _call_groq_with_rotation(lambda client: client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": sms},
            ],
            max_tokens=300,
            temperature=0.1,
        ))
        text = response.choices[0].message.content.strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"^```\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        parsed = json.loads(text.strip())

        # Normalize
        if parsed.get("sender_name") in ("null", "None", "", "N/A"):
            parsed["sender_name"] = None
        if parsed.get("ref") in ("null", "None", "", "N/A"):
            parsed["ref"] = None
        if parsed.get("url") in ("null", "None", "", "N/A"):
            parsed["url"] = None

        return parsed

    except Exception as e:
        logger.error(f"[SMS Parse] Groq error: {e}", exc_info=True)
        return None


# ============================================================
# JINA — URL ላይ ስም ማውጣት
# ============================================================

async def fetch_sender_name_from_url(url: str) -> Optional[str]:
    """
    URL ከፍቶ Payer/Sender name ያወጣል።
    CBE receipt: Payer field
    BOA receipt: Payer field
    Awash receipt: Payer/Sender field
    """
    try:
        jina_url = f"https://r.jina.ai/{url}"
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(jina_url, headers={
                "Accept": "text/plain",
                "User-Agent": "Mozilla/5.0",
            })
            if res.status_code != 200:
                return None
            text = res.text

        patterns = [
            r"Payer\s*[:\-]\s*([A-Za-z\s]+)",
            r"Sender\s*[:\-]\s*([A-Za-z\s]+)",
            r"From\s*[:\-]\s*([A-Za-z\s]+)",
            r"Customer Name\s*[:\-]\s*([A-Za-z\s]+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                if name:
                    return name
        return None

    except Exception as e:
        logger.error(f"[Jina] Error: {e}")
        return None


# ============================================================
# SMS WEBHOOK
# ============================================================

async def handle_sms_webhook(raw_sms: str, bot=None, nekay_cb=None) -> dict:
    logger.info(f"[SMS] Received: {raw_sms}")

    parsed = await parse_sms(raw_sms)
    if not parsed:
        return {"success": False, "reason": "unparseable"}

    # Outgoing SMS → skip
    if not parsed.get("is_incoming"):
        logger.info("[SMS] Outgoing SMS — skipping")
        return {"success": False, "reason": "outgoing"}

    amount = parsed.get("amount")
    sender_name = parsed.get("sender_name")
    ref = parsed.get("ref")
    sms_type = parsed.get("type")
    url = parsed.get("url")

    if not amount:
        return {"success": False, "reason": "no_amount"}

    # Sender name URL ላይ ካለ ያወጣል
    if not sender_name and url:
        logger.info(f"[SMS] No sender name — fetching from URL: {url}")
        sender_name = await fetch_sender_name_from_url(url)

    logger.info(f"[SMS] type={sms_type} | amount={amount} | sender={sender_name} | ref={ref}")

    # DB ይቀምጣል
    result = save_sms_payment(
        amount=amount,
        sender_name=sender_name,
        ref=ref,
        sms_type=sms_type,
        raw_sms=raw_sms,
    )

    if result.get("matched") and bot:
        await notify_match(bot, result["matched"], chat_id=GROUP_CHAT_ID, nekay_cb=nekay_cb)

    return {
        "success": True,
        "matched": result.get("matched"),
        "amount": amount,
        "sender_name": sender_name,
        "ref": ref,
        "type": sms_type,
    }


# ============================================================
# PAYMENT PHOTO HANDLER
# ============================================================

async def handle_payment_photo(bot, msg, nekay_cb=None):
    chat_id = msg.chat.id
    telegram_id = msg.from_user.id
    username = msg.from_user.username or msg.from_user.first_name or "Unknown"

    if str(chat_id) != str(GROUP_CHAT_ID):
        from database import is_group_enabled
        if not is_group_enabled(chat_id):
            return

    try:
        photo = msg.photo[-1]
        image_base64 = await download_image_as_base64(photo.file_id)

        await msg.reply_text("⏳ Screenshot እየተረጋገጠ ነው...")

        analysis = await analyze_screenshot(image_base64)

        if not analysis:
            await msg.reply_text("⚠️ ምስሉ ሊተነተን አልቻለም። ግልጽ screenshot ይላኩ።")
            return

        photo_type = analysis.get("photoType", "other")

        if photo_type == "other":
            description = analysis.get("description", "ክፍያ ያልሆነ ምስል")
            try:
                desc = await describe_photo_in_amharic(description)
            except Exception as e:
                logger.warning(f"[Describe] Failed: {e}")
                desc = "ℹ️ ይህ ምስል የክፍያ ደረሰኝ አይደለም።"
            await msg.reply_text(desc)
            return

        amount = analysis.get("amount")
        sender_name = analysis.get("sender_name")
        ref = analysis.get("ref")  # Telebirr ብቻ

        if not amount:
            await msg.reply_text("⚠️ Amount ሊነበብ አልቻለም። ግልጽ screenshot ይላኩ።")
            return

        logger.info(f"[Payment] type={photo_type} | amount={amount} | sender={sender_name} | ref={ref} | user={username}")

        # Match ይፈልጋል
        match = find_matching_sms(
            telegram_id=telegram_id,
            amount=amount,
            sender_name=sender_name,
            ref=ref,
            pay_type=photo_type,
        )

        if not match:
            await msg.reply_text(
                f"⏳ SMS ገና አልደረሰም። ሲደርስ ይወጣዋል...\n"
                f"💰 ETB {amount}"
                + (f"\n👤 {sender_name}" if sender_name else "")
            )
            # Pending ሆኖ ይቀምጣል — SMS ሲደርስ match ያደርጋል
            save_screenshot_payment(
                telegram_id=telegram_id,
                amount=amount,
                sender_name=sender_name,
                ref=ref,
                pay_type=photo_type,
                description=analysis.get("description", ""),
            )
            return

        # Match ተገኘ!
        mark_sms_as_used(match["id"])
        await notify_match(bot, {**match, "telegram_id": telegram_id}, msg.message_id, chat_id, nekay_cb=nekay_cb)

        try:
            log_activity(chat_id, payments=1)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"[Payment] Photo handler error: {e}", exc_info=True)
        await msg.reply_text("❌ Error ተፈጥሯል። እንደገና ይምከሩ።")


# ============================================================
# SCREENSHOT ANALYZER
# ============================================================

async def analyze_screenshot(image_base64: str) -> dict:
    prompt = """You are a payment receipt analyzer for Ethiopian banks.

Supported: CBE, Telebirr, Awash, BOA (Bank of Abyssinia), and other Ethiopian banks.

Extract:
- photoType: "CBE", "Telebirr", "Awash", "BOA", "Other", or "other" (if not a receipt)
- amount: the transferred/received amount (number only, no currency)
- sender_name: name of the person who SENT the money (Payer field). null if not found.
- ref: transaction reference. Only for Telebirr. null for others.
- description: brief description in English

CRITICAL: Read numbers carefully — check 0/O, 1/I, 5/S confusion.

Respond ONLY in this exact JSON format:
{
  "photoType": "CBE" or "Telebirr" or "Awash" or "BOA" or "Other" or "other",
  "amount": <number or null>,
  "sender_name": "<name or null>",
  "ref": "<ref or null>",
  "description": "<description>"
}"""

    try:
        response = _call_groq_with_rotation(lambda client: client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            max_tokens=300,
            temperature=0.1,
        ))
        text = response.choices[0].message.content.strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"^```\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        parsed = json.loads(text.strip())

        for field in ("sender_name", "ref"):
            if parsed.get(field) in ("null", "None", "", "N/A"):
                parsed[field] = None

        return parsed

    except json.JSONDecodeError as e:
        logger.error(f"[Screenshot] JSON parse error: {e}")
        return {"photoType": "other", "amount": None, "sender_name": None, "ref": None, "description": "Could not parse"}
    except Exception as e:
        logger.error(f"[Screenshot] Analysis error: {e}", exc_info=True)
        return {"photoType": "other", "amount": None, "sender_name": None, "ref": None, "description": "Could not analyze"}


# ============================================================
# WINNER PHOTO ANALYZER
# ============================================================

async def analyze_winner_photo(image_base64: str, settings: dict) -> dict:
    prize_1st = settings.get("prize_1st", 0)
    prize_2nd = settings.get("prize_2nd")
    prize_3rd = settings.get("prize_3rd")

    prizes_desc = f"1st prize: {prize_1st} ETB"
    if prize_2nd:
        prizes_desc += f", 2nd: {prize_2nd} ETB"
    if prize_3rd:
        prizes_desc += f", 3rd: {prize_3rd} ETB"

    prompt = f"""You are analyzing a lottery/raffle winner result image.
Game prizes: {prizes_desc}
Total numbers in game: {settings.get('total_numbers')}

Extract the winning numbers from the image carefully.

Respond ONLY in this exact JSON format with no extra text:
{{
  "1st": <winning number as integer or null>,
  "2nd": <winning number as integer or null>,
  "3rd": <winning number as integer or null>
}}

Only include places that have prizes. Numbers must be integers."""

    try:
        response = _call_groq_with_rotation(lambda client: client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            max_tokens=200,
            temperature=0.1,
        ))
        text = response.choices[0].message.content.strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"^```\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        parsed = json.loads(text.strip())

        result = {}
        if parsed.get("1st") is not None:
            result[1] = int(parsed["1st"])
        if parsed.get("2nd") is not None:
            result[2] = int(parsed["2nd"])
        if parsed.get("3rd") is not None:
            result[3] = int(parsed["3rd"])

        return result if result else None

    except Exception as e:
        logger.error(f"[Winner] Analyze error: {e}", exc_info=True)
        return None


# ============================================================
# WINNER PHOTO HANDLER
# ============================================================

async def handle_winner_photo(bot, msg, settings: dict, group_id: int = None):
    try:
        photo = msg.photo[-1]
        image_base64 = await download_image_as_base64(photo.file_id)

        await msg.reply_text("⏳ Winner እየተለየ ነው...")

        winners = await analyze_winner_photo(image_base64, settings)

        if not winners:
            await msg.reply_text("⚠️ Winner ሊለይ አልቻለም። ግልጽ ምስል ይላኩ።")
            return

        prize_map = {
            1: settings.get("prize_1st", 0),
            2: settings.get("prize_2nd"),
            3: settings.get("prize_3rd"),
        }
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        per_person = settings.get("numbers_per_person", 1)
        lines = ["🏆 Winners!\n"]

        _group_id = group_id or settings.get("group_id")

        for place in sorted(winners.keys()):
            number = winners[place]
            prize = prize_map.get(place)
            medal = medals.get(place, "🎖️")

            if not prize:
                lines.append(f"{medal} {place}ኛ: #{number} — prize አልተቀመጠም")
                continue

            if per_person > 1:
                from board import get_group_start
                lookup_number = get_group_start(number, per_person)
            else:
                lookup_number = number

            user = get_user_by_number(settings["id"], lookup_number)
            if not user:
                lines.append(f"{medal} {place}ኛ: #{number} — user አልተገኘም")
                continue

            telegram_id = user["telegram_id"]
            user_name = user["user_name"]

            add_winner_balance(settings["id"], telegram_id, prize)
            save_winner(settings["id"], place, telegram_id, user_name, number, prize, group_id=_group_id)
            lines.append(f"{medal} {place}ኛ: #{number} — {user_name} → ETB {prize} ✅")

        announcement = "\n".join(lines)
        await msg.reply_text(announcement)

        if _group_id:
            try:
                await bot.send_message(chat_id=_group_id, text=announcement)
            except Exception:
                pass

    except Exception as e:
        logger.error(f"[Winner] Handler error: {e}", exc_info=True)
        await msg.reply_text("❌ Error ተፈጥሯል።")


# ============================================================
# MATCH NOTIFICATION
# ============================================================

async def notify_match(bot, match_data: dict, reply_msg_id=None, chat_id=None, nekay_cb=None):
    from board import build_board

    telegram_id = match_data["telegram_id"]
    amount = match_data["amount"]
    pay_type = match_data.get("type", "Unknown")
    sender_name = match_data.get("sender_name", "")

    result = confirm_payment(telegram_id, amount)
    confirmed = result["confirmed"]
    remaining_balance = result["remaining_balance"]

    if confirmed:
        nums = ", ".join(
            str(c["number"]) + ("(ግማሽ)" if c["is_half"] else "")
            for c in confirmed
        )
        message = (
            f"✅ ክፍያ ተረጋግጧል!\n"
            f"💰 Amount: ETB {amount}\n"
            f"🏦 Via: {pay_type}\n"
            + (f"👤 ከ: {sender_name}\n" if sender_name else "")
            + f"🆔 Telegram ID: {telegram_id}\n"
            f"🎯 ✅ ቁጥሮች: {nums}"
        )
        if remaining_balance > 0:
            message += f"\n💳 ቀሪ ባላንስ: ETB {remaining_balance}"
    else:
        message = (
            f"💰 ETB {amount} ተቀብሏል — ነገር ግን የሚሸፈን ቁጥር የለም።\n"
            f"🆔 Telegram ID: {telegram_id}\n"
            f"💳 ባላንስ: ETB {remaining_balance}"
        )

    logger.info(f"[Match] ✅ TelegramID: {telegram_id} | ETB {amount} | confirmed: {len(confirmed)}")

    target_chat = chat_id or GROUP_CHAT_ID
    if target_chat:
        if reply_msg_id:
            await bot.send_message(chat_id=target_chat, text=message, reply_to_message_id=reply_msg_id)
        else:
            await bot.send_message(chat_id=target_chat, text=message)

    if nekay_cb and confirmed:
        await nekay_cb(confirmed)

    if confirmed and target_chat:
        settings = get_active_settings()
        if settings:
            game_id = settings["id"]
            taken = get_taken_numbers(game_id)
            paid = get_paid_numbers(game_id)
            board_text = build_board(settings, taken, paid)
            board_msg_id = settings.get("board_message_id")

            if board_msg_id:
                try:
                    await bot.edit_message_text(
                        chat_id=target_chat,
                        message_id=board_msg_id,
                        text=board_text
                    )
                except Exception:
                    new_msg = await bot.send_message(chat_id=target_chat, text=board_text)
                    from database import update_board_message_id
                    update_board_message_id(game_id, new_msg.message_id)


# ============================================================
# GROQ — አማርኛ ማብራሪያ
# ============================================================

async def describe_photo_in_amharic(description: str) -> str:
    try:
        response = _call_groq_with_rotation(lambda client: client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{
                "role": "user",
                "content": (
                    f'ይህ ምስል "{description}" ነው። '
                    "በአማርኛ በ2-3 emoji ተጠቅሞ ምስሉ ምን እንደሆነ ብቻ አስረዳ። አጭር ሁን።"
                ),
            }],
            max_tokens=100,
            temperature=0.3,
        ))
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[Describe] Error: {e}")
        return "ℹ️ ይህ ምስል የክፍያ ደረሰኝ አይደለም።"


# ============================================================
# HELPERS
# ============================================================

async def download_image_as_base64(file_id: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        get_file_res = await client.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
            params={"file_id": file_id}
        )
        get_file_res.raise_for_status()
        file_path = get_file_res.json()["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        res = await client.get(file_url)
        res.raise_for_status()
        return base64.b64encode(res.content).decode("utf-8")
