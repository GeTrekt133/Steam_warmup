"""
Cloud API заглушка — минимальный сервер для имитации облачного API.

Позволяет frontend-у работать с маркетплейсом и подписками
без реальной облачной инфраструктуры.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Steam Panel Cloud API (stub)", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/cloud/health")
async def health():
    return {"status": "ok", "mode": "stub"}


@app.post("/api/cloud/auth/validate")
async def validate_subscription():
    """Всегда возвращает free-подписку (заглушка)."""
    return {"valid": True, "tier": "free", "expires_at": None}


@app.get("/api/cloud/marketplace")
async def marketplace():
    """Пустой каталог маркетплейса."""
    return {"items": [], "total": 0}
