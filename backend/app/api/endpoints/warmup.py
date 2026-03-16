"""
Endpoints прогрева Steam-аккаунтов (Community Badge).

POST /warmup/start       — запустить прогрев для списка аккаунтов
GET  /warmup/status/{id} — статус задачи
POST /warmup/stop/{id}   — остановить задачу
GET  /warmup/quests      — список доступных квестов
"""

import asyncio
import threading
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.endpoints.auth import get_current_user
from app.models.user import User
from app.services.warmup_service import (
    WarmupRunner,
    AccountWarmupStatus,
    QUEST_LIST,
)
from app.services.steam_browser import _ensure_proactor
from app.services import text_generator

router = APIRouter()

# ─── In-memory задачи прогрева ────────────────────────────────

_warmup_tasks: dict[str, dict] = {}


# ─── Схемы ───────────────────────────────────────────────────


class WarmupStartRequest(BaseModel):
    accounts: list[dict]  # [{login, password, shared_secret?}]
    master_steam_id: str | None = None
    quests: list[str] = ["all"]
    max_concurrent: int = 2
    proxy_config: dict | None = None  # {server, username?, password?}
    text_prompt: str | None = None    # промпт для LLM-генерации текстов (стиль/тон)


class WarmupStopRequest(BaseModel):
    pass


# ─── Endpoints ───────────────────────────────────────────────


@router.get("/quests")
async def list_quests(current_user: User = Depends(get_current_user)):
    """Список доступных квестов для прогрева."""
    return {
        "quests": [
            {"id": qid, "name": qname}
            for qid, qname in QUEST_LIST
        ]
    }


@router.post("/start")
async def warmup_start(
    req: WarmupStartRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Запустить прогрев для списка аккаунтов.

    Аккаунты передаются из фронтенда (localStorage).
    Задача выполняется в фоне, прогресс через GET /warmup/status/{task_id}.
    """
    if not req.accounts:
        raise HTTPException(status_code=400, detail="Список аккаунтов пуст")

    task_id = str(uuid.uuid4())[:8]

    # Инициализируем статусы
    account_statuses = []
    for acc in req.accounts:
        login = acc.get("login", "?")
        status = AccountWarmupStatus(login=login)
        account_statuses.append((acc, status))

    task = {
        "task_id": task_id,
        "owner_id": current_user.id,
        "total": len(req.accounts),
        "completed": 0,
        "statuses": [s for _, s in account_statuses],
        "running": True,
        "stop_flag": False,
    }
    _warmup_tasks[task_id] = task

    # Запускаем в фоне
    asyncio.create_task(
        _run_warmup(task_id, account_statuses, req)
    )

    return {"task_id": task_id, "total": len(req.accounts), "status": "started"}


async def _run_warmup(
    task_id: str,
    account_statuses: list[tuple[dict, AccountWarmupStatus]],
    req: WarmupStartRequest,
):
    """Фоновая задача прогрева с ограничением параллельности."""
    task = _warmup_tasks[task_id]
    semaphore = asyncio.Semaphore(max(1, min(5, req.max_concurrent)))

    # Генерируем тексты для всех аккаунтов пакетом через LLM
    count = len(account_statuses)
    prompt = req.text_prompt

    nicknames = await text_generator.generate_batch(count, "nickname", prompt)
    bios = await text_generator.generate_batch(count, "bio", prompt)
    reviews = await text_generator.generate_batch(count, "review", prompt)
    comments = await text_generator.generate_batch(count, "comment", prompt)

    async def process_one(idx: int, acc: dict, status: AccountWarmupStatus):
        async with semaphore:
            if task["stop_flag"]:
                status.status = "skipped"
                return

            generated_texts = {
                "nickname": nicknames[idx] if idx < len(nicknames) else None,
                "bio": bios[idx] if idx < len(bios) else None,
                "review": reviews[idx] if idx < len(reviews) else None,
                "comment": comments[idx] if idx < len(comments) else None,
            }

            runner = WarmupRunner(
                login=acc.get("login", ""),
                password=acc.get("password", ""),
                shared_secret=acc.get("shared_secret"),
                master_steam_id=req.master_steam_id,
                proxy_config=req.proxy_config,
                quest_ids=req.quests,
                status=status,
                generated_texts=generated_texts,
            )

            # Запускаем sync Playwright в отдельном потоке
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()

            def target():
                _ensure_proactor()
                try:
                    result = runner.run()
                    loop.call_soon_threadsafe(fut.set_result, result)
                except Exception as exc:
                    loop.call_soon_threadsafe(fut.set_exception, exc)

            thread = threading.Thread(target=target, daemon=True)
            thread.start()

            try:
                await fut
            except Exception as e:
                status.status = "error"
                status.error = str(e)[:300]

            task["completed"] += 1

    # Запускаем все аккаунты с семафором
    tasks = [process_one(i, acc, status) for i, (acc, status) in enumerate(account_statuses)]
    await asyncio.gather(*tasks, return_exceptions=True)

    task["running"] = False


@router.get("/status/{task_id}")
async def warmup_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """Статус задачи прогрева с детализацией по квестам."""
    task = _warmup_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    return {
        "task_id": task_id,
        "total": task["total"],
        "completed": task["completed"],
        "running": task["running"],
        "accounts": [s.to_dict() for s in task["statuses"]],
    }


@router.post("/generate-texts")
async def generate_texts(
    count: int = 3,
    text_type: str = "nickname",
    prompt: str | None = None,
    current_user: User = Depends(get_current_user),
):
    """
    Тестовая генерация текстов через LLM.

    text_type: nickname | bio | review | comment
    prompt: подсказка (стиль, тон)
    """
    texts = await text_generator.generate_batch(
        count=min(count, 20),
        text_type=text_type,
        user_prompt=prompt,
    )
    return {"texts": texts, "text_type": text_type, "count": len(texts)}


@router.post("/stop/{task_id}")
async def warmup_stop(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """Остановить задачу прогрева (текущие квесты завершатся)."""
    task = _warmup_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    task["stop_flag"] = True
    return {"task_id": task_id, "message": "Остановка запрошена"}
