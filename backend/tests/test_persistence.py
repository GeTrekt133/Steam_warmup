"""
Unit-тесты для персистентности сессий Warmup и Farming.

Использует in-memory SQLite для изолированных тестов.
"""

import json
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.session import WarmupSession, FarmingSession
from app.services.session_persistence import (
    save_warmup_session,
    get_warmup_sessions,
    mark_interrupted_warmup_sessions,
    save_farming_session,
    get_farming_sessions,
    get_interrupted_farming_sessions,
)


# ─── Fixtures ────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    """Создаёт async in-memory SQLite session для тестов."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_sess = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_sess() as session:
        yield session

    await engine.dispose()


# ─── Warmup Session Tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_save_warmup_session_create(db_session):
    """Создание новой warmup сессии."""
    session = await save_warmup_session(
        db_session,
        login="test_user",
        owner_id=1,
        status="running",
        quests_total=13,
    )
    assert session.id is not None
    assert session.account_login == "test_user"
    assert session.status == "running"
    assert session.quests_total == 13
    assert session.started_at is not None


@pytest.mark.asyncio
async def test_save_warmup_session_update(db_session):
    """Обновление существующей running сессии."""
    # Создаём
    s1 = await save_warmup_session(
        db_session, login="user1", owner_id=1, status="running", quests_total=10,
    )

    # Обновляем
    quests = [{"quest_id": "q1", "status": "done"}, {"quest_id": "q2", "status": "skipped"}]
    s2 = await save_warmup_session(
        db_session, login="user1", owner_id=1, status="done",
        quests=quests, quests_done=2, quests_total=10,
    )

    assert s1.id == s2.id  # тот же объект
    assert s2.status == "done"
    assert s2.quests_done == 2
    assert s2.finished_at is not None

    parsed = json.loads(s2.quests_json)
    assert len(parsed) == 2


@pytest.mark.asyncio
async def test_get_warmup_sessions(db_session):
    """Получение списка сессий по owner_id."""
    await save_warmup_session(db_session, login="a1", owner_id=1, status="running")
    await save_warmup_session(db_session, login="a2", owner_id=1, status="done")
    await save_warmup_session(db_session, login="a3", owner_id=2, status="running")

    # Только незавершённые
    sessions = await get_warmup_sessions(db_session, owner_id=1, include_finished=False)
    assert len(sessions) == 1
    assert sessions[0].account_login == "a1"

    # Все
    sessions_all = await get_warmup_sessions(db_session, owner_id=1, include_finished=True)
    assert len(sessions_all) == 2


@pytest.mark.asyncio
async def test_mark_interrupted_warmup(db_session):
    """Пометка running сессий как interrupted при рестарте."""
    await save_warmup_session(db_session, login="a1", owner_id=1, status="running")
    await save_warmup_session(db_session, login="a2", owner_id=1, status="pending")
    await save_warmup_session(db_session, login="a3", owner_id=1, status="done")

    await mark_interrupted_warmup_sessions(db_session)

    # Проверяем
    result = await db_session.execute(select(WarmupSession))
    all_sessions = list(result.scalars().all())

    statuses = {s.account_login: s.status for s in all_sessions}
    assert statuses["a1"] == "interrupted"
    assert statuses["a2"] == "interrupted"
    assert statuses["a3"] == "done"  # не тронута


# ─── Farming Session Tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_save_farming_session_create(db_session):
    """Создание farming сессии."""
    session = await save_farming_session(
        db_session,
        bot_name="bot1",
        owner_id=1,
        status="active",
        app_ids=[730, 570],
        hours_target=10.0,
    )
    assert session.id is not None
    assert session.bot_name == "bot1"
    assert session.status == "active"
    assert json.loads(session.app_ids_json) == [730, 570]
    assert session.started_at is not None


@pytest.mark.asyncio
async def test_save_farming_session_update(db_session):
    """Обновление farming сессии."""
    s1 = await save_farming_session(
        db_session, bot_name="bot1", owner_id=1, status="active", app_ids=[730],
    )

    s2 = await save_farming_session(
        db_session, bot_name="bot1", owner_id=1, status="stopped",
        hours_farmed=5.5,
    )

    assert s1.id == s2.id
    assert s2.status == "stopped"
    assert s2.hours_farmed == 5.5
    assert s2.finished_at is not None


@pytest.mark.asyncio
async def test_save_farming_session_smart(db_session):
    """Создание smart farming сессии."""
    config = {"active_start_hour": 8, "active_end_hour": 23}
    session = await save_farming_session(
        db_session,
        bot_name="smart_bot",
        owner_id=1,
        status="active",
        session_type="smart",
        smart_session_id="sf_1_123_456",
        smart_config=config,
        app_ids=[730],
    )
    assert session.session_type == "smart"
    assert session.smart_session_id == "sf_1_123_456"
    assert json.loads(session.smart_config_json) == config


@pytest.mark.asyncio
async def test_get_farming_sessions(db_session):
    """Получение farming сессий по owner_id."""
    await save_farming_session(db_session, bot_name="b1", owner_id=1, status="active")
    await save_farming_session(db_session, bot_name="b2", owner_id=1, status="stopped")
    await save_farming_session(db_session, bot_name="b3", owner_id=2, status="active")

    sessions = await get_farming_sessions(db_session, owner_id=1)
    assert len(sessions) == 1
    assert sessions[0].bot_name == "b1"


@pytest.mark.asyncio
async def test_get_interrupted_farming_sessions(db_session):
    """Находит прерванные сессии для восстановления."""
    await save_farming_session(db_session, bot_name="b1", owner_id=1, status="active")
    await save_farming_session(db_session, bot_name="b2", owner_id=2, status="paused")
    await save_farming_session(db_session, bot_name="b3", owner_id=1, status="stopped")

    interrupted = await get_interrupted_farming_sessions(db_session)
    assert len(interrupted) == 2
    names = {s.bot_name for s in interrupted}
    assert names == {"b1", "b2"}


@pytest.mark.asyncio
async def test_session_survives_simulated_restart(db_session):
    """Симуляция рестарта: сессия сохраняется и восстанавливается."""
    # Создаём активную сессию
    await save_farming_session(
        db_session, bot_name="survivor", owner_id=1,
        status="active", app_ids=[730, 570], hours_farmed=2.5,
    )

    # "Рестарт": находим прерванные сессии
    interrupted = await get_interrupted_farming_sessions(db_session)
    assert len(interrupted) == 1
    assert interrupted[0].bot_name == "survivor"
    assert interrupted[0].hours_farmed == 2.5
    assert json.loads(interrupted[0].app_ids_json) == [730, 570]
