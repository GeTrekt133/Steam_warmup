"""
Сервис прогрева Steam-аккаунтов (Community Badge).

Выполняет квесты Community Badge через Playwright:
- Настройка профиля (аватар, имя, описание)
- Оценка игры, добавление в вишлист
- Добавление друга, комментарий на профиле
- Discovery Queue, подписка Workshop, вступление в группу
- и др.

Каждый квест — отдельный метод, выполняется последовательно.
Прогресс трекится для отображения на фронтенде.

Антибан:
- Задержки между квестами: нормальное распределение (mean=3, std=1.5)
- Human-like действия: скролл, движение мыши, клик в пустую область
- Рандомизация порядка независимых квестов
- Rate limiting: ограничение запусков в минуту с одного IP
- Retry при ошибках с экспоненциальным backoff
"""

import logging
import math
import random
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from playwright.sync_api import sync_playwright, Page, Browser, TimeoutError as PlaywrightTimeout

from app.services.steam_guard import generate_steam_guard_code

logger = logging.getLogger(__name__)

# Директория для сохранения скриншотов/HTML при ошибках
ERROR_DUMPS_DIR = Path(__file__).parent.parent.parent / "error_dumps"
ERROR_DUMPS_DIR.mkdir(exist_ok=True)


# ─── Антибан: рандомные задержки и human-like действия ─────────

def human_delay(mean: float = 3.0, std: float = 1.5, min_val: float = 1.0, max_val: float = 8.0) -> float:
    """Задержка с нормальным распределением (имитация человека)."""
    delay = random.gauss(mean, std)
    delay = max(min_val, min(max_val, delay))
    logger.debug(f"[Antiban] human_delay: {delay:.2f}s")
    time.sleep(delay)
    return delay


def human_actions(page: Page):
    """Случайные human-like действия на текущей странице."""
    actions = random.sample([
        "scroll",
        "mouse_move",
        "click_empty",
    ], k=random.randint(1, 3))

    for action in actions:
        try:
            if action == "scroll":
                # Скролл вниз на случайное расстояние
                scroll_y = random.randint(100, 500)
                page.mouse.wheel(0, scroll_y)
                time.sleep(random.uniform(0.3, 1.0))
                # Иногда скроллим обратно
                if random.random() < 0.3:
                    page.mouse.wheel(0, -random.randint(50, 200))
                    time.sleep(random.uniform(0.2, 0.5))

            elif action == "mouse_move":
                # Движение мыши в случайную точку
                vp = page.viewport_size or {"width": 1280, "height": 720}
                x = random.randint(100, vp["width"] - 100)
                y = random.randint(100, vp["height"] - 100)
                page.mouse.move(x, y)
                time.sleep(random.uniform(0.2, 0.8))

            elif action == "click_empty":
                # Клик в пустую область (body, не по ссылке)
                vp = page.viewport_size or {"width": 1280, "height": 720}
                x = random.randint(50, vp["width"] - 50)
                y = random.randint(50, min(150, vp["height"] - 50))
                page.mouse.click(x, y)
                time.sleep(random.uniform(0.2, 0.6))

            logger.debug(f"[Antiban] human_action: {action}")
        except Exception as e:
            logger.debug(f"[Antiban] human_action {action} failed: {e}")


# ─── Rate limiter: ограничение запусков в минуту ──────────────

class RateLimiter:
    """Лимитирует количество запусков warmup аккаунтов в минуту с одного IP."""

    def __init__(self, max_per_minute: int = 3):
        self.max_per_minute = max(1, max_per_minute)
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def wait(self):
        """Блокирует поток пока не освободится слот."""
        while True:
            with self._lock:
                now = time.time()
                # Убираем записи старше 60 сек
                self._timestamps = [t for t in self._timestamps if now - t < 60.0]
                if len(self._timestamps) < self.max_per_minute:
                    self._timestamps.append(now)
                    return
                # Ждём до освобождения самого раннего слота
                wait_time = 60.0 - (now - self._timestamps[0]) + 0.1
            logger.info(f"[RateLimiter] ожидание {wait_time:.1f}s (лимит {self.max_per_minute}/мин)")
            time.sleep(min(wait_time, 10.0))


# Глобальный rate limiter (настраивается при запуске warmup)
_global_rate_limiter: RateLimiter | None = None


def get_rate_limiter(max_per_minute: int = 3) -> RateLimiter:
    """Получить или создать глобальный rate limiter."""
    global _global_rate_limiter
    if _global_rate_limiter is None or _global_rate_limiter.max_per_minute != max_per_minute:
        _global_rate_limiter = RateLimiter(max_per_minute)
    return _global_rate_limiter


# ─── Retry и обработка ошибок ─────────────────────────────────

def save_error_dump(page: Page, login: str, quest_id: str, attempt: int) -> dict[str, str | None]:
    """Сохраняет скриншот и HTML-дамп страницы при ошибке квеста."""
    dumps: dict[str, str | None] = {"screenshot": None, "html": None}
    timestamp = int(time.time())
    prefix = f"{login}_{quest_id}_attempt{attempt}_{timestamp}"

    try:
        screenshot_path = ERROR_DUMPS_DIR / f"{prefix}.png"
        page.screenshot(path=str(screenshot_path), full_page=False, timeout=5000)
        dumps["screenshot"] = str(screenshot_path)
        logger.info(f"[ErrorDump] скриншот: {screenshot_path}")
    except Exception as e:
        logger.debug(f"[ErrorDump] не удалось сохранить скриншот: {e}")

    try:
        html_path = ERROR_DUMPS_DIR / f"{prefix}.html"
        html_content = page.content()
        html_path.write_text(html_content[:500_000], encoding="utf-8")
        dumps["html"] = str(html_path)
        logger.info(f"[ErrorDump] HTML: {html_path}")
    except Exception as e:
        logger.debug(f"[ErrorDump] не удалось сохранить HTML: {e}")

    return dumps


def run_quest_with_retry(
    quest_method: Callable,
    page: Page,
    login: str,
    quest_id: str,
    max_retries: int = 3,
    base_backoff: float = 2.0,
) -> tuple[str, str | None, list[dict]]:
    """
    Выполняет квест с retry и экспоненциальным backoff.

    Returns:
        (status, error_message, error_dumps)
        status: "done" | "skipped"
    """
    error_dumps: list[dict] = []
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            quest_method(page)
            if attempt > 1:
                logger.info(f"[Retry] {login}: '{quest_id}' выполнен с попытки {attempt}")
            return "done", None, error_dumps
        except PlaywrightTimeout as e:
            last_error = str(e)[:200]
            logger.warning(
                f"[Retry] {login}: '{quest_id}' таймаут (попытка {attempt}/{max_retries}): {last_error}"
            )
            # Сохраняем дамп ошибки
            dump = save_error_dump(page, login, quest_id, attempt)
            error_dumps.append({"attempt": attempt, "error": last_error, **dump})

            if attempt < max_retries:
                backoff = base_backoff * (2 ** (attempt - 1))  # 2, 4, 8
                # При таймауте увеличиваем backoff
                backoff *= 1.5
                logger.info(f"[Retry] {login}: ожидание {backoff:.1f}s перед повтором (таймаут)")
                time.sleep(backoff)
        except Exception as e:
            last_error = str(e)[:200]
            logger.warning(
                f"[Retry] {login}: '{quest_id}' ошибка (попытка {attempt}/{max_retries}): {last_error}"
            )
            dump = save_error_dump(page, login, quest_id, attempt)
            error_dumps.append({"attempt": attempt, "error": last_error, **dump})

            if attempt < max_retries:
                backoff = base_backoff * (2 ** (attempt - 1))  # 2, 4, 8
                logger.info(f"[Retry] {login}: ожидание {backoff:.1f}s перед повтором")
                time.sleep(backoff)

    # Все попытки исчерпаны — пометить как skipped
    logger.warning(f"[Retry] {login}: '{quest_id}' пропущен после {max_retries} попыток")
    return "skipped", last_error, error_dumps


# ─── Группы квестов (независимые можно перемешивать) ──────────

# Квесты, которые зависят друг от друга, объединены в группу
# Внутри группы порядок сохраняется, между группами — рандом
QUEST_DEPENDENCY_GROUPS = [
    # Группа 1: Настройка профиля
    ["setup_avatar", "setup_profile_name"],
    # Группа 2: Отзыв + оценка
    ["write_review"],
    # Группа 3: Независимые квесты
    ["add_to_wishlist"],
    ["discovery_queue"],
    ["join_group"],
    ["subscribe_workshop"],
    ["visit_discussions"],
    ["add_friend"],
    ["post_status"],
    ["view_broadcast"],
    ["send_emoticon"],
    ["setup_profile_background"],
]

# Квесты которые всегда выполняются последними (после получения бейджа/уровня)
QUESTS_ALWAYS_LAST = {"feature_badge", "post_comment"}


def shuffle_quests(quest_ids: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Рандомизирует порядок групп квестов, сохраняя зависимости внутри групп."""
    quest_map = {qid: qname for qid, qname in quest_ids}
    selected_ids = {qid for qid, _ in quest_ids}

    # Собираем группы из выбранных квестов
    groups: list[list[tuple[str, str]]] = []
    used = set()
    for dep_group in QUEST_DEPENDENCY_GROUPS:
        group_quests = [(qid, quest_map[qid]) for qid in dep_group if qid in selected_ids]
        if group_quests:
            groups.append(group_quests)
            used.update(qid for qid, _ in group_quests)

    # Квесты не из групп — каждый как отдельная группа
    for qid, qname in quest_ids:
        if qid not in used:
            groups.append([(qid, qname)])

    # Разделяем: обычные группы и "всегда последние"
    normal_groups = []
    last_groups = []
    for group in groups:
        if any(qid in QUESTS_ALWAYS_LAST for qid, _ in group):
            last_groups.append(group)
        else:
            normal_groups.append(group)

    # Перемешиваем только обычные, "последние" идут в конце
    random.shuffle(normal_groups)
    random.shuffle(last_groups)

    # Собираем обратно в плоский список
    result = []
    for group in normal_groups:
        result.extend(group)
    for group in last_groups:
        result.extend(group)
    return result

def _group_shuffled_quests(shuffled: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """
    Группирует уже перемешанные квесты обратно по зависимостям.

    Зависимые квесты идут в одной группе, независимые — каждый отдельная группа.
    Это нужно для вставки длинных пауз между группами.
    """
    # Маппинг quest_id → номер группы зависимостей
    dep_map: dict[str, int] = {}
    for i, dep_group in enumerate(QUEST_DEPENDENCY_GROUPS):
        for qid in dep_group:
            dep_map[qid] = i

    groups: list[list[tuple[str, str]]] = []
    current_group: list[tuple[str, str]] = []
    current_dep_id: int | None = None

    for qid, qname in shuffled:
        qid_dep = dep_map.get(qid)

        if not current_group:
            current_group.append((qid, qname))
            current_dep_id = qid_dep
        elif qid_dep is not None and qid_dep == current_dep_id:
            # Тот же блок зависимостей — добавляем в текущую группу
            current_group.append((qid, qname))
        else:
            # Новая группа
            groups.append(current_group)
            current_group = [(qid, qname)]
            current_dep_id = qid_dep

    if current_group:
        groups.append(current_group)

    return groups


# ─── Рандомные данные для профиля ─────────────────────────────

_BIOS = [
    "Just gaming", "CS2 enjoyer", "Steam user since 2024", "GG WP",
    "I love gaming", "PC gamer", "Competitive player", "Casual gamer",
    "Trading is fun", "Play hard, win easy", "No pain no gain",
    "Gaming is life", "FPS lover", "RPG enthusiast", "Strategy master",
    "Born to game, forced to work", "Press F to pay respects",
    "AFK in real life", "One more game and I'll sleep",
    "Collecting games faster than playing them",
    "My other car is a gaming PC", "Living the gamer dream",
    "Always ready for a match", "Global Elite wannabe",
    "Dota 2 is not just a game, it's a lifestyle",
]

_NAMES = [
    "Alex", "Max", "Sam", "Jake", "Ryan", "Kyle", "Nick", "Mike",
    "Dan", "Tom", "Leo", "Kai", "Ian", "Ben", "Jay", "Ash",
    "Phoenix", "Shadow", "Storm", "Ghost", "Wolf", "Bear", "Hawk",
    "Viper", "Blade", "Frost", "Blaze", "Raven", "Nova", "Ace",
]

_FIRST_NAMES = [
    "James", "John", "Robert", "Michael", "David", "William", "Richard",
    "Thomas", "Daniel", "Matthew", "Andrew", "Joshua", "Kevin", "Brian",
    "Eric", "Steven", "Mark", "Paul", "Alex", "Chris", "Ryan", "Jason",
    "Anna", "Maria", "Emma", "Sophie", "Laura", "Sarah", "Kate", "Julia",
]

_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis",
    "Wilson", "Anderson", "Taylor", "Thomas", "Moore", "Martin", "Jackson",
    "White", "Harris", "Clark", "Lewis", "Walker", "Hall", "Young", "King",
]

_COMMENTS = [
    "Nice profile!", "Cool account!", "GG", "+rep", "Nice games!",
    "Good player", "Keep it up!", "Great collection", "Hello!",
    "Welcome to Steam!", "Have fun!", "Nice inventory!",
]

_REVIEWS = [
    "Great game, really enjoy playing it! Recommend to everyone.",
    "Fun gameplay, nice graphics. Worth trying out.",
    "Solid game with a good community. Hours of fun.",
    "One of the best free games on Steam. Love it!",
    "Amazing experience, been playing for hours. 10/10",
    "Really addictive gameplay. Can't stop playing.",
    "Good game for casual and competitive players alike.",
    "Nice game to play with friends. Very enjoyable.",
    "Interesting mechanics, smooth gameplay. Thumbs up!",
    "Cool game, lots of content and regular updates.",
]

# Пул платных игр для вишлиста — доступны в РФ (app_id, название)
_WISHLIST_GAMES = [
    (2358720, "Black Myth: Wukong"),
    (892970, "Valheim"),
    (1145360, "Hades"),
    (1145350, "Hades II"),
    (367520, "Hollow Knight"),
    (548430, "Deep Rock Galactic"),
    (413150, "Stardew Valley"),
    (252490, "Rust"),
    (431960, "Wallpaper Engine"),
    (1203220, "NARAKA: BLADEPOINT"),
    (105600, "Terraria"),
    (1794680, "Vampire Survivors"),
    (291550, "Brawlhalla"),
    (620, "Portal 2"),
    (4000, "Garry's Mod"),
    (322330, "Don't Starve Together"),
    (394360, "Hearts of Iron IV"),
    (281990, "Stellaris"),
    (1677740, "Stumble Guys"),
    (1966720, "Lethal Company"),
]

# Пул публичных групп Steam для вступления
_STEAM_GROUPS = [
    "https://steamcommunity.com/groups/SteamClientBeta",
    "https://steamcommunity.com/groups/steamuniverse",
    "https://steamcommunity.com/groups/tf2",
    "https://steamcommunity.com/groups/dota2",
]

# Workshop item для подписки (популярный CS2 карта)
# Пул Workshop items для подписки
_WORKSHOP_ITEMS = [
    "https://steamcommunity.com/sharedfiles/filedetails/?id=3656733284",
    "https://steamcommunity.com/sharedfiles/filedetails/?id=3640041146",
    "https://steamcommunity.com/sharedfiles/filedetails/?id=3615956855",
    "https://steamcommunity.com/sharedfiles/filedetails/?id=3644811896",
    "https://steamcommunity.com/sharedfiles/filedetails/?id=3657262053",
    "https://steamcommunity.com/sharedfiles/filedetails/?id=3655833101",
    "https://steamcommunity.com/sharedfiles/filedetails/?id=3670007086",
]

# ─── Описание квестов ────────────────────────────────────────

QUEST_LIST = [
    ("setup_avatar", "Настройка аватара"),
    ("setup_profile_name", "Профиль (имя + bio + URL)"),
    ("write_review", "Отзыв + оценка игры"),
    ("add_to_wishlist", "Добавление в вишлист"),
    ("discovery_queue", "Discovery Queue"),
    ("join_group", "Вступление в группу"),
    ("subscribe_workshop", "Подписка + оценка Workshop"),
    ("visit_discussions", "Поиск в дискуссиях"),
    ("add_friend", "Добавление друга"),
    ("post_status", "Статус + лайк в ленте"),
    ("view_broadcast", "Просмотр трансляции"),
    ("send_emoticon", "Эмодзи в чат друга"),
    ("setup_profile_background", "Настройка фона"),
    ("feature_badge", "Featured Badge на профиле"),
    ("post_comment", "Комментарий на профиле"),
]


@dataclass
class QuestStatus:
    quest_id: str
    quest_name: str
    status: str = "pending"  # pending | running | done | error | skipped
    error: str | None = None
    retries: int = 0
    error_dumps: list[dict] = field(default_factory=list)


@dataclass
class AccountWarmupStatus:
    login: str
    status: str = "pending"  # pending | running | done | error
    quests: list[QuestStatus] = field(default_factory=list)
    current_quest: str | None = None
    error: str | None = None

    @property
    def quests_done(self) -> int:
        return sum(1 for q in self.quests if q.status in ("done", "skipped"))

    @property
    def quests_total(self) -> int:
        return len(self.quests)

    def to_dict(self) -> dict:
        return {
            "login": self.login,
            "status": self.status,
            "quests_done": self.quests_done,
            "quests_total": self.quests_total,
            "current_quest": self.current_quest,
            "error": self.error,
            "quests": [
                {
                    "id": q.quest_id, "name": q.quest_name, "status": q.status,
                    "error": q.error, "retries": q.retries,
                }
                for q in self.quests
            ],
        }


# ─── Warmup Runner (sync, запускается в отдельном потоке) ─────


class WarmupRunner:
    """Выполняет квесты Community Badge для одного аккаунта через Playwright."""

    def __init__(
        self,
        login: str,
        password: str,
        shared_secret: str | None,
        master_steam_id: str | None,
        proxy_config: dict | None,
        quest_ids: list[str] | None,
        status: AccountWarmupStatus,
        generated_texts: dict | None = None,
        rate_limiter: RateLimiter | None = None,
        warmup_timeout: int = 600,
        max_quest_retries: int = 3,
        friend_requests_count: int = 3,
    ):
        self.login = login
        self.password = password
        self.shared_secret = shared_secret
        self.master_steam_id = master_steam_id
        self.proxy_config = proxy_config
        self.status = status
        self.rate_limiter = rate_limiter
        self.warmup_timeout = warmup_timeout  # общий timeout в секундах (default: 10 мин)
        self.max_quest_retries = max_quest_retries
        self.friend_requests_count = max(1, min(30, friend_requests_count))
        # LLM-сгенерированные тексты (или fallback)
        self.texts = generated_texts or {}

        # Фильтруем квесты
        if quest_ids and "all" not in quest_ids:
            selected = {q for q in quest_ids}
            self.quests = [(qid, qname) for qid, qname in QUEST_LIST if qid in selected]
        else:
            self.quests = list(QUEST_LIST)

        # Инициализируем статусы квестов
        self.status.quests = [QuestStatus(quest_id=qid, quest_name=qname) for qid, qname in self.quests]

    def run(self) -> AccountWarmupStatus:
        """Запускает все квесты последовательно. Вызывать из отдельного потока."""
        self.status.status = "running"
        logger.info(f"[Warmup] {self.login}: старт ({len(self.quests)} квестов)")

        # Rate limiting — ждём свой слот
        if self.rate_limiter:
            logger.info(f"[Warmup] {self.login}: ожидание rate limiter...")
            self.rate_limiter.wait()
            logger.info(f"[Warmup] {self.login}: rate limiter пройден")

        pw = None
        browser = None

        try:
            pw = sync_playwright().start()
            browser_args = {"headless": False}
            if self.proxy_config:
                browser_args["proxy"] = self.proxy_config

            browser = pw.chromium.launch(**browser_args)
            context = browser.new_context()
            page = context.new_page()

            # ─── Прогрев браузера: пошататься по Steam ───────────
            self._browser_warmup(page)

            # Логин
            self._steam_login(page)

            # Библиотеку загрузим лениво при необходимости (в _quest_write_review)
            self.owned_apps = set()

            # Рандомизируем порядок квестов (с учётом зависимостей)
            shuffled = shuffle_quests(self.quests)
            # Обновляем статусы в новом порядке
            self.quests = shuffled
            self.status.quests = [
                QuestStatus(quest_id=qid, quest_name=qname) for qid, qname in shuffled
            ]
            logger.info(f"[Warmup] {self.login}: порядок квестов: {[q[0] for q in shuffled]}")

            # Группируем квесты обратно по зависимостям для пауз между группами
            quest_groups = _group_shuffled_quests(shuffled)
            logger.info(f"[Warmup] {self.login}: {len(quest_groups)} групп квестов")

            # Общий timeout на весь warmup
            warmup_start_time = time.time()
            quest_index = 0

            # Выполняем квесты группами
            for group_idx, group in enumerate(quest_groups):
                # Пауза между группами квестов (имитация чтения / размышления)
                if group_idx > 0:
                    group_pause = random.uniform(5.0, 15.0)
                    logger.info(f"[Warmup] {self.login}: пауза между группами {group_pause:.1f}s")
                    time.sleep(group_pause)
                    # Human-like действия между группами
                    if random.random() < 0.7:
                        human_actions(page)

                for quest_id, quest_name in group:
                    # Проверяем общий timeout
                    elapsed = time.time() - warmup_start_time
                    if elapsed > self.warmup_timeout:
                        logger.warning(
                            f"[Warmup] {self.login}: общий timeout {self.warmup_timeout}s "
                            f"превышен ({elapsed:.0f}s), пропускаем оставшиеся квесты"
                        )
                        for j in range(quest_index, len(self.quests)):
                            self.status.quests[j].status = "skipped"
                            self.status.quests[j].error = "Общий timeout превышен"
                        quest_index = len(self.quests)
                        break

                    qs = self.status.quests[quest_index]
                    qs.status = "running"
                    self.status.current_quest = quest_name

                    method = getattr(self, f"_quest_{quest_id}", None)
                    if not method:
                        qs.status = "skipped"
                        qs.error = "Не реализован"
                        quest_index += 1
                        continue

                    logger.info(f"[Warmup] {self.login}: квест '{quest_name}'")

                    # Retry с экспоненциальным backoff
                    status, error, error_dumps = run_quest_with_retry(
                        quest_method=method,
                        page=page,
                        login=self.login,
                        quest_id=quest_id,
                        max_retries=self.max_quest_retries,
                    )
                    qs.status = status
                    qs.error = error
                    qs.error_dumps = error_dumps
                    qs.retries = len(error_dumps)

                    # Человеческая пауза между квестами (нормальное распределение)
                    delay = human_delay(mean=3.0, std=1.5, min_val=1.0, max_val=8.0)
                    logger.info(f"[Warmup] {self.login}: пауза {delay:.1f}s после '{quest_name}'")

                    # Случайные human-like действия между квестами
                    if random.random() < 0.6:
                        human_actions(page)

                    quest_index += 1

            self.status.status = "done"
            self.status.current_quest = None

        except Exception as e:
            logger.error(f"[Warmup] {self.login}: критическая ошибка: {e}")
            self.status.status = "error"
            self.status.error = str(e)[:300]

        finally:
            # Всегда закрываем браузер, даже при ошибке логина
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
            try:
                if pw:
                    pw.stop()
            except Exception:
                pass

        logger.info(f"[Warmup] {self.login}: завершён ({self.status.quests_done}/{self.status.quests_total})")
        return self.status

    def _browser_warmup(self, page: Page):
        """Прогрев браузера: зайти на Steam, пошататься 10–20 сек."""
        warmup_start = time.time()
        logger.info(f"[Warmup] {self.login}: прогрев браузера...")
        try:
            page.goto("https://store.steampowered.com/", wait_until="domcontentloaded", timeout=20000)
            time.sleep(random.uniform(2, 5))

            # Скроллим главную страницу
            for _ in range(random.randint(2, 4)):
                page.mouse.wheel(0, random.randint(200, 600))
                time.sleep(random.uniform(1, 3))

            # Иногда заходим на случайную страницу
            if random.random() < 0.5:
                pages = [
                    "https://steamcommunity.com/",
                    "https://store.steampowered.com/explore/",
                    "https://store.steampowered.com/news/",
                ]
                page.goto(random.choice(pages), wait_until="domcontentloaded", timeout=15000)
                time.sleep(random.uniform(2, 5))

            elapsed = time.time() - warmup_start
            logger.info(f"[Warmup] {self.login}: прогрев браузера {elapsed:.1f}s")
        except Exception as e:
            logger.debug(f"[Warmup] {self.login}: ошибка прогрева браузера: {e}")

    # ─── Логин ───────────────────────────────────────────────

    def _steam_login(self, page: Page):
        """Логин в Steam через Playwright (копия из steam_browser.py)."""
        page.goto("https://store.steampowered.com/login", wait_until="domcontentloaded", timeout=30000)

        login_form = page.locator('[data-featuretarget="login"]')
        login_form.wait_for(state="visible", timeout=15000)

        login_input = login_form.locator('input[type="text"]').first
        login_input.wait_for(state="visible", timeout=10000)
        login_input.fill(self.login)

        password_input = login_form.locator('input[type="password"]').first
        password_input.fill(self.password)

        submit_btn = login_form.locator('button[type="submit"]').first
        submit_btn.click()
        time.sleep(3)

        # 2FA
        if self.shared_secret:
            code = generate_steam_guard_code(self.shared_secret)
            logger.info(f"[Warmup] {self.login}: 2FA код {code}")

            char_inputs = page.locator('input[maxlength="1"][type="text"]')
            count = char_inputs.count()
            if count >= 5:
                for i in range(5):
                    char_inputs.nth(i).click()
                    char_inputs.nth(i).fill(code[i])
                    time.sleep(0.1)
                time.sleep(3)

        # Ждём загрузки после логина
        page.wait_for_load_state("networkidle", timeout=15000)
        logger.info(f"[Warmup] {self.login}: залогинен, URL={page.url}")

    # ─── Библиотека игр ─────────────────────────────────────

    def _fetch_random_profiles(self, page: Page, count: int = 10) -> list[str]:
        """Парсит участников рандомной группы Steam, возвращает URLs профилей."""
        groups = list(_STEAM_GROUPS)
        random.shuffle(groups)

        for group_url in groups:
            members_url = group_url + "/members"
            # Рандомная страница участников (1-5)
            page_num = random.randint(1, 30)
            url = f"{members_url}?p={page_num}"
            logger.info(f"[Warmup] {self.login}: парсим участников {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)

                profiles = page.evaluate("""
                    () => {
                        const blocks = document.querySelectorAll('.member_block');
                        const online = [];
                        const offline = [];
                        for (const block of blocks) {
                            const link = block.querySelector('a[href*="/profiles/"], a[href*="/id/"]');
                            if (!link || !link.href) continue;
                            const url = link.href;
                            // Проверяем онлайн-статус
                            const status = block.querySelector('.memberBlockStatusOnline, .memberBlockStatusInGame');
                            if (status) {
                                online.push(url);
                            } else {
                                offline.push(url);
                            }
                        }
                        // Сначала онлайн, потом оффлайн
                        return { online: [...new Set(online)], offline: [...new Set(offline)] };
                    }
                """)

                if profiles:
                    online = profiles.get("online", [])
                    offline = profiles.get("offline", [])
                    random.shuffle(online)
                    random.shuffle(offline)
                    # Приоритет онлайн, потом оффлайн как fallback
                    combined = online + offline
                    if combined:
                        result = combined[:count]
                        logger.info(f"[Warmup] {self.login}: найдено {len(online)} онлайн + {len(offline)} оффлайн, взяли {len(result)}")
                        return result
            except Exception as e:
                logger.debug(f"[Warmup] {self.login}: ошибка парсинга группы: {e}")
                continue

        logger.warning(f"[Warmup] {self.login}: не удалось найти профили в группах")
        return []

    def _fetch_owned_apps(self, page: Page) -> set[int]:
        """Загружает список app_id из библиотеки через Steam userdata API."""
        try:
            page.goto("https://store.steampowered.com/dynamicstore/userdata/", wait_until="networkidle", timeout=15000)
            time.sleep(1)
            data = page.evaluate("() => { try { return JSON.parse(document.body.innerText); } catch { return null; } }")
            if data and "rgOwnedApps" in data:
                owned = set(data["rgOwnedApps"])
                logger.info(f"[Warmup] {self.login}: библиотека загружена — {len(owned)} игр")
                return owned
        except Exception as e:
            logger.warning(f"[Warmup] {self.login}: не удалось загрузить библиотеку: {e}")
        return set()

    # ─── Квесты ──────────────────────────────────────────────

    def _quest_setup_avatar(self, page: Page):
        """Загрузить случайный аватар через URL."""
        page.goto("https://steamcommunity.com/my/edit/avatar?l=english", wait_until="networkidle", timeout=20000)
        time.sleep(2)

        # Загружаем стандартный аватар из URL (Steam принимает URL)
        # Или используем встроенный upload
        upload_btn = page.locator('input[type="file"]').first
        if upload_btn.count() > 0:
            # Создаём простой PNG файл для аватара (1x1 пиксель)
            import tempfile
            avatar_path = Path(tempfile.gettempdir()) / f"avatar_{self.login}.png"
            _generate_simple_avatar(avatar_path)
            upload_btn.set_input_files(str(avatar_path))
            time.sleep(2)
            # Сохраняем
            save_btn = page.locator('button:has-text("Save"), button:has-text("Сохранить")').first
            if save_btn.count() > 0:
                save_btn.click()
                time.sleep(2)
        else:
            logger.warning(f"[Warmup] {self.login}: upload input не найден для аватара")

    def _quest_setup_profile_name(self, page: Page):
        """Установить имя профиля, real name, custom URL и описание — всё за один заход."""
        page.goto("https://steamcommunity.com/my/edit?l=english", wait_until="networkidle", timeout=20000)
        time.sleep(2)

        # Имя профиля
        name = self.texts.get("nickname", random.choice(_NAMES) + str(random.randint(10, 99)))
        name_input = page.locator('input[name="personaName"], #personaName').first
        if name_input.count() > 0:
            name_input.fill(name)
            time.sleep(1)
            logger.info(f"[Warmup] {self.login}: никнейм = {name}")

        # Real name
        real_name = random.choice(_FIRST_NAMES) + " " + random.choice(_LAST_NAMES)
        real_name_input = page.locator('input[name="real_name"], #real_name').first
        if real_name_input.count() > 0:
            real_name_input.fill(real_name)
            time.sleep(1)
            logger.info(f"[Warmup] {self.login}: real name = {real_name}")

        # Custom URL
        custom_url = name.replace(" ", "").lower() + str(random.randint(1000, 99999))
        custom_url_input = page.locator('input[name="customURL"], #customURL').first
        if custom_url_input.count() > 0:
            custom_url_input.fill(custom_url)
            time.sleep(1)
            logger.info(f"[Warmup] {self.login}: custom URL = {custom_url}")

        # Описание профиля (bio) — на той же странице, не переходим заново
        bio = self.texts.get("bio", random.choice(_BIOS))
        summary = page.locator('textarea[name="summary"], #summary').first
        if summary.count() > 0:
            summary.fill(bio)
            time.sleep(1)
            logger.info(f"[Warmup] {self.login}: bio = {bio}")

        # Сохраняем всё одной кнопкой
        save_btn = page.locator('button:has-text("Save"), .profile_save_btn, #profile_save_btn').first
        if save_btn.count() > 0:
            save_btn.click()
            time.sleep(2)

    def _quest_setup_profile_summary(self, page: Page):
        """Алиас — описание профиля уже заполняется в setup_profile_name."""
        self._quest_setup_profile_name(page)

    def _quest_rate_game(self, page: Page):
        """Алиас — оценка входит в write_review."""
        self._quest_write_review(page)

    def _quest_write_review(self, page: Page):
        """Написать отзыв + поставить оценку на рандомную игру из библиотеки."""
        # Лениво загружаем библиотеку при первом вызове
        if not self.owned_apps:
            self.owned_apps = self._fetch_owned_apps(page)
        if not self.owned_apps:
            logger.warning(f"[Warmup] {self.login}: библиотека пуста, пропускаем отзыв")
            return

        # Фильтруем библиотеку: сначала пробуем известные популярные игры, потом остальные
        # Популярные игры с большей вероятностью имеют часы и рабочую страницу
        _PRIORITY_APPS = {730, 570, 440, 578080, 252490, 230410, 236390, 1203220,
                          2767030, 1962663, 444090, 431960, 304930, 2399830,
                          1172470, 1085660, 753640, 1599340}
        priority = [aid for aid in self.owned_apps if aid in _PRIORITY_APPS]
        rest = [aid for aid in self.owned_apps if aid not in _PRIORITY_APPS]
        random.shuffle(priority)
        random.shuffle(rest)

        # Сначала приоритетные, потом остальные — до 30 попыток
        all_candidates = (priority + rest)[:30]
        logger.info(f"[Warmup] {self.login}: отзыв — {len(priority)} приоритетных, "
                     f"{len(rest)} остальных, пробуем {len(all_candidates)}")

        for app_id in all_candidates:
            logger.info(f"[Warmup] {self.login}: пробуем отзыв на app/{app_id}")
            try:
                page.goto(f"https://store.steampowered.com/app/{app_id}/?l=english", wait_until="networkidle", timeout=15000)
            except Exception:
                continue
            time.sleep(2)

            # Проверяем что это реальная страница игры (не DLC, не редирект, не 404)
            current_url = page.url
            if "/app/" not in current_url:
                logger.info(f"[Warmup] {self.login}: app/{app_id} — редирект, пропускаем")
                continue

            # Ищем форму отзыва и скроллим к ней
            has_form = page.evaluate("""
                () => {
                    // Ищем textarea внутри секции отзывов, не любую textarea на странице
                    const selectors = [
                        '#TextReviewArea textarea',
                        '.review_area textarea',
                        '#review_text',
                        'textarea'
                    ];
                    for (const sel of selectors) {
                        const ta = document.querySelector(sel);
                        if (ta && ta.offsetParent !== null) {
                            ta.scrollIntoView({ behavior: 'smooth', block: 'center' });
                            return true;
                        }
                    }
                    return false;
                }
            """)
            time.sleep(2)

            if not has_form:
                continue

            # Форма найдена — заполняем
            review_text = self.texts.get("review", random.choice(_REVIEWS))
            review_box = page.locator('textarea').first
            try:
                review_box.click(timeout=5000)
                time.sleep(0.5)
                review_box.fill(review_text)
            except Exception:
                logger.info(f"[Warmup] {self.login}: app/{app_id} — textarea не кликабельна, следующая...")
                continue
            time.sleep(1)
            logger.info(f"[Warmup] {self.login}: отзыв на app/{app_id} заполнен")

            # Кликаем "Yes" (Do you recommend this game?)
            yes_btn = page.locator('a:has-text("Yes"), span:has-text("Yes")').first
            if yes_btn.count() > 0 and yes_btn.is_visible():
                yes_btn.click()
                time.sleep(1)
            else:
                page.evaluate("""
                    () => {
                        const els = document.querySelectorAll('a, span, div');
                        for (const el of els) {
                            if (el.textContent.trim() === 'Yes' && el.offsetParent !== null) {
                                el.click(); return;
                            }
                        }
                    }
                """)
                time.sleep(1)

            # Нажимаем "Post review"
            post_btn = page.locator(
                'span:has-text("Post review"), '
                'a:has-text("Post review"), '
                'button:has-text("Post review"), '
                '.btn_green_white_innerfade:has-text("Post")'
            ).first
            if post_btn.count() > 0 and post_btn.is_visible():
                post_btn.click()
                time.sleep(3)
                logger.info(f"[Warmup] {self.login}: отзыв на app/{app_id} опубликован")
            else:
                page.evaluate("""
                    () => {
                        const els = document.querySelectorAll('a, span, button');
                        for (const el of els) {
                            if (el.textContent.trim().includes('Post review') && el.offsetParent !== null) {
                                el.click(); return;
                            }
                        }
                    }
                """)
                time.sleep(3)
                logger.info(f"[Warmup] {self.login}: отзыв на app/{app_id} опубликован (JS fallback)")
            return

        logger.warning(f"[Warmup] {self.login}: не удалось найти игру с формой отзыва из {len(all_candidates)} попыток")

    def _quest_add_to_wishlist(self, page: Page):
        """Добавить рандомную игру в вишлист (перебирает пул пока не получится)."""
        games = list(_WISHLIST_GAMES)
        random.shuffle(games)

        selectors = [
            'button[data-tooltip-text="Add to your wishlist"]',
            '.queue_btn_wishlist',
            '#add_to_wishlist_area',
            'div.queue_btn_wishlist',
            'a:has-text("Add to Wishlist")',
            'span:has-text("Add to Wishlist")',
            'button:has-text("Add to Wishlist")',
        ]

        for app_id, game_name in games:
            logger.info(f"[Warmup] {self.login}: пробуем вишлист '{game_name}' (app/{app_id})")
            try:
                page.goto(f"https://store.steampowered.com/app/{app_id}/?l=english", wait_until="networkidle", timeout=20000)
            except Exception:
                logger.info(f"[Warmup] {self.login}: '{game_name}' — страница не загрузилась, следующая...")
                continue
            time.sleep(3)

            page.mouse.wheel(0, 300)
            time.sleep(1)

            # Уже в вишлисте — пробуем другую
            already = page.locator('#add_to_wishlist_area_success')
            if already.count() > 0 and already.is_visible():
                logger.info(f"[Warmup] {self.login}: '{game_name}' уже в вишлисте, следующая...")
                continue

            # Пробуем кликнуть по кнопке
            for selector in selectors:
                try:
                    el = page.locator(selector).first
                    if el.count() > 0 and el.is_visible():
                        el.click()
                        time.sleep(2)
                        logger.info(f"[Warmup] {self.login}: '{game_name}' добавлена в вишлист")
                        return
                except Exception:
                    continue

            # JS fallback
            added = page.evaluate("""
                () => {
                    const els = document.querySelectorAll('[class*="wishlist"], [class*="Wishlist"], [data-tooltip-text*="wishlist"]');
                    for (const el of els) {
                        if (el.offsetParent !== null) { el.click(); return true; }
                    }
                    return false;
                }
            """)
            if added:
                time.sleep(2)
                logger.info(f"[Warmup] {self.login}: '{game_name}' добавлена в вишлист (JS fallback)")
                return

            logger.info(f"[Warmup] {self.login}: '{game_name}' — кнопка вишлиста не найдена, следующая...")

        logger.warning(f"[Warmup] {self.login}: не удалось добавить игру в вишлист из {len(_WISHLIST_GAMES)} вариантов")

    def _quest_discovery_queue(self, page: Page):
        """Пройти Discovery Queue (10 игр)."""
        page.goto("https://store.steampowered.com/explore/?l=english", wait_until="networkidle", timeout=20000)
        time.sleep(3)

        # Нажимаем кнопку начала очереди
        start_selectors = [
            'a:has-text("Click here to begin exploring")',
            'a:has-text("Start Queue")',
            '.discovery_queue_overlay a',
            '#discovery_queue_start_link',
            'a.btn_medium[href*="explore"]',
        ]
        for sel in start_selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass
                    time.sleep(3)
                    logger.info(f"[Warmup] {self.login}: discovery queue — старт, URL={page.url}")
                    break
            except Exception:
                continue

        completed = 0
        for i in range(12):
            # Скроллим вниз — кнопка "Next in Queue" внизу страницы
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            # Пробуем найти и кликнуть "Next in Queue"
            clicked = False
            selectors = [
                '#next_in_queue_form .next_in_queue_content',
                '.btn_next_in_queue',
                'div.next_in_queue_content',
                'a:has-text("Next in Queue")',
                'span:has-text("Next in Queue")',
            ]
            for selector in selectors:
                try:
                    el = page.locator(selector).first
                    if el.count() > 0 and el.is_visible():
                        el.click()
                        clicked = True
                        logger.info(f"[Warmup] {self.login}: discovery queue шаг {i+1} — клик '{selector}'")
                        break
                except Exception:
                    continue

            if not clicked:
                # JS fallback — submit формы или клик по тексту
                clicked = page.evaluate("""
                    () => {
                        const form = document.querySelector('#next_in_queue_form');
                        if (form) { form.submit(); return true; }
                        const els = document.querySelectorAll('a, div, span, button');
                        for (const el of els) {
                            if (el.textContent.trim().includes('Next in Queue') && el.offsetParent !== null) {
                                el.click(); return true;
                            }
                        }
                        return false;
                    }
                """)
                if clicked:
                    logger.info(f"[Warmup] {self.login}: discovery queue шаг {i+1} — JS fallback")

            if not clicked:
                # Может это последняя страница очереди — проверяем
                is_end = page.evaluate("""
                    () => {
                        const body = document.body.innerText;
                        return body.includes('explore more') || body.includes('You explored your queue');
                    }
                """)
                if is_end or completed >= 10:
                    logger.info(f"[Warmup] {self.login}: discovery queue — очередь пройдена ({completed} игр)")
                    break
                logger.info(f"[Warmup] {self.login}: discovery queue — кнопка не найдена на шаге {i+1}")
                break

            # Ждём загрузку следующей страницы
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            time.sleep(2)
            completed += 1

        logger.info(f"[Warmup] {self.login}: discovery queue завершён — {completed} игр пролистано")

    def _quest_join_group(self, page: Page):
        """Вступить в рандомную группу Steam."""
        groups = list(_STEAM_GROUPS)
        random.shuffle(groups)

        for group_url in groups:
            url = group_url + "?l=english"
            logger.info(f"[Warmup] {self.login}: пробуем группу {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except Exception:
                continue
            time.sleep(3)

            # Уже в группе?
            is_member = page.evaluate("""
                () => {
                    const text = document.body.innerText;
                    return text.includes('Leave group') || text.includes('Покинуть группу')
                        || text.includes('In Group') || text.includes('В группе');
                }
            """)
            if is_member:
                logger.info(f"[Warmup] {self.login}: уже в группе, следующая...")
                continue

            # Кликаем кнопку Join через JS — самый надёжный способ
            clicked = page.evaluate("""
                () => {
                    // Ищем зелёную кнопку в join area
                    const joinArea = document.querySelector('.grouppage_join_area');
                    if (joinArea) {
                        const btn = joinArea.querySelector('a');
                        if (btn) { btn.click(); return 'joinArea'; }
                    }
                    // Ищем любую зелёную кнопку с текстом Join
                    const greens = document.querySelectorAll('.btn_green_white_innerfade');
                    for (const g of greens) {
                        if (g.textContent.includes('Join') && g.offsetParent !== null) {
                            g.click(); return 'green_join';
                        }
                    }
                    // Ищем по тексту
                    const all = document.querySelectorAll('a, span, button, div');
                    for (const el of all) {
                        const t = el.textContent.trim();
                        if ((t === 'Join Group' || t === 'Join group') && el.offsetParent !== null) {
                            el.click(); return 'text_join';
                        }
                    }
                    return null;
                }
            """)

            if clicked:
                time.sleep(2)
                logger.info(f"[Warmup] {self.login}: вступил в группу ({clicked})")
                return

            # Последняя попытка — Playwright force click
            try:
                btn = page.locator('.grouppage_join_area a').first
                if btn.count() > 0:
                    btn.click(force=True)
                    time.sleep(2)
                    logger.info(f"[Warmup] {self.login}: вступил в группу (force click)")
                    return
            except Exception:
                pass

            logger.info(f"[Warmup] {self.login}: кнопка Join не найдена на {group_url}")

        raise RuntimeError("Не удалось вступить ни в одну группу")

    def _quest_subscribe_workshop(self, page: Page):
        """Подписаться на рандомный Workshop item."""
        items = list(_WORKSHOP_ITEMS)
        random.shuffle(items)

        for item_url in items:
            url = item_url + "&l=english" if "?" in item_url else item_url + "?l=english"
            logger.info(f"[Warmup] {self.login}: пробуем Workshop {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except Exception:
                continue
            time.sleep(3)

            # Всё через JS — надёжнее чем Playwright селекторы
            result = page.evaluate("""
                () => {
                    // Проверяем уже подписан
                    const btn = document.querySelector('#SubscribeItemBtn');
                    if (btn) {
                        if (btn.classList.contains('toggled')) return 'already';
                        btn.click();
                        return 'clicked_id';
                    }
                    // Ищем по тексту Subscribe (но не Unsubscribe)
                    const els = document.querySelectorAll('a, span, button, div');
                    for (const el of els) {
                        const t = el.textContent.trim();
                        if (t === 'Subscribe' && el.offsetParent !== null) {
                            el.click(); return 'clicked_text';
                        }
                    }
                    return null;
                }
            """)

            if result == 'already':
                logger.info(f"[Warmup] {self.login}: уже подписан, следующий...")
                # Всё равно ставим thumbs up
                self._rate_workshop_item(page)
                return
            if result and result.startswith('clicked'):
                time.sleep(2)
                logger.info(f"[Warmup] {self.login}: подписка Workshop ({result})")
                self._rate_workshop_item(page)
                return

            # Последняя попытка — force click
            try:
                btn = page.locator('#SubscribeItemBtn').first
                if btn.count() > 0:
                    btn.click(force=True)
                    time.sleep(2)
                    logger.info(f"[Warmup] {self.login}: подписка Workshop (force click)")
                    self._rate_workshop_item(page)
                    return
            except Exception:
                pass

            logger.info(f"[Warmup] {self.login}: кнопка Subscribe не найдена")

        raise RuntimeError("Не удалось подписаться ни на один Workshop item")

    def _rate_workshop_item(self, page: Page):
        """Поставить thumbs up на текущей странице Workshop item."""
        try:
            rated = page.evaluate("""
                () => {
                    // Кнопка Rate Up / Thumbs Up
                    const btn = document.querySelector('#VoteUpBtn, .rateUp, [id*="VoteUp"]');
                    if (btn && btn.offsetParent !== null) {
                        btn.click(); return 'vote_btn';
                    }
                    // По тексту
                    const els = document.querySelectorAll('a, span, div');
                    for (const el of els) {
                        const t = el.textContent.trim();
                        if ((t === 'Rate Up' || t === 'Thumbs Up' || t === '👍') && el.offsetParent !== null) {
                            el.click(); return 'text';
                        }
                    }
                    // По иконке
                    const imgs = document.querySelectorAll('img[src*="thumb"], img[src*="rate_up"]');
                    for (const img of imgs) {
                        if (img.offsetParent !== null) { img.click(); return 'img'; }
                    }
                    return null;
                }
            """)
            time.sleep(1)
            if rated:
                logger.info(f"[Warmup] {self.login}: Workshop item rated up ({rated})")
        except Exception:
            pass

    def _quest_visit_discussions(self, page: Page):
        """Выполнить поиск в дискуссиях Steam."""
        page.goto("https://steamcommunity.com/discussions/?l=english", wait_until="domcontentloaded", timeout=20000)
        time.sleep(3)

        # Ищем поле поиска и вводим запрос
        search_terms = ["cs2", "game tips", "steam update", "best settings", "help", "trading"]
        query = random.choice(search_terms)

        search_input = page.locator('input[name="forum_search_text"], input[placeholder*="Search"], input[type="search"]').first
        if search_input.count() > 0 and search_input.is_visible():
            search_input.click()
            time.sleep(0.5)
            search_input.fill(query)
            time.sleep(1)
            search_input.press("Enter")
            time.sleep(3)
            logger.info(f"[Warmup] {self.login}: discussions — поиск '{query}'")
        else:
            # JS fallback
            page.evaluate("""
                (q) => {
                    const input = document.querySelector('input[name="forum_search_text"]')
                        || document.querySelector('input[placeholder*="Search"]');
                    if (input) {
                        input.value = q;
                        input.form?.submit();
                    }
                }
            """, query)
            time.sleep(3)
            logger.info(f"[Warmup] {self.login}: discussions — поиск '{query}' (JS)")

    def _add_friend_on_profile(self, page: Page, url: str) -> bool:
        """Добавить в друзья на странице профиля. Возвращает True если кнопка нажата."""
        full_url = url + ("&l=english" if "?" in url else "?l=english")
        try:
            page.goto(full_url, wait_until="domcontentloaded", timeout=15000)
        except Exception:
            return False
        time.sleep(2)

        result = page.evaluate("""
            () => {
                const els = document.querySelectorAll('a, span, button');
                for (const el of els) {
                    const t = el.textContent.trim();
                    if (t === 'Add Friend' && el.offsetParent !== null) {
                        el.click(); return 'clicked';
                    }
                }
                // Уже друзья или заявка отправлена
                for (const el of els) {
                    const t = el.textContent.trim();
                    if (t.includes('Pending') || t.includes('Friends') || t.includes('Accept')) {
                        return 'already';
                    }
                }
                return null;
            }
        """)
        time.sleep(1)
        return result == 'clicked'

    def _quest_add_friend(self, page: Page):
        """Добавить рандомных людей в друзья из участников групп."""
        target_count = self.friend_requests_count
        added = 0

        # Сначала мастер-аккаунт если указан
        if self.master_steam_id:
            mid = self.master_steam_id.strip()
            url = f"https://steamcommunity.com/profiles/{mid}" if mid.isdigit() else f"https://steamcommunity.com/id/{mid}"
            if self._add_friend_on_profile(page, url):
                added += 1
                logger.info(f"[Warmup] {self.login}: add_friend — мастер добавлен")

        # Парсим рандомных людей из групп
        profiles = self._fetch_random_profiles(page, count=15)

        for profile_url in profiles:
            if added >= target_count:
                break

            logger.info(f"[Warmup] {self.login}: add_friend — пробуем {profile_url}")
            if self._add_friend_on_profile(page, profile_url):
                added += 1
                logger.info(f"[Warmup] {self.login}: add_friend — добавлен ({added}/{target_count})")
                time.sleep(random.uniform(2, 5))

        logger.info(f"[Warmup] {self.login}: add_friend — итого {added} заявок отправлено")

    def _post_comment_on_profile(self, page: Page, url: str, comment_text: str) -> bool:
        """Оставить комментарий на профиле. Возвращает True если удалось."""
        full_url = url + ("&l=english" if "?" in url else "?l=english")
        try:
            page.goto(full_url, wait_until="domcontentloaded", timeout=15000)
        except Exception:
            return False
        time.sleep(3)

        # Скроллим к комментариям
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)

        # Ищем textarea через Playwright — пробуем разные селекторы
        textarea_selectors = [
            '.commentthread_entry_quotebox textarea',
            'textarea.commentthread_textarea',
            'textarea[placeholder*="Add a comment"]',
            'textarea[placeholder*="comment" i]',
        ]

        textarea = None
        for sel in textarea_selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0:
                    # Скроллим к textarea и кликаем
                    el.scroll_into_view_if_needed(timeout=3000)
                    time.sleep(1)
                    el.click(timeout=3000)
                    time.sleep(1)
                    textarea = el
                    logger.info(f"[Warmup] {self.login}: comment — textarea найдена '{sel}'")
                    break
            except Exception:
                continue

        if not textarea:
            logger.info(f"[Warmup] {self.login}: comment — textarea не найдена на {url}")
            return False

        # Печатаем текст посимвольно — триггерит JS Steam
        textarea.type(comment_text, delay=30)
        time.sleep(3)
        logger.info(f"[Warmup] {self.login}: comment — текст введён")

        # Ищем кнопку Post Comment
        post_selectors = [
            '.commentthread_entry_submitlink a.btn_green_white_innerfade',
            'span:has-text("Post Comment")',
            'a:has-text("Post Comment")',
        ]
        for sel in post_selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=3000)
                    time.sleep(2)
                    logger.info(f"[Warmup] {self.login}: comment — опубликован через '{sel}'")
                    return True
            except Exception:
                continue

        # JS fallback
        clicked = page.evaluate("""
            () => {
                const els = document.querySelectorAll('a, span, button');
                for (const el of els) {
                    if (el.textContent.trim() === 'Post Comment' && el.offsetParent !== null) {
                        el.click(); return true;
                    }
                }
                const btns = document.querySelectorAll('.commentthread_entry_submitlink a.btn_green_white_innerfade');
                for (const btn of btns) {
                    if (btn.offsetParent !== null) { btn.click(); return true; }
                }
                return false;
            }
        """)
        time.sleep(2)
        if clicked:
            logger.info(f"[Warmup] {self.login}: comment — опубликован (JS fallback)")
            return True

        logger.info(f"[Warmup] {self.login}: comment — кнопка Post не найдена на {url}")
        return False

    def _quest_post_comment(self, page: Page):
        """Оставить комментарий: мастер-аккаунт или рандомный из группы."""
        comment_text = self.texts.get("comment", random.choice(_COMMENTS))

        # 1. Если есть мастер — комментим его
        if self.master_steam_id:
            mid = self.master_steam_id.strip()
            master_url = f"https://steamcommunity.com/profiles/{mid}" if mid.isdigit() else f"https://steamcommunity.com/id/{mid}"
            logger.info(f"[Warmup] {self.login}: post_comment — мастер {master_url}")
            if self._post_comment_on_profile(page, master_url, comment_text):
                logger.info(f"[Warmup] {self.login}: комментарий опубликован на мастере")
                return
            logger.info(f"[Warmup] {self.login}: post_comment — мастер не получился, ищем рандомного...")

        # 2. Ищем рандомного из группы с открытыми комментами
        profiles = self._fetch_random_profiles(page, count=15)
        if not profiles:
            logger.warning(f"[Warmup] {self.login}: post_comment — не удалось спарсить профили")
            return

        for url in profiles:
            logger.info(f"[Warmup] {self.login}: post_comment — пробуем {url}")
            if self._post_comment_on_profile(page, url, comment_text):
                logger.info(f"[Warmup] {self.login}: комментарий опубликован на {url}")
                return

        logger.warning(f"[Warmup] {self.login}: post_comment — не удалось оставить комментарий ни на одном профиле")

    def _quest_setup_profile_background(self, page: Page):
        """Настроить фон профиля (просто посетить страницу настройки)."""
        page.goto("https://steamcommunity.com/my/edit/background?l=english", wait_until="networkidle", timeout=20000)
        time.sleep(2)
        # Посещение страницы настройки фона засчитывается

    def _quest_post_status(self, page: Page):
        """Post a status and rate it up."""
        page.goto("https://steamcommunity.com/my/home?l=english", wait_until="domcontentloaded", timeout=20000)
        time.sleep(3)

        statuses = [
            "Just started gaming!", "Having a great day!", "Ready for some matches!",
            "Exploring new games", "Good vibes today", "Let's play!",
            "Chilling on Steam", "Looking for teammates", "GG everyone!",
        ]
        status_text = random.choice(statuses)

        # Заполняем поле статуса
        input_sel = page.locator('#blotter_statuspost_textarea, textarea[placeholder*="Post a status"], .commentthread_textarea').first
        if input_sel.count() > 0 and input_sel.is_visible():
            input_sel.click()
            time.sleep(1)
            input_sel.type(status_text, delay=30)
            time.sleep(2)
        else:
            raise RuntimeError("Поле статуса не найдено")

        # Нажимаем POST
        page.evaluate("""
            () => {
                const els = document.querySelectorAll('a, span, button, div');
                for (const el of els) {
                    const t = el.textContent.trim();
                    if ((t === 'POST' || t === 'Post' || t === 'Post Status') && el.offsetParent !== null) {
                        el.click(); return true;
                    }
                }
                const btn = document.querySelector('.blotter_userstatus_submit, [onclick*="PostStatus"]');
                if (btn) { btn.click(); return true; }
                return false;
            }
        """)
        time.sleep(3)
        logger.info(f"[Warmup] {self.login}: статус опубликован — '{status_text}'")

        # Переходим в ленту активности — там виден свежий пост и кнопка Rate up
        page.goto("https://steamcommunity.com/my/myactivity?l=english", wait_until="domcontentloaded", timeout=20000)
        time.sleep(4)

        # Лайкаем первый пост (только что опубликованный статус)
        rated = page.evaluate("""
            () => {
                // Кнопка Rate up на статусах в ленте активности
                const btn = document.querySelector('[id^="vote_up_userstatus_"], [onclick*="VoteUpCommentThread"]');
                if (btn && btn.offsetParent !== null) {
                    btn.scrollIntoView({ block: 'center' });
                    btn.click();
                    return 'vote_up_status';
                }
                // Любая кнопка thumb_up в ленте
                const thumbs = document.querySelectorAll('i.thumb_up, .ico16.thumb_up');
                for (const t of thumbs) {
                    const a = t.closest('a');
                    if (a && a.offsetParent !== null) {
                        a.scrollIntoView({ block: 'center' });
                        a.click();
                        return 'thumb_up';
                    }
                }
                return null;
            }
        """)
        time.sleep(1)
        if rated:
            logger.info(f"[Warmup] {self.login}: свой статус лайкнут ({rated})")
        else:
            logger.warning(f"[Warmup] {self.login}: кнопка Rate up не найдена на странице активности")

    def _quest_rate_activity(self, page: Page):
        """Alias — rate activity is done inside post_status."""
        self._quest_post_status(page)

    def _quest_view_broadcast(self, page: Page):
        """View a Steam broadcast."""
        # Патчим MediaSource.isTypeSupported — Steam player проверяет поддержку кодеков
        # до отправки tracking-запросов. Возвращаем true для всех типов, видео не играет
        # но все API-вызовы трекинга отправляются.
        page.add_init_script("""
            if (window.MediaSource) {
                window.MediaSource.isTypeSupported = function() { return true; };
            }
            if (window.HTMLMediaElement) {
                HTMLMediaElement.prototype.canPlayType = function() { return 'probably'; };
            }
        """)

        page.goto("https://steamcommunity.com/?subsection=broadcasts&l=english", wait_until="domcontentloaded", timeout=20000)
        time.sleep(3)

        # Извлекаем URL первой трансляции
        broadcast_url = page.evaluate("""
            () => {
                const links = document.querySelectorAll('a[href*="/broadcast/watch/"]');
                for (const a of links) {
                    if (a.offsetParent !== null && a.href) return a.href;
                }
                return null;
            }
        """)

        if broadcast_url:
            logger.info(f"[Warmup] {self.login}: переходим на трансляцию {broadcast_url}")
            page.goto(broadcast_url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(10)  # Ждём tracking API-вызовов
            logger.info(f"[Warmup] {self.login}: трансляция посещена")
        else:
            raise RuntimeError("Трансляции не найдены на странице broadcasts")

    def _quest_send_emoticon(self, page: Page):
        """Send an emoticon in Steam web chat to a random friend."""
        page.goto("https://steamcommunity.com/chat/?l=english", wait_until="domcontentloaded", timeout=30000)
        time.sleep(8)  # React-чат грузится очень долго

        emoticons = [":steamsad:", ":steammocking:", ":steamhappy:", ":steamfacepalm:", ":steambored:"]
        emoticon = random.choice(emoticons)

        # 1. Находим группу Offline и раскрываем через JS + scrollIntoView
        opened = page.evaluate("""
            () => {
                // Находим контейнер .offlineFriends
                const container = document.querySelector('.offlineFriends, .DropTarget.friendGroup.offlineFriends');
                if (container) {
                    const groupName = container.querySelector('.groupName');
                    if (groupName) {
                        groupName.scrollIntoView({ block: 'center' });
                        groupName.click();
                        return 'offlineFriends';
                    }
                }
                // Fallback — ищем по тексту
                const groups = document.querySelectorAll('.groupName');
                for (const g of groups) {
                    const text = g.textContent.trim();
                    if (text.includes('Offline') || text.includes('Не в сети')) {
                        g.scrollIntoView({ block: 'center' });
                        g.click();
                        return text;
                    }
                }
                return null;
            }
        """)
        time.sleep(2)

        if opened:
            logger.info(f"[Warmup] {self.login}: send_emoticon — группа раскрыта ({opened})")
        else:
            logger.warning(f"[Warmup] {self.login}: send_emoticon — группа Offline не найдена")
            return

        # 2. Скроллим к первому другу внутри .offlineFriends и кликаем ПКМ
        clicked_friend = page.evaluate("""
            () => {
                const container = document.querySelector('.offlineFriends .groupList');
                if (!container) return null;
                const friend = container.querySelector('.friend.offline[draggable="true"]');
                if (!friend) return null;
                friend.scrollIntoView({ block: 'center' });
                return friend.querySelector('.personanameandstatus_playerName_nOdcT')?.textContent || 'found';
            }
        """)
        time.sleep(1)

        if not clicked_friend:
            logger.warning(f"[Warmup] {self.login}: send_emoticon — друг не найден в Offline")
            return

        # ПКМ через Playwright на первого друга в .offlineFriends
        friend = page.locator('.offlineFriends .groupList .friend.offline[draggable="true"]').first
        if friend.count() > 0:
            friend.click(button="right")
            time.sleep(2)
            logger.info(f"[Warmup] {self.login}: send_emoticon — ПКМ на '{clicked_friend}'")
        else:
            logger.warning(f"[Warmup] {self.login}: send_emoticon — не удалось кликнуть ПКМ")
            return

        # 3. Кликаем "Отправить сообщение" / "Send Message" в контекстном меню
        send_msg = page.locator('text=/Send Message|Отправить сообщение/i').first
        if send_msg.count() > 0 and send_msg.is_visible():
            send_msg.click()
            time.sleep(3)
            logger.info(f"[Warmup] {self.login}: send_emoticon — чат открыт")
        else:
            logger.warning(f"[Warmup] {self.login}: send_emoticon — пункт меню не найден")
            return

        # 4. Печатаем эмодзи
        chat_input = page.locator('textarea').first
        if chat_input.count() > 0 and chat_input.is_visible():
            chat_input.click()
            time.sleep(0.5)
            chat_input.type(emoticon, delay=30)
            time.sleep(1)
            logger.info(f"[Warmup] {self.login}: send_emoticon — '{emoticon}' напечатан")
        else:
            logger.warning(f"[Warmup] {self.login}: send_emoticon — textarea не найдена")
            return

        # 5. Кнопка отправки
        submit = page.locator('[class*="chatSubmitButton"], button[type="submit"]').first
        if submit.count() > 0 and submit.is_visible():
            submit.click()
            time.sleep(2)
            logger.info(f"[Warmup] {self.login}: эмодзи '{emoticon}' отправлен")
        else:
            chat_input.press("Enter")
            time.sleep(2)
            logger.info(f"[Warmup] {self.login}: эмодзи '{emoticon}' отправлен (Enter)")

    def _quest_feature_badge(self, page: Page):
        """Feature a badge on profile (Community or Game Collector)."""
        badge_ids = [2, 13]  # 2 = Community, 13 = Game Collector
        random.shuffle(badge_ids)

        for badge_id in badge_ids:
            page.goto(f"https://steamcommunity.com/my/badges/{badge_id}?l=english",
                       wait_until="domcontentloaded", timeout=20000)
            time.sleep(3)

            clicked = page.evaluate("""
                () => {
                    const btns = document.querySelectorAll('button, a, span');
                    for (const btn of btns) {
                        const t = btn.textContent.trim();
                        if (t.includes('Feature this badge') && btn.offsetParent !== null) {
                            btn.click(); return true;
                        }
                    }
                    return false;
                }
            """)

            if clicked:
                time.sleep(2)
                logger.info(f"[Warmup] {self.login}: Featured Badge #{badge_id} установлен")
                return

            logger.info(f"[Warmup] {self.login}: бейдж #{badge_id} — кнопка Feature не найдена, следующий...")

        logger.warning(f"[Warmup] {self.login}: не удалось установить Featured Badge")


def _generate_simple_avatar(path: Path):
    """Генерирует простой PNG-аватар (цветной квадрат 184x184)."""
    import struct
    import zlib

    w, h = 184, 184
    r, g, b = random.randint(30, 200), random.randint(30, 200), random.randint(30, 200)

    raw_data = b""
    for _ in range(h):
        raw_data += b"\x00"  # filter byte
        raw_data += bytes([r, g, b]) * w

    def make_chunk(chunk_type, data):
        chunk = chunk_type + data
        return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    compressed = zlib.compress(raw_data)

    png = signature + make_chunk(b"IHDR", ihdr) + make_chunk(b"IDAT", compressed) + make_chunk(b"IEND", b"")
    path.write_bytes(png)
