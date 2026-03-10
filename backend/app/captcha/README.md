# hCaptcha Solvers

Набор решателей hCaptcha. Три независимых подхода — выбери нужный под свою задачу.

---

## Установка зависимостей

```bash
pip install -r captcha/requirements.txt
playwright install chromium
```

Также нужна локальная библиотека `hcaptcha-challenger` (для `ChallengerSolver`):
```bash
pip install hcaptcha-challenger-0.19.0/
```

---

## Решатель 1 — ChallengerSolver (лучший)

Запускает реальный браузер Chromium через Playwright и решает капчу с помощью **Gemini AI**.

**Нужен:** Gemini API ключ (бесплатный на [aistudio.google.com](https://aistudio.google.com))

```python
from captcha import ChallengerSolver

solver = ChallengerSolver(api_key="ВАШ_GEMINI_API_КЛЮЧ")
solver.generate_hcaptcha(sitekey="...")   # открывает браузер и решает
status, token, cost = solver.resolve_captcha(None)
print(token)
```

**Поддерживаемые типы капч:**
| Тип | Описание |
|-----|----------|
| `image_label_binary` | "Tap all X" — выбрать объекты из 9 картинок |
| `image_label_multi_select` | "Select all artificial objects" |
| `image_drag_drop` | "Drag animal to matching shadow" |
| `image_drag_single` | Перетащить одну фигуру |

---

## Решатель 2 — HCaptchaSolver (без UI)

Решает hCaptcha через прямые API запросы. Браузер не открывается (кроме генерации HSW токена).
Использует **Groq Vision AI** (Llama 4) для анализа картинок.

**Нужен:** Groq API ключ (бесплатный на [console.groq.com](https://console.groq.com))

```python
from captcha import HCaptchaSolver

solver = HCaptchaSolver(groq_api_key="ВАШ_GROQ_API_КЛЮЧ")

# Опционально — список прокси для ротации
solver.set_proxies(["http://user:pass@ip:port", ...])

task = solver.generate_hcaptcha(sitekey="e18a349a-...")
status, token, cost = solver.resolve_captcha(task)
print(token)

solver.close()  # закрыть браузер HSW
```

**Поддерживаемые типы:**
| Тип | Метод |
|-----|-------|
| `image_label_binary` | Groq Vision |
| `image_drag_drop` | OpenCV + Groq Vision |
| текстовые | Groq |

---

## Решатель 3 — OpenCV (line ends)

Чисто алгоритмический решатель для капчи **"Please click on the line ends"**.
Не требует API ключей.

```python
from captcha import find_line_endpoints

# Принимает путь к скриншоту капчи
points = find_line_endpoints("screenshot.png")
# Возвращает список (x, y) — координаты в полном изображении
# Пример: [(212, 171), (159, 343), (90, 302), (158, 343)]

for x, y in points:
    print(f"Кликнуть на: x={x}, y={y}")
```

Или из командной строки:
```bash
python -m captcha.solve_line_ends screenshot.png
```

---

## Выбор решателя

| Задача | Рекомендуемый решатель |
|--------|------------------------|
| Steam регистрация (drag/shadow) | `ChallengerSolver` (Gemini) |
| Массовая регистрация (без UI) | `HCaptchaSolver` (Groq) |
| "Click on line ends" | `find_line_endpoints` (OpenCV) |
| Простая классификация | `HCaptchaSolver` (Groq) |

---

## Структура

```
captcha/
├── __init__.py              # экспорт всех классов
├── challenger_wrapper.py    # ChallengerSolver (Playwright + Gemini)
├── hcaptcha_solver.py       # HCaptchaSolver (Groq + API)
├── solve_line_ends.py       # OpenCV line-ends solver
├── captcha_snippet.py       # вспомогательный код
└── requirements.txt         # зависимости
```
