import os
import re
import json
import base64
import logging
from typing import Optional
from config import BOT_TOKEN, GROUP_CHAT_ID
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
)

logger = logging.getLogger(__name__)

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))


# ============================================================
# SMS WEBHOOK
# ============================================================
async def handle_sms_webhook(raw_sms: str, bot=None, nekay_cb=None) -> dict:
    """Android SMS Forwarder ከሚልከው SMS ይቀበላል"""
    logger.info(f"[SMS] Received: {raw_sms}")

    parsed = await parse_sms(raw_sms)
    if not parsed:
        logger.info("[SMS] Could not parse SMS")
        return {"success": False, "reason": "unparseable"}

    ref_no = parsed.get("refNo")
    amount = parsed.get("amount")
    sms_type = parsed.get("type")

    logger.info(f"[SMS] Parsed → Type: {sms_type} | Ref: {ref_no} | Amount: {amount}")

    if not ref_no:
        return {"success": False, "reason": "no_ref"}

    # Duplicate check
    if get_sms_payment_by_ref(ref_no):
        logger.info(f"[SMS] Ref {ref_no} already exists — skipping")
        return {"success": False, "reason": "ref_already_used", "refNo": ref_no}

    result = save_sms_payment(ref_no, amount, sms_type, raw_sms)

    if result.get("matched") and bot:
        from config import GROUP_CHAT_ID
        await notify_match(bot, result["matched"], chat_id=GROUP_CHAT_ID, nekay_cb=nekay_cb)

    return {"success": True, "matched": result.get("matched"), **parsed}


# ============================================================
# PAYMENT PHOTO HANDLER
# ============================================================
async def handle_payment_photo(bot, msg, nekay_cb=None):
    """Group ውስጥ screenshot ሲላክ"""
    chat_id = msg.chat.id
    telegram_id = msg.from_user.id
    username = msg.from_user.username or msg.from_user.first_name or "Unknown"

    if str(chat_id) != str(GROUP_CHAT_ID):
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
        ref_no = analysis.get("refNo")

        logger.info(f"[Payment] photoType={photo_type} | refNo={ref_no} | user={username}")

        if photo_type not in ("CBE", "Telebirr"):
            description = analysis.get("description", "ክፍያ ያልሆነ ምስል")
            try:
                desc = await describe_photo_in_amharic(description)
            except Exception as e:
                logger.warning(f"[Describe] Failed: {e}")
                desc = "ℹ️ ይህ ምስል የክፍያ ደረሰኝ አይደለም።"
            await msg.reply_text(desc)
            return

        if not ref_no:
            await msg.reply_text("⚠️ Reference number ሊነበብ አልቻለም። ግልጽ screenshot ይላኩ።")
            return

        if is_ref_matched_already(ref_no):
            await msg.reply_text("⚠️ ይህ ክፍያ ቀደም ሲል ተረጋግጧል።")
            return

        result = save_screenshot_payment(
            telegram_id, ref_no, photo_type, analysis.get("description", "")
        )

        if result.get("matched"):
            await notify_match(bot, result["matched"], msg.message_id, chat_id, nekay_cb=nekay_cb)
        else:
            await msg.reply_text(
                f"✅ Screenshot ተቀብሏል። SMS ሲረጋገጥ ይወጣዋል...\n🔖 Ref: {ref_no}"
            )

    except Exception as e:
        logger.error(f"[Payment] Photo handler error: {e}", exc_info=True)
        await msg.reply_text("❌ Error ተፈጥሯል። እንደገና ይምከሩ።")


# ============================================================
# SMS PARSER
# ============================================================
async def parse_sms(sms: str) -> Optional[dict]:

    # CBE — Direct credit
    m = re.search(r"Credited with ETB ([\d,]+\.?\d*).+?Ref No\s+([A-Z0-9]+)", sms, re.DOTALL)
    if m:
        return {"type": "CBE", "amount": float(m.group(1).replace(",", "")), "refNo": m.group(2)}

    # CBE — Transfer with URL receipt
    m = re.search(
        r"(?:received|transferred) ETB ([\d,]+\.?\d*).+(https://Mbreciept\S+)",
        sms, re.DOTALL | re.IGNORECASE
    )
    if m:
        amount = float(m.group(1).replace(",", ""))
        ref_no = await fetch_ref_from_url(m.group(2).strip())
        return {"type": "CBE", "amount": amount, "refNo": ref_no}

    # Telebirr → CBE transfer
    m = re.search(
        r"transferred ETB ([\d,]+\.?\d*).+?bank transaction number is\s+([A-Z0-9]+)",
        sms, re.DOTALL
    )
    if m:
        return {"type": "Telebirr", "amount": float(m.group(1).replace(",", "")), "refNo": m.group(2)}

    # Telebirr — Received
    m = re.search(
        r"received ETB ([\d,]+\.?\d*).+?transaction number is\s+([A-Z0-9]+)",
        sms, re.DOTALL
    )
    if m:
        return {"type": "Telebirr", "amount": float(m.group(1).replace(",", "")), "refNo": m.group(2)}

    return None


# ============================================================
# CBE RECEIPT URL → REF
# ============================================================
async def fetch_ref_from_url(url: str) -> Optional[str]:
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
            r"VAT Receipt No[:\s]+([A-Z0-9]+)",
            r"Reference No\.\s*\(VAT Invoice No\)[:\s]+([A-Z0-9]+)",
            r"Reference No[:\s]+([A-Z0-9]+)",
            r"Ref No[:\s]+([A-Z0-9]+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return m.group(1)
        return None
    except Exception as e:
        logger.error(f"[RefFetch] Error: {e}")
        return None


# ============================================================
# GROQ — SCREENSHOT ANALYZER
# ============================================================
async def analyze_screenshot(image_base64: str) -> dict:
    prompt = """You are a payment receipt analyzer. Look at this image and extract information.

CRITICAL: Read the reference number with extreme care — check 0/O, 1/I, 5/S confusion.

Respond ONLY in this exact JSON format with no extra text:
{
  "photoType": "CBE" or "Telebirr" or "other",
  "refNo": "reference number or null",
  "description": "brief description in English"
}

- CBE = Commercial Bank of Ethiopia receipt
- Telebirr = Telebirr payment receipt
- refNo: CBE → "VAT Receipt No" or "Ref No" | Telebirr → "transaction number"
- If not a payment receipt, set photoType to "other" and refNo to null"""

    try:
        response = groq_client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
            max_tokens=300,
            temperature=0.1,
        )
        text = response.choices[0].message.content.strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"^```\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
        parsed = json.loads(text)
        if parsed.get("refNo") in ("null", "None", "", "N/A"):
            parsed["refNo"] = None
        return parsed
    except json.JSONDecodeError as e:
        logger.error(f"[Screenshot] JSON parse error: {e} | Raw: {text}")
        return {"photoType": "other", "refNo": None, "description": "Could not parse response"}
    except Exception as e:
        logger.error(f"[Screenshot] Analysis error: {e}", exc_info=True)
        return {"photoType": "other", "refNo": None, "description": "Could not analyze"}


# ============================================================
# GROQ — አማርኛ ማብራሪያ
# ============================================================
async def describe_photo_in_amharic(description: str) -> str:
    try:
        response = groq_client.chat.completions.create(
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
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[Describe] Error: {e}")
        return "ℹ️ ይህ ምስል የክፍያ ደረሰኝ አይደለም።"


# ============================================================
# MATCH NOTIFICATION
# ============================================================
async def notify_match(bot, match_data: dict, reply_msg_id=None, chat_id=None, nekay_cb=None):
    from database import confirm_payment, get_paid_numbers, get_active_settings
    from board import build_board
    from database import get_taken_numbers

    telegram_id = match_data["telegram_id"]
    amount = match_data["amount"]
    pay_type = match_data["type"]
    ref_no = match_data["refNo"]

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
            f"🔖 Ref: {ref_no}\n"
            f"👤 Telegram ID: {telegram_id}\n"
            f"🎯 ✅ ቁጥሮች: {nums}"
        )
        if remaining_balance > 0:
            message += f"\n💳 ቀሪ ባላንስ: ETB {remaining_balance}"
    else:
        message = (
            f"💰 ETB {amount} ተቀብሏል — ነገር ግን የሚሸፈን ቁጥር የለም።\n"
            f"👤 Telegram ID: {telegram_id}\n"
            f"💳 ባላንስ: ETB {remaining_balance}"
        )

    logger.info(f"[Match] ✅ TelegramID: {telegram_id} | ETB {amount} | confirmed: {len(confirmed)}")

    target_chat = chat_id or GROUP_CHAT_ID
    if target_chat:
        if reply_msg_id:
            await bot.send_message(
                chat_id=target_chat, text=message, reply_to_message_id=reply_msg_id
            )
        else:
            await bot.send_message(chat_id=target_chat, text=message)

    # ነቃይ callback — confirmed ቁጥሮች ከነቃይ ይጠፋሉ
    if nekay_cb and confirmed:
        await nekay_cb(confirmed)

    # Board ዘምን
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
