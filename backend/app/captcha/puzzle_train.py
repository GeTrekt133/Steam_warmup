# -*- coding: utf-8 -*-
"""
Обучение U-Net для сегментации тени пазл-капчи Proton Mail.

Использование:
  python -m app.captcha.puzzle_train [--epochs 50] [--batch 8] [--lr 1e-4]

Результат:
  app/captcha/models/puzzle_unet.pth  — веса лучшей модели (по val Dice)
"""

import sys
import json
import random
import argparse
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

import segmentation_models_pytorch as smp
from torchvision import transforms as T

# ── Пути ──────────────────────────────────────────────────────────────
DATASET_DIR = Path(__file__).resolve().parents[3] / "datasets" / "puzzle"
IMAGES_DIR = DATASET_DIR / "images"
MASKS_DIR = DATASET_DIR / "masks"
SPLITS_FILE = DATASET_DIR / "splits.json"
MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_PATH = MODEL_DIR / "puzzle_unet.pth"

# ── Параметры по умолчанию ────────────────────────────────────────────
IMG_SIZE = 256
ENCODER = "resnet34"
ENCODER_WEIGHTS = "imagenet"


# ── Dataset ───────────────────────────────────────────────────────────
class PuzzleDataset(Dataset):
    def __init__(self, image_names: list[str], augment: bool = False):
        self.image_names = image_names
        self.augment = augment

        self.normalize = T.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225],
        )

    def __len__(self):
        return len(self.image_names)

    def __getitem__(self, idx):
        name = self.image_names[idx]
        img = cv2.imread(str(IMAGES_DIR / name))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mask = cv2.imread(str(MASKS_DIR / name), cv2.IMREAD_GRAYSCALE)

        # Resize
        img = cv2.resize(img, (IMG_SIZE, IMG_SIZE))
        mask = cv2.resize(mask, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_NEAREST)

        # Бинаризация маски
        mask = (mask > 127).astype(np.float32)

        # Аугментации (применяются одинаково к img и mask)
        if self.augment:
            img, mask = self._augment(img, mask)

        # To tensor: img (H,W,3) → (3,H,W), mask (H,W) → (1,H,W)
        img = torch.from_numpy(np.ascontiguousarray(img).transpose(2, 0, 1)).float() / 255.0
        img = self.normalize(img)
        mask = torch.from_numpy(np.ascontiguousarray(mask)).unsqueeze(0)

        return img, mask

    def _augment(self, img: np.ndarray, mask: np.ndarray):
        # Horizontal flip
        if random.random() < 0.5:
            img = np.fliplr(img)
            mask = np.fliplr(mask)

        # Vertical flip
        if random.random() < 0.3:
            img = np.flipud(img)
            mask = np.flipud(mask)

        # Brightness + contrast
        if random.random() < 0.5:
            alpha = 1.0 + random.uniform(-0.2, 0.2)  # contrast
            beta = random.uniform(-25, 25)             # brightness
            img = np.clip(img.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)

        # Color jitter (hue shift in HSV)
        if random.random() < 0.3:
            hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV).astype(np.int16)
            hsv[:, :, 0] = (hsv[:, :, 0] + random.randint(-10, 10)) % 180
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] + random.randint(-20, 20), 0, 255)
            img = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)

        # Gaussian noise
        if random.random() < 0.3:
            noise = np.random.normal(0, random.uniform(3, 10), img.shape).astype(np.float32)
            img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)

        return img, mask


# ── Splits ────────────────────────────────────────────────────────────
def create_splits(val_ratio: float = 0.1, test_ratio: float = 0.1, seed: int = 42):
    """Создать train/val/test разбиение и сохранить в splits.json."""
    all_names = sorted(f.name for f in IMAGES_DIR.glob("*.png"))

    # Отфильтровать пустые маски
    valid = []
    for name in all_names:
        mask_path = MASKS_DIR / name
        if mask_path.exists():
            mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
            if mask is not None and np.sum(mask > 127) > 100:
                valid.append(name)

    random.seed(seed)
    random.shuffle(valid)

    n = len(valid)
    n_test = int(n * test_ratio)
    n_val = int(n * val_ratio)

    test = valid[:n_test]
    val = valid[n_test:n_test + n_val]
    train = valid[n_test + n_val:]

    splits = {"train": train, "val": val, "test": test}
    SPLITS_FILE.write_text(json.dumps(splits, indent=2))
    print(f"Splits: train={len(train)}, val={len(val)}, test={len(test)}")
    return splits


def load_splits() -> dict:
    if SPLITS_FILE.exists():
        return json.loads(SPLITS_FILE.read_text())
    return create_splits()


# ── Loss ──────────────────────────────────────────────────────────────
class DiceBCELoss(nn.Module):
    def __init__(self, smooth: float = 1.0):
        super().__init__()
        self.smooth = smooth
        self.bce = nn.BCEWithLogitsLoss()

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        bce_loss = self.bce(logits, targets)

        probs = torch.sigmoid(logits)
        probs_flat = probs.view(-1)
        targets_flat = targets.view(-1)

        intersection = (probs_flat * targets_flat).sum()
        dice = (2.0 * intersection + self.smooth) / (
            probs_flat.sum() + targets_flat.sum() + self.smooth
        )
        dice_loss = 1.0 - dice

        return bce_loss + dice_loss


# ── Метрики ───────────────────────────────────────────────────────────
def calc_dice(logits: torch.Tensor, targets: torch.Tensor, threshold: float = 0.5) -> float:
    probs = torch.sigmoid(logits)
    preds = (probs > threshold).float()
    preds_flat = preds.view(-1)
    targets_flat = targets.view(-1)
    intersection = (preds_flat * targets_flat).sum()
    return (2.0 * intersection / (preds_flat.sum() + targets_flat.sum() + 1e-8)).item()


def calc_iou(logits: torch.Tensor, targets: torch.Tensor, threshold: float = 0.5) -> float:
    probs = torch.sigmoid(logits)
    preds = (probs > threshold).float()
    preds_flat = preds.view(-1)
    targets_flat = targets.view(-1)
    intersection = (preds_flat * targets_flat).sum()
    union = preds_flat.sum() + targets_flat.sum() - intersection
    return (intersection / (union + 1e-8)).item()


def calc_center_dist(logits: torch.Tensor, targets: torch.Tensor, threshold: float = 0.5) -> float:
    """Среднее расстояние между центрами предсказанной и GT маски (в пикселях)."""
    probs = torch.sigmoid(logits)
    preds = (probs > threshold).float()

    dists = []
    for pred, target in zip(preds, targets):
        pred_np = pred.squeeze().cpu().numpy()
        target_np = target.squeeze().cpu().numpy()

        # Центр предсказания
        pred_ys, pred_xs = np.where(pred_np > 0.5)
        tgt_ys, tgt_xs = np.where(target_np > 0.5)

        if len(pred_xs) > 0 and len(tgt_xs) > 0:
            pred_cx, pred_cy = pred_xs.mean(), pred_ys.mean()
            tgt_cx, tgt_cy = tgt_xs.mean(), tgt_ys.mean()
            dist = np.sqrt((pred_cx - tgt_cx) ** 2 + (pred_cy - tgt_cy) ** 2)
            dists.append(dist)

    return np.mean(dists) if dists else 999.0


# ── Training ──────────────────────────────────────────────────────────
def train(
    epochs: int = 50,
    batch_size: int = 8,
    lr: float = 1e-4,
    patience: int = 10,
):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # Splits
    splits = load_splits()
    print(f"Train: {len(splits['train'])}, Val: {len(splits['val'])}, Test: {len(splits['test'])}")

    # Datasets
    train_ds = PuzzleDataset(splits["train"], augment=True)
    val_ds = PuzzleDataset(splits["val"], augment=False)

    train_loader = DataLoader(
        train_ds, batch_size=batch_size, shuffle=True,
        num_workers=0, pin_memory=True,
    )
    val_loader = DataLoader(
        val_ds, batch_size=batch_size, shuffle=False,
        num_workers=0, pin_memory=True,
    )

    # Model
    model = smp.Unet(
        encoder_name=ENCODER,
        encoder_weights=ENCODER_WEIGHTS,
        in_channels=3,
        classes=1,
    )
    model.to(device)

    # Loss, optimizer, scheduler
    criterion = DiceBCELoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    # Training loop
    best_dice = 0.0
    no_improve = 0
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    for epoch in range(1, epochs + 1):
        # ── Train ──
        model.train()
        train_loss = 0.0
        train_dice = 0.0
        n_train = 0

        for images, masks in train_loader:
            images = images.to(device)
            masks = masks.to(device)

            logits = model(images)
            loss = criterion(logits, masks)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            train_loss += loss.item() * images.size(0)
            train_dice += calc_dice(logits, masks) * images.size(0)
            n_train += images.size(0)

        train_loss /= n_train
        train_dice /= n_train

        # ── Validation ──
        model.eval()
        val_loss = 0.0
        val_dice = 0.0
        val_iou = 0.0
        val_dist = 0.0
        n_val = 0

        with torch.no_grad():
            for images, masks in val_loader:
                images = images.to(device)
                masks = masks.to(device)

                logits = model(images)
                loss = criterion(logits, masks)

                val_loss += loss.item() * images.size(0)
                val_dice += calc_dice(logits, masks) * images.size(0)
                val_iou += calc_iou(logits, masks) * images.size(0)
                val_dist += calc_center_dist(logits, masks) * images.size(0)
                n_val += images.size(0)

        val_loss /= n_val
        val_dice /= n_val
        val_iou /= n_val
        val_dist /= n_val

        scheduler.step()

        # ── Logging ──
        lr_current = optimizer.param_groups[0]["lr"]
        print(
            f"Epoch {epoch:3d}/{epochs} | "
            f"train loss={train_loss:.4f} dice={train_dice:.4f} | "
            f"val loss={val_loss:.4f} dice={val_dice:.4f} iou={val_iou:.4f} "
            f"dist={val_dist:.1f}px | lr={lr_current:.2e}"
        )

        # ── Early stopping + save best ──
        if val_dice > best_dice:
            best_dice = val_dice
            no_improve = 0
            torch.save({
                "model_state_dict": model.state_dict(),
                "encoder": ENCODER,
                "img_size": IMG_SIZE,
                "best_dice": best_dice,
                "epoch": epoch,
            }, str(MODEL_PATH))
            print(f"  >> Best model saved (dice={best_dice:.4f})")
        else:
            no_improve += 1
            if no_improve >= patience:
                print(f"\nEarly stopping: {patience} эпох без улучшения")
                break

    print(f"\nОбучение завершено. Лучший val dice: {best_dice:.4f}")
    print(f"Модель: {MODEL_PATH}")

    # ── Test evaluation ──
    if splits["test"]:
        evaluate_test(model, splits["test"], device)


def evaluate_test(model, test_names: list[str], device):
    """Оценка на тестовом сплите."""
    print("\n-- Test evaluation --")
    test_ds = PuzzleDataset(test_names, augment=False)
    test_loader = DataLoader(test_ds, batch_size=8, shuffle=False, num_workers=0)

    model.eval()
    all_dice = []
    all_iou = []
    all_dist = []

    with torch.no_grad():
        for images, masks in test_loader:
            images = images.to(device)
            masks = masks.to(device)
            logits = model(images)

            all_dice.append(calc_dice(logits, masks))
            all_iou.append(calc_iou(logits, masks))
            all_dist.append(calc_center_dist(logits, masks))

    print(f"Test Dice:     {np.mean(all_dice):.4f}")
    print(f"Test IoU:      {np.mean(all_iou):.4f}")
    print(f"Test CenterDist: {np.mean(all_dist):.1f}px")

    # Процент тестов с dist < 15px
    close = sum(1 for d in all_dist if d < 15) / len(all_dist) * 100
    print(f"Test dist<15px: {close:.0f}%")


# ── CLI ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Train puzzle captcha segmentation model")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--new-splits", action="store_true", help="Recreate train/val/test splits")
    args = parser.parse_args()

    if args.new_splits or not SPLITS_FILE.exists():
        create_splits()

    train(
        epochs=args.epochs,
        batch_size=args.batch,
        lr=args.lr,
        patience=args.patience,
    )


if __name__ == "__main__":
    main()
