"""
Модуль очеловечивания: движение мыши по Безье, вариативный набор текста,
естественные паузы, случайные действия.
"""
import math
import time
import random
import string
import logging
import ctypes

import pyautogui

logger = logging.getLogger(__name__)


def ensure_english_layout() -> None:
    """
    Переключить раскладку клавиатуры на English (US) в активном окне.
    Отправляет WM_INPUTLANGCHANGEREQUEST в foreground window (Chrome).
    """
    try:
        user32 = ctypes.windll.user32
        EN_US_HKL = 0x04090409  # English (US) keyboard layout handle

        # Загружаем раскладку в систему
        user32.LoadKeyboardLayoutW("00000409", 1)

        # Получаем активное окно (Chrome) и отправляем ему запрос на смену раскладки
        hwnd = user32.GetForegroundWindow()
        WM_INPUTLANGCHANGEREQUEST = 0x0050
        user32.PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, EN_US_HKL)
        time.sleep(0.15)

        # Проверяем: получаем thread id окна и его раскладку
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        current_hkl = user32.GetKeyboardLayout(tid)
        if current_hkl & 0xFFFF == 0x0409:
            logger.debug("Раскладка Chrome: EN-US — OK")
        else:
            logger.debug(f"Раскладка Chrome: {hex(current_hkl)}, пробую Alt+Shift")
            pyautogui.hotkey("alt", "shift")
            time.sleep(0.2)
    except Exception as e:
        logger.warning(f"Не удалось переключить раскладку: {e}")
        pyautogui.hotkey("alt", "shift")
        time.sleep(0.2)

# Отключаем встроенную паузу pyautogui (у нас своя)
pyautogui.PAUSE = 0
# Оставляем failsafe (переместить мышь в угол = аварийная остановка)
pyautogui.FAILSAFE = True


class HumanBehavior:
    """Имитация человеческого поведения при взаимодействии с UI."""

    def __init__(
        self,
        typing_speed: float = 120,     # мс между символами (среднее)
        typing_jitter: float = 40,     # разброс (σ)
        typo_chance: float = 0.04,     # шанс опечатки (4%)
        move_steps_range: tuple = (20, 40),  # шаги при движении мыши
        overshoot_chance: float = 0.15,      # шанс промаха мыши
    ):
        self.typing_speed = typing_speed
        self.typing_jitter = typing_jitter
        self.typo_chance = typo_chance
        self.move_steps_range = move_steps_range
        self.overshoot_chance = overshoot_chance

    # ── Движение мыши ────────────────────────────────────────────────────

    def mouse_move(self, to_x: int, to_y: int, from_xy: tuple[int, int] | None = None) -> None:
        """
        Плавное движение мыши по кривой Безье к целевой точке.
        Иногда с overshoot (промахом) и коррекцией.
        """
        if from_xy is None:
            from_x, from_y = pyautogui.position()
        else:
            from_x, from_y = from_xy

        # Overshoot: иногда промахиваемся и корректируем
        if random.random() < self.overshoot_chance:
            overshoot_x = to_x + random.randint(-15, 15)
            overshoot_y = to_y + random.randint(-15, 15)
            self._bezier_move(from_x, from_y, overshoot_x, overshoot_y)
            time.sleep(random.uniform(0.05, 0.15))
            self._bezier_move(overshoot_x, overshoot_y, to_x, to_y, steps_range=(8, 15))
        else:
            self._bezier_move(from_x, from_y, to_x, to_y)

    def _bezier_move(
        self,
        x0: int, y0: int,
        x1: int, y1: int,
        steps_range: tuple | None = None,
    ) -> None:
        """Движение по кубической кривой Безье с 2 контрольными точками."""
        if steps_range is None:
            steps_range = self.move_steps_range

        steps = random.randint(*steps_range)
        dist = math.hypot(x1 - x0, y1 - y0)

        # Контрольные точки: случайное отклонение перпендикулярно к направлению
        offset = dist * random.uniform(0.1, 0.4)
        angle = math.atan2(y1 - y0, x1 - x0)
        perp = angle + math.pi / 2 * random.choice([-1, 1])

        # Две контрольные точки
        cp1_x = x0 + (x1 - x0) * 0.3 + math.cos(perp) * offset * random.uniform(0.3, 1.0)
        cp1_y = y0 + (y1 - y0) * 0.3 + math.sin(perp) * offset * random.uniform(0.3, 1.0)
        cp2_x = x0 + (x1 - x0) * 0.7 + math.cos(perp) * offset * random.uniform(-0.3, 0.5)
        cp2_y = y0 + (y1 - y0) * 0.7 + math.sin(perp) * offset * random.uniform(-0.3, 0.5)

        for i in range(1, steps + 1):
            t = i / steps
            # Кубическая Безье
            u = 1 - t
            x = u**3 * x0 + 3 * u**2 * t * cp1_x + 3 * u * t**2 * cp2_x + t**3 * x1
            y = u**3 * y0 + 3 * u**2 * t * cp1_y + 3 * u * t**2 * cp2_y + t**3 * y1

            pyautogui.moveTo(int(x), int(y))

            # Вариативная скорость: медленнее в начале и конце (easing)
            base_delay = 0.008
            if t < 0.2 or t > 0.8:
                base_delay *= 1.5
            time.sleep(base_delay + random.uniform(0, 0.005))

    # ── Клик ─────────────────────────────────────────────────────────────

    def click(self, x: int, y: int, button: str = "left") -> None:
        """Human-like клик: переместить мышь → небольшая пауза → клик."""
        self.mouse_move(x, y)
        time.sleep(random.uniform(0.05, 0.2))

        # Длительность нажатия (люди не кликают мгновенно)
        pyautogui.mouseDown(button=button)
        time.sleep(random.uniform(0.04, 0.12))
        pyautogui.mouseUp(button=button)

    def double_click(self, x: int, y: int) -> None:
        """Двойной клик."""
        self.mouse_move(x, y)
        time.sleep(random.uniform(0.05, 0.15))
        pyautogui.doubleClick()

    # ── Набор текста ─────────────────────────────────────────────────────

    def type_text(self, text: str, field_xy: tuple[int, int] | None = None) -> None:
        """
        Human-like набор текста с вариативной скоростью и опечатками.

        Args:
            text: Текст для ввода
            field_xy: Если указано, сначала кликнет по полю
        """
        # Переключаем раскладку на английскую перед вводом
        ensure_english_layout()

        if field_xy:
            self.click(*field_xy)
            self.pause("before_type")

        for i, char in enumerate(text):
            # Опечатка: случайный символ → пауза → backspace → правильный
            if random.random() < self.typo_chance and char.isalnum():
                wrong_char = random.choice(self._nearby_keys(char))
                pyautogui.press(wrong_char)
                time.sleep(random.uniform(0.1, 0.3))  # "заметил ошибку"
                pyautogui.press("backspace")
                time.sleep(random.uniform(0.05, 0.15))

            # Набираем правильный символ
            pyautogui.press(char) if len(char) == 1 else pyautogui.hotkey(char)

            # Задержка: гаусс + дополнительная пауза перед спецсимволами
            delay_ms = max(30, random.gauss(self.typing_speed, self.typing_jitter))
            if char in "@#$%!.":
                delay_ms *= 1.5  # перед спецсимволами печатаем медленнее
            if i > 0 and text[i - 1] == " ":
                delay_ms *= 1.2  # после пробела чуть медленнее (новое слово)

            time.sleep(delay_ms / 1000)

    def _nearby_keys(self, char: str) -> list[str]:
        """Соседние клавиши для реалистичных опечаток."""
        keyboard_neighbors = {
            "q": "wa", "w": "qeas", "e": "wrd", "r": "eft", "t": "rgy",
            "y": "thu", "u": "yji", "i": "uko", "o": "ilp", "p": "o",
            "a": "qws", "s": "awdz", "d": "sefc", "f": "drgv", "g": "ftbh",
            "h": "gyjn", "j": "hukm", "k": "jil", "l": "kop",
            "z": "asx", "x": "zdc", "c": "xfv", "v": "cgb", "b": "vhn",
            "n": "bjm", "m": "nk",
            "1": "2q", "2": "13w", "3": "24e", "4": "35r", "5": "46t",
            "6": "57y", "7": "68u", "8": "79i", "9": "80o", "0": "9p",
        }
        lower = char.lower()
        neighbors = keyboard_neighbors.get(lower, string.ascii_lowercase)
        return list(neighbors)

    # ── Drag (перетаскивание) ────────────────────────────────────────────

    def drag(
        self,
        from_x: int, from_y: int,
        to_x: int, to_y: int,
        steps: int = 30,
    ) -> None:
        """Перетаскивание: mouse_move к началу, затем плавный drag мелкими шагами."""
        self.mouse_move(from_x, from_y)
        time.sleep(0.3)

        pyautogui.mouseDown()
        time.sleep(0.1)

        # Мелкие шаги по 2-3 пикселя для плавности
        dx = to_x - from_x
        dy = to_y - from_y
        total_steps = max(50, int((dx**2 + dy**2)**0.5 / 2))

        for i in range(1, total_steps + 1):
            t = i / total_steps
            x = from_x + dx * t
            y = from_y + dy * t
            pyautogui.moveTo(int(x), int(y), _pause=False)
            time.sleep(0.01)

        # Точно в цель
        pyautogui.moveTo(to_x, to_y, _pause=False)
        time.sleep(0.15)
        pyautogui.mouseUp()

    # ── Паузы ────────────────────────────────────────────────────────────

    def pause(self, context: str = "between_actions") -> None:
        """
        Естественная пауза в зависимости от контекста.

        Контексты:
            thinking     — "задумался" (1-4 сек)
            reading      — "читает текст" (2-8 сек)
            before_type  — перед вводом текста (0.5-1.5 сек)
            between_actions — между действиями (0.5-2 сек)
            short        — короткая пауза (0.2-0.6 сек)
        """
        delays = {
            "thinking":        (1.0, 4.0, 2.0, 0.8),   # min, max, μ, σ
            "reading":         (2.0, 8.0, 4.0, 1.5),
            "before_type":     (0.5, 1.5, 0.8, 0.3),
            "between_actions": (0.5, 2.0, 1.0, 0.4),
            "short":           (0.2, 0.6, 0.3, 0.1),
        }

        min_d, max_d, mu, sigma = delays.get(context, delays["between_actions"])
        delay = max(min_d, min(max_d, random.gauss(mu, sigma)))
        time.sleep(delay)

    # ── Случайные действия (шум) ─────────────────────────────────────────

    def random_mouse_wander(self, bounds: tuple[int, int, int, int] | None = None) -> None:
        """
        Случайное движение мыши в произвольную точку (имитация размышления).

        Args:
            bounds: (x, y, width, height) — область для блуждания
        """
        if bounds:
            x, y, w, h = bounds
            target_x = random.randint(x, x + w)
            target_y = random.randint(y, y + h)
        else:
            screen_w, screen_h = pyautogui.size()
            target_x = random.randint(100, screen_w - 100)
            target_y = random.randint(100, screen_h - 100)

        self.mouse_move(target_x, target_y)
        time.sleep(random.uniform(0.3, 1.0))

    def random_scroll(self, bounds: tuple[int, int, int, int] | None = None) -> None:
        """
        Случайный скролл (имитация чтения страницы).
        """
        if bounds:
            x, y, w, h = bounds
            # Скроллим в центре области
            center_x = x + w // 2
            center_y = y + h // 2
            self.mouse_move(center_x, center_y)
        else:
            # Скроллим в текущей позиции
            pass

        direction = random.choice([-1, 1])  # вверх или вниз
        amount = random.randint(1, 4)

        for _ in range(amount):
            pyautogui.scroll(direction * random.randint(1, 3))
            time.sleep(random.uniform(0.3, 0.8))

    def random_noise(self, bounds: tuple[int, int, int, int] | None = None) -> None:
        """
        Случайное "шумовое" действие: движение мыши, скролл, или просто пауза.
        Вызывай между ключевыми действиями для естественности.
        """
        action = random.choices(
            ["wander", "scroll", "pause"],
            weights=[0.3, 0.2, 0.5],
            k=1
        )[0]

        if action == "wander":
            self.random_mouse_wander(bounds)
        elif action == "scroll":
            self.random_scroll(bounds)
        else:
            self.pause("thinking")

    # ── Навигация ────────────────────────────────────────────────────────

    def navigate_to_url(self, url: str) -> None:
        """Вводит URL в адресную строку Chrome (Ctrl+L → type → Enter)."""
        ensure_english_layout()
        pyautogui.hotkey("ctrl", "l")
        time.sleep(random.uniform(0.3, 0.6))

        # Очищаем поле
        pyautogui.hotkey("ctrl", "a")
        time.sleep(random.uniform(0.1, 0.2))

        # Набираем URL (быстрее чем обычный текст)
        old_speed = self.typing_speed
        self.typing_speed = 50  # URL набираем быстрее
        self.type_text(url)
        self.typing_speed = old_speed

        time.sleep(random.uniform(0.2, 0.5))
        pyautogui.press("enter")

    def press_tab(self, count: int = 1) -> None:
        """Нажать Tab с паузой (переход между полями)."""
        for _ in range(count):
            pyautogui.press("tab")
            time.sleep(random.uniform(0.15, 0.4))
