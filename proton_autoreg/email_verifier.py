"""
Верификация через email: логинимся в Proton webmail, читаем код из письма.
"""
import re
import time
import random
import threading
from playwright.sync_api import sync_playwright

VERIFY_EMAIL    = "lucas.brown7422@proton.me"
VERIFY_PASSWORD = "SmKrq4ggcSha8T%H"


def _fetch_code_proton(since_time: float, wait: int, result: list) -> None:
    """Запускается в отдельном потоке — свой sync_playwright."""
    with sync_playwright() as pw:
        browser = pw.firefox.launch(headless=True)
        ctx  = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        try:
            print("    [proton-inbox] Логинимся...")
            page.goto("https://account.proton.me/login", timeout=30_000, wait_until="domcontentloaded")
            time.sleep(3)

            # Username и пароль — на одной странице
            email_inp = page.locator('#username, input[name="username"]').first
            email_inp.wait_for(state="visible", timeout=15_000)
            email_inp.fill(VERIFY_EMAIL)
            time.sleep(0.5)

            pwd_inp = page.locator('#password, input[type="password"]').first
            pwd_inp.wait_for(state="visible", timeout=10_000)
            pwd_inp.fill(VERIFY_PASSWORD)
            time.sleep(0.5)

            # Нажимаем Sign in
            sign_in = page.locator('button[type="submit"]').first
            if sign_in.count() > 0:
                sign_in.evaluate("el => el.click()")
            else:
                page.keyboard.press("Enter")
            time.sleep(15)

            page.screenshot(path="debug_proton_inbox_login.png")
            print(f"    [proton-inbox] URL после логина: {page.url}")

            # Переходим в inbox
            page.goto("https://mail.proton.me/u/0/inbox", timeout=30_000, wait_until="domcontentloaded")
            time.sleep(5)
            inbox_url = page.url
            print(f"    [proton-inbox] Inbox URL: {inbox_url}")
            deadline  = time.time() + wait

            while time.time() < deadline:
                page.screenshot(path="debug_proton_inbox.png")

                # Ищем письмо с кодом верификации
                rows = page.locator('[data-shortcut-target="item-container"], [class*="conversation-item"], [class*="message-item"]').all()
                for row in rows:
                    try:
                        txt = row.inner_text(timeout=300).lower()
                        if "proton" in txt or "verification" in txt or "верифик" in txt:
                            row.evaluate("el => el.click()")
                            time.sleep(2)
                            body = page.locator("body").inner_text(timeout=5_000)
                            match = re.search(r"\b(\d{6})\b", body)
                            if match:
                                print(f"    [proton-inbox] Код: {match.group(1)}")
                                result[0] = match.group(1)
                                return
                    except Exception:
                        continue

                # Обновляем inbox
                remaining = int(deadline - time.time())
                print(f"    [proton-inbox] Письма нет, ждём... ({remaining}с)")
                try:
                    page.goto(inbox_url, timeout=15_000, wait_until="domcontentloaded")
                    time.sleep(5)
                except Exception:
                    time.sleep(5)

            print("    [proton-inbox] Код не найден")

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"    [proton-inbox] Ошибка: {e}")
        finally:
            try:
                ctx.close()
                browser.close()
            except Exception:
                pass


def _fetch_code(since_time: float, wait: int = 90) -> str | None:
    result = [None]
    t = threading.Thread(target=_fetch_code_proton, args=(since_time, wait, result), daemon=True)
    t.start()
    t.join(timeout=wait + 30)
    return result[0]


def solve_via_email(page) -> bool:
    """
    Кликает таб 'Эл. почта' в диалоге верификации Proton,
    вводит ящик для верификации, получает код автоматически, вводит его.
    """
    print("  [email-verify] Кликаем таб 'Эл. почта'...")
    try:
        email_tab = page.locator("button, [role='tab']").filter(
            has_text=re.compile(r"эл\.?\s*почта|email|почта", re.I)
        )
        email_tab.first.wait_for(state="visible", timeout=5_000)
        email_tab.first.evaluate("el => el.click()")
        time.sleep(random.uniform(0.8, 1.2))
        page.screenshot(path="debug_verify_email_tab.png")
    except Exception as e:
        print(f"    [email-verify] Таб не найден: {e}")
        return False

    print(f"  [email-verify] Вводим {VERIFY_EMAIL}...")
    try:
        inp = page.locator('[role="dialog"] input[type="email"], [role="dialog"] input[type="text"]').first
        if inp.count() == 0:
            inp = page.locator('input[type="email"]').first
        inp.wait_for(state="visible", timeout=5_000)
        inp.fill(VERIFY_EMAIL)
        time.sleep(random.uniform(0.4, 0.7))
    except Exception as e:
        print(f"    [email-verify] Поле email не найдено: {e}")
        return False

    send_time = time.time()

    print("  [email-verify] Отправляем запрос кода...")
    try:
        send_btn = page.locator("button").filter(
            has_text=re.compile(r"получить.*код|send.*code|отправить|verify email|далее|next", re.I)
        )
        if send_btn.count() > 0:
            send_btn.first.evaluate("el => el.click()")
        else:
            page.keyboard.press("Enter")
        time.sleep(1)
    except Exception as e:
        print(f"    [email-verify] Кнопка отправки: {e}")

    print("  [email-verify] Ждём код в Proton inbox...")
    code = _fetch_code(since_time=send_time, wait=90)

    if not code:
        print("  [email-verify] Код не получен")
        return False

    print(f"  [email-verify] Вводим код: {code}")
    try:
        code_inp = page.locator('input[maxlength="6"], input[placeholder*="код"], input[placeholder*="code"]').first
        if code_inp.count() == 0:
            code_inp = page.locator('[role="dialog"] input').first
        code_inp.wait_for(state="visible", timeout=5_000)
        code_inp.fill(code)
        time.sleep(random.uniform(0.3, 0.5))

        confirm = page.locator("button").filter(
            has_text=re.compile(r"подтвердить|confirm|verify|далее|next", re.I)
        )
        if confirm.count() > 0:
            confirm.first.evaluate("el => el.click()")
        else:
            page.keyboard.press("Enter")

        print("  [email-verify] Готово")
        return True
    except Exception as e:
        print(f"    [email-verify] Ввод кода: {e}")
        return False
