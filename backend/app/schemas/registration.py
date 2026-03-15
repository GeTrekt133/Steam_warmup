"""Pydantic-схемы для авторегистрации Steam-аккаунтов."""

from pydantic import BaseModel, Field


class RegistrationRequest(BaseModel):
    """Запрос на регистрацию одного аккаунта."""
    email: str | None = Field(None, description="email:password (через двоеточие). Не нужен если auto_create_email=True")
    login: str | None = Field(None, description="Логин Steam (если None — генерируется)")
    password: str | None = Field(None, description="Пароль Steam (если None — генерируется)")
    proxy_id: int | None = None
    group_id: int | None = None
    auto_create_email: bool = Field(False, description="Автоматически создать Outlook-почту")


class BatchRegistrationRequest(BaseModel):
    """Запрос на массовую регистрацию."""
    emails: list[str] | None = Field(None, description="Список email:password (не нужен если auto_create_email=True)")
    count: int | None = Field(None, ge=1, le=100, description="Количество аккаунтов (если auto_create_email=True)")
    login_prefix: str | None = Field(None, description="Префикс для логинов (prefix_001, prefix_002)")
    proxy_ids: list[int] | None = Field(None, description="Прокси для ротации")
    group_id: int | None = None
    max_concurrent: int = Field(3, ge=1, le=10, description="Параллельных регистраций")
    auto_create_email: bool = Field(False, description="Автоматически создать Outlook-почту")


class RegistrationStepStatus(BaseModel):
    """Статус одного шага регистрации."""
    step: str
    status: str  # "pending", "running", "done", "error"
    detail: str | None = None


class RegistrationResult(BaseModel):
    """Результат регистрации одного аккаунта."""
    success: bool
    login: str | None = None
    password: str | None = None
    email: str | None = None
    email_password: str | None = None  # пароль от email (если auto_create_email)
    steam_id: str | None = None
    account_id: int | None = None
    email_created: bool = False  # True если email был создан автоматически
    error: str | None = None
    steps: list[RegistrationStepStatus] = []


class BatchRegistrationStatus(BaseModel):
    """Статус массовой регистрации."""
    task_id: str
    total: int
    completed: int
    succeeded: int
    failed: int
    in_progress: int
    results: list[RegistrationResult] = []
