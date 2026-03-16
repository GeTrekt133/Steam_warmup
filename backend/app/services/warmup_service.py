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
"""

import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from playwright.sync_api import sync_playwright, Page, Browser

from app.services.steam_guard import generate_steam_guard_code

logger = logging.getLogger(__name__)

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
                {"id": q.quest_id, "name": q.quest_name, "status": q.status, "error": q.error}
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
    ):
        self.login = login
        self.password = password
        self.shared_secret = shared_secret
        self.master_steam_id = master_steam_id
        self.proxy_config = proxy_config
        self.status = status
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

            # Выполняем квесты
            for i, (quest_id, quest_name) in enumerate(self.quests):
                qs = self.status.quests[i]
                qs.status = "running"
                self.status.current_quest = quest_name

                method = getattr(self, f"_quest_{quest_id}", None)
                if not method:
                    qs.status = "skipped"
                    qs.error = "Не реализован"
                    continue

                try:
                    logger.info(f"[Warmup] {self.login}: квест '{quest_name}'")
                    method(page)
                    qs.status = "done"
                except Exception as e:
                    logger.warning(f"[Warmup] {self.login}: квест '{quest_name}' ошибка: {e}")
                    qs.status = "error"
                    qs.error = str(e)[:200]

                # Пауза между квестами (имитация человека)
                time.sleep(random.uniform(1.5, 3.0))

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
