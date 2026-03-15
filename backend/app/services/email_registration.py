"""
Автоматическая регистрация Outlook/Hotmail через Playwright.

Flow:
1. Запуск Chromium (видимый, за экраном)
2. Переход на signup.live.com/signup
3. Ввод email → если занят, добавляем цифры (до 3 попыток)
4. Ввод пароля → Next
5. Ввод имени/фамилии → Next
6. Выбор даты рождения
7. Решение FunCaptcha через 2captcha
8. Если телефон — помечаем ошибку
9. Проверяем IMAP-доступ

Паттерн из steam_browser.py: sync Playwright в ProcessPoolExecutor.
"""

import asyncio
import imaplib
import logging
import random
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

from app.captcha.funcaptcha_solver import FunCaptchaSolver, OUTLOOK_FUNCAPTCHA_PUBLIC_KEY, OUTLOOK_SIGNUP_URL
from app.config import settings
from app.services.profile_generator import (
    generate_email_address,
    generate_email_password,
    generate_first_name,
    generate_last_name,
    generate_birth_date,
)

logger = logging.getLogger(__name__)


@dataclass
class EmailRegStep:
    name: str
    status: str = "pending"   # pending, ok, error
    detail: str | None = None


@dataclass
class EmailRegContext:
    email: str
    password: str
    first_name: str
    last_name: str
    birth_month: int
    birth_day: int
    birth_year: int
    proxy: dict | None = None

    # Результаты
    actual_email: str = ""   # может отличаться если желаемый был занят
    success: bool = False
    error: str | None = None
    steps: list[EmailRegStep] = field(default_factory=list)


def _build_context(
    proxy: dict | None = None,
    email_prefix: str | None = None,
    domain: str = "outlook.com",
) -> EmailRegContext:
    """Генерирует полный контекст для регистрации."""
    if email_prefix:
        num = random.randint(100, 9999)
        email = f"{email_prefix}{num}@{domain}"
    else:
        email = generate_email_address(domain)

    month, day, year = generate_birth_date()
    return EmailRegContext(
        email=email,
        password=generate_email_password(),
        first_name=generate_first_name(),
        last_name=generate_last_name(),
        birth_month=month,
        birth_day=day,
        birth_year=year,
        proxy=proxy,
    )


# ── Async обёртка ────────────────────────────────────────────

async def register_outlook_email(
    proxy: dict | None = None,
    email_prefix: str | None = None,
    domain: str = "outlook.com",
) -> EmailRegContext:
    """
    Регистрирует Outlook-почту в отдельном процессе.

    Args:
        proxy: {"server": "http://host:port", "username": ..., "password": ...}
        email_prefix: если задан, email = prefix+digits@domain
        domain: outlook.com / hotmail.com / live.com

    Returns:
        EmailRegContext с результатами
    """
    ctx = _build_context(proxy, email_prefix, domain)

    loop = asyncio.get_event_loop()
    with ProcessPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(
            pool, _register_outlook_sync, ctx
        )
    return result


# ── Sync реализация (запускается в отдельном процессе) ────────

def _register_outlook_sync(ctx: EmailRegContext) -> EmailRegContext:
    """Sync Playwright: регистрация Outlook."""
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    from playwright.sync_api import sync_playwright

    pw = None
    browser = None

    try:
        pw = sync_playwright().start()

        launch_opts: dict = {
            "headless": False,
            "args": ["--window-position=-32000,-32000"],
        }
        if ctx.proxy:
            launch_opts["proxy"] = ctx.proxy

        browser = pw.chromium.launch(**launch_opts)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = context.new_page()

        # --- Шаг 1: Переход на страницу регистрации ---
        step = EmailRegStep(name="open_signup")
        ctx.steps.append(step)
        try:
            page.goto(OUTLOOK_SIGNUP_URL, wait_until="domcontentloaded", timeout=30000)
            step.status = "ok"
        except Exception as e:
            step.status = "error"
            step.detail = str(e)
            ctx.error = f"Не удалось открыть страницу: {e}"
            return ctx

        # --- Шаг 2: Ввод email ---
        step = EmailRegStep(name="enter_email")
        ctx.steps.append(step)
        try:
            email_input = page.locator('input[type="email"], input[name="MemberName"]').first
            email_input.wait_for(state="visible", timeout=15000)

            actual_email = ctx.email
            for attempt in range(3):
                email_input.fill(actual_email)

                # Нажимаем Next
                next_btn = page.locator('input[type="submit"], button[type="submit"]').first
                next_btn.click()
                time.sleep(2)

                # Проверяем ошибку "email занят"
                error_el = page.locator('#MemberNameError, [id*="error"]').first
                if error_el.count() > 0 and error_el.is_visible():
                    error_text = error_el.text_content() or ""
                    if "already" in error_text.lower() or "taken" in error_text.lower() or "уже" in error_text.lower():
                        # Email занят — генерируем вариацию
                        base = actual_email.split("@")[0]
                        domain = actual_email.split("@")[1]
                        actual_email = f"{base}{random.randint(10, 999)}@{domain}"
                        email_input.clear()
                        continue
                    else:
                        step.status = "error"
                        step.detail = error_text
                        ctx.error = f"Ошибка email: {error_text}"
                        return ctx

                # Успех — перешли на следующий шаг
                ctx.actual_email = actual_email
                step.status = "ok"
                step.detail = actual_email
                break
            else:
                step.status = "error"
                step.detail = "Все варианты email заняты"
                ctx.error = "Не удалось подобрать свободный email"
                return ctx
        except Exception as e:
            step.status = "error"
            step.detail = str(e)
            ctx.error = f"Ошибка ввода email: {e}"
            return ctx

        # --- Шаг 3: Ввод пароля ---
        step = EmailRegStep(name="enter_password")
        ctx.steps.append(step)
        try:
            pwd_input = page.locator('input[type="password"], input[name="Password"]').first
            pwd_input.wait_for(state="visible", timeout=10000)
            pwd_input.fill(ctx.password)

            next_btn = page.locator('input[type="submit"], button[type="submit"]').first
            next_btn.click()
            time.sleep(2)

            step.status = "ok"
        except Exception as e:
            step.status = "error"
            step.detail = str(e)
            ctx.error = f"Ошибка ввода пароля: {e}"
            return ctx

        # --- Шаг 4: Ввод имени/фамилии ---
        step = EmailRegStep(name="enter_name")
        ctx.steps.append(step)
        try:
            first_input = page.locator('input[name="FirstName"], input#FirstName').first
            first_input.wait_for(state="visible", timeout=10000)
            first_input.fill(ctx.first_name)

            last_input = page.locator('input[name="LastName"], input#LastName').first
            last_input.fill(ctx.last_name)

            next_btn = page.locator('input[type="submit"], button[type="submit"]').first
            next_btn.click()
            time.sleep(2)

            step.status = "ok"
        except Exception as e:
            step.status = "error"
            step.detail = str(e)
            ctx.error = f"Ошибка ввода имени: {e}"
            return ctx

        # --- Шаг 5: Дата рождения ---
        step = EmailRegStep(name="enter_birthdate")
        ctx.steps.append(step)
        try:
            # Microsoft использует select-элементы для даты
            month_select = page.locator('select[name="BirthMonth"], select#BirthMonth').first
            month_select.wait_for(state="visible", timeout=10000)
            month_select.select_option(value=str(ctx.birth_month))

            day_select = page.locator('select[name="BirthDay"], select#BirthDay').first
            day_select.select_option(value=str(ctx.birth_day))

            year_select = page.locator('select[name="BirthYear"], select#BirthYear').first
            year_select.select_option(value=str(ctx.birth_year))

            next_btn = page.locator('input[type="submit"], button[type="submit"]').first
            next_btn.click()
            time.sleep(3)

            step.status = "ok"
        except Exception as e:
            step.status = "error"
            step.detail = str(e)
            ctx.error = f"Ошибка ввода даты: {e}"
            return ctx

        # --- Шаг 6: FunCaptcha ---
        step = EmailRegStep(name="solve_captcha")
        ctx.steps.append(step)
        try:
            # Проверяем, появилась ли капча
            captcha_frame = page.locator('iframe[data-e2e="enforcement-frame"], iframe[id*="enforcementFrame"]').first
            if captcha_frame.count() > 0:
                if not settings.FUNCAPTCHA_API_KEY:
                    step.status = "error"
                    step.detail = "FUNCAPTCHA_API_KEY не задан"
                    ctx.error = "Нужен API-ключ для решения FunCaptcha"
                    return ctx

                solver = FunCaptchaSolver(
                    api_key=settings.FUNCAPTCHA_API_KEY,
                    service=settings.FUNCAPTCHA_PROVIDER,
                )
                token = solver.solve(
                    public_key=OUTLOOK_FUNCAPTCHA_PUBLIC_KEY,
                    page_url=OUTLOOK_SIGNUP_URL,
                )

                if not token:
                    step.status = "error"
                    step.detail = "FunCaptcha не решена"
                    ctx.error = "Не удалось решить FunCaptcha"
                    return ctx

                # Вставляем токен через JavaScript
                page.evaluate(f"""
                    var callback = document.querySelector('[data-callback]');
                    if (callback) {{
                        var funcName = callback.getAttribute('data-callback');
                        if (window[funcName]) window[funcName]('{token}');
                    }}
                    // Fallback: устанавливаем через hidden input
                    var inputs = document.querySelectorAll('input[name*="captcha"], input[name*="Solution"]');
                    inputs.forEach(function(inp) {{ inp.value = '{token}'; }});
                """)
                time.sleep(2)

                step.status = "ok"
                step.detail = "FunCaptcha решена"
            else:
                step.status = "ok"
                step.detail = "Капча не появилась"
        except Exception as e:
            step.status = "error"
            step.detail = str(e)
            ctx.error = f"Ошибка капчи: {e}"
            return ctx

        # --- Шаг 7: Проверка на запрос телефона ---
        step = EmailRegStep(name="check_phone")
        ctx.steps.append(step)
        try:
            time.sleep(2)
            phone_el = page.locator(
                'input[type="tel"], '
                'input[name*="Phone"], '
                '[id*="phoneNumber"], '
                '[data-testid*="phone"]'
            ).first

            if phone_el.count() > 0 and phone_el.is_visible():
                step.status = "error"
                step.detail = "Outlook требует телефон"
                ctx.error = "phone_required"
                return ctx

            step.status = "ok"
        except Exception:
            step.status = "ok"  # нет телефона — хорошо

        # --- Шаг 8: Проверяем что регистрация завершена ---
        step = EmailRegStep(name="verify_complete")
        ctx.steps.append(step)
        try:
            # Ждём перехода на страницу приветствия или inbox
            time.sleep(5)
            current_url = page.url.lower()

            if "outlook" in current_url or "office" in current_url or "live" in current_url:
                # Мы на странице Outlook — регистрация успешна
                step.status = "ok"
            else:
                # Пробуем перейти на Outlook
                page.goto("https://outlook.live.com/mail", wait_until="domcontentloaded", timeout=15000)
                time.sleep(3)
                if "login" in page.url.lower() or "signup" in page.url.lower():
                    step.status = "error"
                    step.detail = "Не удалось подтвердить регистрацию"
                    ctx.error = "Регистрация не завершена"
                    return ctx
                step.status = "ok"
        except Exception as e:
            step.status = "error"
            step.detail = str(e)
            ctx.error = f"Ошибка проверки: {e}"
            return ctx

        # --- Шаг 9: Проверяем IMAP-доступ ---
        step = EmailRegStep(name="verify_imap")
        ctx.steps.append(step)
        try:
            imap = imaplib.IMAP4_SSL("imap-mail.outlook.com")
            imap.login(ctx.actual_email, ctx.password)
            imap.logout()
            step.status = "ok"
        except Exception as e:
            step.status = "error"
            step.detail = f"IMAP недоступен: {e}"
            # Не фатально — почта создана, IMAP может заработать позже

        # Успех
        ctx.success = True
        return ctx

    except Exception as e:
        ctx.error = str(e)
        return ctx

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
