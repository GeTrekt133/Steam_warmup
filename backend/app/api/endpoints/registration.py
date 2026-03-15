"""
Endpoints авторегистрации Steam-аккаунтов.

Поддерживает:
- POST /register/single — регистрация одного аккаунта
- POST /register/batch — массовая регистрация (async task)
- GET /register/status/{task_id} — статус массовой регистрации
"""

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.api.endpoints.auth import get_current_user
from app.schemas.registration import (
    RegistrationRequest,
    BatchRegistrationRequest,
    RegistrationResult,
    RegistrationStepStatus,
    BatchRegistrationStatus,
)
from app.schemas.account import AccountCreate
from app.services import account_service
from app.services import email_account_service
from app.services.steam_registration import register_single_account, register_batch
from app.services.captcha_orchestrator import get_orchestrator

router = APIRouter()

# In-memory хранение статуса batch-задач (по task_id)
_batch_tasks: dict[str, BatchRegistrationStatus] = {}


def _proxy_dict(proxy_str: str | None) -> dict | None:
    """Конвертировать строку прокси в dict для requests."""
    if not proxy_str:
        return None
    return {"http": proxy_str, "https": proxy_str}


def _build_proxy_dict(px) -> dict:
    """Построить proxy dict из модели Proxy."""
    proxy_str = f"{px.protocol}://"
    if px.username and px.password:
        proxy_str += f"{px.username}:{px.password}@"
    proxy_str += f"{px.host}:{px.port}"
    return {"http": proxy_str, "https": proxy_str}


@router.post("/single", response_model=RegistrationResult)
async def register_single(
    req: RegistrationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Зарегистрировать один Steam-аккаунт.

    Полный flow: captcha → email verify → IMAP confirm → create account → save to DB.
    """
    # Получаем прокси если указан
    proxy = None
    if req.proxy_id:
        from sqlalchemy import select
        from app.models.proxy import Proxy
        result = await db.execute(select(Proxy).where(Proxy.id == req.proxy_id))
        px = result.scalar_one_or_none()
        if px:
            proxy = _build_proxy_dict(px)

    ctx = await register_single_account(
        email_with_password=req.email,
        login=req.login,
        password=req.password,
        proxy=proxy,
        auto_create_email=req.auto_create_email,
    )

    # Сохраняем email-аккаунт если был создан автоматически
    email_account_id = None
    if req.auto_create_email and ctx.email and ctx.email_password:
        try:
            email_status = "active" if ctx.success else (ctx.error if ctx.error == "phone_required" else "error")
            email_acc = await email_account_service.create_email_account(
                db, email=ctx.email, password=ctx.email_password,
                owner_id=current_user.id, proxy_id=req.proxy_id,
                status=email_status,
                note=f"Авторег. Steam login: {ctx.login}" if ctx.success else ctx.error,
            )
            email_account_id = email_acc.id
        except Exception:
            pass  # не критично — Steam акк важнее

    # Сохраняем Steam-аккаунт если успешно
    account_id = None
    if ctx.success:
        account_data = AccountCreate(
            login=ctx.login,
            password=ctx.password,
            steam_id=ctx.steam_id,
            proxy_id=req.proxy_id,
            group_id=req.group_id,
            note=f"Авторег. Email: {ctx.email}",
        )
        account = await account_service.create_account(db, account_data, current_user.id)
        account_id = account.id

        # Привязываем email к Steam-аккаунту
        if email_account_id:
            await email_account_service.link_to_steam(db, email_account_id, account.id)

    return RegistrationResult(
        success=ctx.success,
        login=ctx.login,
        password=ctx.password if ctx.success else None,
        email=ctx.email,
        email_password=ctx.email_password if req.auto_create_email else None,
        steam_id=ctx.steam_id,
        account_id=account_id,
        email_created=req.auto_create_email and ctx.email_password is not None,
        error=ctx.error,
        steps=[
            RegistrationStepStatus(step=s.name, status=s.status, detail=s.detail)
            for s in ctx.steps
        ],
    )


@router.post("/batch")
async def register_batch_start(
    req: BatchRegistrationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Запустить массовую регистрацию в фоне.

    Возвращает task_id для отслеживания через GET /register/status/{task_id}.
    """
    if not req.emails and not req.auto_create_email:
        raise HTTPException(status_code=400, detail="Список emails пуст и auto_create_email=False")

    total = len(req.emails) if req.emails else (req.count or 1)

    task_id = str(uuid.uuid4())[:8]
    status = BatchRegistrationStatus(
        task_id=task_id,
        total=total,
        completed=0,
        succeeded=0,
        failed=0,
        in_progress=0,
    )
    _batch_tasks[task_id] = status

    asyncio.create_task(
        _run_batch(task_id, req, current_user.id)
    )

    return {"task_id": task_id, "total": total, "status": "started"}


async def _run_batch(
    task_id: str,
    req: BatchRegistrationRequest,
    owner_id: int,
):
    """Фоновая задача массовой регистрации."""
    from app.database import async_session

    status = _batch_tasks[task_id]
    total = len(req.emails) if req.emails else (req.count or 1)
    status.in_progress = total

    # Подготовка прокси
    proxy_list = None
    if req.proxy_ids:
        async with async_session() as db:
            from sqlalchemy import select
            from app.models.proxy import Proxy
            result = await db.execute(
                select(Proxy).where(Proxy.id.in_(req.proxy_ids))
            )
            proxies = result.scalars().all()
            proxy_list = [_build_proxy_dict(px) for px in proxies]

    async for ctx in register_batch(
        emails=req.emails,
        count=req.count,
        login_prefix=req.login_prefix,
        proxy_list=proxy_list,
        max_concurrent=req.max_concurrent,
        auto_create_email=req.auto_create_email,
    ):
        status.completed += 1
        status.in_progress = status.total - status.completed

        result = RegistrationResult(
            success=ctx.success,
            login=ctx.login,
            password=ctx.password if ctx.success else None,
            email=ctx.email,
            steam_id=ctx.steam_id,
            error=ctx.error,
            steps=[
                RegistrationStepStatus(step=s.name, status=s.status, detail=s.detail)
                for s in ctx.steps
            ],
        )

        if ctx.success:
            status.succeeded += 1
            # Сохраняем в БД
            try:
                async with async_session() as db:
                    account_data = AccountCreate(
                        login=ctx.login,
                        password=ctx.password,
                        steam_id=ctx.steam_id,
                        group_id=req.group_id,
                    )
                    account = await account_service.create_account(db, account_data, owner_id)
                    result.account_id = account.id
            except Exception as e:
                result.error = f"Аккаунт создан в Steam, но не сохранён в БД: {e}"
        else:
            status.failed += 1

        status.results.append(result)


@router.get("/status/{task_id}", response_model=BatchRegistrationStatus)
async def get_batch_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """Получить статус массовой регистрации."""
    status = _batch_tasks.get(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return status
