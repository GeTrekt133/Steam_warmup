"""Сервис групп аккаунтов: CRUD + bulk-назначение."""

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.account_group import AccountGroup
from app.schemas.account_group import GroupCreate, GroupUpdate


async def create_group(db: AsyncSession, data: GroupCreate, owner_id: int) -> AccountGroup:
    group = AccountGroup(name=data.name, color=data.color, owner_id=owner_id)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


async def get_group(db: AsyncSession, group_id: int, owner_id: int) -> AccountGroup | None:
    result = await db.execute(
        select(AccountGroup).where(AccountGroup.id == group_id, AccountGroup.owner_id == owner_id)
    )
    return result.scalar_one_or_none()


async def get_groups(db: AsyncSession, owner_id: int) -> list[dict]:
    """Список групп с количеством аккаунтов в каждой."""
    result = await db.execute(
        select(AccountGroup).where(AccountGroup.owner_id == owner_id).order_by(AccountGroup.name)
    )
    groups = list(result.scalars().all())

    # Считаем аккаунты в каждой группе
    counts_result = await db.execute(
        select(Account.group_id, func.count(Account.id))
        .where(Account.owner_id == owner_id, Account.group_id.isnot(None))
        .group_by(Account.group_id)
    )
    counts = dict(counts_result.all())

    return [
        {
            "id": g.id,
            "name": g.name,
            "color": g.color,
            "account_count": counts.get(g.id, 0),
            "created_at": g.created_at,
        }
        for g in groups
    ]


async def update_group(
    db: AsyncSession, group_id: int, owner_id: int, data: GroupUpdate
) -> AccountGroup | None:
    group = await get_group(db, group_id, owner_id)
    if not group:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    await db.commit()
    await db.refresh(group)
    return group


async def delete_group(db: AsyncSession, group_id: int, owner_id: int) -> bool:
    """Удаляет группу. Аккаунты остаются (group_id → NULL через ON DELETE SET NULL)."""
    group = await get_group(db, group_id, owner_id)
    if not group:
        return False
    await db.delete(group)
    await db.commit()
    return True


async def bulk_assign(
    db: AsyncSession, account_ids: list[int], group_id: int | None, owner_id: int
) -> int:
    """Массовое назначение аккаунтов в группу (или снятие если group_id=None)."""
    result = await db.execute(
        update(Account)
        .where(Account.id.in_(account_ids), Account.owner_id == owner_id)
        .values(group_id=group_id)
    )
    await db.commit()
    return result.rowcount
