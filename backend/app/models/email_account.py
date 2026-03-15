"""
Модель email-аккаунта (Outlook/Hotmail/Live).

Используется для автоматической регистрации почты перед созданием Steam-аккаунта.
Пароль хранится зашифрованным (Fernet AES-256).
"""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EmailStatus(str, PyEnum):
    """Статусы email-аккаунта."""
    ACTIVE = "active"                 # Рабочий, можно использовать
    PHONE_REQUIRED = "phone_required" # Outlook потребовал телефон
    ERROR = "error"                   # Ошибка при создании
    CREATING = "creating"             # В процессе регистрации


class EmailAccount(Base):
    __tablename__ = "email_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)

    # --- Почта (зашифрован пароль) ---
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_encrypted: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(50), default="outlook")  # outlook, hotmail, live

    # --- Статус ---
    status: Mapped[str] = mapped_column(String(50), default=EmailStatus.CREATING)

    # --- Связь со Steam-аккаунтом ---
    steam_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )

    # --- Прокси ---
    proxy_id: Mapped[int | None] = mapped_column(
        ForeignKey("proxies.id", ondelete="SET NULL"), nullable=True
    )

    # --- Владелец (пользователь панели) ---
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # --- Временные метки ---
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # --- Заметка ---
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
