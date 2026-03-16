"""Корневой роутер API — подключает все endpoint-модули."""

from fastapi import APIRouter

from app.api.endpoints import health, auth, accounts, proxies, groups, captcha, registration, dataset, asf, warmup, topup

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
api_router.include_router(proxies.router, prefix="/proxies", tags=["proxies"])
api_router.include_router(groups.router, prefix="/groups", tags=["groups"])
api_router.include_router(captcha.router, prefix="/captcha", tags=["captcha"])
api_router.include_router(registration.router, prefix="/register", tags=["registration"])
api_router.include_router(dataset.router, prefix="/dataset", tags=["dataset"])
api_router.include_router(asf.router, prefix="/asf", tags=["asf"])
api_router.include_router(warmup.router, prefix="/warmup", tags=["warmup"])
api_router.include_router(topup.router, prefix="/topup", tags=["topup"])
