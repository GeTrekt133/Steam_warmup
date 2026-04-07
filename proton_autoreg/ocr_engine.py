"""
OCR и template matching для распознавания UI элементов на скриншотах.
Использует EasyOCR для текста и OpenCV для шаблонов.
"""
import re
import logging
from pathlib import Path
from dataclasses import dataclass

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Ленивая загрузка EasyOCR (тяжёлый импорт)
_reader = None


def _get_reader():
    """Ленивая инициализация EasyOCR reader."""
    global _reader
    if _reader is None:
        import easyocr
        logger.info("Загрузка EasyOCR модели...")
        _reader = easyocr.Reader(["en", "ru"], gpu=True, verbose=False)
        logger.info("EasyOCR загружен")
    return _reader


@dataclass
class TextBox:
    """Найденный текст с координатами."""
    text: str
    x: int          # центр X
    y: int          # центр Y
    x1: int         # left
    y1: int         # top
    x2: int         # right
    y2: int         # bottom
    confidence: float


@dataclass
class TemplateMatch:
    """Результат template matching."""
    x: int          # центр X
    y: int          # центр Y
    confidence: float
    width: int
    height: int


class OCREngine:
    """Распознавание текста и поиск UI элементов."""

    def __init__(self, templates_dir: Path | None = None):
        self.templates_dir = templates_dir or Path(__file__).parent / "templates"
        self._template_cache: dict[str, np.ndarray] = {}

    # ── OCR ───────────────────────────────────────────────────────────────

    def read_all(self, screenshot: np.ndarray) -> list[TextBox]:
        """
        Распознать весь текст на скриншоте.

        Args:
            screenshot: BGR или RGB numpy array

        Returns:
            Список TextBox с координатами и текстом
        """
        reader = _get_reader()
        results = reader.readtext(screenshot)

        boxes = []
        for bbox, text, confidence in results:
            # bbox = [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
            x1 = int(min(p[0] for p in bbox))
            y1 = int(min(p[1] for p in bbox))
            x2 = int(max(p[0] for p in bbox))
            y2 = int(max(p[1] for p in bbox))
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2

            boxes.append(TextBox(
                text=text, x=cx, y=cy,
                x1=x1, y1=y1, x2=x2, y2=y2,
                confidence=confidence
            ))

        return boxes

    def find_text(
        self,
        screenshot: np.ndarray,
        text: str,
        fuzzy: bool = False,
        min_confidence: float = 0.3,
    ) -> TextBox | None:
        """
        Найти текст на скриншоте и вернуть его координаты.

        Args:
            screenshot: BGR/RGB numpy array
            text: Текст для поиска
            fuzzy: Нечёткое совпадение
            min_confidence: Минимальная уверенность OCR
        """
        boxes = self.read_all(screenshot)
        text_lower = text.lower()

        best_match = None
        best_score = 0

        for box in boxes:
            if box.confidence < min_confidence:
                continue

            box_text = box.text.lower()

            if fuzzy:
                # Нечёткое совпадение: проверяем содержание подстроки
                if text_lower in box_text or box_text in text_lower:
                    score = box.confidence
                else:
                    score = self._similarity(text_lower, box_text) * box.confidence
                    if score < 0.4:
                        continue
            else:
                # Точное совпадение (подстрока)
                if text_lower not in box_text:
                    continue
                score = box.confidence

            if score > best_score:
                best_score = score
                best_match = box

        if best_match:
            logger.debug(f"Текст '{text}' найден: ({best_match.x}, {best_match.y}) conf={best_match.confidence:.2f}")
        else:
            logger.debug(f"Текст '{text}' не найден")

        return best_match

    def find_text_regex(
        self,
        screenshot: np.ndarray,
        pattern: str,
        min_confidence: float = 0.3,
    ) -> TextBox | None:
        """
        Найти текст по regex паттерну.

        Args:
            pattern: Регулярное выражение (например r"\\d{5,6}" для кода)
        """
        boxes = self.read_all(screenshot)
        regex = re.compile(pattern, re.IGNORECASE)

        for box in boxes:
            if box.confidence < min_confidence:
                continue
            if regex.search(box.text):
                logger.debug(f"Regex '{pattern}' match: '{box.text}' at ({box.x}, {box.y})")
                return box

        logger.debug(f"Regex '{pattern}' не найден")
        return None

    def read_code(
        self,
        screenshot: np.ndarray,
        pattern: str = r"\b[A-Z0-9]{5,6}\b",
    ) -> str | None:
        """
        Найти код подтверждения на скриншоте.

        Args:
            pattern: Regex для кода (по умолчанию 5-6 символов A-Z0-9)
        """
        boxes = self.read_all(screenshot)
        regex = re.compile(pattern)

        for box in boxes:
            match = regex.search(box.text)
            if match:
                code = match.group(0)
                logger.info(f"Код найден: {code} (confidence={box.confidence:.2f})")
                return code

        return None

    # ── Template Matching ─────────────────────────────────────────────────

    def find_template(
        self,
        screenshot: np.ndarray,
        template: str | np.ndarray,
        threshold: float = 0.8,
        scales: list[float] | None = None,
    ) -> TemplateMatch | None:
        """
        Найти шаблон на скриншоте.

        Args:
            screenshot: BGR numpy array
            template: Путь к файлу шаблона или numpy array
            threshold: Порог совпадения (0-1)
            scales: Масштабы для мультимасштабного поиска
        """
        # Загружаем шаблон
        if isinstance(template, str):
            tmpl = self._load_template(template)
        else:
            tmpl = template

        if tmpl is None:
            return None

        # Конвертируем в grayscale
        if len(screenshot.shape) == 3:
            gray_screen = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        else:
            gray_screen = screenshot

        if len(tmpl.shape) == 3:
            gray_tmpl = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
        else:
            gray_tmpl = tmpl

        # Мультимасштабный поиск
        if scales is None:
            scales = [1.0]  # по умолчанию только оригинальный размер

        best_val = 0
        best_loc = None
        best_size = None

        for scale in scales:
            if scale != 1.0:
                w = int(gray_tmpl.shape[1] * scale)
                h = int(gray_tmpl.shape[0] * scale)
                if w < 10 or h < 10:
                    continue
                scaled = cv2.resize(gray_tmpl, (w, h))
            else:
                scaled = gray_tmpl

            # Проверяем что шаблон не больше скриншота
            if scaled.shape[0] > gray_screen.shape[0] or scaled.shape[1] > gray_screen.shape[1]:
                continue

            result = cv2.matchTemplate(gray_screen, scaled, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val > best_val:
                best_val = max_val
                best_loc = max_loc
                best_size = (scaled.shape[1], scaled.shape[0])

        logger.info(f"Template best: conf={best_val:.3f} loc={best_loc} size={best_size} threshold={threshold}")

        if best_val >= threshold and best_loc and best_size:
            cx = best_loc[0] + best_size[0] // 2
            cy = best_loc[1] + best_size[1] // 2
            logger.info(f"Template FOUND: ({cx}, {cy}) confidence={best_val:.3f}")
            return TemplateMatch(
                x=cx, y=cy,
                confidence=best_val,
                width=best_size[0], height=best_size[1],
            )

        logger.warning(f"Template NOT FOUND (best={best_val:.3f}, threshold={threshold})")
        return None

    def find_template_multi_scale(
        self,
        screenshot: np.ndarray,
        template: str | np.ndarray,
        threshold: float = 0.65,
    ) -> TemplateMatch | None:
        """Template matching с автоматическим перебором масштабов."""
        scales = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 2.0]
        return self.find_template(screenshot, template, threshold, scales)

    def _load_template(self, name: str) -> np.ndarray | None:
        """Загружает шаблон из кеша или файла."""
        if name in self._template_cache:
            return self._template_cache[name]

        # Пробуем как путь
        path = Path(name)
        if not path.is_absolute():
            path = self.templates_dir / name

        if not path.exists():
            logger.error(f"Шаблон не найден: {path}")
            return None

        img = cv2.imread(str(path))
        if img is None:
            logger.error(f"Не удалось загрузить: {path}")
            return None

        self._template_cache[name] = img
        return img

    # ── Утилиты ───────────────────────────────────────────────────────────

    @staticmethod
    def _similarity(s1: str, s2: str) -> float:
        """Простое расстояние Левенштейна, нормализованное в [0,1]."""
        if not s1 or not s2:
            return 0.0
        len1, len2 = len(s1), len(s2)
        matrix = [[0] * (len2 + 1) for _ in range(len1 + 1)]
        for i in range(len1 + 1):
            matrix[i][0] = i
        for j in range(len2 + 1):
            matrix[0][j] = j
        for i in range(1, len1 + 1):
            for j in range(1, len2 + 1):
                cost = 0 if s1[i - 1] == s2[j - 1] else 1
                matrix[i][j] = min(
                    matrix[i - 1][j] + 1,
                    matrix[i][j - 1] + 1,
                    matrix[i - 1][j - 1] + cost,
                )
        dist = matrix[len1][len2]
        return 1.0 - dist / max(len1, len2)

    @staticmethod
    def find_color_region(
        screenshot: np.ndarray,
        lower_hsv: tuple, upper_hsv: tuple,
        min_area: int = 500,
    ) -> tuple[int, int] | None:
        """
        Найти область по цвету (HSV).
        Полезно для цветных кнопок (зелёная "Create", синяя "Sign In").
        """
        hsv = cv2.cvtColor(screenshot, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(lower_hsv), np.array(upper_hsv))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return None

        # Самый большой контур
        cnt = max(contours, key=cv2.contourArea)
        if cv2.contourArea(cnt) < min_area:
            return None

        M = cv2.moments(cnt)
        if M["m00"] == 0:
            return None

        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        return cx, cy
