"""
Генератор случайных профилей для Steam-регистрации и Outlook-почт.

Steam:
- Логин: 3-32 символа, латиница + цифры + _
- Пароль: 8+ символов, хотя бы 1 буква + 1 цифра + 1 спецсимвол

Outlook:
- Email: adjective+noun+digits@outlook.com
- Пароль: 16 символов, буквы + цифры + спецсимволы
- Имя/фамилия: из англоязычных списков
- Дата рождения: 1985–2000
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


_FIRST_NAMES = [
    "James", "John", "Robert", "Michael", "David", "William", "Richard",
    "Thomas", "Daniel", "Matthew", "Anthony", "Mark", "Steven", "Paul",
    "Andrew", "Kevin", "Brian", "George", "Edward", "Jason", "Ryan",
    "Jacob", "Gary", "Nicholas", "Eric", "Stephen", "Jonathan", "Larry",
    "Justin", "Scott", "Brandon", "Benjamin", "Samuel", "Patrick", "Jack",
    "Dennis", "Jerry", "Tyler", "Aaron", "Jose", "Nathan", "Henry",
    "Peter", "Adam", "Douglas", "Keith", "Roger", "Gerald", "Carl",
]

_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Wilson", "Anderson", "Taylor",
    "Thomas", "Moore", "Jackson", "Martin", "Lee", "Thompson", "White",
    "Harris", "Clark", "Lewis", "Robinson", "Walker", "Young", "Allen",
    "King", "Wright", "Scott", "Hill", "Green", "Adams", "Baker",
    "Nelson", "Carter", "Mitchell", "Roberts", "Turner", "Phillips",
    "Campbell", "Parker", "Evans", "Edwards", "Collins", "Stewart",
    "Morris", "Reed", "Cook", "Morgan",
]


def generate_first_name() -> str:
    """Случайное англоязычное имя."""
    return random.choice(_FIRST_NAMES)


def generate_last_name() -> str:
    """Случайная англоязычная фамилия."""
    return random.choice(_LAST_NAMES)


def generate_birth_date() -> tuple[int, int, int]:
    """
    Случайная дата рождения (month, day, year) в диапазоне 1985–2000.

    Returns:
        (month, day, year) — например (3, 15, 1993)
    """
    year = random.randint(1985, 2000)
    month = random.randint(1, 12)
    # Простое ограничение дней
    max_day = 28 if month == 2 else (30 if month in (4, 6, 9, 11) else 31)
    day = random.randint(1, max_day)
    return (month, day, year)


def generate_email_address(domain: str = "outlook.com") -> str:
    """
    Генерирует email-адрес в формате adjective+noun+digits@domain.

    Returns:
        Например "coolwolf482@outlook.com"
    """
    adj = random.choice(_ADJECTIVES)
    noun = random.choice(_NOUNS)
    num = random.randint(100, 9999)
    sep = random.choice(["", "_", "."])
    return f"{adj}{sep}{noun}{num}@{domain}"


def generate_email_password(length: int = 16) -> str:
    """
    Генерирует пароль для Outlook.

    Outlook требует: 8+ символов, буквы (верхний+нижний регистр) + цифры.
    """
    lower = random.choices(string.ascii_lowercase, k=length - 5)
    upper = random.choices(string.ascii_uppercase, k=2)
    digits = random.choices(string.digits, k=2)
    special = random.choices("!@#$%&*", k=1)

    chars = lower + upper + digits + special
    random.shuffle(chars)
    return "".join(chars)


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
