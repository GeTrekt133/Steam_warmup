"""Pydantic-схемы для auth endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=6, max_length=128)
    hwid: str | None = None


class UserLogin(BaseModel):
    username: str
    password: str
    hwid: str | None = None


class UserResponse(BaseModel):
    id: int
    username: str
    hwid: str | None
    is_active: bool
    subscription_tier: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
