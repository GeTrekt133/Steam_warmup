"""
Steam Guard Linker — привязка Steam Guard Mobile Authenticator (аналог SDA).

Flow (без SMS, через email):
1. Логин в Steam API (RSA + email Steam Guard код)
2. AddAuthenticator → shared_secret, identity_secret, revocation_code
3. FinalizeAddAuthenticator → подтверждение кодом из email
4. Сохранение maFile в формате SDA

Требует email:password аккаунта для получения кодов подтверждения через IMAP.
"""

import asyncio
import base64
import imaplib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from functools import partial

import requests
from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from cryptography.hazmat.backends import default_backend

from app.services.steam_guard import generate_steam_guard_code
from app.services.email_service import IMAP_HOSTS

logger = logging.getLogger(__name__)

STEAM_API = "https://api.steampowered.com"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


# --- Dataclasses ---


@dataclass
class MaFileData:
    """maFile в формате SDA (Steam Desktop Authenticator)."""
    shared_secret: str = ""
    serial_number: str = ""
    revocation_code: str = ""
    uri: str = ""
    server_time: str = ""
    account_name: str = ""
    token_gid: str = ""
    identity_secret: str = ""
    secret_1: str = ""
    status: int = 0
    steam_id: str = ""

    def to_dict(self) -> dict:
        return {
            "shared_secret": self.shared_secret,
            "serial_number": self.serial_number,
            "revocation_code": self.revocation_code,
            "uri": self.uri,
            "server_time": self.server_time,
            "account_name": self.account_name,
            "token_gid": self.token_gid,
            "identity_secret": self.identity_secret,
            "secret_1": self.secret_1,
            "status": self.status,
            "SteamID": self.steam_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class LinkStep:
    name: str
    status: str = "pending"  # pending, running, done, error
    detail: str | None = None


@dataclass
class LinkResult:
    success: bool = False
    mafile: MaFileData | None = None
    revocation_code: str | None = None
    error: str | None = None
    steps: list[LinkStep] = field(default_factory=list)


# --- RSA ---


def _encrypt_password_rsa(password: str, mod_hex: str, exp_hex: str) -> str:
    """Зашифровать пароль RSA public key от Steam (PKCS1v15)."""
    mod = int(mod_hex, 16)
    exp = int(exp_hex, 16)
    public_key = RSAPublicNumbers(exp, mod).public_key(default_backend())
    encrypted = public_key.encrypt(password.encode("utf-8"), rsa_padding.PKCS1v15())
    return base64.b64encode(encrypted).decode("utf-8")


# --- Email helpers ---


def _imap_connect(email: str, email_password: str) -> imaplib.IMAP4_SSL | None:
    """Подключиться к IMAP. Возвращает server или None."""
    domain = email.split("@")[-1].lower()
    imap_host = IMAP_HOSTS.get(domain)
    if not imap_host:
        logger.error("Неизвестный IMAP-хост для домена: %s", domain)
        return None
    try:
        server = imaplib.IMAP4_SSL(imap_host)
        server.login(email, email_password)
        server.select("INBOX")
        return server
    except Exception as e:
        logger.error("IMAP login failed for %s: %s", email, e)
        return None


def _fetch_code_from_imap(
    email: str,
    email_password: str,
    pattern: re.Pattern,
    max_attempts: int = 10,
    wait_sec: int = 5,
    description: str = "code",
) -> str | None:
    """
    Универсальный fetch кода из email через IMAP.

    Ищет regex pattern в последних письмах.
    """
    server = _imap_connect(email, email_password)
    if not server:
        return None

    try:
        for attempt in range(1, max_attempts + 1):
            logger.info(
                "Ищем %s в email %s (попытка %d/%d)...",
                description, email, attempt, max_attempts,
            )
            _, data = server.search(None, "ALL")
            if not data[0]:
                time.sleep(wait_sec)
                continue

            uids = data[0].split()
            # Проверяем последние 5 писем (новые → старые)
            for uid in reversed(uids[-5:]):
                _, msg_data = server.uid("fetch", uid, "(BODY[TEXT])")
                if not msg_data or not msg_data[0]:
                    continue
                try:
                    body = msg_data[0][1].decode("utf-8", errors="ignore")
                except (IndexError, AttributeError):
                    continue

                match = pattern.search(body)
                if match:
                    code = match.group(1)
                    logger.info("Найден %s: %s", description, code)
                    return code

            time.sleep(wait_sec)

    finally:
        try:
            server.close()
            server.logout()
        except Exception:
            pass

    logger.error("%s не найден после %d попыток", description, max_attempts)
    return None


# Паттерн для Steam Guard email-кода (5 символов, приходит при логине)
# Ищем код после характерных фраз, код должен быть отдельным словом (word boundary)
_LOGIN_CODE_PATTERN = re.compile(
    r"(?:"
    r"Steam\s*Guard\s*code[^A-Z0-9]*"
    r"|login\s*code[^A-Z0-9]*"
    r"|код\s*(?:для\s*)?входа[^A-Z0-9]*"
    r"|access\s*(?:your\s*)?account[^A-Z0-9]*"
    r")(\b[A-Z0-9]{5}\b)",
    re.IGNORECASE,
)

# Паттерн для кода активации authenticator (приходит после AddAuthenticator)
_ACTIVATION_CODE_PATTERN = re.compile(
    r"(?:"
    r"activation\s*code[^A-Z0-9]*"
    r"|код\s*активации[^A-Z0-9]*"
    r"|confirmation\s*code[^A-Z0-9]*"
    r"|verify.*?code[^A-Z0-9]*"
    r"|your\s*code\s*is[^A-Z0-9]*"
    r"|provide\s*the\s*following\s*code[^A-Z0-9]*"
    r"|adding\s*your\s*authenticator[^A-Z0-9]*"
    r"|complete\s*adding[^A-Z0-9]*"
    r")(\b[A-Z0-9]{5}\b)",
    re.IGNORECASE,
)


# --- Main linker ---


class SteamGuardLinker:
    """
    Привязка Steam Guard Mobile Authenticator без SMS (через email).

    Usage:
        linker = SteamGuardLinker()
        result = await linker.link(
            login="steamuser",
            password="password123",
            email="user@mail.com",
            email_password="emailpass",
        )
        if result.success:
            print(result.mafile.to_json())
            print(f"Revocation code: {result.revocation_code}")
    """

    def __init__(self, proxy: dict | None = None, email_provider: str = "auto"):
        self._proxy = proxy
        self._email_provider = email_provider  # "imap", "outlook_web", "auto"

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        if self._proxy:
            session.proxies = self._proxy
        return session

    # --- Steam API calls (синхронные, будут запускаться в executor) ---

    def _get_rsa_key(self, session: requests.Session, account_name: str) -> dict:
        resp = session.get(
            f"{STEAM_API}/IAuthenticationService/GetPasswordRSAPublicKey/v1",
            params={"account_name": account_name},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("response", {})

    def _begin_auth_session(
        self, session: requests.Session,
        account_name: str, encrypted_password: str, timestamp: str,
    ) -> dict:
        resp = session.post(
            f"{STEAM_API}/IAuthenticationService/BeginAuthSessionViaCredentials/v1",
            data={
                "account_name": account_name,
                "encrypted_password": encrypted_password,
                "encryption_timestamp": timestamp,
                "device_friendly_name": "Steam Farming Panel",
                "platform_type": "2",
                "persistence": "1",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("response", {})

    def _submit_steam_guard_code(
        self, session: requests.Session,
        client_id: str, steamid: str, code: str, code_type: int = 2,
    ) -> None:
        """code_type: 2=email, 5=totp"""
        resp = session.post(
            f"{STEAM_API}/IAuthenticationService/UpdateAuthSessionWithSteamGuardCode/v1",
            data={
                "client_id": client_id,
                "steamid": steamid,
                "code": code,
                "code_type": str(code_type),
            },
            timeout=15,
        )
        resp.raise_for_status()

    def _poll_auth_status(
        self, session: requests.Session, client_id: str, request_id: str,
    ) -> dict:
        resp = session.post(
            f"{STEAM_API}/IAuthenticationService/PollAuthSessionStatus/v1",
            data={
                "client_id": client_id,
                "request_id": request_id,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("response", {})

    def _add_authenticator(
        self, session: requests.Session, steamid: str, access_token: str,
    ) -> dict:
        device_id = f"android:{uuid.uuid4()}"
        resp = session.post(
            f"{STEAM_API}/ITwoFactorService/AddAuthenticator/v1",
            params={"access_token": access_token},
            data={
                "steamid": steamid,
                "authenticator_time": str(int(time.time())),
                "authenticator_type": "1",
                "device_identifier": device_id,
                "sms_phone_id": "1",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("response", {})

    def _finalize_authenticator(
        self, session: requests.Session,
        steamid: str, access_token: str,
        authenticator_code: str, activation_code: str,
    ) -> dict:
        resp = session.post(
            f"{STEAM_API}/ITwoFactorService/FinalizeAddAuthenticator/v1",
            params={"access_token": access_token},
            data={
                "steamid": steamid,
                "authenticator_code": authenticator_code,
                "authenticator_time": str(int(time.time())),
                "activation_code": activation_code,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("response", {})

    def _fetch_email_code(self, email: str, email_password: str,
                          pattern: re.Pattern, max_attempts: int = 10,
                          wait_sec: int = 5, description: str = "code") -> str | None:
        """Получить код из email через выбранный провайдер."""
        provider = self._email_provider

        # Auto-detect: Outlook → web, остальные → IMAP
        if provider == "auto":
            domain = email.split("@")[-1].lower()
            if domain in ("outlook.com", "hotmail.com", "live.com"):
                provider = "outlook_web"
            else:
                provider = "imap"

        if provider == "outlook_web":
            from app.services.outlook_web_provider import fetch_code_from_outlook_web
            return fetch_code_from_outlook_web(
                email, email_password, pattern,
                max_attempts=max_attempts, wait_sec=wait_sec, description=description,
            )
        else:
            return _fetch_code_from_imap(
                email, email_password, pattern,
                max_attempts=max_attempts, wait_sec=wait_sec, description=description,
            )

    # --- Full flow ---

    def _login_via_playwright(
        self, login: str, password: str, email: str, email_password: str,
    ) -> tuple[str, str]:
        """
        Логин в Steam через Playwright + получение email кода из Outlook.
        Всё в одном браузере, две вкладки: Tab1=Steam, Tab2=Outlook.
        Возвращает (access_token, steamid).
        """
        from playwright.sync_api import sync_playwright
        from app.services.steam_browser import _ensure_proactor

        _ensure_proactor()
        pw = None
        browser = None

        try:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=False)
            context = browser.new_context(viewport={"width": 1280, "height": 800}, locale="en-US")

            # === Tab 1: Steam Login ===
            steam_page = context.new_page()
            steam_page.goto("https://store.steampowered.com/login", wait_until="domcontentloaded", timeout=30000)

            login_form = steam_page.locator('[data-featuretarget="login"]')
            login_form.wait_for(state="visible", timeout=15000)

            login_input = login_form.locator('input[type="text"]').first
            login_input.wait_for(state="visible", timeout=10000)
            login_input.fill(login)

            password_input = login_form.locator('input[type="password"]').first
            password_input.fill(password)

            submit_btn = login_form.locator('button[type="submit"]').first
            submit_btn.click()
            time.sleep(5)

            logger.info("[login-pw] %s: логин отправлен, открываем Outlook...", login)

            # === Tab 2: Outlook Login + читаем код ===
            outlook_page = context.new_page()
            outlook_page.goto("https://login.live.com/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            # Email
            email_input = outlook_page.locator('input[type="email"], input[name="loginfmt"]').first
            if email_input.count() > 0:
                email_input.fill(email)
                time.sleep(1)
                outlook_page.locator('input[type="submit"], button[type="submit"]').first.click()
                time.sleep(3)

            # Password
            pwd_input = outlook_page.locator('input[type="password"], input[name="passwd"]').first
            if pwd_input.count() > 0 and pwd_input.is_visible():
                pwd_input.fill(email_password)
                time.sleep(1)
                outlook_page.locator('input[type="submit"], button[type="submit"]').first.click()
                time.sleep(3)

            # "Stay signed in?" — No
            try:
                no_btn = outlook_page.locator('#idBtn_Back, input[value="No"]').first
                if no_btn.count() > 0 and no_btn.is_visible():
                    no_btn.click()
                    time.sleep(2)
            except Exception:
                pass

            logger.info("[login-pw] %s: Outlook залогинен", login)

            # Переходим в inbox (с fallback если редирект)
            outlook_page.goto("https://outlook.live.com/mail/0/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)
            # Если редирект на microsoft.com — пробуем другой URL
            if "microsoft.com" in outlook_page.url and "outlook.live.com" not in outlook_page.url:
                logger.info("[login-pw] %s: редирект на %s, пробуем другой URL...", login, outlook_page.url)
                outlook_page.goto("https://outlook.office.com/mail/inbox", wait_until="domcontentloaded", timeout=30000)
                time.sleep(5)
            if "microsoft.com" in outlook_page.url and "outlook" not in outlook_page.url:
                # Ещё один fallback
                outlook_page.goto("https://outlook.live.com/", wait_until="domcontentloaded", timeout=30000)
                time.sleep(5)
            time.sleep(3)

            # Ищем код в письмах — ждём терпеливо, обновляем редко
            email_code = None
            for attempt in range(1, 20):
                logger.info("[login-pw] %s: ищем login code (попытка %d)...", login, attempt)

                # Кликаем на первое письмо от Steam/Guard
                outlook_page.evaluate("""
                    () => {
                        const items = document.querySelectorAll('[role="option"], [role="listitem"], [data-convid]');
                        for (const item of items) {
                            const text = item.textContent || '';
                            if (text.includes('Steam') || text.includes('Guard')) {
                                item.click(); return true;
                            }
                        }
                        if (items.length > 0) items[0].click();
                        return false;
                    }
                """)
                time.sleep(5)

                # Читаем весь текст страницы (включая открытое письмо)
                body_text = outlook_page.evaluate("() => document.body.innerText || ''")
                if body_text:
                    # Основной паттерн
                    match = _LOGIN_CODE_PATTERN.search(body_text)
                    if match:
                        email_code = match.group(1)
                        logger.info("[login-pw] %s: код найден (pattern): %s", login, email_code)
                        break

                    # Fallback — ищем изолированный 5-символьный код [A-Z0-9]
                    # рядом со словами Steam/Guard/code/account
                    if "Steam" in body_text or "Guard" in body_text:
                        fallback = re.findall(r'\b([A-Z0-9]{5})\b', body_text)
                        # Фильтруем — код не должен быть обычным словом
                        for candidate in fallback:
                            # Пропускаем слова: Steam, Guard, etc
                            if candidate in ("STEAM", "GUARD", "EMAIL", "VALVE"):
                                continue
                            # Код содержит и буквы и цифры обычно
                            has_digit = any(c.isdigit() for c in candidate)
                            has_letter = any(c.isalpha() for c in candidate)
                            if has_digit and has_letter:
                                email_code = candidate
                                logger.info("[login-pw] %s: код найден (fallback): %s", login, email_code)
                                break
                        if email_code:
                            break

                # Обновляем inbox каждые 3 попытки (не каждую)
                if attempt % 3 == 0:
                    outlook_page.goto("https://outlook.live.com/mail/0/", wait_until="domcontentloaded", timeout=20000)
                    time.sleep(8)
                else:
                    time.sleep(5)

            if not email_code:
                raise RuntimeError("Email код для входа не найден")

            # === Переключаемся на Tab 1 (Steam) и вводим код ===
            steam_page.bring_to_front()
            time.sleep(1)

            char_inputs = steam_page.locator('input[maxlength="1"][type="text"]')
            count = char_inputs.count()
            if count >= 5:
                for i in range(min(len(email_code), count)):
                    char_inputs.nth(i).click()
                    char_inputs.nth(i).fill(email_code[i])
                    time.sleep(0.1)
                time.sleep(5)

            steam_page.wait_for_load_state("networkidle", timeout=15000)
            logger.info("[login-pw] %s: залогинен в Steam, URL=%s", login, steam_page.url)

            # Извлекаем access_token из cookies
            cookies = context.cookies("https://store.steampowered.com")
            access_token = ""
            steamid = ""

            for cookie in cookies:
                if cookie["name"] == "steamLoginSecure":
                    value = cookie["value"]
                    parts = value.split("%7C%7C")
                    if len(parts) == 2:
                        steamid = parts[0]
                        access_token = parts[1]
                    break

            if not access_token:
                raise RuntimeError("access_token не найден в cookies")

            logger.info("[login-pw] %s: token получен, steamid=%s", login, steamid)
            # НЕ закрываем браузер — возвращаем всё для переиспользования
            return access_token, steamid, outlook_page, pw, browser

        except Exception:
            # При ошибке — закрываем
            if browser:
                try: browser.close()
                except Exception: pass
            if pw:
                try: pw.stop()
                except Exception: pass
            raise

    def _read_code_from_outlook_page(self, outlook_page, pattern, login, description="code", max_attempts=15):
        """Читает код из уже открытой вкладки Outlook."""
        for attempt in range(1, max_attempts + 1):
            logger.info("[outlook] %s: ищем %s (попытка %d)...", login, description, attempt)

            # Кликаем на письмо от Steam
            outlook_page.evaluate("""
                () => {
                    const items = document.querySelectorAll('[role="option"], [role="listitem"], [data-convid]');
                    for (const item of items) {
                        const text = item.textContent || '';
                        if (text.includes('Steam') || text.includes('Guard') || text.includes('authenticator')) {
                            item.click(); return true;
                        }
                    }
                    if (items.length > 0) items[0].click();
                    return false;
                }
            """)
            time.sleep(5)

            body_text = outlook_page.evaluate("() => document.body.innerText || ''")
            if body_text:
                match = pattern.search(body_text)
                if match:
                    code = match.group(1)
                    logger.info("[outlook] %s: %s найден: %s", login, description, code)
                    return code

                # Fallback — изолированный 5-символьный код рядом со Steam
                if "Steam" in body_text or "authenticator" in body_text.lower():
                    fallback = re.findall(r'\b([A-Z0-9]{5})\b', body_text)
                    for candidate in fallback:
                        if candidate in ("STEAM", "GUARD", "EMAIL", "VALVE"):
                            continue
                        has_digit = any(c.isdigit() for c in candidate)
                        has_letter = any(c.isalpha() for c in candidate)
                        if has_digit and has_letter:
                            logger.info("[outlook] %s: %s найден (fallback): %s", login, description, candidate)
                            return candidate

            # Обновляем inbox каждые 3 попытки
            if attempt % 3 == 0:
                outlook_page.goto("https://outlook.live.com/mail/0/", wait_until="domcontentloaded", timeout=20000)
                time.sleep(8)
            else:
                time.sleep(5)

        return None

    def _link_sync(
        self,
        login: str,
        password: str,
        email: str,
        email_password: str,
    ) -> LinkResult:
        """Полный синхронный flow привязки Guard. Один браузер на весь процесс."""
        result = LinkResult()
        session = self._create_session()

        pw_instance = None
        browser_instance = None

        try:
            # === Step 1: Login via Playwright ===
            step_login = LinkStep(name="login", status="running")
            result.steps.append(step_login)

            try:
                access_token, steamid, outlook_page, pw_instance, browser_instance = \
                    self._login_via_playwright(login, password, email, email_password)
            except Exception as e:
                step_login.status = "error"
                step_login.detail = str(e)[:200]
                result.error = str(e)[:200]
                return result

            step_login.status = "done"
            step_login.detail = f"steamid={steamid}"
            logger.info("[login] Успешный вход. steamid=%s", steamid)

            # === Step 2: Add Authenticator ===
            step_add = LinkStep(name="add_authenticator", status="running")
            result.steps.append(step_add)

            auth_resp = self._add_authenticator(session, steamid, access_token)
            status_code = auth_resp.get("status", -1)

            if status_code == 29:
                step_add.status = "error"
                step_add.detail = "status=29 (требуется телефон)"
                result.error = "Steam требует привязку телефона (status=29)"
                return result
            elif status_code == 2:
                step_add.status = "error"
                step_add.detail = "status=2 (уже есть authenticator)"
                result.error = "Аккаунт уже имеет Mobile Authenticator"
                return result
            elif status_code == 84:
                step_add.status = "error"
                step_add.detail = "status=84 (rate limit)"
                result.error = "Rate limit — подождите и повторите"
                return result
            elif status_code != 1:
                step_add.status = "error"
                step_add.detail = f"status={status_code}"
                result.error = f"AddAuthenticator status={status_code}"
                return result

            mafile = MaFileData(
                shared_secret=auth_resp.get("shared_secret", ""),
                serial_number=str(auth_resp.get("serial_number", "")),
                revocation_code=auth_resp.get("revocation_code", ""),
                uri=auth_resp.get("uri", ""),
                server_time=str(auth_resp.get("server_time", "")),
                account_name=auth_resp.get("account_name", login),
                token_gid=auth_resp.get("token_gid", ""),
                identity_secret=auth_resp.get("identity_secret", ""),
                secret_1=auth_resp.get("secret_1", ""),
                status=status_code,
                steam_id=steamid,
            )

            step_add.status = "done"
            step_add.detail = f"revocation_code={mafile.revocation_code}"
            logger.info("[add_auth] Authenticator добавлен. Revocation: %s", mafile.revocation_code)

            # === Step 3: Finalize — читаем activation code из уже открытого Outlook ===
            step_final = LinkStep(name="finalize", status="running")
            result.steps.append(step_final)

            time.sleep(3)

            # Обновляем inbox в уже открытой вкладке
            outlook_page.goto("https://outlook.live.com/mail/0/", wait_until="domcontentloaded", timeout=20000)
            time.sleep(8)

            activation_code = self._read_code_from_outlook_page(
                outlook_page, _ACTIVATION_CODE_PATTERN, login,
                description="activation code", max_attempts=15,
            )
            if not activation_code:
                step_final.status = "error"
                step_final.detail = "Код активации не найден в email"
                result.error = "Не удалось получить код активации из email"
                # maFile всё равно сохраняем — можно финализировать вручную
                result.mafile = mafile
                result.revocation_code = mafile.revocation_code
                return result

            # Генерируем TOTP из свежего shared_secret
            totp_code = generate_steam_guard_code(mafile.shared_secret)

            # Финализация (с retry)
            finalized = False
            for attempt in range(3):
                final_resp = self._finalize_authenticator(
                    session, steamid, access_token, totp_code, activation_code,
                )
                if final_resp.get("success"):
                    finalized = True
                    break
                # TOTP мог протухнуть — ждём новый 30-секундный цикл
                logger.warning(
                    "[finalize] Попытка %d не удалась: %s", attempt + 1, final_resp,
                )
                time.sleep(5)
                totp_code = generate_steam_guard_code(mafile.shared_secret)

            if finalized:
                step_final.status = "done"
                result.success = True
                result.mafile = mafile
                result.revocation_code = mafile.revocation_code
                logger.info("[finalize] Steam Guard привязан для %s", login)
            else:
                step_final.status = "error"
                step_final.detail = "Finalize не прошёл после 3 попыток"
                result.error = "Не удалось финализировать authenticator"
                result.mafile = mafile  # сохраняем на всякий случай
                result.revocation_code = mafile.revocation_code

        except Exception as e:
            if result.steps:
                result.steps[-1].status = "error"
                result.steps[-1].detail = str(e)
            result.error = str(e)
            logger.error("[link] Ошибка для %s: %s", login, e, exc_info=True)

        finally:
            # Закрываем браузер в самом конце
            if browser_instance:
                try: browser_instance.close()
                except Exception: pass
            if pw_instance:
                try: pw_instance.stop()
                except Exception: pass

        return result

    async def link(
        self,
        login: str,
        password: str,
        email: str,
        email_password: str,
    ) -> LinkResult:
        """Async обёртка — запускает полный flow в thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._link_sync,
            login, password, email, email_password,
        )
