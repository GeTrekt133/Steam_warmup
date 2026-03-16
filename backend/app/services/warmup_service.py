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
    # Группа 1: Настройка профиля (порядок важен: имя → описание → сохранение)
    ["setup_avatar", "setup_profile_name", "setup_profile_summary"],
    # Группа 2: Магазин / обзоры (оценка → отзыв)
    ["rate_game", "write_review"],
    # Группа 3: Независимые квесты (каждый сам по себе)
    ["add_to_wishlist"],
    ["discovery_queue"],
    ["join_group"],
    ["subscribe_workshop"],
    ["visit_discussions"],
    # Группа 4: Социальные (добавить друга → комментарий)
    ["add_friend", "post_comment"],
    # Группа 5: Фон (независимый)
    ["setup_profile_background"],
]


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

    # Перемешиваем группы
    random.shuffle(groups)

    # Собираем обратно в плоский список
    result = []
    for group in groups:
        result.extend(group)
    return result

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

# Публичная группа Steam (Official Game Group: CS2)
DEFAULT_GROUP_URL = "https://steamcommunity.com/groups/CSGOBetaTesting"

# Workshop item для подписки (популярный CS2 карта)
DEFAULT_WORKSHOP_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id=3213752450"

# ─── Описание квестов ────────────────────────────────────────

QUEST_LIST = [
    ("setup_avatar", "Настройка аватара"),
    ("setup_profile_name", "Имя профиля"),
    ("setup_profile_summary", "Описание профиля"),
    ("rate_game", "Оценка игры"),
    ("write_review", "Отзыв на игру"),
    ("add_to_wishlist", "Добавление в вишлист"),
    ("discovery_queue", "Discovery Queue"),
    ("join_group", "Вступление в группу"),
    ("subscribe_workshop", "Подписка Workshop"),
    ("visit_discussions", "Посещение дискуссий"),
    ("add_friend", "Добавление друга"),
    ("post_comment", "Комментарий на профиле"),
    ("setup_profile_background", "Настройка фона"),
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

        try:
            pw = sync_playwright().start()
            browser_args = {"headless": False}
            if self.proxy_config:
                browser_args["proxy"] = self.proxy_config

            browser = pw.chromium.launch(**browser_args)
            context = browser.new_context()
            page = context.new_page()

            # Логин
            self._steam_login(page)

            # Рандомизируем порядок квестов (с учётом зависимостей)
            shuffled = shuffle_quests(self.quests)
            # Обновляем статусы в новом порядке
            self.quests = shuffled
            self.status.quests = [
                QuestStatus(quest_id=qid, quest_name=qname) for qid, qname in shuffled
            ]
            logger.info(f"[Warmup] {self.login}: порядок квестов: {[q[0] for q in shuffled]}")

            # Общий timeout на весь warmup
            warmup_start_time = time.time()

            # Выполняем квесты
            for i, (quest_id, quest_name) in enumerate(self.quests):
                # Проверяем общий timeout
                elapsed = time.time() - warmup_start_time
                if elapsed > self.warmup_timeout:
                    logger.warning(
                        f"[Warmup] {self.login}: общий timeout {self.warmup_timeout}s "
                        f"превышен ({elapsed:.0f}s), пропускаем оставшиеся квесты"
                    )
                    for j in range(i, len(self.quests)):
                        self.status.quests[j].status = "skipped"
                        self.status.quests[j].error = "Общий timeout превышен"
                    break

                qs = self.status.quests[i]
                qs.status = "running"
                self.status.current_quest = quest_name

                method = getattr(self, f"_quest_{quest_id}", None)
                if not method:
                    qs.status = "skipped"
                    qs.error = "Не реализован"
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

            self.status.status = "done"
            self.status.current_quest = None

            browser.close()
            pw.stop()

        except Exception as e:
            logger.error(f"[Warmup] {self.login}: критическая ошибка: {e}")
            self.status.status = "error"
            self.status.error = str(e)[:300]

        logger.info(f"[Warmup] {self.login}: завершён ({self.status.quests_done}/{self.status.quests_total})")
        return self.status

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

    # ─── Квесты ──────────────────────────────────────────────

    def _quest_setup_avatar(self, page: Page):
        """Загрузить случайный аватар через URL."""
        page.goto("https://steamcommunity.com/my/edit/avatar", wait_until="networkidle", timeout=20000)
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
        """Установить имя профиля."""
        page.goto("https://steamcommunity.com/my/edit", wait_until="networkidle", timeout=20000)
        time.sleep(2)

        name = self.texts.get("nickname", random.choice(_NAMES) + str(random.randint(10, 99)))
        name_input = page.locator('input[name="personaName"], #personaName').first
        if name_input.count() > 0:
            name_input.fill(name)
            time.sleep(1)
            logger.info(f"[Warmup] {self.login}: никнейм = {name}")

    def _quest_setup_profile_summary(self, page: Page):
        """Установить описание профиля."""
        page.goto("https://steamcommunity.com/my/edit", wait_until="networkidle", timeout=20000)
        time.sleep(2)

        bio = self.texts.get("bio", random.choice(_BIOS))
        summary = page.locator('textarea[name="summary"], #summary').first
        if summary.count() > 0:
            summary.fill(bio)
            time.sleep(1)
            logger.info(f"[Warmup] {self.login}: bio = {bio}")

        # Сохраняем профиль (имя + summary вместе)
        save_btn = page.locator('button:has-text("Save"), .profile_save_btn, #profile_save_btn').first
        if save_btn.count() > 0:
            save_btn.click()
            time.sleep(2)

    def _quest_rate_game(self, page: Page):
        """Оценить игру (thumbs up) на странице магазина."""
        page.goto("https://store.steampowered.com/app/730/Counter-Strike_2/", wait_until="networkidle", timeout=20000)
        time.sleep(2)

        # Ищем кнопку thumbs up
        thumbs_up = page.locator('.review_controls .thumb.up, [data-tooltip="Recommended"]').first
        if thumbs_up.count() > 0 and thumbs_up.is_visible():
            thumbs_up.click()
            time.sleep(2)
        else:
            logger.info(f"[Warmup] {self.login}: rate_game — кнопка не найдена или уже оценена")

    def _quest_write_review(self, page: Page):
        """Написать отзыв на игру (CS2)."""
        # Переходим на страницу отзывов CS2
        page.goto("https://store.steampowered.com/app/730/Counter-Strike_2/", wait_until="networkidle", timeout=20000)
        time.sleep(2)

        # Ищем кнопку "Write a Review" / "Написать обзор"
        review_btn = page.locator(
            'a:has-text("Write a Review"), '
            'a:has-text("Написать обзор"), '
            '.review_create_button, '
            '#review_create'
        ).first
        if review_btn.count() > 0 and review_btn.is_visible():
            review_btn.click()
            time.sleep(3)

            # Заполняем текст отзыва
            review_box = page.locator(
                'textarea.review_box, '
                '#review_text, '
                '.newmodal textarea, '
                'textarea[name="review_text"]'
            ).first
            if review_box.count() > 0:
                review_text = self.texts.get("review", random.choice(_REVIEWS))
                review_box.fill(review_text)
                time.sleep(1)

                # Ставим "Рекомендую"
                recommend_btn = page.locator(
                    '.review_controls .thumb.up, '
                    '#ReviewRecommend, '
                    'input[name="recommend"][value="1"]'
                ).first
                if recommend_btn.count() > 0:
                    recommend_btn.click()
                    time.sleep(0.5)

                # Нажимаем "Опубликовать"
                submit_btn = page.locator(
                    'button:has-text("Post"), '
                    'button:has-text("Опубликовать"), '
                    '.btn_green_white_innerfade:has-text("Post"), '
                    '#review_submit'
                ).first
                if submit_btn.count() > 0:
                    submit_btn.click()
                    time.sleep(3)
                    logger.info(f"[Warmup] {self.login}: отзыв опубликован")
                else:
                    logger.warning(f"[Warmup] {self.login}: кнопка публикации отзыва не найдена")
            else:
                logger.warning(f"[Warmup] {self.login}: поле текста отзыва не найдено")
        else:
            logger.info(f"[Warmup] {self.login}: кнопка 'Write Review' не найдена (уже есть отзыв?)")

    def _quest_add_to_wishlist(self, page: Page):
        """Добавить игру в вишлист."""
        page.goto("https://store.steampowered.com/app/570/Dota_2/", wait_until="networkidle", timeout=20000)
        time.sleep(2)

        wishlist_btn = page.locator('#add_to_wishlist_area, .queue_btn_wishlist').first
        if wishlist_btn.count() > 0 and wishlist_btn.is_visible():
            wishlist_btn.click()
            time.sleep(2)

    def _quest_discovery_queue(self, page: Page):
        """Пройти Discovery Queue (10 игр)."""
        page.goto("https://store.steampowered.com/explore/", wait_until="networkidle", timeout=20000)
        time.sleep(2)

        for i in range(10):
            try:
                next_btn = page.locator('#next_in_queue_form .next_in_queue_content, .btn_next_in_queue').first
                if next_btn.count() > 0 and next_btn.is_visible():
                    next_btn.click()
                    page.wait_for_load_state("networkidle", timeout=10000)
                    time.sleep(1)
                else:
                    break
            except Exception:
                break

    def _quest_join_group(self, page: Page):
        """Вступить в группу Steam."""
        page.goto(DEFAULT_GROUP_URL, wait_until="networkidle", timeout=20000)
        time.sleep(2)

        join_btn = page.locator('.btn_green_white_innerfade:has-text("Join"), .grouppage_join_area a').first
        if join_btn.count() > 0 and join_btn.is_visible():
            join_btn.click()
            time.sleep(2)

    def _quest_subscribe_workshop(self, page: Page):
        """Подписаться на Workshop item."""
        page.goto(DEFAULT_WORKSHOP_URL, wait_until="networkidle", timeout=20000)
        time.sleep(2)

        sub_btn = page.locator('#SubscribeItemBtn, .btn_subscribe').first
        if sub_btn.count() > 0 and sub_btn.is_visible():
            sub_btn.click()
            time.sleep(2)

    def _quest_visit_discussions(self, page: Page):
        """Посетить дискуссии."""
        page.goto("https://steamcommunity.com/discussions/", wait_until="networkidle", timeout=20000)
        time.sleep(2)
        # Просто посещение засчитывается

    def _quest_add_friend(self, page: Page):
        """Добавить мастер-аккаунт в друзья."""
        if not self.master_steam_id:
            raise ValueError("Мастер-аккаунт не указан")

        page.goto(
            f"https://steamcommunity.com/profiles/{self.master_steam_id}",
            wait_until="networkidle",
            timeout=20000,
        )
        time.sleep(2)

        add_btn = page.locator('.btn_profile_action:has-text("Add Friend"), .btn_green_white_innerfade:has-text("Add")').first
        if add_btn.count() > 0 and add_btn.is_visible():
            add_btn.click()
            time.sleep(2)
        else:
            logger.info(f"[Warmup] {self.login}: add_friend — кнопка не найдена (уже друзья?)")

    def _quest_post_comment(self, page: Page):
        """Оставить комментарий на профиле мастер-аккаунта."""
        if not self.master_steam_id:
            raise ValueError("Мастер-аккаунт не указан")

        page.goto(
            f"https://steamcommunity.com/profiles/{self.master_steam_id}",
            wait_until="networkidle",
            timeout=20000,
        )
        time.sleep(2)

        comment_box = page.locator('.commentthread_entry_quotebox textarea').first
        if comment_box.count() > 0 and comment_box.is_visible():
            comment_text = self.texts.get("comment", random.choice(_COMMENTS))
            comment_box.fill(comment_text)
            time.sleep(1)
            post_btn = page.locator('.btn_green_white_innerfade.btn_small').first
            if post_btn.count() > 0:
                post_btn.click()
                time.sleep(2)
        else:
            logger.info(f"[Warmup] {self.login}: post_comment — поле комментария не найдено")

    def _quest_setup_profile_background(self, page: Page):
        """Настроить фон профиля (просто посетить страницу настройки)."""
        page.goto("https://steamcommunity.com/my/edit/background", wait_until="networkidle", timeout=20000)
        time.sleep(2)
        # Посещение страницы настройки фона засчитывается


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
