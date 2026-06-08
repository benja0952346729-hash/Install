import os
import random
from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.getenv("AI_PROVIDER", "groq").lower()
MODEL = os.getenv("AI_MODEL", "llama-3.3-70b-versatile")

# Load all available keys
def load_keys():
    keys = []
    for i in range(1, 11):
        key = os.getenv(f"AI_API_KEY_{i}")
        if key:
            keys.append(key)
    # fallback single key
    single = os.getenv("AI_API_KEY")
    if single and single not in keys:
        keys.append(single)
    return keys

API_KEYS = load_keys()
_key_index = 0

def get_next_key():
    global _key_index
    if not API_KEYS:
        raise ValueError("No AI API keys found in .env")
    key = API_KEYS[_key_index % len(API_KEYS)]
    _key_index += 1
    return key


async def call_ai(system_prompt: str, user_message: str) -> str:
    """Call AI with automatic provider routing and key rotation."""
    last_error = None

    for attempt in range(len(API_KEYS) or 1):
        api_key = get_next_key()
        try:
            if PROVIDER in ("groq", "openai", "deepseek", "together", "mistral"):
                return await _call_openai_compatible(api_key, system_prompt, user_message)
            elif PROVIDER == "anthropic":
                return await _call_anthropic(api_key, system_prompt, user_message)
            elif PROVIDER == "gemini":
                return await _call_gemini(api_key, system_prompt, user_message)
            else:
                # Default: try openai-compatible
                return await _call_openai_compatible(api_key, system_prompt, user_message)
        except Exception as e:
            last_error = e
            print(f"[AI] Key {attempt+1} failed: {e} — trying next key...")
            continue

    raise Exception(f"All API keys failed. Last error: {last_error}")


async def _call_openai_compatible(api_key: str, system_prompt: str, user_message: str) -> str:
    import httpx

    base_urls = {
        "groq": "https://api.groq.com/openai/v1",
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "together": "https://api.together.xyz/v1",
        "mistral": "https://api.mistral.ai/v1",
    }
    base_url = base_urls.get(PROVIDER, os.getenv("AI_BASE_URL", "https://api.openai.com/v1"))

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                "temperature": 0.1,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


async def _call_anthropic(api_key: str, system_prompt: str, user_message: str) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"]


async def _call_gemini(api_key: str, system_prompt: str, user_message: str) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={api_key}",
            headers={"Content-Type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": [{"text": user_message}]}],
                "generationConfig": {"temperature": 0.1},
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
