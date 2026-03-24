"""
Proton Mail + Steam авторегистрация.
1. Регистрирует Proton email (Playwright Firefox + U-Net капча)
2. В том же браузере регистрирует Steam (API + hcaptchasolver.com)
3. Подтверждает email Steam через Proton inbox в браузере
4. Сохраняет всё в accounts.txt

Использование:
    python main.py
    python main.py --proxy user:pass@host:port
    python main.py --count 5
"""
import sys
import re
import time
import random
import string
import argparse
import math
import logging

sys.stdout.reconfigure(encoding="utf-8")

import requests
import httpx
from playwright.sync_api import sync_playwright  # для captcha_solver
from captcha_solver import get_puzzle_target

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s: %(message)s")
logger = logging.getLogger("main")

# ── Конфиги ───────────────────────────────────────────────────────────────────

ACCOUNTS_FILE   = "accounts.txt"
PROTON_SIGNUP   = "https://account.proton.me/mail/signup"
STEAM_STORE     = "https://store.steampowered.com"
STEAM_SITEKEY   = "e18a349a-46c2-46a0-87a8-74be79345c92"
HCAPTCHA_KEY    = "Kenzx_fe6d404383507753a5bf0f849192fd835084d2e1795aaf78"
HCAPTCHA_API    = "https://hcaptchasolver.com/api"
DEFAULT_PROXY   = "5dq43yrp:nxc18dc2@87.236.22.82:10290"
STEAM_UA        = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


# ── Генераторы ────────────────────────────────────────────────────────────────

def gen_username() -> str:
    """Человечный username: имя + фамилия + цифры."""
    first = ["james","john","robert","michael","william","david","thomas",
             "lucas","ethan","noah","liam","oliver","henry","george",
             "alex","max","sam","ben","chris","daniel","emma","anna","kate"]
    last = ["smith","johnson","williams","brown","jones","garcia","miller",
            "davis","wilson","taylor","anderson","martin","harris","clark",
            "lee","walker","hall","young","king","wright","hill","green"]
    sep = random.choice([".", "_", ""])
    num = random.randint(1, 99) if random.random() > 0.3 else random.randint(80, 2005)
    return f"{random.choice(first)}{sep}{random.choice(last)}{num}"


def gen_password(n: int = 16) -> str:
    pool = string.ascii_letters + string.digits + "!@#$%"
    pwd = (random.choice(string.ascii_uppercase)
         + random.choice(string.ascii_lowercase)
         + random.choice(string.digits)
         + random.choice("!@#$%")
         + "".join(random.choices(pool, k=n - 4)))
    return "".join(random.sample(pwd, len(pwd)))


def gen_steam_login() -> str:
    adj = random.choice(["cool","dark","fast","wild","iron","blue","red","ice","sky","neo"])
    noun = random.choice(["wolf","bear","hawk","fox","lion","storm","blade","fire","star","ace"])
    return f"{adj}{noun}{random.randint(100, 9999)}"


# ── Утилиты Playwright ────────────────────────────────────────────────────────

def jclick(locator):
    locator.evaluate("el => el.click()")


def click_btn(page, pattern, timeout=5000):
    try:
        btn = page.locator("button").filter(has_text=re.compile(pattern, re.I))
        if btn.count() > 0:
            jclick(btn.first)
            return True
    except Exception:
        pass
    return False


def click_in_frames(page, pattern):
    for f in page.frames:
        if f == page.main_frame:
            continue
        try:
            btn = f.locator("button").filter(has_text=re.compile(pattern, re.I))
            if btn.count() > 0:
                btn.first.click(timeout=3000)
                return True
        except Exception:
            pass
    return False


def has_captcha_canvas(page) -> bool:
    for f in page.frames:
        if 'captcha' in f.url.lower():
            try:
                if f.locator("canvas").count() > 0:
                    return True
            except Exception:
                pass
    return False


def parse_proxy(s: str) -> dict | None:
    if not s:
        return None
    s = s.strip()
    if "@" in s:
        creds, host = s.rsplit("@", 1)
        user, pwd = creds.split(":", 1)
        # host может быть "socks5://ip:port" или "ip:port"
        if "://" not in host:
            host = f"http://{host}"
        return {"server": host, "username": user, "password": pwd}
    if "://" not in s:
        s = f"http://{s}"
    return {"server": s}


def proxy_for_requests(proxy_str: str) -> dict | None:
    """Прокси в формате requests."""
    if not proxy_str:
        return None
    s = proxy_str.strip()
    if "@" in s:
        creds, host = s.rsplit("@", 1)
        if "://" not in host:
            host = f"http://{host}"
        url = f"{host.split('://')[0]}://{creds}@{host.split('://', 1)[1]}"
    else:
        url = s if "://" in s else f"http://{s}"
    return {"http": url, "https": url}


# ── hcaptchasolver.com ────────────────────────────────────────────────────────

def solve_hcaptcha(sitekey: str = STEAM_SITEKEY,
                   page_url: str = "https://store.steampowered.com/join",
                   proxy_str: str | None = None) -> str | None:
    """Решить hCaptcha через hcaptchasolver.com, вернуть токен."""
    print("  [hcaptcha] Создаём задачу...")
    try:
        task = {
            "type": "PopularCaptchaTaskProxyless",
            "websiteURL": page_url,
            "websiteKey": sitekey,
        }
        # Если есть прокси — используем PopularCaptchaTask с прокси
        if proxy_str:
            s = proxy_str.strip()
            if "@" in s:
                creds, host = s.rsplit("@", 1)
                user, pwd = creds.split(":", 1)
                ip, port = host.split(":", 1)
                task = {
                    "type": "PopularCaptchaTask",
                    "websiteURL": page_url,
                    "websiteKey": sitekey,
                    "proxyType": "http",
                    "proxyAddress": ip,
                    "proxyPort": int(port),
                    "proxyLogin": user,
                    "proxyPassword": pwd,
                }

        resp = httpx.post(f"{HCAPTCHA_API}/createTask", json={
            "clientKey": HCAPTCHA_KEY,
            "task": task,
        }, timeout=30)
        data = resp.json()
        task_id = data.get("taskId")
        if not task_id:
            print(f"  [hcaptcha] Ошибка: {data}")
            return None
        print(f"  [hcaptcha] Задача: {task_id}")

        time.sleep(3)
        start = time.monotonic()
        while time.monotonic() - start < 180:
            resp = httpx.post(f"{HCAPTCHA_API}/getTaskResult", json={
                "clientKey": HCAPTCHA_KEY,
                "taskId": task_id,
            }, timeout=30)
            data = resp.json()
            status = data.get("status")
            if status == "ready":
                token = data.get("solution", {}).get("token") or data.get("solution", {}).get("gRecaptchaResponse")
                elapsed = time.monotonic() - start
                print(f"  [hcaptcha] Решена за {elapsed:.1f}с")
                return token
            if status == "processing":
                time.sleep(2)
                continue
            print(f"  [hcaptcha] Ошибка: {data}")
            return None
        print("  [hcaptcha] Таймаут")
        return None
    except Exception as e:
        print(f"  [hcaptcha] Исключение: {e}")
        return None


# ── Steam регистрация через браузер ───────────────────────────────────────────

def steam_register_browser(steam_page, email: str, steam_login: str, steam_pass: str, proxy_str: str | None = None) -> dict:
    """
    Регистрация Steam в браузере:
    1. Открыть store.steampowered.com/join
    2. Ввести email
    3. Решить hCaptcha через API, вставить токен через JS
    4. Submit → Steam отправляет письмо
    5. (подтверждение email — отдельно)
    6. Ввести login + password, создать аккаунт

    Возвращает {"ok": bool, "steam_id": str, "error": str}
    """
    result = {"ok": False, "steam_id": "", "error": ""}

    # 1. Открыть страницу
    print("  [steam] Загрузка join...")
    try:
        steam_page.goto("https://store.steampowered.com/join", timeout=60_000, wait_until="networkidle")
    except Exception:
        pass
    time.sleep(4)

    # 2. Email + подтверждение email
    print(f"  [steam] Email: {email}")
    try:
        # Ищем все input на странице и заполняем email-поля
        inputs = steam_page.locator("input[type='text'], input[type='email'], input:not([type])").all()
        filled = 0
        for inp in inputs[:5]:
            try:
                name = inp.get_attribute("name") or ""
                id_ = inp.get_attribute("id") or ""
                placeholder = inp.get_attribute("placeholder") or ""
                if any(k in (name + id_ + placeholder).lower() for k in ["email", "mail", "почт"]):
                    inp.fill(email)
                    filled += 1
                    print(f"  [steam] Заполнен: id={id_} name={name}")
                    time.sleep(0.3)
            except Exception:
                pass
        if filled == 0:
            # Fallback — первые 2 текстовых поля
            inputs = steam_page.locator("input[type='text'], input:not([type])").all()
            for inp in inputs[:2]:
                try:
                    inp.fill(email)
                    filled += 1
                except Exception:
                    pass
        print(f"  [steam] Email полей заполнено: {filled}")
    except Exception as e:
        print(f"  [steam] Email: {e}")
    time.sleep(1)

    # 3. Возраст — это ссылка <a>, не кнопка
    print("  [steam] Возраст...")
    for _ in range(10):
        try:
            older = steam_page.locator("a").filter(has_text=re.compile(r"больше|older|over|or more|mehr|plus", re.I))
            if older.count() > 0:
                older.first.click(timeout=3000)
                print("  [steam] Возраст: больше")
                time.sleep(3)
                break
        except Exception:
            pass
        time.sleep(1)

    # 4. Чекбокс соглашения "Я подтверждаю что мне исполнилось 13 лет"
    print("  [steam] Соглашение...")
    try:
        agree_cb = steam_page.locator("#i_agree_check").first
        if agree_cb.count() > 0 and not agree_cb.is_checked():
            agree_cb.click(timeout=5000)
            print("  [steam] Галочка поставлена")
            time.sleep(1)
    except Exception:
        # Fallback — любой checkbox
        try:
            cb = steam_page.locator("input[type='checkbox']").first
            if cb.count() > 0 and not cb.is_checked():
                cb.click(timeout=3000)
                print("  [steam] Галочка (fallback)")
                time.sleep(1)
        except Exception:
            pass

    # 5. hCaptcha
    steam_proxy_str = proxy_str
    print("  [steam] hCaptcha...")
    sitekey = STEAM_SITEKEY
    try:
        hcap_frame = steam_page.locator('iframe[src*="hcaptcha"]').first
        if hcap_frame.count() > 0:
            src = hcap_frame.get_attribute("src") or ""
            m = re.search(r'sitekey=([a-f0-9-]+)', src)
            if m:
                sitekey = m.group(1)
    except Exception:
        pass

    captcha_token = solve_hcaptcha(sitekey, "https://store.steampowered.com/join", proxy_str=steam_proxy_str)
    if not captcha_token:
        result["error"] = "hCaptcha не решена"
        return result

    # 5. Вставить токен — monkey-patch CaptchaText() и hcaptcha.getResponse()
    print("  [steam] Вставляем токен...")
    steam_page.evaluate(f"""() => {{
        const token = "{captcha_token}";
        window.CaptchaText = function() {{ return token; }};
        if (typeof hcaptcha !== 'undefined') {{
            hcaptcha.getResponse = function() {{ return token; }};
        }}
    }}""")
    time.sleep(1)

    # 6. Submit через StartCreationSession()
    print("  [steam] Submit...")
    steam_page.evaluate("StartCreationSession()")
    time.sleep(5)

    # 7. Попап возраста (появляется после submit)
    print("  [steam] Ждём попап возраста...")
    for _ in range(15):
        try:
            # Ищем и в <a> и в <button>
            older = steam_page.locator("a, button").filter(has_text=re.compile(r"больше|older|over|or more|mehr|plus", re.I))
            if older.count() > 0:
                older.first.click(timeout=3000)
                print("  [steam] Возраст: больше")
                time.sleep(3)
                break
        except Exception:
            pass
        time.sleep(1)

    steam_page.screenshot(path="debug_steam_after_submit.png")
    time.sleep(3)

    # Проверяем результат
    body = ""
    try:
        body = steam_page.locator("body").inner_text(timeout=3000).lower()
    except Exception:
        pass

    if "неверный" in body or "captcha" in body.lower():
        result["error"] = "Steam: неверный ответ CAPTCHA"
        return result

    if "verify" in body or "подтвер" in body or "check your email" in body or "проверьте" in body:
        print("  [steam] Steam просит подтвердить email!")

    result["waiting_email"] = True
    result["steam_login"] = steam_login
    result["steam_pass"] = steam_pass
    # creation_id возьмём из JS
    try:
        cid = steam_page.evaluate("() => typeof g_creationSessionID !== 'undefined' ? g_creationSessionID : ''")
        result["creation_id"] = cid or ""
        if cid:
            print(f"  [steam] creation_id={cid}")
    except Exception:
        result["creation_id"] = ""

    return result


def steam_finish_account(steam_page, steam_login: str, steam_pass: str, creation_id: str = "") -> dict:
    """После подтверждения email — ввести login и password, создать аккаунт."""
    print(f"  [steam] Создание аккаунта: {steam_login}")

    # Создаём через API fetch в браузере (cookies совпадают)
    if creation_id:
        create_result = steam_page.evaluate(f"""async () => {{
            try {{
                const formData = new URLSearchParams();
                formData.append('accountname', '{steam_login}');
                formData.append('password', '{steam_pass}');
                formData.append('count', '32');
                formData.append('lt', '0');
                formData.append('creation_sessionid', '{creation_id}');

                const resp = await fetch('/join/createaccount/', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
                    body: formData.toString()
                }});
                return await resp.json();
            }} catch(e) {{
                return {{ error: e.toString() }};
            }}
        }}""")
        print(f"  [steam] Create result: {create_result}")

        if create_result and create_result.get("bSuccess"):
            steam_id = str(create_result.get("steamid", ""))
            print(f"  [steam] Аккаунт создан! SteamID={steam_id}")
            return {"ok": True, "steam_id": steam_id}
        else:
            print(f"  [steam] Ошибка: {create_result}")
            return {"ok": False, "error": str(create_result)}

    return {"ok": False, "error": "no creation_id"}


# ── Proton регистрация (из register.py) ───────────────────────────────────────

def register_proton(page, username: str, password: str) -> bool:
    """Зарегистрировать Proton email на уже открытой странице. Возвращает True если успех."""

    # 0. Человекоподобные движения мыши
    def human_move():
        """Случайные движения мыши перед действием."""
        for _ in range(random.randint(2, 5)):
            page.mouse.move(
                random.randint(100, 1000),
                random.randint(100, 700)
            )
            time.sleep(random.uniform(0.1, 0.4))

    # 1. Загрузка
    print("  [proton] Загрузка...")
    try:
        page.goto(PROTON_SIGNUP, timeout=60_000, wait_until="networkidle")
    except Exception:
        pass
    time.sleep(random.uniform(3, 6))
    human_move()

    # 2. Free план
    human_move()
    print("  [proton] Free план...")
    for _ in range(5):
        try:
            free = page.locator("button.card-plan").filter(has_text=re.compile(r"free|бесплатн", re.I))
            if free.count() > 0:
                jclick(free.first)
                break
        except Exception:
            pass
        time.sleep(2)
    time.sleep(1.5)

    # 3. Username
    human_move()
    time.sleep(random.uniform(1, 2))
    print(f"  [proton] Username: {username}")
    try:
        inp = page.frame_locator('iframe[src*="Name=email"]').locator("input").first
        inp.wait_for(state="attached", timeout=10_000)
        inp.click()
        time.sleep(random.uniform(0.3, 0.7))
        # Печатаем по символу
        for ch in username:
            page.keyboard.type(ch, delay=0)
            time.sleep(random.uniform(0.05, 0.15))
        time.sleep(random.uniform(1.5, 3))
    except Exception:
        try:
            page.locator("#username").first.fill(username)
        except Exception:
            pass

    # 4. Пароль
    human_move()
    time.sleep(random.uniform(0.5, 1.5))
    print("  [proton] Пароль...")
    try:
        page.locator("#password").first.wait_for(state="visible", timeout=8_000)
        page.locator("#password").first.click()
        time.sleep(random.uniform(0.2, 0.5))
        page.locator("#password").first.fill(password)
        time.sleep(random.uniform(0.5, 1))
        try:
            confirm = page.locator("#password-confirm").first
            confirm.wait_for(state="visible", timeout=5000)
            confirm.click()
            time.sleep(random.uniform(0.2, 0.4))
            confirm.fill(password)
            print("  [proton] Пароль подтверждён")
        except Exception as e:
            print(f"  [proton] Нет #password-confirm: {e}")
    except Exception:
        pass
    time.sleep(1)

    # 5. Submit + upsell + captcha
    print("  [proton] Submit...")
    for s_try in range(10):
        if has_captcha_canvas(page):
            break
        # Upsell
        try:
            nt = page.locator("button").filter(has_text=re.compile(r"нет.*спасибо|no.*thanks|nein.*danke|non.*merci", re.I))
            if nt.count() > 0:
                is_shown = nt.first.evaluate("el => el.offsetParent !== null && el.offsetWidth > 0")
                if is_shown:
                    jclick(nt.first)
                    time.sleep(2)
                    try:
                        page.locator("#password").first.fill(password)
                        try:
                            page.locator("#password-confirm").first.fill(password, timeout=2000)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    continue
        except Exception:
            pass
        # Submit (мультиязычный)
        try:
            pay = page.locator('[data-testid="pay"]')
            if pay.count() > 0:
                jclick(pay.first)
            elif not click_btn(page, r"начать|start using|create account|get started|beginne|commencer|inizia"):
                # Fallback — самая большая фиолетовая кнопка
                big_btn = page.locator("button.button-solid-norm").first
                if big_btn.count() > 0:
                    jclick(big_btn)
                else:
                    page.keyboard.press("Enter")
        except Exception:
            page.keyboard.press("Enter")
        time.sleep(4)

    # 6. Решаем капчу
    print("  [proton] Капча...")
    deadline = time.time() + 300
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        url = page.url.lower()

        if attempt % 5 == 1:
            page.screenshot(path=f"debug_proton_{attempt:02d}.png")
            print(f"    [proton loop {attempt}] url={url[:50]}")

        # Успех — попали в inbox
        if "signup" not in url and any(x in url for x in ["mail", "inbox", "getting-started"]):
            print("  [proton] Регистрация успешна!")
            time.sleep(3)
            dismiss_proton_popups(page)
            return True

        # Upsell
        try:
            nt = page.locator("button").filter(has_text=re.compile(r"нет.*спасибо|no.*thanks|nein.*danke|non.*merci", re.I))
            if nt.count() > 0:
                is_shown = nt.first.evaluate("el => el.offsetParent !== null && el.offsetWidth > 0")
                if is_shown:
                    jclick(nt.first)
                    time.sleep(1.5)
                    continue
        except Exception:
            pass

        # Капча
        if has_captcha_canvas(page):
            try:
                result = get_puzzle_target(page)
                if not result or len(result) < 2:
                    raise Exception("no coords")

                (px, py), (tx, ty) = result[0], result[1]
                dist = math.hypot(tx - px, ty - py)
                if dist < 50:
                    raise Exception("too close")

                print(f"    Drag: ({px:.0f},{py:.0f}) → ({tx:.0f},{ty:.0f})")
                page.mouse.move(px, py)
                time.sleep(0.15)
                page.mouse.down()
                time.sleep(0.05)
                for i in range(1, 31):
                    t = i / 30
                    e = t * t * (3 - 2 * t)
                    page.mouse.move(px + (tx-px)*e, py + (ty-py)*e + random.uniform(-2,2))
                    time.sleep(0.015)
                page.mouse.move(tx, ty)
                time.sleep(0.1)
                page.mouse.up()
                time.sleep(1)

                # Далее
                for f in page.frames:
                    if 'captcha' in f.url.lower():
                        try:
                            nb = f.locator("button").filter(has_text=re.compile(r"далее|next", re.I))
                            if nb.count() > 0:
                                nb.first.click(timeout=3000)
                                break
                        except Exception:
                            pass
                time.sleep(3)
            except Exception as e:
                print(f"    Ошибка капчи: {e}")
                time.sleep(2)
            continue

        # Recovery Kit
        try:
            cb = page.locator("input[type='checkbox']")
            if cb.count() > 0:
                if not cb.first.is_checked():
                    jclick(cb.first)
                    time.sleep(0.5)
                click_btn(page, r"продолжить|continue|fortfahren|weiter|continuer")
                time.sleep(2)
                continue
        except Exception:
            pass

        # "Не прошли проверку" — нажать Повторить
        if click_btn(page, r"повторить|retry|try again|erneut|réessayer"):
            print("    Повторить капчу")
            time.sleep(3)
            continue

        # Продолжить (отображаемое имя и т.д.)
        if click_btn(page, r"продолжить|continue|fortfahren|weiter|continuer"):
            time.sleep(2)
            continue

        # Повторить / CAPTCHA tab / Далее — ищем везде (page + frames)
        click_btn(page, r"^captcha$")
        click_btn(page, r"^далее$|^next$")
        click_in_frames(page, r"далее|next|повторить|retry")

        # Повторный submit если модалка пропала
        if attempt > 5 and not has_captcha_canvas(page):
            frames_count = len([f for f in page.frames if f.url and f.url != "about:blank"])
            if frames_count <= 3:
                try:
                    pay = page.locator('[data-testid="pay"]')
                    if pay.count() > 0:
                        jclick(pay.first)
                        time.sleep(4)
                        continue
                except Exception:
                    pass

        time.sleep(1.5)

    return False


# ── Подтверждение Steam email через Proton inbox ──────────────────────────────

def dismiss_proton_popups(page):
    """Закрыть все попапы Proton (Welcome, Desktop app, Theme, Spring Sale)."""
    for _ in range(10):
        closed = False
        # "Maybe later" — welcome wizard и desktop app
        try:
            ml = page.locator("button, a").filter(has_text=re.compile(r"maybe later|позже", re.I))
            if ml.count() > 0:
                ml.first.click(timeout=2000)
                closed = True
                time.sleep(1)
                continue
        except Exception:
            pass
        # "Let's get started" / "Next" / "Use this"
        try:
            for txt in [r"let.*get.*started|начать", r"^next$|^далее$", r"use this|использовать"]:
                btn = page.locator("button").filter(has_text=re.compile(txt, re.I))
                if btn.count() > 0:
                    btn.first.click(timeout=2000)
                    closed = True
                    time.sleep(1)
                    break
        except Exception:
            pass
        # Spring Sale "X" close button
        try:
            close = page.locator("button[aria-label='Close'], button.modal-close, .modal-two-header-button-close")
            if close.count() > 0:
                close.first.click(timeout=2000)
                closed = True
                time.sleep(1)
                continue
        except Exception:
            pass
        # Generic close X
        try:
            x_btn = page.locator("button").filter(has_text=re.compile(r"^×$|^✕$|^X$"))
            if x_btn.count() > 0:
                x_btn.first.click(timeout=1000)
                closed = True
                time.sleep(0.5)
                continue
        except Exception:
            pass
        if not closed:
            break
    print("  [proton] Попапы закрыты")


def warmup_proton_account(page):
    """
    Прогрев аккаунта — имитация реального пользователя (~90 секунд).
    Закрываем попапы, читаем письма, двигаем мышь.
    """
    print("  [warmup] Прогрев аккаунта...")

    # 1. Закрыть все попапы
    dismiss_proton_popups(page)
    time.sleep(random.uniform(2, 4))

    # 2. Движения мыши как реальный пользователь
    for _ in range(random.randint(3, 6)):
        page.mouse.move(random.randint(100, 900), random.randint(100, 600))
        time.sleep(random.uniform(0.3, 0.8))

    # 3. Открыть письмо от Proton (Welcome)
    try:
        proton_mail = page.locator('[data-testid="message-item"]').filter(
            has_text=re.compile(r"proton|welcome|приветств", re.I)
        )
        if proton_mail.count() > 0:
            proton_mail.first.click(timeout=5000)
            print("  [warmup] Открыли письмо от Proton")
            time.sleep(random.uniform(3, 5))
            # Скроллим письмо
            for _ in range(3):
                page.mouse.wheel(0, random.randint(100, 300))
                time.sleep(random.uniform(0.5, 1))
            # Назад в inbox
            try:
                page.go_back(timeout=5000)
            except Exception:
                pass
            time.sleep(random.uniform(1, 2))
    except Exception:
        pass

    # 4. Кликаем по Inbox, Drafts, Settings — как реальный пользователь
    for section in ["Inbox", "Drafts", "Sent"]:
        try:
            nav = page.locator(f"a, button, [data-testid]").filter(has_text=re.compile(f"^{section}$", re.I))
            if nav.count() > 0:
                nav.first.click(timeout=3000)
                time.sleep(random.uniform(1, 2))
                page.mouse.move(random.randint(200, 800), random.randint(200, 500))
                time.sleep(random.uniform(0.5, 1))
        except Exception:
            pass

    # 5. Зайти в настройки и выйти
    try:
        settings = page.locator("a[href*='settings'], button").filter(has_text=re.compile(r"settings|настройки", re.I))
        if settings.count() > 0:
            settings.first.click(timeout=3000)
            time.sleep(random.uniform(2, 4))
            page.go_back(timeout=5000)
            time.sleep(random.uniform(1, 2))
    except Exception:
        pass

    # 6. Вернуться в Inbox
    try:
        inbox = page.locator("a, button").filter(has_text=re.compile(r"^Inbox$|^Входящие$", re.I))
        if inbox.count() > 0:
            inbox.first.click(timeout=3000)
            time.sleep(random.uniform(1, 2))
    except Exception:
        pass

    # 7. Ещё немного движений
    for _ in range(random.randint(2, 4)):
        page.mouse.move(random.randint(100, 1000), random.randint(100, 700))
        time.sleep(random.uniform(0.3, 0.6))

    print("  [warmup] Прогрев завершён")


def confirm_steam_email_in_inbox(page) -> bool:
    """
    Находим письмо от Steam в Proton inbox и кликаем ссылку подтверждения.
    page должен быть на Proton inbox.
    """
    dismiss_proton_popups(page)
    print("  [confirm] Ждём письмо от Steam...")
    for wait in range(30):
        time.sleep(5)
        # Обновляем inbox
        try:
            page.keyboard.press("F5")
        except Exception:
            pass
        time.sleep(3)

        # Ищем письмо от Steam/Valve
        try:
            steam_mail = page.locator('[data-testid="message-item"]').filter(
                has_text=re.compile(r"steam|valve", re.I)
            )
            if steam_mail.count() == 0:
                # Пробуем по тексту
                steam_mail = page.locator("div, span, a").filter(
                    has_text=re.compile(r"new steam account|verify your email|steam account", re.I)
                )
            if steam_mail.count() > 0:
                print("  [confirm] Письмо найдено! Открываем...")
                steam_mail.first.click(timeout=5000)
                time.sleep(3)

                # Ищем ссылку подтверждения
                link = page.locator("a").filter(
                    has_text=re.compile(r"verify|подтвер|confirm|create.*account", re.I)
                )
                if link.count() == 0:
                    # Ищем ссылку по href
                    link = page.locator('a[href*="newaccountverification"]')

                if link.count() > 0:
                    href = link.first.get_attribute("href")
                    print(f"  [confirm] Ссылка: {href[:80]}...")
                    # Открываем ссылку в новой вкладке
                    new_page = page.context.new_page()
                    new_page.goto(href, timeout=30_000)
                    time.sleep(3)
                    new_page.close()
                    print("  [confirm] Email подтверждён!")
                    return True
                else:
                    # Ищем ссылку в body через regex
                    body = page.locator("body").inner_text(timeout=5000)
                    m = re.search(r'https://store\.steampowered\.com/account/newaccountverification[^\s<>"\']+', body)
                    if m:
                        href = m.group(0)
                        print(f"  [confirm] Ссылка (regex): {href[:80]}...")
                        new_page = page.context.new_page()
                        new_page.goto(href, timeout=30_000)
                        time.sleep(3)
                        new_page.close()
                        print("  [confirm] Email подтверждён!")
                        return True

                print("  [confirm] Письмо открыто, но ссылка не найдена")
        except Exception as e:
            pass

        print(f"  [confirm] Ждём... ({(wait+1)*8}с)")

    print("  [confirm] Таймаут — письмо не пришло")
    return False


# ── Главный flow ──────────────────────────────────────────────────────────────

def register_one(proxy_str: str | None, headless: bool = False) -> dict:
    """
    Полный цикл: Proton email → Steam регистрация → подтверждение → сохранение.
    """
    proton_user = gen_username()
    proton_pass = gen_password()
    proton_email = f"{proton_user}@proton.me"

    print(f"\n  === Proton: {proton_email} ===")

    proxy = parse_proxy(proxy_str)

    # Рандомизация — только то что проверено и работает с Proton
    vp = random.choice([
        {"width": 1366, "height": 768}, {"width": 1920, "height": 1080},
        {"width": 1440, "height": 900}, {"width": 1280, "height": 800},
        {"width": 1536, "height": 864}, {"width": 1600, "height": 900},
    ])
    locale = random.choice(["en-US", "en-GB", "de-DE", "fr-FR", "ru-RU"])
    tz = random.choice(["Europe/Berlin", "Europe/London", "Europe/Paris", "America/New_York", "Europe/Moscow"])

    from chrome_manager import ChromeManager

    cm = ChromeManager()
    try:
        session = cm.create_session(proxy_str=proxy_str)
        page = session.page
        ctx = session.context
        browser = session.browser
        print(f"  FP: CDP Chrome | {vp['width']}x{vp['height']} {locale} {tz}")

        # ── Этап 1: Proton email ──────────────────────────────────────
        ok = register_proton(page, proton_user, proton_pass)
        if not ok:
            return {"ok": False, "error": "Proton регистрация не удалась"}

        print(f"  [OK] Proton: {proton_email}")

        # ── Этап 1.5: Прогрев аккаунта (~90 сек) ─────────────────────
        warmup_proton_account(page)

        # ── Этап 2: Steam регистрация (браузер) ───────────────────────
        print(f"\n  === Steam регистрация ===")
        steam_login = gen_steam_login()
        steam_pass = gen_password()

        # Открываем Steam в новой вкладке
        steam_page = ctx.new_page()

        steam_result = steam_register_browser(steam_page, proton_email, steam_login, steam_pass, proxy_str=proxy_str)
        if steam_result.get("error"):
            steam_page.close()
            return {"ok": False, "error": f"Steam: {steam_result['error']}"}

        # ── Этап 3: Подтверждение email в Proton inbox ────────────────
        print(f"\n  === Подтверждение email ===")
        page.bring_to_front()
        if "mail" not in page.url.lower():
            page.goto("https://mail.proton.me", timeout=30_000)
            time.sleep(5)

        confirmed = confirm_steam_email_in_inbox(page)
        if not confirmed:
            steam_page.close()
            return {"ok": False, "error": "Email подтверждение не удалось"}

        # ── Этап 4: Завершить Steam аккаунт ───────────────────────────
        print(f"\n  === Создание Steam аккаунта ===")
        steam_page.bring_to_front()
        creation_id = steam_result.get("creation_id", "")
        create_result = steam_finish_account(steam_page, steam_login, steam_pass, creation_id)
        steam_page.close()

        steam_id = create_result.get("steam_id", "")

        return {
            "ok": True,
            "proton_email": proton_email,
            "proton_pass": proton_pass,
            "steam_login": steam_login,
            "steam_pass": steam_pass,
            "steam_id": steam_id,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(e)}
    finally:
        try:
            cm.close_session(session)
        except Exception:
            pass
        cm.close_all()


def save_account(data: dict):
    """Сохранить данные аккаунта в accounts.txt."""
    line = (f"{data['proton_email']}:{data['proton_pass']}"
            f"|{data['steam_login']}:{data['steam_pass']}"
            f"|{data.get('steam_id', '')}")
    with open(ACCOUNTS_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"  Сохранено: {line}")


# ── Точка входа ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Proton + Steam авторегистрация")
    ap.add_argument("--proxy", default=None, help="user:pass@host:port")
    ap.add_argument("--count", default=1, type=int, help="Сколько аккаунтов")
    ap.add_argument("--headless", action="store_true", default=False)
    args = ap.parse_args()

    if not args.proxy:
        args.proxy = DEFAULT_PROXY

    print(f"\n{'='*50}")
    print(f"Proton + Steam авторегистрация")
    print(f"Аккаунтов: {args.count} | Прокси: {args.proxy}")
    print(f"{'='*50}\n")

    ok_count = 0
    for i in range(args.count):
        iter_start = time.time()
        print(f"\n{'─'*40}")
        print(f"Аккаунт {i+1}/{args.count}")
        print(f"{'─'*40}")

        result = register_one(proxy_str=args.proxy, headless=args.headless)

        if result["ok"]:
            ok_count += 1
            save_account(result)
            print(f"\n  ✓ УСПЕХ!")
        else:
            print(f"\n  ✗ {result.get('error', 'unknown')}")

        if i < args.count - 1:
            elapsed = time.time() - iter_start
            wait = max(0, 120 - elapsed)
            if wait > 0:
                print(f"\n  Пауза {wait:.0f}с...")
                time.sleep(wait)

    print(f"\n{'='*50}")
    print(f"Готово: {ok_count}/{args.count}")
    if ok_count:
        print(f"Сохранено в {ACCOUNTS_FILE}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
