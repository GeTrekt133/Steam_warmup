"""
Менеджер ArchiSteamFarm subprocess.

Отвечает за:
- Генерацию ASF.json (глобальный конфиг)
- Генерацию {login}.json (конфиги ботов из Account-модели)
- Запуск/остановку ASF как subprocess
- Проверку статуса процесса
"""

import asyncio
import io
import json
import logging
import os
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import httpx

from app.config import settings
from app.services.encryption import decrypt

logger = logging.getLogger(__name__)

# ─── ASF Health Check лог ─────────────────────────────────────────
_HEALTH_LOG_DIR = Path(os.path.expanduser("~/Steam_warmup_logs"))
_HEALTH_LOG_DIR.mkdir(exist_ok=True)

_health_logger = logging.getLogger("asf_health")
_health_handler = logging.FileHandler(
    _HEALTH_LOG_DIR / "asf_health.log", encoding="utf-8",
)
_health_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
)
_health_logger.addHandler(_health_handler)
_health_logger.setLevel(logging.INFO)

_health_check_task: asyncio.Task | None = None


async def _asf_health_check_loop():
    """Фоновый health check ASF раз в минуту. Пишет в asf_health.log."""
    while True:
        try:
            await asyncio.sleep(60)

            process_alive = is_running()
            pid = get_pid()

            # Проверяем IPC
            ipc_ok = False
            ipc_detail = ""
            try:
                async with httpx.AsyncClient() as client:
                    headers = {}
                    if settings.ASF_IPC_PASSWORD:
                        headers["Authentication"] = settings.ASF_IPC_PASSWORD
                    r = await client.get(
                        f"{settings.ASF_IPC_URL}/Api/ASF",
                        headers=headers,
                        timeout=5.0,
                    )
                    if r.status_code == 200:
                        data = r.json().get("Result", {})
                        mem = data.get("MemoryUsage", 0)
                        uptime = data.get("ProcessStartTime", "")
                        ipc_ok = True
                        ipc_detail = f"mem={mem}MB, start={uptime}"
            except Exception as e:
                ipc_detail = str(e)[:100]

            # Проверяем ботов
            bots_detail = ""
            if ipc_ok:
                try:
                    async with httpx.AsyncClient() as client:
                        headers = {}
                        if settings.ASF_IPC_PASSWORD:
                            headers["Authentication"] = settings.ASF_IPC_PASSWORD
                        r = await client.get(
                            f"{settings.ASF_IPC_URL}/Api/Bot/ASF",
                            headers=headers,
                            timeout=5.0,
                        )
                        if r.status_code == 200:
                            bots = r.json().get("Result", {})
                            online = sum(1 for b in bots.values() if b.get("IsConnectedAndLoggedOn"))
                            total = len(bots)
                            bots_detail = f"bots={online}/{total} online"
                except Exception:
                    pass

            status = "OK" if process_alive and ipc_ok else "FAIL"
            _health_logger.info(
                f"[{status}] process={'ALIVE' if process_alive else 'DEAD'} "
                f"pid={pid} ipc={'OK' if ipc_ok else 'FAIL'} "
                f"{ipc_detail} {bots_detail}"
            )

            # Если процесс упал — авторестарт
            if not process_alive and _asf_process is not None:
                rc = _asf_process.returncode if _asf_process else "?"
                _health_logger.warning(
                    f"[CRASH] ASF процесс завершился! returncode={rc}, перезапускаю..."
                )
                ok, msg = await start_asf()
                if ok:
                    _health_logger.info(f"[RESTART] ASF успешно перезапущен: {msg}")
                else:
                    _health_logger.error(f"[RESTART] Не удалось перезапустить ASF: {msg}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            _health_logger.error(f"[ERROR] health check exception: {e}")


def start_health_check():
    """Запускает фоновый health check (вызывать при startup)."""
    global _health_check_task
    if _health_check_task is None or _health_check_task.done():
        _health_check_task = asyncio.create_task(_asf_health_check_loop())
        _health_logger.info("[START] ASF health check запущен (интервал: 60 сек)")


def stop_health_check():
    """Останавливает health check."""
    global _health_check_task
    if _health_check_task and not _health_check_task.done():
        _health_check_task.cancel()
        _health_logger.info("[STOP] ASF health check остановлен")

# Глобальный процесс ASF (singleton в рамках backend-процесса)
_asf_process: Optional[subprocess.Popen] = None


# ─── Пути ────────────────────────────────────────────────────


def _asf_dir() -> Path:
    """Абсолютный путь к папке ASF (из настройки ASF_DIR)."""
    p = Path(settings.ASF_DIR)
    if not p.is_absolute():
        # Относительно папки backend/
        p = Path(__file__).resolve().parent.parent.parent / settings.ASF_DIR
    return p.resolve()


def _config_dir() -> Path:
    return _asf_dir() / "config"


def _asf_executable() -> Path:
    """Путь к исполняемому файлу ASF."""
    base = _asf_dir()
    if sys.platform == "win32":
        exe = base / "ArchiSteamFarm.exe"
        if exe.exists():
            return exe
        # Generic .NET версия
        return base / "ArchiSteamFarm"
    return base / "ArchiSteamFarm"


# ─── Конфиги ─────────────────────────────────────────────────


def _global_config() -> dict:
    """Глобальный конфиг ASF.json."""
    cfg = {
        "IPCEnabled": True,
        "Headless": True,
        "AutoRestart": False,
        "UpdateChannel": 0,
        "OptimizationMode": 1,
        "SteamOwnerID": 0,
        "MaxFarmingTime": 10,
        "IdleFarmingPeriod": 8,
    }
    if settings.ASF_IPC_PASSWORD:
        cfg["IPCPassword"] = settings.ASF_IPC_PASSWORD
    return cfg


def _write_global_config() -> None:
    """Записать ASF.json в asf/config/."""
    cfg_dir = _config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "ASF.json"
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(_global_config(), f, indent=2)
    logger.info(f"ASF.json записан: {cfg_path}")


def generate_bot_config(account) -> dict:
    """
    Сгенерировать dict конфига бота из Account-модели.

    Расшифровывает пароль и maFile через Fernet.
    """
    password = decrypt(account.password_encrypted) or ""

    ma_data = None
    if account.mafile_json_encrypted:
        try:
            ma_json = decrypt(account.mafile_json_encrypted)
            if ma_json:
                ma_data = json.loads(ma_json)
        except Exception as e:
            logger.warning(f"Не удалось расшифровать maFile для {account.login}: {e}")

    config = {
        "SteamLogin": account.login,
        "SteamPassword": password,
        "Enabled": True,
        "OnlineStatus": 1,
        "GamesPlayedWhileIdle": [],
        "HoursUntilCardDrops": 0,
        "SendOnFarmingFinished": False,
        "AutoSteamSaleEvent": False,
        "BotBehaviour": 0,
    }

    return config, ma_data


def write_bot_config(account) -> Path:
    """Записать {login}.json в asf/config/ и вернуть путь."""
    cfg_dir = _config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)

    cfg_path = cfg_dir / f"{account.login}.json"
    config, ma_data = generate_bot_config(account)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    logger.info(f"Бот конфиг записан: {cfg_path}")

    # ASF V6+ — maFile отдельным файлом для MobileAuthenticator плагина
    if ma_data:
        ma_data.pop("Session", None)
        mafile_path = cfg_dir / f"{account.login}.maFile"
        with open(mafile_path, "w", encoding="utf-8") as f:
            json.dump(ma_data, f, indent=2)
        logger.info(f"maFile записан: {mafile_path}")

    return cfg_path


def remove_bot_config(bot_name: str) -> bool:
    """Удалить {bot_name}.json из asf/config/. Возвращает True если файл существовал."""
    cfg_path = _config_dir() / f"{bot_name}.json"
    if cfg_path.exists():
        cfg_path.unlink()
        logger.info(f"Бот конфиг удалён: {cfg_path}")
        return True
    return False


def list_bot_configs() -> list[str]:
    """Список имён ботов по файлам в asf/config/ (без ASF.json)."""
    cfg_dir = _config_dir()
    if not cfg_dir.exists():
        return []
    return [f.stem for f in sorted(cfg_dir.glob("*.json")) if f.stem != "ASF"]


# ─── Авто-скачивание ASF ─────────────────────────────────────

GITHUB_API = "https://api.github.com/repos/JustArchiNET/ArchiSteamFarm/releases/latest"

# Статус текущей загрузки (для polling с фронтенда)
_download_state: dict = {
    "active": False,
    "stage": "",       # "fetching_release" | "downloading" | "extracting" | "done" | "error"
    "downloaded": 0,
    "total": 0,
    "version": "",
    "error": "",
}


def get_download_state() -> dict:
    return dict(_download_state)


def _asset_name() -> str:
    if sys.platform == "win32":
        return "ASF-win-x64.zip"
    if sys.platform == "darwin":
        return "ASF-osx-x64.zip"
    return "ASF-linux-x64.zip"


async def download_asf() -> tuple[bool, str]:
    """
    Скачать последнюю версию ASF с GitHub Releases и распаковать в ASF_DIR.

    Обновляет _download_state для polling с фронтенда.
    Возвращает (success, message).
    """
    global _download_state

    if _download_state["active"]:
        return False, "Загрузка уже идёт"

    _download_state = {"active": True, "stage": "fetching_release",
                       "downloaded": 0, "total": 0, "version": "", "error": ""}

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            # 1. Получить последний релиз
            _download_state["stage"] = "fetching_release"
            r = await client.get(
                GITHUB_API,
                headers={"User-Agent": "SteamFarmingPanel"},
                timeout=15.0,
            )
            if r.status_code != 200:
                raise RuntimeError(f"GitHub API вернул {r.status_code}")

            release = r.json()
            version = release.get("tag_name", "?")
            _download_state["version"] = version

            asset_name = _asset_name()
            asset_url = next(
                (a["browser_download_url"] for a in release.get("assets", [])
                 if a["name"] == asset_name),
                None,
            )
            if not asset_url:
                raise RuntimeError(f"Не найден {asset_name} в релизе {version}")

            # 2. Скачать zip с прогрессом
            _download_state["stage"] = "downloading"
            logger.info(f"Скачиваю ASF {version}: {asset_url}")

            zip_chunks: list[bytes] = []
            async with client.stream("GET", asset_url, timeout=180.0) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                _download_state["total"] = total
                downloaded = 0
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    zip_chunks.append(chunk)
                    downloaded += len(chunk)
                    _download_state["downloaded"] = downloaded

            # 3. Распаковать
            _download_state["stage"] = "extracting"
            asf_dir = _asf_dir()
            asf_dir.mkdir(parents=True, exist_ok=True)

            zip_data = b"".join(zip_chunks)
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                zf.extractall(asf_dir)

            # На Linux/macOS ставим +x
            if sys.platform != "win32":
                exe = _asf_executable()
                if exe.exists():
                    exe.chmod(0o755)

            logger.info(f"ASF {version} распакован в {asf_dir}")
            _download_state["stage"] = "done"
            _download_state["active"] = False
            return True, f"ASF {version} успешно скачан"

    except Exception as e:
        logger.error(f"Ошибка скачивания ASF: {e}")
        _download_state["stage"] = "error"
        _download_state["error"] = str(e)
        _download_state["active"] = False
        return False, str(e)


# ─── Subprocess lifecycle ─────────────────────────────────────


async def start_asf() -> tuple[bool, str]:
    """
    Запустить ASF subprocess.

    Возвращает (success, message).
    Ждёт готовности IPC до 30 секунд.
    """
    global _asf_process

    if _asf_process and _asf_process.poll() is None:
        return True, "ASF уже запущен"

    exe = _asf_executable()
    if not exe.exists():
        logger.info("ASF бинарь не найден — запускаю авто-скачивание")
        ok, msg = await download_asf()
        if not ok:
            return False, f"Не удалось скачать ASF: {msg}"
        exe = _asf_executable()
        if not exe.exists():
            return False, "ASF скачан, но бинарь не найден после распаковки"

    _write_global_config()

    try:
        _asf_process = subprocess.Popen(
            [str(exe), "--path", str(_asf_dir())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            cwd=str(_asf_dir()),
        )
        logger.info(f"ASF subprocess запущен, PID={_asf_process.pid}")
    except Exception as e:
        logger.error(f"Ошибка запуска ASF subprocess: {e}")
        return False, str(e)

    # Ждём готовности IPC (максимум 30 сек)
    for i in range(30):
        await asyncio.sleep(1)
        # Процесс мог упасть
        if _asf_process.poll() is not None:
            rc = _asf_process.returncode
            return False, f"ASF завершился с кодом {rc} — проверьте asf/logs/"
        try:
            async with httpx.AsyncClient() as client:
                headers = {}
                if settings.ASF_IPC_PASSWORD:
                    headers["Authentication"] = settings.ASF_IPC_PASSWORD
                r = await client.get(
                    f"{settings.ASF_IPC_URL}/Api/ASF",
                    headers=headers,
                    timeout=2.0,
                )
                if r.status_code in (200, 401):
                    logger.info(f"ASF IPC готов (через {i+1} сек)")
                    return True, "ASF запущен успешно"
        except Exception:
            pass

    if _asf_process.poll() is None:
        return True, "ASF запущен (IPC ещё инициализируется)"

    return False, "ASF завершился сразу после запуска — проверьте asf/logs/"


async def stop_asf() -> tuple[bool, str]:
    """Остановить ASF subprocess."""
    global _asf_process

    if not _asf_process or _asf_process.poll() is not None:
        _asf_process = None
        return False, "ASF не запущен"

    try:
        _asf_process.terminate()
        try:
            _asf_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _asf_process.kill()
            _asf_process = None
            return True, "ASF принудительно завершён (kill)"
        _asf_process = None
        return True, "ASF остановлен"
    except Exception as e:
        return False, str(e)


def is_running() -> bool:
    """Проверить, запущен ли ASF subprocess."""
    return _asf_process is not None and _asf_process.poll() is None


def get_pid() -> int | None:
    """PID ASF процесса или None."""
    if is_running():
        return _asf_process.pid
    return None
