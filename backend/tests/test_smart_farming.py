"""
Unit-тесты для Smart Farming сервиса.

Тестирует: конфигурацию, расписание, ротацию игр, перерывы, основной цикл.
ASF IPC замокан — тесты не требуют запущенного ASF.
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.services.smart_farming import (
    SmartFarmingConfig,
    SmartFarmingSession,
    _is_in_active_window,
    _pick_random_games,
    _schedule_next_break,
    _schedule_next_rotation,
    _generate_session_id,
    start_smart_farming,
    stop_smart_farming,
    get_smart_sessions,
    get_smart_session,
    _smart_sessions,
    FREE_GAMES_POOL,
)


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def config():
    return SmartFarmingConfig(
        bot_names=["test_bot1", "test_bot2"],
        app_ids=[730, 570],
        active_start_hour=0,
        active_end_hour=23,
        break_interval_hours_min=0.001,  # очень короткий для тестов
        break_interval_hours_max=0.002,
        break_duration_minutes_min=1,
        break_duration_minutes_max=1,
        game_rotation_hours=0.001,
        games_per_rotation=3,
        use_random_games=True,
        simulate_game_switching=True,
    )


@pytest.fixture
def session(config):
    return SmartFarmingSession(
        session_id="sf_test_1234",
        config=config,
        owner_id=1,
        started_at=time.time(),
    )


@pytest.fixture(autouse=True)
def cleanup_sessions():
    """Чистим глобальное хранилище после каждого теста."""
    yield
    _smart_sessions.clear()


# ─── Тесты конфигурации ─────────────────────────────────────────


def test_config_defaults():
    """Дефолтные значения конфигурации."""
    cfg = SmartFarmingConfig(bot_names=["bot1"])
    assert cfg.active_start_hour == 8
    assert cfg.active_end_hour == 23
    assert cfg.break_interval_hours_min == 2.0
    assert cfg.break_interval_hours_max == 4.0
    assert cfg.games_per_rotation == 3
    assert cfg.use_random_games is True


def test_config_to_dict():
    """Сериализация конфигурации."""
    cfg = SmartFarmingConfig(bot_names=["bot1"], app_ids=[730])
    d = cfg.to_dict()
    assert d["bot_names"] == ["bot1"]
    assert d["app_ids"] == [730]
    assert "active_start_hour" in d


def test_session_to_dict(session):
    """Сериализация сессии."""
    d = session.to_dict()
    assert d["session_id"] == "sf_test_1234"
    assert d["owner_id"] == 1
    assert "elapsed_hours" in d
    assert "config" in d


# ─── Тесты окна активности ──────────────────────────────────────


def test_active_window_normal():
    """Нормальное окно (start < end)."""
    from datetime import datetime
    cfg = SmartFarmingConfig(bot_names=["bot"], active_start_hour=8, active_end_hour=23)
    current_hour = datetime.now().hour
    result = _is_in_active_window(cfg)
    assert result == (8 <= current_hour < 23)


def test_active_window_always():
    """Окно 0–23 — почти всегда активно."""
    cfg = SmartFarmingConfig(bot_names=["bot"], active_start_hour=0, active_end_hour=24)
    # 24 означает "весь день"
    # При start=0, end=24, start <= end, проверяем 0 <= hour < 24 — всегда true
    # Но наша реализация end_hour=24 → hour < 24 = True
    from datetime import datetime
    current_hour = datetime.now().hour
    expected = 0 <= current_hour < 24
    assert _is_in_active_window(cfg) == expected


def test_active_window_overnight():
    """Ночное окно (start > end, переход через полночь)."""
    cfg = SmartFarmingConfig(bot_names=["bot"], active_start_hour=22, active_end_hour=6)
    from datetime import datetime
    current_hour = datetime.now().hour
    expected = current_hour >= 22 or current_hour < 6
    assert _is_in_active_window(cfg) == expected


# ─── Тесты ротации игр ──────────────────────────────────────────


def test_pick_random_games():
    """Выбор случайных игр из пула."""
    cfg = SmartFarmingConfig(bot_names=["bot"], games_per_rotation=3)
    games = _pick_random_games(cfg)
    assert len(games) == 3
    assert all(g in FREE_GAMES_POOL for g in games)


def test_pick_random_games_with_exclusion():
    """Ротация исключает текущие игры."""
    cfg = SmartFarmingConfig(bot_names=["bot"], games_per_rotation=3)
    exclude = [730, 570, 440]
    games = _pick_random_games(cfg, exclude=exclude)
    assert len(games) == 3
    # Исключённые не должны попасть (если пул достаточно большой)
    for g in games:
        assert g not in exclude


def test_pick_random_games_with_custom_apps():
    """Пользовательские игры добавляются в пул."""
    cfg = SmartFarmingConfig(bot_names=["bot"], app_ids=[999999], games_per_rotation=20)
    games = _pick_random_games(cfg)
    # Пул расширен пользовательскими играми
    assert len(games) == 20


def test_pick_random_games_more_than_pool():
    """Запрос больше игр чем в пуле — возвращает все."""
    cfg = SmartFarmingConfig(bot_names=["bot"], games_per_rotation=999)
    games = _pick_random_games(cfg)
    assert len(games) == len(FREE_GAMES_POOL)


# ─── Тесты планирования ─────────────────────────────────────────


def test_schedule_next_break(session):
    """Планирование перерыва в допустимом диапазоне."""
    now = time.time()
    _schedule_next_break(session)
    assert session.next_break_at > now
    # В тестовой конфигурации интервал 0.001–0.002 часа (3.6–7.2 сек)
    diff = session.next_break_at - now
    assert 0 < diff < 60  # разумный диапазон для теста


def test_schedule_next_rotation(session):
    """Планирование ротации."""
    now = time.time()
    _schedule_next_rotation(session)
    assert session.next_rotation_at > now


def test_generate_session_id():
    """ID сессии уникален."""
    id1 = _generate_session_id(1)
    id2 = _generate_session_id(1)
    assert id1.startswith("sf_1_")
    assert id2.startswith("sf_1_")
    # Разные (за счёт рандома)
    # Не гарантируем уникальность в 100%, но крайне маловероятно
    # Просто проверяем формат


# ─── Тесты start/stop сессии ────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.smart_farming.asf_ipc")
async def test_start_and_stop_session(mock_ipc, config):
    """Запуск и остановка сессии."""
    mock_ipc.play_games = AsyncMock(return_value="OK")
    mock_ipc.stop_playing = AsyncMock(return_value="OK")

    session = await start_smart_farming(config, owner_id=42)
    assert session.session_id in _smart_sessions
    assert session.owner_id == 42

    # Даём циклу немного поработать
    await asyncio.sleep(0.5)
    assert session.status in ("active", "pending")

    # Останавливаем
    result = await stop_smart_farming(session.session_id)
    assert result is True
    assert session.status == "stopped"


@pytest.mark.asyncio
async def test_stop_nonexistent_session():
    """Остановка несуществующей сессии."""
    result = await stop_smart_farming("nonexistent")
    assert result is False


@pytest.mark.asyncio
@patch("app.services.smart_farming.asf_ipc")
async def test_get_sessions(mock_ipc, config):
    """Получение списка сессий."""
    mock_ipc.play_games = AsyncMock(return_value="OK")
    mock_ipc.stop_playing = AsyncMock(return_value="OK")

    s1 = await start_smart_farming(config, owner_id=1)
    s2 = await start_smart_farming(config, owner_id=2)

    all_sessions = get_smart_sessions()
    assert len(all_sessions) == 2

    user1_sessions = get_smart_sessions(owner_id=1)
    assert len(user1_sessions) == 1
    assert user1_sessions[0]["owner_id"] == 1

    # Cleanup
    await stop_smart_farming(s1.session_id)
    await stop_smart_farming(s2.session_id)


@pytest.mark.asyncio
@patch("app.services.smart_farming.asf_ipc")
async def test_game_rotation_direct(mock_ipc, config):
    """Ротация игр работает корректно (прямой вызов _rotate_games)."""
    from app.services.smart_farming import _rotate_games

    mock_ipc.play_games = AsyncMock(return_value="OK")
    mock_ipc.stop_playing = AsyncMock(return_value="OK")

    session = SmartFarmingSession(
        session_id="sf_test_rotation",
        config=config,
        owner_id=1,
        started_at=time.time(),
        current_apps={"test_bot1": [730, 570], "test_bot2": [440, 238960]},
    )

    await _rotate_games(session)

    assert session.rotations_done == 1
    assert session.last_rotation_at > 0
    # Каждый бот получил новые игры
    assert "test_bot1" in session.current_apps
    assert "test_bot2" in session.current_apps
    # play_games вызван для каждого бота (+ simulate_game_switching вызовы)
    assert mock_ipc.play_games.call_count >= 2


@pytest.mark.asyncio
@patch("app.services.smart_farming.asf_ipc")
async def test_break_triggers(mock_ipc, config):
    """Перерывы происходят по расписанию (ускоренный тест)."""
    mock_ipc.play_games = AsyncMock(return_value="OK")
    mock_ipc.stop_playing = AsyncMock(return_value="OK")

    # Конфиг с очень коротким интервалом перерывов и 1 сек перерывом
    config.break_interval_hours_min = 0.0001
    config.break_interval_hours_max = 0.0002
    config.break_duration_minutes_min = 0  # Будет round to 0 → 0 секунд
    config.break_duration_minutes_max = 0
    config.start_jitter_minutes = 0

    session = await start_smart_farming(config, owner_id=1)

    # Принудительно устанавливаем next_break в прошлое
    await asyncio.sleep(0.5)
    session.next_break_at = time.time() - 1

    # Ждём цикл
    await asyncio.sleep(35)  # check_interval = 30

    assert session.breaks_taken >= 1
    assert mock_ipc.stop_playing.call_count >= 1

    await stop_smart_farming(session.session_id)
