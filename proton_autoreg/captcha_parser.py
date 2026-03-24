"""
Парсер капч Proton Mail.
Заходит → заполняет → доходит до капчи → скриншотит → обновляет.
"""
import sys, os, re, time, random, string
sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

SIGNUP_URL    = "https://account.proton.me/mail/signup"
DEFAULT_PROXY = "mxrpcurc:7hv7nezm@45.144.179.21:15382"
PHOTOS_DIR    = "parser_photos"


def parse_proxy(s):
    s = s.strip().lstrip("http://").lstrip("https://")
    if "@" in s:
        creds, host = s.rsplit("@", 1)
        user, pwd = creds.split(":", 1)
        return {"server": f"http://{host}", "username": user, "password": pwd}
    return {"server": f"http://{s}"}


def run(proxy_str=DEFAULT_PROXY, count=1000):
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    existing = len([f for f in os.listdir(PHOTOS_DIR) if f.endswith(".png") and f.startswith("captcha_")])
    idx = existing
    goal = count

    proxy = parse_proxy(proxy_str) if proxy_str else None
    username = ''.join(random.choices(string.ascii_lowercase, k=8)) + str(random.randint(100,9999))
    password = ''.join(random.choices(string.ascii_letters + string.digits + "!@#$", k=16))

    print(f"Цель: {goal}. Уже: {existing}. User: {username}")

    with sync_playwright() as pw:
        browser = pw.firefox.launch(headless=False)
        page = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="ru-RU",
            ignore_https_errors=True,
            **({"proxy": proxy} if proxy else {}),
        ).new_page()

        # 1. Загрузка
        print("[1] Загрузка...")
        try:
            page.goto(SIGNUP_URL, timeout=60000, wait_until="networkidle")
        except Exception:
            pass
        time.sleep(4)

        # 2. Free план
        print("[2] Free план...")
        try:
            btn = page.locator("button.card-plan").filter(has_text=re.compile(r"free|бесплатн", re.I))
            btn.first.click(timeout=10000)
        except Exception:
            pass
        time.sleep(1.5)

        # 3. Username
        print("[3] Username...")
        try:
            inp = page.frame_locator('iframe[src*="Name=email"]').locator("input").first
            inp.wait_for(state="attached", timeout=10000)
            inp.fill(username)
        except Exception:
            pass
        time.sleep(2)

        # 4. Пароль
        print("[4] Пароль...")
        try:
            page.locator("#password").first.fill(password)
            page.locator("#password-confirm").first.fill(password)
        except Exception:
            pass
        time.sleep(1)

        # 5. Submit + закрытие upsell (в цикле пока не дойдём до капчи)
        print("[5] Submit...")
        for _ in range(20):
            # Upsell?
            try:
                nt = page.locator("button").filter(has_text=re.compile(r"нет.*спасибо|no.*thanks", re.I))
                if nt.count() > 0 and nt.first.is_visible():
                    nt.first.click(timeout=3000)
                    print("    Upsell закрыт")
                    time.sleep(2)
                    # Пароль мог сброситься
                    try:
                        page.locator("#password").first.fill(password)
                        page.locator("#password-confirm").first.fill(password)
                    except Exception:
                        pass
                    continue
            except Exception:
                pass

            # Капча уже есть?
            if _has_captcha(page):
                print("    Капча найдена!")
                break

            # Submit
            try:
                sub = page.locator("button").filter(has_text=re.compile(r"начать|start using|create account|get started", re.I))
                if sub.count() > 0 and sub.first.is_visible():
                    sub.first.click(timeout=5000)
                    print("    Submit нажат")
            except Exception:
                pass
            time.sleep(3)

        time.sleep(3)

        # 6. Сбор капч
        print("[6] Сбор капч...")
        while idx < goal:
            if not _has_captcha(page):
                # Может спиннер или экран выбора задачи — ждём
                for w in range(20):
                    if _has_captcha(page):
                        break
                    # Экран выбора "Решите головоломку" → Далее
                    _click_any_in_captcha(page, r"далее|next")
                    # Подтвердить после неудачи
                    _click_any(page, r"подтвердить|confirm|verify")
                    _click_any_in_captcha(page, r"подтвердить|confirm|verify")
                    time.sleep(1)
                else:
                    # Токен сгорел — закрываем модалку, submit заново
                    print("    [!] Капча пропала — перезапускаем...")
                    _click_any(page, r"закрыть|close")
                    time.sleep(2)
                    # Заполняем пароль (мог сброситься)
                    try:
                        page.locator("#password").first.fill(password)
                        page.locator("#password-confirm").first.fill(password)
                    except Exception:
                        pass
                    time.sleep(1)
                    # Submit
                    try:
                        sub = page.locator("button").filter(has_text=re.compile(r"начать|start using|create account|get started", re.I))
                        if sub.count() > 0 and sub.first.is_visible():
                            sub.first.click(timeout=5000)
                            print("    Submit повторный")
                    except Exception:
                        pass
                    time.sleep(5)
                    # Закрываем upsell если появился
                    try:
                        nt = page.locator("button").filter(has_text=re.compile(r"нет.*спасибо|no.*thanks", re.I))
                        if nt.count() > 0 and nt.first.is_visible():
                            nt.first.click(timeout=3000)
                            print("    Upsell закрыт")
                            time.sleep(3)
                            try:
                                page.locator("#password").first.fill(password)
                                page.locator("#password-confirm").first.fill(password)
                            except Exception:
                                pass
                            try:
                                sub = page.locator("button").filter(has_text=re.compile(r"начать|start using|create account|get started", re.I))
                                if sub.count() > 0 and sub.first.is_visible():
                                    sub.first.click(timeout=5000)
                                    print("    Submit повторный")
                            except Exception:
                                pass
                            time.sleep(5)
                    except Exception:
                        pass
                    continue

            # Скриншот captcha iframe
            img_bytes = _screenshot_captcha(page)
            if img_bytes:
                fname = f"captcha_{idx:04d}.png"
                with open(os.path.join(PHOTOS_DIR, fname), "wb") as f:
                    f.write(img_bytes)
                idx += 1
                print(f"    [{idx}/{goal}] {fname}")

            # Далее
            _click_any_in_captcha(page, r"далее|next")
            time.sleep(4)

            # Повторить — ищем везде (page + все frames)
            for w in range(20):
                clicked = False
                # Перебираем ВСЕ кнопки на page
                for b in page.locator("button").all():
                    try:
                        txt = b.inner_text(timeout=500).strip().lower()
                        if b.is_visible() and any(k in txt for k in ["повтор", "сброс", "retry", "reset", "подтвер", "confirm"]):
                            b.click(timeout=3000)
                            print(f"    Нажата: '{txt[:30]}' (page, wait={w})")
                            clicked = True
                            break
                    except Exception:
                        pass
                if clicked:
                    break
                # Перебираем кнопки в каждом frame
                for f in page.frames:
                    if f == page.main_frame:
                        continue
                    for b in f.locator("button").all():
                        try:
                            txt = b.inner_text(timeout=500).strip().lower()
                            if any(k in txt for k in ["повтор", "сброс", "retry", "reset", "подтвер", "confirm"]):
                                b.click(timeout=3000)
                                print(f"    Нажата: '{txt[:30]}' (frame, wait={w})")
                                clicked = True
                                break
                        except Exception:
                            pass
                    if clicked:
                        break
                if clicked:
                    break
                time.sleep(1)

            time.sleep(3)

        print(f"\nГотово! Собрано {idx} капч в {PHOTOS_DIR}/")
        browser.close()


def _has_captcha(page):
    """Есть ли видимый canvas в captcha frame."""
    for f in page.frames:
        if 'captcha' in f.url.lower():
            try:
                c = f.locator("canvas").first
                if c.is_visible():
                    return True
            except Exception:
                pass
    return False


def _screenshot_captcha(page):
    """Скриншот captcha iframe целиком."""
    for iframe_el in page.locator("iframe").all():
        try:
            src = iframe_el.get_attribute("src") or ""
            if "captcha" in src.lower():
                return iframe_el.screenshot(timeout=15000)
        except Exception:
            pass
    return None


def _click_any(page, pattern):
    """Кликнуть первую видимую кнопку на странице по паттерну."""
    try:
        btn = page.locator("button").filter(has_text=re.compile(pattern, re.I))
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click(timeout=3000)
            return True
    except Exception:
        pass
    # Fallback — get_by_role
    try:
        btn = page.get_by_role("button", name=re.compile(pattern, re.I))
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click(timeout=3000)
            return True
    except Exception:
        pass
    return False


def _click_any_in_captcha(page, pattern):
    """Кликнуть кнопку внутри captcha frame."""
    for f in page.frames:
        if 'captcha' in f.url.lower():
            try:
                btn = f.locator("button").filter(has_text=re.compile(pattern, re.I))
                if btn.count() > 0:
                    btn.first.click(timeout=3000)
                    return True
            except Exception:
                pass
    return False


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy", default=DEFAULT_PROXY)
    ap.add_argument("--count", default=1000, type=int)
    args = ap.parse_args()
    run(proxy_str=args.proxy, count=args.count)
