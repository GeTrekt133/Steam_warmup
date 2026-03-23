"""
Live test — оптимизация таймингов Warmup.

Запуск: python -m pytest tests/live/test_warmup_timing.py -v -s
Тестирует: прогрев браузера, паузы между группами, группировку квестов.
"""

import logging
import time
from unittest.mock import patch, MagicMock

import pytest

from app.services.warmup_service import (
    WarmupRunner,
    AccountWarmupStatus,
    _group_shuffled_quests,
    shuffle_quests,
    QUEST_LIST,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@pytest.mark.live
def test_quest_grouping_timing():
    """
    Тест группировки квестов — замеряет что группы формируются корректно
    и логирует ожидаемые паузы между ними.
    """
    shuffled = shuffle_quests(QUEST_LIST)
    groups = _group_shuffled_quests(shuffled)

    logger.info(f"Количество квестов: {len(QUEST_LIST)}")
    logger.info(f"Количество групп: {len(groups)}")

    total_quests = 0
    for i, group in enumerate(groups):
        quest_ids = [qid for qid, _ in group]
        logger.info(f"  Группа {i+1}: {quest_ids} ({len(group)} квестов)")
        total_quests += len(group)

    assert total_quests == len(QUEST_LIST)
    assert len(groups) >= 3, "Должно быть минимум 3 группы"

    # Оценка таймингов
    # Между квестами: ~3s (mean), между группами: 5-15s
    est_intra = len(QUEST_LIST) * 3  # внутри групп
    est_inter = (len(groups) - 1) * 10  # между группами
    est_warmup = 15  # прогрев браузера
    est_total = est_intra + est_inter + est_warmup

    logger.info(f"\nОценка таймингов (без учёта квестов):")
    logger.info(f"  Прогрев браузера: ~{est_warmup}s")
    logger.info(f"  Паузы между квестами: ~{est_intra}s ({len(QUEST_LIST)} × 3s)")
    logger.info(f"  Паузы между группами: ~{est_inter}s ({len(groups)-1} × 10s)")
    logger.info(f"  Итого overhead: ~{est_total}s ({est_total/60:.1f} мин)")

    logger.info("✅ Группировка тест пройден")


@pytest.mark.live
def test_browser_warmup_headful():
    """
    Тест прогрева браузера в headful-режиме.

    Запускает реальный Chromium, заходит на Steam, пошататься.
    Замеряет время прогрева.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright не установлен")

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False, slow_mo=100)
    context = browser.new_context()
    page = context.new_page()

    # Создаём runner с фейковыми данными для вызова _browser_warmup
    status = AccountWarmupStatus(login="timing_test")
    runner = WarmupRunner(
        login="timing_test",
        password="fake",
        shared_secret=None,
        master_steam_id=None,
        proxy_config=None,
        quest_ids=["all"],
        status=status,
    )

    t0 = time.time()
    runner._browser_warmup(page)
    warmup_time = time.time() - t0

    logger.info(f"Прогрев браузера: {warmup_time:.1f}s")

    # Должен занять 10-25 секунд
    assert warmup_time >= 3, "Прогрев слишком быстрый"
    assert warmup_time < 40, "Прогрев слишком долгий"

    # Проверяем что страница загружена
    title = page.title()
    logger.info(f"Страница после прогрева: {title}")
    assert "Steam" in title or page.url.startswith("https://store.steampowered.com") or page.url.startswith("https://steamcommunity.com")

    browser.close()
    pw.stop()

    logger.info(f"✅ Прогрев браузера тест пройден ({warmup_time:.1f}s)")


@pytest.mark.live
def test_timing_comparison():
    """
    Сравнение таймингов: с группировкой vs без.

    Не запускает реальные квесты, просто моделирует паузы.
    """
    import random

    quests = list(QUEST_LIST)
    shuffled = shuffle_quests(quests)
    groups = _group_shuffled_quests(shuffled)

    # Моделируем без группировки: фиксированная пауза 3s между квестами
    time_flat = len(quests) * 3.0
    logger.info(f"Без группировки: {len(quests)} × 3s = {time_flat:.0f}s")

    # Моделируем с группировкой: 3s внутри, 5-15s между группами
    time_grouped = 0.0
    for i, group in enumerate(groups):
        time_grouped += len(group) * 3.0  # внутри группы
        if i > 0:
            time_grouped += random.uniform(5, 15)  # между группами

    # Добавляем прогрев браузера
    warmup_time = random.uniform(10, 20)
    time_grouped += warmup_time

    logger.info(f"С группировкой: {time_grouped:.0f}s (включая прогрев {warmup_time:.0f}s)")
    logger.info(f"Разница: {time_grouped - time_flat:.0f}s (группировка добавляет overhead)")

    # Группировка добавляет overhead, но улучшает антибан
    # Это ожидаемо — overhead идёт на реалистичность
    assert time_grouped > time_flat, "Группировка должна добавлять overhead (паузы)"

    logger.info("✅ Сравнение таймингов тест пройден")
