"""
Автоматическая регистрация Outlook/Hotmail через Playwright.

За основу взят подход из DaniilDunguon/Outlook-autoregister-mails:
- Мобильные user-agent'ы (менее подозрительны для Microsoft)
- Стартовый URL: outlook.live.com/owa/?nlp=1&signup=1 → клик «Создать аккаунт»
- WindMouse-подобное движение мыши
- Country dropdown перед датой рождения
- Обработка диалогов «Пропустить»/«Нет»/«Нет, спасибо» после регистрации

Паттерн: sync Playwright в ProcessPoolExecutor (как steam_browser.py).
"""

import asyncio
import imaplib
import logging
import math
import random
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

from app.captcha.funcaptcha_solver import FunCaptchaSolver, OUTLOOK_FUNCAPTCHA_PUBLIC_KEY
from app.config import settings
from app.services.profile_generator import (
    generate_email_address,
    generate_email_password,
    generate_first_name,
    generate_last_name,
    generate_birth_date,
)

logger = logging.getLogger(__name__)

OUTLOOK_ENTRY_URL = "https://outlook.live.com/owa/?nlp=1&signup=1"

# Мобильные/планшетные user-agent'ы (выборка из 800+ как в оригинале)
MOBILE_USER_AGENTS = [
    "Mozilla/5.0 (Android 13; Mobile; rv:131.0) Gecko/131.0 Firefox/131.0",
    "Mozilla/5.0 (Android 14; Mobile; rv:133.0) Gecko/133.0 Firefox/133.0",
    "Mozilla/5.0 (Android 12; Mobile; rv:128.0) Gecko/128.0 Firefox/128.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 YaBrowser/24.7.2.614.11 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Samsung SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Xiaomi 2312DRA50G) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Redmi Note 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Android 15; Mobile; rv:134.0) Gecko/134.0 Firefox/134.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/131.0.6778.134 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; OnePlus Nord 3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_7_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.7.2 Mobile/15E148 Safari/604.1",
]

# Мобильные viewport'ы
MOBILE_VIEWPORTS = [
    {"width": 390, "height": 844},   # iPhone 14
    {"width": 393, "height": 852},   # iPhone 15
    {"width": 412, "height": 915},   # Pixel 7
    {"width": 360, "height": 800},   # Android generic
    {"width": 414, "height": 896},   # iPhone 11
    {"width": 375, "height": 812},   # iPhone X
]


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

    actual_email: str = ""
    success: bool = False
    error: str | None = None
    steps: list[EmailRegStep] = field(default_factory=list)


def _build_context(
    proxy: dict | None = None,
    email_prefix: str | None = None,
    domain: str = "outlook.com",
) -> EmailRegContext:
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
    ctx = _build_context(proxy, email_prefix, domain)
    loop = asyncio.get_event_loop()
    with ProcessPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(pool, _register_outlook_sync, ctx)
    return result


# ── Sync реализация ────────────────────────────────────────

def _wind_mouse_path(start_x, start_y, dest_x, dest_y, G=9, W=3, M=15, D=12):
    """
    WindMouse алгоритм — генерирует реалистичный путь мыши.
    Адаптировано из DaniilDunguon/Outlook-autoregister-mails.
    """
    sqrt3 = math.sqrt(3)
    sqrt5 = math.sqrt(5)
    path = []
    cx, cy = float(start_x), float(start_y)
    vx = vy = wx = wy = 0.0

    while True:
        dist = math.hypot(dest_x - cx, dest_y - cy)
        if dist < 1:
            break
        w_mag = min(W, dist)
        if dist >= D:
            wx = wx / sqrt3 + (2 * random.random() - 1) * w_mag / sqrt5
            wy = wy / sqrt3 + (2 * random.random() - 1) * w_mag / sqrt5
        else:
            wx /= sqrt3
            wy /= sqrt3
            if M < 3:
                M = random.random() * 3 + 3
            else:
                M /= sqrt5
        vx += wx + G * (dest_x - cx) / dist
        vy += wy + G * (dest_y - cy) / dist
        v_mag = math.hypot(vx, vy)
        if v_mag > M:
            clip = M / 2 + random.random() * M / 2
            vx = vx / v_mag * clip
            vy = vy / v_mag * clip
        cx += vx
        cy += vy
        path.append((int(round(cx)), int(round(cy))))

    return path


def _register_outlook_sync(ctx: EmailRegContext) -> EmailRegContext:
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    pw = None
    browser = None

    try:
        pw = sync_playwright().start()

        ua = random.choice(MOBILE_USER_AGENTS)
        viewport = random.choice(MOBILE_VIEWPORTS)

        launch_opts: dict = {
            "headless": False,
            "channel": "chrome",
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                # Отключаем WebRTC — скрываем реальный IP
                "--disable-webrtc",
            ],
        }
        if ctx.proxy:
            launch_opts["proxy"] = ctx.proxy

        browser = pw.chromium.launch(**launch_opts)
        context = browser.new_context(
            viewport=viewport,
            locale="ru-RU",
            user_agent=ua,
            extra_http_headers={
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )
        stealth = Stealth()
        stealth.apply_stealth_sync(context)
        page = context.new_page()

        # ── Вспомогательные функции ──────────────────────────

        def wind_move(dest_x: float, dest_y: float):
            """Реалистичное движение мыши по алгоритму WindMouse."""
            try:
                pos = page.evaluate("() => ({x: window.__mouseX || 100, y: window.__mouseY || 100})")
                sx, sy = pos.get("x", 100), pos.get("y", 100)
            except Exception:
                sx, sy = 100, 100

            path = _wind_mouse_path(sx, sy, dest_x, dest_y)
            for px, py in path:
                page.mouse.move(px, py)
                time.sleep(random.uniform(0.001, 0.004))
            # Запоминаем позицию через JS
            try:
                page.evaluate(f"() => {{ window.__mouseX = {int(dest_x)}; window.__mouseY = {int(dest_y)}; }}")
            except Exception:
                pass

        def human_click(locator, force: bool = False):
            """Кликает с WindMouse-движением мыши. force=True — JS-клик если label перекрывает."""
            try:
                box = locator.bounding_box()
                if box:
                    cx = box["x"] + box["width"] / 2 + random.uniform(-3, 3)
                    cy = box["y"] + box["height"] / 2 + random.uniform(-2, 2)
                    wind_move(cx, cy)
                    time.sleep(random.uniform(0.1, 0.3))
            except Exception:
                pass
            try:
                locator.click(force=force)
            except Exception:
                # Fallback: JS-клик (как в оригинале: driver.execute_script("arguments[0].click()"))
                try:
                    locator.evaluate("el => el.click()")
                except Exception:
                    locator.click(force=True)

        def human_type(locator, text: str, min_delay: int = 60, max_delay: int = 220):
            """Посимвольный ввод с вариативной скоростью."""
            human_click(locator)
            time.sleep(random.uniform(0.2, 0.5))
            locator.fill("")
            time.sleep(random.uniform(0.1, 0.2))
            for char in text:
                locator.type(char, delay=0)
                delay_ms = random.randint(min_delay, max_delay)
                if random.random() < 0.08:
                    delay_ms += random.randint(200, 600)
                time.sleep(delay_ms / 1000)

        def try_skip_dialogs(timeout: int = 5000):
            """Закрывает диалоги 'Пропустить'/'Нет'/'No' которые появляются после регистрации."""
            skip_selectors = [
                'button:has-text("Пропустить")',
                'button:has-text("Skip")',
                'button:has-text("Нет")',
                'button:has-text("No")',
                'button:has-text("Нет, спасибо")',
                'button:has-text("No thanks")',
                'button[type="button"]',
            ]
            for sel in skip_selectors:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible(timeout=timeout):
                        human_click(btn)
                        time.sleep(random.uniform(0.8, 1.5))
                except Exception:
                    pass

        def save_screenshot(name: str):
            try:
                page.screenshot(path=f"d:/frontend/Steam_warmup/debug_{name}.png")
            except Exception:
                pass

        def random_scroll():
            px = random.randint(40, 150)
            page.mouse.wheel(0, px)
            time.sleep(random.uniform(0.3, 0.7))
            page.mouse.wheel(0, -px // 2)
            time.sleep(random.uniform(0.2, 0.5))

        # ── Шаг 1: Открываем Outlook и кликаем «Создать аккаунт» ──

        step = EmailRegStep(name="open_signup")
        ctx.steps.append(step)
        try:
            page.goto(OUTLOOK_ENTRY_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2.5, 4.0))
            save_screenshot("01_entry")

            # Ищем ссылку «Create free account» — она внизу страницы, прокручиваем
            create_link = page.locator(
                'a:has-text("Create free account"), '
                'a:has-text("Создать бесплатную"), '
                'a[aria-label*="Create"], '
                'a[aria-label*="Создать"]'
            ).first

            # Ждём с прокруткой
            found = False
            for _ in range(5):
                if create_link.count() > 0:
                    try:
                        create_link.wait_for(state="visible", timeout=3000)
                        found = True
                        break
                    except Exception:
                        pass
                page.mouse.wheel(0, 200)
                time.sleep(0.8)

            if found:
                # Берём href напрямую как в оригинале
                href = create_link.get_attribute("href") or ""
                logger.info(f"Create account link href: {href}")
                if href and href.startswith("http"):
                    page.goto(href, wait_until="domcontentloaded", timeout=30000)
                else:
                    # Кликаем и ждём навигации
                    with page.expect_navigation(timeout=15000):
                        human_click(create_link)
                time.sleep(random.uniform(2.0, 3.5))
            else:
                # Если ссылка не найдена — идём напрямую на signup URL
                logger.warning("Ссылка 'Create free account' не найдена, идём напрямую на signup")
                page.goto(
                    "https://signup.live.com/signup?lcid=1033&wa=wsignin1.0&rpsnv=17&ct=1731612345&rver=7.0.6738.0&wp=MBI_SSL&wreply=https%3A%2F%2Foutlook.live.com%2Fowa%2F%3Fnlp%3D1%26RpsCsrfState%3Dtest&id=292841&CBCXT=out&lw=1&fl=dob%2Cflname%2Cwld&cobrandid=90015",
                    wait_until="domcontentloaded", timeout=30000
                )
                time.sleep(random.uniform(2.0, 3.0))

            save_screenshot("01_signup_open")
            step.status = "ok"
        except Exception as e:
            step.status = "error"
            step.detail = str(e)
            ctx.error = f"Не удалось открыть страницу: {e}"
            return ctx

        # ── Шаг 2: Ввод email ──

        step = EmailRegStep(name="enter_email")
        ctx.steps.append(step)
        try:
            email_input = page.locator(
                'input[type="email"], input[name="MemberName"], input#usernameInput'
            ).first
            email_input.wait_for(state="visible", timeout=20000)

            actual_email = ctx.email
            for attempt in range(3):
                human_type(email_input, actual_email)
                time.sleep(random.uniform(1.0, 2.0))

                next_btn = page.locator('input[type="submit"], button[type="submit"]').first
                human_click(next_btn)
                save_screenshot("02_after_email")
                time.sleep(random.uniform(2.5, 4.0))

                error_el = page.locator('#MemberNameError, [id*="error"]').first
                if error_el.count() > 0 and error_el.is_visible():
                    error_text = error_el.text_content() or ""
                    if any(w in error_text.lower() for w in ["already", "taken", "уже", "занят"]):
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

        # ── Шаг 3: Ввод пароля ──

        step = EmailRegStep(name="enter_password")
        ctx.steps.append(step)
        try:
            pwd_input = page.locator('input[type="password"], input[name="Password"]').first
            pwd_input.wait_for(state="visible", timeout=12000)
            time.sleep(random.uniform(0.5, 1.2))
            human_type(pwd_input, ctx.password)
            time.sleep(random.uniform(1.0, 2.0))

            next_btn = page.locator('input[type="submit"], button[type="submit"]').first
            human_click(next_btn)
            save_screenshot("03_after_password")
            time.sleep(random.uniform(2.5, 4.0))
            step.status = "ok"
        except Exception as e:
            step.status = "error"
            step.detail = str(e)
            ctx.error = f"Ошибка ввода пароля: {e}"
            return ctx

        # ── Шаг 4: Дата рождения ──

        step = EmailRegStep(name="enter_birthdate")
        ctx.steps.append(step)
        try:
            def open_fluent_dropdown(btn_selector: str) -> bool:
                """Открывает Fluent UI dropdown через JS-клик, ждёт listbox."""
                btn = page.locator(btn_selector).first
                if btn.count() == 0 or not btn.is_visible(timeout=5000):
                    return False
                # Закрываем любой открытый listbox сначала
                try:
                    if page.locator('[role="listbox"]').count() > 0:
                        page.keyboard.press("Escape")
                        time.sleep(0.3)
                except Exception:
                    pass
                btn.evaluate("el => el.click()")
                time.sleep(random.uniform(0.8, 1.5))
                try:
                    page.locator('[role="listbox"]').first.wait_for(state="visible", timeout=5000)
                    return True
                except Exception:
                    return False

            def select_by_index(zero_based_index: int) -> bool:
                """Кликает [role='option'] по индексу (0-based) — надёжнее чем по тексту."""
                opts = page.locator('[role="listbox"] [role="option"]')
                count = opts.count()
                if count == 0:
                    # Иногда опции прямо на странице без listbox-обёртки
                    opts = page.locator('[role="option"]')
                    count = opts.count()
                if count == 0 or zero_based_index >= count:
                    logger.warning(f"select_by_index: нет опций или индекс {zero_based_index} >= {count}")
                    all_texts = opts.all_text_contents()
                    logger.warning(f"Опции: {[t.strip() for t in all_texts[:10]]}")
                    return False
                opt = opts.nth(zero_based_index)
                try:
                    opt.scroll_into_view_if_needed()
                    time.sleep(0.2)
                    opt.evaluate("el => el.click()")
                except Exception:
                    opt.click(force=True)
                time.sleep(random.uniform(0.4, 0.8))
                return True

            # Month (0-based: январь=0, ..., декабрь=11)
            month_btn = page.locator('button[name="BirthMonth"]').first
            if month_btn.count() > 0 and month_btn.is_visible(timeout=5000):
                save_screenshot("04a_before_month")
                if open_fluent_dropdown('button[name="BirthMonth"]'):
                    save_screenshot("04b_month_listbox")
                    select_by_index(ctx.birth_month - 1)  # 1=Jan=index 0
                else:
                    logger.warning("Не удалось открыть Month dropdown")
            else:
                month_select = page.locator('select[name="BirthMonth"]').first
                if month_select.count() > 0:
                    month_select.select_option(value=str(ctx.birth_month))

            time.sleep(random.uniform(0.5, 1.0))

            # Day (0-based: 1=index 0, 2=index 1, ..., 31=index 30)
            day_btn = page.locator('button[name="BirthDay"]').first
            if day_btn.count() > 0 and day_btn.is_visible(timeout=5000):
                save_screenshot("04c_before_day")
                if open_fluent_dropdown('button[name="BirthDay"]'):
                    save_screenshot("04d_day_listbox")
                    select_by_index(ctx.birth_day - 1)  # 1=index 0
                else:
                    logger.warning("Не удалось открыть Day dropdown")
            else:
                day_select = page.locator('select[name="BirthDay"]').first
                if day_select.count() > 0:
                    day_select.select_option(value=str(ctx.birth_day))

            time.sleep(random.uniform(0.5, 1.0))

            # Year input
            year_input = page.locator('input[type="number"], input[name="BirthYear"]').first
            if year_input.count() > 0 and year_input.is_visible(timeout=5000):
                human_type(year_input, str(ctx.birth_year), min_delay=100, max_delay=200)

            save_screenshot("04e_birthdate_filled")
            time.sleep(random.uniform(1.0, 2.0))
            next_btn = page.locator('button[type="submit"], input[type="submit"]').first
            human_click(next_btn)
            save_screenshot("04_after_birthdate")
            time.sleep(random.uniform(2.5, 4.5))
            step.status = "ok"
        except Exception as e:
            step.status = "error"
            step.detail = str(e)
            ctx.error = f"Ошибка ввода даты: {e}"
            return ctx

        # ── Шаг 5: Ввод имени/фамилии ──

        name_input = page.locator(
            'input[name="firstNameInput"], input[id="firstNameInput"], input[name="FirstName"]'
        ).first
        if name_input.count() > 0 and name_input.is_visible(timeout=8000):
            step = EmailRegStep(name="enter_name")
            ctx.steps.append(step)
            try:
                # Оригинал вводит сначала фамилию, потом имя
                last_input = page.locator(
                    'input[name="lastNameInput"], input[id="lastNameInput"], input[name="LastName"]'
                ).first
                if last_input.count() > 0 and last_input.is_visible():
                    human_type(last_input, ctx.last_name)
                    time.sleep(random.uniform(0.5, 1.2))

                human_type(name_input, ctx.first_name)
                time.sleep(random.uniform(1.0, 2.0))

                random_scroll()

                next_btn = page.locator('button[type="submit"], input[type="submit"]').first
                human_click(next_btn)
                save_screenshot("05_after_name")
                time.sleep(random.uniform(4.0, 7.0))

                # Сразу обрабатываем диалоги
                try_skip_dialogs(timeout=3000)

                step.status = "ok"
            except Exception as e:
                step.status = "error"
                step.detail = str(e)
                ctx.error = f"Ошибка ввода имени: {e}"
                return ctx

        # ── Шаг 6: FunCaptcha (если появилась) ──

        step = EmailRegStep(name="solve_captcha")
        ctx.steps.append(step)
        try:
            captcha_frame = page.locator(
                'iframe[data-e2e="enforcement-frame"], iframe[id*="enforcementFrame"]'
            ).first
            if captcha_frame.count() > 0 and captcha_frame.is_visible(timeout=3000):
                funcaptcha_key = settings.FUNCAPTCHA_API_KEY or settings.EZCAPTCHA_API_KEY
                if not funcaptcha_key:
                    step.status = "error"
                    step.detail = "FUNCAPTCHA_API_KEY не задан"
                    ctx.error = "Нужен API-ключ для FunCaptcha"
                    return ctx

                solver = FunCaptchaSolver(
                    api_key=funcaptcha_key,
                    service=settings.FUNCAPTCHA_PROVIDER,
                )
                token = solver.solve(
                    public_key=OUTLOOK_FUNCAPTCHA_PUBLIC_KEY,
                    page_url=OUTLOOK_ENTRY_URL,
                )
                if not token:
                    step.status = "error"
                    step.detail = "FunCaptcha не решена"
                    ctx.error = "Не удалось решить FunCaptcha"
                    return ctx

                page.evaluate(f"""
                    var inputs = document.querySelectorAll('input[name*="captcha"], input[name*="Solution"]');
                    inputs.forEach(function(inp) {{ inp.value = '{token}'; }});
                    var cb = document.querySelector('[data-callback]');
                    if (cb) {{ var fn = cb.getAttribute('data-callback'); if (window[fn]) window[fn]('{token}'); }}
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

        # ── Шаг 7: Диалоги после регистрации ──

        step = EmailRegStep(name="post_dialogs")
        ctx.steps.append(step)
        try:
            time.sleep(random.uniform(2.0, 3.5))
            try_skip_dialogs(timeout=5000)
            time.sleep(random.uniform(1.0, 2.0))
            try_skip_dialogs(timeout=3000)
            save_screenshot("06_after_dialogs")
            step.status = "ok"
        except Exception:
            step.status = "ok"

        # ── Шаг 8: Проверка телефона ──

        step = EmailRegStep(name="check_phone")
        ctx.steps.append(step)
        try:
            phone_el = page.locator(
                'input[type="tel"], input[name*="Phone"], [id*="phoneNumber"]'
            ).first
            if phone_el.count() > 0 and phone_el.is_visible(timeout=3000):
                step.status = "error"
                step.detail = "Outlook требует телефон"
                ctx.error = "phone_required"
                return ctx
            step.status = "ok"
        except Exception:
            step.status = "ok"

        # ── Шаг 9: Проверяем завершение ──

        step = EmailRegStep(name="verify_complete")
        ctx.steps.append(step)
        try:
            time.sleep(3)
            current_url = page.url.lower()
            if any(w in current_url for w in ["outlook", "office", "live.com/mail"]):
                step.status = "ok"
            else:
                page.goto("https://outlook.live.com/mail", wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)
                if any(w in page.url.lower() for w in ["login", "signup", "account.live"]):
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

        # ── Шаг 10: IMAP (не критично) ──

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
            # Не фатально — почта создана, IMAP Microsoft заблокировал Basic Auth

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
