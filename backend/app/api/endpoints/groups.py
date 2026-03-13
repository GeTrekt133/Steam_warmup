"""Endpoints групп аккаунтов: CRUD + bulk-назначение."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.api.endpoints.auth import get_current_user
from app.schemas.account_group import GroupCreate, GroupUpdate, GroupResponse, BulkAssignGroup
from app.services import group_service

router = APIRouter()


@router.get("/", response_model=list[GroupResponse])
async def list_groups(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Список групп с количеством аккаунтов."""
    return await group_service.get_groups(db, current_user.id)


@router.post("/", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    data: GroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создать группу."""
    group = await group_service.create_group(db, data, current_user.id)
    return GroupResponse(
        id=group.id, name=group.name, color=group.color,
        account_count=0, created_at=group.created_at,
    )


@router.put("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: int,
    data: GroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Обновить группу."""
    group = await group_service.update_group(db, group_id, current_user.id, data)
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    # Получаем полный ответ с count
    groups = await group_service.get_groups(db, current_user.id)
    return next(g for g in groups if g["id"] == group_id)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Удалить группу (аккаунты остаются без группы)."""
    deleted = await group_service.delete_group(db, group_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Группа не найдена")


@router.post("/assign")
async def bulk_assign(
    data: BulkAssignGroup,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Массовое назначение аккаунтов в группу."""
    updated = await group_service.bulk_assign(
        db, data.account_ids, data.group_id, current_user.id
    )
    return {"updated": updated}
