# RELYQO v1.1

Рабочий vertical slice: одноразовый подписанный QR → Verified Visit → оценка → PostgreSQL → детерминированный RELYQO Score → PWA.

## Локальный запуск (Docker Desktop)

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose exec web python -m app.scripts.seed_demo
```

Откройте напечатанный `VISIT_URL`. API: `http://localhost:8000/docs`; health: `http://localhost:8000/v1/health`.

## Публичный деплой

Проект содержит `render.yaml`: загрузите репозиторий на GitHub, в Render выберите **New → Blueprint**, подключите репозиторий и подтвердите ресурсы. После первого деплоя замените `PUBLIC_BASE_URL` на выданный URL и выполните в Render Shell:

```bash
python -m app.scripts.seed_demo
```

Для Railway/Fly.io используйте `Dockerfile` и подключите PostgreSQL + Redis, задав переменные из `.env.example`.

## Owner-панель Fregat

После деплоя задайте секрет `OWNER_PASSWORD` в Render и откройте `/owner`. Первый вход с именем `fregat-owner` и этим паролем создаёт ролевой аккаунт Fregat. Пароль сохраняется в PostgreSQL только как scrypt-хеш. После входа владелец вводит номер чека и получает одноразовый QR со сроком действия 3 часа. Один номер чека нельзя использовать повторно.

## RELYQO Owner Review

Задайте отдельный секрет `REVIEW_PASSWORD` в Render и откройте `/review`. Первый вход с именем `relyqo-reviewer` создаёт независимый ролевой аккаунт Review. Этот аккаунт не должен передаваться ресторану. Сильно противоречивые ответы временно не влияют на Score до решения Review. Обычная низкая оценка не считается спорной и учитывается автоматически.

Авторизация использует случайные отзываемые HttpOnly-сессии сроком 8 часов с `SameSite=Strict`; на HTTPS cookie также получает `Secure`. Роли проверяются сервером на каждом защищённом запросе.

## Неприкосновенные правила

- Business API предоставляет только GET; мутаций для BUSINESS_VIEWER нет.
- Score вычисляется только `app/score.py`, без генеративного AI.
- Сомнительные/критические сущности помещаются в `owner_reviews`; до решения они не включаются в рейтинг.
- Один visit допускает ровно одну rating (ограничение БД).
- В БД хранится только SHA-256 QR-токена; токен одноразовый и подписан HMAC.

## Production checklist

- `DEMO_MODE=false`, секрет QR сгенерирован хостингом.
- HTTPS обязателен; ограничьте CORS фактическим доменом.
- После создания первых аккаунтов удалите bootstrap-секреты `OWNER_PASSWORD` и `REVIEW_PASSWORD` из окружения и настройте отдельный процесс восстановления доступа.
- Настройте резервные копии PostgreSQL, мониторинг и ротацию секретов.
