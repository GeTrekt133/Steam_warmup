"""
Steam Account Registration Service.

Полный flow регистрации аккаунта через Steam Store API:
1. Получить captcha challenge (refreshcaptcha)
2. Решить hCaptcha через orchestrator
3. Отправить email на подтверждение (ajaxverifyemail)
4. Получить ссылку подтверждения из IMAP
5. Подтвердить email (перейти по ссылке)
6. Создать аккаунт (createaccount)
7. Сохранить в БД
"""

import asyncio
import logging
from dataclasses import dataclass, field
from functools import partial

import requests

from app.services.captcha_orchestrator import CaptchaOrchestrator, get_orchestrator
from app.services.email_service import fetch_confirmation_link_async
from app.services.profile_generator import generate_login, generate_password

logger = logging.getLogger(__name__)

STEAM_STORE = "https://store.steampowered.com"
STEAM_SITEKEY = "f5561ba9-8f1e-40ca-9b5b-a0b3f719ef34"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class RegStep:
    name: str
    status: str = "pending"  # pending, running, done, error
    detail: str | None = None


@dataclass
class RegContext:
    """Контекст регистрации одного аккаунта."""
    email: str
    email_password: str
    login: str
    password: str
    proxy: dict | None = None  # {"http": "...", "https": "..."}

    # Промежуточные данные
    captcha_gid: str = ""
    sitekey: str = STEAM_SITEKEY
    captcha_token: str = ""
    creation_id: str = ""

    # Результат
    success: bool = False
    steam_id: str | None = None
    error: str | None = None
    steps: list[RegStep] = field(default_factory=list)

    def _step(self, name: str) -> RegStep:
        step = RegStep(name=name)
        self.steps.append(step)
        return step


def _create_session(proxy: dict | None = None) -> requests.Session:
    """Создать requests-сессию с правильными заголовками."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/json, text/plain, */*",
    })
    if proxy:
        session.proxies = proxy
    return session


def _step_get_captcha(ctx: RegContext, session: requests.Session) -> None:
    """Шаг 1: Получить captcha GID и sitekey от Steam."""
    step = ctx._step("captcha_init")
    step.status = "running"
    try:
        resp = session.get(
            f"{STEAM_STORE}/join/refreshcaptcha/?count=1",
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        ctx.captcha_gid = str(data.get("gid", ""))
        ctx.sitekey = data.get("sitekey", STEAM_SITEKEY)
        step.status = "done"
        step.detail = f"gid={ctx.captcha_gid}"
        logger.info("Got captcha GID: %s", ctx.captcha_gid)
    except Exception as e:
        step.status = "error"
        step.detail = str(e)
        raise


def _step_verify_email(
    ctx: RegContext, session: requests.Session
) -> None:
    """Шаг 3: Отправить email на подтверждение."""
    step = ctx._step("email_verify")
    step.status = "running"
    try:
        data = {
            "captcha_text": ctx.captcha_token,
            "captchagid": ctx.captcha_gid,
            "email": ctx.email,
        }
        resp = session.post(
            f"{STEAM_STORE}/join/ajaxverifyemail",
            data=data,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info("ajaxverifyemail response: %s", result)

        creation_id = result.get("sessionid") or result.get("creationid", "")
        if not creation_id:
            step.status = "error"
            detail = result.get("details", "Steam не принял email/captcha")
            step.detail = detail
            raise Exception(detail)

        ctx.creation_id = creation_id
        step.status = "done"
        step.detail = f"creationid={creation_id}"
        logger.info("Email verification sent, creationid=%s", creation_id)
    except requests.RequestException as e:
        step.status = "error"
        step.detail = str(e)
        raise


def _step_confirm_email_link(
    ctx: RegContext, session: requests.Session, confirmation_link: str
) -> None:
    """Шаг 5: Перейти по ссылке подтверждения."""
    step = ctx._step("email_confirm")
    step.status = "running"
    try:
        resp = session.get(confirmation_link, timeout=30)
        resp.raise_for_status()
        step.status = "done"
        logger.info("Email confirmed via link")
    except Exception as e:
        step.status = "error"
        step.detail = str(e)
        raise


def _step_create_account(ctx: RegContext, session: requests.Session) -> None:
    """Шаг 6: Создать аккаунт в Steam."""
    step = ctx._step("create_account")
    step.status = "running"
    try:
        data = {
            "accountname": ctx.login,
            "password": ctx.password,
            "count": "32",
            "lt": "0",
            "creation_sessionid": ctx.creation_id,
        }
        resp = session.post(
            f"{STEAM_STORE}/join/createaccount/",
            data=data,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info("createaccount response: %s", result)

        if result.get("bSuccess"):
            ctx.success = True
            ctx.steam_id = str(result.get("steamid", ""))
            step.status = "done"
            step.detail = f"steamid={ctx.steam_id}"
            logger.info("Account created! login=%s steamid=%s", ctx.login, ctx.steam_id)
        else:
            error_msg = result.get("details", {})
            step.status = "error"
            step.detail = str(error_msg)
            raise Exception(f"Steam rejected account creation: {error_msg}")

    except requests.RequestException as e:
        step.status = "error"
        step.detail = str(e)
        raise


async def register_single_account(
    email_with_password: str,
    login: str | None = None,
    password: str | None = None,
    proxy: dict | None = None,
    orchestrator: CaptchaOrchestrator | None = None,
) -> RegContext:
    """
    Зарегистрировать один Steam-аккаунт.

    Args:
        email_with_password: "email@example.com:emailpassword"
        login: логин Steam (если None — генерируется)
        password: пароль Steam (если None — генерируется)
        proxy: {"http": "http://...", "https": "http://..."}
        orchestrator: captcha orchestrator (если None — используется singleton)

    Returns:
        RegContext с результатом и шагами
    """
    # Парсим email
    parts = email_with_password.split(":", 1)
    if len(parts) != 2:
        ctx = RegContext(
            email=email_with_password,
            email_password="",
            login=login or "",
            password=password or "",
        )
        ctx.error = "Неверный формат email. Ожидается: email:password"
        return ctx

    email, email_pass = parts[0].strip(), parts[1].strip()

    ctx = RegContext(
        email=email,
        email_password=email_pass,
        login=login or generate_login(),
        password=password or generate_password(),
        proxy=proxy,
    )

    orchestrator = orchestrator or get_orchestrator()
    loop = asyncio.get_event_loop()
    session = _create_session(proxy)

    try:
        # 1. Получить captcha challenge
        await loop.run_in_executor(None, _step_get_captcha, ctx, session)

        # 2. Решить captcha
        step_captcha = ctx._step("captcha_solve")
        step_captcha.status = "running"
        captcha_result = await orchestrator.solve(ctx.sitekey)
        if not captcha_result.success:
            step_captcha.status = "error"
            step_captcha.detail = captcha_result.error
            ctx.error = f"Captcha не решена: {captcha_result.error}"
            return ctx
        ctx.captcha_token = captcha_result.token
        step_captcha.status = "done"
        step_captcha.detail = f"solver={captcha_result.solver.value}, {captcha_result.elapsed_sec:.1f}s"

        # 3. Отправить email на верификацию
        await loop.run_in_executor(None, _step_verify_email, ctx, session)

        # 4. Получить confirmation link из IMAP
        step_imap = ctx._step("email_fetch")
        step_imap.status = "running"
        confirmation_link = await fetch_confirmation_link_async(
            email, email_pass, ctx.creation_id,
        )
        if not confirmation_link:
            step_imap.status = "error"
            step_imap.detail = "Письмо не найдено"
            ctx.error = "Не удалось получить письмо подтверждения от Steam"
            return ctx
        step_imap.status = "done"

        # 5. Подтвердить email
        await loop.run_in_executor(
            None, _step_confirm_email_link, ctx, session, confirmation_link
        )

        # 6. Создать аккаунт
        await loop.run_in_executor(None, _step_create_account, ctx, session)

    except Exception as e:
        ctx.error = str(e)
        logger.error("Registration failed for %s: %s", email, e)

    return ctx


async def register_batch(
    emails: list[str],
    login_prefix: str | None = None,
    proxy_list: list[dict] | None = None,
    group_id: int | None = None,
    max_concurrent: int = 3,
    orchestrator: CaptchaOrchestrator | None = None,
):
    """
    Массовая регистрация с ограничением параллелизма.

    Yields RegContext по мере завершения.
    """
    orchestrator = orchestrator or get_orchestrator()
    semaphore = asyncio.Semaphore(max_concurrent)
    proxy_index = 0

    async def _register_one(idx: int, email_str: str):
        nonlocal proxy_index
        async with semaphore:
            login = None
            if login_prefix:
                login = f"{login_prefix}_{idx + 1:03d}"

            proxy = None
            if proxy_list:
                proxy = proxy_list[proxy_index % len(proxy_list)]
                proxy_index += 1

            return await register_single_account(
                email_with_password=email_str,
                login=login,
                proxy=proxy,
                orchestrator=orchestrator,
            )

    tasks = [_register_one(i, e) for i, e in enumerate(emails)]
    for coro in asyncio.as_completed(tasks):
        result = await coro
        yield result
