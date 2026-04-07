"""
Парсер hCaptcha заданий со страницы Steam.
Открывает Steam /join, кликает по hCaptcha, скриншотит задания.
Сохраняет: скриншоты + JSON с метаданными (текст задания, тип, время).

Использование:
    python captcha_collector.py --count 50
    python captcha_collector.py --count 100 --proxy user:pass@host:port
"""
import os
import re
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime

from playwright.sync_api import sync_playwright, Page, FrameLocator

logger = logging.getLogger(__name__)

STEAM_JOIN = "https://store.steampowered.com/join"
DEFAULT_DATASET_DIR = Path(__file__).parent / "captcha_dataset"
DATASET_DIR = DEFAULT_DATASET_DIR  # будет перезаписано в collect_captchas


def collect_captchas(count: int = 50, proxy: str | None = None, headless: bool = False, output_dir: str | None = None):
    """Собрать датасет hCaptcha заданий."""

    global DATASET_DIR
    DATASET_DIR = Path(output_dir) if output_dir else DEFAULT_DATASET_DIR
    DATASET_DIR.mkdir(exist_ok=True)
    metadata_file = DATASET_DIR / "metadata.jsonl"

    with sync_playwright() as pw:
        proxy_config = None
        if proxy:
            p = proxy.strip()
            if "@" in p:
                creds, host = p.rsplit("@", 1)
                user, pwd = creds.split(":", 1)
                proxy_config = {"server": f"http://{host}", "username": user, "password": pwd}
            else:
                proxy_config = {"server": f"http://{p}"}

        browser = pw.firefox.launch(headless=headless, proxy=proxy_config)
        collected = 0
        errors = 0
        in_session = 0  # счётчик внутри текущей сессии

        context = browser.new_context()
        page = context.new_page()

        while collected < count:
            try:
                # Перезагрузка каждые 10 фреймов или первый запуск
                if in_session == 0 or in_session >= 10:
                    logger.info(f"\n── Новая сессия (собрано {collected}/{count}) ──")
                    in_session = 0

                    # 1. Загрузить страницу
                    logger.info("[1] Загрузка Steam join...")
                    try:
                        page.goto(STEAM_JOIN, timeout=30_000, wait_until="networkidle")
                    except Exception:
                        pass
                    time.sleep(3)

                    # 2. Кликнуть hCaptcha чекбокс
                    logger.info("[2] Клик по hCaptcha чекбоксу...")
                    hcaptcha_clicked = _click_hcaptcha_checkbox(page)
                    if not hcaptcha_clicked:
                        logger.warning("hCaptcha чекбокс не найден")
                        errors += 1
                        time.sleep(3)
                        continue

                    time.sleep(3)

                # 3. Ждём challenge
                if in_session == 0:
                    logger.info("[3] Ожидание challenge...")
                    challenge_appeared = _wait_for_challenge(page, timeout=15)
                    if not challenge_appeared:
                        logger.info("Challenge не появился")
                        errors += 1
                        in_session = 10  # форсировать перезагрузку
                        continue

                # 4. Парсим задание (только frame)
                task_data = _parse_challenge(page, collected)

                if task_data:
                    with open(metadata_file, "a", encoding="utf-8") as f:
                        f.write(json.dumps(task_data, ensure_ascii=False) + "\n")

                    logger.info(f"  ✓ [{collected}] {task_data.get('prompt', '?')} "
                                f"({task_data.get('grid', '?')}, {task_data.get('images_count', '?')} img)")
                    collected += 1
                    in_session += 1

                    # Skip для следующего задания
                    if collected < count:
                        _click_skip(page)
                        time.sleep(2)
                        if not _challenge_visible(page):
                            in_session = 10  # форсировать перезагрузку
                else:
                    logger.warning("Не удалось спарсить challenge")
                    errors += 1
                    in_session = 10  # форсировать перезагрузку

            except Exception as e:
                logger.error(f"Ошибка: {e}")
                errors += 1
                in_session = 10  # форсировать перезагрузку
                time.sleep(3)

        context.close()

        browser.close()

    logger.info(f"\n══ Собрано: {collected}/{count} (ошибок: {errors}) ══")
    logger.info(f"Датасет: {DATASET_DIR}")


def _click_hcaptcha_checkbox(page: Page) -> bool:
    """Кликнуть по чекбоксу hCaptcha."""
    try:
        # hCaptcha живёт в iframe
        hcap_frame = page.frame_locator('iframe[src*="hcaptcha"]').first
        checkbox = hcap_frame.locator('#checkbox')
        if checkbox.count() > 0:
            checkbox.click(timeout=5000)
            return True
    except Exception:
        pass

    # Fallback: искать по другим селекторам
    try:
        frames = page.frames
        for frame in frames:
            if "hcaptcha" in (frame.url or ""):
                cb = frame.locator('#checkbox')
                if cb.count() > 0:
                    cb.click(timeout=5000)
                    return True
    except Exception:
        pass

    return False


def _wait_for_challenge(page: Page, timeout: int = 15) -> bool:
    """Ждать появления challenge iframe (задание с картинками)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _challenge_visible(page):
            return True
        time.sleep(1)
    return False


def _challenge_visible(page: Page) -> bool:
    """Проверить видно ли challenge (задание с картинками)."""
    try:
        # Challenge появляется в отдельном iframe
        challenge_frame = page.frame_locator('iframe[src*="hcaptcha.com/captcha"]')
        # Ищем prompt (текст задания)
        prompt = challenge_frame.locator('.prompt-text, .challenge-prompt')
        if prompt.count() > 0:
            return True
    except Exception:
        pass

    try:
        frames = page.frames
        for frame in frames:
            url = frame.url or ""
            if "hcaptcha.com" in url and "captcha" in url:
                prompt = frame.locator('.prompt-text, .challenge-prompt, .prompt-padding')
                if prompt.count() > 0:
                    return True
    except Exception:
        pass

    return False


def _parse_challenge(page: Page, index: int) -> dict | None:
    """Извлечь данные из challenge: текст задания, картинки."""
    try:
        # Найти challenge frame
        challenge_frame = None
        for frame in page.frames:
            url = frame.url or ""
            if "hcaptcha.com" in url and ("captcha" in url or "challenge" in url):
                challenge_frame = frame
                break

        if not challenge_frame:
            logger.warning("Challenge frame не найден")
            return None

        # Текст задания (prompt)
        prompt_text = ""
        try:
            prompt_el = challenge_frame.locator('.prompt-text').first
            if prompt_el.count() > 0:
                prompt_text = prompt_el.inner_text(timeout=3000)
        except Exception:
            pass

        if not prompt_text:
            try:
                prompt_el = challenge_frame.locator('.challenge-prompt, .prompt-padding').first
                if prompt_el.count() > 0:
                    prompt_text = prompt_el.inner_text(timeout=3000)
            except Exception:
                pass

        # Скриншот только challenge frame
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_name = f"challenge_{index:04d}_{timestamp}.png"

        try:
            challenge_frame.locator('.challenge-container, .task-grid, .challenge').first.screenshot(
                path=str(DATASET_DIR / screenshot_name),
                timeout=3000,
            )
        except Exception:
            # Fallback: скриншот всей страницы
            page.screenshot(path=str(DATASET_DIR / screenshot_name))
            logger.warning("Frame screenshot failed, saved full page")

        # Сетка картинок (3x3 или 4x4)
        grid_size = "unknown"
        images_count = 0
        try:
            task_images = challenge_frame.locator('.task-image, .image-wrapper, [class*="task"] img')
            images_count = task_images.count()
            if images_count == 9:
                grid_size = "3x3"
            elif images_count == 16:
                grid_size = "4x4"
            elif images_count > 0:
                grid_size = f"{images_count}"
        except Exception:
            pass

        return {
            "index": index,
            "timestamp": timestamp,
            "prompt": prompt_text.strip(),
            "grid": grid_size,
            "images_count": images_count,
            "screenshot": screenshot_name,
        }

    except Exception as e:
        logger.error(f"Ошибка парсинга challenge: {e}")
        return None


def _click_skip(page: Page):
    """Нажать кнопку Skip/Пропустить для следующего задания."""
    try:
        for frame in page.frames:
            url = frame.url or ""
            if "hcaptcha.com" in url and ("captcha" in url or "challenge" in url):
                # Ищем кнопку Skip
                skip_btn = frame.locator('text=Skip, text=skip, .refresh-button, [aria-label="Skip"], [class*="skip"]')
                if skip_btn.count() > 0:
                    skip_btn.first.click(timeout=3000)
                    logger.info("Skip нажат")
                    return

                # Fallback: кнопка с текстом
                for text in ["Skip", "skip", "Пропустить", "Next"]:
                    btn = frame.locator(f'text="{text}"')
                    if btn.count() > 0:
                        btn.first.click(timeout=3000)
                        logger.info(f"'{text}' нажат")
                        return

                # Fallback: refresh иконка
                refresh = frame.locator('.refresh, [class*="refresh"], [aria-label*="new"]')
                if refresh.count() > 0:
                    refresh.first.click(timeout=3000)
                    logger.info("Refresh нажат")
                    return
                break
    except Exception as e:
        logger.warning(f"Ошибка skip: {e}")


def _click_random_and_verify(page: Page):
    """Кликнуть по рандомной картинке и нажать verify для получения следующего задания."""
    import random

    try:
        for frame in page.frames:
            url = frame.url or ""
            if "hcaptcha.com" in url and ("captcha" in url or "challenge" in url):
                # Кликаем по рандомной картинке
                images = frame.locator('.task-image, .image-wrapper')
                count = images.count()
                if count > 0:
                    idx = random.randint(0, count - 1)
                    images.nth(idx).click(timeout=3000)
                    time.sleep(0.5)

                # Нажимаем verify/submit
                verify_btn = frame.locator('.button-submit, [class*="verify"], [class*="submit"]')
                if verify_btn.count() > 0:
                    verify_btn.first.click(timeout=3000)
                    time.sleep(2)
                break
    except Exception as e:
        logger.warning(f"Ошибка клика: {e}")


# ── Точка входа ──────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    ap = argparse.ArgumentParser(description="hCaptcha Dataset Collector")
    ap.add_argument("--count", type=int, default=50, help="Количество заданий для сбора")
    ap.add_argument("--proxy", default=None, help="Прокси (user:pass@host:port)")
    ap.add_argument("--headless", action="store_true", help="Без UI")
    ap.add_argument("--output", default=None, help="Папка для сохранения (по умолчанию captcha_dataset/)")
    args = ap.parse_args()

    collect_captchas(count=args.count, proxy=args.proxy, headless=args.headless, output_dir=args.output)
