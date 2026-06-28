
"""
ai_fallback.py
==============
Booking parse fallback — is_clear_pattern=False ሲሆን ብቻ ይጠራል።
Groq rotation ከ handlers.py ይጠቀማል።
"""

from handlers import _call_groq_with_rotation
import json
import re
import logging

logger = logging.getLogger(__name__)


async def ai_parse_booking(text: str, settings: dict) -> dict:
    """
    is_clear_pattern=False ሲሆን ብቻ ይጠራል።
    booking ነው ወይ + numbers ያወጣ።
    """
    total = settings.get("total_numbers", 100)
    price_full = settings.get("price_full", 0)
    price_half = settings.get("price_half", 0)

    prompt = f"""You are an Ethiopian lottery booking parser.
Game has numbers 1-{total}.
Full price: {price_full} ETB, Half price: {price_half} ETB.

User sends messages in Amharic, English, or mixed.
Booking message contains: number(s) + optional name + booking intent (yaz, ፃፍ, ያዝ, መዝግብ, etc)

Examples of booking:
- "96 ሳልሞን እያለ ብልህ yaz" → booking, num=96, name="ሳልሞን"
- "05 አበበ ፃፍልኝ" → booking, num=5, name="አበበ"
- "10 yaz" → booking, num=10, name=null
- "11 21 31 ያዝ" → booking, 3 numbers

NOT booking:
- "96 ለምን ብልህ ትላለህ" → not booking
- "ሰላም እንደምን ነህ" → not booking
- "ውጤት ምን ነው" → not booking

Respond ONLY in this exact JSON format, no extra text:
{{"is_booking": true or false, "numbers": [{{"num": <int>, "name": "<string or null>", "is_half": false}}]}}

If not booking:
{{"is_booking": false, "numbers": []}}"""

    try:
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ]
        result = await _call_groq_with_rotation(messages, max_tokens=150)
        result = re.sub(r"^```json\s*", "", result)
        result = re.sub(r"^```\s*", "", result)
        result = re.sub(r"\s*```$", "", result)
        parsed = json.loads(result.strip())
        logger.info(f"[AI Booking] '{text[:40]}' → is_booking={parsed.get('is_booking')} numbers={parsed.get('numbers')}")
        return parsed
    except Exception as e:
        logger.warning(f"[AI Booking] Error: {e}")
        return {"is_booking": False, "numbers": []}


async def get_ai_fallback(*args, **kwargs):
    return None


def log_transaction(*args, **kwargs):
    pass
