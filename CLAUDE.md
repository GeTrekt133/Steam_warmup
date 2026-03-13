# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## О проекте

**Steam Farming Panel** — десктопное Windows-приложение для массового управления Steam-аккаунтами: авторегистрация, прогрев (бейджи + часы), фарм CS2, управление инвентарём, повышение уровней и встроенный маркетплейс.

Целевая аудитория: фермеры Steam-аккаунтов (10–500+ аккаунтов), трейдеры CS2 предметами.

## О пользователе (Dev 2)

Ты работаешь с **Dev 2** — начинающим фронтенд-разработчиком. Объясняй всё подробно и пошагово, как новичку. Dev 2 отвечает за frontend часть (Electron + React). Backend разрабатывает Dev 1.

## Структура репозитория

```
Steam_warmup/
├── frontend/    # Electron + React + TypeScript (Vite) — ЗДЕСЬ РАБОТАЕТ DEV 2
├── backend/     # Python FastAPI API сервер (Dev 1)
├── docker/      # PostgreSQL через docker-compose
├── PRD.md       # Полный список функциональных требований (все модули)
└── ROADMAP.md   # План разработки по фазам (8 фаз, 20 недель)
```

## Текущий статус: Фаза 0 — Фундамент (активная)

Сейчас готово:
- Каркас приложения (навигация, роутинг, layout)
- Авторизация (LoginPage, RegisterPage)
- Тёмная тема
- Backend health check
- Electron запускает Python backend как subprocess

Все остальные страницы — **заглушки** ("Модуль в разработке — Фаза 1").

### Следующие фазы
- **Фаза 1** (Недели 3–4): Импорт аккаунтов из TXT/maFile, таблица аккаунтов, модуль прокси, группы, шифрование
- **Фаза 2** (Недели 5–6): Авторегистрация Steam (captcha, SMS, генерация профиля)
- **Фаза 3** (Недели 7–8): Встроенный ASF (ArchiSteamFarm) без ручных конфигов
- **Фаза 4** (Недели 9–11): Прогрев бейджей + фарм часов → **MVP к концу этой фазы**
- **Фазы 5–8**: Лутер, уровни, маркетплейс, подписки, планировщик, релиз

## Требования

- **Node.js** v20+ или v24+ (установить с https://nodejs.org/ или `winget install OpenJS.NodeJS.LTS`)
- **npm** v10+

Проверка: `node --version` и `npm --version`

## Команды для разработки

### Frontend (выполнять из `frontend/`)
```bash
npm install        # Установить зависимости
npm run dev        # Запустить dev-сервер (Vite + Electron окно)
npm run build      # Сборка production (TypeScript + Vite)
npm run lint       # Проверка ESLint
npm run preview    # Просмотр production-сборки
```

### Backend (выполнять из `backend/`, обычно запускает Dev 1)
```bash
python -m venv venv              # Создать виртуальное окружение
venv/Scripts/activate            # Активировать
pip install -r requirements.txt  # Установить зависимости
playwright install chromium      # Браузер для автоматизации
alembic upgrade head             # Применить миграции БД
python -m uvicorn app.main:app --reload --port 8420  # Запуск
```

### Запуск в dev-режиме (нужны 2 терминала)
1. **Терминал 1 — Backend** (попроси Dev 1 запустить, или сам): `cd backend && venv/Scripts/activate && python -m uvicorn app.main:app --reload --port 8420`
2. **Терминал 2 — Frontend** (твой основной): `cd frontend && npm run dev`

После запуска откроется Electron-окно. При изменении кода страница обновится автоматически (hot reload).

## Архитектура frontend

### Технологии
- **Electron 40** — десктопная оболочка
- **React 19** + **TypeScript 5.9** — UI
- **Vite 7** — сборщик (с HMR — hot reload)
- **Tailwind CSS 4** — стили (пишутся прямо в className)
- **React Router 7** — роутинг (HashRouter для Electron)
- **Axios** — HTTP-клиент
- **Lucide React** — иконки

### Точки входа
- `electron/main.ts` — главный процесс Electron; автоматически запускает Python backend как subprocess, ждёт health check, убивает при выходе
- `electron/preload.ts` — IPC-мост, экспортирует `window.electronAPI` (getBackendUrl, platform, openFile)
- `src/main.tsx` — точка входа React

### Роутинг (`src/App.tsx`)
HashRouter (нужен для `file://` протокола Electron):
- **Публичные**: `/login`, `/register`
- **Защищённые** (обёрнуты в `ProtectedRoute`, проверяет `localStorage.auth_token`):
  - `/` — DashboardPage
  - `/accounts` — AccountsPage (управление аккаунтами)
  - `/proxies` — ProxiesPage (прокси)
  - `/registration` — RegistrationPage (авторегистрация Steam)
  - `/bots` — BotsPage (ASF боты)
  - `/warmup` — WarmupPage (прогрев: бейджи + часы)
  - `/farming` — FarmingPage (фарм часов)
  - `/marketplace` — MarketplacePage
  - `/settings` — SettingsPage

### API-клиент (`src/lib/api.ts`)
Единый Axios-инстанс. Автоматически:
- Добавляет JWT-токен из localStorage к каждому запросу
- При ошибке 401 очищает токен и перенаправляет на `/login`

Использование:
```tsx
import api from '@/lib/api'
const res = await api.get('/api/health')
const res = await api.post('/api/auth/login', { username, password })
```

### Path alias
`@/*` → `./src/*` (настроен в vite.config.ts и tsconfig.json)

### Структура компонентов
```
frontend/src/
├── pages/              ← Страницы (одна страница = один файл)
├── components/
│   ├── layout/         ← Sidebar, MainLayout (общий каркас)
│   └── ui/             ← Базовые UI-компоненты (кнопки, карточки)
├── lib/
│   ├── api.ts          ← HTTP-клиент для запросов к backend
│   └── utils.ts        ← Утилиты (cn() для стилей)
├── App.tsx             ← Роутинг (какой URL → какая страница)
├── main.tsx            ← Точка входа React
└── index.css           ← Глобальные стили + тёмная тема
```

### Стили
- **Tailwind CSS** — утилитарные классы прямо в className
- Тёмная тема по умолчанию (HSL CSS-переменные в `index.css`)
- `cn()` из `src/lib/utils.ts` — для условного объединения классов (clsx + tailwind-merge)

Пример стилей Tailwind:
```tsx
<div className="p-6 bg-zinc-900 rounded-lg border border-zinc-800">
  <h1 className="text-2xl font-bold">Заголовок</h1>
  <p className="text-zinc-400 mt-2">Описание</p>
</div>
```

### Как добавить новую страницу
1. Создай файл `src/pages/MyPage.tsx`
2. Добавь маршрут в `src/App.tsx` (внутрь MainLayout)
3. Добавь ссылку в `src/components/layout/Sidebar.tsx` (иконку из lucide-react)

## Архитектура backend

- **FastAPI** + async SQLAlchemy + Alembic (миграции)
- БД: SQLite (dev, aiosqlite), PostgreSQL (prod, asyncpg)
- Аутентификация: JWT + bcrypt
- Шифрование данных аккаунтов: Fernet (AES-256)
- Captcha: hcaptcha-challenger + Groq LLM
- Автоматизация: Playwright (браузер)
- Backend работает на порту **8420**
- Все API-роуты начинаются с `/api`

## Модули продукта (из PRD)

Полный список модулей, которые нужно реализовать:
1. **Steam Аккаунты** — импорт TXT/maFile, таблица, группы, шифрование
2. **Регистрация** — авторег Steam с captcha и SMS
3. **ASF Боты** — встроенный ArchiSteamFarm, создание ботов в 2 клика
4. **Прогрев (Бейджи)** — автовыполнение Community Leader badge (~4 мин)
5. **Фарм часов** — ручной и умный режим с имитацией поведения
6. **Достижения** — разблокировка выбранных достижений
7. **Повышение уровней** — донор-аккаунт, авторасчёт и раздача наборов карточек
8. **Лутер** — перенос инвентаря на мастер-аккаунт
9. **Пополнение кошелька** — прямое пополнение Steam
10. **Планировщик задач** — cron-подобные задачи
11. **Прокси** — добавление, проверка, ротация, автопривязка
12. **Маркетплейс** — покупка аккаунтов, авторегов, кодов пополнения
13. **SaaS система** — подписки, внутренний кошелёк, тикеты

## Ключевые соглашения

- Весь код и комментарии в README — на **русском языке**
- ESLint 9 (flat config), без Prettier
- Тестирование пока минимальное (Phase 0)
- API-запросы только через общий Axios-инстанс из `@/lib/api`
- Backend запускается Electron автоматически (или вручную Dev 1)
