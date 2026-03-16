"""
Сервис пополнения баланса Steam — оркестрация провайдеров.

Провайдеры:
- G2A: полный API (search → buy → pay → get key)
- BuySellVouchers: Playwright (заготовка, ручной ввод кода)
- GGSEL: Playwright (заготовка, ручной ввод кода)

После покупки кода → активация через ASF команду 'redeem'.
"""

import logging
import time
from dataclasses import dataclass, field

from app.services.providers import g2a_provider, bsv_provider, ggsel_provider
from app.services import asf_ipc

logger = logging.getLogger(__name__)


@dataclass
class TopupResult:
    success: bool
    provider: str
    code: str | None = None
    amount: str = ""         # номинал ("$5 USD", "100 ₽")
    cost: float = 0.0        # сколько заплатили
    cost_currency: str = "USD"
    error: str | None = None
    order_id: str | None = None


@dataclass
class RedeemResult:
    bot_name: str
    code: str
    success: bool
    message: str = ""


# ─── In-memory история покупок ────────────────────────────────

_purchase_history: list[dict] = []


def get_history() -> list[dict]:
    return list(reversed(_purchase_history))


def _save_to_history(result: TopupResult, redeemed_to: list[str] | None = None):
    _purchase_history.append({
        "provider": result.provider,
        "code": result.code,
        "amount": result.amount,
        "cost": result.cost,
        "cost_currency": result.cost_currency,
        "success": result.success,
        "error": result.error,
        "redeemed_to": redeemed_to or [],
        "timestamp": time.time(),
    })


# ─── Провайдеры ──────────────────────────────────────────────


def get_providers() -> list[dict]:
    """Список провайдеров с их статусом."""
    return [
        {
            **g2a_info(),
            "configured": g2a_provider.is_configured(),
        },
        {
            **bsv_provider.get_info(),
            "configured": True,
        },
        {
            **ggsel_provider.get_info(),
            "configured": True,
        },
    ]


def g2a_info() -> dict:
    return {
        "id": "g2a",
        "name": "G2A",
        "description": "Автоматическая покупка через API — Steam Wallet $5-$100",
        "payment_methods": ["Баланс G2A"],
        "regions": ["Global"],
        "automation": "api",
        "status": "auto" if g2a_provider.is_configured() else "not_configured",
        "url": "https://www.g2a.com",
        "price_examples": [],
    }


# ─── Покупка кода ────────────────────────────────────────────


async def buy_code(provider: str, query: str = "Steam Wallet $5 USD") -> TopupResult:
    """Купить Steam Wallet код у провайдера."""
    if provider == "g2a":
        result = await g2a_provider.buy_wallet_code(query)
        tr = TopupResult(
            success=result.success,
            provider="g2a",
            code=result.code,
            amount=query,
            cost=result.price,
            cost_currency=result.currency,
            error=result.error,
            order_id=result.order_id,
        )
        _save_to_history(tr)
        return tr

    elif provider == "buysellvouchers":
        result = await bsv_provider.buy_wallet_code_playwright(query)
        tr = TopupResult(
            success=result.success,
            provider="buysellvouchers",
            code=result.code,
            amount=query,
            cost=result.cost,
            cost_currency=result.cost_currency,
            error=result.error,
        )
        _save_to_history(tr)
        return tr

    elif provider == "ggsel":
        result = await ggsel_provider.buy_wallet_code_playwright(query)
        tr = TopupResult(
            success=result.success,
            provider="ggsel",
            code=result.code,
            amount=query,
            cost=result.cost,
            cost_currency=result.cost_currency,
            error=result.error,
        )
        _save_to_history(tr)
        return tr

    return TopupResult(success=False, provider=provider, error=f"Неизвестный провайдер: {provider}")


# ─── Активация кода ──────────────────────────────────────────


async def redeem_code(bot_name: str, code: str) -> RedeemResult:
    """Активировать код на аккаунте через ASF."""
    result = await asf_ipc.redeem_key(bot_name, code)
    if result is None:
        return RedeemResult(bot_name=bot_name, code=code, success=False, message="ASF IPC недоступен")

    success = "успешно" in result.lower() or "success" in result.lower() or "OK" in result
    return RedeemResult(bot_name=bot_name, code=code, success=success, message=result)


async def redeem_code_batch(bot_names: list[str], code: str) -> list[RedeemResult]:
    """Активировать один код на нескольких аккаунтах (код можно использовать только 1 раз)."""
    # Wallet код одноразовый — активируем на первом боте
    if not bot_names:
        return []
    result = await redeem_code(bot_names[0], code)
    return [result]


async def buy_and_redeem(
    provider: str,
    query: str,
    bot_names: list[str],
) -> dict:
    """Купить код и сразу активировать на аккаунтах."""
    buy_result = await buy_code(provider, query)
    if not buy_result.success or not buy_result.code:
        return {
            "buy": {"success": False, "error": buy_result.error},
            "redeems": [],
        }

    redeems = []
    for bot_name in bot_names:
        r = await redeem_code(bot_name, buy_result.code)
        redeems.append({"bot": r.bot_name, "success": r.success, "message": r.message})
        if r.success:
            # Wallet код одноразовый — после первой успешной активации стоп
            _save_to_history(buy_result, redeemed_to=[bot_name])
            break

    return {
        "buy": {
            "success": True,
            "code": buy_result.code,
            "provider": buy_result.provider,
            "cost": buy_result.cost,
        },
        "redeems": redeems,
    }
