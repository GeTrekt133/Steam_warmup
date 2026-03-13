# Тестирование Phase 2 — Регистрация и Steam Guard

## Предварительные требования

1. Backend запущен: `cd Steam_warmup/backend && venv/Scripts/activate && python -m uvicorn app.main:app --reload --port 8420`
2. Frontend запущен: `cd Steam_warmup/frontend && npm run dev`
3. В `.env` (папка backend) указаны ключи:
   - `GROQ_API_KEY=...` — для Groq-солвера капчи (быстрый)
   - `GEMINI_API_KEY=...` — для Gemini-солвера капчи (fallback)
   - Достаточно одного из двух
4. Авторизация в панели: зарегистрируйся через UI или используй существующий аккаунт

Все запросы к API требуют JWT-токен. Получить его:
```bash
# Регистрация
curl -X POST http://127.0.0.1:8420/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "123456"}'

# Логин — запомни token
curl -X POST http://127.0.0.1:8420/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "123456"}'
```

Дальше все curl с `-H "Authorization: Bearer <TOKEN>"`.

---

## 2.2 — Captcha Pipeline

### Тест 1: Список доступных солверов

```bash
curl http://127.0.0.1:8420/api/captcha/solvers \
  -H "Authorization: Bearer <TOKEN>"
```

**Ожидание:** `{"available": ["groq"], "stats": {}}` (или `["gemini"]`, или оба — зависит от ключей в .env). Если пустой список — ключи не указаны.

### Тест 2: Решить капчу (Groq)

```bash
curl -X POST http://127.0.0.1:8420/api/captcha/solve \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"solver": "groq"}'
```

**Ожидание:** Ответ через 5-30 секунд:
```json
{
  "success": true,
  "token": "P1_eyJhbGciOi...",
  "solver": "groq",
  "elapsed_sec": 12.3,
  "attempts": 1,
  "error": null
}
```
Если `success: false` — посмотри `error`. Частые причины: невалидный API ключ, rate limit, IP-бан от hCaptcha.

### Тест 3: Решить капчу (Gemini)

```bash
curl -X POST http://127.0.0.1:8420/api/captcha/solve \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"solver": "gemini"}'
```

**Ожидание:** Откроется окно Chromium (headless=false), автоматически решит капчу. Ответ через 30-90 секунд. Формат тот же.

### Тест 4: Авто-выбор солвера (fallback)

```bash
curl -X POST http://127.0.0.1:8420/api/captcha/solve \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Ожидание:** Сначала пробует Groq (быстрый), если не получилось — Gemini (надёжный). Поле `solver` в ответе покажет кто решил.

### Тест 5: Статистика после нескольких решений

```bash
curl http://127.0.0.1:8420/api/captcha/solvers \
  -H "Authorization: Bearer <TOKEN>"
```

**Ожидание:** stats теперь заполнен:
```json
{
  "available": ["groq", "gemini"],
  "stats": {
    "groq": {"attempts": 3, "successes": 2, "failures": 1, "success_rate": "67%", "avg_time": "8.5s"}
  }
}
```

---

## 2.4 — Генератор профилей

Генератор используется внутри registration service, но можно проверить напрямую:

```bash
cd Steam_warmup/backend
venv/Scripts/python -c "
from app.services.profile_generator import generate_login, generate_password
for i in range(5):
    print(f'{generate_login()} / {generate_password()}')
print('---')
for i in range(3):
    print(generate_login(prefix='farm'))
"
```

**Ожидание:**
```
coolwolf382 / aKx3dR!jmLbqwT
darkfox91 / Mn5pQz@fWgXjUh
...
---
farm_4821
farm_127
farm_9503
```

Логин: 6-20 символов, латиница + цифры. Пароль: 14 символов, буквы + цифры + спецсимвол.

---

## 2.1 — Регистрация одного аккаунта

### Требования
- Рабочий email с IMAP-доступом (Gmail, Yandex, Mail.ru, Outlook)
- Для Gmail: нужен App Password (обычный пароль не работает с IMAP)
- Хотя бы один captcha-солвер настроен

### Тест 6: Регистрация с авто-генерацией логина/пароля

```bash
curl -X POST http://127.0.0.1:8420/api/register/single \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "your_email@yandex.ru:email_password_here"
  }'
```

**Ожидание (успех):**
```json
{
  "success": true,
  "login": "darkwolf482",
  "password": "Kx3dR!jmLbqwT",
  "email": "your_email@yandex.ru",
  "steam_id": "76561199...",
  "account_id": 15,
  "error": null,
  "steps": [
    {"step": "captcha_init", "status": "done", "detail": "gid=..."},
    {"step": "captcha_solve", "status": "done", "detail": "solver=groq, 8.2s"},
    {"step": "email_verify", "status": "done", "detail": "creationid=..."},
    {"step": "email_fetch", "status": "done", "detail": null},
    {"step": "email_confirm", "status": "done", "detail": null},
    {"step": "create_account", "status": "done", "detail": "steamid=76561199..."}
  ]
}
```

**Ожидание (ошибка капчи):** `success: false`, steps покажут на каком шаге упало.

**Время:** ~1-3 минуты (капча + ожидание email).

### Тест 7: Регистрация с указанным логином/паролем

```bash
curl -X POST http://127.0.0.1:8420/api/register/single \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "another_email@mail.ru:email_pass",
    "login": "my_custom_login_42",
    "password": "MyStr0ng!Pass99"
  }'
```

**Ожидание:** То же, но логин/пароль будут именно указанные.

### Тест 8: Проверка сохранения в БД

После успешной регистрации аккаунт автоматически сохраняется. Проверь:

```bash
curl http://127.0.0.1:8420/api/accounts/ \
  -H "Authorization: Bearer <TOKEN>"
```

**Ожидание:** Новый аккаунт в списке с `steam_id`, заметка "Авторег. Email: ...".

---

## Массовая регистрация (batch)

### Тест 9: Запуск batch-регистрации

```bash
curl -X POST http://127.0.0.1:8420/api/register/batch \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "emails": [
      "email1@yandex.ru:pass1",
      "email2@yandex.ru:pass2",
      "email3@yandex.ru:pass3"
    ],
    "login_prefix": "batch_test",
    "max_concurrent": 2
  }'
```

**Ожидание:** Мгновенный ответ:
```json
{"task_id": "a1b2c3d4", "total": 3, "status": "started"}
```

### Тест 10: Проверка статуса batch

```bash
curl http://127.0.0.1:8420/api/register/status/a1b2c3d4 \
  -H "Authorization: Bearer <TOKEN>"
```

**Ожидание:** Прогресс обновляется по мере завершения:
```json
{
  "task_id": "a1b2c3d4",
  "total": 3,
  "completed": 1,
  "succeeded": 1,
  "failed": 0,
  "in_progress": 2,
  "results": [...]
}
```

Логины будут: `batch_test_001`, `batch_test_002`, `batch_test_003`.

---

## 2.5 — Привязка Steam Guard (SDA)

### Требования
- Существующий Steam-аккаунт (уже зарегистрированный)
- Email этого аккаунта с IMAP-доступом
- Аккаунт БЕЗ уже привязанного Mobile Authenticator

### Тест 11: Привязка Guard к аккаунту

Сначала узнай ID аккаунта из списка (`GET /api/accounts/`), потом:

```bash
curl -X POST "http://127.0.0.1:8420/api/accounts/15/link-guard?email=steam_email@yandex.ru&email_password=email_pass_here" \
  -H "Authorization: Bearer <TOKEN>"
```

**Ожидание:** Мгновенный ответ:
```json
{
  "status": "started",
  "message": "Привязка Guard запущена для darkwolf482",
  "account_id": 15
}
```

**Что происходит в фоне (смотри логи backend):**
1. `[login] RSA key obtained...` — шифрование пароля
2. `[login] Требуется email код для входа...` — ждёт код из email
3. `[login] Успешный вход. steamid=...` — залогинился
4. `[add_auth] Authenticator добавлен. Revocation: R12345` — получил secrets
5. `[finalize] ...` — подтверждение через email

**Время:** ~1-2 минуты (два email: код входа + код активации).

### Тест 12: Проверка результата

После завершения (смотри логи), проверь аккаунт:

```bash
curl http://127.0.0.1:8420/api/accounts/15 \
  -H "Authorization: Bearer <TOKEN>"
```

**Ожидание:** `has_mafile: true` — Guard привязан.

### Тест 13: Steam Guard код после привязки

```bash
curl http://127.0.0.1:8420/api/accounts/15/guard-code \
  -H "Authorization: Bearer <TOKEN>"
```

**Ожидание:** `{"code": "V2K9R", "ttl": 18}` — код генерируется из свежего shared_secret.

### Тест 14: Повторная привязка (ошибка)

```bash
curl -X POST "http://127.0.0.1:8420/api/accounts/15/link-guard?email=x@y.ru&email_password=z" \
  -H "Authorization: Bearer <TOKEN>"
```

**Ожидание:** `400 — "Guard уже привязан к этому аккаунту"`.

---

## Возможные ошибки и что делать

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `Нет доступных солверов` | Нет GROQ_API_KEY / GEMINI_API_KEY в .env | Добавь ключ, перезапусти backend |
| `hCaptcha solve failed` | Капча не решена (сложный тип, rate limit) | Попробуй другой солвер или подожди |
| `IMAP login failed` | Неверный пароль email или IMAP отключён | Для Gmail нужен App Password; для Yandex включи IMAP в настройках |
| `Steam confirmation email not found` | Письмо не дошло или regex не сматчил | Проверь Spam, подожди дольше |
| `status=29 (требуется телефон)` | Steam требует телефон для этого аккаунта | Аккаунт слишком новый или региональное ограничение |
| `status=2 (уже есть authenticator)` | Guard уже привязан | Сначала отвяжи через SDA |
| `status=84 (rate limit)` | Слишком много попыток | Подожди 30+ минут |
| `Steam rejected account creation` | Логин занят или пароль слабый | Попробуй другой логин/пароль |

---

## Полный happy-path сценарий (от регистрации до Guard)

1. Настрой `.env` (GROQ_API_KEY)
2. Запусти backend + frontend
3. Авторизуйся в панели
4. **Тест 1** — проверь что солвер доступен
5. **Тест 2** — реши тестовую капчу
6. **Тест 6** — зарегистрируй аккаунт (нужен свежий email)
7. **Тест 8** — проверь что аккаунт в БД
8. **Тест 11** — привяжи Guard к зарегистрированному аккаунту
9. **Тест 12** — проверь что maFile сохранён
10. **Тест 13** — получи Steam Guard код

Если всё прошло — Phase 2 работает от начала до конца.
