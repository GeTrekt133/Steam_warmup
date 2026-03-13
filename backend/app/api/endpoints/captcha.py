"""
Endpoints для тестирования captcha-солверов.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.models.user import User
from app.api.endpoints.auth import get_current_user
from app.services.captcha_orchestrator import get_orchestrator, SolverType

router = APIRouter()


class SolveRequest(BaseModel):
    sitekey: str = "f5561ba9-8f1e-40ca-9b5b-a0b3f719ef34"  # Steam default
    host: str = "store.steampowered.com"
    solver: str | None = None  # "groq" or "gemini", None = auto


@router.post("/solve")
async def solve_captcha(
    req: SolveRequest,
    current_user: User = Depends(get_current_user),
):
    """Решить hCaptcha через оркестратор. Для тестирования солверов."""
    orchestrator = get_orchestrator()

    preferred = None
    if req.solver:
        try:
            preferred = SolverType(req.solver)
        except ValueError:
            return {"error": f"Неизвестный солвер: {req.solver}. Доступны: groq, gemini"}

    result = await orchestrator.solve(req.sitekey, req.host, preferred)

    return {
        "success": result.success,
        "token": result.token[:60] + "..." if result.token else None,
        "solver": result.solver.value if result.solver else None,
        "elapsed_sec": round(result.elapsed_sec, 1),
        "attempts": result.attempts,
        "error": result.error,
    }


@router.get("/solvers")
async def list_solvers(
    current_user: User = Depends(get_current_user),
):
    """Список доступных солверов и их статистика."""
    orchestrator = get_orchestrator()
    return {
        "available": [s.value for s in orchestrator.available_solvers],
        "stats": orchestrator.get_stats_summary(),
    }
