"""
Отдельный скрипт для запуска Playwright-браузера.

Запускается как subprocess из steam_browser.py.
Это обходит баг Python 3.14 на Windows, где asyncio.create_subprocess_exec
бросает NotImplementedError в ProactorEventLoop.

Принимает JSON через stdin с данными аккаунта.
Использует persistent context — cookies и сессия сохраняются между запусками.
"""

import base64
import hashlib
import hmac
import json
import os
import struct
import sys
import time

# Steam использует свой алфавит вместо стандартного base32
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


def main():
    # Читаем данные из stdin
    raw = sys.stdin.read()
    data = json.loads(raw)

    login = data["login"]
    password = data["password"]
    shared_secret = data.get("shared_secret")
    proxy = data.get("proxy")  # {"server": "...", "username": "...", "password": "..."}

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()

    # Папка профиля для этого аккаунта (сохраняет cookies между запусками)
    user_data_dir = os.path.join(_PROFILES_DIR, login)
    os.makedirs(user_data_dir, exist_ok=True)

    context = None

    try:
        # Persistent context — сохраняет cookies, localStorage, сессию
        launch_opts = {
            "headless": False,
            "viewport": {"width": 1280, "height": 800},
            "locale": "ru-RU",
        }
        if proxy:
            launch_opts["proxy"] = proxy

        context = pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            **launch_opts,
        )
        # persistent context уже создаёт одну вкладку — используем её
        page = context.pages[0] if context.pages else context.new_page()

        # Переходим на Steam — если сессия сохранена, уже залогинены
        page.goto(
            "https://store.steampowered.com/",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        time.sleep(3)

        # Проверяем: залогинены ли мы уже?
        # Если есть кнопка профиля или аватарка — сессия жива
        profile_link = page.locator('[class*="persona"], [class*="playerAvatar"], #account_pulldown')
        already_logged_in = profile_link.count() > 0 and profile_link.first.is_visible()

        if already_logged_in:
            print(f"Already logged in as {login}!", flush=True)
        else:
            # Нужно залогиниться
            print(f"Not logged in, starting login for {login}...", flush=True)
            page.goto(
                "https://store.steampowered.com/login",
                wait_until="domcontentloaded",
                timeout=30000,
            )

            # Ждём появления формы логина Steam
            page.wait_for_selector('[data-featuretarget="login"]', timeout=15000)
            time.sleep(3)

            # Поле логина
            login_input = page.locator('input[type="text"]._2GBWeup5cttgbTw8FM3tfx')
            login_input.wait_for(state="visible", timeout=10000)
            login_input.fill(login)
            time.sleep(0.5)

            # Пароль
            password_input = page.locator('input[type="password"]._2GBWeup5cttgbTw8FM3tfx')
            password_input.fill(password)
            time.sleep(0.5)

            # Кнопка "Войти"
            submit_btn = page.locator('[data-featuretarget="login"] button[type="submit"]')
            submit_btn.click()

            # 2FA если есть shared_secret
            if shared_secret:
                try:
                    # Steam показывает "Используйте мобильное приложение"
                    # Нужно нажать "Используйте мобильный код"
                    time.sleep(5)

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

                    # Ждём появления полей для 2FA кода
                    page.locator('input[maxlength="1"]').first.wait_for(
                        state="visible", timeout=15000
                    )
                    time.sleep(1)

                    code = generate_steam_guard_code(shared_secret)
                    print(f"2FA code generated: {code}", flush=True)

                    # Вводим по одному символу в каждое поле
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
                # Нет shared_secret — ждём пока пользователь введёт вручную
                time.sleep(5)

        print("BROWSER_READY", flush=True)

        # Ждём пока пользователь закроет браузер
        try:
            while len(context.pages) > 0:
                time.sleep(1)
        except Exception:
            pass

    finally:
        if context:
            try:
                context.close()
            except Exception:
                pass
        try:
            pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
