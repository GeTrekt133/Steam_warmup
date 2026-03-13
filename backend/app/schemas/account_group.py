"""Pydantic-схемы для групп аккаунтов."""

from datetime import datetime

from pydantic import BaseModel, Field


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    color: str = "#6366f1"


class GroupUpdate(BaseModel):
    name: str | None = None
    color: str | None = None


class GroupResponse(BaseModel):
    id: int
    name: str
    color: str
    account_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class BulkAssignGroup(BaseModel):
    """Массовое назначение аккаунтов в группу."""
    account_ids: list[int]
    group_id: int | None = Field(description="ID группы или null для снятия")
