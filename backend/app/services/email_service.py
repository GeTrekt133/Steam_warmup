"""
Email-сервис для получения писем подтверждения Steam.

Поддерживает IMAP-подключение к почтовым ящикам.
Используется при авторегистрации для подтверждения email.
"""

import asyncio
import imaplib
import logging
import re
import time

logger = logging.getLogger(__name__)

# Маппинг домен → IMAP-сервер
IMAP_HOSTS: dict[str, str] = {
    "gmail.com": "imap.gmail.com",
    "yahoo.com": "imap.mail.yahoo.com",
    "outlook.com": "imap-mail.outlook.com",
    "hotmail.com": "imap-mail.outlook.com",
    "live.com": "imap-mail.outlook.com",
    "yandex.ru": "imap.yandex.ru",
    "yandex.com": "imap.yandex.com",
    "mail.ru": "imap.mail.ru",
    "bk.ru": "imap.mail.ru",
    "inbox.ru": "imap.mail.ru",
    "list.ru": "imap.mail.ru",
    "rambler.ru": "imap.rambler.ru",
    "gmx.com": "imap.gmx.com",
    "protonmail.com": "127.0.0.1",  # ProtonMail Bridge
    "icloud.com": "imap.mail.me.com",
}


def _get_imap_host(email: str) -> str | None:
    """Определить IMAP-сервер по домену email."""
    domain = email.split("@")[-1].lower()
    return IMAP_HOSTS.get(domain)


def _fetch_steam_confirmation_link(
    email: str,
    email_password: str,
    creation_id: str,
    max_attempts: int = 8,
    wait_sec: int = 5,
) -> str | None:
    """
    Синхронно подключается к IMAP, ищет письмо от Steam
    с нужным creationid и возвращает ссылку подтверждения.
    """
    domain = email.split("@")[-1].lower()
    imap_host = IMAP_HOSTS.get(domain)
    if not imap_host:
        logger.error("Неизвестный IMAP-хост для домена: %s", domain)
        return None

    email_login = email.split("@")[0] if "@" not in email else email

    try:
        server = imaplib.IMAP4_SSL(imap_host)
        server.login(email_login if "@" not in email_login else email, email_password)
        server.select("INBOX")
    except Exception as e:
        logger.error("IMAP login failed for %s: %s", email, e)
        return None

    try:
        for attempt in range(1, max_attempts + 1):
            logger.info(
                "Checking email %s for Steam confirmation (attempt %d/%d)...",
                email, attempt, max_attempts,
            )
            _, data = server.search(None, "ALL")
            if not data[0]:
                time.sleep(wait_sec)
                continue

            # Проверяем последние 5 писем (от новых к старым)
            uids = data[0].split()
            for uid in reversed(uids[-5:]):
                _, msg_data = server.uid("fetch", uid, "(BODY[TEXT])")
                if not msg_data or not msg_data[0]:
                    continue
                try:
                    body = msg_data[0][1].decode("utf-8", errors="ignore")
                except (IndexError, AttributeError):
                    continue

                link = re.search(
                    r"(https://store\.steampowered\.com/account/newaccountverification[^\s\r\n\"'<>]+)",
                    body,
                )
                if link is None:
                    continue

                url = link.group(1)
                cid = re.search(r"creationid=(\w+)", url)
                if cid and cid.group(1) == creation_id:
                    logger.info("Found confirmation link for creationid=%s", creation_id)
                    return url

            time.sleep(wait_sec)

    finally:
        try:
            server.close()
            server.logout()
        except Exception:
            pass

    logger.error("Steam confirmation email not found after %d attempts", max_attempts)
    return None


async def fetch_confirmation_link_async(
    email: str,
    email_password: str,
    creation_id: str,
    max_attempts: int = 8,
    wait_sec: int = 5,
) -> str | None:
    """Async-обёртка — запускает IMAP-проверку в thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _fetch_steam_confirmation_link,
        email, email_password, creation_id, max_attempts, wait_sec,
    )
