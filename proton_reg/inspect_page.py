from playwright.sync_api import sync_playwright
import time

with sync_playwright() as pw:
    browser = pw.firefox.launch(
        headless=False,
        proxy={"server": "http://45.144.179.21:15382", "username": "b8zu5pt2", "password": "7q3cadno"}
    )
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-US")
    page = ctx.new_page()

    try:
        page.goto("https://account.proton.me/mail/signup", timeout=45000, wait_until="networkidle")
    except Exception:
        pass

    time.sleep(6)
    page.screenshot(path="debug_inspect.png")
    print("URL:", page.url)
    print("Title:", page.title())
    print()

    # Сохраняем полный HTML для анализа
    with open("debug_inspect.html", "w", encoding="utf-8") as f:
        f.write(page.content())
    print("HTML сохранён в debug_inspect.html, len:", len(page.content()))

    # Выводим все кнопки через locator
    print("\n--- BUTTONS ---")
    for btn in page.locator("button").all():
        try:
            txt = btn.inner_text(timeout=300).strip().replace("\n", " ")
            cls = btn.get_attribute("class") or ""
            tid = btn.get_attribute("data-testid") or ""
            print(f"  text={txt[:60]!r:60} | testid={tid:30} | cls={cls[:50]}")
        except Exception:
            pass

    input("Нажми Enter для закрытия...")
    browser.close()
