# -*- coding: utf-8 -*-
"""
Solver для пазл-капчи Proton Mail.

Использует обученную U-Net модель для сегментации тени пазла
и вычисления целевых координат.

Пример:
  from app.captcha.solve_puzzle import PuzzleSolver

  solver = PuzzleSolver()
  x, y, confidence = solver.solve("screenshot.png")
"""

from pathlib import Path

import cv2
import numpy as np
import torch
import segmentation_models_pytorch as smp

# ── Пути ──────────────────────────────────────────────────────────────
MODEL_PATH = Path(__file__).resolve().parent / "models" / "puzzle_unet.pth"

# ── Координаты обрезки (фиксированные для скриншотов 682×600) ────────
CROP_TOP = 89
CROP_BOTTOM = 439
CROP_LEFT = 156
CROP_RIGHT = 526

# ── Нормализация (ImageNet) ───────────────────────────────────────────
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class PuzzleSolver:
    def __init__(self, model_path: str | Path | None = None, device: str | None = None):
        """
        Args:
            model_path: Путь к весам модели. По умолчанию — models/puzzle_unet.pth.
            device: "cuda", "cpu" или None (авто).
        """
        model_path = Path(model_path) if model_path else MODEL_PATH

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        # Загрузить чекпоинт
        checkpoint = torch.load(str(model_path), map_location=self.device, weights_only=False)
        self.img_size = checkpoint.get("img_size", 256)
        encoder = checkpoint.get("encoder", "resnet34")

        # Создать и загрузить модель
        self.model = smp.Unet(
            encoder_name=encoder,
            encoder_weights=None,
            in_channels=3,
            classes=1,
        )
        self.model.load_state_dict(checkpoint["model_state_dict"])
        self.model.to(self.device)
        self.model.eval()

    def solve(
        self,
        image: str | Path | np.ndarray,
        is_screenshot: bool = True,
        debug: bool = False,
    ) -> tuple[int, int, float]:
        """
        Найти позицию тени пазла.

        Args:
            image: Полный скриншот капчи (682x600) или обрезанное фото (350x370).
                   Может быть путём к файлу или numpy array (BGR).
            is_screenshot: True если передан полный скриншот, False если обрезанное фото.
            debug: Сохранить визуализацию рядом с входным файлом.

        Returns:
            (x, y, confidence):
              - x, y — координаты центра тени.
                       Если is_screenshot=True, координаты в системе скриншота.
                       Если is_screenshot=False, координаты в системе обрезанного фото.
              - confidence — средняя вероятность маски (0.0-1.0).
        """
        # Загрузить изображение
        if isinstance(image, (str, Path)):
            image_path = Path(image)
            img = cv2.imread(str(image_path))
            if img is None:
                raise FileNotFoundError(f"Cannot load image: {image_path}")
        else:
            img = image
            image_path = None

        # Обрезать фон из скриншота
        if is_screenshot:
            h, w = img.shape[:2]
            if h == 600 and w == 682:
                photo = img[CROP_TOP:CROP_BOTTOM, CROP_LEFT:CROP_RIGHT]
            else:
                # Нестандартный размер — попробовать использовать как есть
                photo = img
                is_screenshot = False
        else:
            photo = img

        photo_h, photo_w = photo.shape[:2]

        # Предобработка
        rgb = cv2.cvtColor(photo, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (self.img_size, self.img_size))

        # Normalize
        tensor = resized.astype(np.float32) / 255.0
        tensor = (tensor - MEAN) / STD
        tensor = torch.from_numpy(tensor.transpose(2, 0, 1)).unsqueeze(0).to(self.device)

        # Inference
        with torch.no_grad():
            logits = self.model(tensor)
            probs = torch.sigmoid(logits).squeeze().cpu().numpy()

        # Бинарная маска
        mask = (probs > 0.5).astype(np.uint8)

        # Найти наибольший connected component
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)

        if num_labels <= 1:
            # Нет предсказания — вернуть центр изображения с нулевой уверенностью
            cx = photo_w // 2
            cy = photo_h // 2
            return (cx + CROP_LEFT if is_screenshot else cx,
                    cy + CROP_TOP if is_screenshot else cy,
                    0.0)

        # Наибольший компонент (кроме фона = label 0)
        areas = stats[1:, cv2.CC_STAT_AREA]
        best_label = np.argmax(areas) + 1

        # Центроид в координатах resized
        cx_resized, cy_resized = centroids[best_label]

        # Пересчёт в координаты оригинального фото
        cx_photo = cx_resized * photo_w / self.img_size
        cy_photo = cy_resized * photo_h / self.img_size

        # Confidence: средняя вероятность в области маски
        component_mask = (labels == best_label)
        confidence = float(probs[component_mask].mean())

        # Координаты в системе скриншота или фото
        if is_screenshot:
            cx_out = int(round(cx_photo + CROP_LEFT))
            cy_out = int(round(cy_photo + CROP_TOP))
        else:
            cx_out = int(round(cx_photo))
            cy_out = int(round(cy_photo))

        # Debug визуализация
        if debug and image_path is not None:
            self._save_debug(
                img, photo, probs, mask, cx_out, cy_out,
                image_path, is_screenshot,
            )

        return cx_out, cy_out, confidence

    def _save_debug(self, full_img, photo, probs, mask, cx, cy, image_path, is_screenshot):
        """Сохранить debug-визуализацию."""
        # Resize маску обратно к размеру фото
        photo_h, photo_w = photo.shape[:2]
        mask_full = cv2.resize(mask, (photo_w, photo_h), interpolation=cv2.INTER_NEAREST)
        probs_full = cv2.resize(probs, (photo_w, photo_h))

        # Overlay на фото
        overlay = photo.copy()
        overlay[mask_full > 0] = [0, 100, 255]
        blended = cv2.addWeighted(photo, 0.6, overlay, 0.4, 0)

        # Отрисовать центр
        photo_cx = cx - CROP_LEFT if is_screenshot else cx
        photo_cy = cy - CROP_TOP if is_screenshot else cy
        cv2.circle(blended, (int(photo_cx), int(photo_cy)), 5, (0, 255, 0), 2)
        cv2.circle(blended, (int(photo_cx), int(photo_cy)), 2, (0, 255, 0), -1)

        # Heatmap
        heatmap = cv2.applyColorMap((probs_full * 255).astype(np.uint8), cv2.COLORMAP_JET)
        heatmap_blend = cv2.addWeighted(photo, 0.5, heatmap, 0.5, 0)

        # Собрать: фото | overlay | heatmap
        debug_img = np.hstack([photo, blended, heatmap_blend])

        debug_path = str(image_path).replace(".png", "_debug.png")
        cv2.imwrite(debug_path, debug_img)
