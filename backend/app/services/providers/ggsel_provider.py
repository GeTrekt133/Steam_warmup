"""
GGSEL (ggsel.net) — Playwright автоматизация.

Одна из немногих платформ для пополнения Steam из РФ.
Оплата: карты РФ, ЮMoney, СБП.
Нет публичного buyer API → автоматизация через браузер.

Требует:
- Аккаунт GGSEL
- Способ оплаты из РФ

На первом этапе — заготовка + ручной ввод кода.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PROVIDER_NAME = "ggsel"
PROVIDER_LABEL = "GGSEL"
BASE_URL = "https://ggsel.net"
SEARCH_URL = f"{BASE_URL}/catalog/steam-gift-cards"

# Примерные цены (для UI)
PRICE_EXAMPLES = [
    {"denomination": "100 ₽", "approx_cost": "115 ₽", "region": "Россия"},
    {"denomination": "500 ₽", "approx_cost": "565 ₽", "region": "Россия"},
    {"denomination": "1000 ₽", "approx_cost": "1120 ₽", "region": "Россия"},
    {"denomination": "50 TRY", "approx_cost": "320 ₽", "region": "Turkey"},
    {"denomination": "$5 USD", "approx_cost": "530 ₽", "region": "Global"},
    {"denomination": "$10 USD", "approx_cost": "1050 ₽", "region": "Global"},
]


@dataclass
class GGSELBuyResult:
    success: bool
    code: str | None = None
    cost: float = 0.0
    cost_currency: str = "RUB"
    error: str | None = None


def is_configured() -> bool:
    """GGSEL работает через Playwright — всегда доступен (но требует ручной оплаты)."""
    return True


async def search_products() -> list[dict]:
    """Вернуть примерные цены (статические, т.к. нет API)."""
    return PRICE_EXAMPLES


async def buy_wallet_code_playwright(
    denomination: str = "100 ₽",
    ggsel_email: str | None = None,
    ggsel_password: str | None = None,
) -> GGSELBuyResult:
    """
    Автоматическая покупка через Playwright.

    TODO: Реализация после тестирования на реальном аккаунте GGSEL.
    Флоу:
    1. Логин на GGSEL
    2. Поиск "Пополнение Steam" нужного номинала
    3. Оплата (карта РФ / ЮMoney / СБП)
    4. Ожидание доставки кода
    5. Парсинг кода
    """
    return GGSELBuyResult(
        success=False,
        error=(
            "Автоматическая покупка через GGSEL пока не реализована. "
            "Купите код вручную на ggsel.net и введите его в поле 'Ручной ввод кода'."
        ),
    )


def get_info() -> dict:
    """Информация о провайдере для UI."""
    return {
        "id": PROVIDER_NAME,
        "name": PROVIDER_LABEL,
        "description": "Пополнение Steam из РФ — карты РФ, ЮMoney, СБП",
        "payment_methods": ["Карта РФ", "ЮMoney", "СБП", "QIWI"],
        "regions": ["Россия", "Turkey", "Global"],
        "automation": "playwright",
        "status": "manual",
        "url": BASE_URL,
        "price_examples": PRICE_EXAMPLES,
    }
