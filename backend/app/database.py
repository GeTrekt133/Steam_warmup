"""
Async SQLAlchemy engine и session factory.

Поддерживает SQLite (локально) и PostgreSQL (через Docker) —
переключение одной переменной DATABASE_URL.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    # SQLite не поддерживает pool — отключаем для него
    pool_pre_ping=True if "postgresql" in settings.DATABASE_URL else False,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency для FastAPI — выдаёт async session."""
    async with async_session() as session:
        yield session
