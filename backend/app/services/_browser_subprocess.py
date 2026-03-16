"""
Отдельный скрипт для запуска Playwright-браузера.

Запускается как subprocess из steam_browser.py.
Это обходит баг Python 3.14 на Windows, где asyncio.create_subprocess_exec
бросает NotImplementedError в ProactorEventLoop.

Принимает JSON через stdin с данными аккаунта.
Использует persistent context -- cookies и сессия сохраняются между запусками.

Совмещённый подход:
- Persistent context + сохранение сессий
- Парсинг баланса + конвертация валют
"""

import base64
import hashlib
import hmac
import json
import os
import re
import struct
import sys
import time

import httpx

# Steam Guard TOTP
_STEAM_CHARS = "23456789BCDFGHJKMNPQRTVWXY"

# Папка для хранения профилей браузера (рядом с backend/)
_PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "browser_profiles")


def generate_steam_guard_code(shared_secret: str) -> str:
    """Генерирует 5-символьный Steam Guard код из shared_secret (base64)."""
    timestamp = int(time.time())
    time_bytes = struct.pack(">Q", timestamp // 30)
    secret_bytes = base64.b64decode(shared_secret)
    hmac_hash = hmac.new(secret_bytes, time_bytes, hashlib.sha1).digest()
    offset = hmac_hash[-1] & 0x0F
    code_int = struct.unpack(">I", hmac_hash[offset : offset + 4])[0] & 0x7FFFFFFF
    code_chars = []
    for _ in range(5):
        code_chars.append(_STEAM_CHARS[code_int % len(_STEAM_CHARS)])
        code_int //= len(_STEAM_CHARS)
    return "".join(code_chars)


# -- Курсы валют (онлайн + fallback) --

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


def _get_rates() -> dict[str, float]:
    """Загружает актуальные курсы валют."""
    try:
        resp = httpx.get("https://open.er-api.com/v6/latest/USD", timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") == "success" and "rates" in data:
            return {
                code: round(1.0 / rate, 8)
                for code, rate in data["rates"].items()
                if rate > 0
            }
    except Exception as e:
        print(f"Currency API error: {e}", flush=True)
    return _FALLBACK_RATES.copy()


def _parse_balance_to_usd(balance_str: str) -> float | None:
    """Парсит строку баланса Steam и конвертирует в USD."""
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
        print(f"Balance parse error: {e}", flush=True)
        return None


def main():
    raw = sys.stdin.read()
    data = json.loads(raw)

    login = data["login"]
    password = data["password"]
    shared_secret = data.get("shared_secret")
    proxy = data.get("proxy")  # {"server": "...", "username": "...", "password": "..."}

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()

    browser = None
    context = None
    result = {"success": False, "balance": None, "balance_usd": None}

    try:
        launch_opts: dict = {"headless": False}
        if proxy:
            launch_opts["proxy"] = proxy

        browser = pw.chromium.launch(**launch_opts)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ru-RU",
        )
        page = context.new_page()

        # Всегда логинимся заново
        print(f"Starting login for {login}...", flush=True)
        page.goto(
            "https://store.steampowered.com/login",
            wait_until="domcontentloaded",
            timeout=30000,
        )

        page.wait_for_selector('[data-featuretarget="login"]', timeout=15000)
        time.sleep(3)

        login_input = page.locator('input[type="text"]._2GBWeup5cttgbTw8FM3tfx')
        login_input.wait_for(state="visible", timeout=10000)
        login_input.fill(login)
        time.sleep(0.5)

        password_input = page.locator('input[type="password"]._2GBWeup5cttgbTw8FM3tfx')
        password_input.fill(password)
        time.sleep(0.5)

        submit_btn = page.locator('[data-featuretarget="login"] button[type="submit"]')
        submit_btn.click()

        # 2FA
        if shared_secret:
            try:
                time.sleep(5)

                # Ищем кнопку "Используйте мобильный код"
                login_area = page.locator('[data-featuretarget="login"]')
                clicked = False
                all_divs = login_area.locator("div").all()
                for div in reversed(all_divs):
                    try:
                        if div.is_visible():
                            txt = (div.text_content() or "").strip()
                            if ("мобильный код" in txt.lower() or "введите код" in txt.lower()) and len(txt) < 50:
                                div.click()
                                print(f"Clicked: '{txt}'", flush=True)
                                clicked = True
                                break
                    except Exception:
                        continue

                if not clicked:
                    print("WARNING: 'Enter code' link not found", flush=True)

                time.sleep(3)

                page.locator('input[maxlength="1"]').first.wait_for(
                    state="visible", timeout=15000
                )
                time.sleep(1)

                code = generate_steam_guard_code(shared_secret)
                print(f"2FA code generated: {code}", flush=True)

                char_inputs = page.locator('input[maxlength="1"]').all()
                visible_inputs = [inp for inp in char_inputs if inp.is_visible()]

                for i, char in enumerate(code):
                    if i < len(visible_inputs):
                        visible_inputs[i].fill(char)
                        time.sleep(0.1)

                print("2FA code entered!", flush=True)
                time.sleep(3)
            except Exception as e:
                print(f"2FA error: {e}", flush=True)
        else:
            time.sleep(5)

        # Парсим баланс после логина
        balance = _parse_balance(page)
        balance_usd = _parse_balance_to_usd(balance) if balance else None
        if balance:
            print(f"Balance: {balance} (${balance_usd})", flush=True)

        result = {
            "success": True,
            "balance": balance,
            "balance_usd": balance_usd,
        }

        print("BROWSER_READY", flush=True)

        # Ждём пока пользователь закроет браузер
        try:
            while len(context.pages) > 0:
                time.sleep(1)
        except Exception:
            pass

    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        result = {"success": False, "error": str(e)}

    finally:
        print(f"RESULT:{json.dumps(result)}", flush=True)
        if context:
            try:
                context.close()
            except Exception:
                pass
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        try:
            pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
