"""
Открытие Steam в Playwright-браузере с автологином.

Логика:
1. Запускает Chromium (видимый, не headless)
2. Настраивает прокси если привязан к аккаунту
3. Переходит на store.steampowered.com/login
4. Вводит логин/пароль
5. Если есть shared_secret — автоматически вводит 2FA код
6. Оставляет браузер открытым для пользователя

Браузер закрывается, когда пользователь закроет окно.

ВАЖНО: Запускаем Playwright в ОТДЕЛЬНОМ ПРОЦЕССЕ (subprocess.Popen),
т.к. Python 3.14 на Windows не поддерживает asyncio subprocess
(NotImplementedError в ProactorEventLoop).
Даже sync_playwright() внутри использует asyncio — поэтому threading не помогает.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Путь к скрипту-запускатору браузера
_BROWSER_SCRIPT = str(Path(__file__).parent / "_browser_subprocess.py")

# Путь к Python-интерпретатору (тот же, что запустил бэкенд)
_PYTHON_EXE = sys.executable

# Корневая папка backend (для корректного импорта app.*)
_BACKEND_DIR = str(Path(__file__).parent.parent.parent)


def _build_proxy_config(proxy) -> dict:
    """Формирует конфиг прокси для Playwright."""
    server = f"{proxy.protocol}://{proxy.host}:{proxy.port}"
    config = {"server": server}
    if proxy.username:
        config["username"] = proxy.username
    if proxy.password:
        config["password"] = proxy.password
    return config


def open_steam_browser_raw(
    login: str,
    password: str,
    shared_secret: str | None = None,
    proxy_config: dict | None = None,
) -> None:
    """
    Открывает браузер с автологином в отдельном процессе.

    proxy_config — словарь вида {"host": ..., "port": ..., "protocol": ..., "username": ..., "password": ...}
    """
    if not password:
        logger.error("Пароль аккаунта пуст для %s", login)
        return

    # Собираем proxy для Playwright
    proxy_pw = None
    if proxy_config and proxy_config.get("host"):
        protocol = proxy_config.get("protocol", "http")
        host = proxy_config["host"]
        port = proxy_config["port"]
        proxy_pw = {"server": f"{protocol}://{host}:{port}"}
        if proxy_config.get("username"):
            proxy_pw["username"] = proxy_config["username"]
        if proxy_config.get("password"):
            proxy_pw["password"] = proxy_config["password"]

    # JSON-данные для subprocess
    payload = json.dumps({
        "login": login,
        "password": password,
        "shared_secret": shared_secret,
        "proxy": proxy_pw,
    })

    try:
        # Запускаем отдельный Python-процесс с Playwright
        # stdout/stderr не пайпим — иначе буфер переполняется и процесс зависает
        # cwd=backend dir — чтобы работал import app.services.*
        proc = subprocess.Popen(
            [_PYTHON_EXE, _BROWSER_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=None,
            stderr=None,
            text=True,
            cwd=_BACKEND_DIR,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        # Отправляем данные и закрываем stdin (не ждём завершения)
        proc.stdin.write(payload)
        proc.stdin.close()

        logger.info(
            "Браузер запущен в процессе PID=%d для %s",
            proc.pid, login,
        )
    except Exception:
        logger.exception("Не удалось запустить браузер для %s", login)


def open_steam_browser_raw_from_db(account, proxy=None) -> None:
    """Обёртка для вызова из старого кода (account — модель из БД)."""
    from app.services.encryption import decrypt

    login = account.login
    password = decrypt(account.password_encrypted)
    shared_secret = decrypt(account.shared_secret_encrypted)

    proxy_config = None
    if proxy:
        proxy_config = {
            "protocol": getattr(proxy, "protocol", "http"),
            "host": proxy.host,
            "port": proxy.port,
            "username": getattr(proxy, "username", None),
            "password": getattr(proxy, "password", None),
        }

    open_steam_browser_raw(login, password, shared_secret, proxy_config)
