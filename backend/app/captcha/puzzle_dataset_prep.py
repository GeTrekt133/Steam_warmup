# -*- coding: utf-8 -*-
"""
Подготовка датасета для обучения сегментационной модели пазл-капчи.

Этапы:
  1. Вырезать фоновое изображение из полного скриншота капчи
  2. Автоматически сгенерировать бинарные маски теней (OpenCV)
  3. Визуальная проверка масок (GUI-просмотрщик)

Использование:
  # Шаг 1+2: вырезать фон + сгенерировать маски
  python -m app.captcha.puzzle_dataset_prep crop  C:/path/to/screenshots
  python -m app.captcha.puzzle_dataset_prep masks

  # Шаг 3: визуальная проверка (Enter=OK, D=плохая, Q=выход)
  python -m app.captcha.puzzle_dataset_prep review
"""

import sys
import os
import json
from pathlib import Path
from glob import glob

import cv2
import numpy as np

# ── Пути ──────────────────────────────────────────────────────────────
DATASET_DIR = Path(__file__).resolve().parents[3] / "datasets" / "puzzle"
IMAGES_DIR = DATASET_DIR / "images"
MASKS_DIR = DATASET_DIR / "masks"
BAD_LIST = DATASET_DIR / "bad_masks.json"

# ── Координаты обрезки (фиксированные для скриншотов 682×600) ────────
# Определены эмпирически: фото занимает rows 89-438, cols 156-525
CROP_TOP = 89
CROP_BOTTOM = 439  # exclusive
CROP_LEFT = 156
CROP_RIGHT = 526   # exclusive
CROP_H = CROP_BOTTOM - CROP_TOP   # 350
CROP_W = CROP_RIGHT - CROP_LEFT   # 370


def crop_screenshots(src_dir: str) -> None:
    """
    Шаг 1: вырезать фоновые изображения из полных скриншотов капчи.
    Сохраняет в datasets/puzzle/images/.
    """
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    src_path = Path(src_dir)
    files = sorted(src_path.glob("captcha_*.png"))
    if not files:
        print(f"Не найдено captcha_*.png в {src_dir}")
        return

    count = 0
    skipped = 0
    for f in files:
        img = cv2.imread(str(f))
        if img is None:
            print(f"  Не удалось загрузить: {f.name}")
            skipped += 1
            continue

        h, w = img.shape[:2]
        if h != 600 or w != 682:
            print(f"  Нестандартный размер {w}x{h}: {f.name}, пропускаю")
            skipped += 1
            continue

        # Проверка layout: слева от фото (col 155) должен быть белый фон,
        # а внутри фото (col 156, row 89) — содержимое (не белый)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        border_white = gray[CROP_TOP, CROP_LEFT - 1] > 240
        photo_content = gray[CROP_TOP, CROP_LEFT] < 240
        if not (border_white and photo_content):
            print(f"  Нестандартный layout: {f.name}, пропускаю")
            skipped += 1
            continue

        crop = img[CROP_TOP:CROP_BOTTOM, CROP_LEFT:CROP_RIGHT]
        out_path = IMAGES_DIR / f.name
        cv2.imwrite(str(out_path), crop)
        count += 1

    print(f"Обрезано: {count}, пропущено: {skipped}")
    print(f"Сохранено в: {IMAGES_DIR}")


def generate_masks() -> None:
    """
    Шаг 2: автоматическая генерация бинарных масок теней.

    Алгоритм:
      1. Grayscale → threshold для тёмных областей
      2. Морфологические операции для очистки
      3. Фильтрация контуров по площади (3-8% изображения = тень пазла)
      4. Сохранение бинарной маски
    """
    MASKS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(IMAGES_DIR.glob("*.png"))
    if not files:
        print(f"Нет изображений в {IMAGES_DIR}")
        return

    total_area = CROP_H * CROP_W
    min_area = total_area * 0.015   # 1.5%
    max_area = total_area * 0.12    # 12%

    count = 0
    failed = 0
    for f in files:
        img = cv2.imread(str(f))
        if img is None:
            failed += 1
            continue

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Тень — тёмная область. Используем adaptive threshold
        # для устойчивости к разному уровню освещённости фото
        # Также попробуем фиксированный threshold и выберем лучший результат

        mask = _detect_shadow(gray, min_area, max_area)

        if mask is None:
            # Fallback: более агрессивный порог
            mask = _detect_shadow(gray, min_area * 0.5, max_area * 1.5, threshold=100)

        if mask is None:
            print(f"  Не найдена тень: {f.name}")
            failed += 1
            # Сохраняем пустую маску — пометится как плохая при проверке
            mask = np.zeros(gray.shape[:2], dtype=np.uint8)

        cv2.imwrite(str(MASKS_DIR / f.name), mask)
        count += 1

    print(f"Маски сгенерированы: {count}, не удалось найти тень: {failed}")
    print(f"Сохранено в: {MASKS_DIR}")


def _detect_shadow(
    gray: np.ndarray,
    min_area: float,
    max_area: float,
    threshold: int = 80,
) -> np.ndarray | None:
    """
    Найти тень пазла на grayscale изображении.

    Комбинирует несколько стратегий:
    1. Глобальный threshold (для ярких фото)
    2. Локальный контраст (для тёмных фото — тень темнее окружения)
    3. Adaptive threshold (fallback)

    Returns:
        Бинарная маска (255 = тень) или None если не найдена.
    """
    h, w = gray.shape[:2]

    # Стратегия 1: глобальный порог (хорошо для ярких фото)
    result = _threshold_and_find(gray, threshold, min_area, max_area)
    if result is not None:
        return result

    # Стратегия 2: локальный контраст
    # Тень темнее своего окружения → вычитаем размытую версию
    blurred = cv2.GaussianBlur(gray, (51, 51), 0)
    # Пиксели, которые значительно темнее своего окружения
    diff = blurred.astype(np.int16) - gray.astype(np.int16)
    # diff > 0 означает что пиксель темнее среднего окружения
    diff_positive = np.clip(diff, 0, 255).astype(np.uint8)

    # Порог на разницу: тень должна быть хотя бы на 25 уровней темнее
    for diff_thresh in [30, 25, 20, 15]:
        _, binary = cv2.threshold(diff_positive, diff_thresh, 255, cv2.THRESH_BINARY)
        result = _filter_contours(binary, min_area, max_area, h, w)
        if result is not None:
            return result

    # Стратегия 3: adaptive threshold
    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 51, 15,
    )
    result = _filter_contours(adaptive, min_area, max_area, h, w)
    if result is not None:
        return result

    # Стратегия 4: более мягкий глобальный порог
    for t in [100, 120, 140]:
        result = _threshold_and_find(gray, t, min_area, max_area)
        if result is not None:
            return result

    return None


def _threshold_and_find(
    gray: np.ndarray,
    threshold: int,
    min_area: float,
    max_area: float,
) -> np.ndarray | None:
    """Глобальный threshold + морфология + фильтрация контуров."""
    h, w = gray.shape[:2]
    _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)
    return _filter_contours(binary, min_area, max_area, h, w)


def _filter_contours(
    binary: np.ndarray,
    min_area: float,
    max_area: float,
    h: int,
    w: int,
) -> np.ndarray | None:
    """Морфология + фильтрация контуров по площади и форме пазла."""
    # Морфология: закрыть мелкие разрывы, убрать шум
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    kernel_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel_small)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if min_area <= area <= max_area:
            candidates.append((cnt, area))

    if not candidates:
        return None

    # Выбрать наиболее похожий на пазл контур
    best = _pick_best_puzzle_contour(candidates)
    if best is None:
        return None

    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.drawContours(mask, [best], -1, 255, cv2.FILLED)
    return mask


def _pick_best_puzzle_contour(
    candidates: list[tuple[np.ndarray, float]],
) -> np.ndarray | None:
    """
    Из списка контуров выбрать наиболее похожий на пазл.
    Пазл: aspect ratio ~0.7-1.0, solidity ~0.6-0.95.
    """
    best = None
    best_score = -1
    for cnt, area in candidates:
        x, y, bw, bh = cv2.boundingRect(cnt)
        aspect = min(bw, bh) / max(bw, bh) if max(bw, bh) > 0 else 0
        hull_area = cv2.contourArea(cv2.convexHull(cnt))
        solidity = area / hull_area if hull_area > 0 else 0

        # Пазл: aspect ~0.7-1.0, solidity ~0.6-0.95
        score = aspect * solidity
        if score > best_score:
            best_score = score
            best = cnt

    return best


def review_masks() -> None:
    """
    Шаг 3: визуальная проверка масок.

    Горячие клавиши:
      Enter / Space = маска OK
      D            = пометить как плохую
      Q            = выйти
    """
    files = sorted(IMAGES_DIR.glob("*.png"))
    if not files:
        print("Нет изображений для проверки")
        return

    bad_masks = []
    if BAD_LIST.exists():
        bad_masks = json.loads(BAD_LIST.read_text())

    reviewed = 0
    marked_bad = 0

    print(f"Проверка масок: {len(files)} изображений")
    print("Enter/Space = OK, D = плохая, Q = выйти")

    for f in files:
        mask_path = MASKS_DIR / f.name
        if not mask_path.exists():
            continue

        img = cv2.imread(str(f))
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)

        if img is None or mask is None:
            continue

        # Overlay: маска красным полупрозрачно
        overlay = img.copy()
        overlay[mask > 127] = [0, 0, 255]  # красный
        blended = cv2.addWeighted(img, 0.6, overlay, 0.4, 0)

        # Показать имя файла
        cv2.putText(
            blended, f.name, (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2,
        )

        # Проверить площадь маски
        mask_area = np.sum(mask > 127)
        total_area = mask.shape[0] * mask.shape[1]
        pct = mask_area / total_area * 100
        status = f"Mask: {pct:.1f}%"
        if f.name in bad_masks:
            status += " [BAD]"
        cv2.putText(
            blended, status, (10, 50),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1,
        )

        cv2.imshow("Review", blended)
        key = cv2.waitKey(0) & 0xFF

        if key == ord('q'):
            break
        elif key == ord('d'):
            if f.name not in bad_masks:
                bad_masks.append(f.name)
            marked_bad += 1
        # Enter (13) or Space (32) = OK, continue

        reviewed += 1

    cv2.destroyAllWindows()

    # Сохранить список плохих масок
    BAD_LIST.write_text(json.dumps(bad_masks, indent=2))
    print(f"\nПроверено: {reviewed}, помечено плохих: {marked_bad}")
    print(f"Всего плохих масок: {len(bad_masks)}")
    print(f"Список сохранён в: {BAD_LIST}")


def stats() -> None:
    """Показать статистику датасета."""
    images = list(IMAGES_DIR.glob("*.png"))
    masks = list(MASKS_DIR.glob("*.png"))

    print(f"Изображений: {len(images)}")
    print(f"Масок: {len(masks)}")

    if BAD_LIST.exists():
        bad = json.loads(BAD_LIST.read_text())
        print(f"Плохих масок: {len(bad)}")
        print(f"Хороших масок: {len(masks) - len(bad)}")

    # Проверить площадь масок
    if masks:
        areas = []
        empty = 0
        for m in masks[:100]:  # первые 100
            mask = cv2.imread(str(m), cv2.IMREAD_GRAYSCALE)
            if mask is None:
                continue
            a = np.sum(mask > 127) / (mask.shape[0] * mask.shape[1]) * 100
            if a < 0.5:
                empty += 1
            areas.append(a)
        if areas:
            print(f"\nСтатистика площади масок (первые {len(areas)}):")
            print(f"  Среднее: {np.mean(areas):.1f}%")
            print(f"  Мин: {np.min(areas):.1f}%")
            print(f"  Макс: {np.max(areas):.1f}%")
            print(f"  Пустые (<0.5%): {empty}")


# ── CLI ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python -m app.captcha.puzzle_dataset_prep crop <screenshots_dir>")
        print("  python -m app.captcha.puzzle_dataset_prep masks")
        print("  python -m app.captcha.puzzle_dataset_prep review")
        print("  python -m app.captcha.puzzle_dataset_prep stats")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "crop":
        if len(sys.argv) < 3:
            print("Укажи путь к папке со скриншотами")
            sys.exit(1)
        crop_screenshots(sys.argv[2])
    elif cmd == "masks":
        generate_masks()
    elif cmd == "review":
        review_masks()
    elif cmd == "stats":
        stats()
    else:
        print(f"Неизвестная команда: {cmd}")
        sys.exit(1)
