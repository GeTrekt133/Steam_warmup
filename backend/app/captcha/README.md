# Captcha Solvers

Модуль решателей капч. Поддерживает hCaptcha (Steam), FunCaptcha (Outlook) и пазл-капчу (Proton Mail).

---

## Установка зависимостей

```bash
pip install -r requirements.txt
playwright install chromium
```

Для `ChallengerSolver` нужна локальная библиотека:
```bash
pip install hcaptcha-challenger-0.19.0/
```

Для `PuzzleSolver` и `puzzle_train.py`:
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
pip install segmentation-models-pytorch
```

---

## Решатель 1 — ChallengerSolver (hCaptcha, браузер + Gemini)

Запускает Chromium через Playwright и решает hCaptcha с помощью **Gemini AI**.

**Нужен:** Gemini API ключ ([aistudio.google.com](https://aistudio.google.com))

```python
from app.captcha import ChallengerSolver

solver = ChallengerSolver(api_key="GEMINI_API_KEY")
solver.generate_hcaptcha(sitekey="...")
status, token, cost = solver.resolve_captcha(None)
```

**Типы капч:** `image_label_binary`, `image_label_multi_select`, `image_drag_drop`, `image_drag_single`

---

## Решатель 2 — HCaptchaSolver (hCaptcha, без UI)

Прямые API запросы + **Groq Vision AI** (Llama 4). Браузер только для HSW токена.

**Нужен:** Groq API ключ ([console.groq.com](https://console.groq.com))

```python
from app.captcha import HCaptchaSolver

solver = HCaptchaSolver(groq_api_key="GROQ_API_KEY")
solver.set_proxies(["http://user:pass@ip:port", ...])  # опционально

task = solver.generate_hcaptcha(sitekey="e18a349a-...")
status, token, cost = solver.resolve_captcha(task)
solver.close()
```

**Типы:** `image_label_binary`, `image_drag_drop` (OpenCV + Groq), текстовые

---

## Решатель 3 — find_line_endpoints (hCaptcha, OpenCV)

Алгоритмический решатель для "Please click on the line ends". Без API ключей.

```python
from app.captcha import find_line_endpoints

points = find_line_endpoints("screenshot.png")
for x, y in points:
    print(f"Click: x={x}, y={y}")
```

```bash
python -m app.captcha.solve_line_ends screenshot.png
```

---

## Решатель 4 — PuzzleSolver (Proton Mail, U-Net)

Сегментационная модель для пазл-капчи Proton Mail. Находит тень пазла на фоновом изображении.

**API ключи не нужны.** Модель обучена на 981 изображении. Inference ~70ms на CPU.

| Метрика | Результат |
|---------|-----------|
| Dice    | 0.97      |
| IoU     | 0.94      |
| Center distance | 0.3px |

```python
from app.captcha import PuzzleSolver

solver = PuzzleSolver()  # авто GPU/CPU
x, y, confidence = solver.solve("screenshot.png", debug=True)
# x, y — координаты центра тени в пикселях скриншота (682x600)
# confidence — уверенность модели (0.0-1.0)
```

Параметры `solve()`:
- `image` — путь к файлу или numpy array (BGR)
- `is_screenshot=True` — полный скриншот 682x600; `False` — обрезанное фото 350x370
- `debug=True` — сохранить визуализацию `*_debug.png` (фото | overlay | heatmap)

### Переобучение модели

```bash
# 1. Обрезать скриншоты → datasets/puzzle/images/
python -m app.captcha.puzzle_dataset_prep crop C:/path/to/screenshots

# 2. Разметить маски с SAM (GUI: ЛКМ=click, Tab=switch mask, Enter=save, Backspace=back)
python -m app.captcha.puzzle_annotator

# 3. Обучить U-Net
python -m app.captcha.puzzle_train --epochs 50 --batch 8 --lr 1e-4
```

SAM модель для аннотатора (sam_vit_b.pth, 358MB) скачивается отдельно:
```bash
curl -L -o app/captcha/models/sam_vit_b.pth \
  "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth"
```

---

## Решатель 5 — FunCaptchaSolver (Outlook)

Решает FunCaptcha через внешние сервисы (EzCaptcha, 2captcha, anti-captcha).

**Нужен:** API ключ одного из сервисов

```python
from app.captcha.funcaptcha_solver import FunCaptchaSolver

solver = FunCaptchaSolver(service="ezcaptcha", api_key="KEY")
token = solver.solve(public_key="...", page_url="...")
```

---

## Решатель 6 — CapSolverHCaptcha (hCaptcha, fallback)

Fallback через CapSolver API. Быстрый (~3-9 сек), но платный.

```python
from app.captcha.capsolver import CapSolverHCaptcha

solver = CapSolverHCaptcha(api_key="CAPSOLVER_KEY")
token = solver.solve(sitekey="...", page_url="...")
```

---

## Выбор решателя

| Задача | Решатель | API ключ |
|--------|----------|----------|
| Steam регистрация (hCaptcha) | `ChallengerSolver` | Gemini |
| Массовая hCaptcha (без UI) | `HCaptchaSolver` | Groq |
| hCaptcha "line ends" | `find_line_endpoints` | Нет |
| Proton Mail пазл-капча | `PuzzleSolver` | Нет |
| Outlook FunCaptcha | `FunCaptchaSolver` | EzCaptcha/2captcha |
| hCaptcha fallback | `CapSolverHCaptcha` | CapSolver |

---

## Структура

```
captcha/
├── __init__.py                 # экспорт основных классов
├── challenger_wrapper.py       # ChallengerSolver (Playwright + Gemini)
├── hcaptcha_solver.py          # HCaptchaSolver (Groq + API)
├── solve_line_ends.py          # OpenCV line-ends solver
├── solve_puzzle.py             # PuzzleSolver (U-Net segmentation)
├── funcaptcha_solver.py        # FunCaptchaSolver (внешние сервисы)
├── capsolver.py                # CapSolverHCaptcha (fallback)
├── puzzle_train.py             # Обучение U-Net модели
├── puzzle_annotator.py         # SAM-аннотатор (GUI)
├── puzzle_dataset_prep.py      # Предобработка датасета
├── captcha_snippet.py          # Legacy: Steam регистрация через RuCaptcha
├── hcaptcha-challenger-0.19.0/ # Vendored library
└── models/
    ├── puzzle_unet.pth         # Обученная U-Net (94MB, в git)
    └── sam_vit_b.pth           # SAM для аннотатора (358MB, скачать отдельно)
```
