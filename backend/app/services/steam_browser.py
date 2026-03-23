"""
Открытие Steam в Playwright-браузере с автологином.

Логика:
1. Запускает Chromium (видимый, не headless)
2. Настраивает прокси если привязан к аккаунту
3. Переходит на store.steampowered.com/login
4. Вводит логин/пароль
5. Если есть shared_secret — автоматически вводит 2FA код
6. Парсит баланс кошелька
7. Оставляет браузер открытым (open-browser) или закрывает (parse-balance)

Playwright запускается через sync API в отдельном потоке,
т.к. на Windows asyncio event loop не поддерживает subprocess_exec.
"""

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from playwright.sync_api import sync_playwright

from app.models.account import Account
from app.models.proxy import Proxy
from app.services.encryption import decrypt
from app.services.steam_guard import generate_steam_guard_code

logger = logging.getLogger(__name__)

STEAM_LOGIN_URL = "https://store.steampowered.com/login"

# ── Курсы валют (онлайн + кэш на 24ч + fallback) ─────────────

# Маппинг символов/обозначений Steam → ISO-код валюты.
# Порядок важен: длинные обозначения первыми, "$" последним.
STEAM_SYMBOL_TO_ISO: list[tuple[str, str]] = [
    ("CDN$", "CAD"),
    ("ARS$", "ARS"),
    ("CLP$", "CLP"),
    ("COL$", "COP"),
    ("MX$", "MXN"),
    ("NZ$", "NZD"),
    ("HK$", "HKD"),
    ("NT$", "TWD"),
    ("S$", "SGD"),
    ("A$", "AUD"),
    ("R$", "BRL"),
    ("руб", "RUB"),
    ("pуб", "RUB"),   # латинская p
    ("USD", "USD"),
    ("CHF", "CHF"),
    ("S/.", "PEN"),
    ("S/", "PEN"),
    ("RM", "MYR"),
    ("TL", "TRY"),
    ("kr", "NOK"),     # NOK/SEK/DKK — усреднённо через NOK
    ("zł", "PLN"),
    ("Rp", "IDR"),
    ("₽", "RUB"),
    ("€", "EUR"),
    ("£", "GBP"),
    ("¥", "CNY"),
    ("₸", "KZT"),
    ("₴", "UAH"),
    ("₹", "INR"),
    ("₡", "CRC"),
    ("₩", "KRW"),
    ("฿", "THB"),
    ("₫", "VND"),
    ("₱", "PHP"),
    ("₺", "TRY"),
    ("R", "ZAR"),
    ("$", "USD"),
]

# Fallback-курсы на случай если API недоступен
_FALLBACK_RATES: dict[str, float] = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "RUB": 0.011, "KZT": 0.002,
    "UAH": 0.024, "BRL": 0.17, "CAD": 0.73, "AUD": 0.65, "NZD": 0.60,
    "HKD": 0.128, "TWD": 0.031, "SGD": 0.75, "MXN": 0.055, "ARS": 0.001,
    "CLP": 0.001, "COP": 0.00023, "PEN": 0.27, "MYR": 0.22, "TRY": 0.029,
    "NOK": 0.093, "PLN": 0.25, "IDR": 0.000061, "CNY": 0.14, "JPY": 0.0069,
    "INR": 0.012, "CRC": 0.002, "KRW": 0.00073, "THB": 0.029, "VND": 0.000039,
    "PHP": 0.017, "ZAR": 0.054, "CHF": 1.13,
}

# Кэш: {ISO_код: курс_к_USD}
_rates_cache: dict[str, float] = {}
_rates_fetched_at: datetime | None = None
_CACHE_TTL_SECONDS = 86400  # 24 часа


def _get_rates() -> dict[str, float]:
    """Возвращает актуальные курсы. Обновляет из API раз в сутки."""
    global _rates_cache, _rates_fetched_at

    now = datetime.now(timezone.utc)
    if _rates_cache and _rates_fetched_at and (now - _rates_fetched_at).total_seconds() < _CACHE_TTL_SECONDS:
        return _rates_cache

    try:
        resp = httpx.get(
            "https://open.er-api.com/v6/latest/USD",
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") == "success" and "rates" in data:
            # API возвращает сколько единиц валюты за 1 USD,
            # нам нужно обратное: сколько USD за 1 единицу валюты
            _rates_cache = {
                code: round(1.0 / rate, 8)
                for code, rate in data["rates"].items()
                if rate > 0
            }
            _rates_fetched_at = now
            logger.info("Курсы валют обновлены: %d валют", len(_rates_cache))
            return _rates_cache
    except Exception as e:
        logger.warning("Не удалось загрузить курсы валют: %s, используем fallback", e)

    # Fallback
    if not _rates_cache:
        _rates_cache = _FALLBACK_RATES.copy()
        _rates_fetched_at = now
    return _rates_cache


@dataclass
class BrowserResult:
    success: bool
    message: str
    balance: str | None = None
    balance_usd: float | None = None


def _build_proxy_config(proxy: Proxy) -> dict:
    """Формирует конфиг прокси для Playwright."""
    server = f"{proxy.protocol}://{proxy.host}:{proxy.port}"
    config = {"server": server}
    if proxy.username:
        config["username"] = proxy.username
    if proxy.password:
        config["password"] = proxy.password
    return config


def _ensure_proactor():
    """Windows: устанавливаем ProactorEventLoop и создаём свежий event loop в потоке.

    Playwright sync API вызывает asyncio.get_running_loop(). В чистом threading.Thread
    там нет running loop → RuntimeError → Playwright создаёт свой loop. Всё ок.
    Но на Windows нужен ProactorEventLoop для subprocess, поэтому выставляем политику.
    """
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    # Явно создаём и устанавливаем новый (не запущенный) loop для этого потока,
    # чтобы asyncio.get_event_loop() не вернул чужой loop из другого потока.
    asyncio.set_event_loop(asyncio.new_event_loop())


async def _run_in_clean_thread(func, *args):
    """Запускает func в чистом threading.Thread без asyncio-контекста.

    asyncio.to_thread() и loop.run_in_executor() оба используют ctx.run(),
    который копирует contextvars (включая running loop в Python 3.12+).
    Playwright видит running loop и падает.
    Прямой threading.Thread не наследует asyncio-контекст — Playwright работает.
    """
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()

    def target():
        try:
            result = func(*args)
            loop.call_soon_threadsafe(fut.set_result, result)
        except Exception as exc:
            loop.call_soon_threadsafe(fut.set_exception, exc)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return await fut


def _parse_balance_to_usd(balance_str: str) -> float | None:
    """Парсит строку баланса и конвертирует в USD."""
    if not balance_str:
        return None

    # Убираем неразрывные пробелы и обычные (разделители тысяч)
    cleaned = balance_str.replace('\xa0', ' ').strip()

    # Извлекаем число: поддерживаем "1 234,56" и "1,234.56"
    # Если есть и запятая и точка — определяем формат по позиции
    num_match = re.search(r'[\d\s.,]+', cleaned)
    if not num_match:
        return None

    num_str = num_match.group().strip()

    # Определяем десятичный разделитель
    if ',' in num_str and '.' in num_str:
        # Оба символа: последний — десятичный
        if num_str.rfind(',') > num_str.rfind('.'):
            # 1.234,56 → европейский
            num_str = num_str.replace('.', '').replace(',', '.')
        else:
            # 1,234.56 → американский
            num_str = num_str.replace(',', '')
    elif ',' in num_str:
        # Только запятая: если после неё 2 цифры в конце — десятичный
        parts = num_str.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            num_str = num_str.replace(',', '.')
        else:
            num_str = num_str.replace(',', '')
    # Убираем пробелы (разделители тысяч)
    num_str = num_str.replace(' ', '')

    try:
        amount = float(num_str)
    except ValueError:
        return None

    # Определяем валюту (порядок важен — длинные обозначения первыми)
    rates = _get_rates()
    for symbol, iso_code in STEAM_SYMBOL_TO_ISO:
        if symbol in cleaned:
            rate = rates.get(iso_code, _FALLBACK_RATES.get(iso_code, 1.0))
            return round(amount * rate, 2)

    # Если валюта не определена — считаем USD
    return round(amount, 2)


# ── Логин в Steam ────────────────────────────────────────────

def _steam_login(page, login: str, password: str, shared_secret: str | None) -> str | None:
    """Общая логика логина в Steam. Возвращает строку баланса или None."""
    page.goto(STEAM_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)

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
        logger.info("Сгенерирован Steam Guard код для %s: %s", login, code)

        char_inputs = page.locator('input[maxlength="1"][type="text"]')
        count = char_inputs.count()

        if count >= 5:
            logger.info("Найдены %d ячеек 2FA, вводим посимвольно", count)
            for i in range(5):
                char_inputs.nth(i).click()
                char_inputs.nth(i).fill(code[i])
                time.sleep(0.1)
            logger.info("2FA код введён для %s", login)
            time.sleep(3)
        else:
            logger.warning("Не найдены ячейки 2FA (найдено %d), пропускаем", count)

    # Парсим баланс
    balance = _parse_balance(page)
    if balance:
        logger.info("Баланс аккаунта %s: %s", login, balance)

    return balance


def _parse_balance(page) -> str | None:
    """Парсит баланс кошелька со страницы Steam Store."""
    try:
        page.goto("https://store.steampowered.com/", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)

        logger.info("Парсинг баланса, URL: %s", page.url)

        selectors = [
            '#header_wallet_balance',
            'a#header_wallet_balance',
            '[class*="wallet_balance"]',
            'a[href*="/account/"] >> text=/\\d/',
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    text = el.text_content()
                    logger.info("Селектор '%s' → текст: '%s'", sel, text)
                    if text and re.search(r'\d', text):
                        return text.strip()
            except Exception as e:
                logger.debug("Селектор '%s' не сработал: %s", sel, e)
                continue

        return None
    except Exception as e:
        logger.warning("Не удалось распарсить баланс: %s", e)
        return None


# ── Открытие браузера (остаётся открытым) ─────────────────────

async def open_steam_browser_raw(
    login: str,
    password: str,
    shared_secret: str | None = None,
) -> BrowserResult:
    """Открывает браузер с credentials напрямую (без модели Account)."""
    if not password:
        return BrowserResult(success=False, message="Пароль аккаунта пуст")
    return await _run_in_clean_thread(
        _open_browser_sync, login, password, shared_secret
    )


async def open_steam_browser(account: Account, proxy: Proxy | None = None) -> BrowserResult:
    """Открывает браузер, логинится в Steam, оставляет открытым."""
    login = account.login
    password = decrypt(account.password_encrypted)
    shared_secret = decrypt(account.shared_secret_encrypted)

    if not password:
        return BrowserResult(success=False, message="Пароль аккаунта пуст")

    proxy_config = _build_proxy_config(proxy) if proxy else None
    return await _run_in_clean_thread(
        _open_browser_sync, login, password, shared_secret, proxy_config
    )


def _open_browser_sync(
    login: str,
    password: str,
    shared_secret: str | None = None,
    proxy_config: dict | None = None,
) -> BrowserResult:
    """Логин + парсинг баланса. Браузер отключается от Playwright и остаётся открытым."""
    _ensure_proactor()

    pw = None
    browser = None

    try:
        pw = sync_playwright().start()

        launch_opts: dict = {"headless": False}
        if proxy_config:
            launch_opts["proxy"] = proxy_config

        browser = pw.chromium.launch(**launch_opts)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ru-RU",
        )
        page = context.new_page()

        balance = _steam_login(page, login, password, shared_secret)
        balance_usd = _parse_balance_to_usd(balance) if balance else None

        logger.info("Браузер открыт для %s, баланс: %s ($%s)", login, balance, balance_usd)

        # Отключаемся от browser через CDP — браузер останется открытым,
        # Playwright освободит поток и не зависнет при сворачивании
        # Получаем CDP endpoint и просто закрываем соединение
        browser = None  # не закрываем в finally
        pw = None        # не останавливаем в finally

        return BrowserResult(
            success=True,
            message="Браузер открыт",
            balance=balance,
            balance_usd=balance_usd,
        )

    except Exception as e:
        logger.exception("Ошибка при открытии браузера для %s", login)
        return BrowserResult(success=False, message=str(e))

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


# ── Парсинг баланса (браузер закрывается после парсинга) ──────

async def fetch_steam_balance(
    login: str,
    password: str,
    shared_secret: str | None = None,
) -> BrowserResult:
    """Запускает парсинг баланса в чистом потоке (избегаем конфликт event loop)."""
    if not password:
        return BrowserResult(success=False, message="Пароль пуст")
    return await _run_in_clean_thread(_fetch_balance_sync, login, password, shared_secret)


def _fetch_balance_sync(
    login: str,
    password: str,
    shared_secret: str | None = None,
) -> BrowserResult:
    """Sync: видимый браузер → логин → баланс → закрытие. Запускается в отдельном процессе."""
    _ensure_proactor()

    pw = None
    browser = None

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=False,
            args=["--window-position=-32000,-32000"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ru-RU",
        )
        page = context.new_page()

        balance = _steam_login(page, login, password, shared_secret)
        balance_usd = _parse_balance_to_usd(balance) if balance else None

        if balance:
            return BrowserResult(success=True, message="OK", balance=balance, balance_usd=balance_usd)
        else:
            return BrowserResult(success=False, message="Баланс не найден")

    except Exception as e:
        # Не используем logger — это отдельный процесс
        import traceback
        traceback.print_exc()
        return BrowserResult(success=False, message=str(e))

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


# ── Комбинированный парсинг: баланс + прайм ──────────────────

@dataclass
class AccountInfoResult:
    success: bool
    balance: str | None = None
    balance_usd: float | None = None
    prime: bool | None = None
    message: str = ""


def _fetch_account_info_sync(
    login: str,
    password: str,
    shared_secret: str | None = None,
) -> AccountInfoResult:
    """Sync: логин → баланс → проверка прайма через лицензии → закрытие."""
    _ensure_proactor()
    pw_inst = None
    br = None
    try:
        pw_inst = sync_playwright().start()
        br = pw_inst.chromium.launch(
            headless=False,
            args=["--window-position=-32000,-32000"],
        )
        ctx = br.new_context(viewport={"width": 1280, "height": 800}, locale="ru-RU")
        pg = ctx.new_page()

        balance = _steam_login(pg, login, password, shared_secret)
        balance_usd = _parse_balance_to_usd(balance) if balance else None

        prime = None
        try:
            pg.goto("https://store.steampowered.com/account/licenses/",
                     wait_until="domcontentloaded", timeout=15000)
            pg.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(1)
            content = pg.content()
            prime = (
                "Prime Status Upgrade" in content
                or "Counter-Strike 2 Prime" in content
                or "CS:GO Prime" in content
            )
            logger.info("[AccountInfo] %s: prime=%s", login, prime)
        except Exception as e:
            logger.warning("[AccountInfo] %s: ошибка прайма: %s", login, e)

        return AccountInfoResult(
            success=True, message="OK",
            balance=balance, balance_usd=balance_usd, prime=prime,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return AccountInfoResult(success=False, message=str(e))
    finally:
        if br:
            try:
                br.close()
            except Exception:
                pass
        if pw_inst:
            try:
                pw_inst.stop()
            except Exception:
                pass


async def fetch_account_info(
    login: str, password: str, shared_secret: str | None = None,
) -> AccountInfoResult:
    """Запускает парсинг баланса + прайма в чистом потоке."""
    if not password:
        return AccountInfoResult(success=False, message="Пароль пуст")
    return await _run_in_clean_thread(_fetch_account_info_sync, login, password, shared_secret)


# ── Проверка Community Badge ─────────────────────────────────

@dataclass
class BadgeCheckResult:
    success: bool
    badge_level: int = 0
    badge_xp: int = 0
    tasks_completed: int = 0
    tasks_total: int = 0
    tasks: list = None  # [{name, completed}]
    message: str = ""

    def __post_init__(self):
        if self.tasks is None:
            self.tasks = []


def _check_badge_sync(
    login: str,
    password: str,
    shared_secret: str | None = None,
) -> BadgeCheckResult:
    """Sync: логин → страница бейджа → парсинг прогресса."""
    _ensure_proactor()
    pw_b = None
    br_b = None
    try:
        pw_b = sync_playwright().start()
        br_b = pw_b.chromium.launch(
            headless=False,
            args=["--window-position=-32000,-32000"],
        )
        ctx = br_b.new_context(viewport={"width": 1280, "height": 800}, locale="en-US")
        pg = ctx.new_page()

        _steam_login(pg, login, password, shared_secret)

        # Переходим на страницу Community Badge
        pg.goto("https://steamcommunity.com/my/badges/2?l=english",
                wait_until="domcontentloaded", timeout=20000)
        pg.wait_for_load_state("networkidle", timeout=15000)
        time.sleep(2)

        # Сохраняем HTML для диагностики
        try:
            from pathlib import Path as _Path
            html = pg.content()
            dump_dir = _Path(__file__).parent.parent.parent / "error_dumps"
            dump_dir.mkdir(exist_ok=True)
            dump_path = dump_dir / f"badge_{login}.html"
            dump_path.write_text(html[:500000], encoding="utf-8")
            logger.info(f"[Badge] {login}: HTML сохранён в {dump_path}")
        except Exception as e:
            logger.warning(f"[Badge] {login}: не удалось сохранить HTML: {e}")

        # Парсим задачи и прогресс через JS
        data = pg.evaluate("""
            () => {
                const result = {
                    badge_level: 0,
                    badge_xp: 0,
                    tasks: [],
                    tasks_completed: 0,
                    tasks_total: 0,
                };

                // Уровень бейджа — ищем в тексте страницы
                const body = document.body.innerText;
                if (body.includes('Community Patron')) result.badge_level = 4;
                else if (body.includes('Community Leader')) result.badge_level = 3;
                else if (body.includes('Community Ambassador')) result.badge_level = 2;
                else if (body.includes('Pillar of Community')) result.badge_level = 1;

                // XP
                const xpMatch = body.match(/(\\d+)\\s*XP/);
                if (xpMatch) result.badge_xp = parseInt(xpMatch[1]);

                // Прогресс "N of M tasks completed"
                const progressMatch = body.match(/(\\d+)\\s*of\\s*(\\d+)\\s*tasks?\\s*completed/i);
                if (progressMatch) {
                    result.tasks_completed = parseInt(progressMatch[1]);
                    result.tasks_total = parseInt(progressMatch[2]);
                }

                // Задачи — структура Steam:
                // div.badge_task > img.quest_icon (src содержит _on.png или _off.png)
                //                > div.badge_task_name (текст задачи)
                const taskEls = document.querySelectorAll('.badge_task');
                for (const el of taskEls) {
                    const nameEl = el.querySelector('.badge_task_name');
                    if (!nameEl) continue;
                    const name = nameEl.textContent.trim();
                    if (!name) continue;

                    const img = el.querySelector('img.quest_icon');
                    const src = img ? img.src : '';
                    const completed = src.includes('_on.png');

                    result.tasks.push({ name, completed });
                }

                return result;
            }
        """)

        logger.info("[Badge] %s: level=%s xp=%s tasks=%s/%s",
                     login, data.get('badge_level'), data.get('badge_xp'),
                     data.get('tasks_completed'), data.get('tasks_total'))

        return BadgeCheckResult(
            success=True,
            badge_level=data.get('badge_level', 0),
            badge_xp=data.get('badge_xp', 0),
            tasks_completed=data.get('tasks_completed', 0),
            tasks_total=data.get('tasks_total', 0),
            tasks=data.get('tasks', []),
            message="OK",
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return BadgeCheckResult(success=False, message=str(e))

    finally:
        if br_b:
            try: br_b.close()
            except Exception: pass
        if pw_b:
            try: pw_b.stop()
            except Exception: pass


async def check_community_badge(
    login: str, password: str, shared_secret: str | None = None,
) -> BadgeCheckResult:
    """Проверяет прогресс Community Badge."""
    if not password:
        return BadgeCheckResult(success=False, message="Пароль пуст")
    return await _run_in_clean_thread(_check_badge_sync, login, password, shared_secret)
