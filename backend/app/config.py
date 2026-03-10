"""
Конфигурация приложения через переменные окружения.

Все настройки можно переопределить через .env файл в папке backend/
или через переменные окружения системы.

Пример переключения на PostgreSQL:
    DATABASE_URL=postgresql+asyncpg://steam:pass@localhost:5432/steam_panel
"""

import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    APP_NAME: str = "Steam Farming Panel"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    API_PORT: int = 8420

    # --- Database ---
    # По умолчанию SQLite (локальный файл). Для PostgreSQL укажи:
    # DATABASE_URL=postgresql+asyncpg://steam:pass@localhost:5432/steam_panel
    DATABASE_URL: str = "sqlite+aiosqlite:///./steam_panel.db"

    # --- Auth (JWT) ---
    SECRET_KEY: str = secrets.token_urlsafe(64)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 часа

    # --- Encryption (Fernet AES-256) ---
    # Генерируется автоматически если не задан. Сохрани в .env для постоянства!
    FERNET_KEY: str = ""

    # --- CORS ---
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",
    ]


settings = Settings()
