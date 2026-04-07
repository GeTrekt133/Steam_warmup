"""
Универсальный SAM-лейблер для hCaptcha. Три режима:

  --mode figures   Сегментация фигур (drag-to-similar). Каждая фигура = маска.
  --mode lines     Сегментация линий (line breaks). Каждая цветовая линия = маска.
  --mode detect    Детекция ячеек (сетки с животными/объектами). Bbox + класс (correct/wrong).

Общее управление:
  ЛКМ          — positive point (SAM сегментирует / начать bbox)
  ПКМ          — negative point (уточнить маску) / отменить bbox
  Space        — завершить текущий элемент, начать новый
  N            — переключить вариант маски (SAM)
  Backspace    — удалить последний элемент
  S            — сохранить и следующая
  D            — пропустить
  R            — сбросить всё
  Q            — выйти
  T            — пометить как TARGET / CORRECT

Дополнительно (mode=detect):
  ЛКМ drag     — нарисовать bbox
  C            — пометить последний bbox как correct

Использование:
  python captcha_labeler.py --mode figures --filter "drag"
  python captcha_labeler.py --mode lines --filter "line break"
  python captcha_labeler.py --mode detect --filter "animal"
  python captcha_labeler.py --mode detect --filter "heavier"
"""
import json
import argparse
import logging
from pathlib import Path

import cv2
import numpy as np
import torch
from segment_anything import sam_model_registry, SamPredictor

logger = logging.getLogger(__name__)

DATASET_DIR = Path(__file__).parent / "captcha_dataset"
MASKS_DIR = DATASET_DIR / "masks"
LABELS_FILE = DATASET_DIR / "labels.jsonl"

DISPLAY_SCALE = 2
MASK_ALPHA = 0.4

MASK_COLORS = [
    (255, 100, 100), (100, 255, 100), (100, 100, 255),
    (255, 255, 100), (255, 100, 255), (100, 255, 255),
    (200, 200, 100), (100, 200, 200),
]
TARGET_COLOR = (0, 255, 0)
EDITING_COLOR = (0, 200, 255)
BBOX_COLOR = (255, 255, 0)
BBOX_CORRECT_COLOR = (0, 255, 0)
BBOX_WRONG_COLOR = (100, 100, 255)


# ── Shared data classes ──────────────────────────────────────────────

class MaskEntry:
    """Одна маска (фигура или линия)."""
    def __init__(self, mask: np.ndarray, point: list[int], is_target: bool = False):
        self.mask = mask
        self.point = point
        self.is_target = is_target
        self.neg_points: list[list[int]] = []
        self.pos_points: list[list[int]] = [point]
        self.all_masks: np.ndarray | None = None
        self.variant = 0


class BboxEntry:
    """Один bounding box (ячейка сетки)."""
    def __init__(self, x1: int, y1: int, x2: int, y2: int, is_correct: bool = False):
        self.x1 = min(x1, x2)
        self.y1 = min(y1, y2)
        self.x2 = max(x1, x2)
        self.y2 = max(y1, y2)
        self.is_correct = is_correct

    @property
    def center(self) -> tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    def to_dict(self) -> dict:
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2, "is_correct": self.is_correct}


# ── Base labeler ─────────────────────────────────────────────────────

class BaseSAMLabeler:
    """Общая логика: загрузка SAM, навигация по датасету, сохранение."""

    def __init__(self, model_path: str, model_type: str, start: int, filter_prompt: str | None, mode: str):
        MASKS_DIR.mkdir(exist_ok=True)
        self.mode = mode

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Загрузка SAM ({model_type}) на {device}...")
        sam = sam_model_registry[model_type](checkpoint=model_path)
        sam.to(device)
        self.predictor = SamPredictor(sam)
        print("SAM загружен!")

        self.entries = []
        # Загрузить из всех датасетов
        for dataset_dir in [DATASET_DIR, DATASET_DIR.parent / "captcha_dataset_v2"]:
            meta_file = dataset_dir / "metadata.jsonl"
            if not meta_file.exists():
                continue
            with open(meta_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if filter_prompt and filter_prompt.lower() not in entry.get("prompt", "").lower():
                        continue
                    entry["_dataset_dir"] = str(dataset_dir)
                    self.entries.append(entry)

        # Перемешать (фиксированный seed для воспроизводимости)
        import random
        random.seed(42)
        random.shuffle(self.entries)

        self.labeled = set()
        if LABELS_FILE.exists():
            with open(LABELS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    self.labeled.add(d.get("screenshot", ""))

        self.current_idx = start
        self.orig_img = None

    def run(self):
        total = len(self.entries)
        labeled_count = len(self.labeled)
        print(f"Режим: {self.mode} | Всего: {total} | Размечено: {labeled_count}")
        print(f"Начинаю с {self.current_idx}")
        self._print_help()

        cv2.namedWindow("SAM Labeler", cv2.WINDOW_NORMAL)
        cv2.setMouseCallback("SAM Labeler", self._mouse_callback)

        while self.current_idx < total:
            entry = self.entries[self.current_idx]
            screenshot = entry["screenshot"]

            if screenshot in self.labeled:
                self.current_idx += 1
                continue

            ds_dir = Path(entry.get("_dataset_dir", str(DATASET_DIR)))
            img_path = ds_dir / screenshot
            if not img_path.exists():
                self.current_idx += 1
                continue

            self.orig_img = cv2.imread(str(img_path))
            if self.orig_img is None:
                self.current_idx += 1
                continue

            # SAM encode (для modes figures/lines)
            if self.mode in ("figures", "lines"):
                rgb = cv2.cvtColor(self.orig_img, cv2.COLOR_BGR2RGB)
                print(f"[{self.current_idx}/{total}] {screenshot} — encoding...", end=" ", flush=True)
                self.predictor.set_image(rgb)
                print("OK")
            else:
                print(f"[{self.current_idx}/{total}] {screenshot}")

            print(f"  Prompt: {entry.get('prompt', '?')}")
            self._reset_state()

            action = self._interact()

            if action == "save":
                self._save(entry)
                labeled_count += 1
                print(f"  ✓ Сохранено ({labeled_count})")
                self.current_idx += 1
            elif action == "skip":
                print(f"  → Пропуск")
                self.current_idx += 1
            elif action == "quit":
                break

        cv2.destroyAllWindows()
        print(f"\nИтого размечено: {labeled_count}")

    # Абстрактные методы — реализуются в подклассах
    def _print_help(self): pass
    def _reset_state(self): pass
    def _render(self) -> np.ndarray: return self.orig_img.copy()
    def _interact(self) -> str: return "skip"
    def _mouse_callback(self, event, x, y, flags, param): pass
    def _save(self, entry: dict): pass


# ── Figures mode (drag-to-similar) ───────────────────────────────────

class FiguresLabeler(BaseSAMLabeler):
    """Сегментация фигур. Каждая фигура = отдельная маска. M = режим bbox для Move."""

    def _print_help(self):
        print("ЛКМ=positive | ПКМ=negative | Space=новая маска | N=вариант | Bksp=удалить")
        print("T=target | M=bbox Move | B=brush | scroll=brush size | S=save | D=skip | R=reset | Q=quit\n")

    def _reset_state(self):
        self.masks: list[MaskEntry] = []
        self.current_edit: MaskEntry | None = None
        self.drag_bbox: list[int] | None = None  # [x1, y1, x2, y2]
        self.drawing_bbox = False
        self.bbox_start: tuple[int, int] | None = None
        self.bbox_current: tuple[int, int] | None = None
        self.bbox_mode = False  # M переключает
        self.brush_mode = False  # B переключает
        self.brush_size = 8
        self.brush_drawing = False
        self.brush_erasing = False

    def _predict(self, pos_points, neg_points):
        points = pos_points + neg_points
        labels = [1] * len(pos_points) + [0] * len(neg_points)
        masks, scores, _ = self.predictor.predict(
            point_coords=np.array(points), point_labels=np.array(labels), multimask_output=True)
        order = np.argsort(-scores)
        return masks[order], scores[order]

    def _finalize_current(self):
        if self.current_edit is not None and self.current_edit.mask is not None:
            self.masks.append(self.current_edit)
            print(f"  ✓ Маска {len(self.masks)} завершена")
        self.current_edit = None

    def _render(self) -> np.ndarray:
        img = self.orig_img.copy()
        all_masks = list(self.masks)
        editing_idx = None
        if self.current_edit is not None and self.current_edit.mask is not None:
            editing_idx = len(all_masks)
            all_masks.append(self.current_edit)

        for i, me in enumerate(all_masks):
            if me.mask is None:
                continue
            is_editing = (i == editing_idx)
            if me.is_target:
                color = TARGET_COLOR
            elif is_editing:
                color = EDITING_COLOR
            else:
                color = MASK_COLORS[i % len(MASK_COLORS)]

            overlay = img.copy()
            overlay[me.mask] = color
            img = cv2.addWeighted(overlay, MASK_ALPHA, img, 1 - MASK_ALPHA, 0)
            mask_u8 = (me.mask * 255).astype(np.uint8)
            contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(img, contours, -1, color, 2 if (me.is_target or is_editing) else 1)

            cx, cy = me.point
            prefix = "T" if me.is_target else ("*" if is_editing else "")
            cv2.putText(img, f"{prefix}{i+1}", (cx - 5, cy - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 2)
            cv2.putText(img, f"{prefix}{i+1}", (cx - 5, cy - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
            cv2.circle(img, (cx, cy), 3, color, -1)
            for np_ in me.neg_points:
                cv2.circle(img, (np_[0], np_[1]), 3, (0, 0, 255), -1)

        display = cv2.resize(img, None, fx=DISPLAY_SCALE, fy=DISPLAY_SCALE, interpolation=cv2.INTER_LINEAR)
        h = display.shape[0]
        targets = sum(1 for m in self.masks if m.is_target)
        # Drag bbox
        if self.drag_bbox:
            bx1, by1, bx2, by2 = self.drag_bbox
            cv2.rectangle(img, (bx1, by1), (bx2, by2), (0, 165, 255), 2)
            cv2.putText(img, "MOVE", (bx1 + 3, by1 + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 165, 255), 1)

        # Текущий рисуемый bbox
        if self.drawing_bbox and self.bbox_start and self.bbox_current:
            sx, sy = self.bbox_start
            cx, cy = self.bbox_current
            cv2.rectangle(img, (sx, sy), (cx, cy), (0, 165, 255), 1)

        display = cv2.resize(img, None, fx=DISPLAY_SCALE, fy=DISPLAY_SCALE, interpolation=cv2.INTER_LINEAR)
        h = display.shape[0]

        has_bbox = "Y" if self.drag_bbox else "N"
        if self.brush_mode:
            mode_str = f"[BRUSH sz={self.brush_size}]"
        elif self.bbox_mode:
            mode_str = "[BBOX]"
        elif self.current_edit:
            mode_str = "[SAM EDIT]"
        else:
            mode_str = ""
        cv2.putText(display, f"Masks:{len(self.masks)} Move:{has_bbox} {mode_str} | B=brush M=bbox T=tgt Space=next S=save", (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
        return display

    def _interact(self) -> str:
        while True:
            cv2.imshow("SAM Labeler", self._render())
            key = cv2.waitKey(30) & 0xFF
            if key == ord("s") or key == ord("S"):
                self._finalize_current()
                if not self.masks:
                    print("  ⚠ Нет масок!"); continue
                return "save"
            elif key == ord("d") or key == ord("D"): return "skip"
            elif key == ord("q") or key == ord("Q"): return "quit"
            elif key == ord("r") or key == ord("R"):
                self.masks = []; self.current_edit = None
                self.drag_bbox = None; self.brush_mode = False; self.bbox_mode = False
                print("  Reset")
            elif key == 32:  # Space
                self._finalize_current()
                self.brush_mode = False
                print("  Новая маска")
            elif key == ord("t") or key == ord("T"):
                t = self.current_edit or (self.masks[-1] if self.masks else None)
                if t: t.is_target = not t.is_target; print(f"  {'TARGET' if t.is_target else 'обычная'}")
            elif key == ord("m") or key == ord("M"):
                self.bbox_mode = not self.bbox_mode
                self.brush_mode = False
                print(f"  {'BBOX MODE' if self.bbox_mode else 'SAM MODE'}")
            elif key == ord("b") or key == ord("B"):
                self.brush_mode = not self.brush_mode
                self.bbox_mode = False
                if self.brush_mode and self.current_edit is None:
                    # Создать пустую маску для рисования
                    h, w = self.orig_img.shape[:2]
                    empty_mask = np.zeros((h, w), dtype=bool)
                    me = MaskEntry(mask=empty_mask, point=[w // 2, h // 2])
                    self.current_edit = me
                print(f"  {'BRUSH MODE (size={self.brush_size})' if self.brush_mode else 'SAM MODE'}")
            elif key == ord("n") or key == ord("N"):
                me = self.current_edit
                if me and me.all_masks is not None:
                    me.variant = (me.variant + 1) % len(me.all_masks)
                    me.mask = me.all_masks[me.variant]
                    print(f"  Вариант {me.variant + 1}/{len(me.all_masks)}")
            elif key == 8 or key == 127:
                if self.drag_bbox:
                    self.drag_bbox = None; print("  Move bbox удалён")
                elif self.current_edit:
                    self.current_edit = None; print("  Текущая удалена")
                elif self.masks:
                    self.masks.pop(); print(f"  Удалена ({len(self.masks)})")

    def _mouse_callback(self, event, x, y, flags, param):
        if self.orig_img is None: return
        ox, oy = x // DISPLAY_SCALE, y // DISPLAY_SCALE
        h, w = self.orig_img.shape[:2]
        ox = max(0, min(ox, w - 1))
        oy = max(0, min(oy, h - 1))

        # Scroll = brush size
        if event == cv2.EVENT_MOUSEWHEEL:
            if self.brush_mode:
                if flags > 0:
                    self.brush_size = min(50, self.brush_size + 2)
                else:
                    self.brush_size = max(2, self.brush_size - 2)
                print(f"  Brush: {self.brush_size}px")
            return

        # Режим brush
        if self.brush_mode:
            if self.current_edit is None:
                h_, w_ = self.orig_img.shape[:2]
                me = MaskEntry(mask=np.zeros((h_, w_), dtype=bool), point=[ox, oy])
                self.current_edit = me

            if event == cv2.EVENT_LBUTTONDOWN:
                self.brush_drawing = True
                cv2.circle(self.current_edit.mask.view(np.uint8), (ox, oy), self.brush_size, 1, -1)
                self.current_edit.point = [ox, oy]
            elif event == cv2.EVENT_RBUTTONDOWN:
                self.brush_erasing = True
                cv2.circle(self.current_edit.mask.view(np.uint8), (ox, oy), self.brush_size, 0, -1)
            elif event == cv2.EVENT_MOUSEMOVE:
                if self.brush_drawing:
                    cv2.circle(self.current_edit.mask.view(np.uint8), (ox, oy), self.brush_size, 1, -1)
                elif self.brush_erasing:
                    cv2.circle(self.current_edit.mask.view(np.uint8), (ox, oy), self.brush_size, 0, -1)
            elif event == cv2.EVENT_LBUTTONUP:
                self.brush_drawing = False
            elif event == cv2.EVENT_RBUTTONUP:
                self.brush_erasing = False
            return

        # Режим bbox (Move)
        if self.bbox_mode:
            if event == cv2.EVENT_LBUTTONDOWN:
                self.drawing_bbox = True
                self.bbox_start = (ox, oy)
                self.bbox_current = (ox, oy)
            elif event == cv2.EVENT_MOUSEMOVE and self.drawing_bbox:
                self.bbox_current = (ox, oy)
            elif event == cv2.EVENT_LBUTTONUP and self.drawing_bbox:
                self.drawing_bbox = False
                if self.bbox_start and abs(ox - self.bbox_start[0]) > 5 and abs(oy - self.bbox_start[1]) > 5:
                    sx, sy = self.bbox_start
                    self.drag_bbox = [min(sx, ox), min(sy, oy), max(sx, ox), max(sy, oy)]
                    print(f"  Move bbox: {self.drag_bbox}")
                    self.bbox_mode = False  # автовыход из bbox mode
                self.bbox_start = None
                self.bbox_current = None
            elif event == cv2.EVENT_RBUTTONDOWN:
                self.drag_bbox = None
                print("  Move bbox удалён")
            return

        # SAM mode
        if event == cv2.EVENT_LBUTTONDOWN:
            if self.current_edit is None:
                result = self._predict([[ox, oy]], [])
                masks, scores = result
                me = MaskEntry(mask=masks[0], point=[ox, oy])
                me.all_masks = masks
                self.current_edit = me
                print(f"  + Новая ({scores[0]:.2f})")
            else:
                me = self.current_edit
                me.pos_points.append([ox, oy]); me.point = [ox, oy]
                masks, scores = self._predict(me.pos_points, me.neg_points)
                me.all_masks = masks; me.variant = min(me.variant, len(masks)-1); me.mask = masks[me.variant]
                print(f"  + Positive ({scores[me.variant]:.2f})")
        elif event == cv2.EVENT_RBUTTONDOWN:
            if self.current_edit:
                me = self.current_edit; me.neg_points.append([ox, oy])
                masks, scores = self._predict(me.pos_points, me.neg_points)
                me.all_masks = masks; me.variant = min(me.variant, len(masks)-1); me.mask = masks[me.variant]
                print(f"  - Negative ({scores[me.variant]:.2f})")

    def _save(self, entry: dict):
        self._finalize_current()
        screenshot = entry["screenshot"]
        h, w = self.orig_img.shape[:2]
        mask_files = []
        target_idx = -1
        for i, me in enumerate(self.masks):
            mask_name = screenshot.replace(".png", f"_mask_{i}.png")
            cv2.imwrite(str(MASKS_DIR / mask_name), (me.mask * 255).astype(np.uint8))
            mask_files.append(mask_name)
            if me.is_target: target_idx = i

        combined = np.zeros((h, w), dtype=np.uint8)
        for i, me in enumerate(self.masks):
            combined[me.mask] = i + 1
        combined_name = screenshot.replace(".png", "_masks_combined.png")
        cv2.imwrite(str(MASKS_DIR / combined_name), combined)

        label = {
            "mode": "figures", "screenshot": screenshot, "masks": mask_files,
            "combined_mask": combined_name, "target_idx": target_idx,
            "drag_bbox": self.drag_bbox,
            "num_masks": len(self.masks), "points": [me.point for me in self.masks],
            "prompt": entry.get("prompt", ""),
        }

        if self.drag_bbox:
            print(f"  Move bbox: {self.drag_bbox}")

        with open(LABELS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(label, ensure_ascii=False) + "\n")
        self.labeled.add(screenshot)


# ── Lines mode (line breaks) ─────────────────────────────────────────

class LinesLabeler(BaseSAMLabeler):
    """Сегментация линий. Каждая цветовая линия = отдельная маска."""

    def _print_help(self):
        print("ЛКМ=positive | ПКМ=negative | Space=новая линия | N=вариант | Bksp=удалить | S=save | D=skip | R=reset | Q=quit\n")

    def _reset_state(self):
        self.masks: list[MaskEntry] = []
        self.current_edit: MaskEntry | None = None

    def _predict(self, pos_points, neg_points):
        points = pos_points + neg_points
        labels = [1] * len(pos_points) + [0] * len(neg_points)
        masks, scores, _ = self.predictor.predict(
            point_coords=np.array(points), point_labels=np.array(labels), multimask_output=True)
        order = np.argsort(-scores)
        return masks[order], scores[order]

    def _finalize_current(self):
        if self.current_edit is not None and self.current_edit.mask is not None:
            self.masks.append(self.current_edit)
            print(f"  ✓ Линия {len(self.masks)} завершена")
        self.current_edit = None

    def _render(self) -> np.ndarray:
        img = self.orig_img.copy()
        all_masks = list(self.masks)
        editing_idx = None
        if self.current_edit is not None and self.current_edit.mask is not None:
            editing_idx = len(all_masks)
            all_masks.append(self.current_edit)

        for i, me in enumerate(all_masks):
            if me.mask is None: continue
            is_editing = (i == editing_idx)
            color = EDITING_COLOR if is_editing else MASK_COLORS[i % len(MASK_COLORS)]

            overlay = img.copy()
            overlay[me.mask] = color
            img = cv2.addWeighted(overlay, MASK_ALPHA, img, 1 - MASK_ALPHA, 0)
            mask_u8 = (me.mask * 255).astype(np.uint8)
            contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(img, contours, -1, color, 2 if is_editing else 1)

            cx, cy = me.point
            lbl = f"{'*' if is_editing else ''}{i+1}"
            cv2.putText(img, lbl, (cx - 5, cy - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
            cv2.circle(img, (cx, cy), 3, color, -1)
            for np_ in me.neg_points:
                cv2.circle(img, (np_[0], np_[1]), 3, (0, 0, 255), -1)

        display = cv2.resize(img, None, fx=DISPLAY_SCALE, fy=DISPLAY_SCALE, interpolation=cv2.INTER_LINEAR)
        h = display.shape[0]
        editing = " [EDITING]" if self.current_edit else ""
        cv2.putText(display, f"LINES | Segments:{len(self.masks)}{editing} | Space=next S=save", (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        return display

    def _interact(self) -> str:
        while True:
            cv2.imshow("SAM Labeler", self._render())
            key = cv2.waitKey(30) & 0xFF
            if key == ord("s") or key == ord("S"):
                self._finalize_current()
                if not self.masks:
                    print("  ⚠ Нет масок!"); continue
                return "save"
            elif key == ord("d") or key == ord("D"): return "skip"
            elif key == ord("q") or key == ord("Q"): return "quit"
            elif key == ord("r") or key == ord("R"):
                self.masks = []; self.current_edit = None; print("  Reset")
            elif key == 32:  # Space
                self._finalize_current(); print("  Новая линия")
            elif key == ord("n") or key == ord("N"):
                me = self.current_edit
                if me and me.all_masks is not None:
                    me.variant = (me.variant + 1) % len(me.all_masks)
                    me.mask = me.all_masks[me.variant]
                    print(f"  Вариант {me.variant + 1}/{len(me.all_masks)}")
            elif key == 8 or key == 127:
                if self.current_edit: self.current_edit = None; print("  Текущая удалена")
                elif self.masks: self.masks.pop(); print(f"  Удалена ({len(self.masks)})")

    def _mouse_callback(self, event, x, y, flags, param):
        if self.orig_img is None: return
        ox, oy = x // DISPLAY_SCALE, y // DISPLAY_SCALE
        h, w = self.orig_img.shape[:2]
        if ox < 0 or ox >= w or oy < 0 or oy >= h: return

        if event == cv2.EVENT_LBUTTONDOWN:
            if self.current_edit is None:
                masks, scores = self._predict([[ox, oy]], [])
                me = MaskEntry(mask=masks[0], point=[ox, oy])
                me.all_masks = masks
                self.current_edit = me
                print(f"  + Новая линия ({scores[0]:.2f})")
            else:
                me = self.current_edit
                me.pos_points.append([ox, oy]); me.point = [ox, oy]
                masks, scores = self._predict(me.pos_points, me.neg_points)
                me.all_masks = masks; me.variant = min(me.variant, len(masks)-1); me.mask = masks[me.variant]
                print(f"  + Positive ({scores[me.variant]:.2f})")
        elif event == cv2.EVENT_RBUTTONDOWN:
            if self.current_edit:
                me = self.current_edit; me.neg_points.append([ox, oy])
                masks, scores = self._predict(me.pos_points, me.neg_points)
                me.all_masks = masks; me.variant = min(me.variant, len(masks)-1); me.mask = masks[me.variant]
                print(f"  - Negative ({scores[me.variant]:.2f})")

    def _save(self, entry: dict):
        self._finalize_current()
        screenshot = entry["screenshot"]
        h, w = self.orig_img.shape[:2]

        mask_files = []
        for i, me in enumerate(self.masks):
            mask_name = screenshot.replace(".png", f"_line_{i}.png")
            cv2.imwrite(str(MASKS_DIR / mask_name), (me.mask * 255).astype(np.uint8))
            mask_files.append(mask_name)

        combined = np.zeros((h, w), dtype=np.uint8)
        for i, me in enumerate(self.masks):
            combined[me.mask] = i + 1
        combined_name = screenshot.replace(".png", "_lines_combined.png")
        cv2.imwrite(str(MASKS_DIR / combined_name), combined)

        label = {
            "mode": "lines", "screenshot": screenshot, "masks": mask_files,
            "combined_mask": combined_name, "num_lines": len(self.masks),
            "points": [me.point for me in self.masks],
            "prompt": entry.get("prompt", ""),
        }
        with open(LABELS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(label, ensure_ascii=False) + "\n")
        self.labeled.add(screenshot)


# ── Detect mode (grid captchas) ──────────────────────────────────────

class DetectLabeler(BaseSAMLabeler):
    """Детекция ячеек для grid-captchas. ЛКМ drag = bbox, C = correct."""

    def _print_help(self):
        print("ЛКМ-drag=bbox | C=correct | Bksp=удалить | S=save | D=skip | R=reset | Q=quit\n")

    def _reset_state(self):
        self.bboxes: list[BboxEntry] = []
        self.drawing = False
        self.draw_start: tuple[int, int] | None = None
        self.draw_current: tuple[int, int] | None = None

    def _render(self) -> np.ndarray:
        img = self.orig_img.copy()

        for i, bb in enumerate(self.bboxes):
            color = BBOX_CORRECT_COLOR if bb.is_correct else BBOX_WRONG_COLOR
            cv2.rectangle(img, (bb.x1, bb.y1), (bb.x2, bb.y2), color, 2)
            label = f"{'✓' if bb.is_correct else ''}{i+1}"
            cv2.putText(img, label, (bb.x1 + 3, bb.y1 + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

        # Текущий рисуемый bbox
        if self.drawing and self.draw_start and self.draw_current:
            sx, sy = self.draw_start
            cx, cy = self.draw_current
            cv2.rectangle(img, (sx, sy), (cx, cy), BBOX_COLOR, 1)

        display = cv2.resize(img, None, fx=DISPLAY_SCALE, fy=DISPLAY_SCALE, interpolation=cv2.INTER_LINEAR)
        h = display.shape[0]
        correct = sum(1 for b in self.bboxes if b.is_correct)
        cv2.putText(display, f"DETECT | Boxes:{len(self.bboxes)} Correct:{correct} | ЛКМ-drag=bbox C=mark-correct S=save", (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        return display

    def _interact(self) -> str:
        while True:
            cv2.imshow("SAM Labeler", self._render())
            key = cv2.waitKey(30) & 0xFF
            if key == ord("s") or key == ord("S"):
                if not self.bboxes:
                    print("  ⚠ Нет bbox!"); continue
                return "save"
            elif key == ord("d") or key == ord("D"): return "skip"
            elif key == ord("q") or key == ord("Q"): return "quit"
            elif key == ord("r") or key == ord("R"):
                self.bboxes = []; print("  Reset")
            elif key == ord("c") or key == ord("C"):
                if self.bboxes:
                    self.bboxes[-1].is_correct = not self.bboxes[-1].is_correct
                    status = "CORRECT" if self.bboxes[-1].is_correct else "wrong"
                    print(f"  Box {len(self.bboxes)}: {status}")
            elif key == ord("t") or key == ord("T"):
                # Alias для C
                if self.bboxes:
                    self.bboxes[-1].is_correct = not self.bboxes[-1].is_correct
                    status = "CORRECT" if self.bboxes[-1].is_correct else "wrong"
                    print(f"  Box {len(self.bboxes)}: {status}")
            elif key == 8 or key == 127:
                if self.bboxes: self.bboxes.pop(); print(f"  Удалён ({len(self.bboxes)})")

    def _mouse_callback(self, event, x, y, flags, param):
        if self.orig_img is None: return
        ox, oy = x // DISPLAY_SCALE, y // DISPLAY_SCALE
        h, w = self.orig_img.shape[:2]
        ox = max(0, min(ox, w - 1))
        oy = max(0, min(oy, h - 1))

        if event == cv2.EVENT_LBUTTONDOWN:
            self.drawing = True
            self.draw_start = (ox, oy)
            self.draw_current = (ox, oy)
        elif event == cv2.EVENT_MOUSEMOVE and self.drawing:
            self.draw_current = (ox, oy)
        elif event == cv2.EVENT_LBUTTONUP and self.drawing:
            self.drawing = False
            if self.draw_start:
                sx, sy = self.draw_start
                # Минимальный размер bbox
                if abs(ox - sx) > 10 and abs(oy - sy) > 10:
                    bb = BboxEntry(sx, sy, ox, oy)
                    self.bboxes.append(bb)
                    print(f"  + Box {len(self.bboxes)}: ({bb.x1},{bb.y1})-({bb.x2},{bb.y2})")
            self.draw_start = None
            self.draw_current = None
        elif event == cv2.EVENT_RBUTTONDOWN:
            # Удалить bbox под курсором
            for i in range(len(self.bboxes) - 1, -1, -1):
                bb = self.bboxes[i]
                if bb.x1 <= ox <= bb.x2 and bb.y1 <= oy <= bb.y2:
                    self.bboxes.pop(i)
                    print(f"  - Удалён box ({len(self.bboxes)})")
                    break

    def _save(self, entry: dict):
        screenshot = entry["screenshot"]
        label = {
            "mode": "detect", "screenshot": screenshot,
            "bboxes": [bb.to_dict() for bb in self.bboxes],
            "num_boxes": len(self.bboxes),
            "correct_indices": [i for i, bb in enumerate(self.bboxes) if bb.is_correct],
            "prompt": entry.get("prompt", ""),
        }
        with open(LABELS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(label, ensure_ascii=False) + "\n")
        self.labeled.add(screenshot)


# ── Entry point ──────────────────────────────────────────────────────

LABELERS = {
    "figures": FiguresLabeler,
    "lines": LinesLabeler,
    "detect": DetectLabeler,
}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    ap = argparse.ArgumentParser(description="Universal SAM Captcha Labeler")
    ap.add_argument("--mode", choices=["figures", "lines", "detect"], required=True,
                    help="figures=drag-to-similar/arrows | lines=line breaks | detect=grid captchas")
    ap.add_argument("--model", default="sam_vit_b.pth", help="Путь к весам SAM")
    ap.add_argument("--model-type", default="vit_b", help="vit_h, vit_l, vit_b")
    ap.add_argument("--start", type=int, default=0, help="Начать с индекса")
    ap.add_argument("--filter", default=None, help="Фильтр по prompt (например 'drag', 'line break', 'animal')")
    args = ap.parse_args()

    # Дефолтные фильтры по моду
    if args.filter is None:
        defaults = {"figures": None, "lines": "line break", "detect": None}
        args.filter = defaults.get(args.mode)

    LabelerClass = LABELERS[args.mode]
    labeler = LabelerClass(
        model_path=args.model, model_type=args.model_type,
        start=args.start, filter_prompt=args.filter, mode=args.mode,
    )
    labeler.run()
