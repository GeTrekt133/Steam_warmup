"""
Endpoints пополнения баланса Steam.

GET  /topup/providers     — список провайдеров
POST /topup/search        — поиск товаров
POST /topup/buy           — купить код
POST /topup/redeem        — активировать код на аккаунте (ASF)
POST /topup/buy-and-redeem — купить + активировать
GET  /topup/history       — история покупок
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.endpoints.auth import get_current_user
from app.models.user import User
from app.services import topup_service
from app.services.providers import g2a_provider, bsv_provider, ggsel_provider

router = APIRouter()


# ─── Схемы ───────────────────────────────────────────────────


class SearchRequest(BaseModel):
    provider: str  # g2a | buysellvouchers | ggsel
    query: str = "Steam Wallet"


class BuyRequest(BaseModel):
    provider: str
    query: str = "Steam Wallet $5 USD"


class RedeemRequest(BaseModel):
    bot_name: str
    code: str


class BuyAndRedeemRequest(BaseModel):
    provider: str
    query: str = "Steam Wallet $5 USD"
    bot_names: list[str]


# ─── Endpoints ───────────────────────────────────────────────


@router.get("/providers")
async def list_providers(current_user: User = Depends(get_current_user)):
    """Список провайдеров с их статусом и ценами."""
    return {"providers": topup_service.get_providers()}


@router.post("/search")
async def search_products(
    req: SearchRequest,
    current_user: User = Depends(get_current_user),
):
    """Поиск Steam Wallet кодов у провайдера."""
    if req.provider == "g2a":
        products = await g2a_provider.search_products(req.query)
        return {"provider": "g2a", "products": [
            {"id": p.product_id, "name": p.name, "price": p.price, "currency": p.currency, "qty": p.quantity}
            for p in products
        ]}
    elif req.provider == "buysellvouchers":
        products = await bsv_provider.search_products()
        return {"provider": "buysellvouchers", "products": products}
    elif req.provider == "ggsel":
        products = await ggsel_provider.search_products()
        return {"provider": "ggsel", "products": products}

    raise HTTPException(status_code=400, detail=f"Неизвестный провайдер: {req.provider}")


@router.post("/buy")
async def buy_code(
    req: BuyRequest,
    current_user: User = Depends(get_current_user),
):
    """Купить Steam Wallet код."""
    result = await topup_service.buy_code(req.provider, req.query)
    if not result.success:
        return {
            "success": False,
            "provider": result.provider,
            "error": result.error,
        }
    return {
        "success": True,
        "provider": result.provider,
        "code": result.code,
        "cost": result.cost,
        "cost_currency": result.cost_currency,
    }


@router.post("/redeem")
async def redeem_code(
    req: RedeemRequest,
    current_user: User = Depends(get_current_user),
):
    """Активировать Steam Wallet код на аккаунте через ASF."""
    from app.services import asf_manager
    if not asf_manager.is_running():
        raise HTTPException(status_code=400, detail="ASF не запущен")

    result = await topup_service.redeem_code(req.bot_name, req.code)
    return {
        "bot_name": result.bot_name,
        "success": result.success,
        "message": result.message,
    }


@router.post("/buy-and-redeem")
async def buy_and_redeem(
    req: BuyAndRedeemRequest,
    current_user: User = Depends(get_current_user),
):
    """Купить код и сразу активировать на аккаунтах."""
    result = await topup_service.buy_and_redeem(req.provider, req.query, req.bot_names)
    return result


@router.get("/history")
async def get_history(current_user: User = Depends(get_current_user)):
    """История покупок (in-memory)."""
    return {"history": topup_service.get_history()}
