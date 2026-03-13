"""
Endpoints аккаунтов: CRUD + импорт из TXT + импорт maFile + открытие в браузере.

Все эндпоинты защищены JWT — требуют авторизации.
Каждый пользователь видит только свои аккаунты (owner_id).
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.proxy import Proxy
from app.api.endpoints.auth import get_current_user
from app.schemas.account import (
    AccountCreate,
    AccountUpdate,
    AccountImportTxt,
    MaFileImport,
    MaFileBatchImport,
    AccountResponse,
    AccountImportResult,
)
from app.services import account_service
from app.services.steam_browser import open_steam_browser
from app.services.steam_guard import get_code_with_ttl
from app.services.encryption import decrypt

router = APIRouter()


@router.get("/", response_model=list[AccountResponse])
async def list_accounts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    group_id: int | None = None,
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Список аккаунтов с фильтрацией и пагинацией."""
    return await account_service.get_accounts(
        db, current_user.id, skip, limit, group_id, status_filter, search
    )


@router.get("/count")
async def accounts_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Общее количество аккаунтов."""
    total = await account_service.count_accounts(db, current_user.id)
    return {"count": total}


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Получить аккаунт по ID."""
    account = await account_service.get_account(db, account_id, current_user.id)
    if not account:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")
    return account


@router.post("/", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    data: AccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создать один аккаунт."""
    return await account_service.create_account(db, data, current_user.id)


@router.put("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: int,
    data: AccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Обновить аккаунт (частично)."""
    account = await account_service.update_account(db, account_id, current_user.id, data)
    if not account:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Удалить аккаунт."""
    deleted = await account_service.delete_account(db, account_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")


@router.post("/import/txt", response_model=AccountImportResult)
async def import_txt(
    data: AccountImportTxt,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Импорт аккаунтов из текста login:password."""
    return await account_service.import_from_txt(
        db, data.content, current_user.id, data.group_id, data.delimiter
    )


@router.post("/import/mafile", response_model=AccountResponse)
async def import_mafile(
    data: MaFileImport,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Импорт одного maFile (JSON). Если аккаунт уже есть — обновляет SteamGuard."""
    account, error = await account_service.import_mafile(
        db, data.mafile_json, current_user.id, data.password, data.group_id
    )
    if error:
        raise HTTPException(status_code=400, detail=error)
    return account


@router.post("/import/mafiles", response_model=AccountImportResult)
async def import_mafiles_batch(
    data: MaFileBatchImport,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Массовый импорт maFiles."""
    return await account_service.import_mafiles_batch(
        db, [f.model_dump() for f in data.files], current_user.id
    )


@router.post("/delete-bulk")
async def delete_bulk(
    account_ids: list[int],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Массовое удаление аккаунтов."""
    deleted = await account_service.delete_accounts_bulk(db, account_ids, current_user.id)
    return {"deleted": deleted}


@router.post("/{account_id}/open-browser")
async def open_browser(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Открыть Steam в браузере с автологином.

    Запускает Playwright-браузер, вводит логин/пароль, 2FA (если есть maFile).
    Браузер открывается в фоне — endpoint сразу возвращает статус.
    """
    account = await account_service.get_account(db, account_id, current_user.id)
    if not account:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")

    # Получаем прокси если привязан
    proxy = None
    if account.proxy_id:
        result = await db.execute(
            select(Proxy).where(Proxy.id == account.proxy_id)
        )
        proxy = result.scalar_one_or_none()

    # Запускаем браузер в фоновой задаче (не блокируем API)
    asyncio.create_task(open_steam_browser(account, proxy))

    return {
        "status": "launched",
        "message": f"Браузер открывается для {account.login}",
        "account_id": account.id,
    }


@router.get("/{account_id}/guard-code")
async def get_guard_code(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Получить текущий Steam Guard код для аккаунта.

    Возвращает 5-символьный код и количество секунд до его истечения.
    Требует наличие shared_secret (maFile).
    """
    account = await account_service.get_account(db, account_id, current_user.id)
    if not account:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")

    shared_secret = decrypt(account.shared_secret_encrypted)
    if not shared_secret:
        raise HTTPException(status_code=400, detail="У аккаунта нет shared_secret (maFile)")

    code, ttl = get_code_with_ttl(shared_secret)
    return {"code": code, "ttl": ttl}


@router.post("/{account_id}/link-guard")
async def link_guard(
    account_id: int,
    email: str | None = None,
    email_password: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Привязать Steam Guard Mobile Authenticator (аналог SDA).

    Полный flow: login → AddAuthenticator → email confirm → Finalize → save maFile.
    Запускает в фоне — endpoint возвращает task_id для отслеживания.
    """
    from app.services.steam_guard_linker import SteamGuardLinker

    account = await account_service.get_account(db, account_id, current_user.id)
    if not account:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")

    if account.shared_secret_encrypted:
        raise HTTPException(status_code=400, detail="Guard уже привязан к этому аккаунту")

    # Расшифровываем пароль Steam
    steam_password = decrypt(account.password_encrypted)
    if not steam_password:
        raise HTTPException(status_code=400, detail="Пароль аккаунта не найден")

    if not email or not email_password:
        raise HTTPException(
            status_code=400,
            detail="Для привязки Guard нужен email и пароль от email (IMAP)",
        )

    # Прокси
    proxy = None
    if account.proxy_id:
        result = await db.execute(select(Proxy).where(Proxy.id == account.proxy_id))
        px = result.scalar_one_or_none()
        if px:
            proxy_str = f"{px.protocol}://{px.host}:{px.port}"
            proxy = {"http": proxy_str, "https": proxy_str}

    # Запускаем линковку (синхронная, долгая — в background task)
    async def _run_link():
        from app.database import async_session

        linker = SteamGuardLinker(proxy=proxy)
        link_result = await linker.link(
            login=account.login,
            password=steam_password,
            email=email,
            email_password=email_password,
        )

        if link_result.success and link_result.mafile:
            async with async_session() as session:
                acc = await account_service.get_account(session, account_id, current_user.id)
                if acc:
                    await account_service.save_guard_mafile(
                        session,
                        acc,
                        mafile_data=link_result.mafile.to_dict(),
                        shared_secret=link_result.mafile.shared_secret,
                        identity_secret=link_result.mafile.identity_secret,
                    )
            logger.info(
                "Guard linked for %s. Revocation: %s",
                account.login, link_result.revocation_code,
            )
        else:
            logger.error(
                "Guard link failed for %s: %s",
                account.login, link_result.error,
            )

        return link_result

    # Для длительной операции — запускаем в фоне
    import logging
    logger = logging.getLogger(__name__)

    asyncio.create_task(_run_link())

    return {
        "status": "started",
        "message": f"Привязка Guard запущена для {account.login}",
        "account_id": account.id,
    }
