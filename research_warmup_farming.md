# Task Brief: Улучшение Warmup & Farming модулей

## Твоя роль

Ты автономный агент-разработчик. Твоя задача — улучшить модули warmup (прогрев аккаунтов) и farming (фарм часов) в проекте Steam Farming Panel. Работай самостоятельно, коммить атомарно на feature-ветку.

## Контекст проекта

Steam Farming Panel — десктопное приложение для массового управления Steam-аккаунтами. Стек: FastAPI + SQLAlchemy (backend), Electron + React (frontend), ASF для farming.

### Текущая реализация (что уже есть — НЕ переписывай):
- **Warmup**: `backend/app/services/warmup_service.py` — Playwright-автоматизация 13 квестов Community Badge (~4-5 мин/аккаунт)
- **Farming**: `backend/app/api/endpoints/asf.py` — ASF IPC для фарма часов (ручной режим, 30+ F2P игр)
- **Text generation**: `backend/app/services/text_generator.py` — LLM генерация (Groq/Gemini + fallback)
- **API endpoints**: warmup.py, asf.py — start/stop/status
- **Frontend**: WarmupPage.tsx, FarmingPage.tsx — полноценный UI с прогрессом

### Что НЕ реализовано (твои задачи):
- Сессии warmup/farming хранятся in-memory — теряются при рестарте
- Нет Smart Farming (расписания, перерывы, рандомизация)
- Нет антибана: proxy rotation, rate limiting, fingerprint protection
- Нет retry логики при ошибках квестов
- Тайминги warmup могут быть слишком предсказуемыми

## Задачи (в порядке приоритета)

### Задача 1: Антибан для Warmup

**Файлы:** `backend/app/services/warmup_service.py`

Что сделать:
- Рандомизировать задержки между квестами: вместо фиксированных 1.5-3 сек использовать нормальное распределение (mean=3, std=1.5, min=1, max=8)
- Рандомизировать порядок квестов (те что не зависят друг от друга)
- Добавить случайные "человеческие" паузы: скролл страницы, движение мыши, клик в пустую область
- ~~Proxy support~~ — **ПРОПУСТИТЬ, прокси пока нет**. Подготовь интерфейс (параметр proxy в функциях), но не реализуй и не тестируй
- Rate limiting: не запускать больше N аккаунтов в минуту с одного IP (настраиваемый параметр)

### Задача 2: Retry и обработка ошибок в Warmup

**Файлы:** `backend/app/services/warmup_service.py`, `backend/app/api/endpoints/warmup.py`

Что сделать:
- При ошибке квеста — retry до 3 раз с экспоненциальным backoff (2, 4, 8 сек)
- Если квест фейлится после 3 попыток — пометить как `skipped`, продолжить остальные
- Логировать причину ошибки для каждого квеста (screenshot или HTML dump при ошибке)
- При таймауте страницы — увеличить timeout и retry
- Добавить общий timeout на весь warmup аккаунта (default: 10 мин)

### Задача 3: Smart Farming

**Файлы:** создать `backend/app/services/smart_farming.py`, обновить `backend/app/api/endpoints/asf.py`

Что сделать:
- Режим "Smart Farming" с расписанием:
  - Настраиваемые окна активности (например: 08:00-23:00)
  - Случайные перерывы (каждые 2-4 часа пауза на 15-45 мин)
  - Рандомное время старта/стопа (±30 мин от заданного)
- Ротация игр: менять набор игр каждые N часов
- Имитация паттернов: иногда "выходить" из одной игры и "заходить" в другую
- API endpoint: `POST /asf/farm/smart-start` с параметрами расписания

### Задача 4: Персистентность сессий

**Файлы:** создать модель в `backend/app/models/`, обновить warmup.py и asf.py endpoints

Что сделать:
- Создать SQLAlchemy модели `WarmupSession` и `FarmingSession`
- Сохранять статус сессий в БД вместо in-memory dict
- При рестарте backend — восстанавливать незавершённые сессии
- Farming: возобновлять ASF farming после рестарта
- Warmup: помечать прерванные квесты как `interrupted`, позволять продолжить

### Задача 5: Оптимизация тайминг Warmup

**Файлы:** `backend/app/services/warmup_service.py`

Что сделать:
- Определить какие квесты независимы и могут выполняться параллельно (группами по 2-3)
- Добавить "прогрев браузера": перед квестами — зайти на steamcommunity.com, пошататься 10-20 сек
- Между группами квестов — пауза 5-15 сек (имитация чтения страницы)
- После warmup — случайная задержка 1-5 мин перед следующим аккаунтом

## Правила работы

1. **Перед началом**: `git checkout -b feature/warmup-farming-improvements`
2. **Читай существующий код** перед изменениями — не ломай то что работает
3. **Коммить атомарно** — один логический блок = один коммит
4. **Пиши тесты** для новой логики (pytest, в `backend/tests/`)
5. **Не трогай frontend** — только backend
6. **Запускай `python -m pytest`** после каждого значимого изменения
7. **Не пуши** — только локальные коммиты

## Верификация — живое тестирование после каждой задачи

**ОБЯЗАТЕЛЬНО:** после завершения каждой задачи проведи live-тест через Playwright/скрипт. Не коммить задачу пока не убедился что она реально работает.

### Как тестировать:

**Задача 1 (Антибан):**
- Написать скрипт `backend/tests/live/test_antiban.py`
- Запустить Playwright браузер **без proxy** (прокси пока нет)
- Проверить что задержки действительно рандомные (залогировать тайминги)
- Проверить что human-like действия выполняются (скролл, движение мыши)
- Визуально убедиться в headful-режиме: `playwright.chromium.launch(headless=False)`

**Задача 2 (Retry):**
- Написать скрипт `backend/tests/live/test_retry.py`
- Эмулировать ошибку квеста (например, неправильный URL) и убедиться что retry срабатывает
- Проверить что screenshot/HTML dump создаётся при ошибке
- Проверить что после 3 фейлов квест помечается как `skipped` и остальные продолжаются

**Задача 3 (Smart Farming):**
- Написать скрипт `backend/tests/live/test_smart_farming.py`
- Запустить Smart Farming в ускоренном режиме (короткие интервалы для теста)
- Проверить что перерывы срабатывают (лог: "pausing for X minutes")
- Проверить ротацию игр (лог: "switching games from [...] to [...]")
- Убедиться что ASF IPC команды отправляются корректно (или замокать если ASF не запущен)

**Задача 4 (Персистентность):**
- Написать скрипт `backend/tests/live/test_persistence.py`
- Создать сессию → проверить что записалась в БД
- Имитировать "рестарт" (пересоздать сервис) → проверить что сессия восстановилась
- Alembic миграция должна пройти без ошибок: `alembic upgrade head`

**Задача 5 (Оптимизация таймингов):**
- Написать скрипт `backend/tests/live/test_warmup_timing.py`
- Запустить warmup одного тестового аккаунта в headful-режиме
- Залогировать тайминги каждого этапа (browser warmup → quest groups → pauses)
- Сравнить с предыдущими таймингами — убедиться что параллельные группы быстрее

### Формат live-тестов:

```python
# backend/tests/live/test_example.py
"""
Live test — запускать вручную: python -m pytest backend/tests/live/ -v -s
Требует: запущенный backend, доступ к Steam (опционально)
"""
import pytest

@pytest.mark.live
async def test_something():
    # Тест с реальным Playwright/ASF
    ...
```

### Структура отчёта после каждой задачи:

После каждой задачи добавь в коммит-сообщение:
```
Verified: [описание что протестировано]
- ✅ задержки рандомные (min=1.2s, max=7.8s, mean=3.1s)
- ✅ retry сработал 2/3 раза, квест выполнен со 2й попытки
- ❌ proxy не протестирован (нет доступного proxy)
```

## Окружение на машине

Всё уже установлено и запущено, тебе не нужно ничего настраивать:

- **Backend**: запущен на `localhost:8420`
- **ASF**: запущен на `localhost:1242` (IPC доступен)
- **БД**: SQLite с тестовыми аккаунтами (уже есть в таблице accounts)
- **Proxy**: есть доступные proxy в таблице proxies
- **Playwright**: chromium установлен (`playwright install chromium` уже выполнен)
- **venv**: активирован, все зависимости установлены

### Как получить тестовые данные для live-тестов:

```python
# Получить аккаунт из БД
from app.database import async_session
from app.models.account import Account
async with async_session() as session:
    account = await session.execute(select(Account).limit(1))
    acc = account.scalar_one()
    # acc.login, acc.password (зашифрован), acc.proxy_id
```

### Как запустить Playwright в headful-режиме для отладки:

```python
browser = playwright.chromium.launch(headless=False, slow_mo=500)
```

### ASF IPC:

```python
# Проверить что ASF работает
import httpx
resp = await httpx.AsyncClient().get("http://localhost:1242/Api/ASF")
# Отправить команду
resp = await httpx.AsyncClient().post("http://localhost:1242/Api/Command", json={"Command": "status"})
```

## Технические ограничения

- Python 3.13, async/await
- Playwright для браузерной автоматизации (sync API в thread pool)
- ASF IPC на localhost:1242 (HTTP)
- SQLAlchemy async (aiosqlite для SQLite)
- Alembic для миграций БД

## Порядок работы

1. **Самодиагностика** — перед началом проверь что всё доступно:
   - `curl http://localhost:8420/api/health` — backend жив?
   - `curl http://localhost:1242/Api/ASF` — ASF жив?
   - `python -c "from app.database import ..."` — БД подключается?
   - `python -m playwright install --dry-run` — chromium есть?
   - Если что-то не работает — напиши в лог какие задачи можешь выполнить без этого, и выполни их

2. **Задача за задачей**: выполняй задачи строго по порядку (1→2→3→4→5)
3. **Цикл на каждую задачу**:
   - Прочитай существующий код
   - Реализуй изменения
   - Напиши unit-тест (`backend/tests/`)
   - Напиши live-тест (`backend/tests/live/`)
   - Запусти unit-тесты: `python -m pytest backend/tests/ -v --ignore=backend/tests/live`
   - Запусти live-тест: `python -m pytest backend/tests/live/test_<task>.py -v -s`
   - Если тест падает — исправь и повтори
   - Коммит с отчётом верификации
4. **Не застревай**: если live-тест не проходит после 3 попыток — коммить что есть с пометкой `WIP`, переходи к следующей задаче

## Критерии успеха

- Warmup работает с рандомизированными таймингами и proxy
- Квесты ретраятся при ошибках, не ломают весь процесс
- Smart Farming запускается по расписанию с перерывами
- Сессии сохраняются в БД и восстанавливаются после рестарта
- Все unit-тесты проходят (`python -m pytest`)
- **Все live-тесты проходят** (`python -m pytest backend/tests/live/ -v -s`)
- Каждый коммит содержит отчёт верификации в сообщении
