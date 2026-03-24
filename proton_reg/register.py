"""
Proton Mail авторегистрация через Firefox (Playwright).
Использование:
    python register.py
    python register.py --proxy user:pass@host:port
    python register.py --count 5
"""
import sys
import re
import time
import random
import string
import argparse
import math

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright
from captcha_solver import get_puzzle_target, find_piece_in_canvas

OUTPUT_FILE   = "proton_accounts.txt"
SIGNUP_URL    = "https://account.proton.me/mail/signup"
DEFAULT_PROXY = "vhforgg2:4cysn2yf@45.144.179.21:15382"


# ── Генераторы ────────────────────────────────────────────────────────────────

def gen_username() -> str:
    length = random.randint(8, 12)
    num_letters = int(length * 0.7)
    num_digits = length - num_letters
    chars = (random.choices(string.ascii_lowercase, k=num_letters)
           + random.choices(string.digits, k=num_digits))
    random.shuffle(chars)
    # Первый символ — всегда буква
    if chars[0].isdigit():
        for i, c in enumerate(chars):
            if c.isalpha():
                chars[0], chars[i] = chars[i], chars[0]
                break
    return "".join(chars)


def gen_password(n: int = 16) -> str:
    pool = string.ascii_letters + string.digits + "!@#$%"
    pwd  = (random.choice(string.ascii_uppercase)
          + random.choice(string.ascii_lowercase)
          + random.choice(string.digits)
          + random.choice("!@#$%")
          + "".join(random.choices(pool, k=n - 4)))
    return "".join(random.sample(pwd, len(pwd)))


# ── Вспомогательные ──────────────────────────────────────────────────────────

def pause(a=0.5, b=1.5):
    time.sleep(random.uniform(a, b))


def jclick(locator):
    """JS-клик — работает даже за оверлеем."""
    locator.evaluate("el => el.click()")


def parse_proxy(s: str) -> dict | None:
    if not s:
        return None
    s = s.strip().lstrip("http://").lstrip("https://")
    if "@" in s:
        creds, host = s.rsplit("@", 1)
        user, pwd   = creds.split(":", 1)
        return {"server": f"http://{host}", "username": user, "password": pwd}
    return {"server": f"http://{s}"}


def click_btn(page, pattern, timeout=5000):
    """Кликнуть первую кнопку по паттерну текста (JS-клик, работает при свёрнутом окне)."""
    try:
        btn = page.locator("button").filter(has_text=re.compile(pattern, re.I))
        if btn.count() > 0:
            jclick(btn.first)
            return True
    except Exception:
        pass
    return False


def click_in_frames(page, pattern):
    """Кликнуть кнопку внутри любого iframe по паттерну."""
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
    """Есть ли canvas в captcha frame (работает при свёрнутом окне)."""
    for f in page.frames:
        if 'captcha' in f.url.lower():
            try:
                if f.locator("canvas").count() > 0:
                    return True
            except Exception:
                pass
    return False


# ── Регистрация одного аккаунта ───────────────────────────────────────────────

def register_one(proxy_str: str | None, headless: bool = False) -> dict:
    username = gen_username()
    password = gen_password()
    print(f"  User: {username}@proton.me | Pass: {password}")

    proxy = parse_proxy(proxy_str)

    with sync_playwright() as pw:
        browser = pw.firefox.launch(headless=headless)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="ru-RU",
            ignore_https_errors=True,
            **({"proxy": proxy} if proxy else {}),
        )
        page = ctx.new_page()

        try:
            # ── 1. Загрузка ───────────────────────────────────────────────
            print("  [1] Загрузка...")
            try:
                page.goto(SIGNUP_URL, timeout=60_000, wait_until="networkidle")
            except Exception:
                pass
            time.sleep(3)
            page.screenshot(path="debug_01_loaded.png")

            # ── 2. Free план ──────────────────────────────────────────────
            print("  [2] Free план...")
            for _ in range(5):
                try:
                    free = page.locator("button.card-plan").filter(has_text=re.compile(r"free|бесплатн", re.I))
                    if free.count() > 0:
                        jclick(free.first)
                        print("      OK")
                        break
                except Exception:
                    pass
                time.sleep(2)
            else:
                print("      SKIP (не найден)")
            time.sleep(1.5)

            # ── 3. Username (в challenge iframe) ──────────────────────────
            print("  [3] Username...")
            try:
                inp = page.frame_locator('iframe[src*="Name=email"]').locator("input").first
                inp.wait_for(state="attached", timeout=10_000)
                inp.fill(username)
                time.sleep(2)
                print(f"      OK: {username}")
            except Exception:
                print("      WARN: iframe не найден, пробуем #username")
                try:
                    page.locator("#username").first.fill(username)
                except Exception:
                    pass
            page.screenshot(path="debug_03_username.png")

            # ── 4. Пароль ─────────────────────────────────────────────────
            print("  [4] Пароль...")
            try:
                page.locator("#password").first.wait_for(state="visible", timeout=8_000)
                page.locator("#password").first.fill(password)
                # confirm может не быть
                try:
                    page.locator("#password-confirm").first.fill(password, timeout=3000)
                except Exception:
                    pass
                print("      OK")
            except Exception as e:
                print(f"      WARN: {e}")
            time.sleep(1)
            page.screenshot(path="debug_04_password.png")

            # ── 5. Submit (цикл: submit + закрыть upsell пока не капча) ──
            print("  [5] Submit...")
            for s_try in range(10):
                # Уже на капче?
                if has_captcha_canvas(page):
                    print("      Капча уже есть!")
                    break

                # Upsell "Нет, спасибо"
                if click_btn(page, r"нет.*спасибо|no.*thanks", timeout=2000):
                    print("      Upsell закрыт")
                    time.sleep(2)
                    # Пароль мог сброситься
                    try:
                        page.locator("#password").first.fill(password)
                        try:
                            page.locator("#password-confirm").first.fill(password, timeout=2000)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    continue

                # Submit кнопка (testid=pay)
                try:
                    pay = page.locator('[data-testid="pay"]')
                    if pay.count() > 0:
                        jclick(pay.first)
                        print(f"      Submit [{s_try}] (testid=pay)")
                    elif click_btn(page, r"начать|start using|create account|get started"):
                        print(f"      Submit [{s_try}] (text)")
                    else:
                        page.keyboard.press("Enter")
                        print(f"      Submit [{s_try}] (Enter)")
                except Exception:
                    page.keyboard.press("Enter")
                    print(f"      Submit [{s_try}] (Enter)")
                time.sleep(4)

            page.screenshot(path="debug_05_after_submit.png")

            # ── 6. Ждём результат ─────────────────────────────────────────
            print("  [6] Ждём результата...")
            deadline = time.time() + 300
            attempt = 0
            no_canvas_streak = 0

            while time.time() < deadline:
                attempt += 1
                url = page.url.lower()

                # Скриншот только каждые 10 попыток
                if attempt % 10 == 1:
                    page.screenshot(path=f"debug_loop_{attempt:02d}.png")

                # Успех
                if "signup" not in url and any(x in url for x in ["mail", "inbox", "getting-started"]):
                    with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
                        f.write(f"{username}@proton.me:{password}\n")
                    return {"ok": True, "email": f"{username}@proton.me", "password": password}

                # Upsell
                try:
                    no_thanks = page.locator("button").filter(has_text=re.compile(r"нет.*спасибо|no.*thanks", re.I))
                    if no_thanks.count() > 0:
                        is_shown = no_thanks.first.evaluate("el => el.offsetParent !== null && el.offsetWidth > 0")
                        if is_shown:
                            jclick(no_thanks.first)
                            print("    Upsell закрыт")
                            time.sleep(1.5)
                            continue
                except Exception:
                    pass

                # Капча с canvas?
                if has_captcha_canvas(page):
                    print(f"  [captcha] Попытка {attempt}...")
                    try:
                        result = get_puzzle_target(page)
                        if not result or not isinstance(result, tuple) or len(result) < 2:
                            raise Exception("Координаты не получены")

                        (px, py), (tx, ty) = result[0], result[1]
                        dist = math.hypot(tx - px, ty - py)
                        if dist < 50:
                            raise Exception(f"Слишком близко: dist={dist:.0f}px")

                        print(f"    Drag: ({px},{py}) → ({tx},{ty}) dist={dist:.0f}px")

                        # Drag
                        page.mouse.move(px, py)
                        time.sleep(0.15)
                        page.mouse.down()
                        time.sleep(0.05)
                        steps = 30
                        for i in range(1, steps + 1):
                            t = i / steps
                            eased = t * t * (3 - 2 * t)
                            page.mouse.move(
                                px + (tx - px) * eased,
                                py + (ty - py) * eased + random.uniform(-2, 2)
                            )
                            time.sleep(0.015)
                        page.mouse.move(tx, ty)
                        time.sleep(0.1)
                        page.mouse.up()
                        time.sleep(1)
                        page.screenshot(path="debug_after_drag.png")

                        # Далее
                        for f in page.frames:
                            if 'captcha' in f.url.lower():
                                try:
                                    nb = f.locator("button").filter(has_text=re.compile(r"далее|next", re.I))
                                    if nb.count() > 0:
                                        nb.first.click(timeout=3000)
                                        print("    Далее")
                                        break
                                except Exception:
                                    pass
                        else:
                            click_btn(page, r"^далее$|^next$", timeout=2000)

                        time.sleep(3)
                        no_canvas_streak = 0

                    except Exception as e:
                        print(f"    Ошибка: {e}")
                        no_canvas_streak += 1
                        time.sleep(2)
                    continue

                # Recovery Kit — галочка + Продолжить
                try:
                    checkbox = page.locator("input[type='checkbox']")
                    if checkbox.count() > 0:
                        is_checked = checkbox.first.is_checked()
                        if not is_checked:
                            jclick(checkbox.first)
                            print("    Recovery Kit — галочка")
                            time.sleep(0.5)
                        if click_btn(page, r"продолжить|continue", timeout=2000):
                            print("    Recovery Kit — Продолжить")
                            time.sleep(3)
                            continue
                except Exception:
                    pass

                # Установить отображаемое имя / любой другой экран с "Продолжить"
                if click_btn(page, r"продолжить|continue", timeout=1000):
                    print("    Продолжить")
                    time.sleep(2)
                    continue

                # Вкладка CAPTCHA / экран выбора / Далее
                click_btn(page, r"^captcha$", timeout=1000)
                click_btn(page, r"^далее$|^next$", timeout=1000)
                click_in_frames(page, r"далее|next")

                # Модалка пропала — повторный submit
                if attempt > 5 and not has_captcha_canvas(page):
                    frames_count = len([f for f in page.frames if f.url and f.url != "about:blank"])
                    if frames_count <= 3:
                        try:
                            pay = page.locator('[data-testid="pay"]')
                            if pay.count() > 0:
                                jclick(pay.first)
                                print("    Повторный submit")
                                time.sleep(4)
                                continue
                        except Exception:
                            pass

                print(f"    [loop {attempt}]")
                time.sleep(1.5)

            return {"ok": False, "msg": f"Таймаут. URL: {page.url}"}

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"ok": False, "msg": str(e)}
        finally:
            try:
                ctx.close()
                browser.close()
            except Exception:
                pass


# ── Точка входа ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Proton Mail авторегистрация")
    ap.add_argument("--proxy",    default=None,  help="user:pass@host:port")
    ap.add_argument("--count",    default=1, type=int, help="Сколько аккаунтов")
    ap.add_argument("--headless", action="store_true", default=False)
    args = ap.parse_args()

    if not args.proxy:
        args.proxy = DEFAULT_PROXY

    print(f"\nСоздаём {args.count} аккаунт(ов). Прокси: {args.proxy or 'нет'}\n")

    ok_count = 0
    for i in range(args.count):
        print(f"── Аккаунт {i+1}/{args.count} ──────────────────────")
        iter_start = time.time()
        result = register_one(proxy_str=args.proxy, headless=args.headless)

        if result["ok"]:
            ok_count += 1
            print(f"  ✓ {result['email']}:{result['password']}")
        else:
            print(f"  ✗ {result['msg']}")

        if i < args.count - 1:
            # Считаем сколько прошло с начала этого аккаунта
            elapsed = time.time() - iter_start
            wait = max(0, 120 - elapsed)
            if wait > 0:
                print(f"  Пауза {wait:.0f}с (до 2 мин)...")
                time.sleep(wait)

    print(f"\n══ Готово: {ok_count}/{args.count} ══")


if __name__ == "__main__":
    main()
