# -*- coding: utf-8 -*-
"""
OpenCV solver for "Please click on the line ends" hCaptcha.
Uses color-separated Zhang-Suen skeletonization to find 2 endpoints per line.
Usage: python solve_line_ends.py <screenshot.png>
"""
import sys
import cv2
import numpy as np


def find_line_endpoints(image_path, debug=True):
    img = cv2.imread(str(image_path))
    if img is None:
        print(f"Cannot load image: {image_path}")
        return []

    h, w = img.shape[:2]
    # Crop to challenge image area (skip banner and borders)
    if h > 300:
        top, bot, left, right = 110, h - 80, 30, w - 20
        img_crop = img[top:bot, left:right]
    else:
        top, bot, left, right = 0, h, 0, w
        img_crop = img

    ch, cw = img_crop.shape[:2]

    # Convert to float for color math
    b = img_crop[:, :, 0].astype(float)
    g = img_crop[:, :, 1].astype(float)
    r = img_crop[:, :, 2].astype(float)

    # Separate the two lines by color:
    # Brown/dark-red line: R dominant
    # Blue/navy line: B dominant
    # Both are dark (low overall brightness) — exclude bright background
    brightness = (b + g + r) / 3.0
    dark_mask = brightness < 130

    brown_mask = dark_mask & (r > g) & (r > b) & (r > 50)
    blue_mask  = dark_mask & (b >= r) & (b >= g) & (b > 50)

    brown_bin = (brown_mask.astype(np.uint8)) * 255
    blue_bin  = (blue_mask.astype(np.uint8)) * 255

    if debug:
        dbg_path = str(image_path).replace(".png", "_masks.png")
        side = np.zeros((ch, cw * 2, 3), np.uint8)
        side[:, :cw] = cv2.merge([brown_bin, np.zeros_like(brown_bin), np.zeros_like(brown_bin)])
        side[:, cw:] = cv2.merge([np.zeros_like(blue_bin), np.zeros_like(blue_bin), blue_bin])
        cv2.imwrite(dbg_path, side)
        print(f"Debug masks saved: {dbg_path}")

    # Morphological close to fill gaps in lines
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    brown_bin = cv2.morphologyEx(brown_bin, cv2.MORPH_CLOSE, kernel)
    blue_bin  = cv2.morphologyEx(blue_bin,  cv2.MORPH_CLOSE, kernel)

    # Remove small noise
    brown_bin = _remove_small(brown_bin, min_area=300)
    blue_bin  = _remove_small(blue_bin,  min_area=300)

    # Zhang-Suen skeletonize each color channel
    skel_brown = _zhang_suen(brown_bin)
    skel_blue  = _zhang_suen(blue_bin)

    # Find endpoints (1 neighbor → sum==2 including self)
    eps_brown = _find_endpoints(skel_brown)
    eps_blue  = _find_endpoints(skel_blue)

    # Cluster nearby endpoints
    eps_brown = _cluster_points(eps_brown, radius=20)
    eps_blue  = _cluster_points(eps_blue,  radius=20)

    # Remove endpoints too close to the crop border (frame artifacts)
    margin = 15
    eps_brown = [(x, y) for x, y in eps_brown if margin < x < cw - margin and margin < y < ch - margin]
    eps_blue  = [(x, y) for x, y in eps_blue  if margin < x < cw - margin and margin < y < ch - margin]

    # Keep only the 2 farthest-apart endpoints per line (true line ends)
    eps_brown = _pick_two_endpoints(eps_brown)
    eps_blue  = _pick_two_endpoints(eps_blue)

    all_eps = eps_brown + eps_blue

    # Convert crop coords back to full image coords
    result = [(x + left, y + top) for x, y in all_eps]

    if debug:
        vis = img.copy()
        colors = [(0, 80, 200), (0, 80, 200), (0, 160, 0), (0, 160, 0)]
        labels = ["B1", "B2", "Br1", "Br2"]
        for i, (x, y) in enumerate(result):
            c = colors[i] if i < len(colors) else (255, 0, 255)
            cv2.circle(vis, (x, y), 14, c, 3)
            cv2.circle(vis, (x, y), 4, c, -1)
            cv2.putText(vis, labels[i] if i < len(labels) else str(i),
                        (x + 10, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, c, 2)
        out_path = str(image_path).replace(".png", "_result.png")
        cv2.imwrite(out_path, vis)
        print(f"Result image saved: {out_path}")
        print(f"\nFound {len(result)} endpoints:")
        for i, (x, y) in enumerate(result):
            name = "blue" if i < 2 else "brown"
            print(f"  [{i+1}] {name}: x={x}, y={y}")

    return result


def _remove_small(binary, min_area=300):
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
    out = np.zeros_like(binary)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            out[labels == i] = 255
    return out


def _zhang_suen(binary):
    """Zhang-Suen thinning algorithm."""
    img = (binary > 0).astype(np.uint8)
    changed = True
    while changed:
        changed = False
        for step in [1, 2]:
            p = np.pad(img, 1, constant_values=0)
            p2 = p[0:-2, 1:-1].astype(int)
            p3 = p[0:-2, 2:  ].astype(int)
            p4 = p[1:-1, 2:  ].astype(int)
            p5 = p[2:,   2:  ].astype(int)
            p6 = p[2:,   1:-1].astype(int)
            p7 = p[2:,   0:-2].astype(int)
            p8 = p[1:-1, 0:-2].astype(int)
            p9 = p[0:-2, 0:-2].astype(int)

            B = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
            nb = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
            A = sum((nb[i] == 0) & (nb[i + 1] == 1) for i in range(8))

            cond_B = (B >= 2) & (B <= 6)
            cond_A = (A == 1)
            if step == 1:
                c3 = (p2 * p4 * p6 == 0)
                c4 = (p4 * p6 * p8 == 0)
            else:
                c3 = (p2 * p4 * p8 == 0)
                c4 = (p2 * p6 * p8 == 0)

            rm = (img > 0) & cond_B & cond_A & c3 & c4
            if rm.any():
                img[rm] = 0
                changed = True
    return img * 255


def _find_endpoints(skeleton):
    """Return list of (x, y) endpoint pixels (exactly 1 neighbor in 8-conn)."""
    skel_bin = (skeleton > 0).astype(np.uint8)
    kernel = np.ones((3, 3), np.float32)
    neighbor_count = cv2.filter2D(skel_bin.astype(np.float32), -1, kernel)
    # Endpoint: pixel itself + exactly 1 neighbor → sum == 2
    endpoint_mask = (skel_bin == 1) & (neighbor_count == 2)
    ys, xs = np.where(endpoint_mask)
    return list(zip(xs.tolist(), ys.tolist()))


def _cluster_points(points, radius=20):
    """Merge nearby points into centroids."""
    if not points:
        return []
    points = list(points)
    used = [False] * len(points)
    clusters = []
    for i, p in enumerate(points):
        if used[i]:
            continue
        group = [p]
        used[i] = True
        for j, q in enumerate(points):
            if not used[j]:
                if abs(p[0] - q[0]) <= radius and abs(p[1] - q[1]) <= radius:
                    group.append(q)
                    used[j] = True
        cx = int(sum(g[0] for g in group) / len(group))
        cy = int(sum(g[1] for g in group) / len(group))
        clusters.append((cx, cy))
    return clusters


def _pick_two_endpoints(points):
    """Return the 2 points with maximum distance between them."""
    if len(points) <= 2:
        return points
    best = (0, None, None)
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            d = (points[i][0] - points[j][0]) ** 2 + (points[i][1] - points[j][1]) ** 2
            if d > best[0]:
                best = (d, points[i], points[j])
    return [best[1], best[2]] if best[1] is not None else points[:2]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python solve_line_ends.py <captcha_screenshot.png>")
        sys.exit(1)
    find_line_endpoints(sys.argv[1])
