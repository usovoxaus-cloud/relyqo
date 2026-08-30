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

После деплоя задайте секрет `OWNER_PASSWORD` в Render и откройте `/owner`. Владелец вводит номер чека и пароль, после чего получает одноразовый QR со сроком действия 3 часа. Один номер чека нельзя использовать повторно.

## RELYQO Owner Review

Задайте отдельный секрет `REVIEW_PASSWORD` в Render и откройте `/review`. Этот пароль принадлежит только независимому RELYQO Review и не должен передаваться ресторану. Сильно противоречивые ответы временно не влияют на Score до решения Review. Обычная низкая оценка не считается спорной и учитывается автоматически.

## Неприкосновенные правила

- Business API предоставляет только GET; мутаций для BUSINESS_VIEWER нет.
- Score вычисляется только `app/score.py`, без генеративного AI.
- Сомнительные/критические сущности помещаются в `owner_reviews`; до решения они не включаются в рейтинг.
- Один visit допускает ровно одну rating (ограничение БД).
- В БД хранится только SHA-256 QR-токена; токен одноразовый и подписан HMAC.

## Production checklist

- `DEMO_MODE=false`, секрет QR сгенерирован хостингом.
- HTTPS обязателен; ограничьте CORS фактическим доменом.
- Подключите полноценную customer/owner аутентификацию до реальных пользователей.
- Настройте резервные копии PostgreSQL, мониторинг и ротацию секретов.
