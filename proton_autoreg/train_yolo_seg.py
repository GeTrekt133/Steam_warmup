"""
Конвертация SAM-разметки в YOLO формат + обучение YOLO11-seg.

1. Конвертирует маски из labels.jsonl → YOLO polygon format
2. Создаёт dataset.yaml
3. Запускает обучение YOLO11-seg

Формат YOLO segmentation (один .txt на изображение):
  class_id x1 y1 x2 y2 ... xN yN  (нормализованные координаты полигона)

4 отдельные модели:
  --task figures   → class 0: figure (drag-to-similar)
  --task puzzles   → class 0: puzzle_piece (matching half)
  --task letters   → class 0: letter (drag letter)
  --task arrows    → class 0: arrow (circular pattern)

python train_yolo_seg.py --task figures
python train_yolo_seg.py --task arrows
python train_yolo_seg.py --task puzzles
python train_yolo_seg.py --task letters
python train_yolo_seg.py --task figures --convert-only
python train_yolo_seg.py --task figures --train-only
"""
import json
import shutil
import random
import argparse
import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DATASET_DIR = BASE_DIR / "captcha_dataset"
MASKS_DIR = DATASET_DIR / "masks"
LABELS_FILE = DATASET_DIR / "labels.jsonl"

DATASET_DIRS = [
    BASE_DIR / "captcha_dataset",
    BASE_DIR / "captcha_dataset_v2",
]

# ── Конфиг задач ─────────────────────────────────────────────────────

TASK_CONFIG = {
    "figures": {
        "classes": {0: "move", 1: "figure"},
        "prompt_filters": ["similar", "most similar"],
        "yolo_dir": BASE_DIR / "yolo_figures",
        "run_name": "captcha_figures",
    },
    "puzzles": {
        "classes": {0: "move", 1: "puzzle_piece"},
        "prompt_filters": ["piece", "half", "matching half"],
        "yolo_dir": BASE_DIR / "yolo_puzzles",
        "run_name": "captcha_puzzles",
    },
    "letters": {
        "classes": {0: "move", 1: "letter"},
        "prompt_filters": ["letter", "fits"],
        "yolo_dir": BASE_DIR / "yolo_letters",
        "run_name": "captcha_letters",
    },
    "arrows": {
        "classes": {0: "arrow"},  # стрелки — один класс, move не нужен
        "prompt_filters": ["arrow", "pattern", "circular"],
        "yolo_dir": BASE_DIR / "yolo_arrows",
        "run_name": "captcha_arrows",
    },
}


# ── Конвертация ──────────────────────────────────────────────────────

def mask_to_polygon(mask: np.ndarray, simplify_epsilon: float = 2.0) -> list[list[float]] | None:
    """
    Конвертировать бинарную маску в нормализованный полигон для YOLO.

    Returns:
        [[x1, y1, x2, y2, ...], ...] — нормализованные координаты (0-1)
        или None если контур не найден
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Берём самый большой контур
    contour = max(contours, key=cv2.contourArea)

    # Минимальная площадь
    if cv2.contourArea(contour) < 50:
        return None

    # Упрощаем полигон
    contour = cv2.approxPolyDP(contour, simplify_epsilon, True)

    # Минимум 3 точки
    if len(contour) < 3:
        return None

    h, w = mask.shape[:2]
    points = contour.squeeze()

    # Нормализация (0-1)
    normalized = []
    for pt in points:
        normalized.append(float(pt[0]) / w)
        normalized.append(float(pt[1]) / h)

    return normalized


def convert_to_yolo(task: str, val_split: float = 0.2, seed: int = 42):
    """Конвертировать SAM-разметку в YOLO формат для конкретной задачи."""
    cfg = TASK_CONFIG[task]
    yolo_dir = cfg["yolo_dir"]
    prompt_filters = cfg["prompt_filters"]

    images_train = yolo_dir / "images" / "train"
    images_val = yolo_dir / "images" / "val"
    labels_train = yolo_dir / "labels" / "train"
    labels_val = yolo_dir / "labels" / "val"
    yaml_path = yolo_dir / "dataset.yaml"

    # Очистить старые данные
    if yolo_dir.exists():
        shutil.rmtree(yolo_dir)

    for d in [images_train, images_val, labels_train, labels_val]:
        d.mkdir(parents=True, exist_ok=True)

    # Загрузить labels и фильтровать по prompt
    labels = []
    with open(LABELS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)

            if entry.get("mode") != "figures":
                continue
            if entry.get("num_masks", 0) < 2:
                continue

            prompt = entry.get("prompt", "").lower()
            if not any(pf in prompt for pf in prompt_filters):
                continue

            labels.append(entry)

    if not labels:
        print(f"Нет данных для задачи '{task}'!")
        print(f"  Фильтры: {prompt_filters}")
        return

    # Shuffle + split
    random.seed(seed)
    random.shuffle(labels)
    split_idx = max(1, int(len(labels) * (1 - val_split)))
    train_labels = labels[:split_idx]
    val_labels = labels[split_idx:] if split_idx < len(labels) else labels[:1]

    print(f"Task: {task} (classes: {cfg['classes']})")
    print(f"Всего: {len(labels)} | Train: {len(train_labels)} | Val: {len(val_labels)}")

    # Конвертация
    train_ok = _convert_split(train_labels, images_train, labels_train, "train", task)
    val_ok = _convert_split(val_labels, images_val, labels_val, "val", task)

    print(f"Сконвертировано: train={train_ok} val={val_ok}")

    # Создать dataset.yaml
    classes = cfg["classes"]
    names_str = "\n".join(f"  {k}: {v}" for k, v in classes.items())
    yaml_content = f"""path: {yolo_dir.resolve()}
train: images/train
val: images/val

names:
{names_str}
"""
    with open(yaml_path, "w") as f:
        f.write(yaml_content)

    print(f"Dataset YAML: {yaml_path}")


def _convert_split(labels: list[dict], images_dir: Path, labels_dir: Path, split_name: str, task: str) -> int:
    """Конвертировать один split (train/val)."""
    cfg = TASK_CONFIG[task]
    has_move_class = 0 in cfg["classes"] and cfg["classes"][0] == "move"
    figure_class_id = 1 if has_move_class else 0
    ok = 0

    for entry in labels:
        screenshot = entry["screenshot"]
        mask_files = entry.get("masks", [])
        drag_bbox = entry.get("drag_bbox")  # [x1, y1, x2, y2] или None
        points = entry.get("points", [])

        # Найти исходное изображение
        img_path = _find_image(screenshot)
        if img_path is None:
            logger.warning(f"Image not found: {screenshot}")
            continue

        # Получить размеры изображения
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        img_h, img_w = img.shape[:2]

        # Копировать изображение
        dst_img = images_dir / screenshot
        shutil.copy2(img_path, dst_img)

        label_lines = []

        # Определить какая маска = move (внутри drag_bbox)
        move_mask_idx = -1
        if has_move_class and drag_bbox:
            bx1, by1, bx2, by2 = drag_bbox
            for i, pt in enumerate(points):
                if bx1 <= pt[0] <= bx2 and by1 <= pt[1] <= by2:
                    move_mask_idx = i
                    break

        # Конвертировать маски
        for i, mask_file in enumerate(mask_files):
            mask_path = MASKS_DIR / mask_file
            if not mask_path.exists():
                continue

            mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
            if mask is None:
                continue

            polygon = mask_to_polygon(mask)
            if polygon is None:
                continue

            # Определить class_id
            if has_move_class and i == move_mask_idx:
                class_id = 0  # move
            else:
                class_id = figure_class_id  # figure / puzzle / letter / arrow

            coords_str = " ".join(f"{v:.6f}" for v in polygon)
            label_lines.append(f"{class_id} {coords_str}")

        # Если drag_bbox есть но маска move не найдена — добавить bbox как move
        if has_move_class and drag_bbox and move_mask_idx == -1:
            bx1, by1, bx2, by2 = drag_bbox
            # Bbox → нормализованный полигон (4 точки)
            nx1, ny1 = bx1 / img_w, by1 / img_h
            nx2, ny2 = bx2 / img_w, by2 / img_h
            coords_str = f"{nx1:.6f} {ny1:.6f} {nx2:.6f} {ny1:.6f} {nx2:.6f} {ny2:.6f} {nx1:.6f} {ny2:.6f}"
            label_lines.append(f"0 {coords_str}")

        if not label_lines:
            dst_img.unlink(missing_ok=True)
            continue

        label_file = labels_dir / screenshot.replace(".png", ".txt")
        with open(label_file, "w") as f:
            f.write("\n".join(label_lines) + "\n")

        ok += 1

    return ok


def _find_image(screenshot: str) -> Path | None:
    """Найти изображение в одном из датасетов."""
    for ds_dir in DATASET_DIRS:
        p = ds_dir / screenshot
        if p.exists():
            return p
    return None


# ── Обучение ─────────────────────────────────────────────────────────

def train(
    task: str,
    model_name: str = "yolo11s-seg.pt",
    epochs: int = 100,
    imgsz: int = 512,
    batch: int = 4,
    patience: int = 20,
    device: str = "",
):
    """Запустить обучение YOLO11-seg для конкретной задачи."""
    from ultralytics import YOLO

    cfg = TASK_CONFIG[task]
    yaml_path = cfg["yolo_dir"] / "dataset.yaml"
    run_name = cfg["run_name"]

    if not yaml_path.exists():
        print(f"Dataset YAML не найден: {yaml_path}")
        print(f"Сначала: python train_yolo_seg.py --task {task} --convert-only")
        return

    print(f"Task: {task} | Модель: {model_name}")
    print(f"Epochs: {epochs} | ImgSize: {imgsz} | Batch: {batch}")

    model = YOLO(model_name)

    results = model.train(
        data=str(yaml_path),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        patience=patience,
        device=device or None,
        project=str(BASE_DIR / "runs"),
        name=run_name,
        exist_ok=True,
        # Аугментации
        hsv_h=0.015,
        hsv_s=0.3,
        hsv_v=0.3,
        degrees=15.0,
        translate=0.1,
        scale=0.3,
        fliplr=0.5,
        flipud=0.0,
        mosaic=0.5,
        # Прочее
        plots=True,
        save=True,
        val=True,
    )

    print(f"\nОбучение завершено!")
    print(f"Best model: runs/{run_name}/weights/best.pt")

    return results


# ── Валидация ────────────────────────────────────────────────────────

def validate(task: str, model_path: str | None = None):
    """Запустить валидацию и показать метрики."""
    from ultralytics import YOLO

    cfg = TASK_CONFIG[task]
    if model_path is None:
        model_path = str(BASE_DIR / "runs" / cfg["run_name"] / "weights" / "best.pt")

    yaml_path = cfg["yolo_dir"] / "dataset.yaml"

    model = YOLO(model_path)
    metrics = model.val(data=str(yaml_path))

    print(f"\n===== Метрики =====")
    print(f"  mAP50 (box):  {metrics.box.map50:.3f}")
    print(f"  mAP50 (mask): {metrics.seg.map50:.3f}")
    print(f"  mAP50-95 (mask): {metrics.seg.map:.3f}")

    return metrics


# ── Inference demo ───────────────────────────────────────────────────

def demo(task: str, model_path: str | None = None, image: str | None = None):
    """Прогнать модель на одном изображении и показать результат."""
    from ultralytics import YOLO

    cfg = TASK_CONFIG[task]
    if model_path is None:
        model_path = str(BASE_DIR / "runs" / cfg["run_name"] / "weights" / "best.pt")

    model = YOLO(model_path)

    if image is None:
        val_images = list((cfg["yolo_dir"] / "images" / "val").glob("*.png"))
        if not val_images:
            print("Нет изображений для demo")
            return
        image = str(val_images[0])

    results = model(image)

    for r in results:
        print(f"Найдено {len(r.boxes)} фигур:")
        if r.masks is not None:
            for i, (box, mask) in enumerate(zip(r.boxes, r.masks)):
                conf = box.conf.item()
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                print(f"  [{i}] conf={conf:.2f} bbox=({x1:.0f},{y1:.0f},{x2:.0f},{y2:.0f})")

        # Сохранить визуализацию
        annotated = r.plot()
        out_path = str(Path(image).parent / "demo_yolo_result.png")
        cv2.imwrite(out_path, annotated)
        print(f"Визуализация: {out_path}")


# ── Entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    ap = argparse.ArgumentParser(description="YOLO11-seg для hCaptcha")
    ap.add_argument("--task", required=True, choices=list(TASK_CONFIG.keys()),
                    help="figures / puzzles / letters / arrows")
    ap.add_argument("--convert-only", action="store_true", help="Только конвертация в YOLO формат")
    ap.add_argument("--train-only", action="store_true", help="Только обучение")
    ap.add_argument("--validate", action="store_true", help="Валидация модели")
    ap.add_argument("--demo", action="store_true", help="Прогнать на одном изображении")
    ap.add_argument("--model", default="yolo11x-seg.pt", help="yolo11n-seg / yolo11s-seg / yolo11m-seg / yolo11l-seg / yolo11x-seg")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--imgsz", type=int, default=512)
    ap.add_argument("--patience", type=int, default=20, help="Early stopping patience")
    ap.add_argument("--device", default="0", help="0 = GPU, cpu = CPU")
    ap.add_argument("--image", default=None, help="Изображение для demo")
    args = ap.parse_args()

    if args.validate:
        validate(task=args.task)
    elif args.demo:
        demo(task=args.task, image=args.image)
    elif args.convert_only:
        convert_to_yolo(task=args.task)
    elif args.train_only:
        train(task=args.task, model_name=args.model, epochs=args.epochs, imgsz=args.imgsz,
              batch=args.batch, patience=args.patience, device=args.device)
    else:
        convert_to_yolo(task=args.task)
        train(task=args.task, model_name=args.model, epochs=args.epochs, imgsz=args.imgsz,
              batch=args.batch, patience=args.patience, device=args.device)
