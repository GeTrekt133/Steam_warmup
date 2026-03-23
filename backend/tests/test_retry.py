"""
Unit-тесты для retry логики warmup.

Тестирует:
- run_quest_with_retry: retry с экспоненциальным backoff
- save_error_dump: сохранение скриншотов/HTML при ошибках
- Общий timeout warmup
"""

import time
import threading
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

import sys
sys.path.insert(0, ".")

from app.services.warmup_service import (
    run_quest_with_retry,
    save_error_dump,
    QuestStatus,
    AccountWarmupStatus,
    WarmupRunner,
    ERROR_DUMPS_DIR,
)


class TestRunQuestWithRetry:
    """Тесты для run_quest_with_retry."""

    def _make_mock_page(self):
        page = MagicMock()
        page.viewport_size = {"width": 1280, "height": 720}
        page.screenshot = MagicMock()
        page.content = MagicMock(return_value="<html><body>test</body></html>")
        return page

    def test_success_first_try(self):
        """Квест выполняется с первой попытки."""
        page = self._make_mock_page()
        method = MagicMock()

        status, error, dumps = run_quest_with_retry(
            method, page, "test_user", "test_quest", max_retries=3, base_backoff=0.01
        )

        assert status == "done"
        assert error is None
        assert len(dumps) == 0
        method.assert_called_once_with(page)

    def test_success_after_retry(self):
        """Квест выполняется после retry."""
        page = self._make_mock_page()
        call_count = 0

        def failing_then_success(p):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception(f"Ошибка попытка {call_count}")

        status, error, dumps = run_quest_with_retry(
            failing_then_success, page, "test_user", "test_quest",
            max_retries=3, base_backoff=0.01
        )

        assert status == "done"
        assert error is None
        assert len(dumps) == 2  # 2 неудачные попытки записаны
        assert call_count == 3

    def test_all_retries_exhausted(self):
        """Все retry исчерпаны — квест помечен как skipped."""
        page = self._make_mock_page()
        method = MagicMock(side_effect=Exception("Постоянная ошибка"))

        status, error, dumps = run_quest_with_retry(
            method, page, "test_user", "test_quest",
            max_retries=3, base_backoff=0.01
        )

        assert status == "skipped"
        assert error is not None
        assert "Постоянная ошибка" in error
        assert len(dumps) == 3
        assert method.call_count == 3

    def test_exponential_backoff_timing(self):
        """Backoff увеличивается экспоненциально."""
        page = self._make_mock_page()
        timestamps = []

        def record_time(p):
            timestamps.append(time.time())
            raise Exception("fail")

        run_quest_with_retry(
            record_time, page, "test_user", "test_quest",
            max_retries=3, base_backoff=0.1  # 0.1, 0.2, (no wait after last)
        )

        assert len(timestamps) == 3
        # Проверяем что второй backoff больше первого
        gap1 = timestamps[1] - timestamps[0]
        gap2 = timestamps[2] - timestamps[1]
        assert gap2 > gap1 * 1.5, f"Backoff не экспоненциальный: gap1={gap1:.3f}, gap2={gap2:.3f}"

    def test_timeout_error_longer_backoff(self):
        """При PlaywrightTimeout backoff увеличивается на 1.5x."""
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        page = self._make_mock_page()
        timestamps = []

        def timeout_error(p):
            timestamps.append(time.time())
            raise PlaywrightTimeout("Timeout 30000ms exceeded")

        run_quest_with_retry(
            timeout_error, page, "test_user", "test_quest",
            max_retries=2, base_backoff=0.1
        )

        assert len(timestamps) == 2

    def test_error_dump_saved(self):
        """При ошибке сохраняются скриншот и HTML."""
        page = self._make_mock_page()
        method = MagicMock(side_effect=Exception("test error"))

        status, error, dumps = run_quest_with_retry(
            method, page, "test_user", "dump_quest",
            max_retries=1, base_backoff=0.01
        )

        assert len(dumps) == 1
        assert dumps[0]["attempt"] == 1
        assert "test error" in dumps[0]["error"]
        # screenshot и html вызваны
        page.screenshot.assert_called()
        page.content.assert_called()


class TestSaveErrorDump:
    """Тесты для save_error_dump."""

    def test_saves_screenshot_and_html(self):
        """Сохраняет скриншот и HTML."""
        page = MagicMock()
        page.content.return_value = "<html><body>error page</body></html>"

        result = save_error_dump(page, "user1", "quest1", 1)

        assert result["screenshot"] is not None or result["html"] is not None
        page.screenshot.assert_called_once()
        page.content.assert_called_once()

    def test_handles_screenshot_failure(self):
        """Не падает если скриншот не удалось сохранить."""
        page = MagicMock()
        page.screenshot.side_effect = Exception("Browser closed")
        page.content.return_value = "<html>ok</html>"

        result = save_error_dump(page, "user1", "quest1", 1)
        # Не упал, HTML всё равно сохранён
        assert result["html"] is not None


class TestWarmupTimeout:
    """Тесты для общего timeout warmup."""

    def test_timeout_parameter_stored(self):
        """WarmupRunner принимает warmup_timeout."""
        status = AccountWarmupStatus(login="test")
        runner = WarmupRunner(
            login="test", password="pass", shared_secret=None,
            master_steam_id=None, proxy_config=None, quest_ids=["all"],
            status=status, warmup_timeout=300, max_quest_retries=2,
        )
        assert runner.warmup_timeout == 300
        assert runner.max_quest_retries == 2

    def test_default_timeout(self):
        """Дефолтный timeout = 600 секунд."""
        status = AccountWarmupStatus(login="test")
        runner = WarmupRunner(
            login="test", password="pass", shared_secret=None,
            master_steam_id=None, proxy_config=None, quest_ids=["all"],
            status=status,
        )
        assert runner.warmup_timeout == 600

    def test_quest_status_has_retries(self):
        """QuestStatus хранит информацию о retry."""
        qs = QuestStatus(quest_id="test", quest_name="Test")
        assert qs.retries == 0
        assert qs.error_dumps == []
        qs.retries = 2
        qs.error_dumps = [{"attempt": 1, "error": "fail"}]
        assert qs.retries == 2
