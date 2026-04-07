"""
Решение puzzle-капчи Proton Mail через U-Net сегментацию.
Используем обученную модель из Steam_warmup_puzzle.
"""
import re
import cv2
import numpy as np
import time
from pathlib import Path

import torch
import segmentation_models_pytorch as smp

# ── Пути ──────────────────────────────────────────────────────────────
MODEL_PATH = Path(__file__).resolve().parent.parent / "backend" / "app" / "captcha" / "models" / "puzzle_unet.pth"

# ── Координаты обрезки (скриншот iframe 682×600 → фото 350×370) ──────
CROP_TOP = 89
CROP_BOTTOM = 439
CROP_LEFT = 156
CROP_RIGHT = 526

# ── ImageNet нормализация ─────────────────────────────────────────────
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# ── Синглтон модели ───────────────────────────────────────────────────
_solver = None


def _get_solver():
    global _solver
    if _solver is None:
        print(f"    [unet] Загрузка модели: {MODEL_PATH}")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        checkpoint = torch.load(str(MODEL_PATH), map_location=device, weights_only=False)
        img_size = checkpoint.get("img_size", 256)
        encoder = checkpoint.get("encoder", "resnet34")

        model = smp.Unet(
            encoder_name=encoder,
            encoder_weights=None,
            in_channels=3,
            classes=1,
        )
        model.load_state_dict(checkpoint["model_state_dict"])
        model.to(device)
        model.eval()
        _solver = {"model": model, "device": device, "img_size": img_size}
        print(f"    [unet] Модель загружена (device={device}, size={img_size})")
    return _solver


def solve_screenshot(screenshot_bgr: np.ndarray) -> tuple[int, int, float] | None:
    """
    Принимает скриншот captcha iframe (682×600 BGR).
    Возвращает (x, y, confidence) в координатах скриншота, или None.
    """
    s = _get_solver()
    model, device, img_size = s["model"], s["device"], s["img_size"]

    h, w = screenshot_bgr.shape[:2]

    # Ресайз до 682×600 если другой размер
    if h != 600 or w != 682:
        screenshot_bgr = cv2.resize(screenshot_bgr, (682, 600))
        h, w = 600, 682

    photo = screenshot_bgr[CROP_TOP:CROP_BOTTOM, CROP_LEFT:CROP_RIGHT]
    photo_h, photo_w = photo.shape[:2]

    # Предобработка
    rgb = cv2.cvtColor(photo, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (img_size, img_size))
    tensor = resized.astype(np.float32) / 255.0
    tensor = (tensor - MEAN) / STD
    tensor = torch.from_numpy(tensor.transpose(2, 0, 1)).unsqueeze(0).to(device)

    # Inference
    with torch.no_grad():
        logits = model(tensor)
        probs = torch.sigmoid(logits).squeeze().cpu().numpy()

    # Бинарная маска
    mask = (probs > 0.5).astype(np.uint8)
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)

    if num_labels <= 1:
        print("    [unet] Маска пустая — тень не найдена")
        return None

    # Наибольший компонент (кроме фона)
    areas = stats[1:, cv2.CC_STAT_AREA]
    best_label = np.argmax(areas) + 1
    cx_resized, cy_resized = centroids[best_label]

    # Пересчёт в координаты фото
    cx_photo = cx_resized * photo_w / img_size
    cy_photo = cy_resized * photo_h / img_size

    # Confidence
    component_mask = (labels == best_label)
    confidence = float(probs[component_mask].mean())

    # В координаты скриншота iframe
    cx_out = int(round(cx_photo + CROP_LEFT))
    cy_out = int(round(cy_photo + CROP_TOP))

    print(f"    [unet] Тень: ({cx_out},{cy_out}) confidence={confidence:.3f}")
    return cx_out, cy_out, confidence


def solve_photo_direct(photo_bgr: np.ndarray) -> tuple[int, int, float] | None:
    """
    Принимает ТОЛЬКО фото пазла (без UI обвязки) в BGR.
    Подаёт напрямую в U-Net без crop. Для CV пайплайна.
    Возвращает (x, y, confidence) в координатах фото.
    """
    s = _get_solver()
    model, device, img_size = s["model"], s["device"], s["img_size"]

    photo_h, photo_w = photo_bgr.shape[:2]

    rgb = cv2.cvtColor(photo_bgr, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (img_size, img_size))
    tensor = resized.astype(np.float32) / 255.0
    tensor = (tensor - MEAN) / STD
    tensor = torch.from_numpy(tensor.transpose(2, 0, 1)).unsqueeze(0).to(device)

    with torch.no_grad():
        logits = model(tensor)
        probs = torch.sigmoid(logits).squeeze().cpu().numpy()

    mask = (probs > 0.5).astype(np.uint8)
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)

    if num_labels <= 1:
        print("    [unet] Маска пустая — тень не найдена")
        return None

    areas = stats[1:, cv2.CC_STAT_AREA]
    best_label = np.argmax(areas) + 1
    cx_resized, cy_resized = centroids[best_label]

    cx = int(round(cx_resized * photo_w / img_size))
    cy = int(round(cy_resized * photo_h / img_size))
    confidence = float(probs[labels == best_label].mean())

    print(f"    [unet-direct] Тень: ({cx},{cy}) confidence={confidence:.3f}")
    return cx, cy, confidence


def find_piece_in_canvas(canvas_img: np.ndarray) -> tuple[int, int]:
    """Находит кусочек пазла (верхний левый угол canvas) через Canny."""
    gray = cv2.cvtColor(canvas_img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    region = gray[:h // 3, :w // 3]
    edges = cv2.Canny(cv2.GaussianBlur(region, (3, 3), 0), 15, 60)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        cnt = max(contours, key=cv2.contourArea)
        M = cv2.moments(cnt)
        if M['m00'] > 0 and cv2.contourArea(cnt) > 100:
            return int(M['m10'] / M['m00']), int(M['m01'] / M['m00'])
    return w // 8, h // 8


def _find_piece_in_screenshot(screenshot: np.ndarray) -> tuple[int, int]:
    """
    Находит piece в полном скриншоте iframe (682×600).
    Piece — фигурный элемент в верхнем левом углу, частично над crop region.
    """
    gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    # Ищем в верхней левой трети скриншота
    region = gray[:h // 3, :w // 3]

    edges = cv2.Canny(cv2.GaussianBlur(region, (3, 3), 0), 15, 60)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if contours:
        # Берём самый крупный контур — это piece
        cnt = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(cnt)
        if area > 100:
            # Центр bounding box — точнее чем центр масс контура
            x, y, bw, bh = cv2.boundingRect(cnt)
            cx = x + bw // 2
            cy = y + bh // 2
            print(f"    [piece] area={area:.0f} bbox=({x},{y},{bw},{bh}) center=({cx},{cy})")
            return cx, cy

    # Fallback
    print("    [piece] контур не найден, fallback")
    return w // 6, h // 6


def _find_captcha_iframe(page):
    """Найти iframe элемент с капчей на странице."""
    for iframe_el in page.locator("iframe").all():
        try:
            src = iframe_el.get_attribute("src") or ""
            if "captcha" in src.lower():
                return iframe_el
        except Exception:
            pass
    return None


def _ensure_puzzle_visible(page):
    """Если показан экран выбора типа капчи — нажать 'Далее'. НЕ нажимает если canvas уже есть."""
    for f in page.frames:
        if 'captcha' in f.url.lower():
            # Если canvas уже есть — не трогаем
            try:
                if f.locator("canvas").count() > 0:
                    print("    [solver] Canvas уже есть")
                    return True
            except Exception:
                pass
            # Нет canvas — возможно экран выбора типа, нажимаем "Далее"
            try:
                btn = f.locator("button").filter(has_text=re.compile(r"далее|next", re.I))
                if btn.count() > 0:
                    btn.first.click(timeout=3000)
                    print("    [solver] Нажали 'Далее' (экран выбора)")
                    time.sleep(3)
            except Exception:
                pass
            # Ждём canvas
            try:
                canvas = f.locator("canvas").first
                canvas.wait_for(state="attached", timeout=8000)
                return True
            except Exception:
                pass
    return False


def get_puzzle_target(page) -> tuple | None:
    """
    Основная функция: скриншот captcha iframe → U-Net → координаты drag.
    Возвращает ((src_page_x, src_page_y), (dst_page_x, dst_page_y)) или None.
    """
    # ── 1. Убедиться что puzzle видим ──────────────────────────────────
    _ensure_puzzle_visible(page)

    # ── 2. Найти captcha iframe и сделать его скриншот (682×600) ───────
    iframe_el = _find_captcha_iframe(page)
    if not iframe_el:
        print("    [solver] captcha iframe не найден")
        return None

    try:
        iframe_box = iframe_el.bounding_box(timeout=5000)
        screenshot_bytes = iframe_el.screenshot(timeout=15000)
    except Exception as e:
        print(f"    [solver] iframe screenshot error: {e}")
        return None

    arr = np.frombuffer(screenshot_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    cv2.imwrite("debug_captcha_screenshot.png", img)
    h, w = img.shape[:2]
    print(f"    [solver] iframe screenshot: {w}x{h}")

    # ── 3. U-Net inference ─────────────────────────────────────────────
    result = solve_screenshot(img)
    if result is None:
        return None

    hole_x_ss, hole_y_ss, confidence = result

    if confidence < 0.1:
        print(f"    [solver] Confidence слишком низкий: {confidence:.3f}")
        return None

    # ── 4. Всё считаем через iframe координаты ──────────────────────────
    # iframe_box — позиция iframe на странице
    # hole_x_ss, hole_y_ss — hole в координатах скриншота iframe (682×600)
    # piece — в верхнем левом углу фото (crop region скриншота)
    # Piece coords в скриншоте: примерно CROP_LEFT + piece_x_in_photo, CROP_TOP + piece_y_in_photo

    scale_x = iframe_box['width'] / w
    scale_y = iframe_box['height'] / h

    # Piece — ищем в полном скриншоте iframe (piece ВЫШЕ crop region)
    piece_ss_x, piece_ss_y = _find_piece_in_screenshot(img)
    print(f"    [solver] Piece в screenshot: ({piece_ss_x},{piece_ss_y})")

    # В page coordinates
    src_page_x = int(iframe_box['x'] + piece_ss_x * scale_x)
    src_page_y = int(iframe_box['y'] + piece_ss_y * scale_y)
    dst_page_x = int(iframe_box['x'] + hole_x_ss * scale_x)
    dst_page_y = int(iframe_box['y'] + hole_y_ss * scale_y)

    print(f"    [solver] iframe={iframe_box['width']:.0f}x{iframe_box['height']:.0f} scale=({scale_x:.2f},{scale_y:.2f})")
    print(f"    [solver] piece_ss=({piece_ss_x},{piece_ss_y}) hole_ss=({hole_x_ss},{hole_y_ss})")
    print(f"    [solver] Drag: ({src_page_x},{src_page_y}) → ({dst_page_x},{dst_page_y})")

    # Debug визуализация на полном скриншоте
    debug = img.copy()
    cv2.circle(debug, (piece_ss_x, piece_ss_y), 8, (0, 255, 0), 2)
    cv2.circle(debug, (hole_x_ss, hole_y_ss), 8, (0, 0, 255), 2)
    cv2.arrowedLine(debug, (piece_ss_x, piece_ss_y), (hole_x_ss, hole_y_ss), (0, 200, 255), 2)
    cv2.imwrite("debug_canvas_solution.png", debug)

    return (src_page_x, src_page_y), (dst_page_x, dst_page_y)
