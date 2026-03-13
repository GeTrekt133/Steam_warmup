"""
Открытие Steam в Playwright-браузере с автологином.

Логика:
1. Запускает Chromium (видимый, не headless)
2. Настраивает прокси если привязан к аккаунту
3. Переходит на store.steampowered.com/login
4. Вводит логин/пароль
5. Если есть shared_secret — автоматически вводит 2FA код
6. Оставляет браузер открытым для пользователя

Браузер закрывается, когда пользователь закроет окно.
"""

import asyncio
import logging
from dataclasses import dataclass

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from app.models.account import Account
from app.models.proxy import Proxy
from app.services.encryption import decrypt
from app.services.steam_guard import generate_steam_guard_code

logger = logging.getLogger(__name__)

STEAM_LOGIN_URL = "https://store.steampowered.com/login"


@dataclass
class BrowserResult:
    success: bool
    message: str


def _build_proxy_config(proxy: Proxy) -> dict:
    """Формирует конфиг прокси для Playwright."""
    server = f"{proxy.protocol}://{proxy.host}:{proxy.port}"
    config = {"server": server}
    if proxy.username:
        config["username"] = proxy.username
    if proxy.password:
        config["password"] = proxy.password
    return config


async def open_steam_browser(account: Account, proxy: Proxy | None = None) -> BrowserResult:
    """
    Открывает браузер, логинится в Steam, оставляет открытым.

    Запускается в фоновой задаче — не блокирует API.
    Возвращает BrowserResult после завершения логина (или ошибки).
    """
    login = account.login
    password = decrypt(account.password_encrypted)
    shared_secret = decrypt(account.shared_secret_encrypted)

    if not password:
        return BrowserResult(success=False, message="Пароль аккаунта пуст")

    pw = None
    browser: Browser | None = None

    try:
        pw = await async_playwright().start()

        # Настройка прокси
        launch_opts: dict = {"headless": False}
        if proxy:
            launch_opts["proxy"] = _build_proxy_config(proxy)

        browser = await pw.chromium.launch(**launch_opts)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ru-RU",
        )
        page = await context.new_page()

        # Переходим на страницу логина
        await page.goto(STEAM_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)

        # Steam New Login — ждём поле ввода логина
        login_input = page.locator('input[type="text"]._2GBWeup5cttgbTw8FM3tfx')
        # Fallback: ищем по более надёжному селектору
        if not await login_input.count():
            login_input = page.locator('input[type="text"]').first

        await login_input.wait_for(state="visible", timeout=15000)
        await login_input.fill(login)

        # Вводим пароль
        password_input = page.locator('input[type="password"]').first
        await password_input.fill(password)

        # Нажимаем "Войти"
        submit_btn = page.locator('button[type="submit"]').first
        await submit_btn.click()

        # Ждём: либо 2FA, либо сразу профиль, либо ошибка
        try:
            # Ждём появления поля 2FA или перехода на главную
            await page.wait_for_selector(
                'input[type="text"].newlogindialog_SegmentedCharacterInput_1kJ6q, '
                'input.newlogindialog_SegmentedCharacterInput_1kJ6q, '
                '[class*="SegmentedCharacterInput"], '
                '[class*="newlogindialog_FailureTitle"]',
                timeout=15000,
            )
        except Exception:
            # Возможно уже залогинились (нет 2FA)
            pass

        # Проверяем ошибку логина
        error_el = page.locator('[class*="newlogindialog_FailureTitle"]')
        if await error_el.count() > 0:
            error_text = await error_el.text_content()
            return BrowserResult(
                success=False,
                message=f"Ошибка входа Steam: {error_text}",
            )

        # Вводим 2FA если есть shared_secret
        guard_input = page.locator('[class*="SegmentedCharacterInput"] input, input[class*="SegmentedCharacterInput"]')
        if shared_secret and await guard_input.count() > 0:
            code = generate_steam_guard_code(shared_secret)
            logger.info("Вводим Steam Guard код для %s", login)

            # Steam Guard использует несколько отдельных input-полей (по 1 символу)
            char_inputs = page.locator('[class*="SegmentedCharacterInput"] input[type="text"]')
            count = await char_inputs.count()
            if count >= 5:
                for i in range(5):
                    await char_inputs.nth(i).fill(code[i])
                    await asyncio.sleep(0.05)
            else:
                # Fallback: вставляем код целиком в первый input
                first_input = char_inputs.first
                await first_input.fill(code)

            # Ждём завершения авторизации
            await asyncio.sleep(2)

        logger.info("Браузер открыт для аккаунта %s — ждём закрытия окна", login)

        # Ждём пока пользователь закроет браузер
        try:
            await page.wait_for_event("close", timeout=0)
        except Exception:
            pass

        # Ждём закрытия всех страниц
        while len(context.pages) > 0:
            await asyncio.sleep(1)

        return BrowserResult(success=True, message="Браузер закрыт пользователем")

    except Exception as e:
        logger.exception("Ошибка при открытии браузера для %s", login)
        return BrowserResult(success=False, message=str(e))

    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        if pw:
            try:
                await pw.stop()
            except Exception:
                pass
