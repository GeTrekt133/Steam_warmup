"""
Генерация текстов через бесплатные LLM API (Groq / Gemini).

Используется для прогрева аккаунтов:
- Никнеймы Steam
- Описания профиля
- Отзывы на игры

Приоритет: Groq (Llama 3.3) → Gemini → хардкод fallback.
"""

import logging
import random

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ─── Fallback списки (если нет API ключей) ────────────────────

_FALLBACK_NAMES = [
    "Phoenix42", "StormRider", "NightWolf", "BlazeMaster", "IceViper",
    "DarkHawk", "ProGamer99", "SkyRunner", "GhostFox", "CoolAce",
    "RedTiger", "BlueStar", "MadNinja", "FastBear", "EpicKing",
]

_FALLBACK_BIOS = [
    "Just gaming", "CS2 enjoyer", "Steam user since 2024", "GG WP",
    "PC gamer", "Competitive player", "Born to game, forced to work",
    "One more game and I'll sleep", "Press F to pay respects",
    "Gaming is life", "AFK in real life", "Global Elite wannabe",
]

_FALLBACK_REVIEWS = [
    "Great game, really enjoy playing it! Recommend to everyone.",
    "Fun gameplay, nice graphics. Worth trying out.",
    "Solid game with a good community. Hours of fun.",
    "Amazing experience, been playing for hours. 10/10",
    "Really addictive gameplay. Can't stop playing.",
    "Good game for casual and competitive players alike.",
]


# ─── LLM API вызовы ──────────────────────────────────────────


async def _call_groq(prompt: str, max_tokens: int = 100) -> str | None:
    """Вызов Groq API (бесплатный, Llama 3.3 70B)."""
    if not settings.GROQ_API_KEY:
        return None

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.9,
                },
                timeout=15.0,
            )
            if r.status_code == 200:
                data = r.json()
                text = data["choices"][0]["message"]["content"].strip()
                return text
            logger.warning(f"Groq API: HTTP {r.status_code}")
    except Exception as e:
        logger.warning(f"Groq API error: {e}")
    return None


async def _call_gemini(prompt: str, max_tokens: int = 100) -> str | None:
    """Вызов Gemini API (бесплатный tier)."""
    if not settings.GEMINI_API_KEY:
        return None

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={settings.GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.9},
                },
                timeout=15.0,
            )
            if r.status_code == 200:
                data = r.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                return text
            logger.warning(f"Gemini API: HTTP {r.status_code}")
    except Exception as e:
        logger.warning(f"Gemini API error: {e}")
    return None


async def _call_llm(prompt: str, max_tokens: int = 100) -> str | None:
    """Вызов LLM: Groq → Gemini → None."""
    result = await _call_groq(prompt, max_tokens)
    if result:
        return result
    return await _call_gemini(prompt, max_tokens)


# ─── Публичные функции генерации ──────────────────────────────


async def generate_nickname(user_prompt: str | None = None) -> str:
    """
    Сгенерировать никнейм для Steam через LLM.

    Args:
        user_prompt: подсказка от пользователя (стиль, тематика)
    """
    prompt = (
        "Generate exactly 1 creative Steam gaming nickname. "
        "Requirements: 4-16 characters, English, no spaces, can include numbers. "
        "Reply with ONLY the nickname, nothing else."
    )
    if user_prompt:
        prompt += f"\nStyle/theme: {user_prompt}"

    result = await _call_llm(prompt, max_tokens=30)
    if result:
        # Очищаем — LLM может добавить кавычки/пробелы
        clean = result.strip().strip('"\'').replace(" ", "")[:16]
        if clean and len(clean) >= 3:
            return clean

    return random.choice(_FALLBACK_NAMES)


async def generate_bio(user_prompt: str | None = None) -> str:
    """
    Сгенерировать описание профиля Steam через LLM.

    Args:
        user_prompt: подсказка (стиль, тон)
    """
    prompt = (
        "Write a short Steam profile bio/summary (1-2 sentences, max 100 characters). "
        "Make it sound like a real gamer. Be creative and unique. "
        "Reply with ONLY the bio text, nothing else."
    )
    if user_prompt:
        prompt += f"\nStyle: {user_prompt}"

    result = await _call_llm(prompt, max_tokens=60)
    if result:
        clean = result.strip().strip('"\'')[:200]
        if clean and len(clean) >= 5:
            return clean

    return random.choice(_FALLBACK_BIOS)


async def generate_review(game_name: str = "CS2", user_prompt: str | None = None) -> str:
    """
    Сгенерировать отзыв на игру через LLM.

    Args:
        game_name: название игры
        user_prompt: подсказка (тон, что упомянуть)
    """
    prompt = (
        f"Write a short positive Steam review for {game_name} (2-3 sentences, max 200 characters). "
        "Sound like a real player. Be specific about gameplay. "
        "Reply with ONLY the review text, nothing else."
    )
    if user_prompt:
        prompt += f"\nAdditional instructions: {user_prompt}"

    result = await _call_llm(prompt, max_tokens=100)
    if result:
        clean = result.strip().strip('"\'')[:500]
        if clean and len(clean) >= 10:
            return clean

    return random.choice(_FALLBACK_REVIEWS)


async def generate_comment(user_prompt: str | None = None) -> str:
    """Сгенерировать комментарий для профиля."""
    prompt = (
        "Write a very short friendly comment for a Steam profile (3-10 words). "
        "Examples: 'Nice profile!', 'GG bro', 'Cool games collection'. "
        "Reply with ONLY the comment, nothing else."
    )
    if user_prompt:
        prompt += f"\nStyle: {user_prompt}"

    result = await _call_llm(prompt, max_tokens=30)
    if result:
        clean = result.strip().strip('"\'')[:100]
        if clean and len(clean) >= 2:
            return clean

    return random.choice(["Nice profile!", "GG", "+rep", "Cool account!"])


async def generate_batch(
    count: int,
    text_type: str,
    user_prompt: str | None = None,
    game_name: str = "CS2",
) -> list[str]:
    """
    Сгенерировать пакет текстов за 1 вызов LLM.

    Args:
        count: сколько текстов
        text_type: "nickname" | "bio" | "review" | "comment"
        user_prompt: подсказка пользователя
        game_name: для отзывов
    """
    type_prompts = {
        "nickname": f"Generate {count} unique Steam gaming nicknames (4-16 chars, English, no spaces). One per line.",
        "bio": f"Generate {count} unique short Steam profile bios (1-2 sentences each, max 100 chars). One per line.",
        "review": f"Generate {count} unique short positive Steam reviews for {game_name} (2-3 sentences each). One per line.",
        "comment": f"Generate {count} unique short friendly Steam profile comments (3-10 words each). One per line.",
    }

    prompt = type_prompts.get(text_type, type_prompts["nickname"])
    if user_prompt:
        prompt += f"\nStyle/theme: {user_prompt}"
    prompt += "\nReply with ONLY the texts, one per line, no numbering."

    result = await _call_llm(prompt, max_tokens=count * 50)
    if result:
        lines = [l.strip().strip('"\'').strip("- ").strip("0123456789. ") for l in result.strip().split("\n") if l.strip()]
        lines = [l for l in lines if len(l) >= 2]
        if lines:
            return lines[:count]

    # Fallback
    fallbacks = {
        "nickname": _FALLBACK_NAMES,
        "bio": _FALLBACK_BIOS,
        "review": _FALLBACK_REVIEWS,
        "comment": ["Nice!", "GG", "+rep", "Cool!"],
    }
    pool = fallbacks.get(text_type, _FALLBACK_NAMES)
    return [random.choice(pool) for _ in range(count)]
