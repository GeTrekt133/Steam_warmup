"""Pydantic-схемы для email-аккаунтов."""

from datetime import datetime
from pydantic import BaseModel


class EmailAccountResponse(BaseModel):
    id: int
    email: str
    provider: str
    status: str
    steam_account_id: int | None = None
    created_at: datetime
    note: str | None = None

    model_config = {"from_attributes": True}
