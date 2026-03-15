"""
Решение FunCaptcha (Arkose Labs) для Outlook/Hotmail.

Провайдеры:
- EzCaptcha (рекомендуется для Outlook, $1.2/1000)
- 2captcha (fallback)
- anti-captcha (fallback)

Outlook FunCaptcha public key: B7D8911C-5CC8-A9A3-35B0-554ACEE604DA
"""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

OUTLOOK_FUNCAPTCHA_PUBLIC_KEY = "B7D8911C-5CC8-A9A3-35B0-554ACEE604DA"
OUTLOOK_SIGNUP_URL = "https://signup.live.com/signup"


class FunCaptchaSolver:
    """Решение FunCaptcha через внешний API."""

    def __init__(self, api_key: str, service: str = "ezcaptcha"):
        self.api_key = api_key
        self.service = service
        self._timeout = 180  # секунд (Outlook капчи сложные)
        self._poll_interval = 5

    def solve(
        self,
        public_key: str = OUTLOOK_FUNCAPTCHA_PUBLIC_KEY,
        page_url: str = OUTLOOK_SIGNUP_URL,
    ) -> str | None:
        """Отправляет задачу на решение и ждёт результат."""
        solvers = {
            "ezcaptcha": self._solve_ezcaptcha,
            "2captcha": self._solve_2captcha,
            "anti-captcha": self._solve_anticaptcha,
        }
        solver = solvers.get(self.service)
        if not solver:
            logger.error("Неизвестный сервис капчи: %s", self.service)
            return None
        return solver(public_key, page_url)

    # ── EzCaptcha (рекомендуется для Outlook) ────────────────

    def _solve_ezcaptcha(self, public_key: str, page_url: str) -> str | None:
        """Решение через EzCaptcha API — специализируется на Outlook FunCaptcha."""
        try:
            # Шаг 1: создать задачу
            resp = httpx.post(
                "https://api.ez-captcha.com/createTask",
                json={
                    "clientKey": self.api_key,
                    "task": {
                        "type": "FunCaptchaTaskProxyless",
                        "websiteURL": page_url,
                        "websitePublicKey": public_key,
                    },
                },
                timeout=30,
            )
            data = resp.json()

            if data.get("errorId", 0) != 0:
                logger.error("EzCaptcha create error: %s", data.get("errorDescription"))
                return None

            task_id = data["taskId"]
            logger.info("EzCaptcha задача создана: %s", task_id)

            # Шаг 2: polling
            start = time.monotonic()
            time.sleep(10)

            while time.monotonic() - start < self._timeout:
                resp = httpx.post(
                    "https://api.ez-captcha.com/getTaskResult",
                    json={
                        "clientKey": self.api_key,
                        "taskId": task_id,
                    },
                    timeout=30,
                )
                data = resp.json()

                if data.get("status") == "ready":
                    token = data["solution"]["token"]
                    logger.info("EzCaptcha FunCaptcha решена за %.0f сек", time.monotonic() - start)
                    return token

                if data.get("status") == "processing":
                    time.sleep(self._poll_interval)
                    continue

                logger.error("EzCaptcha error: %s", data.get("errorDescription"))
                return None

            logger.error("EzCaptcha timeout (%d сек)", self._timeout)
            return None

        except Exception as e:
            logger.exception("Ошибка EzCaptcha: %s", e)
            return None

    # ── 2captcha (fallback) ──────────────────────────────────

    def _solve_2captcha(self, public_key: str, page_url: str) -> str | None:
        """Решение через 2captcha.com API."""
        try:
            resp = httpx.post(
                "https://2captcha.com/in.php",
                data={
                    "key": self.api_key,
                    "method": "funcaptcha",
                    "publickey": public_key,
                    "pageurl": page_url,
                    "json": "1",
                },
                timeout=30,
            )
            data = resp.json()

            if data.get("status") != 1:
                logger.error("2captcha submit error: %s", data.get("request"))
                return None

            task_id = data["request"]
            logger.info("2captcha задача создана: %s", task_id)

            start = time.monotonic()
            time.sleep(10)

            while time.monotonic() - start < self._timeout:
                resp = httpx.get(
                    "https://2captcha.com/res.php",
                    params={
                        "key": self.api_key,
                        "action": "get",
                        "id": task_id,
                        "json": "1",
                    },
                    timeout=30,
                )
                data = resp.json()

                if data.get("status") == 1:
                    token = data["request"]
                    logger.info("2captcha FunCaptcha решена за %.0f сек", time.monotonic() - start)
                    return token

                if data.get("request") == "CAPCHA_NOT_READY":
                    time.sleep(self._poll_interval)
                    continue

                logger.error("2captcha error: %s", data.get("request"))
                return None

            logger.error("2captcha timeout (%d сек)", self._timeout)
            return None

        except Exception as e:
            logger.exception("Ошибка 2captcha: %s", e)
            return None

    # ── anti-captcha (fallback) ──────────────────────────────

    def _solve_anticaptcha(self, public_key: str, page_url: str) -> str | None:
        """Решение через anti-captcha.com API."""
        try:
            resp = httpx.post(
                "https://api.anti-captcha.com/createTask",
                json={
                    "clientKey": self.api_key,
                    "task": {
                        "type": "FunCaptchaTaskProxyless",
                        "websiteURL": page_url,
                        "websitePublicKey": public_key,
                    },
                },
                timeout=30,
            )
            data = resp.json()

            if data.get("errorId", 0) != 0:
                logger.error("anti-captcha create error: %s", data.get("errorDescription"))
                return None

            task_id = data["taskId"]
            logger.info("anti-captcha задача создана: %s", task_id)

            start = time.monotonic()
            time.sleep(10)

            while time.monotonic() - start < self._timeout:
                resp = httpx.post(
                    "https://api.anti-captcha.com/getTaskResult",
                    json={
                        "clientKey": self.api_key,
                        "taskId": task_id,
                    },
                    timeout=30,
                )
                data = resp.json()

                if data.get("status") == "ready":
                    token = data["solution"]["token"]
                    logger.info("anti-captcha FunCaptcha решена за %.0f сек", time.monotonic() - start)
                    return token

                if data.get("status") == "processing":
                    time.sleep(self._poll_interval)
                    continue

                logger.error("anti-captcha error: %s", data.get("errorDescription"))
                return None

            logger.error("anti-captcha timeout (%d сек)", self._timeout)
            return None

        except Exception as e:
            logger.exception("Ошибка anti-captcha: %s", e)
            return None
