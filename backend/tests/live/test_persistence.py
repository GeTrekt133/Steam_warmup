"""
Live test — персистентность сессий в реальной БД.

Запуск: python -m pytest tests/live/test_persistence.py -v -s
Требует: запущенный backend (для проверки БД).
"""

import json
import logging

import pytest
import pytest_asyncio
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.session import WarmupSession, FarmingSession
from app.services.session_persistence import (
    save_warmup_session,
    save_farming_session,
    get_warmup_sessions,
    get_farming_sessions,
    mark_interrupted_warmup_sessions,
    get_interrupted_farming_sessions,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@pytest_asyncio.fixture
async def db():
    """In-memory SQLite для live тестов."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_sess = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_sess() as session:
        yield session
    await engine.dispose()


@pytest.mark.live
@pytest.mark.asyncio
async def test_warmup_session_full_lifecycle(db):
    """
    Полный цикл жизни warmup сессии:
    create → update → finish → query
    """
    # Создаём сессию
    s = await save_warmup_session(db, login="live_test_acc", owner_id=99, status="running", quests_total=13)
    logger.info(f"Создана warmup сессия: id={s.id}, login={s.account_login}")
    assert s.id is not None
    assert s.started_at is not None

    # Обновляем прогресс
    quests = [
        {"quest_id": "setup_avatar", "status": "done"},
        {"quest_id": "rate_game", "status": "done"},
        {"quest_id": "join_group", "status": "skipped", "error": "timeout"},
    ]
    s2 = await save_warmup_session(
        db, login="live_test_acc", owner_id=99, status="done",
        quests=quests, quests_done=2, quests_total=3,
    )
    logger.info(f"Обновлена: status={s2.status}, done={s2.quests_done}/{s2.quests_total}")
    assert s2.status == "done"
    assert s2.finished_at is not None
    assert json.loads(s2.quests_json)[2]["error"] == "timeout"

    # Запрашиваем из БД
    all_sessions = await get_warmup_sessions(db, owner_id=99, include_finished=True)
    logger.info(f"Найдено сессий для owner=99: {len(all_sessions)}")
    assert len(all_sessions) == 1

    logger.info("✅ Warmup lifecycle тест пройден")


@pytest.mark.live
@pytest.mark.asyncio
async def test_farming_session_full_lifecycle(db):
    """
    Полный цикл farming сессии:
    create → update hours → stop → query
    """
    s = await save_farming_session(
        db, bot_name="live_bot", owner_id=99,
        status="active", app_ids=[730, 570], hours_target=10.0,
    )
    logger.info(f"Создана farming сессия: id={s.id}, bot={s.bot_name}")
    assert s.status == "active"

    # Обновляем часы
    s2 = await save_farming_session(
        db, bot_name="live_bot", owner_id=99,
        status="active", hours_farmed=3.5,
    )
    logger.info(f"Обновлена: hours_farmed={s2.hours_farmed}")
    assert s2.hours_farmed == 3.5
    assert s2.id == s.id  # тот же объект

    # Останавливаем
    s3 = await save_farming_session(
        db, bot_name="live_bot", owner_id=99,
        status="stopped",
    )
    assert s3.status == "stopped"
    assert s3.finished_at is not None

    # Запрашиваем
    active = await get_farming_sessions(db, owner_id=99, include_finished=False)
    assert len(active) == 0
    all_sessions = await get_farming_sessions(db, owner_id=99, include_finished=True)
    assert len(all_sessions) == 1

    logger.info("✅ Farming lifecycle тест пройден")


@pytest.mark.live
@pytest.mark.asyncio
async def test_restart_recovery_simulation(db):
    """
    Симуляция рестарта backend:
    1. Создаём активные сессии
    2. Помечаем warmup как interrupted
    3. Находим farming для восстановления
    """
    # Warmup — running
    await save_warmup_session(db, login="acc1", owner_id=1, status="running", quests_total=10)
    await save_warmup_session(db, login="acc2", owner_id=1, status="running", quests_total=10)

    # Farming — active
    await save_farming_session(db, bot_name="farm_bot1", owner_id=1, status="active", app_ids=[730])
    await save_farming_session(db, bot_name="farm_bot2", owner_id=1, status="paused", app_ids=[570])

    logger.info("Сессии созданы, симулируем рестарт...")

    # Рестарт: помечаем warmup как interrupted
    await mark_interrupted_warmup_sessions(db)

    warmup_sessions = await get_warmup_sessions(db, owner_id=1, include_finished=True)
    interrupted_count = sum(1 for s in warmup_sessions if s.status == "interrupted")
    logger.info(f"Warmup interrupted: {interrupted_count}/{len(warmup_sessions)}")
    assert interrupted_count == 2

    # Farming — находим для восстановления
    interrupted_farming = await get_interrupted_farming_sessions(db)
    logger.info(f"Farming для восстановления: {len(interrupted_farming)}")
    assert len(interrupted_farming) == 2

    for s in interrupted_farming:
        apps = json.loads(s.app_ids_json) if s.app_ids_json else []
        logger.info(f"  {s.bot_name}: status={s.status}, apps={apps}")

    logger.info("✅ Restart recovery тест пройден")
