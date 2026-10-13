# 🚀 EnjoyAnime — Полная архитектурная инструкция и Roadmap перехода на Telegram Mini App (TMA)

> **Статус документа:** Главное руководство по проектированию и разработке (Engineering Blueprint).  
> **Архитектурный паттерн:** Модульный монолит (Modular Monolith) на Python (FastAPI + aiogram 3 + background worker) с клиентом на Vite + React + TypeScript, базой PostgreSQL и адаптерной архитектурой плееров.

---

## 0. Чеклист предпроектного аудита (Фаза 0)

### 0.1. Идентичность бота и HMAC-проверка
* **Основной runtime бот:** `@AnimeSpaceFree_bot` (ID: `8648632519`).
* **Инлайн/публичное имя:** `@EnjoyAnimeBot`.
> ⚠️ **Критическое правило:** Валидация Telegram `initData` по HMAC-SHA256 **привязана к токену конкретного бота**, через которого открыт WebApp. `initData` от `@AnimeSpaceFree_bot` невозможно проверить токеном `@EnjoyAnimeBot` и наоборот. Всегда использовать `BOT_TOKEN` того бота, у которого настроен WebApp / Menu Button.

### 0.2. Проверка схемы и данных SQLite (`bot.db`)
В текущей схеме SQLite выявляются следующие потенциальные конфликты:
* `subscriptions`: необходимо убедиться, что ограничение уникальности стоит на `UNIQUE(user_id, title_id)`, а не глобально на `mal_id` (иначе на тайтл сможет подписаться только один человек во всём боте).
* `user_titles`: композитный ключ `PRIMARY KEY (user_id, title_id)`.
* Аудит фактических типов, индексов и целостности связей перед миграцией в PostgreSQL.

### 0.3. Проверка воспроизведения на реальных Telegram-клиентах
* Проверить работу HLS (AniLibria / AniLiberty API V1) и iframe (Kodik) на платформах:
  * **Telegram Android** (Android WebView, аппаратно-зависимый fullscreen).
  * **Telegram iOS** (WKWebView, native Safari HLS engine, inline playback).
  * **Telegram Desktop** (Chromium/Qt webview).
* Зафиксировать технические возможности источников:
  1. Разрешено ли встраивание по CORS / Origin?
  2. Доступны ли события: `ready`, `timeupdate`/`progress`, `durationchange`, `ended`?
  3. Работает ли программная перемотка (`seek(seconds)`)?
  4. Время жизни URL медиасегментов и плееров.

---

## 1. Архитектура новой системы

### 1.1. Общая топология
```text
Telegram Client
 ├── Чат с ботом (aiogram)
 │    ├── /start, меню, помощь
 │    ├── Уведомления о новых сериях
 │    └── Кнопка «Открыть EnjoyAnime» (Menu Button / WebApp)
 │
 └── Mini App (Telegram WebView)
      └── React SPA (Vite + TS)
           └── HTTPS REST API (/api/v1)
                └── FastAPI
                     ├── AuthService (HMAC WebAppData -> Session)
                     ├── CatalogService (Meta, Search, Vibe)
                     ├── LibraryService (Tracking, Favorites)
                     ├── PlaybackService (Sessions, Heartbeat, Telemetry)
                     └── SubscriptionService (Notifications)

aiogram Bot Process ─────┐
FastAPI Backend ────────┼── Общие Domain & Application Services
Background Worker ──────┘
                             ├── PostgreSQL (Основное хранилище)
                             ├── Провайдеры (Shikimori, AniList, Kodik, AniLibria)
                             └── Кэш / Notification Outbox
```

> **Маршрутизация видео:** Трафик видеопотоков идёт напрямую: `Telegram WebView → Видеосервер источника (CDN)`. Бэкенд EnjoyAnime отдаёт только манифесты, токены и дескрипторы воспроизведения, не проксируя терабайты видео через себя.

### 1.2. Процессы и окружение (Docker Compose)
Для разработки и production используется единый образ с разными entrypoint:

| Контейнер / Сервис | Команда запуска | Назначение |
|---|---|---|
| `api` | `python -m app.entrypoints.api` | FastAPI REST API (Uvicorn / Gunicorn) |
| `bot` | `python -m app.entrypoints.bot` | aiogram 3 Long Polling / Webhook |
| `worker` | `python -m app.entrypoints.worker` | Scheduler, опрос онгоингов, outbox fanout |
| `postgres` | — | PostgreSQL 16+ |
| `reverse-proxy`| Nginx / Caddy | SSL termination, статика фронтенда, CSP заголовки |

> ⚠️ **Правило:** Планировщик (`scheduler`) **не запускается** внутри воркеров FastAPI во избежание дублирования фоновых проверок при масштабировании API.

### 1.3. Структура кодовой базы
```text
enjoyanime/
├── backend/
│   ├── app/
│   │   ├── entrypoints/
│   │   │   ├── api.py           # Запуск FastAPI
│   │   │   ├── bot.py           # Запуск aiogram бота
│   │   │   └── worker.py        # Запуск фонового шедулера/воркера
│   │   ├── api/
│   │   │   ├── dependencies/    # Auth, DB session, rate limits
│   │   │   └── routes/          # auth, catalog, library, playback, subs
│   │   ├── bot/
│   │   │   ├── handlers/        # Команды и меню бота
│   │   │   └── keyboards/       # Reply / Inline / MenuButton
│   │   ├── application/         # Бизнес-логика (Application Services)
│   │   │   ├── catalog.py
│   │   │   ├── library.py
│   │   │   ├── playback.py
│   │   │   └── subscriptions.py
│   │   ├── domain/              # Доменные модели и интерфейсы
│   │   ├── infrastructure/      # Реализация адаптеров и репозиториев
│   │   │   ├── db/              # SQLAlchemy модели, сессии, репозитории
│   │   │   ├── providers/       # shikimori, anilibria, kodik, anilist, jikan
│   │   │   └── cache/           # Redis / In-memory кэш
│   │   └── config.py
│   ├── migrations/              # Alembic
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── app/                 # Router, провайдеры, Telegram SDK bridge
│   │   ├── pages/               # Home, Search, Title, Watch, Library, Profile
│   │   ├── features/            # Playback, Auth, Filters, Library-Actions
│   │   ├── entities/            # Title, Episode, ReleaseVariant
│   │   └── shared/              # API clients, UI primitives, i18n
│   ├── package.json
│   └── vite.config.ts
└── compose.yaml
```

### 1.4. Рефакторинг агрегатора и Канонический Title ID
* Файл `aggregator.py` разделяется на независимые провайдеры с изолированными таймаутами, retry-политиками и circuit-breaker.
* **Собственный первичный ключ:** Отказ от `mal_id` как глобального PK.
  * Внутренний ID: `titles.id` (UUID или BigInt).
  * Связка внешних баз: таблица `title_external_ids` с полями `(title_id, provider, external_id, mapping_status)`.
  * Уникальность: `UNIQUE (provider, external_id)`.

---

## 2. Аутентификация через Telegram initData

### 2.1. Поток авторизации
1. Пользователь открывает Mini App.
2. Фронтенд считывает `Telegram.WebApp.initData` (сырая строка).
3. Отправляет POST `/api/v1/auth/telegram` с телом `{ "init_data": "<raw_string>" }`.
4. Бэкенд валидирует HMAC-подпись с секретом `HMAC_SHA256("WebAppData", BOT_TOKEN)`.
5. Проверяет срок годности `auth_date` (не старше 600 секунд) и валидность `user.id`.
6. Создаёт серверную сессию с безопасной cookie (`HttpOnly`, `Secure`, `SameSite=None` или `Lax`) либо opaque session token.
7. Все дальнейшие API-запросы авторизуются по этой сессии.

### 2.2. Защитный чеклист Auth
* Никогда не доверять `initDataUnsafe`.
* Не логировать сырой `initData` в открытом виде (содержит чувствительные данные).
* Возвращать клиенту обезличенный HTTP `401 Unauthorized`.
* Защита от CSRF и проверка `Origin`.

---

## 3. База данных и схема (PostgreSQL + SQLAlchemy 2.0 async)

### 3.1. Ключевые таблицы реляционной схемы

| Таблица | Назначение | Ключевые поля |
|---|---|---|
| `users` | Пользователи Telegram | `telegram_user_id BIGINT PK`, `lang`, `created_at` |
| `titles` | Канонический тайтл | `id BIGSERIAL PK`, `format`, `status`, `total_episodes`, `poster_url` |
| `title_localizations` | Названия и синопсисы | `title_id`, `lang`, `title`, `description` |
| `title_external_ids` | Маппинг баз (MAL, Shiki, AniList) | `title_id`, `provider`, `external_id`, `mapping_status` |
| `episodes` | Канонические серии | `id PK`, `title_id`, `sequence_index`, `display_number`, `kind` |
| `release_variants` | Варианты озвучки/перевода | `id PK`, `title_id`, `provider`, `translation_name`, `language` |
| `episode_sources` | Конкретные медиа-ссылки/HLS/iframe | `id PK`, `episode_id`, `release_variant_id`, `provider_episode_id` |
| `user_titles` | Библиотека пользователя | `user_id`, `title_id`, `status`, `current_episode`, `is_favorite` |
| `subscriptions` | Подписки на уведомления | `user_id`, `title_id`, `release_variant_id`, `enabled` |
| `playback_progress` | Точный таймкод видео | `user_id`, `episode_source_id`, `position_seconds`, `duration_seconds` |
| `user_episode_state` | Факт просмотра серии | `user_id`, `episode_id`, `completed_at`, `completion_method` |
| `release_events` | Обнаруженные новые серии | `id PK`, `episode_source_id`, `detected_at` |
| `notification_outbox` | Очередь отправки уведомлений | `user_id`, `release_event_id`, `status`, `attempts`, `sent_at` |

### 3.2. Разделение понятий прогресса
* **Позиция в видео (`playback_progress`):** привязана к `episode_source_id` (конкретная озвучка и видеофайл, так как опенинги и тайминги в разных озвучках различаются).
* **Факт просмотра (`user_episode_state`):** привязан к каноническому `episode_id` (серия считается просмотренной независимо от того, в какой озвучке её досмотрели).
* **Счетчик тайтла (`current_episode`):** не инкрементируется через `+= 1` на `ended`. Рассчитывается идемпотентно по максимальному непрерывно просмотренному эпизоду из `user_episode_state`.

---

## 4. Фронтенд Telegram Mini App (Vite + React + TypeScript)

### 4.1. Архитектурный стек
* **Сборщик:** Vite (быстрый HMR, легковесный бандл для мобильного Telegram WebView).
* **UI & Стили:** Tailwind CSS + Radix UI / shadcn/ui primitives.
* **Серверный стейт:** TanStack Query v5 (кэширование запросов, автоинвалидация, отмена устаревших запросов).
* **Клиентский стейт:** Zustand (состояние UI: открытые BottomSheet, локальный выбор плеера, фильтры).
* **Навигация:** React Router (синхронизация URL, вкладки, watch route).
* **Интеграция:** Telegram WebApp SDK (`ready()`, `expand()`, `BackButton`, `HapticFeedback`).

### 4.2. Экраны приложения
1. **Главная (`/`):**
   * Блок «Продолжить просмотр» (таймкод, оставшиеся минуты, прямой переход в плеер).
   * Онгоинги сезона, тренды, персональные рекомендации из «В планах».
2. **Поиск и Vibe Wizard (`/search`):**
   * Мгновенный текстовый поиск.
   * Drawer/BottomSheet расширенных фильтров (ползунок рейтинга, диапазон годов, мультивыбор жанров, тип).
3. **Карточка тайтла (`/title/:id`):**
   * Постер, рейтинг, жанры, описание.
   * Кнопка «Смотреть» / «Продолжить».
   * Сетка серий с разделением по озвучкам.
   * Кнопки трекинга («Смотрю», «В планах», «Избранное», «Уведомлять»).
4. **Видеоплеер (`/watch/:titleId/:episodeId`):**
   * Полноэкранный плеер с адаптером (HLS / Kodik).
   * Селектор озвучки и качества.
   * Кнопки «Предыдущая / Следующая серия».
5. **Библиотека (`/library`):**
   * Вкладки «Смотрю», «В планах», «Просмотрено», «Брошено».
   * Быстрый прогресс `+1 серия` с идемпотентным запросом.

---

## 5. Архитектура плеера и воспроизведения

### 5.1. Интерфейс PlayerAdapter
```typescript
export type PlayerCapabilities = {
  position: boolean;         // Доступно ли чтение текущего таймкода
  duration: boolean;         // Доступна ли общая длительность
  seek: boolean;             // Доступна ли перемотка
  ended: boolean;            // Приходит ли событие окончания серии
  qualitySelection: boolean; // Доступно ли ручное переключение качества
};

export interface PlayerAdapter {
  mount(container: HTMLElement): Promise<void>;
  destroy(): void;
  getCapabilities(): PlayerCapabilities;
  play(): Promise<void>;
  pause(): void;
  seek(seconds: number): Promise<void>;
  on(event: "ready" | "progress" | "ended" | "error", callback: (data: unknown) => void): () => void;
}
```

### 5.2. Адаптеры источников
1. **`HlsPlayerAdapter` (AniLibria / HLS):**
   * Safari / iOS: Native `<video playsinline>` HLS.
   * Android / Desktop: `hls.js` + MediaSource engine.
   * Полная поддержка всех capabilities (`position`, `duration`, `seek`, `ended`, `qualitySelection`).
2. **`KodikIframeAdapter` (Kodik iframe):**
   * Встраивание через `<iframe>` с `allow="autoplay; fullscreen; picture-in-picture"`.
   * Двустороннее общение через `postMessage` со строгой валидацией `event.origin` по whitelist.
   * Fallback-режим: если телеметрия недоступна, отображается кнопка «Серия просмотрена».

---

## 6. Синхронизация прогресса и Heartbeat

### 6.1. Протокол Heartbeat
* Клиент отправляет `PATCH /api/v1/playback/sessions/:id/progress` каждые 15–20 секунд при активном воспроизведении, а также на `pause`, `seek` и `ended`.
* Защита от гонок: инкрементальный `sequence`-номер. Устаревшие запросы с `sequence < current` отбрасываются.
* Определение завершения серии: событие `ended` либо просмотр >85% хронометража при подтвержденном coverage (фактическом времени проигрывания, исключая быструю перемотку).

---

## 7. Связка Mini App с Telegram-ботом

### 7.1. Точки входа
1. **Menu Button бота:**
   ```python
   await bot.set_chat_menu_button(
       menu_button=MenuButtonWebApp(
           text="📺 Смотреть аниме",
           web_app=WebAppInfo(url=settings.mini_app_url),
       )
   )
   ```
2. **Direct Link & Пуши с deep link:**
   * Формат deep link: `https://t.me/AnimeSpaceFree_bot?startapp=w_{title_id}_{episode_id}`.
   * Telegram передаёт параметр в `start_param`.
   * Mini App валидирует сессию и моментально открывает экран плеера нужной серии.

### 7.2. Фоновый шедулер и Notification Outbox
* Опрос онгоингов выполняется батчами по уникальным тайтлам (а не для каждого пользователя отдельно).
* При обнаружении серии создаётся `release_event` и задания в `notification_outbox`.
* Воркер бота рассылает сообщения с инлайн-кнопкой прямого перехода в WebApp, учитывая rate limits Telegram и статус блокировки бота пользователем.

---

## 8. Пошаговые фазы разработки (Implementation Phases)

| Фаза | Название | Приоритет | Ключевой результат |
|---|---|---|---|
| **Фаза 0** | **Техническая разведка** | **P0** | Проверка воспроизведения HLS и Kodik на iOS, Android и Desktop; валидация контрактов postMessage |
| **Фаза 1** | **Backend & Монолит** | **P0** | Выделение domain/application слоя, единый репозиторий, Docker Compose (api, bot, worker) |
| **Фаза 2** | **PostgreSQL & Миграция** | **P0** | SQLAlchemy 2.0 async, Alembic, канонические ID тайтлов, скрипт миграции из SQLite `bot.db` |
| **Фаза 3** | **Auth & Каркас TMA** | **P0** | Vite + React + TS, Telegram SDK, эндпоинт HMAC-проверки `initData`, сессии, theme bridge |
| **Фаза 4** | **Каталог & Библиотека** | **P0** | Лента, карточка тайтла, трекер статусов («Смотрю», «В планах»), ручной прогресс `+1` |
| **Фаза 5** | **Первый плеер (HLS)** | **P0** | Полноценный `HlsPlayerAdapter`, heartbeat, сохранение таймкодов, resume воспроизведения |
| **Фаза 6** | **Deep Links & Пуши** | **P0** | Связка `startapp` deep link с плеером, рассылка из шедулера через Outbox |
| **Фаза 7** | **Второй плеер & Вайб** | **P1** | `KodikIframeAdapter` с capabilities fallback, расширенный Drawer фильтров Vibe Search |
| **Фаза 8** | **Production Hardening** | **P0** | Нагрузочные тесты, мониторинг ошибок воспроизведения, staging стенд, релиз |

---

## 9. Четкое разделение Scope (MVP vs Post-MVP)

### ✅ Входит в MVP:
1. Бесшовная авторизация через Telegram `initData`.
2. Каталог, поиск и детальная карточка аниме.
3. Личная библиотека (статусы, серии, избранное).
4. Один гарантированно работающий плеер (HLS) с сохранением таймкодов и resume.
5. Уведомления о сериях с кнопкой перехода сразу в плеер.
6. Сохранение работы классического текстового бота на время бета-теста.

### ⏳ Отложено на Post-MVP:
1. Второй плеер со сложным postMessage.
2. Персональные ML-рекомендации.
3. Интеграция донатов Telegram Stars внутри Mini App.
4. Отдельный публичный SSR-сайт (Next.js).
5. Расширенная социальная аналитика просмотров.
