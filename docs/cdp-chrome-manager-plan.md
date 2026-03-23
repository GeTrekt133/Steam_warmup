# План: CDP Chrome Manager — антидетект браузер для автоматизации

## Контекст

Proton Mail детектит Playwright при регистрации почт и блокирует автоматизацию. Нужен максимально "беспалевный" способ управления браузером. CDP (Chrome DevTools Protocol) к живому Chrome — золотой стандарт антидетекта: сайт видит обычный браузер без маркеров автоматизации.

**Задачи:** регистрация почт (Proton), регистрация Steam, привязка Steam Guard.
**Параллельность:** 1-3 сессии одновременно.

## Архитектура

### ChromeManager — менеджер Chrome-инстансов

Новый сервис `backend/app/services/chrome_manager.py`:

1. **Запускает** реальный Chrome с `--remote-debugging-port` и изолированным `--user-data-dir`
2. **Playwright подключается** через `connect_over_cdp()` — управляет как обычно
3. **Каждый аккаунт** получает свой Chrome-инстанс с чистым профилем (нет пересечения cookies)
4. **Прокси** передаётся через `--proxy-server` флаг Chrome
5. **Cleanup** — после завершения Chrome убивается, профиль удаляется (опционально сохраняется)

### Поток данных

```
API endpoint → ChromeManager.create_session(proxy?)
  → subprocess: chrome.exe --remote-debugging-port=9222+N --user-data-dir=temp_profile
  → Playwright.connect_over_cdp("http://localhost:9222+N")
  → page = context.new_page()
  → ... автоматизация ...
  → ChromeManager.close_session() → kill chrome, cleanup profile
```

## Файлы

### 1. `backend/app/services/chrome_manager.py` (новый)

```python
class ChromeSession:
    port: int              # debug port (9300+)
    process: subprocess.Popen
    profile_dir: Path      # temp user-data-dir
    browser: Browser       # Playwright CDP browser
    context: BrowserContext
    page: Page

class ChromeManager:
    _sessions: dict[str, ChromeSession]  # session_id → session
    _next_port: int = 9300

    def find_chrome() -> Path
        # Ищет Chrome/Edge на Windows:
        # - %ProgramFiles%/Google/Chrome/Application/chrome.exe
        # - %ProgramFiles(x86)%/Google/Chrome/Application/chrome.exe
        # - %LocalAppData%/Google/Chrome/Application/chrome.exe
        # - %ProgramFiles(x86)%/Microsoft/Edge/Application/msedge.exe

    def create_session(proxy?, keep_profile=False) -> ChromeSession
        # 1. Создаёт temp dir для профиля
        # 2. Запускает Chrome subprocess:
        #    chrome.exe --remote-debugging-port={port}
        #               --user-data-dir={temp_profile}
        #               --no-first-run --no-default-browser-check
        #               --proxy-server={proxy}  (если есть)
        # 3. Ждёт готовности порта (poll http://localhost:{port}/json)
        # 4. Playwright connect_over_cdp
        # 5. Возвращает ChromeSession с page

    def close_session(session_id)
        # 1. Закрывает Playwright browser
        # 2. Убивает Chrome process
        # 3. Удаляет temp profile (если не keep_profile)

    def close_all()
        # Cleanup всех сессий (вызывается при shutdown)
```

### 2. `backend/app/api/endpoints/accounts.py` (изменение)

Обновить существующие эндпоинты, которые используют Playwright:
- `POST /api/accounts/link-guard-batch` — использует `ChromeManager` вместо `pw.chromium.launch()`

### 3. `backend/app/services/steam_guard_linker.py` (изменение)

- `_login_via_playwright()` → `_login_via_cdp()` — вместо `pw.chromium.launch()` использует `chrome_manager.create_session()`
- Outlook tab работает в том же Chrome-инстансе (как сейчас — два таба)
- При ошибке — `chrome_manager.close_session()`

### 4. Будущее: регистрация почт и Steam

Когда будем реализовывать (Фаза 2):
- `backend/app/services/proton_registration.py` — регистрация Proton через CDP
- `backend/app/services/steam_registration.py` — регистрация Steam через CDP
- Оба используют `ChromeManager.create_session()` с прокси

## Переиспользуем

- `_ensure_proactor()` из `steam_browser.py` — Windows event loop fix
- `_run_in_clean_thread()` из `steam_browser.py` — запуск sync кода в чистом потоке
- `_build_proxy_config()` из `steam_browser.py` — формат прокси (переделать в Chrome-флаг)
- Proxy модель из `proxy_service.py`

## Детали реализации

### Поиск Chrome на Windows
```
Приоритет:
1. HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe
2. %ProgramFiles%\Google\Chrome\Application\chrome.exe
3. %ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe
4. %LocalAppData%\Google\Chrome\Application\chrome.exe
5. msedge.exe (аналогичные пути) — fallback
```

### Chrome-флаги
```
--remote-debugging-port={port}
--user-data-dir={temp_dir}
--no-first-run
--no-default-browser-check
--disable-background-networking
--lang=en-US
--proxy-server={protocol}://{host}:{port}   (если прокси)
```

**НЕ добавляем** `--disable-gpu`, `--headless`, `--enable-automation` — они палевные.

### Ожидание готовности
Poll `http://localhost:{port}/json/version` каждые 500ms до 15 секунд. Когда вернёт JSON — Chrome готов для CDP.

### Подключение Playwright
```python
pw = sync_playwright().start()
browser = pw.chromium.connect_over_cdp(f"http://localhost:{port}")
context = browser.contexts[0]  # дефолтный контекст Chrome
page = context.new_page()
```

### Cleanup при shutdown
Регистрируем `atexit` + `app.on_event("shutdown")` для `chrome_manager.close_all()`.

## Сравнение подходов

| | Playwright (текущий) | CDP к Chrome | undetected-chromedriver |
|---|---|---|---|
| Антидетект | 3/10 | 10/10 | 9/10 |
| Простота миграции | — | Высокая (тот же Playwright API) | Низкая (переписывать на Selenium) |
| Параллельность | Легко | Средне (порты) | Легко |
| Прокси | `proxy={}` | `--proxy-server` флаг | `proxy=` параметр |
| Кодеки (видео) | Нет | Есть (Chrome) | Есть (Chrome) |

## Верификация

1. Запустить `ChromeManager.create_session()` — Chrome открывается
2. `page.goto("https://bot.sannysoft.com/")` — проверить что `webdriver=false`, нет маркеров
3. `page.goto("https://proton.me/mail")` — нет детекта автоматизации
4. Закрыть сессию — Chrome убивается, профиль удалён
5. Тест с прокси — Chrome использует указанный прокси
6. Тест параллельности — 2-3 сессии одновременно на разных портах
