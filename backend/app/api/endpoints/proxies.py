"""
Endpoints прокси: CRUD + импорт + проверка + round-robin привязка.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.api.endpoints.auth import get_current_user
from app.schemas.proxy import (
    ProxyCreate,
    ProxyUpdate,
    ProxyImportTxt,
    ProxyResponse,
    ProxyImportResult,
    ProxyCheckResult,
)
from app.services import proxy_service

router = APIRouter()


@router.get("/", response_model=list[ProxyResponse])
async def list_proxies(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    alive_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Список прокси."""
    return await proxy_service.get_proxies(db, current_user.id, skip, limit, alive_only)


@router.get("/count")
async def proxies_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Количество прокси."""
    total = await proxy_service.count_proxies(db, current_user.id)
    return {"count": total}


@router.get("/{proxy_id}", response_model=ProxyResponse)
async def get_proxy(
    proxy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Получить прокси по ID."""
    proxy = await proxy_service.get_proxy(db, proxy_id, current_user.id)
    if not proxy:
        raise HTTPException(status_code=404, detail="Прокси не найден")
    return proxy


@router.post("/", response_model=ProxyResponse, status_code=status.HTTP_201_CREATED)
async def create_proxy(
    data: ProxyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создать прокси."""
    return await proxy_service.create_proxy(db, data, current_user.id)


@router.put("/{proxy_id}", response_model=ProxyResponse)
async def update_proxy(
    proxy_id: int,
    data: ProxyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Обновить прокси."""
    proxy = await proxy_service.update_proxy(db, proxy_id, current_user.id, data)
    if not proxy:
        raise HTTPException(status_code=404, detail="Прокси не найден")
    return proxy


@router.delete("/{proxy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proxy(
    proxy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Удалить прокси."""
    deleted = await proxy_service.delete_proxy(db, proxy_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Прокси не найден")


@router.post("/import/txt", response_model=ProxyImportResult)
async def import_txt(
    data: ProxyImportTxt,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Импорт прокси из текста (разные форматы)."""
    return await proxy_service.import_from_txt(db, data.content, current_user.id)


@router.post("/check", response_model=list[ProxyCheckResult])
async def check_proxies(
    proxy_ids: list[int],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Проверить выбранные прокси (ping)."""
    return await proxy_service.check_proxies(db, proxy_ids, current_user.id)


@router.post("/check-all", response_model=list[ProxyCheckResult])
async def check_all_proxies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Проверить все прокси пользователя."""
    return await proxy_service.check_all_proxies(db, current_user.id)


@router.post("/assign-round-robin")
async def assign_round_robin(
    account_ids: list[int],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Привязать прокси к аккаунтам по кругу (round-robin)."""
    assigned = await proxy_service.assign_proxies_round_robin(
        db, account_ids, current_user.id
    )
    return {"assigned": assigned}
