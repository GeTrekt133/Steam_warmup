"""
Регистрация Steam через Playwright Firefox (проверенный подход из proton_reg).
hCaptcha решается через hcaptchasolver.com API, токен вставляется через page.evaluate().
Proton остаётся в CV Chrome, Steam — отдельный Playwright.
"""
import re
import time
import logging

import httpx
from playwright.sync_api import sync_playwright, Page, Browser

from proton_cv import gen_username, gen_password

logger = logging.getLogger(__name__)

STEAM_SITEKEY = "e18a349a-46c2-46a0-87a8-74be79345c92"

HCAPTCHA_KEY = "Kenzx_fe6d404383507753a5bf0f849192fd835084d2e1795aaf78"
HCAPTCHA_API = "https://hcaptchasolver.com/api"


class SteamPlaywright:
    """Регистрация Steam через Playwright Firefox + hcaptchasolver.com API."""

    def __init__(self, proxy: str | None = None):
        self.proxy = proxy
        self._pw = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    def _start_browser(self) -> Page:
        """Запустить Playwright Firefox."""
        self._pw = sync_playwright().start()

        proxy_config = None
        if self.proxy:
            p = self.proxy.strip()
            if "@" in p:
                creds, host = p.rsplit("@", 1)
                user, pwd = creds.split(":", 1)
                proxy_config = {
                    "server": f"http://{host}",
                    "username": user,
                    "password": pwd,
                }
            else:
                proxy_config = {"server": f"http://{p}"}

        self._browser = self._pw.firefox.launch(
            headless=False,
            proxy=proxy_config,
        )
        context = self._browser.new_context()
        self._page = context.new_page()
        return self._page

    def close(self):
        """Закрыть браузер."""
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    # ── hCaptcha через API ───────────────────────────────────────────

    def _solve_hcaptcha_api(self, sitekey: str) -> str | None:
        """Решить hCaptcha через hcaptchasolver.com API."""
        logger.info("[Steam] [hcaptcha] Создаю задачу...")

        task = {
            "type": "PopularCaptchaTaskProxyless",
            "websiteURL": "https://store.steampowered.com/join",
            "websiteKey": sitekey,
        }

        if self.proxy:
            s = self.proxy.strip()
            if "@" in s:
                creds, host = s.rsplit("@", 1)
                user, pwd = creds.split(":", 1)
                ip, port = host.split(":", 1)
                task = {
                    "type": "PopularCaptchaTask",
                    "websiteURL": "https://store.steampowered.com/join",
                    "websiteKey": sitekey,
                    "proxyType": "http",
                    "proxyAddress": ip,
                    "proxyPort": int(port),
                    "proxyLogin": user,
                    "proxyPassword": pwd,
                }

        try:
            resp = httpx.post(f"{HCAPTCHA_API}/createTask", json={
                "clientKey": HCAPTCHA_KEY,
                "task": task,
            }, timeout=30)
            data = resp.json()
            task_id = data.get("taskId")
            if not task_id:
                logger.error(f"[Steam] [hcaptcha] Ошибка: {data}")
                return None
            logger.info(f"[Steam] [hcaptcha] Задача: {task_id}")

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
                    token = (data.get("solution", {}).get("token")
                             or data.get("solution", {}).get("gRecaptchaResponse"))
                    elapsed = time.monotonic() - start
                    logger.info(f"[Steam] [hcaptcha] Решена за {elapsed:.1f}с, токен: {token[:80]}...")
                    return token
                if status == "processing":
                    time.sleep(2)
                    continue
                logger.error(f"[Steam] [hcaptcha] Ошибка: {data}")
                return None

            logger.error("[Steam] [hcaptcha] Таймаут (180с)")
            return None
        except Exception as e:
            logger.error(f"[Steam] [hcaptcha] Исключение: {e}")
            return None

    # ── Полный flow ──────────────────────────────────────────────────

    def register(self, email: str, username: str, password: str) -> dict:
        """
        Полный flow регистрации Steam через Playwright.

        Returns:
            {"ok": bool, "username": str, "password": str, "steam_id": str, "msg": str}
        """
        logger.info(f"[Steam] === Регистрация: {username} ({email}) ===")

        try:
            page = self._start_browser()

            # ── 1. Открыть страницу ──────────────────────────────────
            logger.info("[Steam] [1] Загрузка join...")
            try:
                page.goto("https://store.steampowered.com/join",
                          timeout=60_000, wait_until="networkidle")
            except Exception:
                pass
            time.sleep(4)

            # ── 2. Извлечь sitekey + запустить решение captcha ПАРАЛЛЕЛЬНО ──
            sitekey = STEAM_SITEKEY
            try:
                hcap_frame = page.locator('iframe[src*="hcaptcha"]').first
                if hcap_frame.count() > 0:
                    src = hcap_frame.get_attribute("src") or ""
                    m = re.search(r'sitekey=([a-f0-9-]+)', src)
                    if m:
                        sitekey = m.group(1)
                        logger.info(f"[Steam] Sitekey из iframe: {sitekey}")
            except Exception:
                pass

            # Запускаем решение captcha в отдельном потоке
            import concurrent.futures
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            captcha_future = executor.submit(self._solve_hcaptcha_api, sitekey)
            logger.info("[Steam] [2] hCaptcha решается в фоне...")

            # ── 3. Пока captcha решается — заполняем форму ───────────
            logger.info(f"[Steam] [3] Email: {email}")
            inputs = page.locator("input[type='text'], input[type='email'], input:not([type])").all()
            filled = 0
            for inp in inputs[:5]:
                try:
                    name = inp.get_attribute("name") or ""
                    id_ = inp.get_attribute("id") or ""
                    placeholder = inp.get_attribute("placeholder") or ""
                    if any(k in (name + id_ + placeholder).lower() for k in ["email", "mail"]):
                        inp.fill(email)
                        filled += 1
                        time.sleep(0.3)
                except Exception:
                    pass
            if filled == 0:
                for inp in inputs[:2]:
                    try:
                        inp.fill(email)
                        filled += 1
                    except Exception:
                        pass
            logger.info(f"[Steam] Email полей заполнено: {filled}")
            time.sleep(1)

            # ── 4. Чекбокс (если есть) ───────────────────────────────
            logger.info("[Steam] [4] Чекбоксы...")
            try:
                agree_cb = page.locator("#i_agree_check").first
                if agree_cb.count() > 0 and not agree_cb.is_checked():
                    agree_cb.click(timeout=3000)
                    logger.info("[Steam] Чекбокс i_agree_check")
                    time.sleep(1)
            except Exception:
                pass

            try:
                cb = page.locator("input[type='checkbox']").first
                if cb.count() > 0 and not cb.is_checked():
                    cb.click(timeout=3000)
                    logger.info("[Steam] Чекбокс (fallback)")
                    time.sleep(1)
            except Exception:
                pass

            page.screenshot(path="debug_steam_02_after_email.png")

            # ── 5. Ждём captcha токен ────────────────────────────────
            logger.info("[Steam] [5] Ожидание captcha токена...")
            captcha_token = captcha_future.result(timeout=180)
            executor.shutdown(wait=False)

            if not captcha_token:
                return {"ok": False, "username": username, "password": password,
                        "msg": "hCaptcha не решена"}

            # Сразу вставить токен и submit (минимум задержки!)
            logger.info("[Steam] [6] Вставляю токен + Submit...")
            page.evaluate(f"""() => {{
                const token = "{captcha_token}";
                window.CaptchaText = function() {{ return token; }};
                if (typeof hcaptcha !== 'undefined') {{
                    hcaptcha.getResponse = function() {{ return token; }};
                }}
            }}""")
            page.evaluate("StartCreationSession()")
            time.sleep(5)

            # ── 7. Скриншот после submit ─────────────────────────────
            page.screenshot(path="debug_steam_after_submit.png")
            logger.info("[Steam] [7] Проверяю результат...")

            # Попап возраста (может не быть)
            for _ in range(5):
                try:
                    older = page.locator("a, button").filter(
                        has_text=re.compile(r"больше|older|over|or more|mehr|plus", re.I))
                    if older.count() > 0:
                        older.first.click(timeout=2000)
                        logger.info("[Steam] Возраст (попап) подтверждён")
                        time.sleep(3)
                        break
                except Exception:
                    pass
                time.sleep(1)

            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(0.5)
            page.screenshot(path="debug_steam_after_age.png")

            # Проверяем результат
            body = ""
            try:
                body = page.locator("body").inner_text(timeout=3000).lower()
            except Exception:
                pass

            if "неверный" in body or "invalid" in body or "captcha" in body:
                return {"ok": False, "username": username, "password": password,
                        "msg": "Steam: неверный ответ CAPTCHA"}

            waiting_email = ("verify" in body or "подтвер" in body or
                             "check your email" in body or "проверьте" in body)
            if waiting_email:
                logger.info("[Steam] Steam просит подтвердить email!")

            # Получить creation_id
            creation_id = ""
            try:
                creation_id = page.evaluate(
                    "() => typeof g_creationSessionID !== 'undefined' ? g_creationSessionID : ''"
                ) or ""
                if creation_id:
                    logger.info(f"[Steam] creation_id={creation_id}")
            except Exception:
                pass

            return {
                "ok": True,
                "stage": "email_sent",
                "username": username,
                "password": password,
                "creation_id": creation_id,
                "msg": "Email отправлен, ожидание подтверждения",
            }

        except Exception as e:
            logger.error(f"[Steam] Ошибка: {e}", exc_info=True)
            return {"ok": False, "username": username, "password": password, "msg": str(e)}

    def complete_after_email_verification(self, username: str, password: str, creation_id: str = "") -> dict:
        """Создать аккаунт после подтверждения email."""
        logger.info(f"[Steam] Создание аккаунта: {username}")
        page = self._page

        if not page:
            return {"ok": False, "username": username, "password": password,
                    "msg": "Браузер не запущен"}

        try:
            # Создаём через fetch в браузере (cookies совпадают)
            if creation_id:
                result = page.evaluate(f"""async () => {{
                    try {{
                        const formData = new URLSearchParams();
                        formData.append('accountname', '{username}');
                        formData.append('password', '{password}');
                        formData.append('count', '32');
                        formData.append('lt', '0');
                        formData.append('creation_sessionid', '{creation_id}');
                        const resp = await fetch('https://store.steampowered.com/join/createaccount/', {{
                            method: 'POST',
                            body: formData,
                            headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
                        }});
                        return await resp.json();
                    }} catch(e) {{ return {{ bSuccess: false, details: e.message }}; }}
                }}""")

                logger.info(f"[Steam] createaccount: {result}")

                if result and result.get("bSuccess"):
                    steam_id = str(result.get("steamid", ""))
                    logger.info(f"[Steam] Аккаунт создан! SteamID: {steam_id}")
                    return {
                        "ok": True,
                        "username": username,
                        "password": password,
                        "steam_id": steam_id,
                        "msg": "Аккаунт создан",
                    }
                else:
                    error = str(result.get("details", result)) if result else "Empty response"
                    return {"ok": False, "username": username, "password": password, "msg": error}

            # Fallback: заполнить форму если нет creation_id
            logger.info("[Steam] Нет creation_id, заполняю форму...")
            time.sleep(3)
            page.screenshot(path="debug_steam_after_verify.png")

            # Ищем поля username/password
            inputs = page.locator("input[type='text'], input[type='password']").all()
            for inp in inputs:
                try:
                    name = inp.get_attribute("name") or ""
                    itype = inp.get_attribute("type") or ""
                    if "accountname" in name or "login" in name:
                        inp.fill(username)
                    elif itype == "password":
                        inp.fill(password)
                except Exception:
                    pass

            # Submit
            try:
                done_btn = page.locator("button, input[type='submit']").filter(
                    has_text=re.compile(r"Done|Complete|Create|Готово|Создать", re.I))
                if done_btn.count() > 0:
                    done_btn.first.click(timeout=5000)
            except Exception:
                pass

            time.sleep(5)
            page.screenshot(path="debug_steam_account_created.png")
            return {
                "ok": True,
                "username": username,
                "password": password,
                "msg": "Аккаунт создан (форма)",
            }

        except Exception as e:
            logger.error(f"[Steam] Ошибка создания: {e}", exc_info=True)
            return {"ok": False, "username": username, "password": password, "msg": str(e)}
