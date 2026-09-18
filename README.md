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

Каждый пользователь может сменить собственный пароль в своей панели. После смены пароля все ранее открытые сеансы этого аккаунта автоматически завершаются. Владелец может сбросить пароль сотрудника в `/owner`; старый пароль и все сеансы сотрудника сразу перестают работать. После пяти неверных попыток вход блокируется на 15 минут. Пароли никогда не сохраняются в открытом виде, а смена, сброс, неудачные входы и блокировки фиксируются в Audit Log.

Владелец и независимый RELYQO Review могут заранее создать одноразовый резервный код в своей защищённой панели. Код показывается только один раз; в PostgreSQL хранится только SHA-256-хеш. Страница `/recover` позволяет установить новый пароль по этому коду, отзывает все старые сеансы и уничтожает использованный код. Создание нового кода отменяет предыдущий.

## Пилотный отчёт Business

Публичная read-only панель `/business` показывает Score, категории и историю, а также достаточность текущей выборки: прогресс до 20 учтённых оценок, процент завершения формы, незавершённые визиты, очередь Review и сильную/слабую категорию. При малой выборке интерфейс явно запрещает использовать ранний сигнал для кадровых или финансовых решений.

## AI-аналитик Business

В Business-панель встроен изолированный AI-аналитик на OpenAI Responses API. Для экономичного пилота по умолчанию используется `gpt-5.6-luna`; модель можно заменить переменной `OPENAI_MODEL`. В Render добавьте секрет `OPENAI_API_KEY`. Ключ существует только на сервере и никогда не передаётся браузеру.

AI получает только агрегированные показатели Fregat без имён гостей, сотрудников, номеров чеков и отдельных оценок. Запросы отправляются с `store=false`. Запуск анализа разрешён только владельцу с действующей HttpOnly-сессией, ограничен по частоте и кешируется на 10 минут. Без ключа остальная система продолжает работать, а AI-кнопка показывает, что подключение ещё не настроено.

AI не рассчитывает RELYQO Score, не изменяет оценки, не принимает решения Owner Review и не записывает свои рекомендации в рейтинг. Его вывод — только справочная интерпретация детерминированных агрегатов.

## Мой RELYQO и AI-помощник потребителя

Страница `/me` предоставляет отдельный аккаунт потребителя: регистрация, безопасная HttpOnly-сессия, синхронизированное избранное и история Community-оценок. Локальное избранное из браузера переносится в аккаунт после входа. Активный каталог состоит только из зарегистрированных организаций и мест, добавленных потребителями RELYQO.

В личном кабинете доступен read-only AI-помощник. Он может объяснять доступные показатели, учитывать избранное и собственные оценки пользователя, помогать выбирать организации разных сфер услуг. Помощник не получает пароль или историю геолокации, не меняет Verified RELYQO Score, Community Score и решения Owner Review. Запросы ограничены по частоте и отправляются с `store=false`.

На странице `/nearby` доступен публичный помощник «Спросить RELYQO». Человек может написать простую потребность — например, найти чистое место рядом или лучшее соотношение цены и качества. Сервер заново читает фактические оценки из PostgreSQL и детерминированно отбирает варианты; клиент не передаёт готовые баллы. Verified и Community показываются отдельными списками и никогда не объединяются в один рейтинг. ИИ получает только короткий обезличенный список с агрегированными оценками и расстоянием, объясняет уже рассчитанный результат и предлагает перейти к профилю или собственной оценке. Если OpenAI временно недоступен, работает автоматическое объяснение без ИИ.

RELYQO проектируется как универсальная платформа качества услуг: рестораны и кафе являются первой вертикалью, но каталог уже поддерживает отели, красоту, здоровье, развлечения, торговлю, автосервисы, профессиональные услуги, образование и образовательные учреждения, а также другие категории.

## Рекламный модуль

В `/admin` администратор может создать рекламную кампанию и задать её понятные параметры: внутреннее название, рекламодателя, верхнюю панель или угловой блок, страницы показа, короткий заголовок и текст, подпись кнопки, HTTPS-ссылку, даты начала и окончания и необязательный общий лимит показов. В списке кампаний есть ссылка «Посмотреть как пользователь». Кампания автоматически не показывается до даты начала, после даты окончания или после достижения лимита.

Для верхней панели действуют компактные пределы: заголовок до 55 и текст до 160 символов. Для углового блока — до 80 и 240 символов соответственно. Можно прикрепить фотографию, короткое видео или презентацию. Поддерживаются JPEG, PNG и WebP до 5 МБ, MP4 и WebM до 25 МБ, PDF, PPT и PPTX до 15 МБ. Фото и видео показываются внутри баннера, презентация открывается отдельным безопасным файлом. Медиа можно удалить, а кампанию — включить или поставить на паузу. Существующую кампанию можно редактировать без потери медиа, числа показов и переходов; рядом со счётчиками Admin‑панель показывает CTR — долю переходов от показов.

Активные кампании показываются только на страницах потребителей. Каждый блок явно помечен словом `Реклама`, закрывается пользователем и собирает только агрегированное число показов и переходов без персонального профилирования.

Реклама и её медиа хранятся отдельно от организаций и оценок. Оплата не даёт места в официальном рейтинге, не влияет ни на Verified RELYQO Score, ни на Community Score и не участвует в Owner Review. Создание, загрузка медиа, включение и приостановка кампаний записываются в Audit Log.

## Самостоятельная регистрация бизнеса

Страница `/business-owner` позволяет владельцу создать отдельный аккаунт и вручную заполнить профиль организации: название, сферу услуг, описание, адрес, город, страну, телефон, сайт и координаты. Браузер может подставить текущее местоположение только после явного разрешения владельца.

Самостоятельно зарегистрированный профиль получает статус `SELF_REGISTERED`. Это ещё не подтверждённый партнёр и не основание для Verified RELYQO Score. Владелец может редактировать только сведения профиля. API явно запрещает ему создавать Community-оценки, изменять оценки, Score и решения Owner Review.

Для проверки заявок задайте отдельный секрет `ADMIN_PASSWORD` и откройте `/admin`. Первый вход с именем `relyqo-admin` создаёт административный аккаунт. Решение `PUBLISH` переводит профиль в статус `PUBLISHED` и разрешает показывать его в каталоге, но не присваивает статус QR-партнёра и не создаёт Verified Score. Отдельное решение `ENABLE_QR` подключает проверенную организацию к выдаче одноразовых QR. После этого её владелец выпускает QR по номеру чека прямо в `/business-owner`; одинаковые номера чеков запрещены внутри одного филиала. Решение `REJECT` скрывает профиль. Если владелец изменит уже опубликованные или QR-подключённые сведения, профиль снова получает `SELF_REGISTERED` и должен пройти повторную проверку.

Community-оценка теперь принимается только от вошедшего аккаунта с ролью `CONSUMER`. Бизнес-владелец, кассир, Review и AI не могут участвовать в выставлении пользовательских оценок.

## Отдельные контуры Consumer и Admin

Публичный вход потребителя доступен по `/consumer`, личный кабинет — по `/me`, а административный центр — только по `/admin`. Админ-панель имеет самостоятельный экран входа и серверную роль `RELYQO_ADMIN`. Она показывает агрегированное состояние платформы, очередь профилей организаций и последние события Audit Log. Потребительский аккаунт не может читать административные API, а администратор, владелец бизнеса, кассир и Review не могут отправлять оценки даже при наличии действующего QR.

Admin может проверять и публиковать профиль организации и отдельно подключать выпуск QR. Он не может редактировать сведения за владельца, создавать или изменять оценки, менять Score и принимать решения по спорным Verified-оценкам. Последнее остаётся исключительной задачей отдельного контура `/review`. Score по-прежнему вычисляется только детерминированным Score Engine.

Если пароль Admin потерян, владелец инфраструктуры может выполнить контролируемое восстановление: заменить секрет `ADMIN_PASSWORD` в Render, дождаться перезапуска и один раз войти как `relyqo-admin` с новым значением. Сервер обновит хеш пароля существующего Admin, снимет блокировку, отзовёт старые Admin-сессии и запишет `AUTH_ADMIN_RECOVERED_FROM_ENV` в Audit Log. После успешного восстановления bootstrap-секрет следует удалить из окружения.

## План SMS-восстановления доступа

Текущий резервный код остаётся рабочим офлайн-механизмом восстановления. Следующий production-этап — подтверждённый номер телефона и настоящий одноразовый SMS-код. Реализация должна включать отдельный SMS-провайдер, хранение только хеша кода, короткий срок действия, одноразовое использование, лимит запросов и попыток, блокировку перебора, отзыв всех старых сессий после восстановления и запись событий в Audit Log. До подключения провайдера интерфейс не показывает неработающую кнопку «Отправить SMS».

## Карта организаций и услуг рядом

Страница `/nearby` — RELYQO Map с Google Maps и поиском Google Places. С разрешения пользователя она определяет текущее местоположение и показывает организации в любом положительном радиусе, который пользователь вводит вручную; верхнего ограничения радиуса в RELYQO нет. Выбранные радиус, сфера и количество результатов сохраняются на текущем устройстве. Пользователь отдельно выбирает сферу: питание, гостиницы, красота, здоровье, развлечения, магазины, автоуслуги, профессиональные услуги или образование. Координаты используются только браузером для текущего запроса и не сохраняются RELYQO.

Google используется для изображения улиц и живого поиска названия, адреса, категории и координат организаций. Google Rating не запрашивается, не импортируется и не влияет ни на один Score. Результаты Google Maps не сохраняются автоматически. Найденный внешний объект нельзя оценивать напрямую: потребитель подтверждает сведения, RELYQO сохраняет собственную карточку и разрешённый для долговременного хранения Google Place ID, после чего открывается Community-оценка. Place ID предотвращает дубли одной организации; каталог Google при этом не копируется в базу. Для карты нужен ограниченный по домену ключ `GOOGLE_MAPS_BROWSER_KEY` с доступом к Maps JavaScript API и Places API (New).

Вкладка **«Все с оценками RELYQO»** загружает собственный глобальный каталог без требования геолокации. В ней вместе перечисляются партнёры с Verified-оценками и пользовательские карточки с Community-оценками, но типы баллов остаются явно разделёнными и не объединяются в одну формулу. Поиск и серверные фильтры работают по названию, стране, городу, сфере, типу оценки и минимальному рейтингу. Каталог выдаётся страницами по 50 записей через кнопку **«Показать ещё»**, поэтому браузеру не нужно загружать всю мировую базу сразу. Первые три организации с минимум тремя оценками получают заметку **«ТОП»** по выбранному типу рейтинга; позиция считается автоматически по баллу и числу оценок, не продаётся и не редактируется бизнесом.

### Community Score для любого объекта

Вошедший потребитель может нажать **«Оценить в RELYQO»** у зарегистрированной организации или места, добавленного в каталог RELYQO, и оставить отдельную общественную оценку качества. В базе хранится идентификатор объекта, сама оценка, идентификатор аккаунта потребителя и технический хеш защиты от повторной отправки; точная геолокация пользователя не сохраняется в Community-оценке. Один аккаунт может оценить один объект один раз.

Community Score никогда не входит в официальный RELYQO Score и не изменяет его. Verified RELYQO Score по-прежнему создаётся только после одноразового QR и подтверждённого посещения, рассчитывается детерминированным Score Engine, а противоречивые подтверждённые оценки направляются в Owner Review.

Названия критериев оценки адаптируются к сфере, но внутренние числовые поля и формула остаются стабильными. Например, автосервис оценивается по качеству работы, срокам и сервису, аккуратности и прозрачности цены; гостиница — по комфорту, обслуживанию, чистоте и ценности. На карте и в профиле показывается детализация показателей RELYQO.

Потребитель может приложить к Community-оценке или подтверждённой QR-оценке одну фотографию JPEG, PNG или WebP до 5 МБ. Фото хранится как дополнительный материал оценки. AI через OpenAI Responses API описывает только видимые признаки состояния или результата и не выставляет балл, не подтверждает посещение, не делает медицинских или санитарных заключений и не изменяет Score. При спорной подтверждённой оценке независимый Review видит фото и AI-наблюдение вместе с ответами потребителя. Главным подтверждением официальной оценки остаётся одноразовый QR; фотография его не заменяет.

Если нужного объекта ещё нет в каталоге, пользователь может нажать **«Добавить место в RELYQO»**. RELYQO сохраняет название, сферу, короткое описание, адрес и координаты как пользовательские данные и явно отмечает такой объект. Поддерживаются заведения питания, гостиницы, красота, здоровье, развлечения, магазины, автоуслуги, профессиональные и другие услуги. Пользовательский объект получает только Community Score до официального подключения QR.

Автоматический импорт внешнего каталога отключён. Google Places используется только для живого поиска, а карточки RELYQO создаются отдельно из данных, введённых самим потребителем. Существующие исторические ссылки не удаляются из базы автоматически, чтобы не нарушить историю пользовательских действий.

### Профили и официальные рейтинги

Кнопка **«Подробнее»** на карте открывает `/place`. Профиль явно разделяет Verified RELYQO Score и Community Score, позволяет потребителю оценить объект и добавить его в избранное.

Страница `/rankings` показывает официальные позиции партнёров по городу, стране или миру. В рейтинг попадают только организации с минимум 20 подтверждёнными оценками. Сортировка детерминирована: Verified Score, число подтверждённых оценок, затем название. Community Score в официальной позиции не участвует; организации с меньшей выборкой показываются отдельно как предварительные.

## Аккаунты сотрудников Fregat

Владелец управляет кассирами на `/owner`: создаёт отдельные аккаунты и немедленно отключает доступ при необходимости. Сотрудник входит на `/staff` и может только выпустить одноразовый QR по номеру чека. Его аккаунт не даёт прав управления Business, сотрудниками или Review. Каждый новый QR хранит автора и время выдачи; последние 100 записей доступны владельцу в read-only журнале со статусами `ACTIVE`, `USED` и `EXPIRED`.

## Неприкосновенные правила

- Business API предоставляет только GET; мутаций для BUSINESS_VIEWER нет.
- Score вычисляется только `app/score.py`, без генеративного AI.
- Сомнительные/критические сущности помещаются в `owner_reviews`; до решения они не включаются в рейтинг.
- Один visit допускает ровно одну rating (ограничение БД).
- В БД хранится только SHA-256 QR-токена; токен одноразовый и подписан HMAC.

## Production checklist

- `DEMO_MODE=false`, секрет QR сгенерирован хостингом.
- HTTPS обязателен; ограничьте CORS фактическим доменом.
- После создания первых аккаунтов удалите bootstrap-секреты `OWNER_PASSWORD`, `REVIEW_PASSWORD` и `ADMIN_PASSWORD` из окружения и настройте отдельный процесс восстановления доступа.
- Настройте резервные копии PostgreSQL, мониторинг и ротацию секретов.

## Аналитика потребителей и категории в Admin

Раздел `/admin/analytics` открывается из админки. Данные и выводы ИИ доступны только роли `RELYQO_ADMIN`; Consumer, Business Owner, Owner, Staff и Review получают отказ. Статическая оболочка страницы не содержит статистики. API: `GET /v1/admin/analytics` и `POST /v1/admin/analytics/insights`. Ответы не кешируются браузером.

Отчёт фильтруется по датам (UTC, максимум 366 дней), организации и категории. SQL рассчитывает подтверждённые посещения, число уникальных аккаунтов авторов, безымянные оценки, распределение общей оценки и средние по пяти критериям. Посещения относятся к дате подтверждения, оценки — к дате отправки; поэтому отношение этих двух чисел не называется конверсией. Уникальные авторы считаются заново для каждого среза, а не суммируются между организациями. Посещения без оценки не позволяют определить уникального человека. Полный офлайн-поток клиентов без регистрации в RELYQO неизвестен.

Условная удовлетворённость: 8–10 — довольны, 5–7 — нейтрально, 1–4 — недовольны, по общей оценке. Это доля оценок, не NPS и не установленное эмоциональное состояние человека. Verified и Community выбираются отдельно. Проверяемые/исключённые оценки не входят в удовлетворённость. Community филиалов объединяются по организации; категория берётся из текущего каталога, а не из присланного потребителем значения.

ИИ использует существующие серверные `OPENAI_API_KEY` и `OPENAI_MODEL`. Он получает сводки, недельную динамику с числом наблюдаемых дней, до 30 категорий и 20 организаций с оценками; адреса почты, идентификаторы авторов, пароли, фотографии и персональная история не передаются. ИИ не меняет рейтинги или модерацию. Первый отчёт при наличии оценок запускается при открытии страницы; повторный — кнопкой. Сервер кеширует одинаковый отчёт на 15 минут и ограничивает новые запросы администратора одним в минуту (в пределах процесса). При недоступности ИИ обычная статистика продолжает работать.

Форма «Добавить сферу услуг» вызывает `POST /v1/admin/service-categories`; название и поисковая группа сохраняются в `service_categories`. Публичный `GET /v1/public/service-categories` содержит только справочник категорий. Регистрация/редактирование бизнеса, добавление мест, оценки и фильтры проверяют категорию по этому справочнику. Неизвестные коды отклоняются. Встроенные категории сохранены; новые получают внутренний код автоматически. Миграция `0022` добавляет справочник и индексы дат для аналитических запросов, не изменяя существующие оценки.

Проверки: `python -m pytest tests/test_admin_analytics.py`; DOM-проверки без браузера и настоящих запросов ИИ: `npm install --prefix /tmp/relyqo-dom-tests linkedom`, затем `NODE_PATH=/tmp/relyqo-dom-tests/node_modules node --test tests/admin-analytics-ui.cjs`.

## Восстановление пароля по email

Используется существующая авторизация RELYQO (FastAPI, `users`, scrypt, серверные cookie-сессии), не Supabase. Все интерактивные роли — Consumer, Business Owner, Fregat Owner, Staff, RELYQO Review и Admin — могут открыть `/account-security`, указать email и текущий пароль, затем подтвердить адрес по ссылке из письма. Только заранее подтверждённый адрес используется на `/forgot-password`. Аккаунт, пароль от которого уже утрачен и почта к которому никогда не привязывалась, нельзя безопасно восстановить автоматически; для Admin сохраняется аварийное восстановление через `ADMIN_PASSWORD` в Render.

Перед публикацией нужны серверные переменные:

- `RESEND_API_KEY`: ключ Resend с разрешением отправки писем для нужного домена. Секрет, не включать в frontend, Git или скриншоты.
- `RECOVERY_EMAIL_FROM`: адрес, например `noreply@ваш-домен`, на домене, подтверждённом в Resend через DNS. Тестовый отправитель не подходит для произвольных получателей.
- `PUBLIC_BASE_URL=https://relyqo.onrender.com` либо фактический production origin без пути, query и fragment.
- `RECOVERY_ALLOW_LOCAL_URLS=false` в production (значение по умолчанию). Только для локальной проверки можно поставить `true` и указать `PUBLIC_BASE_URL=http://127.0.0.1:8767`.
- Как и прежде: `DEMO_MODE=false`, сильный случайный `QR_SECRET`, корректный `DATABASE_URL` и `CORS_ORIGINS` с фактическим origin. Секрет QR генерируется существующим Blueprint. Проверьте HTTPS и Secure-cookie за доверенным reverse proxy.

Отправка идёт через `https://api.resend.com/emails` по HTTPS. Это совместимо с Render Free: стандартные SMTP-порты на Free заблокированы. В коде нет SMTP-обхода, второго провайдера авторизации или ключей клиента.

Источник: [ограничения Render Free](https://render.com/docs/free), [Resend API](https://resend.com/docs/api-reference/emails/send-email), [домен отправителя](https://resend.com/docs/knowledge-base/how-do-i-create-an-email-address-or-sender-in-resend).

### Миграция и ссылки

Перед запуском новой версии примените `alembic upgrade head` (миграции `0020` и `0021`). Существующий Docker CMD уже выполняет миграции перед стартом. Миграции добавляют `consumer_emails`, `password_recovery_tokens`, `recovery_rate_limits` и поля проверки кода/счётчика попыток, сохраняя существующие учётные записи и старые ссылки. Перед production-миграцией нужна резервная копия БД.

Публичные страницы: `/forgot-password`, `/reset-password`, `/verify-email`; защищённая настройка адреса: `/account-security`. Для сброса отправляется шестизначный одноразовый код со сроком 10 минут. Ссылка подтверждения email использует отдельный случайный токен во fragment `#token=…`, который удаляется из адресной строки после чтения. Redirect после сброса не принимается от пользователя и автоматического входа нет. Страницы не подключают рекламу, аналитику или сторонние скрипты; выставлены CSP, `no-store`, `no-referrer` и запрет iframe.

### Гарантии и ограничения

- Код сброса состоит из 6 случайных цифр, хранится как HMAC-SHA256 с серверным `QR_SECRET`, нормализованным email и случайным идентификатором запроса, действует 10 минут и используется атомарно один раз. Код подтверждения email содержит 32 случайных байта и действует 30 минут.
- Код или токен привязан к аккаунту, его роли, подтверждённому адресу и текущему хешу пароля. Старые ссылки Consumer продолжают работать только для Consumer. Смена пароля другим способом делает его недействительным.
- Сброс завершает все старые сессии и инвалидирует остальные ссылки. Новый пароль хранится тем же scrypt, что и при обычной регистрации.
- Для существующего и неизвестного email одинаковый ответ 202; поиск аккаунта и отправка вынесены в BackgroundTasks после ответа. Отсутствие конфигурации возвращает одинаковый 503 для любого адреса.
- DB-backed лимиты: 30 запросов/час на ASGI client IP, 3 письма/час на email, 3 попытки привязки/час на пользователя и 10 попыток ввода кода/час на email. Каждый отдельный код допускает максимум 5 попыток, в том числе при смене часа; повторная отправка отменяет предыдущий код. Доверять forwarded IP можно только от фактического reverse proxy; иначе общий IP прокси может ограничить нескольких пользователей.
- При отказе почтового API токен инвалидируется; в логах только тип события, без адреса, ключа или ссылки. Ответ «запрос принят» не является подтверждением доставки. BackgroundTasks не является устойчивой очередью: при остановке процесса письмо может не отправиться, пользователь должен повторить запрос. Для сквозной проверки production нужны подтверждённый адрес тестового аккаунта, реальное письмо, вход после сброса и уведомление о смене пароля.
- Провайдер должен иметь достаточную квоту и подтверждённый домен. Учётные данные почты, DNS, реальная доставка и production PostgreSQL проверяются отдельно от локальных тестов.

Основа проверок безопасности: [OWASP Forgot Password Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).

### Проверки

`node --test tests/password-recovery-client.test.cjs` проверяет код контроллера формы: старые ссылки, ввод кода, удаление секрета из URL и несовпадающие пароли. Это тест с DOM-фикстурой, а не визуальная проверка браузера.

`python -m pytest` запускает backend regression. Новые тесты используют отдельные временные SQLite БД и перехват доставки, без реальных писем. `tests/ui-ux-browser.cjs` проверяет 7 страниц, а `tests/password-recovery-browser.cjs` — восстановление на 1440/390/320 px. Для них нужны установленный Playwright, локальный сервер и `RELYQO_BASE_URL`; при использовании Edge задайте `PLAYWRIGHT_CHANNEL=msedge`. Переменная `RELYQO_SCREENSHOTS` задаёт необязательную папку снимков. API почты в browser-тестах подменён; настоящие транзакции подтверждения/сброса, login/logout и отзыва сессий проверяются Python-тестами.


## Trust, access and operations release (17 September 2026)

- `/admin/control`: private admin-only queue for risk signals, legacy rating reviews, complaints and appeals, business applications, all feedback with reasons/comments, AI conclusions, decisions and operational status. Consumers can complain from a place page, appeal their own excluded rating, and see responses in `/me`. Numeric scores are immutable; a reasoned decision can include/exclude a rating from every aggregate.
- Optional email at consumer/business registration starts email verification. Verified email is accepted as a login alias. All existing roles can bind email in `/account-security`; an unverified address cannot recover an account. Recovery delivery has been checked at the provider; `MailDelivery.ACCEPTED` alone means provider acceptance, not inbox delivery. Delivery is currently a background task; failed attempts are recorded and users can request another verification link.
- RU/UZ selector covers pages, dynamic interface messages, validation errors and emails. The confirmed account language controls subsequent emails; AI requests specify the selected language. User names, comments, complaints and submitted values are not translated. Custom category names remain as entered by the administrator.
- Signals on new submissions: >=8 ratings/object/10 min, >=3 accounts/browser/object/day, >=10 ratings/account/hour, duplicate decoded photo pixels. These are review indicators, never automatic fraud verdicts or numeric score changes. Existing photographs without a digest are not retroactively classified. Signed first-party browser cookies are used; no fingerprint or raw IP is stored for these signals. Correlation events are pruned after 30 days on rating submissions. Closed cases retain the explanation and decision history.
- `/v1/admin/operations` is admin-only. Generic server-error alerts go to previously verified admin addresses (at most once/hour). Whole-site/database outages are monitored independently by `.github/workflows/health.yml` every hour, with time for a Free instance to wake. The owner must enable GitHub Actions failure notifications in GitHub notification settings; schedules can be delayed/disabled by GitHub and are not an uptime SLA. No authentication tokens or client data are sent to this workflow.

### Encrypted backup and restore

In `/admin/control` → «Состояние системы», re-enter the current admin password and choose a separate backup passphrase of at least 16 characters. Download the `.rqbackup` file to storage outside Render and store the passphrase separately. Snapshots include account records, photos and audit history; AES-GCM authenticates/encrypts the archive with a scrypt-derived key. Never commit snapshots, passphrases or database URLs. The portable export supports up to 64 MB of serialized data; use PostgreSQL-native backups for larger databases.

The CLI reads secrets from environment variables, never arguments or logs:

```bash
# DATABASE_URL: source connection. RELYQO_BACKUP_PASSPHRASE: separate secret.
python -m app.scripts.backup export /secure/relyqo.rqbackup
python -m app.scripts.backup verify /secure/relyqo.rqbackup
# RELYQO_RESTORE_DATABASE_URL: a DIFFERENT, EMPTY database, never production.
python -m app.scripts.backup restore /secure/relyqo.rqbackup
```

A verification-only command checks archive authentication; a real restore drill must restore into an isolated database, compare counts and representative records/photos, then run application health and login checks against that isolated database. The command refuses a target with any existing rows. Use the same application revision that produced the backup; perform subsequent migrations after restoration. A restored production clone contains real secrets/customer data and must be kept private, with email/AI disabled during the drill. Do not switch production to it until separately reviewed.

Manual download does **not** enable scheduled durable backups. Render Free PostgreSQL has no native recovery and expires after 30 days. Set `DATABASE_EXPIRES_AT` to the provider's observed expiry for an admin warning, and leave `AUTOMATIC_BACKUP_STATUS=not_configured` until backups are actually enabled. After approving a paid database, enable/verify Render recovery, perform a restore into a separate instance, and only then mark automatic backups enabled. Paid web compute is separately required to remove idle sleeping. Pricing and recurring charges require the owner's approval.

[Render recovery documentation](https://render.com/docs/postgresql-backups) · [Free service limitations](https://render.com/docs/free)


### Loading performance (18 September 2026)

Language scripts no longer block HTML parsing. Public JavaScript, CSS, dictionaries and icons can be reused for five minutes and then revalidated with ETag; private endpoints and page responses retain their existing cache policy. The map page no longer ships the disabled legacy implementation. Own catalog requests run alongside Maps loading and render without waiting for Google; third-party timeouts and search identifiers prevent stalled/old requests from blocking or replacing current results. Admin cases and the reason catalog load concurrently. `Server-Timing: app` reports server processing time separately from transfer latency. Render Free idle spin-up remains a hosting limitation; these changes do not enable paid compute or artificial keep-alive traffic.

## Administrator workflow release (18 September 2026)

- `/admin/analytics`: compares the selected range with the immediately preceding equal-length range; percentage-point differences are distinct from counts. First-time/returning **registered rating authors** are calculated from all eligible history within the selected source and organization/category scope. Repeated authors have at least two eligible ratings within the range. Anonymous feedback is never counted as people. These are not total footfall or a retention rate.
- Admin-only Excel export uses the applied report filters and contains four sheets of aggregates. All names are string cells, so organization names beginning with `=` cannot execute spreadsheet formulas. Neither raw comments nor account identifiers are exported.
- Notifications appear on all three admin pages. They include pending complaints/appeals/review signals and business applications, with per-admin read receipts. Dissatisfaction alerts compare two completed seven-day UTC windows, require at least 10 eligible ratings in each, at least three low current ratings, and an increase of at least 20 percentage points. Verified and Community stay separate. Notifications refresh while an admin page is visible; no email/SMS/push subscription is created. Pending lists are bounded to the newest 100 cases and 100 applications; the underlying control queues remain available.
- `/admin/control#actions`: save an AI-assisted or manually written action with an immutable server-computed baseline from completed days. Track planned/in-progress/completed/cancelled states with reasons and an audit history. Concurrent stale edits receive 409. Completed tasks cannot be reopened: a new experiment needs a new baseline. Measurement starts on the next full UTC day after completion and uses the same planned number of days. Partial windows and small samples must not be treated as causal evidence of improvement.
- All new reports, exports, notification receipts, experiments, histories and setup controls require `RELYQO_ADMIN`. Existing business permissions and numeric scores are unchanged. RU/UZ interface strings include these features.

### Free daily backups on Windows

The operations tab offers a Windows installer bundle and an export-only credential, created after re-entering the current administrator password. The bundle contains no credential. The key is shown once for five minutes, lasts 180 days, and is invalidated by revocation, replacement, role/account disablement or a password change. Only its hash and a password fingerprint are stored on the server. Treat this key as sensitive: it can download an encrypted full database using a caller-supplied passphrase, although it cannot edit data or access any admin endpoint.

The owner runs `SETUP.cmd` once on their Windows 10/11 computer, pastes the key and chooses a separate encryption passphrase. Windows DPAPI protects both values under the current user on that machine; the admin password is never saved. The setup first saves a real archive, then registers a limited-privilege interactive task at 19:00 and user logon. The computer must be on, online and signed in. Missing runs start when available. Files go to Documents/RELYQO-Backups and are never automatically deleted. Keep the passphrase separately and keep a second copy off the computer.

An archive is written to a temporary file, flushed to disk, checked against the server's SHA-256 and format header, then renamed before the client confirms it. The admin page distinguishes awaiting-first-copy, recently-saved (within 36 hours), overdue and disabled states. A receipt is a client assertion of local persistence, **not a restore drill or a native Render backup**. It cannot refresh an old archive's age. Creating a key alone does not enable a schedule. Windows configuration must be completed on the owner's actual computer; installing this release does not do so remotely. This mechanism does not extend the Render database expiry or eliminate free web-service sleep.

Backend tests verify authorization, export, receipt validation, revocation/password rotation, and archive restore into a separate empty database. The Windows CI job checks PowerShell 5.1 parsing, actual DPAPI roundtrips, safe file-save/receipt order using mocked network transport, and actual registration/removal of an isolated Windows scheduled task. Real delivery to the owner's PC is established by the first saved receipt. Do not set `AUTOMATIC_BACKUP_STATUS=enabled` merely because this installer exists; that setting describes provider-side backups.

### Pilot readiness

Use 3–5 consenting organizations and 30–50 invited consumers for an initial pilot. On real phones, verify registration, email confirmation, QR submission, rating/comment/photo, recovery, and complaints in both languages. In the admin panel, verify notifications, an application decision, report filters/export, and one completed improvement task. Start with real pilot activity; synthetic fixtures belong only in isolated tests and must never inflate the public rating. Before accepting irreplaceable data, save a copy and practice a separate restore; resolve the current database expiry before 28 September 2026.
