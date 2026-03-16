"""
Открытие Steam в Playwright-браузере с автологином.

Два режима:
1. open_steam_browser_raw — subprocess с persistent context (сессии сохраняются)
2. fetch_steam_balance — sync Playwright в отдельном потоке (парсинг баланса)

ВАЖНО: Основной режим (open_steam_browser_raw) использует subprocess.Popen,
т.к. Python 3.14 на Windows не поддерживает asyncio subprocess
(NotImplementedError в ProactorEventLoop).
"""

import asyncio
import json
import logging
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from app.models.account import Account
from app.models.proxy import Proxy
from app.services.encryption import decrypt
from app.services.steam_guard import generate_steam_guard_code

logger = logging.getLogger(__name__)

STEAM_LOGIN_URL = "https://store.steampowered.com/login"

# Путь к скрипту-запускатору браузера
_BROWSER_SCRIPT = str(Path(__file__).parent / "_browser_subprocess.py")
_PYTHON_EXE = sys.executable
_BACKEND_DIR = str(Path(__file__).parent.parent.parent)


# -- Курсы валют (онлайн + кэш + fallback) --

STEAM_SYMBOL_TO_ISO: list[tuple[str, str]] = [
    ("CDN$", "CAD"), ("ARS$", "ARS"), ("CLP$", "CLP"), ("COL$", "COP"),
    ("MX$", "MXN"), ("NZ$", "NZD"), ("HK$", "HKD"), ("NT$", "TWD"),
    ("S$", "SGD"), ("A$", "AUD"), ("R$", "BRL"),
    ("руб", "RUB"), ("pуб", "RUB"),
    ("USD", "USD"), ("CHF", "CHF"), ("S/.", "PEN"), ("S/", "PEN"),
    ("RM", "MYR"), ("TL", "TRY"), ("kr", "NOK"), ("zł", "PLN"),
    ("Rp", "IDR"), ("₽", "RUB"), ("€", "EUR"), ("£", "GBP"),
    ("¥", "CNY"), ("₸", "KZT"), ("₴", "UAH"), ("₹", "INR"),
    ("₡", "CRC"), ("₩", "KRW"), ("฿", "THB"), ("₫", "VND"),
    ("₱", "PHP"), ("₺", "TRY"), ("R", "ZAR"), ("$", "USD"),
]

_FALLBACK_RATES: dict[str, float] = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "RUB": 0.011, "KZT": 0.002,
    "UAH": 0.024, "BRL": 0.17, "CAD": 0.73, "AUD": 0.65, "NZD": 0.60,
    "HKD": 0.128, "TWD": 0.031, "SGD": 0.75, "MXN": 0.055, "ARS": 0.001,
    "CLP": 0.001, "COP": 0.00023, "PEN": 0.27, "MYR": 0.22, "TRY": 0.029,
    "NOK": 0.093, "PLN": 0.25, "IDR": 0.000061, "CNY": 0.14, "JPY": 0.0069,
    "INR": 0.012, "CRC": 0.002, "KRW": 0.00073, "THB": 0.029, "VND": 0.000039,
    "PHP": 0.017, "ZAR": 0.054, "CHF": 1.13,
}

_rates_cache: dict[str, float] = {}
_rates_fetched_at: datetime | None = None
_CACHE_TTL_SECONDS = 86400


def _get_rates() -> dict[str, float]:
    """Возвращает актуальные курсы. Обновляет из API раз в сутки."""
    global _rates_cache, _rates_fetched_at

    now = datetime.now(timezone.utc)
    if _rates_cache and _rates_fetched_at and (now - _rates_fetched_at).total_seconds() < _CACHE_TTL_SECONDS:
        return _rates_cache

    try:
        resp = httpx.get("https://open.er-api.com/v6/latest/USD", timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") == "success" and "rates" in data:
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


def _parse_balance_to_usd(balance_str: str) -> float | None:
    """Парсит строку баланса и конвертирует в USD."""
    if not balance_str:
        return None

    cleaned = balance_str.replace('\xa0', ' ').strip()
    num_match = re.search(r'[\d\s.,]+', cleaned)
    if not num_match:
        return None

    num_str = num_match.group().strip()

    if ',' in num_str and '.' in num_str:
        if num_str.rfind(',') > num_str.rfind('.'):
            num_str = num_str.replace('.', '').replace(',', '.')
        else:
            num_str = num_str.replace(',', '')
    elif ',' in num_str:
        parts = num_str.split(',')
        if len(parts) == 2 and len(parts[1]) <= 2:
            num_str = num_str.replace(',', '.')
        else:
            num_str = num_str.replace(',', '')

    num_str = num_str.replace(' ', '')
    try:
        amount = float(num_str)
    except ValueError:
        return None

    rates = _get_rates()
    for symbol, iso_code in STEAM_SYMBOL_TO_ISO:
        if symbol in cleaned:
            rate = rates.get(iso_code, _FALLBACK_RATES.get(iso_code, 1.0))
            return round(amount * rate, 2)

    return round(amount, 2)


# -- Subprocess подход (основной) --

def open_steam_browser_raw(
    login: str,
    password: str,
    shared_secret: str | None = None,
    proxy_config: dict | None = None,
) -> None:
    """
    Открывает браузер с автологином в отдельном процессе.
    Использует persistent context для сохранения сессий.

    proxy_config -- словарь вида {"host": ..., "port": ..., "protocol": ..., "username": ..., "password": ...}
    """
    if not password:
        logger.error("Пароль аккаунта пуст для %s", login)
        return

    # Собираем proxy для Playwright
    proxy_pw = None
    if proxy_config and proxy_config.get("host"):
        protocol = proxy_config.get("protocol", "http")
        host = proxy_config["host"]
        port = proxy_config["port"]
        proxy_pw = {"server": f"{protocol}://{host}:{port}"}
        if proxy_config.get("username"):
            proxy_pw["username"] = proxy_config["username"]
        if proxy_config.get("password"):
            proxy_pw["password"] = proxy_config["password"]

    payload = json.dumps({
        "login": login,
        "password": password,
        "shared_secret": shared_secret,
        "proxy": proxy_pw,
    })

    try:
        proc = subprocess.Popen(
            [_PYTHON_EXE, _BROWSER_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=None,
            stderr=None,
            text=True,
            cwd=_BACKEND_DIR,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        proc.stdin.write(payload)
        proc.stdin.close()

        logger.info("Браузер запущен в процессе PID=%d для %s", proc.pid, login)
    except Exception:
        logger.exception("Не удалось запустить браузер для %s", login)


def open_steam_browser_raw_from_db(account: Account, proxy: Proxy | None = None) -> None:
    """Обёртка для вызова из старого кода (account -- модель из БД)."""
    login = account.login
    password = decrypt(account.password_encrypted)
    shared_secret = decrypt(account.shared_secret_encrypted)

    proxy_config = None
    if proxy:
        proxy_config = {
            "protocol": getattr(proxy, "protocol", "http"),
            "host": proxy.host,
            "port": proxy.port,
            "username": getattr(proxy, "username", None),
            "password": getattr(proxy, "password", None),
        }

    open_steam_browser_raw(login, password, shared_secret, proxy_config)


# -- Обратная совместимость: async обёртки для accounts.py --

async def open_steam_browser(account: Account, proxy: Proxy | None = None) -> BrowserResult:
    """Открывает браузер через subprocess (для вызова из async endpoint)."""
    login = account.login
    password = decrypt(account.password_encrypted)
    shared_secret = decrypt(account.shared_secret_encrypted)

    if not password:
        return BrowserResult(success=False, message="Пароль аккаунта пуст")

    proxy_config = None
    if proxy:
        proxy_config = {
            "protocol": getattr(proxy, "protocol", "http"),
            "host": proxy.host,
            "port": proxy.port,
            "username": getattr(proxy, "username", None),
            "password": getattr(proxy, "password", None),
        }

    open_steam_browser_raw(login, password, shared_secret, proxy_config)
    return BrowserResult(success=True, message="Браузер запущен")


# -- Парсинг баланса (sync Playwright в потоке) --

def _ensure_proactor():
    """Windows: устанавливаем ProactorEventLoop в потоке."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.set_event_loop(asyncio.new_event_loop())


async def _run_in_clean_thread(func, *args):
    """Запускает func в чистом threading.Thread без asyncio-контекста."""
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

    if shared_secret:
        code = generate_steam_guard_code(shared_secret)
        logger.info("Сгенерирован Steam Guard код для %s: %s", login, code)

        char_inputs = page.locator('input[maxlength="1"][type="text"]')
        count = char_inputs.count()

        if count >= 5:
            for i in range(5):
                char_inputs.nth(i).click()
                char_inputs.nth(i).fill(code[i])
                time.sleep(0.1)
            time.sleep(3)
        else:
            logger.warning("Не найдены ячейки 2FA (найдено %d)", count)

    balance = _parse_balance(page)
    if balance:
        logger.info("Баланс аккаунта %s: %s", login, balance)

    return balance


def _parse_balance(page) -> str | None:
    """Парсит баланс кошелька со страницы Steam Store."""
    try:
        page.goto("https://store.steampowered.com/", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)

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
                    if text and re.search(r'\d', text):
                        return text.strip()
            except Exception:
                continue
        return None
    except Exception as e:
        logger.warning("Не удалось распарсить баланс: %s", e)
        return None


async def fetch_steam_balance(
    login: str,
    password: str,
    shared_secret: str | None = None,
) -> BrowserResult:
    """Парсинг баланса в чистом потоке."""
    if not password:
        return BrowserResult(success=False, message="Пароль пуст")
    return await _run_in_clean_thread(_fetch_balance_sync, login, password, shared_secret)


def _fetch_balance_sync(
    login: str,
    password: str,
    shared_secret: str | None = None,
) -> BrowserResult:
    """Sync: видимый браузер -> логин -> баланс -> закрытие."""
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
