"""
Сервис для получения CS2 профиля через Game Coordinator.

Вызывает Node.js скрипт (cs2_gc/fetch_profile.js) как subprocess.
Возвращает: ранг, уровень, XP, VAC бан, Premier рейтинг.
"""

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SCRIPT_PATH = Path(__file__).parent.parent.parent / "cs2_gc" / "fetch_profile.js"
NODE_PATH = "node"


@dataclass
class CS2Profile:
    account_id: int | None = None
    vac_banned: int = 0          # 0 = нет, 1+ = забанен в CS2
    penalty_reason: int = 0      # причина бана/кулдауна
    penalty_seconds: int = 0     # секунд до разбана
    player_level: int | None = None   # уровень профиля CS2 (1-40)
    player_cur_xp: int | None = None  # текущий XP
    mm_rank: int | None = None        # ранг MM
    mm_wins: int | None = None        # побед в MM
    premier_rank: int | None = None   # Premier рейтинг
    error: str | None = None


def _fetch_cs2_profile_sync(
    login: str,
    password: str,
    shared_secret: str | None = None,
    target_steamid64: str | None = None,
    timeout: int = 35,
) -> CS2Profile:
    """Sync: запускает Node.js скрипт и парсит JSON ответ."""
    if not SCRIPT_PATH.exists():
        return CS2Profile(error=f"Скрипт не найден: {SCRIPT_PATH}")

    args = [
        NODE_PATH,
        str(SCRIPT_PATH),
        login,
        password,
        shared_secret or "null",
        target_steamid64 or "null",
    ]

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(SCRIPT_PATH.parent),
        )

        stdout_str = result.stdout.strip()
        stderr_str = result.stderr.strip()

        if stderr_str:
            logger.info(f"[CS2 GC] stderr: {stderr_str[:500]}")

        if not stdout_str:
            return CS2Profile(error=f"Пустой ответ от скрипта (exit={result.returncode})")

        # Парсим JSON из stdout (берём последнюю строку — может быть мусор от steam-user)
        lines = stdout_str.strip().split("\n")
        json_line = lines[-1]
        data = json.loads(json_line)

        if "error" in data:
            return CS2Profile(error=data["error"])

        return CS2Profile(
            account_id=data.get("account_id"),
            vac_banned=data.get("vac_banned", 0),
            penalty_reason=data.get("penalty_reason", 0),
            penalty_seconds=data.get("penalty_seconds", 0),
            player_level=data.get("player_level"),
            player_cur_xp=data.get("player_cur_xp"),
            mm_rank=data.get("mm_rank"),
            mm_wins=data.get("mm_wins"),
            premier_rank=data.get("premier_rank"),
        )

    except subprocess.TimeoutExpired:
        return CS2Profile(error=f"Таймаут {timeout}с")
    except json.JSONDecodeError as e:
        return CS2Profile(error=f"Ошибка парсинга JSON: {e}")
    except Exception as e:
        logger.error(f"[CS2 GC] Ошибка: {e}")
        return CS2Profile(error=str(e))


async def fetch_cs2_profile(
    login: str,
    password: str,
    shared_secret: str | None = None,
    target_steamid64: str | None = None,
    timeout: int = 35,
) -> CS2Profile:
    """Запускает sync subprocess в отдельном потоке."""
    return await asyncio.to_thread(
        _fetch_cs2_profile_sync, login, password, shared_secret, target_steamid64, timeout,
    )
