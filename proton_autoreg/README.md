# Captcha Solver Pipeline

CV-пайплайн для решения hCaptcha на Steam. Регистрация Proton Mail через компьютерное зрение, Steam через Playwright.

## Установка

### 1. Python 3.12

```bash
# Windows
winget install Python.Python.3.12
```

### 2. Virtual environment

```bash
cd proton_autoreg
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac
```

### 3. Зависимости

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install ultralytics
pip install segment-anything
pip install easyocr opencv-python numpy pyautogui pyperclip httpx
pip install segmentation_models_pytorch
pip install playwright
playwright install firefox
```

**Без GPU** (CPU-only):
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

### 4. SAM веса (для разметки)

```bash
# SAM ViT-B (375MB, рекомендуется)
curl -L -o sam_vit_b.pth https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth

# SAM ViT-H (2.4GB, лучше но медленнее)
curl -L -o sam_vit_h.pth https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth
```

## Структура

```
proton_autoreg/
├── cv_pipeline.py          # Оркестратор: Proton + Steam
├── proton_cv.py            # CV-регистрация Proton Mail
├── steam_cv.py             # Регистрация Steam (Playwright)
├── chrome_launcher.py      # Запуск Chrome без CDP
├── screen_automation.py    # pyautogui обёртка
├── human_behavior.py       # Очеловечивание (Bezier, typing)
├── ocr_engine.py           # OCR + template matching
├── captcha_solver.py       # U-Net солвер для Proton puzzle
├── captcha_collector.py    # Парсер hCaptcha датасета
├── captcha_labeler.py      # SAM-лейблер (разметка)
├── captcha_matcher.py      # Contour matching (PoC)
├── captcha_eval.py         # Оценка качества матчинга
├── train_yolo_seg.py       # Обучение YOLO11-seg
├── train_segmentation.py   # Обучение U-Net (legacy)
├── templates/              # Шаблоны кнопок для CV
├── captcha_dataset/        # Датасет v1
│   ├── metadata.jsonl
│   ├── labels.jsonl
│   ├── masks/
│   └── *.png
├── captcha_dataset_v2/     # Датасет v2
├── yolo_figures/           # YOLO датасет (конвертированный)
├── runs/                   # Результаты обучения YOLO
└── models/                 # Веса моделей
```

## Сбор датасета

```bash
# Собрать 500 капч (Playwright Firefox)
python captcha_collector.py --count 500

# В отдельную папку
python captcha_collector.py --count 500 --output captcha_dataset_v2

# С прокси
python captcha_collector.py --count 500 --proxy user:pass@host:port
```

## Разметка

SAM-лейблер с тремя режимами:

```bash
# Фигуры (drag-to-similar + arrows) — основной режим
python captcha_labeler.py --mode figures --model sam_vit_b.pth --model-type vit_b

# Линии (line breaks)
python captcha_labeler.py --mode lines --model sam_vit_b.pth --model-type vit_b

# Детекция bbox (grid captchas)
python captcha_labeler.py --mode detect --filter "animal"
```

### Управление лейблера

| Клавиша | Действие |
|---------|----------|
| ЛКМ | SAM positive point / Brush draw / Bbox start |
| ПКМ | SAM negative point / Brush erase / Bbox delete |
| Space | Завершить маску, начать новую |
| N | Переключить вариант маски (SAM) |
| T | Пометить как TARGET |
| M | Режим bbox (Move element) |
| B | Режим кисточки (ручная дорисовка) |
| Scroll | Размер кисти |
| Backspace | Удалить последний элемент |
| S | Сохранить |
| D | Пропустить |
| R | Сбросить |
| Q | Выйти |

## Обучение YOLO11-seg

4 модели для разных типов капч:

```bash
# Конвертация разметки в YOLO формат
python train_yolo_seg.py --task figures --convert-only

# Обучение на GPU (рекомендуется)
python train_yolo_seg.py --task figures --device 0 --epochs 100

# Обучение на CPU (медленно)
python train_yolo_seg.py --task figures --device cpu --epochs 100 --batch 2

# Валидация
python train_yolo_seg.py --task figures --validate

# Demo на одном изображении
python train_yolo_seg.py --task figures --demo
```

### Задачи

| Task | Классы | Описание |
|------|--------|----------|
| `figures` | move, figure | Drag-to-similar (62% капч) |
| `arrows` | arrow | Circular pattern (28%) |
| `puzzles` | move, puzzle_piece | Matching half (2.6%) |
| `letters` | move, letter | Drag letter (0.6%) |

### Параметры обучения

| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `--model` | yolo11x-seg.pt | Размер модели (n/s/m/l/x) |
| `--epochs` | 100 | Количество эпох |
| `--batch` | 4 | Batch size (уменьшить если OOM) |
| `--imgsz` | 512 | Размер изображения |
| `--patience` | 20 | Early stopping |
| `--device` | 0 | GPU (0) или CPU (cpu) |

## Оценка качества

```bash
# Прогнать contour matcher на размеченных данных
python captcha_matcher.py --visualize

# Ручная оценка (Y/N на каждую визуализацию)
python captcha_eval.py
```

## Регистрация

```bash
# Только Proton (CV + Chrome)
python cv_pipeline.py --proton-only

# Только Steam (Playwright)
python cv_pipeline.py --steam-only --email user@proton.me

# Полный цикл: Proton + Steam
python cv_pipeline.py --count 1
```
