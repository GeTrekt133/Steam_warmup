"""
Генератор случайных профилей для Steam-регистрации.

Генерирует логины и пароли, проходящие валидацию Steam:
- Логин: 3-32 символа, латиница + цифры + _
- Пароль: 8+ символов, хотя бы 1 буква + 1 цифра + 1 спецсимвол
"""

import random
import string

# Словари для генерации "натуральных" логинов
_ADJECTIVES = [
    "cool", "dark", "fast", "wild", "red", "blue", "cold", "hot", "big",
    "old", "new", "pro", "mad", "raw", "sly", "epic", "bold", "keen",
    "grim", "pale", "calm", "free", "true", "deep", "high", "low",
]

_NOUNS = [
    "wolf", "bear", "hawk", "fox", "lion", "tank", "storm", "blade",
    "fire", "ice", "rock", "star", "moon", "sun", "sky", "rain",
    "ghost", "ninja", "snake", "crow", "shark", "tiger", "viper",
    "eagle", "rider", "scout", "chief", "king", "duke", "ace",
]


def generate_login(prefix: str | None = None) -> str:
    """
    Генерирует случайный Steam-логин.

    Args:
        prefix: если задан, формат: prefix_XXX (с числовым суффиксом)

    Returns:
        Логин 6-20 символов
    """
    if prefix:
        suffix = random.randint(100, 9999)
        login = f"{prefix}_{suffix}"
        return login[:32]

    adj = random.choice(_ADJECTIVES)
    noun = random.choice(_NOUNS)
    num = random.randint(10, 999)
    sep = random.choice(["_", ""])
    login = f"{adj}{sep}{noun}{num}"
    return login


def generate_password(length: int = 14) -> str:
    """
    Генерирует пароль, проходящий валидацию Steam.

    Steam требует: 8+ символов, буквы + цифры.
    Мы делаем сильнее: буквы + цифры + спецсимволы.
    """
    lower = random.choices(string.ascii_lowercase, k=length - 4)
    upper = random.choices(string.ascii_uppercase, k=2)
    digits = random.choices(string.digits, k=1)
    special = random.choices("!@#$%&*", k=1)

    chars = lower + upper + digits + special
    random.shuffle(chars)
    return "".join(chars)
