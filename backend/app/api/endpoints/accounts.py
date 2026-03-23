"""
Endpoints аккаунтов: CRUD + импорт из TXT + импорт maFile + открытие в браузере + проверка Prime.

Все эндпоинты защищены JWT — требуют авторизации.
Каждый пользователь видит только свои аккаунты (owner_id).
"""

import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
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
from app.services.steam_browser import open_steam_browser, open_steam_browser_raw, fetch_steam_balance, fetch_account_info, check_community_badge, _parse_balance_to_usd
from app.services.steam_guard import get_code_with_ttl, generate_steam_guard_code
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


@router.post("/open-browser-raw")
async def open_browser_raw(
    data: dict,
    current_user: User = Depends(get_current_user),
):
    """
    Открыть Steam в браузере по переданным credentials (без привязки к БД).

    Используется пока аккаунты хранятся на фронте в localStorage.
    Принимает: login, password, shared_secret (опционально).
    """
    login = data.get("login")
    password = data.get("password")
    shared_secret = data.get("shared_secret")

    if not login or not password:
        raise HTTPException(status_code=400, detail="Нужны login и password")

    asyncio.create_task(open_steam_browser_raw(login, password, shared_secret))

    return {
        "status": "launched",
        "message": f"Браузер открывается для {login}",
    }


@router.post("/convert-balances")
async def convert_balances(
    data: dict,
    current_user: User = Depends(get_current_user),
):
    """
    Пересчитывает балансы в USD по актуальному курсу (без логина в Steam).

    Принимает: balances — словарь {account_id: "строка баланса"}.
    Возвращает: {account_id: usd_value}.
    """
    balances: dict = data.get("balances", {})
    result = {}
    for account_id, balance_str in balances.items():
        usd = _parse_balance_to_usd(balance_str) if balance_str else None
        result[account_id] = usd
    return result


@router.post("/parse-balance")
async def parse_balance(
    data: dict,
    current_user: User = Depends(get_current_user),
):
    """
    Логинится в Steam (headless) и возвращает баланс кошелька.

    Принимает: login, password, shared_secret (опционально).
    """
    login = data.get("login")
    password = data.get("password")
    shared_secret = data.get("shared_secret")

    if not login or not password:
        raise HTTPException(status_code=400, detail="Нужны login и password")

    result = await fetch_steam_balance(login, password, shared_secret)
    return {
        "success": result.success,
        "balance": result.balance,
        "balance_usd": result.balance_usd,
        "message": result.message,
        "login": login,
    }


@router.post("/parse-info")
async def parse_info(
    data: dict,
    current_user: User = Depends(get_current_user),
):
    """
    Логинится в Steam и возвращает баланс + Prime статус за один заход.
    """
    login = data.get("login")
    password = data.get("password")
    shared_secret = data.get("shared_secret")

    if not login or not password:
        raise HTTPException(status_code=400, detail="Нужны login и password")

    result = await fetch_account_info(login, password, shared_secret)
    return {
        "success": result.success,
        "balance": result.balance,
        "balance_usd": result.balance_usd,
        "prime": result.prime,
        "message": result.message,
        "login": login,
    }


@router.post("/check-badge")
async def check_badge(
    data: dict,
    current_user: User = Depends(get_current_user),
):
    """
    Проверяет прогресс Community Badge: уровень, XP, выполненные задачи.
    """
    login = data.get("login")
    password = data.get("password")
    shared_secret = data.get("shared_secret")

    if not login or not password:
        raise HTTPException(status_code=400, detail="Нужны login и password")

    result = await check_community_badge(login, password, shared_secret)

    return {
        "success": result.success,
        "login": login,
        "badge_level": result.badge_level,
        "badge_xp": result.badge_xp,
        "tasks_completed": result.tasks_completed,
        "tasks_total": result.tasks_total,
        "tasks": result.tasks,
        "message": result.message,
    }


@router.post("/cs2-profile")
async def cs2_profile(
    data: dict,
    current_user: User = Depends(get_current_user),
):
    """
    Получает CS2 профиль через Game Coordinator: ранг, уровень, XP, VAC бан, Premier.
    Не требует Playwright — подключается к Steam напрямую через протокол.
    """
    from app.services.cs2_gc_service import fetch_cs2_profile

    login = data.get("login")
    password = data.get("password")
    shared_secret = data.get("shared_secret")

    if not login or not password:
        raise HTTPException(status_code=400, detail="Нужны login и password")

    profile = await fetch_cs2_profile(login, password, shared_secret)

    logger.info(f"[CS2 Profile] {login}: success={profile.error is None}, "
                f"level={profile.player_level}, xp={profile.player_cur_xp}, "
                f"vac={profile.vac_banned}, premier={profile.premier_rank}, "
                f"error={profile.error}")

    return {
        "success": profile.error is None,
        "login": login,
        "vac_banned": profile.vac_banned,
        "penalty_reason": profile.penalty_reason,
        "penalty_seconds": profile.penalty_seconds,
        "player_level": profile.player_level,
        "player_cur_xp": profile.player_cur_xp,
        "mm_rank": profile.mm_rank,
        "mm_wins": profile.mm_wins,
        "premier_rank": profile.premier_rank,
        "error": profile.error,
    }


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


# ─── Batch привязка Steam Guard ─────────────────────────────────

logger = logging.getLogger(__name__)


class LinkGuardItem(BaseModel):
    login: str
    password: str
    email: str
    email_password: str


class LinkGuardBatchRequest(BaseModel):
    accounts: list[LinkGuardItem]


@router.post("/link-guard-batch")
async def link_guard_batch(
    data: LinkGuardBatchRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Привязать Steam Guard для списка аккаунтов (из localStorage).
    Последовательно — IMAP не любит параллельные подключения.
    Возвращает результат для каждого аккаунта.
    """
    from app.services.steam_guard_linker import SteamGuardLinker

    if not data.accounts:
        raise HTTPException(status_code=400, detail="Список аккаунтов пуст")

    if len(data.accounts) > 20:
        raise HTTPException(status_code=400, detail="Максимум 20 аккаунтов за раз")

    results = []

    for acc in data.accounts:
        try:
            linker = SteamGuardLinker()
            link_result = await linker.link(
                login=acc.login,
                password=acc.password,
                email=acc.email,
                email_password=acc.email_password,
            )

            if link_result.success and link_result.mafile:
                results.append({
                    "login": acc.login,
                    "success": True,
                    "revocation_code": link_result.revocation_code,
                    "shared_secret": link_result.mafile.shared_secret,
                    "identity_secret": link_result.mafile.identity_secret,
                    "mafile_json": link_result.mafile.to_json(),
                    "steam_id": link_result.mafile.steam_id,
                    "error": None,
                })
                logger.info(f"[LinkGuard] {acc.login}: OK, revocation={link_result.revocation_code}")
            else:
                results.append({
                    "login": acc.login,
                    "success": False,
                    "revocation_code": None,
                    "shared_secret": None,
                    "identity_secret": None,
                    "mafile_json": None,
                    "steam_id": None,
                    "error": link_result.error or "Unknown error",
                })
                logger.error(f"[LinkGuard] {acc.login}: FAIL — {link_result.error}")

        except Exception as e:
            results.append({
                "login": acc.login,
                "success": False,
                "revocation_code": None,
                "shared_secret": None,
                "identity_secret": None,
                "mafile_json": None,
                "steam_id": None,
                "error": str(e)[:300],
            })
            logger.error(f"[LinkGuard] {acc.login}: EXCEPTION — {e}")

    return {"results": results}


# ─── Проверка CS2 Prime статуса ─────────────────────────────────


class PrimeCheckAccount(BaseModel):
    login: str
    password: str
    shared_secret: str | None = None


class PrimeCheckRequest(BaseModel):
    accounts: list[PrimeCheckAccount]


class PrimeCheckResult(BaseModel):
    login: str
    prime: bool | None = None  # None = ошибка проверки
    error: str | None = None


class PrimeCheckResponse(BaseModel):
    results: list[PrimeCheckResult]


def _check_prime_sync(login: str, password: str, shared_secret: str | None) -> PrimeCheckResult:
    """
    Sync Playwright — проверяет CS2 Prime статус.
    Запускается в отдельном потоке через asyncio.to_thread().
    """
    import time
    from playwright.sync_api import sync_playwright
    from app.services.steam_browser import _ensure_proactor

    _ensure_proactor()
    pw = None
    browser = None

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 720}, locale="en-US")
        page = context.new_page()

        # ─── Логин ───
        page.goto("https://store.steampowered.com/login", wait_until="domcontentloaded", timeout=30000)
        login_form = page.locator('[data-featuretarget="login"]')
        login_form.wait_for(state="visible", timeout=15000)

        login_input = login_form.locator('input[type="text"]').first
        login_input.wait_for(state="visible", timeout=10000)
        login_input.fill(login)

        password_input = login_form.locator('input[type="password"]').first
        password_input.fill(password)

        submit_btn = login_form.locator('button[type="submit"]').first
        submit_btn.click()
        time.sleep(3)

        # 2FA
        if shared_secret:
            code = generate_steam_guard_code(shared_secret)
            logger.info(f"[Prime] {login}: 2FA код {code}")
            char_inputs = page.locator('input[maxlength="1"][type="text"]')
            count = char_inputs.count()
            if count >= 5:
                for i in range(5):
                    char_inputs.nth(i).click()
                    char_inputs.nth(i).fill(code[i])
                    time.sleep(0.1)
                time.sleep(3)

        page.wait_for_load_state("networkidle", timeout=15000)
        logger.info(f"[Prime] {login}: залогинен, URL={page.url}")

        # ─── Проверяем Prime через лицензии ───
        page.goto("https://store.steampowered.com/account/licenses/",
                   wait_until="domcontentloaded", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)
        time.sleep(2)

        page_content = page.content()
        # Prime Status Upgrade = Sub 303386 или упоминание "Prime Status" в лицензиях
        prime = (
            "Prime Status Upgrade" in page_content
            or "Counter-Strike 2 Prime" in page_content
            or "CS:GO Prime" in page_content
        )
        logger.info(f"[Prime] {login}: prime={prime}")
        return PrimeCheckResult(login=login, prime=prime)

    except Exception as e:
        logger.error(f"[Prime] {login}: ошибка — {e}")
        return PrimeCheckResult(login=login, prime=None, error=str(e)[:200])

    finally:
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        try:
            if pw:
                pw.stop()
        except Exception:
            pass


async def _check_prime_for_account(login: str, password: str, shared_secret: str | None) -> PrimeCheckResult:
    """Запускает sync Playwright в отдельном потоке."""
    import asyncio
    return await asyncio.to_thread(_check_prime_sync, login, password, shared_secret)


@router.post("/check-prime", response_model=PrimeCheckResponse)
async def check_prime(
    data: PrimeCheckRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Проверка CS2 Prime статуса для списка аккаунтов.

    Для каждого аккаунта логинится в Steam (headless Playwright),
    переходит на страницу CS2 и проверяет наличие кнопки «Upgrade to Prime».
    """
    if not data.accounts:
        raise HTTPException(status_code=400, detail="Список аккаунтов пуст")

    if len(data.accounts) > 50:
        raise HTTPException(status_code=400, detail="Максимум 50 аккаунтов за раз")

    # Проверяем аккаунты последовательно (чтобы не перегружать систему)
    results: list[PrimeCheckResult] = []
    for acc in data.accounts:
        result = await _check_prime_for_account(acc.login, acc.password, acc.shared_secret)
        results.append(result)

    return PrimeCheckResponse(results=results)
