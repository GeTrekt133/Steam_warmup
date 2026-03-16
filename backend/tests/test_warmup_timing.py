"""
Unit-тесты для оптимизации таймингов Warmup.

Тестирует: группировку квестов, прогрев браузера, паузы между группами.
"""

import pytest

from app.services.warmup_service import (
    _group_shuffled_quests,
    shuffle_quests,
    QUEST_LIST,
    QUEST_DEPENDENCY_GROUPS,
)


def test_group_shuffled_quests_basic():
    """Группировка зависимых квестов сохраняется."""
    # Простой случай: профиль → магазин → независимый
    quests = [
        ("setup_avatar", "Аватар"),
        ("setup_profile_name", "Имя"),
        ("setup_profile_summary", "Описание"),
        ("rate_game", "Оценка"),
        ("write_review", "Отзыв"),
        ("join_group", "Группа"),
    ]
    groups = _group_shuffled_quests(quests)

    # Первая группа: профиль (3 квеста)
    assert len(groups[0]) == 3
    assert groups[0][0][0] == "setup_avatar"
    assert groups[0][1][0] == "setup_profile_name"
    assert groups[0][2][0] == "setup_profile_summary"

    # Вторая группа: магазин (2 квеста)
    assert len(groups[1]) == 2
    assert groups[1][0][0] == "rate_game"

    # Третья группа: независимый (1 квест)
    assert len(groups[2]) == 1
    assert groups[2][0][0] == "join_group"


def test_group_shuffled_quests_all():
    """Все квесты из QUEST_LIST группируются корректно."""
    groups = _group_shuffled_quests(QUEST_LIST)

    # Должно быть несколько групп
    assert len(groups) >= 3

    # Все квесты сохранены
    total = sum(len(g) for g in groups)
    assert total == len(QUEST_LIST)


def test_group_shuffled_quests_after_shuffle():
    """Группировка работает после shuffle_quests."""
    shuffled = shuffle_quests(QUEST_LIST)
    groups = _group_shuffled_quests(shuffled)

    # Все квесты сохранены
    total = sum(len(g) for g in groups)
    assert total == len(QUEST_LIST)

    # Внутри каждой группы зависимости сохранены
    for group in groups:
        if len(group) > 1:
            ids = [qid for qid, _ in group]
            # Проверяем что все квесты из одной группы зависимостей
            found_dep_group = None
            for dep_group in QUEST_DEPENDENCY_GROUPS:
                if ids[0] in dep_group:
                    found_dep_group = dep_group
                    break
            if found_dep_group:
                for qid in ids:
                    assert qid in found_dep_group, f"{qid} не в группе зависимостей {found_dep_group}"


def test_group_shuffled_quests_preserves_order():
    """Порядок внутри группы зависимостей сохранён."""
    quests = [
        ("add_friend", "Друг"),
        ("post_comment", "Комментарий"),
    ]
    groups = _group_shuffled_quests(quests)
    assert len(groups) == 1
    assert groups[0][0][0] == "add_friend"
    assert groups[0][1][0] == "post_comment"


def test_group_shuffled_quests_single_quests():
    """Одиночные квесты — каждый отдельная группа."""
    quests = [
        ("join_group", "Группа"),
        ("discovery_queue", "Queue"),
        ("subscribe_workshop", "Workshop"),
    ]
    groups = _group_shuffled_quests(quests)
    assert len(groups) == 3
    for g in groups:
        assert len(g) == 1


def test_group_shuffled_quests_empty():
    """Пустой список."""
    groups = _group_shuffled_quests([])
    assert groups == []


def test_multiple_shuffles_produce_groups():
    """Несколько shuffle → группировка всегда корректна."""
    for _ in range(10):
        shuffled = shuffle_quests(QUEST_LIST)
        groups = _group_shuffled_quests(shuffled)
        total = sum(len(g) for g in groups)
        assert total == len(QUEST_LIST)
        assert len(groups) >= 2  # минимум 2 группы
