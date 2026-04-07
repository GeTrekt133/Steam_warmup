"""
Высокоуровневая обёртка над pyautogui + OCR + human_behavior.
Привязывается к конкретному окну Chrome и предоставляет удобный API.
"""
import time
import logging

import cv2
import numpy as np
import pyautogui

from chrome_launcher import ChromeInstance, ChromeLauncher
from human_behavior import HumanBehavior
from ocr_engine import OCREngine, TextBox, TemplateMatch

logger = logging.getLogger(__name__)


class ScreenAutomation:
    """
    Управление Chrome через компьютерное зрение.
    Все координаты — экранные (абсолютные).
    """

    def __init__(
        self,
        chrome: ChromeInstance,
        launcher: ChromeLauncher,
        human: HumanBehavior | None = None,
        ocr: OCREngine | None = None,
    ):
        self.chrome = chrome
        self.launcher = launcher
        self.human = human or HumanBehavior()
        self.ocr = ocr or OCREngine()
        self._window_rect: tuple[int, int, int, int] | None = None

    @property
    def window_rect(self) -> tuple[int, int, int, int]:
        """Получить текущие координаты окна Chrome (с кешем)."""
        if self._window_rect is None:
            self._window_rect = self.launcher.get_window_rect(self.chrome)
        return self._window_rect

    def refresh_window_rect(self) -> tuple[int, int, int, int] | None:
        """Принудительно обновить координаты окна."""
        self._window_rect = self.launcher.get_window_rect(self.chrome)
        return self._window_rect

    # ── Скриншоты ────────────────────────────────────────────────────────

    def screenshot(self, region: tuple[int, int, int, int] | None = None) -> np.ndarray:
        """
        Сделать скриншот окна Chrome (или его части).

        Args:
            region: (x, y, width, height) в координатах окна (не экранных).
                    Если None — весь Chrome.

        Returns:
            BGR numpy array
        """
        rect = self.window_rect
        if rect is None:
            raise RuntimeError("Окно Chrome не найдено")

        wx, wy, ww, wh = rect

        if region:
            rx, ry, rw, rh = region
            screen_region = (wx + rx, wy + ry, rw, rh)
        else:
            screen_region = (wx, wy, ww, wh)

        img = pyautogui.screenshot(region=screen_region)
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    def screenshot_content_area(self) -> np.ndarray:
        """
        Скриншот только контентной области (без заголовка Chrome и адресной строки).
        Примерно: от y=90 (под адресной строкой) до конца.
        """
        rect = self.window_rect
        if rect is None:
            raise RuntimeError("Окно Chrome не найдено")

        # Chrome toolbar ≈ 90px (title bar + address bar + bookmarks)
        toolbar_height = 90
        return self.screenshot(region=(0, toolbar_height, rect[2], rect[3] - toolbar_height))

    # ── Поиск элементов ──────────────────────────────────────────────────

    def find_text(
        self,
        text: str,
        fuzzy: bool = False,
        content_only: bool = True,
    ) -> tuple[int, int] | None:
        """
        Найти текст на экране и вернуть экранные координаты.

        Args:
            text: Искомый текст
            fuzzy: Нечёткий поиск
            content_only: Искать только в контентной области

        Returns:
            (screen_x, screen_y) или None
        """
        if content_only:
            img = self.screenshot_content_area()
            offset_y = 90  # toolbar
        else:
            img = self.screenshot()
            offset_y = 0

        box = self.ocr.find_text(img, text, fuzzy=fuzzy)
        if box is None:
            return None

        rect = self.window_rect
        screen_x = rect[0] + box.x
        screen_y = rect[1] + offset_y + box.y
        return screen_x, screen_y

    def find_text_regex(
        self,
        pattern: str,
        content_only: bool = True,
    ) -> tuple[int, int, str] | None:
        """
        Найти текст по regex, вернуть координаты и найденный текст.
        """
        if content_only:
            img = self.screenshot_content_area()
            offset_y = 90
        else:
            img = self.screenshot()
            offset_y = 0

        box = self.ocr.find_text_regex(img, pattern)
        if box is None:
            return None

        rect = self.window_rect
        screen_x = rect[0] + box.x
        screen_y = rect[1] + offset_y + box.y
        return screen_x, screen_y, box.text

    def find_template(
        self,
        template: str,
        multi_scale: bool = False,
        content_only: bool = True,
    ) -> tuple[int, int] | None:
        """
        Найти шаблон (кнопку/иконку) на экране.

        Args:
            template: Имя файла шаблона (из templates/) или путь
            multi_scale: Перебирать масштабы

        Returns:
            (screen_x, screen_y) или None
        """
        if content_only:
            img = self.screenshot_content_area()
            offset_y = 90
        else:
            img = self.screenshot()
            offset_y = 0

        if multi_scale:
            match = self.ocr.find_template_multi_scale(img, template)
        else:
            match = self.ocr.find_template(img, template)

        if match is None:
            return None

        rect = self.window_rect
        screen_x = rect[0] + match.x
        screen_y = rect[1] + offset_y + match.y
        return screen_x, screen_y

    def find_color_button(
        self,
        lower_hsv: tuple,
        upper_hsv: tuple,
        content_only: bool = True,
    ) -> tuple[int, int] | None:
        """Найти цветную кнопку по HSV цвету."""
        if content_only:
            img = self.screenshot_content_area()
            offset_y = 90
        else:
            img = self.screenshot()
            offset_y = 0

        result = self.ocr.find_color_region(img, lower_hsv, upper_hsv)
        if result is None:
            return None

        rect = self.window_rect
        screen_x = rect[0] + result[0]
        screen_y = rect[1] + offset_y + result[1]
        return screen_x, screen_y

    def read_code(self, pattern: str = r"\b[A-Z0-9]{5,6}\b") -> str | None:
        """Прочитать код подтверждения с экрана."""
        img = self.screenshot_content_area()
        return self.ocr.read_code(img, pattern)

    def read_all_text(self, content_only: bool = True) -> list[TextBox]:
        """Прочитать весь текст с экрана (для отладки)."""
        if content_only:
            img = self.screenshot_content_area()
        else:
            img = self.screenshot()
        return self.ocr.read_all(img)

    # ── Действия ─────────────────────────────────────────────────────────

    def click_text(self, text: str, fuzzy: bool = False) -> bool:
        """Найти текст и кликнуть по нему."""
        coords = self.find_text(text, fuzzy=fuzzy)
        if coords is None:
            logger.warning(f"Текст '{text}' не найден для клика")
            return False

        self.human.click(*coords)
        return True

    def click_template(self, template: str, multi_scale: bool = False) -> bool:
        """Найти шаблон и кликнуть по нему."""
        coords = self.find_template(template, multi_scale=multi_scale)
        if coords is None:
            logger.warning(f"Шаблон '{template}' не найден для клика")
            return False

        self.human.click(*coords)
        return True

    def click_at(self, x: int, y: int) -> None:
        """Кликнуть по экранным координатам."""
        self.human.click(x, y)

    def type_in_field(self, text: str, field_text: str | None = None) -> bool:
        """
        Ввести текст в поле.

        Args:
            text: Текст для ввода
            field_text: Текст рядом с полем (label) для поиска. Если None — печатает в текущее поле.
        """
        if field_text:
            coords = self.find_text(field_text)
            if coords is None:
                logger.warning(f"Поле '{field_text}' не найдено")
                return False
            # Кликаем чуть правее и ниже от label (на поле ввода)
            self.human.click(coords[0] + 100, coords[1] + 30)
            self.human.pause("before_type")

        self.human.type_text(text)
        return True

    def navigate(self, url: str) -> None:
        """Перейти по URL."""
        self.launcher.focus_window(self.chrome)
        time.sleep(0.3)
        self.human.navigate_to_url(url)

    def scroll_down(self, amount: int = 3) -> None:
        """Скроллить вниз."""
        self.human.random_scroll(self.window_rect)

    # ── Ожидание ─────────────────────────────────────────────────────────

    def wait_for_text(
        self,
        text: str,
        timeout: int = 30,
        interval: float = 2.0,
        fuzzy: bool = False,
    ) -> tuple[int, int] | None:
        """
        Ждать появления текста на экране.

        Args:
            text: Ожидаемый текст
            timeout: Таймаут в секундах
            interval: Интервал проверки

        Returns:
            (screen_x, screen_y) или None если таймаут
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            coords = self.find_text(text, fuzzy=fuzzy)
            if coords:
                logger.info(f"Текст '{text}' появился: {coords}")
                return coords
            time.sleep(interval)

        logger.warning(f"Таймаут ожидания текста '{text}' ({timeout}с)")
        return None

    def wait_for_template(
        self,
        template: str,
        timeout: int = 30,
        interval: float = 2.0,
    ) -> tuple[int, int] | None:
        """Ждать появления шаблона на экране."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            coords = self.find_template(template)
            if coords:
                logger.info(f"Шаблон '{template}' появился: {coords}")
                return coords
            time.sleep(interval)

        logger.warning(f"Таймаут ожидания шаблона '{template}' ({timeout}с)")
        return None

    def wait_for_page_load(self, timeout: int = 15) -> None:
        """Ждать загрузки страницы (простая эвристика)."""
        time.sleep(2)
        # Сравниваем скриншоты: если перестали меняться — загрузилась
        prev = self.screenshot()
        for _ in range(timeout // 2):
            time.sleep(2)
            curr = self.screenshot()
            diff = cv2.absdiff(prev, curr).mean()
            if diff < 1.0:  # страница стабильна
                return
            prev = curr

    # ── Отладка ──────────────────────────────────────────────────────────

    def debug_screenshot(self, filename: str = "debug_screen.png") -> None:
        """Сохранить скриншот для отладки."""
        img = self.screenshot()
        cv2.imwrite(filename, img)
        logger.info(f"Debug screenshot: {filename}")

    def debug_ocr(self, filename: str = "debug_ocr.png") -> None:
        """Сохранить скриншот с отмеченными текстовыми блоками."""
        img = self.screenshot_content_area()
        boxes = self.ocr.read_all(img)

        for box in boxes:
            cv2.rectangle(img, (box.x1, box.y1), (box.x2, box.y2), (0, 255, 0), 2)
            cv2.putText(img, f"{box.text} ({box.confidence:.2f})",
                       (box.x1, box.y1 - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

        cv2.imwrite(filename, img)
        logger.info(f"Debug OCR screenshot: {filename} ({len(boxes)} boxes)")
