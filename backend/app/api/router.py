"""Корневой роутер API — подключает все endpoint-модули."""

from fastapi import APIRouter

from app.api.endpoints import health, auth, accounts, proxies, groups, captcha, registration

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
api_router.include_router(proxies.router, prefix="/proxies", tags=["proxies"])
api_router.include_router(groups.router, prefix="/groups", tags=["groups"])
api_router.include_router(captcha.router, prefix="/captcha", tags=["captcha"])
api_router.include_router(registration.router, prefix="/register", tags=["registration"])
