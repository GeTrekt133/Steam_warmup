"""
HTTP-клиент к ASF IPC API.

ASF IPC работает на localhost:1242 (по умолчанию).
Документация: https://github.com/JustArchiNET/ArchiSteamFarm/wiki/IPC

Все функции асинхронные (httpx.AsyncClient).
"""

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _headers() -> dict:
    """Заголовки для ASF IPC (с паролем если задан)."""
    h = {"Content-Type": "application/json"}
    if settings.ASF_IPC_PASSWORD:
        h["Authentication"] = settings.ASF_IPC_PASSWORD
    return h


def _url(path: str) -> str:
    return f"{settings.ASF_IPC_URL}{path}"


# ─── Глобальный статус ────────────────────────────────────────


async def get_asf_status() -> dict | None:
    """
    GET /Api/ASF — глобальный статус ASF (версия, память, время работы).

    Возвращает None если ASF недоступен.
    """
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(_url("/Api/ASF"), headers=_headers(), timeout=5.0)
            if r.status_code == 200:
                return r.json().get("Result", {})
    except Exception as e:
        logger.debug(f"ASF IPC get_asf_status: {e}")
    return None


# ─── Боты ────────────────────────────────────────────────────


async def get_bots(names: str = "ASF") -> list[dict]:
    """
    GET /Api/Bot/{names} — список ботов с их статусом.

    names='ASF' означает «все боты».
    Возвращает список dict с полями бота (BotName, IsConnected, CardsFarmer, etc.)
    """
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(_url(f"/Api/Bot/{names}"), headers=_headers(), timeout=5.0)
            if r.status_code == 200:
                data = r.json()
                result = data.get("Result", {})
                if isinstance(result, dict):
                    return list(result.values())
                return []
    except Exception as e:
        logger.debug(f"ASF IPC get_bots: {e}")
    return []


async def get_bot(name: str) -> dict | None:
    """Получить статус одного бота."""
    bots = await get_bots(name)
    return bots[0] if bots else None


# ─── Команды ─────────────────────────────────────────────────


async def send_command(command: str) -> str | None:
    """
    POST /Api/Command — выполнить ASF команду.

    Возвращает текстовый ответ ASF или None при ошибке.

    Примеры команд:
        status ASF          — статус всех ботов
        start BotName       — логин в Steam
        stop BotName        — логаут
        play BotName 730    — фарм часов CS2
        play BotName        — стоп фарм часов
        resume BotName      — возобновить фарм карточек
        pause BotName       — пауза фарма карточек
        loot BotName        — отправить предметы мастеру
    """
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                _url("/Api/Command"),
                headers=_headers(),
                json={"Command": command},
                timeout=15.0,
            )
            data = r.json()
            # ASF возвращает Result (текст при успехе) или Message (текст при ошибке)
            return data.get("Result") or data.get("Message", f"HTTP {r.status_code}")
    except Exception as e:
        logger.error(f"ASF IPC send_command '{command}': {e}")
    return None


# ─── Удобные обёртки над командами ───────────────────────────


async def start_bot(name: str) -> str | None:
    """Запустить бота (логин в Steam)."""
    return await send_command(f"start {name}")


async def stop_bot(name: str) -> str | None:
    """Остановить бота (логаут)."""
    return await send_command(f"stop {name}")


async def resume_bot(name: str) -> str | None:
    """Возобновить фарм карточек."""
    return await send_command(f"resume {name}")


async def pause_bot(name: str) -> str | None:
    """Поставить фарм карточек на паузу."""
    return await send_command(f"pause {name}")


async def play_games(name: str, app_ids: list[int]) -> str | None:
    """
    Начать фарм часов в указанных играх.

    Пример: play_games("login1", [730, 570]) → команда 'play login1 730,570'
    """
    if not app_ids:
        return await stop_playing(name)
    apps_str = ",".join(str(a) for a in app_ids)
    return await send_command(f"play {name} {apps_str}")


async def stop_playing(name: str) -> str | None:
    """Остановить фарм часов (вернуть к нормальному состоянию)."""
    return await send_command(f"play {name}")


async def add_license(name: str, app_ids: list[int]) -> str | None:
    """
    Добавить бесплатные игры в библиотеку бота.

    Команда: addlicense BotName app/730,app/570,...
    ASF добавит бесплатные и пропустит платные.
    """
    if not app_ids:
        return None
    apps_str = ",".join(f"app/{a}" for a in app_ids)
    return await send_command(f"addlicense {name} {apps_str}")


async def redeem_key(name: str, key: str) -> str | None:
    """Активировать Steam Wallet код или игровой ключ. Команда: redeem BotName KEY."""
    return await send_command(f"redeem {name} {key}")


async def delete_bot_ipc(name: str) -> bool:
    """
    DELETE /Api/Bot/{name} — удалить бота из ASF (без удаления конфига).

    Используется при удалении через UI — конфиг удаляем отдельно через asf_manager.
    """
    try:
        async with httpx.AsyncClient() as client:
            r = await client.delete(
                _url(f"/Api/Bot/{name}"),
                headers=_headers(),
                timeout=5.0,
            )
            return r.status_code in (200, 204)
    except Exception as e:
        logger.error(f"ASF IPC delete_bot '{name}': {e}")
    return False


async def is_ipc_available() -> bool:
    """Быстрая проверка доступности IPC."""
    result = await get_asf_status()
    return result is not None
