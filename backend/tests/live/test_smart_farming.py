"""
Live test — Smart Farming с ускоренными интервалами.

Запуск: python -m pytest tests/live/test_smart_farming.py -v -s
Требует: запущенный backend (localhost:8420). ASF не обязателен (мокается).

Тестирует:
- Запуск/остановка Smart Farming через API
- Перерывы (лог: "перерыв на X мин")
- Ротация игр (лог: "ротация игр [...] → [...]")
- Корректность ASF IPC команд (или мок если ASF не запущен)
"""

import asyncio
import logging
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

# Настраиваем логирование для видимости
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


# ─── Проверка что backend запущен ────────────────────────────────

BACKEND_URL = "http://localhost:8420"
ASF_URL = "http://localhost:1242"


async def _backend_alive() -> bool:
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{BACKEND_URL}/api/health", timeout=3)
            return r.status_code == 200
    except Exception:
        return False


async def _asf_alive() -> bool:
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{ASF_URL}/Api/ASF", timeout=3)
            return r.status_code == 200
    except Exception:
        return False


# ─── Live тесты ──────────────────────────────────────────────────


@pytest.mark.live
@pytest.mark.asyncio
async def test_smart_farming_session_lifecycle():
    """
    Тест жизненного цикла Smart Farming сессии.

    Запускает сессию с ускоренными параметрами, проверяет что:
    1. Сессия создаётся и стартует
    2. Перерывы планируются
    3. Ротация игр планируется
    4. Сессия корректно останавливается
    """
    from app.services.smart_farming import (
        SmartFarmingConfig,
        start_smart_farming,
        stop_smart_farming,
        get_smart_sessions,
    )

    asf_available = await _asf_alive()
    logger.info(f"ASF доступен: {asf_available}")

    # Мокаем ASF IPC если он не запущен
    mock_ctx = None
    if not asf_available:
        logger.info("ASF не запущен — мокаем IPC вызовы")
        mock_ctx = patch("app.services.smart_farming.asf_ipc")
        mock_ipc = mock_ctx.start()
        mock_ipc.play_games = AsyncMock(return_value="OK (mocked)")
        mock_ipc.stop_playing = AsyncMock(return_value="OK (mocked)")

    try:
        config = SmartFarmingConfig(
            bot_names=["test_bot_sf"],
            app_ids=[730, 570],
            active_start_hour=0,   # всегда активно
            active_end_hour=24,
            start_jitter_minutes=0,
            break_interval_hours_min=0.001,
            break_interval_hours_max=0.002,
            break_duration_minutes_min=0,
            break_duration_minutes_max=0,
            game_rotation_hours=0.001,
            games_per_rotation=3,
            use_random_games=True,
        )

        # Запускаем
        session = await start_smart_farming(config, owner_id=999)
        logger.info(f"Сессия создана: {session.session_id}")

        assert session.session_id is not None
        assert session.owner_id == 999

        # Ждём старта
        await asyncio.sleep(1)
        logger.info(f"Статус после 1s: {session.status}")
        assert session.status in ("active", "pending")

        # Проверяем что сессия видна в списке
        sessions = get_smart_sessions(owner_id=999)
        assert len(sessions) >= 1
        logger.info(f"Найдено сессий: {len(sessions)}")

        # Проверяем что перерывы и ротация запланированы
        assert session.next_break_at > 0
        assert session.next_rotation_at > 0
        logger.info(f"Перерыв запланирован: {session.next_break_at}")
        logger.info(f"Ротация запланирована: {session.next_rotation_at}")

        # Проверяем что боты получили игры
        logger.info(f"Текущие игры: {session.current_apps}")
        assert "test_bot_sf" in session.current_apps
        assert len(session.current_apps["test_bot_sf"]) > 0

        # Останавливаем
        success = await stop_smart_farming(session.session_id)
        assert success is True
        logger.info(f"Сессия остановлена: {session.status}")
        assert session.status == "stopped"

        logger.info("✅ Lifecycle тест пройден")

    finally:
        if mock_ctx:
            mock_ctx.stop()


@pytest.mark.live
@pytest.mark.asyncio
async def test_smart_farming_game_rotation():
    """
    Тест ротации игр — прямой вызов _rotate_games.

    Проверяет:
    - Новые игры отличаются от старых
    - IPC команды отправляются корректно
    """
    from app.services.smart_farming import (
        SmartFarmingConfig,
        SmartFarmingSession,
        _rotate_games,
    )

    mock_ctx = patch("app.services.smart_farming.asf_ipc")
    mock_ipc = mock_ctx.start()
    mock_ipc.play_games = AsyncMock(return_value="OK (mocked)")

    try:
        config = SmartFarmingConfig(
            bot_names=["bot1", "bot2"],
            games_per_rotation=3,
            use_random_games=True,
            simulate_game_switching=True,
        )
        session = SmartFarmingSession(
            session_id="sf_rotation_test",
            config=config,
            owner_id=1,
            started_at=time.time(),
            current_apps={"bot1": [730, 570, 440], "bot2": [238960, 1599340, 1366540]},
        )

        old_apps_bot1 = session.current_apps["bot1"].copy()
        old_apps_bot2 = session.current_apps["bot2"].copy()

        await _rotate_games(session)

        new_apps_bot1 = session.current_apps["bot1"]
        new_apps_bot2 = session.current_apps["bot2"]

        logger.info(f"bot1: {old_apps_bot1} → {new_apps_bot1}")
        logger.info(f"bot2: {old_apps_bot2} → {new_apps_bot2}")

        assert session.rotations_done == 1
        assert new_apps_bot1 != old_apps_bot1, "Игры bot1 должны измениться"
        assert new_apps_bot2 != old_apps_bot2, "Игры bot2 должны измениться"

        # IPC вызовы: simulate_game_switching делает доп. вызов на бота + финальный
        assert mock_ipc.play_games.call_count >= 2
        logger.info(f"IPC play_games вызван {mock_ipc.play_games.call_count} раз")

        # Логируем все IPC вызовы
        for call in mock_ipc.play_games.call_args_list:
            logger.info(f"  IPC call: play_games{call}")

        logger.info("✅ Ротация игр тест пройден")

    finally:
        mock_ctx.stop()


@pytest.mark.live
@pytest.mark.asyncio
async def test_smart_farming_break_cycle():
    """
    Тест перерывов — прямой вызов _take_break.

    Проверяет:
    - Фарм останавливается во время перерыва
    - Фарм возобновляется после перерыва
    - Статус меняется break → active
    """
    from app.services.smart_farming import (
        SmartFarmingConfig,
        SmartFarmingSession,
        _take_break,
    )

    mock_ctx = patch("app.services.smart_farming.asf_ipc")
    mock_ipc = mock_ctx.start()
    mock_ipc.play_games = AsyncMock(return_value="OK (mocked)")
    mock_ipc.stop_playing = AsyncMock(return_value="OK (mocked)")

    try:
        config = SmartFarmingConfig(
            bot_names=["bot_break"],
            break_duration_minutes_min=0,  # 0 минут = мгновенный перерыв
            break_duration_minutes_max=0,
            use_random_games=True,
        )
        session = SmartFarmingSession(
            session_id="sf_break_test",
            config=config,
            owner_id=1,
            started_at=time.time(),
            status="active",
        )

        t0 = time.time()
        await _take_break(session)
        duration = time.time() - t0

        logger.info(f"Перерыв длился {duration:.1f}s")
        logger.info(f"Статус после перерыва: {session.status}")
        logger.info(f"Перерывов взято: {session.breaks_taken}")

        assert session.breaks_taken == 1
        assert session.status == "active"
        assert mock_ipc.stop_playing.call_count >= 1
        assert mock_ipc.play_games.call_count >= 1  # возобновление

        logger.info("✅ Перерыв тест пройден")

    finally:
        mock_ctx.stop()


@pytest.mark.live
@pytest.mark.asyncio
async def test_smart_farming_api_endpoint():
    """
    Тест API endpoint POST /asf/farm/smart-start через HTTP.

    Проверяет что endpoint доступен и принимает параметры.
    Требует запущенный backend.
    """
    alive = await _backend_alive()
    if not alive:
        pytest.skip("Backend не запущен")

    # Получаем токен
    async with httpx.AsyncClient() as c:
        # Регистрируем тестового юзера или логинимся
        login_resp = await c.post(
            f"{BACKEND_URL}/api/auth/login",
            json={"username": "admin", "password": "admin"},
            timeout=5,
        )
        if login_resp.status_code != 200:
            pytest.skip("Не удалось залогиниться (нет тестового юзера)")

        token = login_resp.json().get("access_token")
        headers = {"Authorization": f"Bearer {token}"}

        # Запускаем Smart Farming
        resp = await c.post(
            f"{BACKEND_URL}/api/asf/farm/smart-start",
            headers=headers,
            json={
                "bot_names": ["test_api_bot"],
                "app_ids": [730],
                "active_start_hour": 0,
                "active_end_hour": 24,
                "start_jitter_minutes": 0,
                "game_rotation_hours": 1.0,
            },
            timeout=5,
        )
        logger.info(f"smart-start response: {resp.status_code} {resp.text}")

        # Может вернуть 200 или ошибку если ASF не запущен — проверяем что endpoint работает
        assert resp.status_code in (200, 400, 503)

        if resp.status_code == 200:
            data = resp.json()
            session_id = data.get("session_id")
            assert session_id is not None
            logger.info(f"Сессия создана через API: {session_id}")

            # Проверяем список сессий
            sessions_resp = await c.get(
                f"{BACKEND_URL}/api/asf/farm/smart-sessions",
                headers=headers,
                timeout=5,
            )
            assert sessions_resp.status_code == 200
            sessions = sessions_resp.json().get("sessions", [])
            logger.info(f"Smart sessions: {len(sessions)}")

            # Останавливаем
            stop_resp = await c.post(
                f"{BACKEND_URL}/api/asf/farm/smart-stop",
                headers=headers,
                json={"session_id": session_id},
                timeout=5,
            )
            logger.info(f"smart-stop response: {stop_resp.status_code}")
            assert stop_resp.status_code == 200

    logger.info("✅ API endpoint тест пройден")
