"""
Решение hCaptcha через CapSolver API.

Используется как fallback для Steam hCaptcha после Groq/Gemini AI солверов.
CapSolver — AI-powered, ~3-9 секунд, $0.80-3/1000.

Документация: https://docs.capsolver.com/en/
"""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

CAPSOLVER_API = "https://api.capsolver.com"


class CapSolverHCaptcha:
    """Решение hCaptcha через CapSolver API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._timeout = 120
        self._poll_interval = 3

    def solve(
        self,
        sitekey: str,
        page_url: str = "https://store.steampowered.com/join",
    ) -> str | None:
        """
        Решить hCaptcha и вернуть токен.

        Args:
            sitekey: hCaptcha sitekey
            page_url: URL страницы с капчей

        Returns:
            Токен hCaptcha или None
        """
        try:
            # Шаг 1: создать задачу
            resp = httpx.post(
                f"{CAPSOLVER_API}/createTask",
                json={
                    "clientKey": self.api_key,
                    "task": {
                        "type": "HCaptchaTaskProxyLess",
                        "websiteURL": page_url,
                        "websiteKey": sitekey,
                    },
                },
                timeout=30,
            )
            data = resp.json()

            if data.get("errorId", 0) != 0:
                logger.error("CapSolver create error: %s (code: %s)",
                             data.get("errorDescription"), data.get("errorCode"))
                return None

            task_id = data.get("taskId")
            if not task_id:
                logger.error("CapSolver: нет taskId в ответе: %s", data)
                return None

            logger.info("CapSolver задача создана: %s", task_id)

            # Шаг 2: polling результата
            start = time.monotonic()
            time.sleep(5)

            while time.monotonic() - start < self._timeout:
                resp = httpx.post(
                    f"{CAPSOLVER_API}/getTaskResult",
                    json={
                        "clientKey": self.api_key,
                        "taskId": task_id,
                    },
                    timeout=30,
                )
                data = resp.json()

                if data.get("errorId", 0) != 0:
                    logger.error("CapSolver result error: %s", data.get("errorDescription"))
                    return None

                status = data.get("status")

                if status == "ready":
                    solution = data.get("solution", {})
                    token = solution.get("gRecaptchaResponse") or solution.get("token")
                    elapsed = time.monotonic() - start
                    logger.info("CapSolver hCaptcha решена за %.0f сек", elapsed)
                    return token

                if status == "processing":
                    time.sleep(self._poll_interval)
                    continue

                logger.error("CapSolver unexpected status: %s", status)
                return None

            logger.error("CapSolver timeout (%d сек)", self._timeout)
            return None

        except Exception as e:
            logger.exception("Ошибка CapSolver: %s", e)
            return None

    def get_balance(self) -> float | None:
        """Проверить баланс аккаунта CapSolver."""
        try:
            resp = httpx.post(
                f"{CAPSOLVER_API}/getBalance",
                json={"clientKey": self.api_key},
                timeout=10,
            )
            data = resp.json()
            if data.get("errorId", 0) == 0:
                return data.get("balance", 0.0)
            return None
        except Exception:
            return None
