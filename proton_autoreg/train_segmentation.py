"""
Обучение U-Net для сегментации фигур hCaptcha.

Акцент на качество контуров (boundary-weighted loss):
- Dice Loss — общее качество маски
- BCE Loss — попиксельная точность
- Boundary Loss — повышенный штраф за ошибки на краях контура

Вход: скриншот капчи (500x470 → 512x512)
Выход: бинарная маска всех фигур

python train_segmentation.py
python train_segmentation.py --epochs 100 --batch 4 --lr 1e-4
"""
import json
import argparse
import logging
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import segmentation_models_pytorch as smp

logger = logging.getLogger(__name__)

DATASET_DIR = Path(__file__).parent / "captcha_dataset"
MASKS_DIR = DATASET_DIR / "masks"
LABELS_FILE = DATASET_DIR / "labels.jsonl"
MODEL_DIR = Path(__file__).parent / "models"
IMG_SIZE = 512


# ── Dataset ──────────────────────────────────────────────────────────

class CaptchaSegDataset(Dataset):
    """Датасет для сегментации фигур."""

    def __init__(self, labels: list[dict], img_size: int = IMG_SIZE, augment: bool = False):
        self.labels = labels
        self.img_size = img_size
        self.augment = augment

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        entry = self.labels[idx]
        screenshot = entry["screenshot"]

        # Загрузить изображение
        img = cv2.imread(str(DATASET_DIR / screenshot))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # Загрузить combined mask (multi-label → binary)
        combined_mask_path = MASKS_DIR / entry["combined_mask"]
        mask = cv2.imread(str(combined_mask_path), cv2.IMREAD_GRAYSCALE)

        # Бинаризация: все фигуры (label > 0) = 1
        mask = (mask > 0).astype(np.float32)

        # Resize
        img = cv2.resize(img, (self.img_size, self.img_size), interpolation=cv2.INTER_LINEAR)
        mask = cv2.resize(mask, (self.img_size, self.img_size), interpolation=cv2.INTER_NEAREST)

        # Boundary weight map (повышенный вес на краях контура)
        boundary_weight = self._compute_boundary_weight(mask)

        # Аугментации
        if self.augment:
            img, mask, boundary_weight = self._augment(img, mask, boundary_weight)

        # Нормализация
        img = img.astype(np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1))  # HWC → CHW

        return (
            torch.from_numpy(img),
            torch.from_numpy(mask).unsqueeze(0),  # (1, H, W)
            torch.from_numpy(boundary_weight).unsqueeze(0),  # (1, H, W)
        )

    @staticmethod
    def _compute_boundary_weight(mask: np.ndarray, boundary_width: int = 5, boundary_boost: float = 10.0) -> np.ndarray:
        """
        Создать weight map с повышенным весом на границах маски.

        boundary_width: ширина полосы вокруг контура (в пикселях)
        boundary_boost: множитель веса для boundary пикселей
        """
        mask_uint8 = (mask * 255).astype(np.uint8)

        # Расширить и сузить маску
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (boundary_width * 2 + 1,) * 2)
        dilated = cv2.dilate(mask_uint8, kernel)
        eroded = cv2.erode(mask_uint8, kernel)

        # Boundary = dilated - eroded (полоса вокруг контура)
        boundary = ((dilated - eroded) > 0).astype(np.float32)

        # Weight map: 1.0 везде + boost на boundary
        weight = np.ones_like(mask, dtype=np.float32) + boundary * (boundary_boost - 1.0)

        return weight

    @staticmethod
    def _augment(img, mask, weight):
        """Простые аугментации."""
        # Random horizontal flip
        if np.random.rand() > 0.5:
            img = np.fliplr(img).copy()
            mask = np.fliplr(mask).copy()
            weight = np.fliplr(weight).copy()

        # Random brightness/contrast
        if np.random.rand() > 0.5:
            alpha = np.random.uniform(0.8, 1.2)  # contrast
            beta = np.random.uniform(-20, 20)     # brightness
            img = np.clip(alpha * img + beta, 0, 255).astype(np.uint8)

        # Random small rotation (±10°)
        if np.random.rand() > 0.5:
            angle = np.random.uniform(-10, 10)
            h, w = img.shape[:2]
            M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
            img = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REFLECT)
            mask = cv2.warpAffine(mask, M, (w, h), flags=cv2.INTER_NEAREST)
            weight = cv2.warpAffine(weight, M, (w, h), borderMode=cv2.BORDER_REFLECT)

        return img, mask, weight


# ── Losses ───────────────────────────────────────────────────────────

class DiceLoss(nn.Module):
    """Dice Loss для бинарной сегментации."""
    def __init__(self, smooth: float = 1.0):
        super().__init__()
        self.smooth = smooth

    def forward(self, pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        pred = torch.sigmoid(pred)
        pred_flat = pred.view(-1)
        target_flat = target.view(-1)
        intersection = (pred_flat * target_flat).sum()
        return 1 - (2 * intersection + self.smooth) / (pred_flat.sum() + target_flat.sum() + self.smooth)


class BoundaryWeightedBCE(nn.Module):
    """BCE с повышенным весом на boundary пикселях."""
    def forward(self, pred: torch.Tensor, target: torch.Tensor, weight: torch.Tensor) -> torch.Tensor:
        bce = nn.functional.binary_cross_entropy_with_logits(pred, target, reduction='none')
        weighted_bce = (bce * weight).mean()
        return weighted_bce


class BoundaryFocusLoss(nn.Module):
    """
    Комбинированный loss с акцентом на контуры:
    L = α * Dice + β * Weighted_BCE

    Weighted_BCE даёт x10 штраф за ошибки на краях контура.
    """
    def __init__(self, alpha: float = 0.5, beta: float = 0.5):
        super().__init__()
        self.alpha = alpha
        self.beta = beta
        self.dice = DiceLoss()
        self.weighted_bce = BoundaryWeightedBCE()

    def forward(self, pred, target, weight):
        dice_loss = self.dice(pred, target)
        bce_loss = self.weighted_bce(pred, target, weight)
        return self.alpha * dice_loss + self.beta * bce_loss


# ── Training ─────────────────────────────────────────────────────────

def load_labels() -> list[dict]:
    labels = []
    with open(LABELS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                labels.append(json.loads(line))
    return labels


def train(
    epochs: int = 50,
    batch_size: int = 2,
    lr: float = 1e-4,
    encoder: str = "resnet34",
    boundary_width: int = 5,
    boundary_boost: float = 10.0,
):
    MODEL_DIR.mkdir(exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")

    # Данные
    labels = load_labels()
    print(f"Всего размеченных: {len(labels)}")

    if len(labels) < 2:
        print("Нужно хотя бы 2 размеченных примера!")
        return

    # Train/val split (80/20)
    np.random.seed(42)
    indices = np.random.permutation(len(labels))
    split = max(1, int(len(labels) * 0.8))
    train_labels = [labels[i] for i in indices[:split]]
    val_labels = [labels[i] for i in indices[split:]] if split < len(labels) else train_labels[:1]

    print(f"Train: {len(train_labels)} | Val: {len(val_labels)}")

    train_ds = CaptchaSegDataset(train_labels, augment=True)
    val_ds = CaptchaSegDataset(val_labels, augment=False)

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=0)

    # Модель
    model = smp.Unet(
        encoder_name=encoder,
        encoder_weights="imagenet",
        in_channels=3,
        classes=1,
        activation=None,  # raw logits
    )
    model.to(device)
    print(f"Модель: U-Net + {encoder}")

    # Loss & optimizer
    criterion = BoundaryFocusLoss(alpha=0.5, beta=0.5)
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    # Метрики
    best_val_loss = float('inf')
    best_boundary_iou = 0

    for epoch in range(epochs):
        # ── Train ──
        model.train()
        train_loss = 0
        for batch_idx, (img, mask, weight) in enumerate(train_loader):
            img = img.to(device)
            mask = mask.to(device)
            weight = weight.to(device)

            pred = model(img)
            loss = criterion(pred, mask, weight)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            train_loss += loss.item()

        train_loss /= len(train_loader)

        # ── Validation ──
        model.eval()
        val_loss = 0
        val_iou = 0
        val_boundary_f1 = 0

        with torch.no_grad():
            for img, mask, weight in val_loader:
                img = img.to(device)
                mask = mask.to(device)
                weight = weight.to(device)

                pred = model(img)
                loss = criterion(pred, mask, weight)
                val_loss += loss.item()

                # IoU
                pred_bin = (torch.sigmoid(pred) > 0.5).float()
                intersection = (pred_bin * mask).sum()
                union = pred_bin.sum() + mask.sum() - intersection
                iou = (intersection + 1) / (union + 1)
                val_iou += iou.item()

                # Boundary F1 (на CPU)
                bf1 = _compute_boundary_f1(
                    pred_bin.cpu().numpy(),
                    mask.cpu().numpy(),
                    tolerance=3,
                )
                val_boundary_f1 += bf1

        val_loss /= len(val_loader)
        val_iou /= len(val_loader)
        val_boundary_f1 /= len(val_loader)

        scheduler.step()
        current_lr = scheduler.get_last_lr()[0]

        print(f"Epoch {epoch+1:3d}/{epochs} | "
              f"Train: {train_loss:.4f} | "
              f"Val: {val_loss:.4f} | "
              f"IoU: {val_iou:.3f} | "
              f"Boundary F1: {val_boundary_f1:.3f} | "
              f"LR: {current_lr:.6f}")

        # Сохранить лучшую модель (по boundary F1)
        if val_boundary_f1 > best_boundary_iou:
            best_boundary_iou = val_boundary_f1
            torch.save(model.state_dict(), str(MODEL_DIR / "captcha_seg_best.pth"))
            print(f"  ★ Лучшая модель (Boundary F1: {val_boundary_f1:.3f})")

        # Сохранить последнюю
        if (epoch + 1) % 10 == 0 or epoch == epochs - 1:
            torch.save(model.state_dict(), str(MODEL_DIR / "captcha_seg_last.pth"))

    # Сохранить конфиг
    config = {
        "encoder": encoder,
        "img_size": IMG_SIZE,
        "boundary_width": boundary_width,
        "boundary_boost": boundary_boost,
        "epochs": epochs,
        "best_boundary_f1": best_boundary_iou,
    }
    with open(MODEL_DIR / "captcha_seg_config.json", "w") as f:
        json.dump(config, f, indent=2)

    print(f"\nГотово! Лучшая модель: models/captcha_seg_best.pth (Boundary F1: {best_boundary_iou:.3f})")


def _compute_boundary_f1(pred: np.ndarray, target: np.ndarray, tolerance: int = 3) -> float:
    """
    Boundary F1: насколько точно предсказаны контуры.

    1. Извлечь контуры из pred и target
    2. Для каждой точки pred-контура: есть ли точка target-контура в пределах tolerance?
    3. Precision = доля pred-точек рядом с target-контуром
    4. Recall = доля target-точек рядом с pred-контуром
    5. F1 = harmonic mean
    """
    pred = pred.squeeze()
    target = target.squeeze()

    pred_u8 = (pred > 0.5).astype(np.uint8) * 255
    target_u8 = (target > 0.5).astype(np.uint8) * 255

    # Контуры
    pred_edges = cv2.Canny(pred_u8, 50, 150)
    target_edges = cv2.Canny(target_u8, 50, 150)

    if pred_edges.sum() == 0 or target_edges.sum() == 0:
        return 0.0

    # Distance transform
    pred_dist = cv2.distanceTransform(255 - pred_edges, cv2.DIST_L2, 3)
    target_dist = cv2.distanceTransform(255 - target_edges, cv2.DIST_L2, 3)

    # Precision: pred boundary points close to target boundary
    pred_boundary_pts = pred_edges > 0
    precision = (target_dist[pred_boundary_pts] <= tolerance).mean() if pred_boundary_pts.sum() > 0 else 0

    # Recall: target boundary points close to pred boundary
    target_boundary_pts = target_edges > 0
    recall = (pred_dist[target_boundary_pts] <= tolerance).mean() if target_boundary_pts.sum() > 0 else 0

    if precision + recall == 0:
        return 0.0

    return 2 * precision * recall / (precision + recall)


# ── Entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    ap = argparse.ArgumentParser(description="Train captcha segmentation U-Net")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--encoder", default="resnet50")
    ap.add_argument("--boundary-width", type=int, default=5, help="Ширина boundary зоны (px)")
    ap.add_argument("--boundary-boost", type=float, default=10.0, help="Множитель веса для boundary")
    args = ap.parse_args()

    train(
        epochs=args.epochs,
        batch_size=args.batch,
        lr=args.lr,
        encoder=args.encoder,
        boundary_width=args.boundary_width,
        boundary_boost=args.boundary_boost,
    )
