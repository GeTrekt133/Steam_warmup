"""
BuySellVouchers (buysellvouchers.com) — Playwright автоматизация.

Лучшие цены на региональные Steam Wallet карты (TRY, BRL, INR).
Нет публичного API → автоматизация через браузер.

Требует:
- Зарегистрированный аккаунт на BSV
- Средства для оплаты (крипто USDT, карта)

На первом этапе — заготовка + ручной ввод кода.
"""

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PROVIDER_NAME = "buysellvouchers"
PROVIDER_LABEL = "BuySellVouchers"
BASE_URL = "https://www.buysellvouchers.com"
SEARCH_URL = f"{BASE_URL}/en/products/list/Gift_cards-Steam_Gift_Cards/"

# Примерные цены (для UI, обновляются вручную)
PRICE_EXAMPLES = [
    {"denomination": "$5 USD", "approx_cost": "$5.35", "region": "Global"},
    {"denomination": "$10 USD", "approx_cost": "$10.30", "region": "Global"},
    {"denomination": "50 TRY", "approx_cost": "$2.58", "region": "Turkey"},
    {"denomination": "50 BRL", "approx_cost": "$10.36", "region": "Brazil"},
    {"denomination": "100 TWD", "approx_cost": "$3.11", "region": "Taiwan"},
    {"denomination": "250 INR", "approx_cost": "$2.85", "region": "India"},
    {"denomination": "60000 IDR", "approx_cost": "$3.68", "region": "Indonesia"},
]


@dataclass
class BSVBuyResult:
    success: bool
    code: str | None = None
    cost: float = 0.0
    cost_currency: str = "USD"
    error: str | None = None


def is_configured() -> bool:
    """BSV работает через Playwright — всегда доступен (но требует ручной оплаты)."""
    return True


async def search_products() -> list[dict]:
    """Вернуть примерные цены (статические, т.к. нет API)."""
    return PRICE_EXAMPLES


async def buy_wallet_code_playwright(
    denomination: str = "$5 USD",
    bsv_email: str | None = None,
    bsv_password: str | None = None,
) -> BSVBuyResult:
    """
    Автоматическая покупка через Playwright.

    TODO: Реализация после тестирования на реальном аккаунте BSV.
    Флоу:
    1. Логин на BSV
    2. Поиск Steam Wallet карты нужного номинала
    3. Покупка (крипто USDT)
    4. Ожидание доставки кода
    5. Парсинг кода со страницы заказа
    """
    return BSVBuyResult(
        success=False,
        error=(
            "Автоматическая покупка через BSV пока не реализована. "
            "Купите код вручную на buysellvouchers.com и введите его в поле 'Ручной ввод кода'."
        ),
    )


def get_info() -> dict:
    """Информация о провайдере для UI."""
    return {
        "id": PROVIDER_NAME,
        "name": PROVIDER_LABEL,
        "description": "Лучшие цены на региональные Steam Wallet карты (TRY, BRL, INR)",
        "payment_methods": ["Крипто USDT/USDC", "Visa/Mastercard"],
        "regions": ["Global", "Turkey", "Brazil", "India", "Taiwan", "Indonesia"],
        "automation": "playwright",
        "status": "manual",  # "manual" = ручной ввод кода, "auto" = полная автоматизация
        "url": BASE_URL,
        "price_examples": PRICE_EXAMPLES,
    }
