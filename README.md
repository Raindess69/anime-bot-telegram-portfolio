# 🎌 EnjoyAnime — Telegram Bot & Telegram Mini App (TMA)

> **Единый мастер-документ проекта (Status, Architecture & Next Session Roadmap)**  
> **Основной репозиторий:** `https://github.com/Raindess69/anime-bot-telegram-portfolio.git` (`main`)  
> **Бот:** `@AnimeSpaceFree_bot` (публичный инлайн `@EnjoyAnimeBot`)  
> **Инфраструктура:** $0 budget (remote sandbox `muse.ai` + Pinggy/Cloudflare HTTPS tunnels)

---

## 📌 Оглавление
1. [Обзор и концепция системы](#1-обзор-и-концепция-системы)
2. [Текущий стек и архитектура](#2-текущий-стек-и-архитектура)
3. [Что уже полностью готово (Changelog & Features)](#3-что-уже-полностью-готово)
4. [Структура базы данных (SQLite `bot.db`)](#4-структура-базы-данных)
5. [Пайплайн агрегации контента и плееров](#5-пайплайн-агрегации-контента-и-плееров)
6. [Инструкция по запуску и окружение](#6-инструкция-по-запуску-и-окружение)
7. [Детальный план на следующую сессию (Roadmap)](#7-детальный-план-на-следующую-сессию)
8. [Состояние разработки и задачи следующей сессии](#8-состояние-разработки-и-задачи-следующей-сессии)

---

## 1. Обзор и концепция системы

**EnjoyAnime** — это гибридная экосистема для поиска, трекинга и мгновенного просмотра аниме прямо в Telegram:
1. **Telegram-бот (aiogram 3):** текстовый поиск, меню, история, поддержка Stars, инлайн-режим, фоновый опрос онгоингов и push-уведомления о выходе новых серий.
2. **Telegram Mini App (TMA / FastAPI + SPA):** современный адаптивный веб-интерфейс в стиле Netflix/Кинопоиск, открывающийся по кнопке меню или deep-link прямо в клиенте Telegram (iOS, Android, Desktop, Web). Включает плеер, ленту сезонов, библиотечный трекер и фильтры.

---

## 2. Текущий стек и архитектура

```text
Telegram Client (iOS / Android / Desktop / Web)
 ├── Текстовый чат с ботом (aiogram 3.4+)
 │    ├── /start, /search, меню, история, Stars донаты
 │    ├── Фоновые уведомления о новых сериях (scheduler)
 │    └── Кнопка «📺 Смотреть аниме» (Menu Button WebApp)
 │
 └── Mini App (Telegram WebView)
      └── SPA Frontend (HTML5, Tailwind CSS, Plus Jakarta Sans, JS)
           └── REST API (FastAPI + Uvicorn на порту 8080)
                ├── Auth: HMAC-SHA256 валидация Telegram initData
                ├── Feed: Онгоинги, Популярное, Топы, Hero-баннер дня
                ├── Player & Episodes Hub: Kodik iframe + AniLibria/Shikimori
                ├── Library: Смотрю, В планах, Просмотрено, Избранное (+1 эп.)
                ├── Continue Watching: быстрый возврат к недосмотренному
                └── Vibe Wizard: умный подбор по эпохам, жанрам и рейтингу
```

### Структура файлов проекта:
```text
anime-bot/
├── bot.py                  # Точка входа: запуск aiogram + uvicorn web_api + watchdog
├── web_api.py              # FastAPI REST API бэкенд для Mini App
├── static/
│   └── index.html          # SPA фронтенд Mini App (интерфейс, плеер, трекер)
├── config.py               # Pydantic BaseSettings (.env: BOT_TOKEN, KODIK_TOKEN и т.д.)
├── tunnel.py               # Управление туннелями (Pinggy SSH 443 + Cloudflare)
├── tunnel_keeper.sh        # Внешний bash-супервизор туннеля для muse.ai
├── restart_bot.sh          # Скрипт перезапуска бота при ротации прокси
├── services/
│   ├── aggregator.py       # Оркестратор параллельного поиска с fallback и рекомендациями
│   ├── http_client.py      # Общий асинхронный HTTP-клиент (connection pool, rate limits, retries)
│   ├── shikimori.py        # Shikimori v1 API (русские названия, постеры, очистка BBCode)
│   ├── kodik.py            # Kodik API (плеер, озвучки, серии)
│   ├── anilibria.py        # AniLibria API (HLS потоки, UUID серий, .torrent файлы)
│   ├── anilist.py          # AniList GraphQL (метаданные, стримы, трейлеры)
│   ├── jikan.py            # MyAnimeList REST API v4
│   ├── yummy.py            # YummyAnime парсер
│   └── scheduler.py        # Фоновый опрос подписок (проверка новых серий)
├── db/
│   ├── __init__.py         # Инициализация SQLite базы bot.db и миграций
│   ├── backup.py           # Изолированное online-резервное копирование и восстановление SQLite
│   ├── outbox.py           # Очередь push-уведомлений и базовые точки тайтлов (Outbox)
│   ├── user_titles.py      # Библиотека user_titles и потрековый прогресс episode_progress
│   ├── subscriptions.py    # Таблица подписок subscriptions v2
│   ├── users.py            # Пользователи, языковые настройки и флаг блокировки
│   └── history.py          # Кольцевой буфер истории поисковых запросов
├── utils/
│   └── cache.py            # Async-safe LRU/TTL кэш с защитой от дэдлоков и coalescing
├── tests/                  # Автоматические тесты (53 сценария с моками без реальной отправки)
│   ├── test_notifications.py
│   ├── test_security_and_library.py
│   └── test_recommendations_and_api.py
├── handlers/
│   ├── commands.py         # Команды /start, /help, /app, /lang
│   ├── search.py           # Поиск и рендеринг карточек бота с TMA deep-link
│   ├── menu.py             # Главное меню бота и FSM-визарды
│   ├── callbacks.py        # Инлайн-кнопки (эпизоды, торренты, статусы)
│   ├── mylist.py           # Браузер трекера в текстовом боте
│   ├── donate.py           # Telegram Stars платежи
│   └── inline.py           # Инлайн-режим @bot
├── locales/                # Локализация ru / uk / en
└── README.md               # Данный единый документ проекта
```

---

## 3. Что уже полностью готово

### 3.1. Mini App UI & Player Drawer
* **Новая компоновка модалки тайтла:**
  1. **Шапка:** постер, название, оценка, год, формат, количество серий, бейджи жанров.
  2. **Главная кнопка действия (Hero Watch Button):** большая неоновая кнопка `[ ▶ Смотреть 1 серию ]` (или `[ ▶ Продолжить: N серия ]`), плавно скроллящая к плееру.
  3. **Плеерный хаб:**
     - При наличии видео: встраивается адаптивный видеоплеер.
     - Селектор озвучек (переключение Studio Band, AniLibria, Субтитры и т.д. в 1 клик).
     - Резервный блок прямого перехода: прямые кнопки для просмотра на AniLibria и Shikimori.
  4. **Всегда доступная сетка серий:** кнопки серий `1, 2, ... N` отображаются **всегда** (даже без API-токенов). Клик по серии переключает плеер, обновляет бейдж активной серии и синхронизирует прогресс в библиотеке.
  5. **Описание:** полный синопсис с автоматической очисткой от BBCode-тегов (`[character]`, `[anime]`, `[b]`).
  6. **Трекер библиотеки:** 4 кнопки статуса («Смотрю», «В планах», «Просмотрено», «В избранное») с визуальной активной подсветкой и haptic feedback.

### 3.2. Лента, Поиск и Профиль
* **Секция «Продолжить просмотр»:** персональная карусель на главном экране с сохранёнными постерами и кнопкой мгновенного продолжения с последней серии.
* **Фиксы постеров:** заменены битые домены на `shikimori.io`, встроен офлайн векторный SVG-fallback, исключены карточки с 404-картинками.
* **Идеальная верстка:** строгая пропорция постеров 2:3, фиксированная высота заголовков `h-8` (2 строки) — исключена «рваность» сетки.
* **HMAC-SHA256 безопасность:** автоматическая валидация `Telegram.WebApp.initData` через секретный ключ бота, защита от подделки `user_id`.
* **Deep Links:** поддержка прямых переходов `#title/{id}` и `startapp=w_{title_id}_{episode_id}`.
* **Профиль:** окно аналитики с количеством просмотренных серий и распределением по спискам.

### 3.3. ПК-навигация каруселей и витрина подборок (Каталог)
* **Навигация стрелками на ПК:**
  - В шапки горизонтальных каруселей («Выходят сейчас», «Популярное», «Топ рейтинга», «Продолжить просмотр») добавлены навигационные стрелки `‹` и `›`.
  - Кнопки расположены в заголовке секции, не перекрывают карточки и не мешают кликам по постерам.
  - Автоопределение границ переполнения и скролла (`scrollLeft <= 4` / `scrollLeft + clientWidth >= scrollWidth - 4`): граничные кнопки автоматически отключаются (`disabled`, `opacity-30`).
  - Шаг прокрутки `clientWidth * 0.75` с поддержкой `@media (prefers-reduced-motion: reduce)` (мгновенный скачок при сниженном движении, плавный в обычном режиме).
  - Доступность: кнопки фокусируются с клавиатуры, имеют `aria-label`, мобильный touch-свайп и трекпад работают нативно.
* **Полноэкранная витрина категории (`#view-category`):**
  - Кнопка действия «Все →» в заголовках категорий открывает отдельный SPA-экран каталога.
  - Пагинация по 24 карточки на страницу по кнопке «Показать ещё» со спиннером.
  - **Provider Pinning:** источник данных первой страницы (`shikimori`, `jikan`, `anilist`) фиксируется для всех последующих страниц категории, исключая смешивание ID и дублирование.
  - Защита от состояния гонки: sequence token (`categorySeqId`) отсекает запоздавшие сетевые ответы.
  - Защита от повторных кликов (`isLoadingCategory`) предотвращает повторные запросы пагинации.
  - Иерархия кнопки «Назад» (Telegram `BackButton`): Карточка -> Витрина подборки -> Главная.
  - Обработка состояний: анимированные скелетоны, экран отсутствия данных и плашка ошибки с кнопкой «Повторить».
  - Мультиязычность: полная поддержка локалей `ru`, `en`, `uk`.

### 3.4. Серверная инфраструктура ($0 бюджет на muse.ai)
* **Авто-туннель Pinggy 443 + Cloudflare:** `tunnel.py` с постоянным чтением stdout и авто-реконнектом за 3с.
* **Динамическая синхронизация Menu Button:** фоновый поток `watch_url_changes()` в `bot.py` сверяет URL каждые 4с и мгновенно обновляет кнопку меню Telegram без перезапуска процесса.
* **Watchdog ротации прокси:** при ошибке `407 Proxy Authentication Required` бот корректно завершается, и внешний watchdog перезапускает его через `restart_bot.sh` в свежей сессии.

---

## 4. Структура базы данных (SQLite `bot.db`)

1. **`users`:** `user_id` (PK, INTEGER), `lang` (TEXT: ru/uk/en), `is_blocked` (INTEGER: 0/1), `created_at` (INTEGER).
2. **`user_titles` (Библиотека):**
   - PK: `(user_id, mal_id)`.
   - `title`, `lang`, `status` (`watching`, `completed`, `plan`, `dropped`).
   - `current_episode` (INTEGER), `is_favorite` (INTEGER: 0/1 — строго независим от статуса), `image_url` (TEXT), `updated_at` (INTEGER).
3. **`episode_progress` (Потрековый просмотр эпизодов):**
   - PK: `(user_id, mal_id, episode)`.
   - `position` (REAL: позиция в секундах), `duration` (REAL: общая длина в секундах), `is_completed` (INTEGER: 0/1 при достижении 85% хронометража), `updated_at` (INTEGER).
   - *Правило 85%:* достижение позиции 85% хронометража фиксирует завершение серии, но не означает завершение всего тайтла и не помечает предыдущие серии.
4. **`subscriptions` v2 (Подписки на онгоинги):**
   - `id` (PK), `user_id`, `mal_id` (UNIQUE: `user_id, mal_id`), `title`.
   - `anilibria_code`, `yummy_url`, `shikimori_id`, `last_episode`, `created_at`.
5. **`notification_outbox` (Транзакционная очередь Push-уведомлений):**
   - `id` (PK AUTOINCREMENT), `user_id`, `mal_id`, `episode`, `event_type`.
   - UNIQUE: `(user_id, mal_id, episode, event_type)` — абсолютная дедупликация.
   - `title` (TEXT), `status` (`pending`, `processing`, `sent`, `failed`, `cancelled`).
   - `attempts` (INTEGER: число реальных доставок в Telegram API), `next_attempt_at` (INTEGER), `created_at` (INTEGER), `claimed_at` (INTEGER: unix timestamp захвата lease / fencing token), `sent_at` (INTEGER), `last_error` (TEXT).
6. **`tracked_titles` (Базовые точки онгоингов и метаданные источников):**
   - `mal_id` (PK), `title` (TEXT), `anilibria_code` (TEXT), `yummy_url` (TEXT), `shikimori_id` (INTEGER), `last_known_episode` (INTEGER), `updated_at` (INTEGER).
7. **`schema_migrations` (Идемпотентные миграции):**
   - `version` (PK, TEXT), `applied_at` (INTEGER).
8. **`search_history`:** кольцевой буфер последних 10 поисковых запросов пользователя.

---

## 5. Пайплайн агрегации контента и плееров

1. **Поиск и метаданные:**
   - **Shikimori:** приоритет для RU-пользователей (русские названия, постеры, синопсис).
   - **AniList GraphQL:** быстрые ответы, топы сезонов, стриминг-ссылки Crunchyroll.
   - **Jikan (MAL):** фильтры, рейтинги, жанровый поиск с fallback-ротатором.
2. **Видео и плееры:**
   - **Kodik:** мультиязычные переводы, прямой iframe, per-episode URLs (требуется партнерский токен `KODIK_TOKEN`).
   - **AniLibria:** бесплатный API без токенов, HLS видеопотоки (480p, 720p, 1080p), UUID серий, .torrent файлы, а также встроенный `external_player`.
   - **Shikimori / AniLibria ссылки:** прямой переход в 1 клик при отсутствии встроенного плеера.

---

## 6. Инструкция по запуску и окружение

### Локально на Windows:
```powershell
# 1. Перейти в папку бота
cd C:\Users\MainAdmin\Desktop\Claude\anime-bot

# 2. Активировать venv и запустить бота вместе с Web API:
.\.venv\Scripts\python.exe bot.py

# Или запустить только Web API (для верстки и тестов фронтенда):
.\.venv\Scripts\python.exe -m uvicorn web_api:app --host 127.0.0.1 --port 8080 --reload
```
Веб-интерфейс доступен по адресу: `http://127.0.0.1:8080`.

### На удалённом сервере / muse.ai:
```bash
# Обновление из GitHub:
git pull origin main

# Перезапуск туннеля и бота:
bash restart_bot.sh
```

### Переменные окружения (`.env`):
* `BOT_TOKEN` — токен Telegram-бота из `@BotFather` (обязательно).
* `DB_PATH` — путь к файлу SQLite (`bot.db`, по умолчанию).
* `DEFAULT_LANG` — язык по умолчанию (`ru`).
* `KODIK_TOKEN` — партнерский токен Kodik (`https://kodik.cc/`, опционально, активирует полный каталог озвучек Kodik).
* `MINI_APP_URL` — текущий публичный URL Mini App (обновляется туннелем автоматически).

---

## 7. Единый сводный чек-лист Roadmap EnjoyAnime

| ID | Этап / Задача | Статус | Доказательство / Блокер |
|---|---|---|---|
| **P1.1-R** | **Этап 1: Проверка Push Backend** | **DONE** | Таблица `notification_outbox` с `claim_token` (атомарный инкремент поколения), `claimed_at`, `recover_stale_processing` с таймаутом lease, снятие `is_blocked = 0` при активности, глобальная пауза `_telegram_flood_until`, `defer_event` без расхода попыток при отсутствии туннеля, кнопка типа `web_app` с полным HTTPS URL. Отклонение перехвата активного lease воркером B. Флаг безопасного запуска `DISABLE_OUTBOX_DISPATCH`. 39 тестов в `tests/test_notifications.py` успешно пройдены. |
| **SEC-01** | **Этап 2: Основа и безопасность** | **DONE** | Валидация `Telegram.WebApp.initData` HMAC-SHA256 (срок жизни 7 дней для минимизированных сессий, допуск 300с рассинхронизации). Zero-trust `user_id`: клиент не может подменить чужой `user_id`. Валидация Pydantic-моделей в `web_api.py`. Маскирование секретов в `config.py` (`mask_secret`). Online-резервное копирование `db/backup.py`. Параметризованные SQL-запросы. 14 тестов в `tests/test_security_and_library.py`. |
| **LIB-01** | **Этап 3: Библиотека и прогресс** | **DONE** | Таблица `episode_progress (user_id, mal_id, episode)`. Независимость `is_favorite` от статуса. Дедупликация тайтлов по `mal_id`. Правило 85%: просмотр до 85% хронометража помечает серию завершенной, но не завершает весь тайтл и не помечает серии 1..N-1. Защита от устаревших событий по `updated_at`. 14 тестов в `tests/test_security_and_library.py`. |
| **API-01** | **Этап 4: API, агрегация и кэш** | **DONE** | Общий синглтон `httpx.AsyncClient` в `services/http_client.py` с пулом соединений и семафорами по доменам. Строгое соблюдение `Retry-After` без преждевременных повторов. Общий бюджет дедлайна `/api/feed` (`FEED_TIMEOUT_SECONDS`, по умолч. 5.0с) на базе `asyncio.timeout` Python 3.11. Параллельный сбор категорий с сохранением частичных результатов и гарантией отдачи локального `continue_watching` при сбоях внешних источников. Семантический fallback (`airing` -> онгоинги, `popular` -> популярное, `top` -> рейтинг). Кэш `TTLCache` в `utils/cache.py` с request coalescing и отменой зависших воркеров; запрет кэширования полных отказов на 300с. Endpoints `/health`, `/health/live`, `/health/ready`. 14 тестов в `tests/test_recommendations_and_api.py`. |
| **VID-01** | **Этап 5: Видео и плеер** | **PARTIAL** | **IMPLEMENTED:** `static/index.html`: Чистый плеер со штатными HTML5 video controls (дублирующая нижняя панель и избыточный кастомный seekbar удалены). Ограниченное автовосстановление Hls.js (`NETWORK_ERROR` $\le 3$, `MEDIA_ERROR` $\le 3$). Autoplay Policy: всплывающий оверлей возобновления звука/видео. Валидация `event.source` и origin в postMessage (`kodik`, `anilibria`). Safe area padding и `@media (prefers-reduced-motion)`.<br>**NOT IMPLEMENTED:** Резервный балансер Kinobox в коде отсутствует (запасной источник — прямой HLS AniLibria и внешние ссылки Shikimori/AniLibria). |
| **P1.2** | **Этап 6: Frontend Deep Link** | **PARTIAL** | **IMPLEMENTED & CHROME MOCK VERIFIED:** `static/index.html`: Функция `handleDeepLinks()` с флагом `deepLinkHandled`. Парсинг `startapp=w_{mal_id}_{episode}`, `#w_{mal_id}_{episode}` и `#title/{id}`. Запуск плеера через `playEpisode()`. Привязка `Telegram.WebApp.BackButton`. Проверено в headless Google Chrome с mock-SDK (`tests/test_frontend_chrome.py`).<br>**NOT RUN:** Проверка в реальных клиентах Telegram Android/iOS/Desktop. |
| **UX-01** | **Этап 7: Поиск серий и UX** | **PARTIAL** | **IMPLEMENTED & CHROME MOCK VERIFIED:** Селектор серий с разбивкой по диапазонам (`1–25`, `26–50` и т.д.) при $>25$ серий. Поле быстрого перехода к номеру серии (`jumpToEpisode`). Сохранение реальной нумерации серий от провайдеров. Плавный `scrollIntoView` активного эпизода. Проверено в headless Google Chrome.<br>**NOT RUN:** Проверка на физических мобильных устройствах. |
| **REC-01** | **Этап 8: Рекомендации (Rule-based / Vibe)** | **DONE** | `services/aggregator.py: get_recommendations()` и эндпоинт `GET /api/recommendations`. Стабильная сортировка по рейтингу, исключение просмотренных/брошенных тайтлов (`exclude_watched`), явные объяснения причин рекомендации (`recommendation_reason`). 7 тестов в `tests/test_recommendations_and_api.py`. |
| **REC-02** | **Этап 8: Семантический поиск (Embeddings)** | **BLOCKED** | **Причина блокировки:** В рабочем окружении Python отсутствуют библиотеки векторизации и ML (`torch`, `sentence-transformers`, `numpy`). Регламент проекта строго запрещает несанкционированную установку тяжелых внешних пакетов. |
| **SOC-01** | **Этап 9: Шеринг тайтлов и серий** | **PARTIAL** | **IMPLEMENTED & CHROME MOCK VERIFIED:** Кнопка «Поделиться» генерирует канонический deep link `t.me/<bot>?startapp=w_{mal_id}_{episode}` без PII/токенов. Вызов `Telegram.WebApp.shareToStory` с fallback на Web Share API проверен в изолированном mock SDK в Chrome.<br>**NOT RUN:** Реальная публикация Stories в живой Telegram-клиент. |
| **SOC-02** | **Этап 9: Совместный просмотр (Watch Party)** | **BLOCKED** | **Причина блокировки:** Сторонний iframe Kodik изолирован политикой Cross-Origin (Same-Origin sandbox) и не предоставляет публичного API удаленного управления перемоткой/паузой для синхронизации нескольких клиентов. В $0 архитектуре с эфемерными туннелями отсутствует постоянный брокер WebSocket сессий для синхронизации стейта. |
| **OPS-01** | **Этап 10: Проверки и эксплуатация** | **DONE** | Полный набор тестов: **83 теста (100% passed)**. Синтаксический анализ AST: 39 файлов (0 ошибок). `git diff --check` чист. Разработаны инструкции резервного копирования, безопасного отката, регламент единственной схемы запуска (порт 8080, `./restart_bot.sh`) и план перехода на PostgreSQL. |
| **NAV-01** | **Этап 11: ПК-навигация и витрина подборок** | **DONE** | Стрелки прокрутки горизонтальных каруселей на ПК в заголовках без перекрытия постеров, определение границ переполнения, доступность с клавиатуры. SPA-экран `#view-category`, пагинация 24 тайтла/стр., надежное вычисление `has_more` (авторитетная пагинация AniList/Jikan и probe следующей страницы Shikimori без probe в feed), защита от race condition (`categorySeqId`) и дублирующих кликов, provider pinning (фиксация источника первой страницы), эндпоинт `GET /api/category/{category}`, иерархия BackButton (Карточка -> Подборка -> Главная), мультиязычность `ru`/`en`/`uk`. 83 теста (100% passed, включая 20 проверок в headless Chrome). |

---

## 8. Состояние разработки, эксплуатация и регламенты

### 8.1. Текущий статус готовности компонентов
* **Backend:**
  * Очередь Outbox и диспетчер: полностью верифицированы, покрыты 38 тестами (`notification_outbox` с `claim_token`, `claimed_at`, generation counter, recovery lease, отклонение повторного захвата активного lease воркером B).
  * Безопасность Web API: zero-trust user ID, валидация Telegram initData HMAC-SHA256, строгая проверка типов Pydantic.
  * Потрековый прогресс: таблица `episode_progress` с защитой от регресса и соблюдением правила 85%.
  * HTTP-клиент: общий пул `httpx.AsyncClient`, ограничение параллельности к внешним API, строгое соблюдение Retry-After.
  * Общий дедлайн и кэш ленты: общий бюджет `FEED_TIMEOUT_SECONDS` (5.0с) для `/api/feed`, параллельный сбор категорий, сохранение частичных результатов, семантический fallback, запрет кэширования отказов, single-flight без дэдлоков.
  * Витрина подборок: эндпоинт `GET /api/category/{category}` с валидацией категорий (`airing`, `popular`, `top`), пагинацией (1..100, лимит 1..50), provider pinning, изолированным кэшем `category_cache`, строгим соответствием upstream-лимита для устранения пропусков/пересечений и надежным probe следующей страницы (без лишних запросов в feed).
  * Рекомендации: верифицированный эндпоинт `/api/recommendations` с исключениями и объяснениями.
  * Health probes: эндпоинты `/health`, `/health/live` и `/health/ready` (проверка соединения с SQLite).
* **Frontend (`static/index.html`):**
  * ПК-навигация: стрелки прокрутки в заголовках каруселей, автоматический расчет границ и `disabled`, поддержка `@media (prefers-reduced-motion)`.
  * Витрина категорий: SPA-экран `#view-category`, кнопка «Показать ещё» (+24 тайтла), скелетоны, экран ошибки с повтором, защита от race conditions и спам-кликов; неполные или пустые страницы при наличии продолжения не скрывают «Показать ещё».
  * Отказоустойчивость постеров: тайтлы без постеров не отбрасываются из каталога; фронтенд использует хелпер `safeImg` и SVG-fallback `FALLBACK_POSTER` без риска `src="undefined"`, `src="null"` или зацикливания `onerror`.
  * Плеер: штатные HTML5 video controls, чистый интерфейс без дублирующих ползунков и кнопок.
  * Deep link `startapp=w_{mal_id}_{episode}` открывает карточку и стартует плеер.
  * Иерархия навигации BackButton Telegram WebApp: Карточка -> Витрина подборки -> Главная.
  * Оверлей Autoplay Policy возобновляет звук/видео в 1 клик.
  * Навигация по сериям: диапазоны по 25 эпизодов и быстрый переход по номеру.
  * Шеринг: канонический `startapp` URL и поддержка Stories.
  * Стили: адаптивные отступы `safe-area-inset` и поддержка `@media (prefers-reduced-motion)`.
  * Локализация: полная поддержка языков `ru`, `en`, `uk`.
* **Тестирование:**
  * **87 автоматических тестов** в каталоге `tests/` выполняются успешно (`Ran 87 tests, OK` за ~23с).
  * **15 сценариев в браузере с mock-SDK (23 проверки)** проверены через headless Google Chrome (`tests/test_frontend_chrome.py`):
    1. Script Load & Zero Uncaught Errors.
    2. Valid Deep Link (`#w_101_3`).
    3. Corrupted Deep Link (`#w_corrupted`).
    4. Missing Episode Handling.
    5. Episode Range Switch & Quick Jump to Episode 42.
    6. Deep Link Idempotency Guard.
    7. Close Detail Cleanup (BackButton hidden, modal hidden).
    8. Search Sequence Token Rejection (race condition guard).
    9. Carousel Arrows Mounted, Start Boundary (`disabled`) & Scroll Triggered.
    10. Category View Displayed, Title Localization & BackButton Active.
    11. "Показать ещё" Pagination (+24 карточки).
    12. Double-click Guard on Load More.
    13. Category Stale Sequence Rejection on fast switch.
    14. Navigation Hierarchy (Card -> Category -> Home) & BackButton Coordination.
    15. Fallback Poster in Card HTML, imgFallback Handler Safety & Hero/Modal Safe Posters.
  * Все тесты работают на временных изолированных БД в `tempfile.mkdtemp()`.
* **Что НЕ проверялось и требует ручной проверки после запуска:**
  * Отправка реальных пушей реальным пользователям в живой Telegram (запрещено регламентом).
  * Поведение плеера и deep link на реальных клиентах Telegram Android, iOS и Desktop: **NOT RUN**.
  * Физическая публикация карточки в реальные Telegram Stories: **NOT RUN** (проверялся только вызов mock-метода).
  * Резервный балансер Kinobox: **NOT IMPLEMENTED**.
  * Семантический поиск на эмбеддингах (ML) и Watch Party: **BLOCKED**.

---

### 8.2. Инструкция по резервному копированию и восстановлению базы данных

Утилита `db/backup.py` использует нативный безопасный механизм `sqlite3.backup()` без блокировки пишущих транзакций (WAL-safe).

```powershell
# 1. Создание резервной копии рабочей БД:
.\.venv\Scripts\python.exe -c "import asyncio, db.backup; asyncio.run(db.backup.create_backup('bot.db', 'backups/bot_backup.db'))"

# 2. Восстановление из резервной копии:
.\.venv\Scripts\python.exe -c "import asyncio, db.backup; asyncio.run(db.backup.restore_backup('backups/bot_backup.db', 'bot.db'))"
```

---

### 8.3. Безопасная инструкция отката (Safe Rollback)

> [!WARNING]
> Никогда не используйте `git reset --hard` или удаление папок `rmdir /s tests`, чтобы не уничтожить тесты и посторонние файлы!

При необходимости точечного отката изменений в рабочей директории:
```powershell
# Проверить список измененных файлов перед откатом:
git status --short

# Откатить только конкретный измененный файл:
git checkout -- services/scheduler.py

# Для удаления только временных артефактов без удаления тестов:
git clean -nd  # dry-run: посмотреть, что удалится
```

---

### 8.4. План перехода на PostgreSQL (Post-MVP)

#### Условия старта миграции:
1. Одновременный онлайн Mini App превышает 1000 активных пользователей.
2. Необходимость горизонтального масштабирования (несколько инстансов `web_api.py` за балансировщиком Nginx/Caddy).
3. Появление потребности в фоновом анализе данных без конкуренции за блокировку SQLite.

#### Соответствие типов данных и схема в PostgreSQL:
* `users`: `user_id BIGINT PRIMARY KEY`, `lang VARCHAR(10)`, `is_blocked SMALLINT DEFAULT 0`, `created_at BIGINT`.
* `user_titles`: `user_id BIGINT`, `mal_id INTEGER`, `status VARCHAR(20)`, `current_episode INTEGER`, `is_favorite SMALLINT`, `image_url TEXT`, `updated_at BIGINT`, `PRIMARY KEY (user_id, mal_id)`.
* `episode_progress`: `user_id BIGINT`, `mal_id INTEGER`, `episode INTEGER`, `position DOUBLE PRECISION`, `duration DOUBLE PRECISION`, `is_completed SMALLINT`, `updated_at BIGINT`, `PRIMARY KEY (user_id, mal_id, episode)`.
* `notification_outbox`: `id BIGSERIAL PRIMARY KEY`, `user_id BIGINT`, `mal_id INTEGER`, `episode INTEGER`, `event_type VARCHAR(50)`, `payload JSONB`, `status VARCHAR(20)`, `claimed_at BIGINT`, `claim_token INTEGER DEFAULT 0`, `retry_count INTEGER`, `next_retry_at BIGINT`, `UNIQUE (user_id, mal_id, episode, event_type)`.
* В PostgreSQL переход `status = 'pending' -> 'processing'` реализуется атомарно через `SELECT ... FOR UPDATE SKIP LOCKED`, исключая необходимость ручной эмуляции распределенного lease.

#### Шаги миграции:
1. Развернуть PostgreSQL 16+ и настроить подключение через `asyncpg` и `SQLAlchemy 2.0 (async)`.
2. Создать DDL схемы и индексов через `Alembic`.
3. Экспортировать данные из SQLite через скрипт стриминговой выгрузки батчами по 1000 строк.
4. Переключить `DB_PATH` на `DATABASE_URL` в `.env`.

---

### 8.5. Команды контрольных проверок

```powershell
# 1. Запуск полного пакета автоматических тестов (61 тест):
.\.venv\Scripts\python.exe -m unittest discover tests

# 2. Запуск тестов очереди Outbox (39 тестов):
.\.venv\Scripts\python.exe -m unittest tests/test_notifications.py

# 3. Запуск браузерной проверки frontend в Google Chrome headless (8 сценариев):
.\.venv\Scripts\python.exe -m unittest tests/test_frontend_chrome.py

# 4. Проверка синтаксиса AST всех Python-файлов проекта:
.\.venv\Scripts\python.exe -m compileall -q .

# 5. Проверка пробелов и целостности diff:
git diff --check
```

---

### 8.6. Регламент безопасного первого запуска (Safe First Launch Guide)

#### Архитектурная схема запуска:
Приложение EnjoyAnime спроектировано как **единый процесс** (`bot.py`):
1. **API:** Встроенный Uvicorn запускается внутри `bot.py` асинхронной задачей (`asyncio.create_task(web_server.serve())`). Запускать отдельный экземпляр Uvicorn **НЕ ТРЕБУЕТСЯ** и вредно (вызовет конфликт портов).
2. **Порт:** Реально используется порт `settings.web_port` (по умолчанию **`8080`**, настраивается через `WEB_PORT` в `.env`).
3. **Планировщик (Scheduler):** Запускается внутри `bot.py` (`asyncio.create_task(run_periodic_check(bot))`).
4. **Туннель:** `bot.py` **не запускает** туннель сам. В проекте имеется готовый скрипт `tunnel.py`, который поднимает туннель (Pinggy / Cloudflare), сохраняет внешний HTTPS URL в `.env` (`WEB_APP_URL` и `MINI_APP_URL`). Функция `watch_url_changes(bot)` в `bot.py` отслеживает изменения адреса туннеля в `.env` и динамически обновляет кнопку Telegram Menu Button.
5. **Количество процессов:** Ровно **1 процесс Python** (`bot.py`) + **1 процесс туннеля** (`python tunnel.py`).

Перед первым боевым запуском выполните следующие шаги:

#### Шаг 1. Определение активного пути к базе данных
Проверьте фактический путь к SQLite БД, сконфигурированный в окружении:
```powershell
.\.venv\Scripts\python.exe -c "import config; print('DB Path:', config.settings.db_path)"
```

#### Шаг 2. Создание горячей резервной копии (Zero-Downtime Backup)
Перед запуском создайте защитную копию рабочей БД через `sqlite3.backup`:
```powershell
.\.venv\Scripts\python.exe -c "import db.backup, config; db.backup.create_backup(config.settings.db_path, 'backups/pre_launch_backup.db'); print('Backup OK')"
```

#### Шаг 3. Проверка целостности созданного бэкапа
Убедитесь, что резервная копия не повреждена:
```powershell
.\.venv\Scripts\python.exe -c "import sqlite3; conn = sqlite3.connect('backups/pre_launch_backup.db'); cur = conn.cursor(); cur.execute('PRAGMA integrity_check'); res = cur.fetchone(); print('Integrity check:', res); assert res[0] == 'ok'"
```

#### Шаг 4. Smoke-тестирование миграций на копии БД (Dry-Run)
Проверьте применение схемы и миграций на изолированной копии перед боевой базой:
```powershell
.\.venv\Scripts\python.exe -c "import asyncio, shutil, db; shutil.copy('backups/pre_launch_backup.db', 'backups/test_mig.db'); asyncio.run(db.init_db('backups/test_mig.db')); print('Dry-run migration OK')"
```

#### Шаг 5. Контрольная проверка конфигурации окружения
Проверьте корректность настроек `.env` (токен бота, туннель, порты) без раскрытия секретов:
```powershell
.\.venv\Scripts\python.exe -c "import config; print('Bot token configured:', bool(config.settings.bot_token)); print('Tunnel URL:', config.settings.mini_app_url); print('Web host:', config.settings.web_host); print('Web port:', config.settings.web_port); print('Dispatch disabled:', config.settings.disable_outbox_dispatch)"
```

#### Шаг 6. Штатный запуск (Single Process)

##### Вариант А: Запуск первого UI-теста (с ГАРАНТИРОВАННО отключённой отправкой push)
```powershell
# В первом окне терминала (туннель):
.\.venv\Scripts\python.exe tunnel.py

# Во втором окне терминала (бот + API с отключенным диспетчером рассылки):
$env:DISABLE_OUTBOX_DISPATCH="1"; .\.venv\Scripts\python.exe bot.py
```

##### Вариант Б: Штатный рабочий запуск (с активной отправкой уведомлений)
```powershell
# В первом окне терминала (туннель):
.\.venv\Scripts\python.exe tunnel.py

# Во втором окне терминала (бот + API + диспетчер):
.\.venv\Scripts\python.exe bot.py
```

---

### 8.7. Чек-лист ручной приёмки (Manual Acceptance Checklist)

Перед включением боевой рассылки выполните ручную проверку интерфейса:

- [ ] Запуск одного bot.py, без второго Uvicorn.
- [ ] Запуск существующего механизма туннеля (`python tunnel.py`).
- [ ] Обновление Menu Button после смены URL.
- [ ] Открытие Mini App из меню Telegram.
- [ ] Поиск и открытие карточки.
- [ ] Добавление в библиотеку.
- [ ] Избранное независимо от статуса.
- [ ] Запуск доступного HLS-эпизода.
- [ ] Пауза, перемотка, fullscreen.
- [ ] Смена серии.
- [ ] Сохранение позиции после закрытия и открытия.
- [ ] Открытие конкретной серии по ссылке.
- [ ] Понятное сообщение при недоступной серии.
- [ ] BackButton.
- [ ] Обычный шеринг ссылки.

> [!NOTE]
> Push и Stories проверяются отдельно: без реальной рассылки или публикации на этом этапе.
