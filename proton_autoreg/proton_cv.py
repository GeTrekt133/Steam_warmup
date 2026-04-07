"""
CV-логика для Proton Mail: регистрация и чтение почты через скриншоты + OCR.
Управляет обычным Chrome без CDP/Playwright.
"""
import re
import time
import random
import string
import logging

import cv2
import numpy as np
import pyautogui

from screen_automation import ScreenAutomation
from captcha_solver import solve_photo_direct, _find_piece_in_screenshot
from human_behavior import HumanBehavior
from captcha_solver import solve_screenshot

logger = logging.getLogger(__name__)

SIGNUP_URL = "https://account.proton.me/mail/signup"
INBOX_URL = "https://mail.proton.me/u/0/inbox"
OUTPUT_FILE = "proton_accounts.txt"


# ── Генераторы ───────────────────────────────────────────────────────────

def gen_username() -> str:
    length = random.randint(8, 12)
    num_letters = int(length * 0.7)
    num_digits = length - num_letters
    chars = (random.choices(string.ascii_lowercase, k=num_letters)
           + random.choices(string.digits, k=num_digits))
    random.shuffle(chars)
    if chars[0].isdigit():
        for i, c in enumerate(chars):
            if c.isalpha():
                chars[0], chars[i] = chars[i], chars[0]
                break
    return "".join(chars)


def gen_password(n: int = 16) -> str:
    pool = string.ascii_letters + string.digits + "!@#$%"
    pwd = (random.choice(string.ascii_uppercase)
         + random.choice(string.ascii_lowercase)
         + random.choice(string.digits)
         + random.choice("!@#$%")
         + "".join(random.choices(pool, k=n - 4)))
    return "".join(random.sample(pwd, len(pwd)))


# ── Proton CV ────────────────────────────────────────────────────────────

class ProtonCV:
    """Регистрация Proton Mail и чтение почты через компьютерное зрение."""

    def __init__(self, screen: ScreenAutomation, human: HumanBehavior | None = None):
        self.screen = screen
        self.human = human or screen.human

    # ── Утилита: template first, OCR fallback ───────────────────────────

    def _find_element(
        self,
        template: str | None = None,
        ocr_texts: list[str] | None = None,
        fuzzy: bool = True,
        offset_y: int = 0,
    ) -> tuple[int, int] | None:
        """
        Найти элемент: сначала template matching (быстро), потом OCR (fallback).

        Args:
            template: Имя файла шаблона (из templates/)
            ocr_texts: Список текстов для OCR fallback (пробуем по очереди)
            fuzzy: Нечёткий OCR поиск
            offset_y: Смещение вниз от найденного элемента (для клика на поле под label)

        Returns:
            (screen_x, screen_y) или None
        """
        # 1. Template matching (быстро, ~50мс)
        if template:
            coords = self.screen.find_template(template, multi_scale=True)
            if coords:
                logger.info(f"[ProtonCV] Найдено (template: {template})")
                return (coords[0], coords[1] + offset_y)

        # 2. OCR fallback (медленно, ~3-5с)
        if ocr_texts:
            for text in ocr_texts:
                coords = self.screen.find_text(text, fuzzy=fuzzy)
                if coords:
                    logger.info(f"[ProtonCV] Найдено (OCR: '{text}')")
                    return (coords[0], coords[1] + offset_y)

        return None

    def _click_element(
        self,
        template: str | None = None,
        ocr_texts: list[str] | None = None,
        fuzzy: bool = True,
        offset_y: int = 0,
        double: bool = False,
        retries: int = 5,
        retry_delay: float = 2.0,
    ) -> bool:
        """Найти элемент и кликнуть. Повторяет retries раз."""
        for attempt in range(retries):
            coords = self._find_element(template, ocr_texts, fuzzy, offset_y)
            if coords:
                if double:
                    self.human.double_click(*coords)
                else:
                    self.human.click(*coords)
                return True
            if attempt < retries - 1:
                time.sleep(retry_delay)
        return False

    def register(self, username: str, password: str) -> dict:
        """
        Зарегистрировать аккаунт Proton Mail через CV.

        Returns:
            {"ok": True/False, "email": "...", "password": "...", "msg": "..."}
        """
        email = f"{username}@proton.me"
        logger.info(f"[ProtonCV] Регистрация: {email}")

        try:
            # ── 1. Загрузка страницы ─────────────────────────────────
            logger.info("[ProtonCV] [1] Загрузка signup...")
            self.screen.navigate(SIGNUP_URL)
            self.screen.wait_for_page_load(timeout=20)
            self.human.pause("reading")
            self.screen.debug_screenshot("debug_cv_01_loaded.png")

            # ── 2. Выбор Free плана (двойной клик на карточку) ────────
            logger.info("[ProtonCV] [2] Free план...")
            clicked = self._click_element(
                template="free_text.png",
                ocr_texts=["Free"],
                fuzzy=False,
                double=True,
            )
            if clicked:
                logger.info("[ProtonCV]    OK (double click)")
            else:
                logger.warning("[ProtonCV]    Free план не найден, продолжаем")

            self.human.pause("between_actions")
            self.screen.wait_for_page_load(timeout=10)

            # ── 3. Username ──────────────────────────────────────────
            logger.info(f"[ProtonCV] [3] Username: {username}")
            self._fill_username(username)
            self.human.pause("between_actions")
            self.screen.debug_screenshot("debug_cv_03_username.png")

            # ── 4. Пароль ────────────────────────────────────────────
            logger.info("[ProtonCV] [4] Пароль...")
            self._fill_password(password)
            self.human.pause("between_actions")
            self.screen.debug_screenshot("debug_cv_04_password.png")

            # ── 5. Нажать кнопку Submit ───────────────────────────────
            logger.info("[ProtonCV] [5] Кнопка Submit...")
            self._click_element(
                template="start_using_btn.png",
                ocr_texts=["Start using Proton Mail now", "Начать использовать Proton Mail"],
            )
            time.sleep(3)
            self.screen.debug_screenshot("debug_cv_05_after_submit.png")

            # ── 6. Закрыть upsell "No, thanks" ──────────────────────
            logger.info("[ProtonCV] [6] Upsell...")
            self._click_element(
                template="no_thanks_text.png",
                ocr_texts=["No, thanks", "Нет, спасибо", "No thanks"],
                retries=3,
            )
            time.sleep(3)
            self.screen.debug_screenshot("debug_cv_06_after_upsell.png")

            # ── 7. Капча ─────────────────────────────────────────────
            logger.info("[ProtonCV] [7] Решение капчи...")
            captcha_solved = self._handle_captcha(max_attempts=5)
            if captcha_solved:
                logger.info("[ProtonCV] Капча решена!")
            else:
                logger.warning("[ProtonCV] Капча не решена")

            time.sleep(3)
            self.screen.debug_screenshot("debug_cv_07_after_captcha.png")

            # ── 8. Recovery Kit: скачать PDF + чекбокс + Continue ────
            logger.info("[ProtonCV] [8] Recovery Kit...")
            self._handle_recovery_kit()
            time.sleep(3)
            self.screen.debug_screenshot("debug_cv_08_after_recovery.png")

            # ── 9. Display Name + Continue ───────────────────────────
            logger.info("[ProtonCV] [9] Display Name...")
            coords = self.screen.find_template("continue_btn.png", multi_scale=True)
            if coords:
                self.human.click(*coords)
                logger.info("[ProtonCV] Display Name Continue (template)")
            else:
                self._click_purple_button()
            time.sleep(15)

            # ── 10. Пост-регистрационные экраны ──────────────────────
            logger.info("[ProtonCV] [10] Post-signup кнопки...")
            post_steps = [
                ("get_started_btn.png", "Let's get started"),
                ("maybe_later_btn.png", "Maybe later (btn)"),
                ("next_btn.png", "Next"),
                ("use_btn.png", "Use this"),
                ("dont_show_again_btn.png", "Don't show again"),
                ("maybe_later_text.png", "Maybe later (text)"),
            ]
            for tmpl, name in post_steps:
                time.sleep(2)
                self.screen.debug_screenshot(f"debug_cv_10_{tmpl.replace('.png','')}.png")
                coords = self.screen.find_template(tmpl, multi_scale=True)
                if coords:
                    self.human.click(*coords)
                    logger.info(f"[ProtonCV] {name} — нажат")
                    time.sleep(2)
                else:
                    logger.warning(f"[ProtonCV] {name} — не найден, пропуск")

            self.screen.debug_screenshot("debug_cv_final.png")
            logger.info("[ProtonCV] Регистрация завершена!")
            return {"ok": True, "email": email, "password": password}

        except Exception as e:
            logger.error(f"[ProtonCV] Ошибка: {e}", exc_info=True)
            self.screen.debug_screenshot("debug_cv_error.png")
            return {"ok": False, "email": email, "password": password, "msg": str(e)}

    def _fill_username(self, username: str) -> None:
        """Заполнить поле username (клик на поле под label)."""
        # Template first (клик ниже label — на поле ввода), OCR fallback
        found = self._find_element(
            template="username_text.png",
            ocr_texts=["Username", "пользователя", "email"],
            offset_y=40,  # клик ниже label — на само поле
        )

        if found:
            self.human.click(*found)
        else:
            # Fallback: Tab
            self.human.press_tab(2)

        self.human.pause("before_type")
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)
        self.human.type_text(username)

    def _fill_password(self, password: str) -> None:
        """Заполнить поля пароля (клик на поле под label)."""
        # Template first, OCR fallback
        found = self._find_element(
            template="password_text.png",
            ocr_texts=["Пароль", "Password"],
            offset_y=40,  # клик ниже label — на само поле
        )

        if found:
            self.human.click(*found)
        else:
            self.human.press_tab()

        self.human.pause("before_type")
        self.human.type_text(password)
        self.human.pause("short")

        # Confirm password — Tab из поля пароля
        self.human.press_tab()

        self.human.pause("before_type")
        self.human.type_text(password)

    def _click_purple_button(self) -> bool:
        """Найти и нажать фиолетовую кнопку (template first)."""
        return self._click_element(
            template="start_using_btn.png",
            ocr_texts=["Start using Proton Mail now", "Начать использовать Proton Mail"],
            retries=3,
        )

    def _handle_captcha(self, max_attempts: int = 5) -> bool:
        """
        Решить puzzle капчу через U-Net + pyautogui drag.
        Находим фото пазла на экране, вырезаем, подаём в U-Net напрямую.
        """
        for attempt in range(max_attempts):
            self.human.pause("between_actions")
            self.screen.debug_screenshot(f"debug_cv_captcha_{attempt}.png")

            full_img = self.screen.screenshot()

            # Проверяем наличие капчи (на content area)
            content_img = full_img[90:, :]
            if not self._detect_captcha_presence(content_img):
                logger.info(f"[ProtonCV] Капча не обнаружена (попытка {attempt})")
                if attempt > 0:
                    return True  # Капча была решена на прошлой попытке
                time.sleep(3)
                continue

            logger.info(f"[ProtonCV] Капча обнаружена, попытка {attempt + 1}")

            # Вырезаем фото пазла из ПОЛНОГО скриншота
            photo, photo_offset = self._extract_puzzle_photo(full_img)
            if photo is None:
                logger.warning("[ProtonCV] Не удалось вырезать фото пазла")
                time.sleep(2)
                continue

            px_off, py_off = photo_offset
            photo_h, photo_w = photo.shape[:2]
            cv2.imwrite(f"debug_captcha_photo_{attempt}.png", photo)

            # U-Net: найти тень (куда тянуть)
            result = solve_photo_direct(photo)
            if result is None:
                logger.warning("[ProtonCV] U-Net не нашёл тень")
                time.sleep(2)
                continue

            hole_x, hole_y, confidence = result
            if confidence < 0.1:
                logger.warning(f"[ProtonCV] Confidence слишком низкий: {confidence:.3f}")
                continue

            # Piece всегда в верхнем левом углу фото — захардкожено
            piece_x = 29
            piece_y = 36

            # Пересчёт в экранные координаты (offset от полного скриншота, без toolbar)
            rect = self.screen.window_rect

            src_x = rect[0] + px_off + piece_x
            src_y = rect[1] + py_off + piece_y
            dst_x = rect[0] + px_off + hole_x
            dst_y = rect[1] + py_off + hole_y

            logger.info(f"[ProtonCV] Piece: ({piece_x},{piece_y}) Hole: ({hole_x},{hole_y})")
            logger.info(f"[ProtonCV] Drag: ({src_x},{src_y}) → ({dst_x},{dst_y})")

            # Debug: рисуем стрелку на фото
            debug = photo.copy()
            cv2.circle(debug, (piece_x, piece_y), 8, (0, 255, 0), 2)
            cv2.circle(debug, (hole_x, hole_y), 8, (0, 0, 255), 2)
            cv2.arrowedLine(debug, (piece_x, piece_y), (hole_x, hole_y), (0, 200, 255), 2)
            cv2.imwrite(f"debug_captcha_solution_{attempt}.png", debug)

            # Перетаскиваем
            self.human.drag(src_x, src_y, dst_x, dst_y)
            time.sleep(1.5)

            # Кликаем "Next" / Continue
            self._click_element(
                template="continue_btn.png",
                ocr_texts=["Next", "Далее"],
                retries=2,
                retry_delay=1.0,
            )
            time.sleep(5)

            # Если drag прошёл — капча решена, выходим
            return True

        return False

    def _extract_puzzle_photo(self, full_screenshot: np.ndarray) -> tuple[np.ndarray | None, tuple[int, int]]:
        """
        Вырезать фото пазла с piece из ПОЛНОГО скриншота окна Chrome.
        Координаты от полного скриншота: top=345, bottom=150, left=450, right=450.
        Возвращает (photo_bgr, (offset_x, offset_y)) в координатах полного скриншота.
        """
        h, w = full_screenshot.shape[:2]

        # Отступы от краёв полного скриншота
        left = 450
        right = 450
        top = 345      # включает piece в верхнем левом углу
        bottom = 150

        x1 = left
        y1 = top
        x2 = w - right
        y2 = h - bottom

        if x2 <= x1 or y2 <= y1:
            logger.warning(f"[ProtonCV] Некорректные координаты: ({x1},{y1})-({x2},{y2})")
            return None, (0, 0)

        photo = full_screenshot[y1:y2, x1:x2]
        logger.info(f"[ProtonCV] Puzzle photo: ({x1},{y1}) {x2-x1}x{y2-y1}")
        return photo, (x1, y1)

    def _detect_captcha_presence(self, img: np.ndarray) -> bool:
        """Проверить есть ли капча на скриншоте."""
        # Ищем текст "CAPTCHA" или "puzzle" или "verify"
        boxes = self.screen.ocr.read_all(img)
        for box in boxes:
            text_lower = box.text.lower()
            if any(kw in text_lower for kw in ["captcha", "puzzle", "verify you", "human"]):
                return True

        # Ищем характерный паттерн: большая прямоугольная область с фото
        # (Proton puzzle captcha)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            aspect = w / max(h, 1)
            if w > 300 and h > 250 and 0.8 < aspect < 1.5:
                return True

        return False

    def _handle_recovery_kit(self) -> None:
        """Скачать Recovery PDF, кликнуть чекбокс, нажать Continue."""
        # Закрыть "Save password?" от Chrome если есть
        self.screen.click_text("Never", fuzzy=True)
        time.sleep(1)

        # Ждём появления страницы Recovery Kit
        self.screen.wait_for_text("Secure your account", timeout=15, fuzzy=True)
        self.human.pause("reading")

        # 1. Скачать PDF
        self._click_element(
            template="download_secret.png",
            ocr_texts=["Download PDF"],
            retries=3,
        )
        time.sleep(3)

        # 2. Чекбокс "I understand..."
        self._click_element(
            template="checkbox.png",
            ocr_texts=["I understand", "Я понимаю"],
            retries=3,
        )
        time.sleep(1)

        # 3. Continue
        self._click_element(
            template="continue_btn.png",
            ocr_texts=["Continue", "Продолжить"],
            retries=3,
        )

    def _handle_post_signup(self) -> None:
        """Обработать пост-регистрационные экраны (Recovery kit, Display name, etc)."""
        for _ in range(15):
            time.sleep(2)
            self.screen.debug_screenshot("debug_cv_post_signup.png")

            # "Start using Proton Mail now" — template matching
            coords = self.screen.find_template("start_using_btn.png", multi_scale=True)
            if coords:
                self.human.click(*coords)
                logger.info("[ProtonCV] Нажали 'Start using' (template)")
                time.sleep(3)
                return

            # Fallback: по тексту
            for text in ["Start using", "Начать использовать"]:
                if self.screen.click_text(text, fuzzy=True):
                    logger.info(f"[ProtonCV] Нажали '{text}'")
                    time.sleep(3)
                    return

            # Recovery Kit — чекбокс + Continue
            if self.screen.click_text("Recovery", fuzzy=True):
                time.sleep(0.5)
                self.screen.click_text("understand", fuzzy=True)
                time.sleep(0.5)
                self.screen.click_text("Continue", fuzzy=True) or self.screen.click_text("Продолжить", fuzzy=True)
                time.sleep(2)
                continue

            # "No thanks" / "Нет, спасибо" (upsell)
            for dismiss in ["No thanks", "Нет, спасибо", "нет спасибо"]:
                if self.screen.click_text(dismiss, fuzzy=True):
                    time.sleep(2)
                    break

            # "Continue" / "Продолжить" / "Next" / "Далее"
            for btn in ["Continue", "Продолжить", "Next", "Далее"]:
                if self.screen.click_text(btn, fuzzy=True):
                    time.sleep(2)
                    break
            if self.screen.click_text("Next", fuzzy=True):
                time.sleep(2)
                continue

            # Проверяем может уже inbox
            img = self.screen.screenshot_content_area()
            boxes = self.screen.ocr.read_all(img)
            for box in boxes:
                if any(kw in box.text.lower() for kw in ["inbox", "compose", "new message"]):
                    return

            break

    def _wait_for_success(self, timeout: int = 120) -> bool:
        """Ждать пока откроется inbox (признак успешной регистрации)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            img = self.screen.screenshot_content_area()
            boxes = self.screen.ocr.read_all(img)

            for box in boxes:
                text_lower = box.text.lower()
                if any(kw in text_lower for kw in ["inbox", "compose", "new message", "getting started"]):
                    return True

            # Проверяем URL (если видна адресная строка)
            url_img = self.screen.screenshot(region=(200, 30, 800, 30))
            url_boxes = self.screen.ocr.read_all(url_img)
            for box in url_boxes:
                if "mail" in box.text.lower() and "signup" not in box.text.lower():
                    return True

            time.sleep(3)

        return False

    # ── Чтение почты ─────────────────────────────────────────────────────

    def read_email_code(
        self,
        subject_keywords: list[str],
        code_pattern: str = r"\b[A-Z0-9]{5,6}\b",
        timeout: int = 120,
    ) -> str | None:
        """
        Открыть inbox Proton, найти письмо по теме, извлечь код.

        Args:
            subject_keywords: Ключевые слова в теме письма (["Steam", "Guard"])
            code_pattern: Regex для поиска кода
            timeout: Таймаут ожидания письма

        Returns:
            Найденный код или None
        """
        logger.info(f"[ProtonCV] Чтение кода из почты (keywords={subject_keywords})")

        # Переходим в inbox
        self.screen.navigate(INBOX_URL)
        self.screen.wait_for_page_load(timeout=15)
        self.human.pause("reading")

        deadline = time.time() + timeout

        while time.time() < deadline:
            self.screen.debug_screenshot("debug_cv_inbox.png")

            # Ищем письмо с нужными ключевыми словами
            img = self.screen.screenshot_content_area()
            boxes = self.screen.ocr.read_all(img)

            for box in boxes:
                text_lower = box.text.lower()
                if any(kw.lower() in text_lower for kw in subject_keywords):
                    logger.info(f"[ProtonCV] Найдено письмо: '{box.text}'")

                    # Кликаем на письмо
                    rect = self.screen.window_rect
                    screen_x = rect[0] + box.x
                    screen_y = rect[1] + 90 + box.y
                    self.human.click(screen_x, screen_y)
                    time.sleep(3)

                    # Читаем содержимое письма
                    email_img = self.screen.screenshot_content_area()
                    code = self.screen.ocr.read_code(email_img, code_pattern)

                    if code:
                        logger.info(f"[ProtonCV] Код найден: {code}")
                        return code

                    # Если код не найден в видимой части — скроллим
                    for _ in range(3):
                        self.screen.scroll_down()
                        time.sleep(1)
                        email_img = self.screen.screenshot_content_area()
                        code = self.screen.ocr.read_code(email_img, code_pattern)
                        if code:
                            logger.info(f"[ProtonCV] Код найден (после скролла): {code}")
                            return code

                    # Код не найден в этом письме, пробуем другие
                    # Возвращаемся в inbox
                    self.screen.navigate(INBOX_URL)
                    time.sleep(3)
                    break

            # Письмо не найдено — обновляем inbox
            remaining = int(deadline - time.time())
            logger.info(f"[ProtonCV] Письмо не найдено, обновляю inbox ({remaining}с)")
            pyautogui.press("f5")
            time.sleep(5)

        logger.warning("[ProtonCV] Таймаут: код не найден")
        return None

    def read_confirmation_link(
        self,
        subject_keywords: list[str],
        link_pattern: str = r"https?://store\.steampowered\.com/\S+",
        timeout: int = 120,
    ) -> str | None:
        """
        Открыть inbox, найти письмо, извлечь ссылку подтверждения.
        Для Steam регистрации (подтверждение email).
        """
        logger.info(f"[ProtonCV] Чтение ссылки из почты (keywords={subject_keywords})")

        self.screen.navigate(INBOX_URL)
        self.screen.wait_for_page_load(timeout=15)
        self.human.pause("reading")

        deadline = time.time() + timeout

        while time.time() < deadline:
            img = self.screen.screenshot_content_area()
            boxes = self.screen.ocr.read_all(img)

            for box in boxes:
                text_lower = box.text.lower()
                if any(kw.lower() in text_lower for kw in subject_keywords):
                    logger.info(f"[ProtonCV] Найдено письмо: '{box.text}'")

                    # Кликаем
                    rect = self.screen.window_rect
                    self.human.click(rect[0] + box.x, rect[1] + 90 + box.y)
                    time.sleep(3)

                    # Ищем ссылку
                    email_img = self.screen.screenshot_content_area()
                    link_box = self.screen.ocr.find_text_regex(email_img, link_pattern)
                    if link_box:
                        logger.info(f"[ProtonCV] Ссылка найдена: {link_box.text}")
                        return link_box.text

                    # Скроллим если не видно
                    for _ in range(3):
                        self.screen.scroll_down()
                        time.sleep(1)
                        email_img = self.screen.screenshot_content_area()
                        link_box = self.screen.ocr.find_text_regex(email_img, link_pattern)
                        if link_box:
                            return link_box.text

                    break

            remaining = int(deadline - time.time())
            logger.info(f"[ProtonCV] Ссылка не найдена, обновляю inbox ({remaining}с)")
            pyautogui.press("f5")
            time.sleep(5)

        return None
