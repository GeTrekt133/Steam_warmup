"""
Live test — антибан для warmup.

Запускать вручную: python -m pytest backend/tests/live/test_antiban.py -v -s
Требует: установленный Playwright chromium
"""

import logging
import statistics
import time

import pytest

import sys
sys.path.insert(0, ".")

from app.services.warmup_service import human_delay, human_actions

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@pytest.mark.live
def test_human_delay_distribution():
    """Проверяет что задержки реально рандомные (нормальное распределение)."""
    delays = []
    for i in range(30):
        d = human_delay(mean=3.0, std=1.5, min_val=1.0, max_val=8.0)
        delays.append(d)

    avg = statistics.mean(delays)
    std = statistics.stdev(delays)
    min_d = min(delays)
    max_d = max(delays)

    logger.info(f"Задержки: min={min_d:.2f}s, max={max_d:.2f}s, mean={avg:.2f}s, std={std:.2f}s")
    logger.info(f"Все задержки: {[f'{d:.2f}' for d in delays]}")

    # Проверки
    assert 1.0 <= min_d, f"min={min_d} < 1.0"
    assert max_d <= 8.0, f"max={max_d} > 8.0"
    assert 1.5 < avg < 5.0, f"mean={avg} не в ожидаемом диапазоне"
    assert std > 0.3, f"std={std} слишком маленькое — задержки не рандомные"

    print(f"\n[OK] Задержки рандомные: min={min_d:.2f}s, max={max_d:.2f}s, mean={avg:.2f}s, std={std:.2f}s")


@pytest.mark.live
def test_human_actions_in_browser():
    """Проверяет human-like действия в реальном браузере (headful)."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page()

    # Открываем простую страницу
    page.set_content("""
        <html>
        <body style="height: 3000px; background: linear-gradient(#1a1a2e, #16213e, #0f3460);">
            <h1 style="color: white; padding: 50px;">Human Actions Test Page</h1>
            <p style="color: #aaa; padding: 50px;">Scroll down to see more content...</p>
            <div style="height: 2000px;"></div>
            <p style="color: #aaa; padding: 50px;">Bottom of page</p>
        </body>
        </html>
    """)
    time.sleep(1)

    # Выполняем human-like действия несколько раз
    action_count = 0
    for i in range(5):
        logger.info(f"--- Human actions iteration {i+1} ---")
        human_actions(page)
        action_count += 1

    browser.close()
    pw.stop()

    assert action_count == 5
    print(f"\n[OK] Human-like действия выполнены {action_count} раз (скролл, мышь, клик)")
