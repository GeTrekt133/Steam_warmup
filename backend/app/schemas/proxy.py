"""Pydantic-схемы для прокси."""

from datetime import datetime

from pydantic import BaseModel, Field


# --- Request ---

class ProxyCreate(BaseModel):
    """Создание одного прокси вручную."""
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    protocol: str = "http"  # http, socks5
    username: str | None = None
    password: str | None = None


class ProxyUpdate(BaseModel):
    """Частичное обновление прокси."""
    host: str | None = None
    port: int | None = Field(None, ge=1, le=65535)
    protocol: str | None = None
    username: str | None = None
    password: str | None = None


class ProxyImportTxt(BaseModel):
    """
    Импорт прокси из текста.
    Поддерживаемые форматы:
    - host:port
    - host:port:user:pass
    - protocol://host:port
    - protocol://user:pass@host:port
    """
    content: str


# --- Response ---

class ProxyResponse(BaseModel):
    """Прокси в ответе API."""
    id: int
    host: str
    port: int
    protocol: str
    username: str | None
    is_alive: bool
    ping_ms: int | None
    last_checked_at: datetime | None
    country: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProxyCheckResult(BaseModel):
    """Результат проверки прокси."""
    id: int
    host: str
    port: int
    is_alive: bool
    ping_ms: int | None
    error: str | None = None


class ProxyImportResult(BaseModel):
    """Результат импорта прокси."""
    imported: int
    skipped: int
    errors: list[str]
