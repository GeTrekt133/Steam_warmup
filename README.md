# Steam Farming Panel

Десктопное приложение для массового управления Steam-аккаунтами.

## Структура проекта

```
Steam_warmup/
├── backend/          ← Python (FastAPI) — бизнес-логика, API, база данных
├── frontend/         ← Electron + React — интерфейс приложения (ТЫ РАБОТАЕШЬ ЗДЕСЬ)
└── docker/           ← PostgreSQL и облачный API (запускается через docker-compose)
```

## Установка (для Dev 2 — frontend)

### 1. Установи Node.js

Скачай и установи **Node.js LTS** с https://nodejs.org/ (или через `winget install OpenJS.NodeJS.LTS`).

Проверь:
```bash
node --version   # должно быть v20+ или v24+
npm --version    # должно быть v10+
```

### 2. Установи зависимости frontend

```bash
cd Steam_warmup/frontend
npm install
```

### 3. Запуск в dev-режиме

Тебе нужно **два терминала** (backend запускает Dev 1 или он уже работает):

**Терминал 1 — Backend** (попроси Dev 1 запустить, или сам):
```bash
cd Steam_warmup/backend
venv/Scripts/activate
python -m uvicorn app.main:app --reload --port 8420
```

**Терминал 2 — Frontend** (твой основной):
```bash
cd Steam_warmup/frontend
npm run dev
```

После запуска откроется Electron-окно с приложением. При изменении кода страница обновится автоматически (hot reload).

## Где что лежит (для Dev 2)

```
frontend/src/
├── pages/              ← Страницы приложения (одна страница = один файл)
│   ├── DashboardPage.tsx
│   ├── AccountsPage.tsx
│   ├── LoginPage.tsx
│   └── ...
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

### Как добавить новую страницу

1. Создай файл в `frontend/src/pages/MyPage.tsx`
2. Добавь маршрут в `frontend/src/App.tsx`
3. Добавь ссылку в сайдбар в `frontend/src/components/layout/Sidebar.tsx`

### Стили

Используем **Tailwind CSS** — стили пишутся прямо в className:
```tsx
<div className="p-6 bg-zinc-900 rounded-lg border border-zinc-800">
  <h1 className="text-2xl font-bold">Заголовок</h1>
  <p className="text-zinc-400 mt-2">Описание</p>
</div>
```

Документация Tailwind: https://tailwindcss.com/docs

### API запросы к backend

```tsx
import api from '@/lib/api'

// GET запрос
const res = await api.get('/api/health')

// POST запрос
const res = await api.post('/api/auth/login', { username: 'test', password: '123' })
```

## Полная установка (для Dev 1)

### Backend
```bash
cd Steam_warmup/backend
python -m venv venv
venv/Scripts/activate
pip install -r requirements.txt
playwright install chromium
alembic upgrade head
python -m uvicorn app.main:app --reload --port 8420
```

### Docker (PostgreSQL + cloud API)
```bash
cd Steam_warmup/docker
docker-compose up -d
```

## Стек

| Слой | Технологии |
|------|-----------|
| Frontend | Electron, React 18, TypeScript, Vite, Tailwind CSS |
| Backend | Python 3.13, FastAPI, SQLAlchemy, Alembic |
| БД | SQLite (локально), PostgreSQL (Docker) |
| Auth | JWT + bcrypt |
| Шифрование | AES-256 (Fernet) |
