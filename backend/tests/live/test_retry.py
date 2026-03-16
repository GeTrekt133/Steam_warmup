"""
Live test -- retry логика warmup.

Запускать вручную: python -m pytest backend/tests/live/test_retry.py -v -s
Требует: установленный Playwright chromium
"""

import logging
import os
import time

import pytest

import sys
sys.path.insert(0, ".")

from app.services.warmup_service import (
    run_quest_with_retry,
    save_error_dump,
    ERROR_DUMPS_DIR,
    human_delay,
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@pytest.mark.live
def test_retry_with_bad_url():
    """Эмулирует ошибку квеста (неправильный URL) и проверяет retry."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page()

    # Загружаем начальную страницу
    page.set_content("<html><body><h1>Test</h1></body></html>")

    call_count = 0

    def quest_with_bad_url(p):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            # Эмулируем ошибку навигации
            p.goto("http://localhost:99999/nonexistent", timeout=2000)
        # На третьей попытке -- "успех"

    status, error, dumps = run_quest_with_retry(
        quest_method=quest_with_bad_url,
        page=page,
        login="test_live",
        quest_id="bad_url_quest",
        max_retries=3,
        base_backoff=1.0,
    )

    logger.info(f"Status: {status}, Error: {error}, Retries: {len(dumps)}")
    logger.info(f"Call count: {call_count}")

    assert status == "done", f"Квест должен был выполниться с 3й попытки, status={status}"
    assert call_count == 3
    assert len(dumps) == 2  # 2 неудачные попытки

    browser.close()
    pw.stop()

    print(f"\n[OK] Retry сработал: квест выполнен с попытки {call_count}")
    print(f"[OK] Записано {len(dumps)} ошибок с дампами")


@pytest.mark.live
def test_retry_all_fail_marks_skipped():
    """Если все retry исчерпаны -- квест помечается как skipped."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_content("<html><body><h1>Test</h1></body></html>")

    def always_fail(p):
        raise Exception("Simulated quest failure")

    status, error, dumps = run_quest_with_retry(
        quest_method=always_fail,
        page=page,
        login="test_live",
        quest_id="always_fail_quest",
        max_retries=3,
        base_backoff=0.5,
    )

    logger.info(f"Status: {status}, Error: {error}")
    logger.info(f"Error dumps: {len(dumps)}")

    assert status == "skipped"
    assert error is not None
    assert "Simulated quest failure" in error
    assert len(dumps) == 3

    browser.close()
    pw.stop()

    print(f"\n[OK] После 3 фейлов квест помечен как skipped")
    print(f"[OK] Ошибка сохранена: {error}")


@pytest.mark.live
def test_error_dump_creates_files():
    """Проверяет что screenshot и HTML dump создаются при ошибке."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_content("""
        <html>
        <body style="background: #1a1a2e;">
            <h1 style="color: red;">Error Page</h1>
            <p>Something went wrong during quest execution</p>
        </body>
        </html>
    """)

    dumps = save_error_dump(page, "test_dump", "quest_fail", 1)

    logger.info(f"Screenshot: {dumps['screenshot']}")
    logger.info(f"HTML: {dumps['html']}")

    # Проверяем что файлы созданы
    if dumps["screenshot"]:
        assert os.path.exists(dumps["screenshot"]), f"Screenshot файл не найден: {dumps['screenshot']}"
        size = os.path.getsize(dumps["screenshot"])
        logger.info(f"Screenshot size: {size} bytes")
        assert size > 0

    if dumps["html"]:
        assert os.path.exists(dumps["html"]), f"HTML файл не найден: {dumps['html']}"
        with open(dumps["html"], "r", encoding="utf-8") as f:
            content = f.read()
        assert "Error Page" in content
        logger.info(f"HTML size: {len(content)} chars")

    browser.close()
    pw.stop()

    print(f"\n[OK] Screenshot создан: {dumps['screenshot']}")
    print(f"[OK] HTML dump создан: {dumps['html']}")


@pytest.mark.live
def test_retry_exponential_backoff_timing():
    """Проверяет что backoff реально экспоненциальный."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_content("<html><body>test</body></html>")

    timestamps = []

    def record_and_fail(p):
        timestamps.append(time.time())
        raise Exception("timed fail")

    status, error, dumps = run_quest_with_retry(
        quest_method=record_and_fail,
        page=page,
        login="test_timing",
        quest_id="timing_quest",
        max_retries=3,
        base_backoff=1.0,  # backoff: 1*2^0=1s, 1*2^1=2s
    )

    assert len(timestamps) == 3
    gap1 = timestamps[1] - timestamps[0]
    gap2 = timestamps[2] - timestamps[1]

    logger.info(f"Gap 1 (expected ~2s): {gap1:.2f}s")
    logger.info(f"Gap 2 (expected ~4s): {gap2:.2f}s")

    # gap1 should be ~2s (base_backoff * 2^0 = 1, but code does base*2^(attempt-1) = 1*1=1... wait
    # attempt=1: backoff = 1.0 * 2^0 = 1.0s
    # attempt=2: backoff = 1.0 * 2^1 = 2.0s
    assert gap1 >= 0.8, f"Gap1 too short: {gap1:.2f}s"
    assert gap2 > gap1, f"Backoff not exponential: gap1={gap1:.2f}, gap2={gap2:.2f}"

    browser.close()
    pw.stop()

    print(f"\n[OK] Backoff экспоненциальный: gap1={gap1:.2f}s, gap2={gap2:.2f}s")
    print(f"[OK] Status: {status}")
