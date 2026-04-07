"""
Proof of Concept: сопоставление контуров фигур hCaptcha.

Берёт маски из SAM-разметки, определяет drag-элемент (нижняя фигура),
сравнивает его контур с каждой целью через cv2.matchShapes(),
выбирает наиболее похожую.

python captcha_matcher.py
python captcha_matcher.py --visualize
"""
import json
import argparse
from pathlib import Path

import cv2
import numpy as np

DATASET_DIR = Path(__file__).parent / "captcha_dataset"
MASKS_DIR = DATASET_DIR / "masks"
LABELS_FILE = DATASET_DIR / "labels.jsonl"


def load_labels() -> list[dict]:
    labels = []
    with open(LABELS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                labels.append(json.loads(line))
    return labels


def _mask_centroid(mask: np.ndarray) -> tuple[int, int] | None:
    """Центр bounding box контура маски."""
    if mask is None or mask.sum() == 0:
        return None
    contour = get_main_contour(mask)
    if contour is None:
        return None
    x, y, w, h = cv2.boundingRect(contour)
    return (x + w // 2, y + h // 2)


def get_main_contour(mask: np.ndarray) -> np.ndarray | None:
    """Извлечь самый большой контур из маски."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return max(contours, key=cv2.contourArea)


def contour_to_fourier(contour: np.ndarray, n_descriptors: int = 32) -> np.ndarray:
    """Преобразовать контур в Fourier дескрипторы (инвариантны к масштабу/повороту/сдвигу)."""
    # Контур как комплексные числа
    pts = contour.squeeze()
    if len(pts.shape) != 2 or pts.shape[0] < 4:
        return np.zeros(n_descriptors)

    complex_pts = pts[:, 0] + 1j * pts[:, 1]

    # FFT
    fft = np.fft.fft(complex_pts)

    # Нормализация: убрать DC (сдвиг), нормировать по первому ненулевому (масштаб)
    fft[0] = 0  # убрать сдвиг
    if np.abs(fft[1]) > 1e-10:
        fft = fft / np.abs(fft[1])  # нормировать масштаб

    # Взять амплитуды (инвариантны к повороту и стартовой точке)
    magnitudes = np.abs(fft[1:n_descriptors + 1])
    return magnitudes


def fourier_distance(desc1: np.ndarray, desc2: np.ndarray) -> float:
    """Расстояние между двумя наборами Fourier дескрипторов."""
    min_len = min(len(desc1), len(desc2))
    return np.linalg.norm(desc1[:min_len] - desc2[:min_len])


def contour_to_skeleton_angles(contour: np.ndarray, n_edges: int = 5) -> np.ndarray:
    """
    Описать фигуру через углы между основными рёбрами полигона.

    1. Аппроксимировать контур полигоном (approxPolyDP)
    2. Найти n_edges самых длинных рёбер
    3. Вычислить углы между последовательными рёбрами
    4. Отсортировать углы → fingerprint фигуры
    """
    pts = contour.squeeze()
    if len(pts.shape) != 2 or pts.shape[0] < 4:
        return np.zeros(n_edges)

    # Аппроксимация полигоном
    perimeter = cv2.arcLength(contour, True)
    epsilon = 0.02 * perimeter
    approx = cv2.approxPolyDP(contour, epsilon, True).squeeze()

    if len(approx.shape) != 2 or approx.shape[0] < 3:
        return np.zeros(n_edges)

    n_pts = approx.shape[0]

    # Рёбра: длина + направление
    edges = []
    for i in range(n_pts):
        p1 = approx[i]
        p2 = approx[(i + 1) % n_pts]
        dx = float(p2[0] - p1[0])
        dy = float(p2[1] - p1[1])
        length = np.sqrt(dx * dx + dy * dy)
        angle = np.arctan2(dy, dx)  # -pi..pi
        edges.append((length, angle, i))

    # Сортировать по длине (самые длинные = основные)
    edges.sort(key=lambda e: -e[0])
    top_edges = edges[:n_edges]

    # Углы между последовательными рёбрами полигона (в вершинах)
    vertex_angles = []
    for i in range(n_pts):
        p0 = approx[(i - 1) % n_pts].astype(float)
        p1 = approx[i].astype(float)
        p2 = approx[(i + 1) % n_pts].astype(float)

        v1 = p0 - p1
        v2 = p2 - p1

        cos_a = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-10)
        cos_a = np.clip(cos_a, -1, 1)
        angle = np.arccos(cos_a)  # 0..pi
        vertex_angles.append(angle)

    # Отсортировать углы → инвариант к повороту и стартовой точке
    vertex_angles.sort()

    # Взять n_edges углов (самые характерные)
    result = np.zeros(n_edges)
    for i in range(min(n_edges, len(vertex_angles))):
        result[i] = vertex_angles[i]

    return result


def skeleton_distance(desc1: np.ndarray, desc2: np.ndarray) -> float:
    """Расстояние между skeleton angle descriptors."""
    return np.linalg.norm(desc1 - desc2)


def match_contours(drag_contour: np.ndarray, target_contours: list[np.ndarray]) -> list[float]:
    """Сравнить drag-контур с каждым target. Fourier + Hu."""
    drag_fd = contour_to_fourier(drag_contour)

    scores = []
    for tc in target_contours:
        if tc is None:
            scores.append(float('inf'))
            continue
        target_fd = contour_to_fourier(tc)

        fd_score = fourier_distance(drag_fd, target_fd)
        hu_score = cv2.matchShapes(drag_contour, tc, cv2.CONTOURS_MATCH_I1, 0)

        combined = 0.7 * fd_score + 0.3 * hu_score
        scores.append(combined)
    return scores


def extract_shape_features(mask: np.ndarray, contour: np.ndarray) -> dict:
    """Дополнительные фичи формы для улучшения матчинга."""
    area = cv2.contourArea(contour)
    perimeter = cv2.arcLength(contour, True)
    x, y, w, h = cv2.boundingRect(contour)
    aspect_ratio = w / max(h, 1)

    # Hu Moments
    moments = cv2.moments(contour)
    hu = cv2.HuMoments(moments).flatten()

    # Solidity (area / convex hull area)
    hull = cv2.convexHull(contour)
    hull_area = cv2.contourArea(hull)
    solidity = area / max(hull_area, 1)

    # Circularity
    circularity = (4 * np.pi * area) / max(perimeter ** 2, 1)

    return {
        "area": area,
        "perimeter": perimeter,
        "aspect_ratio": aspect_ratio,
        "solidity": solidity,
        "circularity": circularity,
        "hu_moments": hu,
        "bbox": (x, y, w, h),
    }


def combined_similarity(drag_features: dict, target_features: dict, match_shape_score: float) -> float:
    """Комбинированная метрика похожести (меньше = лучше)."""
    # matchShapes (основная метрика)
    w_shape = 1.0

    # Разница aspect ratio
    ar_diff = abs(drag_features["aspect_ratio"] - target_features["aspect_ratio"])
    w_ar = 0.3

    # Разница solidity
    sol_diff = abs(drag_features["solidity"] - target_features["solidity"])
    w_sol = 0.2

    # Разница circularity
    circ_diff = abs(drag_features["circularity"] - target_features["circularity"])
    w_circ = 0.2

    return w_shape * match_shape_score + w_ar * ar_diff + w_sol * sol_diff + w_circ * circ_diff


def process_one(label: dict, visualize: bool = False) -> dict:
    """Обработать одну капчу."""
    screenshot = label["screenshot"]
    mask_files = label["masks"]
    points = label["points"]
    num_masks = label["num_masks"]

    if num_masks < 2:
        return {"error": "Меньше 2 масок", "screenshot": screenshot}

    # Определить папку с данными
    ds_dir = DATASET_DIR
    if not (ds_dir / screenshot).exists():
        # Попробуем captcha_dataset_v2
        alt_dir = DATASET_DIR.parent / "captcha_dataset_v2"
        if (alt_dir / screenshot).exists():
            ds_dir = alt_dir

    # Загрузить оригинал
    img = cv2.imread(str(ds_dir / screenshot))
    if img is None:
        return {"error": f"Image not found: {screenshot}"}

    h, w = img.shape[:2]

    # Загрузить маски
    masks = []
    for mf in mask_files:
        m = cv2.imread(str(MASKS_DIR / mf), cv2.IMREAD_GRAYSCALE)
        if m is not None:
            masks.append(m)
        else:
            masks.append(np.zeros((h, w), dtype=np.uint8))

    # Определить drag-элемент
    drag_bbox = label.get("drag_bbox")
    if drag_bbox:
        # drag_bbox = [x1, y1, x2, y2] — найти маску, центр которой внутри bbox
        bx1, by1, bx2, by2 = drag_bbox
        drag_idx = -1
        for i, pt in enumerate(points):
            if bx1 <= pt[0] <= bx2 and by1 <= pt[1] <= by2:
                drag_idx = i
                break
        if drag_idx == -1:
            # Fallback: самая нижняя
            drag_idx = max(range(len(points)), key=lambda i: points[i][1])
    else:
        # Старый формат: самая нижняя точка (max y)
        drag_idx = max(range(len(points)), key=lambda i: points[i][1])

    drag_mask = masks[drag_idx]
    drag_contour = get_main_contour(drag_mask)

    if drag_contour is None:
        return {"error": "Drag contour not found", "screenshot": screenshot}

    drag_features = extract_shape_features(drag_mask, drag_contour)

    # Цели: все кроме drag
    target_indices = [i for i in range(num_masks) if i != drag_idx]
    target_contours = []
    target_features_list = []

    for ti in target_indices:
        tc = get_main_contour(masks[ti])
        target_contours.append(tc)
        if tc is not None:
            target_features_list.append(extract_shape_features(masks[ti], tc))
        else:
            target_features_list.append(None)

    # matchShapes scores
    shape_scores = match_contours(drag_contour, target_contours)

    # Combined scores
    combined_scores = []
    for i, (ss, tf) in enumerate(zip(shape_scores, target_features_list)):
        if tf is None:
            combined_scores.append(float('inf'))
        else:
            combined_scores.append(combined_similarity(drag_features, tf, ss))

    # Лучшее совпадение
    best_local_idx = np.argmin(combined_scores)
    best_global_idx = target_indices[best_local_idx]
    best_score = combined_scores[best_local_idx]

    # Центры масс масок (а не точки клика)
    drag_center = _mask_centroid(masks[drag_idx])
    best_center = _mask_centroid(masks[best_global_idx])
    best_point = list(best_center) if best_center else points[best_global_idx]
    drag_point = list(drag_center) if drag_center else points[drag_idx]

    result = {
        "screenshot": screenshot,
        "drag_idx": drag_idx,
        "drag_point": drag_point,
        "best_match_idx": best_global_idx,
        "best_match_point": best_point,
        "best_score": best_score,
        "all_scores": {target_indices[i]: round(combined_scores[i], 4) for i in range(len(target_indices))},
        "shape_scores": {target_indices[i]: round(shape_scores[i], 4) for i in range(len(target_indices))},
    }

    if visualize:
        vis = img.copy()
        overlay = vis.copy()

        # ── 1. Полупрозрачные маски ──
        for i in range(num_masks):
            if masks[i] is None or masks[i].sum() == 0:
                continue
            mask_bool = masks[i] > 127

            if i == drag_idx:
                overlay[mask_bool] = (0, 165, 255)  # оранжевый
            elif i == best_global_idx:
                overlay[mask_bool] = (0, 255, 0)    # зелёный
            else:
                overlay[mask_bool] = (180, 180, 180)  # серый

        vis = cv2.addWeighted(overlay, 0.35, vis, 0.65, 0)

        # ── 2. Контуры ──
        for i in range(num_masks):
            c = get_main_contour(masks[i])
            if c is None:
                continue
            if i == drag_idx:
                cv2.drawContours(vis, [c], -1, (0, 165, 255), 2)
            elif i == best_global_idx:
                cv2.drawContours(vis, [c], -1, (0, 255, 0), 2)
            else:
                cv2.drawContours(vis, [c], -1, (200, 200, 200), 1)

        # ── 3. Кривая drag (Bezier) от центра drag к центру best ──
        dp = drag_point
        bp = best_point

        # Контрольная точка для кривой (немного выше середины)
        mid_x = (dp[0] + bp[0]) // 2
        mid_y = min(dp[1], bp[1]) - 40
        ctrl = (mid_x, mid_y)

        # Рисуем кривую Безье
        n_pts = 50
        curve_pts = []
        for t_i in range(n_pts + 1):
            t = t_i / n_pts
            x = int((1-t)**2 * dp[0] + 2*(1-t)*t * ctrl[0] + t**2 * bp[0])
            y = int((1-t)**2 * dp[1] + 2*(1-t)*t * ctrl[1] + t**2 * bp[1])
            curve_pts.append((x, y))

        for j in range(len(curve_pts) - 1):
            # Градиент цвета: оранжевый → зелёный
            t = j / max(len(curve_pts) - 1, 1)
            r = int(0 * (1-t) + 0 * t)
            g = int(165 * (1-t) + 255 * t)
            b = int(255 * (1-t) + 0 * t)
            cv2.line(vis, curve_pts[j], curve_pts[j+1], (r, g, b), 2, cv2.LINE_AA)

        # Наконечник стрелки
        if len(curve_pts) >= 2:
            cv2.arrowedLine(vis, curve_pts[-3], curve_pts[-1], (0, 255, 0), 2, tipLength=0.5, line_type=cv2.LINE_AA)

        # ── 4. Точки старта/финиша ──
        # Drag point (оранжевый круг)
        cv2.circle(vis, (dp[0], dp[1]), 8, (0, 165, 255), 2, cv2.LINE_AA)
        cv2.circle(vis, (dp[0], dp[1]), 3, (0, 165, 255), -1, cv2.LINE_AA)

        # Best point (зелёный круг)
        cv2.circle(vis, (bp[0], bp[1]), 8, (0, 255, 0), 2, cv2.LINE_AA)
        cv2.circle(vis, (bp[0], bp[1]), 3, (0, 255, 0), -1, cv2.LINE_AA)

        # ── 5. Score badge на best ──
        score_text = f"{best_score:.2f}"
        (tw, th), _ = cv2.getTextSize(score_text, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
        badge_x = bp[0] - tw // 2
        badge_y = bp[1] - 15
        cv2.rectangle(vis, (badge_x - 3, badge_y - th - 3), (badge_x + tw + 3, badge_y + 3), (0, 0, 0), -1)
        cv2.putText(vis, score_text, (badge_x, badge_y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1, cv2.LINE_AA)

        # ── 6. Увеличить ──
        vis = cv2.resize(vis, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
        out_path = str(DATASET_DIR / screenshot.replace(".png", "_match.png"))
        cv2.imwrite(out_path, vis)
        print(f"  Viz: {out_path}")

    return result


def main():
    ap = argparse.ArgumentParser(description="Captcha Contour Matcher PoC")
    ap.add_argument("--visualize", action="store_true", help="Сохранить визуализации")
    args = ap.parse_args()

    labels = load_labels()
    print(f"Загружено {len(labels)} размеченных капч\n")

    for label in labels:
        result = process_one(label, visualize=args.visualize)

        if "error" in result:
            print(f"  SKIP {result['screenshot']}: {result['error']}")
            continue

        print(f"[{result['screenshot']}]")
        print(f"  Drag: mask {result['drag_idx']} @ {result['drag_point']}")
        print(f"  Best: mask {result['best_match_idx']} @ {result['best_match_point']} (score={result['best_score']:.4f})")
        print(f"  Scores: {result['all_scores']}")
        print()


if __name__ == "__main__":
    main()
