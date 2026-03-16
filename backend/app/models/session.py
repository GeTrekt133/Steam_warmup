"""
Модели сессий Warmup и Farming для персистентности в БД.

Сессии сохраняются при создании/обновлении, восстанавливаются при рестарте backend.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, Float, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WarmupSession(Base):
    """Сессия прогрева аккаунта (Community Badge квесты)."""
    __tablename__ = "warmup_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Аккаунт
    account_login: Mapped[str] = mapped_column(String(255), index=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )

    # Владелец
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # Статус: pending | running | done | error | interrupted
    status: Mapped[str] = mapped_column(String(50), default="pending")

    # Прогресс квестов (JSON: список {quest_id, quest_name, status, error, retries})
    quests_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Текущий квест
    current_quest: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Сколько квестов выполнено / всего
    quests_done: Mapped[int] = mapped_column(Integer, default=0)
    quests_total: Mapped[int] = mapped_column(Integer, default=0)

    # Ошибка (если status=error)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Время
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


class FarmingSession(Base):
    """Сессия фарма часов (ASF / Smart Farming)."""
    __tablename__ = "farming_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Тип: "manual" (обычный фарм) или "smart" (Smart Farming)
    session_type: Mapped[str] = mapped_column(String(50), default="manual")

    # Идентификатор Smart Farming сессии (если smart)
    smart_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)

    # Бот(ы) — имя ASF бота
    bot_name: Mapped[str] = mapped_column(String(255), index=True)

    # Владелец
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # Статус: active | paused | break | stopped | error
    status: Mapped[str] = mapped_column(String(50), default="active")

    # Игры (JSON массив app_id)
    app_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Целевые часы (0 = бессрочно)
    hours_target: Mapped[float] = mapped_column(Float, default=0.0)

    # Нафармлено часов
    hours_farmed: Mapped[float] = mapped_column(Float, default=0.0)

    # Smart Farming конфиг (JSON)
    smart_config_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Статистика
    breaks_taken: Mapped[int] = mapped_column(Integer, default=0)
    rotations_done: Mapped[int] = mapped_column(Integer, default=0)

    # Ошибка
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Время
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
