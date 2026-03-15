"""
CRUD-сервис для EmailAccount.

Сохраняет созданные email-аккаунты, связывает с Steam-аккаунтами.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_account import EmailAccount, EmailStatus
from app.services.encryption import encrypt


async def create_email_account(
    db: AsyncSession,
    email: str,
    password: str,
    owner_id: int,
    provider: str = "outlook",
    status: str = EmailStatus.ACTIVE,
    proxy_id: int | None = None,
    note: str | None = None,
) -> EmailAccount:
    """Создать запись email-аккаунта в БД."""
    account = EmailAccount(
        email=email,
        password_encrypted=encrypt(password),
        provider=provider,
        status=status,
        owner_id=owner_id,
        proxy_id=proxy_id,
        note=note,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def link_to_steam(
    db: AsyncSession,
    email_account_id: int,
    steam_account_id: int,
) -> None:
    """Привязать email-аккаунт к Steam-аккаунту."""
    result = await db.execute(
        select(EmailAccount).where(EmailAccount.id == email_account_id)
    )
    email_acc = result.scalar_one_or_none()
    if email_acc:
        email_acc.steam_account_id = steam_account_id
        await db.commit()


async def get_by_email(db: AsyncSession, email: str) -> EmailAccount | None:
    """Найти email-аккаунт по адресу."""
    result = await db.execute(
        select(EmailAccount).where(EmailAccount.email == email)
    )
    return result.scalar_one_or_none()


async def get_emails(
    db: AsyncSession,
    owner_id: int,
    status: str | None = None,
    limit: int = 100,
) -> list[EmailAccount]:
    """Список email-аккаунтов пользователя."""
    query = select(EmailAccount).where(EmailAccount.owner_id == owner_id)
    if status:
        query = query.where(EmailAccount.status == status)
    query = query.order_by(EmailAccount.id.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())
