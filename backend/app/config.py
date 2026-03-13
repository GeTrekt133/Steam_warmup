"""
Конфигурация приложения через переменные окружения.

Все настройки можно переопределить через .env файл в папке backend/
или через переменные окружения системы.

Пример переключения на PostgreSQL:
    DATABASE_URL=postgresql+asyncpg://steam:pass@localhost:5432/steam_panel
"""

import secrets
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
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
    FERNET_KEY: str = ""

    # --- Captcha ---
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""

    # --- CORS ---
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",
    ]


def _ensure_env_keys(s: Settings) -> Settings:
    """Генерирует и сохраняет в .env ключи, которые не должны меняться между запусками."""
    lines_to_add: list[str] = []

    if not s.FERNET_KEY:
        s.FERNET_KEY = Fernet.generate_key().decode()
        lines_to_add.append(f"FERNET_KEY={s.FERNET_KEY}")

    if s.SECRET_KEY and not _env_has_key("SECRET_KEY"):
        lines_to_add.append(f"SECRET_KEY={s.SECRET_KEY}")

    if lines_to_add:
        with open(_ENV_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join([""] + lines_to_add + [""]))

    return s


def _env_has_key(key: str) -> bool:
    """Проверяет, есть ли ключ в .env файле."""
    if not _ENV_FILE.exists():
        return False
    return any(line.startswith(f"{key}=") for line in _ENV_FILE.read_text("utf-8").splitlines())


settings = _ensure_env_keys(Settings())
