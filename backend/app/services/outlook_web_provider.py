"""
Outlook Web Provider — получение кодов из Outlook через Playwright (без IMAP).

Обходит ограничение Outlook на IMAP без верификации аккаунта.
Логинится в outlook.live.com, ищет письма от Steam, извлекает код по regex.
"""

import logging
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)


def _ensure_proactor():
    """Windows: переключаем event loop policy для subprocess."""
    import sys
    if sys.platform == "win32":
        import asyncio
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass


def fetch_code_from_outlook_web(
    email: str,
    email_password: str,
    pattern: re.Pattern,
    max_attempts: int = 10,
    wait_sec: int = 5,
    description: str = "code",
) -> str | None:
    """
    Получает код из Outlook через веб-интерфейс (Playwright).

    Логинится в outlook.live.com, проверяет последние письма от Steam,
    ищет код по regex pattern.
    """
    _ensure_proactor()
    pw = None
    browser = None

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=False,
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = context.new_page()

        # === Логин в Outlook ===
        logger.info("[OutlookWeb] %s: логин...", email)
        page.goto("https://login.live.com/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        # Email
        email_input = page.locator('input[type="email"], input[name="loginfmt"]').first
        if email_input.count() > 0:
            email_input.fill(email)
            time.sleep(1)
            # Кнопка Next
            page.locator('input[type="submit"], button[type="submit"]').first.click()
            time.sleep(3)

        # Password
        pwd_input = page.locator('input[type="password"], input[name="passwd"]').first
        if pwd_input.count() > 0 and pwd_input.is_visible():
            pwd_input.fill(email_password)
            time.sleep(1)
            page.locator('input[type="submit"], button[type="submit"]').first.click()
            time.sleep(3)

        # "Stay signed in?" — нажимаем No
        try:
            no_btn = page.locator('input[value="No"], button:has-text("No"), #idBtn_Back').first
            if no_btn.count() > 0 and no_btn.is_visible():
                no_btn.click()
                time.sleep(2)
        except Exception:
            pass

        logger.info("[OutlookWeb] %s: залогинен, URL=%s", email, page.url)

        # === Переходим в Outlook Inbox ===
        page.goto("https://outlook.live.com/mail/0/inbox", wait_until="domcontentloaded", timeout=30000)
        time.sleep(8)  # Outlook SPA грузится очень долго

        # === Ищем письмо от Steam с кодом ===
        for attempt in range(1, max_attempts + 1):
            logger.info(
                "[OutlookWeb] %s: ищем %s (попытка %d/%d)...",
                email, description, attempt, max_attempts,
            )

            # Кликаем на первое письмо от Steam/Valve в списке
            page.evaluate("""
                () => {
                    // Outlook использует div[role="option"] для писем в списке
                    const items = document.querySelectorAll(
                        '[role="option"], [role="listitem"], [data-convid], [class*="customScrollBar"] [role="treeitem"]'
                    );
                    for (const item of items) {
                        const text = item.textContent || '';
                        if (text.includes('Steam') || text.includes('Valve') || text.includes('noreply@steampowered')) {
                            item.click();
                            return true;
                        }
                    }
                    // Кликаем на самое первое письмо
                    if (items.length > 0) {
                        items[0].click();
                        return true;
                    }
                    return false;
                }
            """)
            time.sleep(3)

            # Читаем всё содержимое правой панели (Reading Pane)
            body_text = page.evaluate("""
                () => {
                    // Весь текст страницы — самый надёжный способ
                    return document.body.innerText || '';
                }
            """)

            if body_text:
                match = pattern.search(body_text)
                if match:
                    found_code = match.group(1)
                    logger.info("[OutlookWeb] %s: найден %s: %s", email, description, found_code)
                    return found_code

            # Обновляем inbox и ждём новое письмо
            if attempt < max_attempts:
                page.goto("https://outlook.live.com/mail/0/inbox", wait_until="domcontentloaded", timeout=20000)
                time.sleep(wait_sec)

        logger.error("[OutlookWeb] %s: %s не найден после %d попыток", email, description, max_attempts)
        return None

    except Exception as e:
        logger.error("[OutlookWeb] %s: ошибка — %s", email, e)
        return None

    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                pass
