"""
Персистентность сессий Warmup и Farming.

Сохраняет статус сессий в БД, восстанавливает при рестарте backend.
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import WarmupSession, FarmingSession

logger = logging.getLogger(__name__)


# ─── Warmup Sessions ────────────────────────────────────────────


async def save_warmup_session(
    db: AsyncSession,
    login: str,
    owner_id: int,
    status: str,
    quests: list[dict] | None = None,
    current_quest: str | None = None,
    quests_done: int = 0,
    quests_total: int = 0,
    error: str | None = None,
    account_id: int | None = None,
) -> WarmupSession:
    """Создаёт или обновляет сессию warmup в БД."""
    # Ищем существующую незавершённую сессию для этого аккаунта
    result = await db.execute(
        select(WarmupSession).where(
            WarmupSession.account_login == login,
            WarmupSession.owner_id == owner_id,
            WarmupSession.status.in_(["pending", "running"]),
        )
    )
    session = result.scalar_one_or_none()

    if session:
        session.status = status
        session.quests_json = json.dumps(quests, ensure_ascii=False) if quests else None
        session.current_quest = current_quest
        session.quests_done = quests_done
        session.quests_total = quests_total
        session.error = error
        if status == "running" and not session.started_at:
            session.started_at = datetime.now(timezone.utc)
        if status in ("done", "error"):
            session.finished_at = datetime.now(timezone.utc)
    else:
        session = WarmupSession(
            account_login=login,
            account_id=account_id,
            owner_id=owner_id,
            status=status,
            quests_json=json.dumps(quests, ensure_ascii=False) if quests else None,
            current_quest=current_quest,
            quests_done=quests_done,
            quests_total=quests_total,
            error=error,
            started_at=datetime.now(timezone.utc) if status == "running" else None,
        )
        db.add(session)

    await db.commit()
    await db.refresh(session)
    logger.debug(f"[Persistence] Warmup session saved: {login} → {status}")
    return session


async def get_warmup_sessions(
    db: AsyncSession,
    owner_id: int,
    include_finished: bool = False,
) -> list[WarmupSession]:
    """Получает сессии warmup из БД."""
    query = select(WarmupSession).where(WarmupSession.owner_id == owner_id)
    if not include_finished:
        query = query.where(WarmupSession.status.in_(["pending", "running", "interrupted"]))
    query = query.order_by(WarmupSession.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def mark_interrupted_warmup_sessions(db: AsyncSession):
    """При рестарте backend помечает все running сессии как interrupted."""
    await db.execute(
        update(WarmupSession)
        .where(WarmupSession.status.in_(["pending", "running"]))
        .values(status="interrupted", error="Backend перезапущен")
    )
    await db.commit()
    logger.info("[Persistence] Прерванные warmup сессии помечены как interrupted")


# ─── Farming Sessions ───────────────────────────────────────────


async def save_farming_session(
    db: AsyncSession,
    bot_name: str,
    owner_id: int,
    status: str,
    session_type: str = "manual",
    smart_session_id: str | None = None,
    app_ids: list[int] | None = None,
    hours_target: float = 0.0,
    hours_farmed: float = 0.0,
    smart_config: dict | None = None,
    breaks_taken: int = 0,
    rotations_done: int = 0,
    error: str | None = None,
) -> FarmingSession:
    """Создаёт или обновляет сессию фарма в БД."""
    # Ищем существующую активную сессию для этого бота
    query = select(FarmingSession).where(
        FarmingSession.bot_name == bot_name,
        FarmingSession.owner_id == owner_id,
        FarmingSession.status.in_(["active", "paused", "break"]),
    )
    if smart_session_id:
        query = select(FarmingSession).where(
            FarmingSession.smart_session_id == smart_session_id,
        )

    result = await db.execute(query)
    session = result.scalar_one_or_none()

    if session:
        session.status = status
        session.app_ids_json = json.dumps(app_ids) if app_ids else None
        session.hours_farmed = hours_farmed
        session.breaks_taken = breaks_taken
        session.rotations_done = rotations_done
        session.error = error
        if status in ("stopped", "error"):
            session.finished_at = datetime.now(timezone.utc)
    else:
        session = FarmingSession(
            bot_name=bot_name,
            owner_id=owner_id,
            session_type=session_type,
            smart_session_id=smart_session_id,
            status=status,
            app_ids_json=json.dumps(app_ids) if app_ids else None,
            hours_target=hours_target,
            hours_farmed=hours_farmed,
            smart_config_json=json.dumps(smart_config, ensure_ascii=False) if smart_config else None,
            breaks_taken=breaks_taken,
            rotations_done=rotations_done,
            error=error,
            started_at=datetime.now(timezone.utc) if status in ("active", "paused") else None,
        )
        db.add(session)

    await db.commit()
    await db.refresh(session)
    logger.debug(f"[Persistence] Farming session saved: {bot_name} → {status}")
    return session


async def get_farming_sessions(
    db: AsyncSession,
    owner_id: int,
    include_finished: bool = False,
) -> list[FarmingSession]:
    """Получает сессии фарма из БД."""
    query = select(FarmingSession).where(FarmingSession.owner_id == owner_id)
    if not include_finished:
        query = query.where(FarmingSession.status.in_(["active", "paused", "break"]))
    query = query.order_by(FarmingSession.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_interrupted_farming_sessions(db: AsyncSession) -> list[FarmingSession]:
    """Получает сессии фарма, прерванные рестартом (для восстановления)."""
    result = await db.execute(
        select(FarmingSession).where(
            FarmingSession.status.in_(["active", "paused", "break"]),
        )
    )
    return list(result.scalars().all())


async def mark_interrupted_farming_sessions(db: AsyncSession):
    """При рестарте backend помечает все активные сессии."""
    # Не помечаем как ошибку — farming можно восстановить
    count = await db.execute(
        select(FarmingSession).where(
            FarmingSession.status.in_(["active", "paused", "break"]),
        )
    )
    sessions = list(count.scalars().all())
    logger.info(f"[Persistence] Найдено {len(sessions)} прерванных farming сессий для восстановления")
    return sessions
