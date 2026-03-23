"""
Smart Farming — интеллектуальный фарм часов с расписанием, перерывами и ротацией игр.

Функции:
- Настраиваемые окна активности (например 08:00–23:00)
- Случайные перерывы (каждые 2–4 часа пауза на 15–45 мин)
- Рандомное время старта/стопа (±30 мин от заданного)
- Ротация игр: менять набор каждые N часов
- Имитация паттернов: "выходить" из одной игры и "заходить" в другую

Используется совместно с ASF IPC для управления фармом.
"""

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.services import asf_ipc

logger = logging.getLogger(__name__)

# ─── Файловый лог фарма ──────────────────────────────────────────
_LOG_DIR = Path(os.path.expanduser("~/Steam_warmup_logs"))
_LOG_DIR.mkdir(exist_ok=True)

_farm_file_handler = logging.FileHandler(
    _LOG_DIR / "smart_farming.log", encoding="utf-8",
)
_farm_file_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
)
_farm_file_handler.setLevel(logging.INFO)
logger.addHandler(_farm_file_handler)
logger.setLevel(logging.DEBUG)


# ─── Пул F2P игр (копия из asf.py для ротации) ─────────────────

FREE_GAMES_POOL = [
    730, 570, 440, 578080, 1172470, 230410, 304930, 444090,
    386360, 236390, 1085660, 238960, 1599340, 1366540,
    1097150, 2399830, 2767030, 1963000, 3221870, 945360,
]

# Имена игр для читаемых логов
GAME_NAMES: dict[int, str] = {
    730: "CS2", 570: "Dota 2", 440: "TF2", 578080: "PUBG",
    1172470: "Apex Legends", 230410: "Warframe", 304930: "Unturned",
    444090: "Paladins", 386360: "SMITE", 236390: "War Thunder",
    1085660: "Destiny 2", 238960: "Path of Exile", 1599340: "Lost Ark",
    1366540: "Enlisted", 1097150: "Fall Guys", 2399830: "Overwatch 2",
    2767030: "Marvel Rivals", 1963000: "The Finals", 3221870: "Delta Force",
    945360: "Among Us",
}


def _game_str(app_id: int) -> str:
    """Человекочитаемое название игры для логов."""
    name = GAME_NAMES.get(app_id)
    return f"{name} ({app_id})" if name else str(app_id)


def _games_str(app_ids: list[int]) -> str:
    """Список игр для логов."""
    return ", ".join(_game_str(a) for a in app_ids)


# ─── Конфигурация Smart Farming ─────────────────────────────────


@dataclass
class SmartFarmingConfig:
    """Конфигурация Smart Farming для одного бота/группы."""
    bot_names: list[str]
    app_ids: list[int] = field(default_factory=list)
    game_weights: dict[int, int] = field(default_factory=dict)  # {730: 60, 570: 20} — веса для ротации

    # Окно активности (часы, 0–23)
    active_start_hour: int = 8       # начало активности
    active_end_hour: int = 23        # конец активности

    # Рандомизация времени старта/стопа
    start_jitter_minutes: int = 30   # ±30 мин от заданного
    stop_jitter_minutes: int = 30

    # Перерывы
    break_interval_hours_min: float = 2.0   # мин интервал между перерывами
    break_interval_hours_max: float = 4.0   # макс интервал
    break_duration_minutes_min: int = 15    # мин длительность перерыва
    break_duration_minutes_max: int = 45    # макс длительность

    # Ротация игр
    game_rotation_hours: float = 3.0   # менять игры каждые N часов
    games_per_rotation: int = 1        # сколько игр на ротацию
    use_random_games: bool = True      # использовать случайные игры из пула

    # Имитация паттернов
    simulate_game_switching: bool = True  # иногда выходить/заходить в игры

    def to_dict(self) -> dict:
        return {
            "bot_names": self.bot_names,
            "app_ids": self.app_ids,
            "game_weights": {str(k): v for k, v in self.game_weights.items()},
            "active_start_hour": self.active_start_hour,
            "active_end_hour": self.active_end_hour,
            "start_jitter_minutes": self.start_jitter_minutes,
            "stop_jitter_minutes": self.stop_jitter_minutes,
            "break_interval_hours_min": self.break_interval_hours_min,
            "break_interval_hours_max": self.break_interval_hours_max,
            "break_duration_minutes_min": self.break_duration_minutes_min,
            "break_duration_minutes_max": self.break_duration_minutes_max,
            "game_rotation_hours": self.game_rotation_hours,
            "games_per_rotation": self.games_per_rotation,
            "use_random_games": self.use_random_games,
            "simulate_game_switching": self.simulate_game_switching,
        }


# ─── Статус сессии ───────────────────────────────────────────────


@dataclass
class SmartFarmingSession:
    """Состояние одной Smart Farming сессии."""
    session_id: str
    config: SmartFarmingConfig
    owner_id: int
    status: str = "pending"  # pending | active | paused | break | stopped | error
    started_at: float = 0.0
    last_break_at: float = 0.0
    next_break_at: float = 0.0
    last_rotation_at: float = 0.0
    next_rotation_at: float = 0.0
    current_apps: dict[str, list[int]] = field(default_factory=dict)  # bot_name → app_ids
    total_hours_farmed: float = 0.0
    breaks_taken: int = 0
    rotations_done: int = 0
    error: str | None = None
    _task: asyncio.Task | None = field(default=None, repr=False)

    def to_dict(self) -> dict:
        now = time.time()
        return {
            "session_id": self.session_id,
            "status": self.status,
            "config": self.config.to_dict(),
            "owner_id": self.owner_id,
            "started_at": self.started_at,
            "elapsed_hours": round((now - self.started_at) / 3600, 2) if self.started_at else 0,
            "next_break_at": self.next_break_at,
            "next_rotation_at": self.next_rotation_at,
            "current_apps": self.current_apps,
            "total_hours_farmed": round(self.total_hours_farmed, 2),
            "breaks_taken": self.breaks_taken,
            "rotations_done": self.rotations_done,
            "error": self.error,
        }


# ─── Менеджер Smart Farming ─────────────────────────────────────

# In-memory хранение активных сессий
_smart_sessions: dict[str, SmartFarmingSession] = {}


def _generate_session_id(owner_id: int) -> str:
    """Генерирует уникальный ID сессии."""
    return f"sf_{owner_id}_{int(time.time())}_{random.randint(1000, 9999)}"


def _is_in_active_window(config: SmartFarmingConfig) -> bool:
    """Проверяет, находится ли текущее время в окне активности."""
    now_hour = datetime.now().hour
    if config.active_start_hour <= config.active_end_hour:
        return config.active_start_hour <= now_hour < config.active_end_hour
    else:
        # Переход через полночь (напр. 22:00–06:00)
        return now_hour >= config.active_start_hour or now_hour < config.active_end_hour


def _schedule_next_break(session: SmartFarmingSession) -> float:
    """Планирует следующий перерыв (случайный интервал)."""
    config = session.config
    interval_hours = random.uniform(
        config.break_interval_hours_min,
        config.break_interval_hours_max,
    )
    interval_seconds = interval_hours * 3600
    next_break = time.time() + interval_seconds
    session.next_break_at = next_break
    logger.info(
        f"[SmartFarm] {session.session_id}: следующий перерыв через "
        f"{interval_hours:.1f}ч ({interval_seconds:.0f}s)"
    )
    return next_break


def _schedule_next_rotation(session: SmartFarmingSession) -> float:
    """Планирует следующую ротацию игр."""
    interval_seconds = session.config.game_rotation_hours * 3600
    # Добавляем ±15% jitter
    jitter = interval_seconds * random.uniform(-0.15, 0.15)
    next_rotation = time.time() + interval_seconds + jitter
    session.next_rotation_at = next_rotation
    logger.info(
        f"[SmartFarm] {session.session_id}: следующая ротация через "
        f"{(interval_seconds + jitter) / 3600:.1f}ч"
    )
    return next_rotation


def _pick_random_games(config: SmartFarmingConfig, exclude: list[int] | None = None) -> list[int]:
    """Выбирает случайный набор игр для ротации.

    Если задан game_weights — используем взвешенный выбор.
    Игра с весом 60 попадает в ротацию в 3 раза чаще чем с весом 20.
    """
    # --- Взвешенный режим (профиль игрока) ---
    if config.game_weights:
        pool_ids = list(config.game_weights.keys())
        weights = [config.game_weights[g] for g in pool_ids]

        # Исключаем текущие (чтобы ротация была заметна)
        if exclude:
            filtered = [(g, w) for g, w in zip(pool_ids, weights) if g not in exclude]
            if filtered:
                pool_ids, weights = zip(*filtered)
                pool_ids = list(pool_ids)
                weights = list(weights)
            # Если после исключения пусто — берём всё
            else:
                pool_ids = list(config.game_weights.keys())
                weights = [config.game_weights[g] for g in pool_ids]

        count = min(config.games_per_rotation, len(pool_ids))
        # Без повторов: выбираем по одной с весами
        selected: list[int] = []
        remaining_ids = list(pool_ids)
        remaining_weights = list(weights)
        for _ in range(count):
            if not remaining_ids:
                break
            chosen = random.choices(remaining_ids, weights=remaining_weights, k=1)[0]
            selected.append(chosen)
            idx = remaining_ids.index(chosen)
            remaining_ids.pop(idx)
            remaining_weights.pop(idx)
        return selected

    # --- Обычный режим (равные шансы) ---
    pool = list(FREE_GAMES_POOL)
    if config.app_ids:
        pool = list(set(pool + config.app_ids))
    if exclude:
        pool = [g for g in pool if g not in exclude]
    if not pool:
        pool = list(FREE_GAMES_POOL)
    count = min(config.games_per_rotation, len(pool))
    return random.sample(pool, count)


async def _start_playing(session: SmartFarmingSession):
    """Запускает фарм для всех ботов сессии."""
    config = session.config
    for bot_name in config.bot_names:
        if config.game_weights:
            apps = _pick_random_games(config)
        elif config.use_random_games:
            apps = _pick_random_games(config)
        elif config.app_ids:
            apps = config.app_ids[:5]
        else:
            apps = _pick_random_games(config)

        # Добавляем игры в библиотеку (если F2P и нет в аккаунте — ASF добавит)
        add_result = await asf_ipc.add_license(bot_name, apps)
        logger.info(
            f"[SmartFarm] {session.session_id} | {bot_name} | "
            f"addlicense [{_games_str(apps)}] → {add_result}"
        )

        session.current_apps[bot_name] = apps
        result = await asf_ipc.play_games(bot_name, apps)
        logger.info(
            f"[SmartFarm] {session.session_id} | {bot_name} | "
            f"▶ PLAY [{_games_str(apps)}] → {result}"
        )


async def _stop_playing(session: SmartFarmingSession):
    """Останавливает фарм для всех ботов сессии."""
    for bot_name in session.config.bot_names:
        old_apps = session.current_apps.get(bot_name, [])
        result = await asf_ipc.stop_playing(bot_name)
        logger.info(
            f"[SmartFarm] {session.session_id} | {bot_name} | "
            f"■ STOP (было: [{_games_str(old_apps)}]) → {result}"
        )
    session.current_apps.clear()


async def _rotate_games(session: SmartFarmingSession):
    """Ротация игр: меняет набор для каждого бота."""
    config = session.config
    for bot_name in config.bot_names:
        old_apps = session.current_apps.get(bot_name, [])
        new_apps = _pick_random_games(config, exclude=old_apps)

        if config.simulate_game_switching:
            # Имитация: сначала "выходим" из одной игры
            if old_apps and len(old_apps) > 1:
                removed = random.choice(old_apps)
                temp_apps = [a for a in old_apps if a != removed]
                await asf_ipc.play_games(bot_name, temp_apps)
                logger.info(
                    f"[SmartFarm] {session.session_id} | {bot_name} | "
                    f"↩ вышел из {_game_str(removed)}, осталось [{_games_str(temp_apps)}]"
                )
                await asyncio.sleep(random.uniform(2, 8))

        # Добавляем новые игры в библиотеку перед запуском
        await asf_ipc.add_license(bot_name, new_apps)

        # Переключаемся на новые игры
        session.current_apps[bot_name] = new_apps
        await asf_ipc.play_games(bot_name, new_apps)
        logger.info(
            f"[SmartFarm] {session.session_id} | {bot_name} | "
            f"🔄 РОТАЦИЯ [{_games_str(old_apps)}] → [{_games_str(new_apps)}]"
        )

    session.rotations_done += 1
    session.last_rotation_at = time.time()
    _schedule_next_rotation(session)


async def _take_break(session: SmartFarmingSession):
    """Перерыв: останавливает фарм на случайное время."""
    config = session.config
    duration_minutes = random.randint(
        config.break_duration_minutes_min,
        config.break_duration_minutes_max,
    )
    duration_seconds = duration_minutes * 60

    logger.info(
        f"[SmartFarm] {session.session_id} | "
        f"☕ ПЕРЕРЫВ {duration_minutes} мин (нафармлено {session.total_hours_farmed:.1f}ч)"
    )

    session.status = "break"
    await _stop_playing(session)

    # Ждём перерыв
    await asyncio.sleep(duration_seconds)

    session.breaks_taken += 1
    session.last_break_at = time.time()
    _schedule_next_break(session)

    # Возобновляем фарм
    if session.status == "break":  # мог быть остановлен пользователем
        session.status = "active"
        await _start_playing(session)
        logger.info(
            f"[SmartFarm] {session.session_id} | "
            f"☕→▶ ПЕРЕРЫВ ЗАКОНЧЕН, фарм возобновлён (перерывов: {session.breaks_taken})"
        )


async def _smart_farming_loop(session: SmartFarmingSession):
    """
    Основной цикл Smart Farming.

    Проверяет:
    1. Находимся ли в окне активности
    2. Пора ли брать перерыв
    3. Пора ли ротировать игры
    """
    config = session.config
    session.started_at = time.time()
    session.status = "active"

    # Логируем конфигурацию при старте
    if config.game_weights:
        weights_str = ", ".join(f"{_game_str(k)}={v}" for k, v in config.game_weights.items())
        logger.info(
            f"[SmartFarm] {session.session_id} | КОНФИГ: "
            f"боты={config.bot_names}, профиль=[{weights_str}], "
            f"окно={config.active_start_hour}:00–{config.active_end_hour}:00, "
            f"перерывы={config.break_interval_hours_min}-{config.break_interval_hours_max}ч, "
            f"ротация каждые {config.game_rotation_hours}ч по {config.games_per_rotation} игр"
        )
    else:
        logger.info(
            f"[SmartFarm] {session.session_id} | КОНФИГ: "
            f"боты={config.bot_names}, профиль=РАНДОМ ИЗ ПУЛА, "
            f"окно={config.active_start_hour}:00–{config.active_end_hour}:00, "
            f"перерывы={config.break_interval_hours_min}-{config.break_interval_hours_max}ч, "
            f"ротация каждые {config.game_rotation_hours}ч по {config.games_per_rotation} игр"
        )

    # Рандомизация времени старта
    if config.start_jitter_minutes > 0:
        jitter = random.uniform(0, config.start_jitter_minutes * 60)
        logger.info(
            f"[SmartFarm] {session.session_id} | ⏳ jitter {jitter / 60:.1f} мин перед стартом"
        )
        await asyncio.sleep(jitter)

    # Ждём окна активности
    if not _is_in_active_window(config):
        session.status = "paused"
        logger.info(
            f"[SmartFarm] {session.session_id} | ⏸ вне окна активности "
            f"({config.active_start_hour}:00–{config.active_end_hour}:00), ожидание"
        )
        while not _is_in_active_window(config) and session.status != "stopped":
            await asyncio.sleep(60)
        if session.status == "stopped":
            return
        session.status = "active"

    # Запускаем фарм
    await _start_playing(session)
    _schedule_next_break(session)
    _schedule_next_rotation(session)

    # Основной цикл — проверяем каждые 30 сек
    check_interval = 30
    while session.status not in ("stopped", "error"):
        try:
            await asyncio.sleep(check_interval)
            now = time.time()

            # Обновляем время фарма
            if session.status == "active":
                session.total_hours_farmed += check_interval / 3600

            # Проверяем окно активности
            if not _is_in_active_window(config):
                if session.status == "active":
                    logger.info(
                        f"[SmartFarm] {session.session_id} | "
                        f"⏸ ОКНО ЗАКРЫЛОСЬ ({config.active_end_hour}:00), пауза "
                        f"(нафармлено {session.total_hours_farmed:.1f}ч)"
                    )
                    session.status = "paused"
                    await _stop_playing(session)
                continue
            elif session.status == "paused":
                logger.info(
                    f"[SmartFarm] {session.session_id} | "
                    f"▶ ОКНО ОТКРЫЛОСЬ ({config.active_start_hour}:00), возобновление"
                )
                session.status = "active"
                await _start_playing(session)
                _schedule_next_break(session)
                _schedule_next_rotation(session)

            # Проверяем перерыв
            if session.status == "active" and now >= session.next_break_at:
                await _take_break(session)

            # Проверяем ротацию игр
            if session.status == "active" and now >= session.next_rotation_at:
                await _rotate_games(session)

        except asyncio.CancelledError:
            logger.info(f"[SmartFarm] {session.session_id}: задача отменена")
            break
        except Exception as e:
            logger.error(f"[SmartFarm] {session.session_id}: ошибка в цикле: {e}")
            session.error = str(e)[:300]
            # Продолжаем работу при некритичных ошибках
            await asyncio.sleep(60)

    # Остановка
    await _stop_playing(session)
    if session.status != "error":
        session.status = "stopped"
    logger.info(
        f"[SmartFarm] {session.session_id}: сессия завершена, "
        f"часов: {session.total_hours_farmed:.1f}, "
        f"перерывов: {session.breaks_taken}, ротаций: {session.rotations_done}"
    )


# ─── Публичное API ──────────────────────────────────────────────


async def start_smart_farming(
    config: SmartFarmingConfig,
    owner_id: int,
) -> SmartFarmingSession:
    """Запускает Smart Farming сессию."""
    session_id = _generate_session_id(owner_id)
    session = SmartFarmingSession(
        session_id=session_id,
        config=config,
        owner_id=owner_id,
    )

    # Запускаем фоновую задачу
    task = asyncio.create_task(_smart_farming_loop(session))
    session._task = task

    _smart_sessions[session_id] = session
    logger.info(
        f"[SmartFarm] Запущена сессия {session_id} для ботов {config.bot_names}"
    )
    return session


async def stop_smart_farming(session_id: str) -> bool:
    """Останавливает Smart Farming сессию."""
    session = _smart_sessions.get(session_id)
    if not session:
        return False

    session.status = "stopped"
    if session._task and not session._task.done():
        session._task.cancel()
        try:
            await session._task
        except asyncio.CancelledError:
            pass

    await _stop_playing(session)
    logger.info(f"[SmartFarm] Сессия {session_id} остановлена")
    return True


def get_smart_sessions(owner_id: int | None = None) -> list[dict]:
    """Возвращает список Smart Farming сессий."""
    sessions = _smart_sessions.values()
    if owner_id is not None:
        sessions = [s for s in sessions if s.owner_id == owner_id]
    return [s.to_dict() for s in sessions]


def get_smart_session(session_id: str) -> SmartFarmingSession | None:
    """Возвращает конкретную сессию."""
    return _smart_sessions.get(session_id)


async def cleanup_stopped_sessions():
    """Удаляет завершённые сессии из памяти."""
    to_remove = [
        sid for sid, s in _smart_sessions.items()
        if s.status in ("stopped", "error")
    ]
    for sid in to_remove:
        del _smart_sessions[sid]
    if to_remove:
        logger.info(f"[SmartFarm] Очищено {len(to_remove)} завершённых сессий")
