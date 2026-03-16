# Task Brief: Тестирование и доработка модуля прогрева (Warmup)

## Твоя роль

Ты автономный агент-разработчик. Твоя задача — протестировать модуль прогрева Steam-аккаунтов end-to-end с реальным браузером (Playwright) и доработать код + фронтенд по результатам тестирования.

## Ветка

**Работай ТОЛЬКО в ветке `dev/autonomous-setup`.** Не переключайся на другие ветки.

```bash
git checkout dev/autonomous-setup
```

## Адреса сервисов

| Сервис | Адрес | Проверка |
|--------|-------|----------|
| **Backend API** | `http://localhost:8420` | `curl http://localhost:8420/api/health` |
| **ASF IPC** | `http://localhost:1242` | `curl http://localhost:1242/Api/ASF` |
| **Frontend** | `http://localhost:5173` | Открой в браузере |
| **Swagger docs** | `http://localhost:8420/docs` | Открой в браузере |

Перед началом работы проверь что backend и frontend запущены. Если что-то не работает — напиши в claude-progress.txt и работай с тем что доступно.

## Что уже реализовано (НЕ переписывай)

Предыдущий агент выполнил 5 задач (см. claude-progress.txt):
- Антибан: рандомные задержки, human-like действия, rate limiting
- Retry: 3 попытки с exponential backoff, error dumps
- Smart Farming: расписания, перерывы, ротация игр
- Персистентность: WarmupSession/FarmingSession в БД
- Оптимизация: группировка квестов, browser warmup, паузы

## Задачи

### Задача 1: End-to-end тест прогрева через Playwright

**Цель:** Запустить полный цикл warmup на реальном Steam-аккаунте и убедиться что всё работает.

Что сделать:
1. Открой браузер через MCP Playwright (`browser_navigate`) или Python Playwright с `headless=False`
2. Зайди на `http://localhost:8420/docs` — проверь что API доступен (скриншот)
3. Вызови `POST http://localhost:8420/api/warmup/start` с тестовым аккаунтом из БД
4. Мониторь статус через `GET http://localhost:8420/api/warmup/status/{task_id}` (поллинг каждые 5 сек)
5. Параллельно открой `https://steamcommunity.com` — наблюдай действия бота (скриншоты каждого квеста)
6. Дождись завершения, проверь что все квесты completed/skipped
7. Проверь что сессия сохранилась в БД: `GET http://localhost:8420/api/warmup/sessions`

**Скриншоты** (сохраняй в `backend/test_evidence/`):
- swagger_api.png — Swagger UI доступен
- warmup_started.png — ответ API на start
- quest_progress.png — промежуточный статус
- steam_profile.png — профиль Steam после warmup
- warmup_completed.png — финальный статус

**Если квесты падают** — зафикси код и запусти снова.

### Задача 2: Тест каждого квеста отдельно

**Цель:** Проверить каждый квест Community Badge индивидуально.

Список квестов для теста (из `QUEST_LIST` в warmup_service.py):
1. `setup_avatar` — загрузка аватара
2. `setup_profile_name` — установка имени профиля
3. `setup_profile_summary` — описание профиля
4. `rate_game` — оценка игры
5. `add_to_wishlist` — добавление в вишлист
6. `discovery_queue` — просмотр Discovery Queue
7. `join_group` — вступление в группу Steam
8. `subscribe_workshop` — подписка на Workshop item
9. `post_discussion` — создание обсуждения (или комментарий)
10. `add_friend` — добавление друга (нужен master_steam_id)
11. `post_comment` — комментарий на профиле мастера
12. `setup_background` — установка фона профиля
13. `write_review` — написание отзыва

Для каждого квеста:
- Вызови warmup с `quests: ["quest_name"]` (один квест)
- Если упал — посмотри error dump в `backend/error_dumps/`, зафикси
- Сделай скриншот Steam-страницы после квеста

### Задача 3: Тест фронтенда WarmupPage

**Цель:** Проверить что фронтенд корректно работает с API и отображает прогресс.

1. Открой `http://localhost:5173` через MCP Playwright
2. Залогинься (если требуется авторизация)
3. Перейди на страницу Warmup
4. Выбери тестовый аккаунт
5. Запусти warmup через UI
6. Проверь что прогресс-бар обновляется в реальном времени
7. Проверь что статусы квестов отображаются (pending/running/done/error/skipped)
8. Скриншоты: до запуска, в процессе, после завершения

**Если фронтенд некорректно работает** — исправь `frontend/src/pages/WarmupPage.tsx`:
- Убедись что polling статуса работает (каждые 3 сек)
- Убедись что новые параметры API отображаются (warmup_timeout, max_quest_retries)
- Добавь отображение retry count и error dumps если их нет
- Добавь кнопку/переключатель для Smart Farming параметров если нужно

### Задача 4: Тест Smart Farming через UI

**Цель:** Проверить Smart Farming end-to-end.

1. Открой `http://localhost:5173` → страница Farming
2. Проверь что есть UI для Smart Farming (если нет — добавь в `frontend/src/pages/FarmingPage.tsx`)
3. Нужные элементы UI:
   - Переключатель Manual / Smart режим
   - Настройки расписания (active_start, active_end)
   - Настройки перерывов (break_interval, break_duration)
   - Ротация игр (rotation_interval)
   - Отображение текущих smart-сессий
4. Запусти Smart Farming через API: `POST http://localhost:8420/api/asf/farm/smart-start`
5. Проверь через `GET http://localhost:8420/api/asf/farm/smart-sessions`
6. Скриншоты: UI формы, активная сессия, статус после паузы

### Задача 5: Интеграционные исправления

**Цель:** Зафиксить всё что сломалось во время тестирования.

- Если API возвращает ошибки — исправь backend
- Если фронтенд не отображает данные — исправь frontend
- Если квесты Steam изменились (новые селекторы) — обнови warmup_service.py
- Если Alembic миграция не прошла — исправь
- Запусти финальный полный тест: warmup 1 аккаунта через UI от начала до конца

## Правила работы

1. **Ветка**: `dev/autonomous-setup` — ТОЛЬКО она
2. **Коммить атомарно** — один логический блок = один коммит
3. **Фронтенд можно и нужно менять** — если UI не соответствует API, обнови
4. **Скриншоты обязательны** — сохраняй в `backend/test_evidence/`
5. **Playwright headless=False** — браузер должен быть видимым
6. **Обнови claude-progress.txt** после каждой задачи
7. **Не пуши** — только локальные коммиты

## Как делать скриншоты

### Через MCP Playwright (рекомендуется):
```
1. browser_navigate → url
2. browser_screenshot → сохранить
```

### Через Python:
```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=300)
    page = browser.new_page()
    page.goto("http://localhost:8420/docs")
    page.screenshot(path="backend/test_evidence/swagger.png")
```

### Через API тест:
```python
import httpx
# Запустить warmup
resp = httpx.post("http://localhost:8420/api/warmup/start", json={
    "accounts": [{"login": "test", "password": "test", "shared_secret": "..."}],
    "quests": ["all"],
    "max_concurrent": 1
})
task_id = resp.json()["task_id"]

# Проверить статус
status = httpx.get(f"http://localhost:8420/api/warmup/status/{task_id}")
print(status.json())
```

## Критерии успеха

- Полный warmup 1 аккаунта проходит end-to-end (API → Playwright → Steam)
- Каждый квест протестирован индивидуально
- Фронтенд корректно отображает прогресс warmup
- Smart Farming имеет UI и работает через API
- Все баги найденные при тестировании — зафиксены
- Скриншоты каждого этапа сохранены в `backend/test_evidence/`
- claude-progress.txt обновлён
