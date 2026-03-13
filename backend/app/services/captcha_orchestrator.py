"""
Captcha Orchestrator — единый async-интерфейс для решения hCaptcha.

Пробует доступные солверы по приоритету (быстрый → надёжный),
с retry и fallback. Используется registration service и другими модулями.

Порядок:
1. HCaptchaSolver (Groq) — быстрый, API-based, ~5-15с
2. ChallengerSolver (Gemini) — надёжный, Playwright browser, ~30-60с
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import partial

from app.config import settings

logger = logging.getLogger(__name__)


class SolverType(str, Enum):
    GROQ = "groq"
    GEMINI = "gemini"


@dataclass
class CaptchaResult:
    success: bool
    token: str | None = None
    solver: SolverType | None = None
    elapsed_sec: float = 0.0
    attempts: int = 0
    error: str | None = None


@dataclass
class SolverStats:
    """Статистика солвера за сессию."""
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    total_time: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts > 0 else 0.0

    @property
    def avg_time(self) -> float:
        return self.total_time / self.successes if self.successes > 0 else 0.0


class CaptchaOrchestrator:
    """
    Async orchestrator для hCaptcha солверов.

    Использование:
        orchestrator = CaptchaOrchestrator()
        result = await orchestrator.solve("sitekey", host="store.steampowered.com")
        if result.success:
            print(result.token)
    """

    def __init__(
        self,
        groq_api_key: str | None = None,
        gemini_api_key: str | None = None,
        max_retries_per_solver: int = 2,
        proxy_list: list[str] | None = None,
    ):
        self._groq_key = groq_api_key or settings.GROQ_API_KEY
        self._gemini_key = gemini_api_key or settings.GEMINI_API_KEY
        self._max_retries = max_retries_per_solver
        self._proxy_list = proxy_list or []

        # Lazy-initialized solver instances
        self._groq_solver = None
        self._gemini_solver = None

        # Stats
        self.stats: dict[SolverType, SolverStats] = {
            SolverType.GROQ: SolverStats(),
            SolverType.GEMINI: SolverStats(),
        }

    @property
    def available_solvers(self) -> list[SolverType]:
        """Список доступных солверов (у которых есть API ключ)."""
        solvers = []
        if self._groq_key:
            solvers.append(SolverType.GROQ)
        if self._gemini_key:
            solvers.append(SolverType.GEMINI)
        return solvers

    def _get_groq_solver(self):
        if self._groq_solver is None:
            from app.captcha import HCaptchaSolver
            self._groq_solver = HCaptchaSolver(self._groq_key)
            if self._proxy_list:
                self._groq_solver.set_proxies(self._proxy_list)
        return self._groq_solver

    def _get_gemini_solver(self):
        if self._gemini_solver is None:
            from app.captcha import ChallengerSolver
            self._gemini_solver = ChallengerSolver(self._gemini_key)
        return self._gemini_solver

    def _solve_with_groq(self, sitekey: str, host: str) -> tuple[str, str]:
        """Синхронный вызов Groq-солвера. Возвращает (status, token)."""
        solver = self._get_groq_solver()
        task = solver.generate_hcaptcha(sitekey)
        status, token, _ = solver.resolve_captcha(task, max_attempts=1)
        return status, token

    def _solve_with_gemini(self, sitekey: str, host: str) -> tuple[str, str]:
        """Синхронный вызов Gemini-солвера. Возвращает (status, token)."""
        solver = self._get_gemini_solver()
        task_id = solver.generate_hcaptcha(sitekey)
        result = solver.resolve_captcha(task_id)
        if result and result[0] == "OK":
            return result[0], result[1]
        raise Exception("Gemini solver returned no token")

    async def _try_solver(
        self, solver_type: SolverType, sitekey: str, host: str
    ) -> CaptchaResult:
        """Попытка решить капчу конкретным солвером с retry."""
        loop = asyncio.get_event_loop()

        if solver_type == SolverType.GROQ:
            func = partial(self._solve_with_groq, sitekey, host)
        elif solver_type == SolverType.GEMINI:
            func = partial(self._solve_with_gemini, sitekey, host)
        else:
            return CaptchaResult(success=False, error=f"Unknown solver: {solver_type}")

        last_error = ""
        for attempt in range(1, self._max_retries + 1):
            start = time.monotonic()
            self.stats[solver_type].attempts += 1

            try:
                logger.info(
                    "[%s] Attempt %d/%d for sitekey=%s...",
                    solver_type.value, attempt, self._max_retries, sitekey[:16],
                )
                status, token = await loop.run_in_executor(None, func)
                elapsed = time.monotonic() - start
                self.stats[solver_type].successes += 1
                self.stats[solver_type].total_time += elapsed

                logger.info(
                    "[%s] Solved in %.1fs, token=%s...",
                    solver_type.value, elapsed, token[:40],
                )
                return CaptchaResult(
                    success=True,
                    token=token,
                    solver=solver_type,
                    elapsed_sec=elapsed,
                    attempts=attempt,
                )

            except Exception as e:
                elapsed = time.monotonic() - start
                self.stats[solver_type].failures += 1
                self.stats[solver_type].total_time += elapsed
                last_error = str(e)
                logger.warning(
                    "[%s] Attempt %d failed (%.1fs): %s",
                    solver_type.value, attempt, elapsed, e,
                )

        return CaptchaResult(
            success=False,
            solver=solver_type,
            attempts=self._max_retries,
            error=last_error,
        )

    async def solve(
        self,
        sitekey: str,
        host: str = "store.steampowered.com",
        preferred_solver: SolverType | None = None,
    ) -> CaptchaResult:
        """
        Решить hCaptcha. Пробует солверы по приоритету с fallback.

        Args:
            sitekey: hCaptcha sitekey
            host: домен сайта
            preferred_solver: принудительно использовать конкретный солвер

        Returns:
            CaptchaResult с токеном или ошибкой
        """
        solvers = self.available_solvers
        if not solvers:
            return CaptchaResult(
                success=False,
                error="Нет доступных солверов. Укажите GROQ_API_KEY или GEMINI_API_KEY в .env",
            )

        if preferred_solver and preferred_solver in solvers:
            order = [preferred_solver]
        else:
            order = solvers  # groq first, then gemini

        total_attempts = 0
        errors = []

        for solver_type in order:
            result = await self._try_solver(solver_type, sitekey, host)
            total_attempts += result.attempts
            if result.success:
                result.attempts = total_attempts
                return result
            errors.append(f"{solver_type.value}: {result.error}")

        return CaptchaResult(
            success=False,
            attempts=total_attempts,
            error=" | ".join(errors),
        )

    def get_stats_summary(self) -> dict:
        """Статистика по всем солверам."""
        return {
            solver.value: {
                "attempts": s.attempts,
                "successes": s.successes,
                "failures": s.failures,
                "success_rate": f"{s.success_rate:.0%}",
                "avg_time": f"{s.avg_time:.1f}s",
            }
            for solver, s in self.stats.items()
            if s.attempts > 0
        }

    def close(self):
        """Освобождение ресурсов (Playwright браузеры)."""
        if self._groq_solver:
            try:
                self._groq_solver.close()
            except Exception:
                pass
        # ChallengerSolver не держит постоянный браузер


# Singleton для использования из endpoints
_orchestrator: CaptchaOrchestrator | None = None


def get_orchestrator() -> CaptchaOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = CaptchaOrchestrator()
    return _orchestrator
