"""
Endpoints для управления ASF (ArchiSteamFarm) и фармом часов.

Маршруты:
  GET  /asf/status              — статус ASF процесса + IPC
  POST /asf/start               — запустить ASF
  POST /asf/stop                — остановить ASF
  GET  /asf/bots                — список ботов (из IPC)
  POST /asf/bots/add            — добавить аккаунты как боты
  POST /asf/bots/{name}/start   — запустить бота
  POST /asf/bots/{name}/stop    — остановить бота
  DELETE /asf/bots/{name}       — удалить бота
  POST /asf/farm/start          — начать фарм часов
  POST /asf/farm/stop           — остановить фарм часов
  GET  /asf/farm/sessions       — активные сессии фарма
  POST /asf/command             — raw ASF команда
"""

import asyncio
import random
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.auth import get_current_user
from app.database import get_db, async_session
from app.models.account import Account
from app.models.proxy import Proxy
from app.models.user import User
from app.services import asf_manager, asf_ipc
from app.services.session_persistence import save_farming_session

router = APIRouter()

# ─── Пул F2P / популярных игр для рандомного фарма ────────────

FREE_GAMES_POOL = [
    # ─── Топ F2P (точно бесплатные) ──────────────────────
    730,      # CS2
    570,      # Dota 2
    440,      # TF2
    578080,   # PUBG
    1172470,  # Apex Legends
    230410,   # Warframe
    304930,   # Unturned
    444090,   # Paladins
    386360,   # Smite
    236390,   # War Thunder
    1085660,  # Destiny 2
    # ─── F2P шутеры / экшен ──────────────────────────────
    2379780,  # Counter-Strike 2 (отдельный AppID)
    1604030,  # V Rising (F2P trial)
    252490,   # Rust (стал F2P в 2024)
    218620,   # PAYDAY 2 (бесплатный)
    # ─── F2P MMO / RPG ──────────────────────────────────
    255710,   # Cities: Skylines (free weekends)
    1091500,  # Cyberpunk 2077 (free trial)
    238960,   # Path of Exile
    570940,   # Dark Souls III (free trial)
    1599340,  # Lost Ark
    1366540,  # Enlisted
    # ─── F2P стратегии / другое ──────────────────────────
    431960,   # Wallpaper Engine (если куплен ранее)
    1097150,  # Fall Guys
    2399830,  # Arena Breakout: Infinite
    2767030,  # Marvel Rivals
    1963000,  # The Finals
    3221870,  # Once Human
    1517290,  # Battlebit Remastered
    945360,   # Among Us
    # ─── Популярные F2P карточные / казуальные ───────────
    753,      # Steam Trading Cards Beta
    4000,     # Garry's Mod (свободный)
]

# ─── In-memory хранение активных фарм-сессий ─────────────────
_farm_sessions: dict[str, dict] = {}


# ─── Схемы ───────────────────────────────────────────────────


class AddBotsRequest(BaseModel):
    account_ids: list[int]


class AddBotsDirectRequest(BaseModel):
    """Добавить ботов напрямую из данных (без БД)."""
    accounts: list[dict]  # [{login, password, ..., proxy_id?}]


class BotActionRequest(BaseModel):
    pass


class FarmStartRequest(BaseModel):
    bot_names: list[str]
    app_ids: list[int] = []
    hours_target: float = 0.0        # 0 = бессрочно
    random_games: bool = False        # случайные игры из пула
    random_count: int = 3             # сколько случайных игр на бота (1-5)


class FarmStopRequest(BaseModel):
    bot_names: list[str]


class SmartFarmStartRequest(BaseModel):
    bot_names: list[str]
    app_ids: list[int] = []
    game_weights_pool: list[dict[str, int]] | None = None  # массив профилей, каждому боту — рандомный
    active_start_hour: int = 8
    active_end_hour: int = 23
    start_jitter_minutes: int = 30
    stop_jitter_minutes: int = 30
    break_interval_hours_min: float = 2.0
    break_interval_hours_max: float = 4.0
    break_duration_minutes_min: int = 15
    break_duration_minutes_max: int = 45
    game_rotation_hours: float = 3.0
    games_per_rotation: int = 1
    use_random_games: bool = True
    simulate_game_switching: bool = True


class SmartFarmStopRequest(BaseModel):
    session_id: str


class RawCommandRequest(BaseModel):
    command: str


# ─── ASF Процесс ─────────────────────────────────────────────


@router.get("/status")
async def asf_status(current_user: User = Depends(get_current_user)):
    """
    Статус ASF процесса и IPC.

    Возвращает:
    - running: ASF subprocess запущен
    - ipc_available: IPC сервер отвечает
    - pid: PID процесса
    - asf_info: данные от ASF IPC (версия, память)
    - bots: список ботов с их статусом
    - bot_configs: список имён из конфиг-файлов
    """
    running = asf_manager.is_running()
    pid = asf_manager.get_pid()
    bot_configs = asf_manager.list_bot_configs()

    asf_info = None
    bots = []
    ipc_available = False

    if running:
        asf_info = await asf_ipc.get_asf_status()
        ipc_available = asf_info is not None
        if ipc_available:
            bots = await asf_ipc.get_bots()

    return {
        "running": running,
        "ipc_available": ipc_available,
        "pid": pid,
        "asf_info": asf_info,
        "bots": bots,
        "bot_configs": bot_configs,
    }


@router.post("/download")
async def download_asf_endpoint(current_user: User = Depends(get_current_user)):
    """
    Запустить скачивание ASF с GitHub в фоне.

    Прогресс доступен через GET /asf/download/progress.
    """
    if asf_manager.get_download_state()["active"]:
        return {"started": False, "message": "Загрузка уже идёт"}
    asyncio.create_task(asf_manager.download_asf())
    return {"started": True, "message": "Скачивание ASF запущено"}


@router.get("/download/progress")
async def download_progress(current_user: User = Depends(get_current_user)):
    """Прогресс скачивания ASF."""
    state = asf_manager.get_download_state()
    pct = 0
    if state["total"] > 0:
        pct = round(state["downloaded"] / state["total"] * 100, 1)
    return {**state, "percent": pct}


@router.post("/start")
async def start_asf(current_user: User = Depends(get_current_user)):
    """
    Запустить ASF subprocess (неблокирующий).

    Если ASF не установлен — скачивает с GitHub.
    Всё выполняется в фоне, ответ возвращается сразу.
    Фронтенд отслеживает через GET /asf/status (polling).
    """
    from app.services import asf_manager as mgr

    if mgr.is_running():
        return {"success": True, "downloading": False, "message": "ASF уже запущен"}

    exe = mgr._asf_executable()
    if not exe.exists():
        state = mgr.get_download_state()
        if state["active"]:
            return {"success": False, "downloading": True, "message": "Скачивание уже идёт"}
        asyncio.create_task(_download_then_start())
        return {"success": False, "downloading": True, "message": "ASF не установлен — начато скачивание"}

    # Бинарь есть — запускаем синхронно
    import logging
    logger = logging.getLogger(__name__)
    try:
        loop = asyncio.get_running_loop()
        logger.info(f"ASF start: event_loop={type(loop).__name__}, exe={exe}")
        success, message = await asf_manager.start_asf()
        logger.info(f"ASF start result: success={success}, message={message}")
        if not success:
            raise HTTPException(status_code=400, detail=message)
        return {"success": True, "downloading": False, "message": message}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ASF start exception")
        raise HTTPException(status_code=500, detail=str(e))


async def _download_then_start():
    """Фоновая задача: скачать ASF, затем запустить."""
    ok, msg = await asf_manager.download_asf()
    if ok:
        await asf_manager.start_asf()


@router.post("/stop")
async def stop_asf(current_user: User = Depends(get_current_user)):
    """Остановить ASF subprocess."""
    success, message = await asf_manager.stop_asf()
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message}


# ─── Боты ────────────────────────────────────────────────────


@router.get("/bots")
async def list_bots(current_user: User = Depends(get_current_user)):
    """
    Список ботов из ASF IPC.

    Если ASF не запущен — возвращает список из конфиг-файлов (offline).
    """
    bot_configs = asf_manager.list_bot_configs()

    if not asf_manager.is_running():
        return {
            "ipc_available": False,
            "bots": [{"BotName": name, "IsConnected": False, "status": "offline"} for name in bot_configs],
        }

    bots = await asf_ipc.get_bots()
    ipc_available = bots is not None

    # Дополняем ботами из конфигов, которых нет в IPC (ещё не инициализированы)
    ipc_names = {b.get("BotName", "") for b in bots}
    for name in bot_configs:
        if name not in ipc_names:
            bots.append({"BotName": name, "IsConnected": False, "status": "initializing"})

    return {"ipc_available": ipc_available, "bots": bots}


@router.post("/bots/add")
async def add_bots(
    req: AddBotsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Добавить аккаунты из БД как ASF-боты.

    Для каждого account_id:
    1. Загружает Account из БД
    2. Расшифровывает пароль + maFile
    3. Записывает {login}.json в asf/config/
    4. Если ASF запущен — перезагружает бота через IPC команду

    Возвращает список добавленных/пропущенных ботов.
    """
    if not req.account_ids:
        raise HTTPException(status_code=400, detail="Список account_ids пуст")

    result = await db.execute(
        select(Account).where(
            Account.id.in_(req.account_ids),
            Account.owner_id == current_user.id,
        )
    )
    accounts = result.scalars().all()

    added = []
    errors = []

    for account in accounts:
        try:
            path = asf_manager.write_bot_config(account)
            added.append({"login": account.login, "config_path": str(path)})

            # Если ASF запущен — говорим ему перезагрузить бота
            if asf_manager.is_running() and await asf_ipc.is_ipc_available():
                await asf_ipc.send_command(f"start {account.login}")
        except Exception as e:
            errors.append({"login": account.login, "error": str(e)})

    not_found = set(req.account_ids) - {a.id for a in accounts}
    for nf_id in not_found:
        errors.append({"account_id": nf_id, "error": "Аккаунт не найден"})

    return {
        "added": len(added),
        "errors": len(errors),
        "bots": added,
        "error_details": errors,
    }


@router.post("/bots/add-direct")
async def add_bots_direct(
    req: AddBotsDirectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Добавить ботов напрямую из данных фронтенда (localStorage).

    Принимает список {login, password, shared_secret?, mafile_json?, proxy_id?}.
    Генерирует bot.json. Если proxy_id — добавляет WebProxy в конфиг.
    """
    import json as _json

    # Загружаем все нужные прокси одним запросом
    proxy_ids = {acc.get("proxy_id") for acc in req.accounts if acc.get("proxy_id")}
    proxies_map: dict[int, Proxy] = {}
    if proxy_ids:
        result = await db.execute(select(Proxy).where(Proxy.id.in_(proxy_ids)))
        for px in result.scalars().all():
            proxies_map[px.id] = px

    added = []
    errors = []

    cfg_dir = asf_manager._config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)

    for acc in req.accounts:
        login = acc.get("login", "").strip()
        password = acc.get("password", "").strip()
        if not login or not password:
            errors.append({"login": login or "?", "error": "Нет логина или пароля"})
            continue

        try:
            config = {
                "SteamLogin": login,
                "SteamPassword": password,
                "Enabled": True,
                "OnlineStatus": 1,
                "GamesPlayedWhileIdle": [],
                "HoursUntilCardDrops": 0,
                "SendOnFarmingFinished": False,
                "AutoSteamSaleEvent": False,
                "BotBehaviour": 0,
            }

            # Добавляем прокси если указан
            pid = acc.get("proxy_id")
            if pid and pid in proxies_map:
                px = proxies_map[pid]
                proxy_str = f"{px.protocol}://"
                if px.username and px.password:
                    proxy_str += f"{px.username}:{px.password}@"
                proxy_str += f"{px.host}:{px.port}"
                config["WebProxy"] = proxy_str

            cfg_path = cfg_dir / f"{login}.json"
            with open(cfg_path, "w", encoding="utf-8") as f:
                _json.dump(config, f, indent=2)

            # ASF V6+ — maFile кладётся отдельным файлом для MobileAuthenticator плагина
            mafile = acc.get("mafile_json")
            if mafile:
                if isinstance(mafile, str):
                    mafile_data = _json.loads(mafile)
                else:
                    mafile_data = mafile
                # Убираем Session — токены протухают
                mafile_data.pop("Session", None)
                mafile_path = cfg_dir / f"{login}.maFile"
                with open(mafile_path, "w", encoding="utf-8") as f:
                    _json.dump(mafile_data, f, indent=2)
            elif acc.get("shared_secret"):
                # Минимальный maFile из shared_secret
                mafile_data = {
                    "shared_secret": acc["shared_secret"],
                    "identity_secret": acc.get("identity_secret", ""),
                    "device_id": f"android:00000000-0000-0000-0000-000000000000",
                }
                mafile_path = cfg_dir / f"{login}.maFile"
                with open(mafile_path, "w", encoding="utf-8") as f:
                    _json.dump(mafile_data, f, indent=2)

            added.append({"login": login})

            if asf_manager.is_running() and await asf_ipc.is_ipc_available():
                await asf_ipc.send_command(f"start {login}")
        except Exception as e:
            errors.append({"login": login, "error": str(e)})

    return {
        "added": len(added),
        "errors": len(errors),
        "bots": added,
        "error_details": errors,
    }


@router.post("/bots/{name}/start")
async def start_bot(name: str, current_user: User = Depends(get_current_user)):
    """Запустить конкретного бота (логин в Steam через IPC)."""
    if not asf_manager.is_running():
        raise HTTPException(status_code=400, detail="ASF не запущен")
    result = await asf_ipc.start_bot(name)
    if result is None:
        raise HTTPException(status_code=503, detail="ASF IPC недоступен")
    return {"bot": name, "result": result}


@router.post("/bots/{name}/stop")
async def stop_bot(name: str, current_user: User = Depends(get_current_user)):
    """Остановить конкретного бота (логаут)."""
    if not asf_manager.is_running():
        raise HTTPException(status_code=400, detail="ASF не запущен")
    result = await asf_ipc.stop_bot(name)
    if result is None:
        raise HTTPException(status_code=503, detail="ASF IPC недоступен")
    return {"bot": name, "result": result}


@router.post("/bots/{name}/pause")
async def pause_bot(name: str, current_user: User = Depends(get_current_user)):
    """Поставить фарм карточек на паузу."""
    if not asf_manager.is_running():
        raise HTTPException(status_code=400, detail="ASF не запущен")
    result = await asf_ipc.pause_bot(name)
    return {"bot": name, "result": result}


@router.post("/bots/{name}/resume")
async def resume_bot(name: str, current_user: User = Depends(get_current_user)):
    """Возобновить фарм карточек."""
    if not asf_manager.is_running():
        raise HTTPException(status_code=400, detail="ASF не запущен")
    result = await asf_ipc.resume_bot(name)
    return {"bot": name, "result": result}


@router.delete("/bots/{name}")
async def delete_bot(name: str, current_user: User = Depends(get_current_user)):
    """
    Удалить бота:
    1. Через IPC (если ASF запущен)
    2. Удалить конфиг-файл
    """
    ipc_deleted = False
    if asf_manager.is_running() and await asf_ipc.is_ipc_available():
        # Сначала останавливаем
        await asf_ipc.stop_bot(name)
        await asyncio.sleep(1)
        ipc_deleted = await asf_ipc.delete_bot_ipc(name)

    config_deleted = asf_manager.remove_bot_config(name)

    return {
        "bot": name,
        "ipc_deleted": ipc_deleted,
        "config_deleted": config_deleted,
    }


# ─── Фарм часов ──────────────────────────────────────────────


@router.post("/farm/start")
async def farm_start(
    req: FarmStartRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Начать фарм часов для указанных ботов.

    Отправляет команду 'play BotName app1,app2,...' каждому боту.
    Сохраняет сессию в _farm_sessions для отслеживания.
    """
    if not asf_manager.is_running():
        raise HTTPException(status_code=400, detail="ASF не запущен")
    if not await asf_ipc.is_ipc_available():
        raise HTTPException(status_code=503, detail="ASF IPC недоступен")
    if not req.bot_names:
        raise HTTPException(status_code=400, detail="Список ботов пуст")
    if not req.app_ids and not req.random_games:
        raise HTTPException(status_code=400, detail="Выберите игры или включите рандомный режим")

    count = max(1, min(5, req.random_count))  # clamp 1-5

    started = []
    errors = []

    for bot_name in req.bot_names:
        # Формируем набор игр для этого бота
        if req.random_games:
            bot_apps = random.sample(FREE_GAMES_POOL, min(count, len(FREE_GAMES_POOL)))
            if req.app_ids:
                bot_apps = list(set(req.app_ids + bot_apps))
        else:
            bot_apps = req.app_ids

        # Автоматически добавляем бесплатные игры в библиотеку перед фармом
        if bot_apps:
            await asf_ipc.add_license(bot_name, bot_apps)

        result = await asf_ipc.play_games(bot_name, bot_apps)
        if result is not None:
            started.append({"name": bot_name, "app_ids": bot_apps})
            session_key = f"{current_user.id}:{bot_name}"
            _farm_sessions[session_key] = {
                "bot_name": bot_name,
                "app_ids": bot_apps,
                "hours_target": req.hours_target,
                "started_at": time.time(),
                "owner_id": current_user.id,
            }
            # Сохраняем в БД
            try:
                async with async_session() as db:
                    await save_farming_session(
                        db, bot_name=bot_name, owner_id=current_user.id,
                        status="active", session_type="manual",
                        app_ids=bot_apps, hours_target=req.hours_target,
                    )
            except Exception:
                pass
        else:
            errors.append(bot_name)

    return {
        "started": started,
        "errors": errors,
        "random_games": req.random_games,
    }


@router.post("/farm/add-games")
async def farm_add_games(
    req: FarmStartRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Добавить бесплатные игры в библиотеку ботов (без запуска фарма).

    Использует ASF команду addlicense для каждого бота.
    """
    if not asf_manager.is_running():
        raise HTTPException(status_code=400, detail="ASF не запущен")

    count = max(1, min(5, req.random_count))
    results = []

    for bot_name in req.bot_names:
        if req.random_games:
            bot_apps = random.sample(FREE_GAMES_POOL, min(count, len(FREE_GAMES_POOL)))
            if req.app_ids:
                bot_apps = list(set(req.app_ids + bot_apps))
        else:
            bot_apps = req.app_ids

        if bot_apps:
            result = await asf_ipc.add_license(bot_name, bot_apps)
            results.append({"bot": bot_name, "app_ids": bot_apps, "result": result})

    return {"results": results}


@router.get("/farm/games-pool")
async def get_games_pool(current_user: User = Depends(get_current_user)):
    """Список бесплатных игр из пула для рандомного фарма."""
    return {"games": FREE_GAMES_POOL, "count": len(FREE_GAMES_POOL)}


@router.post("/farm/stop")
async def farm_stop(
    req: FarmStopRequest,
    current_user: User = Depends(get_current_user),
):
    """Остановить фарм часов для указанных ботов."""
    if not asf_manager.is_running():
        raise HTTPException(status_code=400, detail="ASF не запущен")

    stopped = []
    errors = []

    for bot_name in req.bot_names:
        result = await asf_ipc.stop_playing(bot_name)
        if result is not None:
            stopped.append(bot_name)
            session_key = f"{current_user.id}:{bot_name}"
            _farm_sessions.pop(session_key, None)
            # Обновляем в БД
            try:
                async with async_session() as db:
                    await save_farming_session(
                        db, bot_name=bot_name, owner_id=current_user.id,
                        status="stopped",
                    )
            except Exception:
                pass
        else:
            errors.append(bot_name)

    return {"stopped": stopped, "errors": errors}


@router.get("/farm/sessions")
async def farm_sessions(current_user: User = Depends(get_current_user)):
    """Активные сессии фарма часов для текущего пользователя (in-memory)."""
    now = time.time()
    user_sessions = [
        {
            **s,
            "elapsed_hours": round((now - s["started_at"]) / 3600, 2),
        }
        for key, s in _farm_sessions.items()
        if s["owner_id"] == current_user.id
    ]
    return {"sessions": user_sessions}


@router.get("/farm/sessions-db")
async def farm_sessions_db(
    include_finished: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Сессии фарма из БД (персистентные, переживают рестарт)."""
    from app.services.session_persistence import get_farming_sessions
    import json

    sessions = await get_farming_sessions(db, owner_id=current_user.id, include_finished=include_finished)
    return {
        "sessions": [
            {
                "id": s.id,
                "bot_name": s.bot_name,
                "session_type": s.session_type,
                "status": s.status,
                "app_ids": json.loads(s.app_ids_json) if s.app_ids_json else [],
                "hours_target": s.hours_target,
                "hours_farmed": s.hours_farmed,
                "breaks_taken": s.breaks_taken,
                "rotations_done": s.rotations_done,
                "error": s.error,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "finished_at": s.finished_at.isoformat() if s.finished_at else None,
            }
            for s in sessions
        ]
    }


# ─── Smart Farming ───────────────────────────────────────────


@router.post("/farm/smart-start")
async def farm_smart_start(
    req: SmartFarmStartRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Запустить Smart Farming — фарм с расписанием, перерывами и ротацией игр.

    Параметры:
    - bot_names: список ботов ASF
    - active_start_hour/active_end_hour: окно активности (часы 0–23)
    - break_interval_*: интервал перерывов
    - break_duration_*: длительность перерывов
    - game_rotation_hours: интервал ротации игр
    - use_random_games: случайные игры из пула F2P
    """
    from app.services.smart_farming import SmartFarmingConfig, start_smart_farming

    if not req.bot_names:
        raise HTTPException(status_code=400, detail="Список ботов пуст")

    # Конвертируем пул профилей: [{"730": 60}, {"570": 50}] → [{730: 60}, {570: 50}]
    weights_pool: list[dict[int, int]] = []
    if req.game_weights_pool:
        for wp in req.game_weights_pool:
            weights_pool.append({int(k): v for k, v in wp.items()})

    import random as _random

    # Для каждого бота — рандомный профиль из пула (или без профиля)
    results = []
    for bot_name in req.bot_names:
        bot_weights: dict[int, int] = {}
        if weights_pool:
            bot_weights = _random.choice(weights_pool)

        config = SmartFarmingConfig(
            bot_names=[bot_name],
            app_ids=req.app_ids,
            game_weights=bot_weights,
            active_start_hour=req.active_start_hour,
            active_end_hour=req.active_end_hour,
            start_jitter_minutes=req.start_jitter_minutes,
            stop_jitter_minutes=req.stop_jitter_minutes,
            break_interval_hours_min=req.break_interval_hours_min,
            break_interval_hours_max=req.break_interval_hours_max,
            break_duration_minutes_min=req.break_duration_minutes_min,
            break_duration_minutes_max=req.break_duration_minutes_max,
            game_rotation_hours=req.game_rotation_hours,
            games_per_rotation=req.games_per_rotation,
            use_random_games=req.use_random_games and not bot_weights,
            simulate_game_switching=req.simulate_game_switching,
        )

        session = await start_smart_farming(config, owner_id=current_user.id)
        results.append({
            "session_id": session.session_id,
            "bot_name": bot_name,
            "status": session.status,
            "profile_games": list(bot_weights.keys()) if bot_weights else "random_pool",
        })

    return {"sessions": results}


@router.post("/farm/smart-stop")
async def farm_smart_stop(
    req: SmartFarmStopRequest,
    current_user: User = Depends(get_current_user),
):
    """Остановить Smart Farming сессию."""
    from app.services.smart_farming import stop_smart_farming, get_smart_session

    session = get_smart_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    if session.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Нет доступа к этой сессии")

    success = await stop_smart_farming(req.session_id)
    if not success:
        raise HTTPException(status_code=500, detail="Не удалось остановить сессию")

    return {"session_id": req.session_id, "status": "stopped"}


@router.get("/farm/smart-sessions")
async def farm_smart_sessions(current_user: User = Depends(get_current_user)):
    """Список Smart Farming сессий текущего пользователя."""
    from app.services.smart_farming import get_smart_sessions
    return {"sessions": get_smart_sessions(owner_id=current_user.id)}


# ─── Raw команда ─────────────────────────────────────────────


@router.post("/command")
async def raw_command(
    req: RawCommandRequest,
    current_user: User = Depends(get_current_user),
):
    """Выполнить произвольную ASF команду (для ASF Console в UI)."""
    if not asf_manager.is_running():
        raise HTTPException(status_code=400, detail="ASF не запущен")
    if not await asf_ipc.is_ipc_available():
        raise HTTPException(status_code=503, detail="ASF IPC недоступен")

    result = await asf_ipc.send_command(req.command)
    if result is None:
        raise HTTPException(status_code=503, detail="Команда не выполнена")

    return {"command": req.command, "result": result}
