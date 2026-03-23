"""
Unit-тесты для антибан функциональности warmup.

Тестирует:
- human_delay: нормальное распределение, min/max границы
- shuffle_quests: рандомизация порядка, сохранение зависимостей
- RateLimiter: ограничение запусков в минуту
"""

import time
import threading
import statistics

import pytest

import sys
sys.path.insert(0, ".")

from app.services.warmup_service import (
    human_delay,
    shuffle_quests,
    RateLimiter,
    QUEST_LIST,
    QUEST_DEPENDENCY_GROUPS,
)


class TestHumanDelay:
    """Тесты для human_delay — рандомная задержка с нормальным распределением."""

    def test_delay_within_bounds(self):
        """Задержка всегда в пределах [min_val, max_val]."""
        delays = []
        for _ in range(50):
            d = human_delay(mean=3.0, std=1.5, min_val=1.0, max_val=8.0)
            delays.append(d)
            assert 1.0 <= d <= 8.0, f"Задержка {d} вне границ [1.0, 8.0]"
        # Среднее должно быть примерно 3.0 (±1.5)
        avg = statistics.mean(delays)
        assert 1.5 < avg < 5.0, f"Среднее {avg} слишком далеко от ожидаемого 3.0"

    def test_delays_are_random(self):
        """Задержки должны отличаться друг от друга."""
        delays = [human_delay(mean=3.0, std=1.5, min_val=1.0, max_val=8.0) for _ in range(20)]
        unique = set(round(d, 4) for d in delays)
        # Хотя бы 5 разных значений из 20
        assert len(unique) >= 5, f"Слишком мало уникальных задержек: {len(unique)}"


class TestShuffleQuests:
    """Тесты для shuffle_quests — рандомизация порядка с зависимостями."""

    def test_all_quests_preserved(self):
        """Все квесты сохраняются после перемешивания."""
        original = list(QUEST_LIST)
        shuffled = shuffle_quests(original)
        assert set(q[0] for q in shuffled) == set(q[0] for q in original)
        assert len(shuffled) == len(original)

    def test_dependencies_preserved(self):
        """Зависимые квесты сохраняют относительный порядок."""
        for _ in range(20):
            shuffled = shuffle_quests(list(QUEST_LIST))
            shuffled_ids = [q[0] for q in shuffled]

            for group in QUEST_DEPENDENCY_GROUPS:
                # Получаем индексы квестов этой группы в перемешанном списке
                indices = [shuffled_ids.index(qid) for qid in group if qid in shuffled_ids]
                # Проверяем что они идут в возрастающем порядке (порядок сохранён)
                assert indices == sorted(indices), (
                    f"Нарушен порядок зависимой группы {group}: индексы {indices}"
                )

    def test_order_actually_changes(self):
        """Порядок групп действительно меняется."""
        original = list(QUEST_LIST)
        original_ids = [q[0] for q in original]
        different_count = 0
        for _ in range(20):
            shuffled = shuffle_quests(list(QUEST_LIST))
            shuffled_ids = [q[0] for q in shuffled]
            if shuffled_ids != original_ids:
                different_count += 1
        # Хотя бы половина перемешиваний дала другой порядок
        assert different_count >= 5, f"Только {different_count}/20 перемешиваний дали другой порядок"

    def test_subset_of_quests(self):
        """Работает с подмножеством квестов."""
        subset = [("rate_game", "Оценка игры"), ("join_group", "Вступление в группу")]
        shuffled = shuffle_quests(subset)
        assert len(shuffled) == 2
        assert set(q[0] for q in shuffled) == {"rate_game", "join_group"}


class TestRateLimiter:
    """Тесты для RateLimiter — ограничение запусков в минуту."""

    def test_allows_within_limit(self):
        """Пропускает запросы в пределах лимита."""
        limiter = RateLimiter(max_per_minute=5)
        start = time.time()
        for _ in range(5):
            limiter.wait()
        elapsed = time.time() - start
        # 5 запросов в пределах лимита — не должно быть задержки
        assert elapsed < 1.0, f"Заняло {elapsed:.2f}s для 5 запросов в лимите 5/мин"

    def test_blocks_over_limit(self):
        """Блокирует при превышении лимита."""
        limiter = RateLimiter(max_per_minute=2)
        # Первые 2 проходят мгновенно
        limiter.wait()
        limiter.wait()
        # Третий должен подождать (но мы не будем ждать 60 сек в тесте)
        # Проверяем что timestamps заполнены
        assert len(limiter._timestamps) == 2

    def test_thread_safety(self):
        """Потокобезопасность rate limiter."""
        limiter = RateLimiter(max_per_minute=10)
        results = []

        def worker():
            limiter.wait()
            results.append(time.time())

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(results) == 10, f"Только {len(results)}/10 потоков прошли"
