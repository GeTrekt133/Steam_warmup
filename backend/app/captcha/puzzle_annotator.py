# -*- coding: utf-8 -*-
"""
Инструмент разметки пазл-капчи с SAM (Segment Anything Model).

Workflow:
  1. Показывает изображение
  2. Клик левой кнопкой → SAM генерирует маску от точки клика
  3. Клик правой кнопкой → отрицательная точка (исключить область)
  4. Enter → сохранить маску, перейти к следующему
  5. R → сбросить точки, начать заново
  6. Q → выйти

Использование:
  python -m app.captcha.puzzle_annotator [--resume] [--only-bad]

Флаги:
  --resume    Пропустить уже размеченные изображения
  --only-bad  Разметить только плохие маски из bad_masks.json
"""

import sys
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from segment_anything import sam_model_registry, SamPredictor

# ── Пути ──────────────────────────────────────────────────────────────
DATASET_DIR = Path(__file__).resolve().parents[3] / "datasets" / "puzzle"
IMAGES_DIR = DATASET_DIR / "images"
MASKS_DIR = DATASET_DIR / "masks"
BAD_LIST = DATASET_DIR / "bad_masks.json"
MODEL_PATH = Path(__file__).resolve().parent / "models" / "sam_vit_b.pth"

# ── Настройки отображения ─────────────────────────────────────────────
WINDOW_NAME = "SAM Annotator"
DISPLAY_SCALE = 2  # увеличение для удобства (350x370 мелковато)


class SAMAnnotator:
    def __init__(self):
        print("Загрузка SAM модели...")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        sam = sam_model_registry["vit_b"](checkpoint=str(MODEL_PATH))
        sam.to(device)
        self.predictor = SamPredictor(sam)
        self.device = device
        print(f"SAM загружен на {device}")

        # Состояние аннотации
        self.current_image = None
        self.current_mask = None
        self.all_masks = None
        self.all_scores = None
        self.current_mask_idx = 0
        self.positive_points = []
        self.negative_points = []

    def _on_mouse(self, event, x, y, flags, param):
        """Обработчик кликов мыши."""
        # Пересчёт координат из display scale в оригинальные
        ox = int(x / DISPLAY_SCALE)
        oy = int(y / DISPLAY_SCALE)

        if event == cv2.EVENT_LBUTTONDOWN:
            # Левый клик = положительная точка (тут тень)
            self.positive_points.append([ox, oy])
            self._predict_mask()
            self._show()
        elif event == cv2.EVENT_RBUTTONDOWN:
            # Правый клик = отрицательная точка (тут НЕ тень)
            self.negative_points.append([ox, oy])
            self._predict_mask()
            self._show()

    def _predict_mask(self):
        """Запустить SAM с текущими точками."""
        if not self.positive_points:
            self.current_mask = None
            self.all_masks = None
            self.current_mask_idx = 0
            return

        points = np.array(self.positive_points + self.negative_points)
        labels = np.array(
            [1] * len(self.positive_points) + [0] * len(self.negative_points)
        )

        masks, scores, _ = self.predictor.predict(
            point_coords=points,
            point_labels=labels,
            multimask_output=True,
        )

        # Сохранить все маски для переключения через Tab
        self.all_masks = masks
        self.all_scores = scores

        # Умный выбор маски: тень пазла ~1-10% площади изображения
        total_px = masks[0].shape[0] * masks[0].shape[1]
        target_min = total_px * 0.01  # 1%
        target_max = total_px * 0.10  # 10%

        # Найти маску в целевом диапазоне с лучшим score
        best_idx = None
        best_score = -1
        for i, (m, s) in enumerate(zip(masks, scores)):
            area = np.sum(m)
            if target_min <= area <= target_max and s > best_score:
                best_idx = i
                best_score = s

        # Если ни одна маска не в диапазоне — выбрать ближайшую по площади
        if best_idx is None:
            target_center = total_px * 0.04  # 4% — типичный размер тени
            best_idx = min(
                range(len(masks)),
                key=lambda i: abs(np.sum(masks[i]) - target_center),
            )

        self.current_mask_idx = best_idx
        self.current_mask = masks[best_idx].astype(np.uint8) * 255

    def _cycle_mask(self):
        """Переключить на следующую маску SAM (по Tab)."""
        if self.all_masks is None:
            return
        n = len(self.all_masks)
        self.current_mask_idx = (self.current_mask_idx + 1) % n
        idx = self.current_mask_idx
        self.current_mask = self.all_masks[idx].astype(np.uint8) * 255
        self._show()

    def _show(self):
        """Отобразить изображение с overlay маски и точками."""
        display = self.current_image.copy()

        # Overlay маски
        if self.current_mask is not None:
            overlay = display.copy()
            overlay[self.current_mask > 127] = [0, 100, 255]  # оранжевый
            display = cv2.addWeighted(display, 0.6, overlay, 0.4, 0)

            # Показать площадь маски и индекс
            area_pct = np.sum(self.current_mask > 127) / (
                self.current_mask.shape[0] * self.current_mask.shape[1]
            ) * 100
            idx = self.current_mask_idx
            score = self.all_scores[idx] if self.all_scores is not None else 0
            n = len(self.all_masks) if self.all_masks is not None else 0
            cv2.putText(
                display,
                f"Mask {idx+1}/{n}: {area_pct:.1f}% (score={score:.2f}) [Tab=next]",
                (5, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1,
            )

        # Отрисовать точки
        for px, py in self.positive_points:
            cv2.circle(display, (px, py), 4, (0, 255, 0), -1)   # зелёный = positive
            cv2.circle(display, (px, py), 5, (255, 255, 255), 1)
        for px, py in self.negative_points:
            cv2.circle(display, (px, py), 4, (0, 0, 255), -1)   # красный = negative
            cv2.circle(display, (px, py), 5, (255, 255, 255), 1)

        # Увеличить для удобного отображения
        h, w = display.shape[:2]
        display = cv2.resize(
            display, (w * DISPLAY_SCALE, h * DISPLAY_SCALE),
            interpolation=cv2.INTER_NEAREST,
        )

        cv2.imshow(WINDOW_NAME, display)

    def annotate(self, resume: bool = False, only_bad: bool = False):
        """Основной цикл разметки."""
        files = sorted(IMAGES_DIR.glob("*.png"))
        if not files:
            print("Нет изображений в", IMAGES_DIR)
            return

        # Фильтрация
        if only_bad and BAD_LIST.exists():
            bad_names = set(json.loads(BAD_LIST.read_text()))
            files = [f for f in files if f.name in bad_names]
            print(f"Режим only-bad: {len(files)} изображений")

        if resume:
            # Пропустить уже размеченные (маска существует и не пустая)
            remaining = []
            for f in files:
                mask_path = MASKS_DIR / f.name
                if mask_path.exists():
                    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
                    if mask is not None and np.sum(mask > 127) > 100:
                        continue
                remaining.append(f)
            files = remaining
            print(f"Режим resume: {len(files)} оставшихся")

        MASKS_DIR.mkdir(parents=True, exist_ok=True)

        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(WINDOW_NAME, self._on_mouse)

        total = len(files)
        saved = 0
        skipped = 0
        idx = 0

        while 0 <= idx < total:
            f = files[idx]
            img = cv2.imread(str(f))
            if img is None:
                idx += 1
                continue

            # Установить изображение в SAM predictor
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            self.predictor.set_image(img_rgb)

            # Сбросить состояние
            self.current_image = img
            self.current_mask = None
            self.all_masks = None
            self.positive_points = []
            self.negative_points = []

            # Заголовок окна
            cv2.setWindowTitle(
                WINDOW_NAME,
                f"[{idx + 1}/{total}] {f.name} | "
                f"LMB=add RMB=exclude Tab=switch "
                f"Enter=save Bksp=back R=reset S=skip Q=quit",
            )
            self._show()

            action = None
            while action is None:
                key = cv2.waitKey(0) & 0xFF

                if key == 13 or key == 10:  # Enter — сохранить
                    if self.current_mask is not None:
                        cv2.imwrite(str(MASKS_DIR / f.name), self.current_mask)
                        saved += 1
                        print(f"  [{idx+1}/{total}] {f.name} — сохранено")
                    action = "next"
                elif key == 9:  # Tab — переключить маску
                    self._cycle_mask()
                elif key == 8 or key == 127:  # Backspace — назад
                    action = "prev"
                elif key == ord('r'):  # R — сбросить
                    self.positive_points = []
                    self.negative_points = []
                    self.current_mask = None
                    self.all_masks = None
                    self._show()
                elif key == ord('s'):  # S — пропустить
                    skipped += 1
                    action = "next"
                elif key == ord('q'):  # Q — выйти
                    cv2.destroyAllWindows()
                    print(f"\nСохранено: {saved}, пропущено: {skipped}")
                    return

            if action == "next":
                idx += 1
            elif action == "prev":
                idx = max(0, idx - 1)

        cv2.destroyAllWindows()
        print(f"\nГотово! Сохранено: {saved}, пропущено: {skipped}")


def main():
    resume = "--resume" in sys.argv
    only_bad = "--only-bad" in sys.argv

    annotator = SAMAnnotator()
    annotator.annotate(resume=resume, only_bad=only_bad)


if __name__ == "__main__":
    main()
