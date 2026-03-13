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
_LOGIN_CODE_PATTERN = re.compile(
    r"(?:"
    r"login\s*code"
    r"|код\s*(?:для\s*)?входа"
    r"|guard\s*code"
    r"|account\s*access\s*code"
    r")[:\s]*([A-Z0-9]{5})",
    re.IGNORECASE,
)

# Паттерн для кода активации authenticator (приходит после AddAuthenticator)
_ACTIVATION_CODE_PATTERN = re.compile(
    r"(?:"
    r"activation\s*code"
    r"|код\s*активации"
    r"|confirmation\s*code"
    r"|verify.*?code"
    r"|your\s*code\s*is"
    r")[:\s]*([A-Z0-9]{5})",
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

    def __init__(self, proxy: dict | None = None):
        self._proxy = proxy

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

    # --- Full flow ---

    def _link_sync(
        self,
        login: str,
        password: str,
        email: str,
        email_password: str,
    ) -> LinkResult:
        """Полный синхронный flow привязки Guard."""
        result = LinkResult()
        session = self._create_session()

        try:
            # === Step 1: Login ===
            step_login = LinkStep(name="login", status="running")
            result.steps.append(step_login)

            # 1a. RSA key
            rsa_data = self._get_rsa_key(session, login)
            encrypted_pw = _encrypt_password_rsa(
                password,
                rsa_data["publickey_mod"],
                rsa_data["publickey_exp"],
            )

            # 1b. Begin auth
            auth = self._begin_auth_session(
                session, login, encrypted_pw, rsa_data["timestamp"],
            )
            client_id = str(auth["client_id"])
            request_id = str(auth["request_id"])
            steamid = str(auth.get("steamid", ""))

            # 1c. Email Guard (если нужен)
            confirmations = auth.get("allowed_confirmations", [])
            needs_email = any(c.get("confirmation_type") == 2 for c in confirmations)

            if needs_email:
                logger.info("[login] Требуется email код для входа...")
                login_code = _fetch_code_from_imap(
                    email, email_password, _LOGIN_CODE_PATTERN,
                    max_attempts=8, wait_sec=5, description="login code",
                )
                if not login_code:
                    step_login.status = "error"
                    step_login.detail = "Email код для входа не найден"
                    result.error = step_login.detail
                    return result

                self._submit_steam_guard_code(session, client_id, steamid, login_code)
                logger.info("[login] Email код отправлен")

            # 1d. Poll для получения токенов
            access_token = ""
            for _ in range(15):
                time.sleep(2)
                poll = self._poll_auth_status(session, client_id, request_id)
                access_token = poll.get("access_token", "")
                if access_token:
                    break

            if not access_token:
                step_login.status = "error"
                step_login.detail = "Не удалось получить access_token"
                result.error = step_login.detail
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
                step_add.detail = "status=29 (требуется телефон — не должно быть)"
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
                result.error = f"AddAuthenticator неожиданный status={status_code}"
                return result

            # Собираем maFile
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
            logger.info(
                "[add_auth] Authenticator добавлен. Revocation: %s",
                mafile.revocation_code,
            )

            # === Step 3: Finalize (email подтверждение) ===
            step_final = LinkStep(name="finalize", status="running")
            result.steps.append(step_final)

            # Ждём email с кодом активации
            time.sleep(3)
            activation_code = _fetch_code_from_imap(
                email, email_password, _ACTIVATION_CODE_PATTERN,
                max_attempts=12, wait_sec=5, description="activation code",
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
