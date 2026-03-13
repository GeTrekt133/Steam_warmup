"""Pydantic-схемы для аккаунтов."""

from datetime import datetime

from pydantic import BaseModel, Field


# --- Request ---

class AccountCreate(BaseModel):
    """Создание одного аккаунта вручную."""
    login: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)
    steam_id: str | None = None
    proxy_id: int | None = None
    group_id: int | None = None
    note: str | None = None


class AccountUpdate(BaseModel):
    """Частичное обновление аккаунта."""
    password: str | None = None
    steam_id: str | None = None
    proxy_id: int | None = None
    group_id: int | None = None
    status: str | None = None
    note: str | None = None


class AccountImportTxt(BaseModel):
    """Импорт аккаунтов из текста (login:password построчно)."""
    content: str = Field(description="Текст с аккаунтами: login:password на каждой строке")
    group_id: int | None = None
    delimiter: str = ":"


class MaFileImport(BaseModel):
    """Импорт одного maFile (JSON содержимое)."""
    mafile_json: dict
    password: str | None = Field(None, description="Пароль аккаунта (если известен)")
    group_id: int | None = None


class MaFileBatchImport(BaseModel):
    """Импорт нескольких maFiles."""
    files: list[MaFileImport]


# --- Response ---

class AccountResponse(BaseModel):
    """Аккаунт в ответе API (пароль НЕ возвращается)."""
    id: int
    login: str
    steam_id: str | None
    profile_url: str | None
    has_mafile: bool
    status: str
    steam_level: int
    cs2_hours: float
    balance: float
    is_limited: bool
    proxy_id: int | None
    group_id: int | None
    note: str | None
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}


class AccountImportResult(BaseModel):
    """Результат импорта."""
    imported: int
    skipped: int
    errors: list[str]
