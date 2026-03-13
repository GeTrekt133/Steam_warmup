"""
Модель Steam-аккаунта.

Чувствительные поля (password, shared_secret, identity_secret) хранятся
в БД в зашифрованном виде (Fernet AES-256). Шифрование/расшифровка
происходит на уровне сервиса, а не модели — в БД лежит ciphertext.
"""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AccountStatus(str, PyEnum):
    """Статусы аккаунта."""
    ACTIVE = "active"           # Рабочий
    BANNED = "banned"           # VAC/Trade/Community бан
    LIMITED = "limited"         # Лимитированный (< $5)
    COOLDOWN = "cooldown"      # Временное ограничение
    UNCHECKED = "unchecked"    # Не проверен
    ERROR = "error"            # Ошибка входа


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)

    # --- Логин (зашифрованы в сервисе) ---
    login: Mapped[str] = mapped_column(String(255), index=True)
    password_encrypted: Mapped[str] = mapped_column(Text)

    # --- Steam идентификаторы ---
    steam_id: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    profile_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # --- SteamGuard / maFile (зашифрованы) ---
    shared_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    identity_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    mafile_json_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Статус и метаданные ---
    status: Mapped[str] = mapped_column(String(50), default=AccountStatus.UNCHECKED)
    steam_level: Mapped[int] = mapped_column(Integer, default=0)
    cs2_hours: Mapped[float] = mapped_column(default=0.0)
    balance: Mapped[float] = mapped_column(default=0.0)         # Баланс кошелька
    is_limited: Mapped[bool] = mapped_column(default=True)       # Лимитированный акк

    # --- Прокси ---
    proxy_id: Mapped[int | None] = mapped_column(
        ForeignKey("proxies.id", ondelete="SET NULL"), nullable=True
    )

    # --- Группа ---
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("account_groups.id", ondelete="SET NULL"), nullable=True
    )

    # --- Владелец (пользователь панели) ---
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # --- Временные метки ---
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # --- Заметка ---
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def has_mafile(self) -> bool:
        """Есть ли привязанный maFile (SteamGuard)."""
        return self.mafile_json_encrypted is not None
