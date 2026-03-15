"""
Endpoints для сбора датасета капч.

POST /dataset/collect/hcaptcha — запустить сбор N hCaptcha
POST /dataset/collect/funcaptcha — запустить сбор N FunCaptcha
GET  /dataset/stats — статистика датасета
GET  /dataset/samples — последние N записей
"""

import asyncio
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.proxy import Proxy
from app.api.endpoints.auth import get_current_user
from app.services.captcha_collector import CaptchaCollector, CollectResult

router = APIRouter()

# In-memory статус фоновых задач сбора
_collect_tasks: dict[str, dict] = {}


class CollectRequest(BaseModel):
    count: int = Field(10, ge=1, le=500, description="Количество челленджей для сбора")
    proxy_id: int | None = Field(None, description="ID прокси для сбора")


@router.post("/collect/hcaptcha")
async def collect_hcaptcha(
    req: CollectRequest,
    db: AsyncSession = Depends(get_db),
):
    """Запустить сбор hCaptcha челленджей в фоне."""
    proxy_str = None
    if req.proxy_id:
        result = await db.execute(select(Proxy).where(Proxy.id == req.proxy_id))
        px = result.scalar_one_or_none()
        if px:
            proxy_str = f"{px.protocol}://"
            if px.username and px.password:
                proxy_str += f"{px.username}:{px.password}@"
            proxy_str += f"{px.host}:{px.port}"

    task_id = uuid.uuid4().hex[:8]
    _collect_tasks[task_id] = {"status": "running", "type": "hcaptcha", "count": req.count}

    async def _run():
        collector = CaptchaCollector()
        result = await collector.collect_hcaptcha(count=req.count, proxy=proxy_str)
        _collect_tasks[task_id] = {
            "status": "done",
            "type": "hcaptcha",
            "collected": result.collected,
            "errors": result.errors,
            "error_messages": result.error_messages[-10:],  # последние 10
        }

    asyncio.create_task(_run())
    return {"task_id": task_id, "status": "started", "count": req.count}


@router.post("/collect/funcaptcha")
async def collect_funcaptcha(
    req: CollectRequest,
    db: AsyncSession = Depends(get_db),
):
    """Запустить сбор FunCaptcha скриншотов в фоне."""
    proxy_dict = None
    if req.proxy_id:
        result = await db.execute(select(Proxy).where(Proxy.id == req.proxy_id))
        px = result.scalar_one_or_none()
        if px:
            proxy_dict = {"server": f"{px.protocol}://{px.host}:{px.port}"}
            if px.username:
                proxy_dict["username"] = px.username
            if px.password:
                proxy_dict["password"] = px.password

    task_id = uuid.uuid4().hex[:8]
    _collect_tasks[task_id] = {"status": "running", "type": "funcaptcha", "count": req.count}

    async def _run():
        collector = CaptchaCollector()
        result = await collector.collect_funcaptcha(count=req.count, proxy=proxy_dict)
        _collect_tasks[task_id] = {
            "status": "done",
            "type": "funcaptcha",
            "collected": result.collected,
            "errors": result.errors,
            "error_messages": result.error_messages[-10:],
        }

    asyncio.create_task(_run())
    return {"task_id": task_id, "status": "started", "count": req.count}


@router.get("/collect/status/{task_id}")
async def collect_status(
    task_id: str,
):
    """Статус задачи сбора."""
    task = _collect_tasks.get(task_id)
    if not task:
        return {"error": "Задача не найдена"}
    return task


@router.get("/stats")
async def dataset_stats():
    """Статистика собранного датасета."""
    collector = CaptchaCollector()
    return collector.get_stats()


@router.get("/samples")
async def dataset_samples(
    source: str = Query("hcaptcha", description="hcaptcha или funcaptcha"),
    limit: int = Query(10, ge=1, le=100),
):
    """Последние N записей из датасета."""
    collector = CaptchaCollector()
    return collector.get_samples(source=source, limit=limit)
