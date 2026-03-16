"""
G2A Integration API — автоматическая покупка Steam Wallet кодов.

Документация: https://github.com/g2a-official/integration-api-client
Auth: email + API key + HMAC-SHA256 signature.
Sandbox: https://sandbox.g2a.com (для тестов без реальных денег).

Флоу:
1. search_products("Steam Wallet $5") → список товаров
2. create_order(product_id) → order_id
3. pay_order(order_id) → оплата с баланса G2A
4. get_keys(order_id) → ["XXXXX-XXXXX-XXXXX"]
"""

import hashlib
import logging
import time
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class G2AProduct:
    product_id: str
    name: str
    price: float
    currency: str
    quantity: int


@dataclass
class G2ABuyResult:
    success: bool
    code: str | None = None
    order_id: str | None = None
    price: float = 0.0
    currency: str = "USD"
    error: str | None = None


def _base_url() -> str:
    if settings.G2A_SANDBOX:
        return "https://sandboxapi.g2a.com"
    return "https://api.g2a.com"


def _auth_headers() -> dict:
    """Генерация заголовков авторизации G2A (HMAC-SHA256)."""
    ts = str(int(time.time()))
    raw = f"{settings.G2A_API_KEY}{settings.G2A_EMAIL}{ts}"
    signature = hashlib.sha256(
        (raw + settings.G2A_API_SECRET).encode()
    ).hexdigest()

    return {
        "Authorization": f"{settings.G2A_API_KEY}, {signature}",
        "Content-Type": "application/json",
    }


def is_configured() -> bool:
    """Проверить наличие API ключей."""
    return bool(settings.G2A_API_KEY and settings.G2A_API_SECRET and settings.G2A_EMAIL)


async def search_products(
    query: str = "Steam Wallet",
    currency: str = "USD",
    min_qty: int = 1,
) -> list[G2AProduct]:
    """Поиск товаров на G2A."""
    if not is_configured():
        return []

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{_base_url()}/v1/products",
                headers=_auth_headers(),
                params={
                    "search": query,
                    "currency": currency,
                    "minQty": min_qty,
                    "page": 1,
                    "pageSize": 20,
                },
                timeout=15.0,
            )
            if r.status_code == 200:
                data = r.json()
                products = []
                for item in data.get("docs", []):
                    products.append(G2AProduct(
                        product_id=str(item.get("id", "")),
                        name=item.get("name", ""),
                        price=float(item.get("minPrice", 0)),
                        currency=currency,
                        quantity=int(item.get("qty", 0)),
                    ))
                return products
            logger.warning(f"G2A search: HTTP {r.status_code}")
    except Exception as e:
        logger.error(f"G2A search error: {e}")
    return []


async def create_order(product_id: str, quantity: int = 1, max_price: float | None = None) -> dict | None:
    """Создать заказ на G2A."""
    if not is_configured():
        return None

    try:
        body = {
            "productId": product_id,
            "quantity": quantity,
            "currency": "USD",
        }
        if max_price:
            body["maxPrice"] = max_price

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{_base_url()}/v1/order",
                headers=_auth_headers(),
                json=body,
                timeout=15.0,
            )
            if r.status_code in (200, 201):
                return r.json()
            logger.warning(f"G2A create_order: HTTP {r.status_code} — {r.text}")
    except Exception as e:
        logger.error(f"G2A create_order error: {e}")
    return None


async def pay_order(order_id: str) -> dict | None:
    """Оплатить заказ с баланса G2A."""
    if not is_configured():
        return None

    try:
        async with httpx.AsyncClient() as client:
            r = await client.put(
                f"{_base_url()}/v1/order/{order_id}/pay",
                headers=_auth_headers(),
                timeout=15.0,
            )
            if r.status_code == 200:
                return r.json()
            logger.warning(f"G2A pay_order: HTTP {r.status_code} — {r.text}")
    except Exception as e:
        logger.error(f"G2A pay_order error: {e}")
    return None


async def get_keys(order_id: str) -> list[str]:
    """Получить ключи из оплаченного заказа."""
    if not is_configured():
        return []

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{_base_url()}/v1/order/{order_id}/keys",
                headers=_auth_headers(),
                timeout=15.0,
            )
            if r.status_code == 200:
                data = r.json()
                return [k.get("key", "") for k in data.get("keys", []) if k.get("key")]
            logger.warning(f"G2A get_keys: HTTP {r.status_code}")
    except Exception as e:
        logger.error(f"G2A get_keys error: {e}")
    return []


async def buy_wallet_code(query: str = "Steam Wallet $5 USD") -> G2ABuyResult:
    """
    Полный цикл: поиск → заказ → оплата → получение кода.

    Возвращает G2ABuyResult с кодом Steam Wallet.
    """
    if not is_configured():
        return G2ABuyResult(success=False, error="G2A API не настроен")

    # 1. Поиск
    products = await search_products(query)
    if not products:
        return G2ABuyResult(success=False, error="Товары не найдены")

    product = products[0]
    logger.info(f"G2A: выбран '{product.name}' за {product.price} {product.currency}")

    # 2. Создание заказа
    order = await create_order(product.product_id)
    if not order:
        return G2ABuyResult(success=False, error="Не удалось создать заказ")

    order_id = str(order.get("orderId", order.get("id", "")))

    # 3. Оплата
    payment = await pay_order(order_id)
    if not payment:
        return G2ABuyResult(success=False, order_id=order_id, error="Не удалось оплатить")

    # 4. Получение ключей
    keys = await get_keys(order_id)
    if not keys:
        return G2ABuyResult(success=False, order_id=order_id, error="Ключи не получены")

    return G2ABuyResult(
        success=True,
        code=keys[0],
        order_id=order_id,
        price=product.price,
        currency=product.currency,
    )
