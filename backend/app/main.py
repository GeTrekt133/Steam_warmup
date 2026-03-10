"""
Точка входа FastAPI приложения.

Запуск:
    python -m uvicorn app.main:app --reload --port 8420
"""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine
from app.api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Создаёт таблицы при старте (dev mode)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# CORS — разрешаем запросы от Vite dev server и Electron
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS + ["*"],  # '*' для Electron file://
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=settings.API_PORT,
        reload=settings.DEBUG,
    )
