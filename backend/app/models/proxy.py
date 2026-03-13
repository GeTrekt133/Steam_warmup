"""Модель прокси-сервера."""

from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Proxy(Base):
    __tablename__ = "proxies"

    id: Mapped[int] = mapped_column(primary_key=True)

    # --- Подключение ---
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column()
    protocol: Mapped[str] = mapped_column(String(20), default="http")  # http, socks5
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Статус ---
    is_alive: Mapped[bool] = mapped_column(default=False)
    ping_ms: Mapped[int | None] = mapped_column(nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    country: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # --- Владелец ---
    owner_id: Mapped[int] = mapped_column()

    # --- Временные метки ---
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
