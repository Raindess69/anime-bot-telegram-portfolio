STRINGS = {
    "welcome": (
        "Привет, {name}! 👋\n\n"
        "Я — твой ани-бот 🍿. Помогу найти любое аниме и <b>не пропустить ни одну новую серию</b>.\n\n"
        "🔔 <b>Главная фишка</b>: подпишись на любимый тайтл — и я пришлю уведомление, как только выйдет новая серия. "
        "Сканирую несколько источников (Anilibria, Yummy и др.) каждые 12 часов.\n\n"
        "Ещё умею:\n"
        "🔍 Искать аниме по названию (RU / EN / JP / UA)\n"
        "🎯 Подбирать по вайбу (год · рейтинг · жанр)\n"
        "🔥 Показывать топ-чарты MyAnimeList\n"
        "🎲 Кидать случайное аниме\n"
        "🕘 Помнить историю твоих поисков (/history)\n"
        "💖 Принимать поддержку звёздами (/donate)\n\n"
        "Жми кнопки ниже 👇 или пришли название аниме."
    ),
    "help": (
        "<b>Как пользоваться:</b>\n"
        "• Просто пришли название — я найду карточку.\n"
        "• 🔔 На карточке жми <b>Подписаться</b>, чтобы получать уведомления о новых сериях.\n"
        "• 🎯 <b>Подбор по вайбу</b> — я задам пару вопросов (год / рейтинг / жанр) и подберу топ.\n"
        "• 🔥 <b>Топы</b> — рейтинги MyAnimeList: общий, сезонный, выходят сейчас и т.д.\n"
        "• 🎲 <b>Случайное</b> — случайное аниме с MAL.\n\n"
        "<b>Команды:</b>\n"
        "/search <i>название</i> — поиск\n"
        "/subs — мои подписки\n"
        "/history — история моих поисков\n"
        "/donate — поддержать проект ⭐\n"
        "/lang — сменить язык\n"
        "/help — эта справка\n\n"
        "Ещё есть inline-режим: <code>@имя_бота название</code>"
    ),
    "choose_lang": "Выберите язык интерфейса:",
    "choose_lang_first": (
        "👋 <b>Привет! / Hi! / Привіт!</b>\n\n"
        "🇷🇺 Выбери язык интерфейса\n"
        "🇬🇧 Choose your language\n"
        "🇺🇦 Обери мову інтерфейсу"
    ),
    "lang_set": "Язык переключён на русский ✅",
    "empty_query": "Введите название аниме после команды. Пример: <code>/search Наруто</code>",
    "searching": "🔍 Ищу…",
    "not_found": "Ничего не нашёл по запросу «<b>{query}</b>». Попробуй другое название.",
    "api_error": "⚠️ Источник данных временно недоступен, попробуй через минуту.",

    "score": "Рейтинг",
    "episodes": "Серий",
    "status": "Статус",
    "genres": "Жанры",
    "year": "Год",
    "unknown": "н/д",

    "status_airing": "🟢 Выходит",
    "status_finished": "✅ Завершено",
    "status_upcoming": "🕒 Анонс",

    "btn_prev": "◀",
    "btn_next": "▶",
    "btn_watch": "▶️ Смотреть",
    "btn_episodes": "📺 Серии",
    "btn_anilibria": "▶️ Смотреть Anilibria",
    "btn_download": "💾 Скачать",
    "btn_yummy": "🌐 Смотреть Yummy Anime",
    "btn_crunchyroll": "🍥 Crunchyroll",
    "btn_kodik": "🎬 Смотреть здесь",
    "btn_kodik_episodes": "🎬 Смотреть здесь (серии)",
    "kodik_pick_episode": "🎬 <b>{title}</b>\nВыбирай серию — плеер откроется прямо тут:",
    "kodik_translation": "🎙 Озвучка: {name}",
    "btn_subscribe": "🔔 Подписаться",
    "btn_unsubscribe": "🔕 Отписаться",
    "btn_open_release": "🎬 {title}",
    "btn_watch_episode": "▶️ Смотреть серию {ep}",
    "btn_back": "⬅ Назад к карточке",
    "btn_menu": "🏠 Меню",
    "btn_mal": "MAL",
    "episode_short": "{n}",
    "episodes_header": "Выбери серию — плеер откроется во встроенном браузере Telegram:",
    "no_episodes": "Для этого тайтла Anilibria пока не подобрала эпизодов.",
    "download_header": (
        "<b>{title}</b>\n"
        "Выбери качество. Пришлю .torrent файл — открой его в qBittorrent или другом торрент-клиенте.\n"
    ),
    "download_button": "{quality} • {size} • {episodes}",
    "download_button_no_size": "{quality} • {episodes}",
    "no_torrents": "Для этого тайтла торрентов пока нет.",
    "torrent_caption": "<b>{title}</b>\nКачество: {quality}\nСерии: {episodes}\nОткрой в qBittorrent для скачивания.",
    "torrent_fetching": "⬇️ Загружаю .torrent…",
    "torrent_failed": "⚠️ Не удалось скачать torrent, попробуй ещё раз.",
    "size_gb": "{value} ГБ",

    "sub_added": "🔔 Подписан на «{title}». Проверяю новые серии каждые 12ч.",
    "sub_removed": "🔕 Отписался от «{title}».",
    "sub_removed_short": "🔕 Отписан",
    "sub_not_available": "Подписка недоступна — не смог опознать тайтл на MAL.",
    "cmd_subs_header": "🔔 <b>Твои подписки:</b>",
    "cmd_subs_empty": "У тебя нет подписок. Открой карточку любого аниме и нажми 🔔 Подписаться.",

    # --- Title tracking (status / favorites / progress) ---
    "status_track": "📌 Отслеживать",
    "status_watching": "👁 Смотрю",
    "status_completed": "✅ Просмотрено",
    "status_plan": "🕒 В планах",
    "status_dropped": "🗑 Брошено",
    "btn_favorite_on": "★ В избранном",
    "btn_favorite_off": "☆ В избранное",
    "btn_mark_watched": "✅ Посмотрел(а)",
    "fav_added": "Добавлено в избранное",
    "fav_removed": "Убрано из избранного",
    "progress_saved": "Отмечено: серия {ep}",

    # --- JSON backup export ---
    "export_caption": "Бэкап: {count} тайтлов",
    "export_empty": "Список отслеживания пуст — нечего экспортировать",

    # --- Plan-to-watch random ---
    "planrandom_empty": "В планах пока пусто. Добавьте что-нибудь через кнопку «В планах» на карточке тайтла",
    "new_episode_notification": (
        "🎬 <b>{title}</b>\n"
        "Вышла <b>серия {episode}</b>! 🎉"
    ),
    "new_episode_sources": "▶️ Смотреть:",
    "btn_source_watch": "▶️ {source}",

    "result_position": "Результат {current} из {total}",
    "no_synopsis": "Описание отсутствует.",

    # --- Persistent menu ---
    "menu_search": "🔍 Поиск",
    "menu_vibe": "🎯 Подбор по вайбу",
    "menu_top": "🔥 Топы",
    "menu_random": "🎲 Случайное",
    "menu_subs": "🔔 Мои подписки",
    "menu_history": "🕘 История",
    "menu_help": "❓ Помощь",
    "menu_donate": "💖 Донат ⭐",
    "menu_shown": "Готово! Пользуйся кнопками ниже 👇",
    "search_prompt": "Пришли название аниме следующим сообщением 🔍",
    "random_searching": "🎲 Тяну случайное аниме…",
    "random_failed": "⚠️ Не смог достать случайное аниме, попробуй ещё раз.",

    # --- Vibe wizard ---
    "vibe_intro": "🎯 <b>Подбор по вайбу</b>\nОтвечу парой вопросов — я подберу топ. Любой шаг можно пропустить.",
    "vibe_step_year": "🗓 <b>Какой период интересует?</b>",
    "vibe_step_score": "⭐ <b>Минимальный рейтинг?</b>",
    "vibe_step_genre": "🎭 <b>Жанр?</b>",
    "vibe_step_type": "🎬 <b>Формат?</b>",
    "vibe_skip": "⏭ Пропустить",
    "vibe_cancel": "✖ Отмена",
    "vibe_cancelled": "Ок, отменил подбор.",
    "vibe_searching": "🔎 Собираю подборку…",
    "vibe_empty": "По этим фильтрам ничего не нашлось. Попробуй ослабить условия.",
    "vibe_relaxed": "😅 Слишком строгие фильтры — немного расширил, вот что подобрал:",
    "vibe_year_recent": "2020+",
    "vibe_year_2015_2019": "2015–2019",
    "vibe_year_2010_2014": "2010–2014",
    "vibe_year_2000s": "2000–2009",
    "vibe_year_classic": "До 2000",
    "vibe_score_6": "6+",
    "vibe_score_7": "7+",
    "vibe_score_8": "8+",
    "vibe_score_9": "9+",
    "vibe_type_tv": "TV-сериал",
    "vibe_type_movie": "Фильм",
    "vibe_type_ova": "OVA/ONA",
    "vibe_type_any": "Любой",
    "vibe_genre_action": "⚔ Экшен",
    "vibe_genre_adventure": "🗺 Приключения",
    "vibe_genre_comedy": "😂 Комедия",
    "vibe_genre_drama": "🎭 Драма",
    "vibe_genre_fantasy": "🧙 Фэнтези",
    "vibe_genre_horror": "👻 Хоррор",
    "vibe_genre_mystery": "🕵 Детектив",
    "vibe_genre_romance": "💘 Романтика",
    "vibe_genre_sci_fi": "🚀 Фантастика",
    "vibe_genre_slice_of_life": "☕ Повседневность",
    "vibe_genre_sports": "⚽ Спорт",
    "vibe_genre_supernatural": "✨ Мистика",
    "vibe_genre_thriller": "🔪 Триллер",
    "vibe_genre_psychological": "🧠 Психологическое",
    "vibe_genre_mecha": "🤖 Меха",
    "vibe_genre_music": "🎵 Музыка",

    # --- Top wizard ---
    "top_intro": "🔥 <b>Топы</b>\nВыбирай категорию:",
    "top_overall": "🏆 Общий топ",
    "top_airing": "📡 Выходят сейчас",
    "top_upcoming": "🕒 Скоро выходят",
    "top_popular": "👀 Популярные",
    "top_movies": "🎬 Фильмы",
    "top_seasonal": "🌸 Сезон",
    "top_searching": "🔎 Собираю топ…",
    "top_empty": "Тут пока пусто, попробуй другую категорию.",

    # --- List rendering (used for vibe/top results) ---
    "list_header": "<b>{title}</b>\nВыбери номер, чтобы открыть карточку:",
    "list_item": "{n}. <b>{title}</b> — ⭐ {score} ({year})",
    "list_item_no_year": "{n}. <b>{title}</b> — ⭐ {score}",
    "list_open_card": "{n}",

    # --- Donations (Telegram Stars) ---
    "donate_intro": (
        "💖 <b>Ты крутой, что дошёл до этой кнопки!</b>\n\n"
        "Ани-бот на 100% бесплатный: без рекламы, без платных фич, без «премиум-подписки». "
        "Он живёт только на добровольной поддержке.\n\n"
        "Куда идёт твой донат:\n"
        "🌐 Хостинг 24/7 — чтобы бот не спал ночами\n"
        "🛠 Новые источники и фишки (Kodik, Crunchyroll и др.)\n"
        "⚡ Скорость ответов и стабильность\n\n"
        "💡 <b>Что такое ⭐?</b> Telegram Stars — встроенная валюта Telegram. "
        "Реальные деньги <b>не тратятся</b>, платишь звёздами со своего Telegram-баланса.\n\n"
        "Выбери, чем угостить бота 👇"
    ),
    "donate_option": "{amount} ⭐",
    "donate_invoice_title": "Спасибо ани-боту ⭐",
    "donate_invoice_desc": "Донат {amount} ⭐ — спасибо, что помогаешь боту жить 💖",
    "donate_invoice_label": "Донат {amount} ⭐",
    "donate_thanks": (
        "🎉 <b>Огромное спасибо за {amount} ⭐!</b>\n\n"
        "Ты только что помог боту прожить ещё немного 🫂\n"
        "Твоя поддержка — это топливо для новых фишек. Обнимаю от лица всех отаку 🍿"
    ),
    "donate_failed": "⚠️ Не удалось создать счёт, попробуй ещё раз.",

    # --- Search history ---
    "history_empty": "🕘 История пустая. Пришли название аниме — я запомню.",
    "history_header": "🕘 <b>Последние 10 запросов</b>\nЖми, чтобы повторить:",
    "history_item": "{n}. {query}",
    "history_clear": "🗑 Очистить историю",
    "history_cleared": "🗑 История очищена.",
    "history_reopening": "🔍 Повторяю: {query}",

    # --- Persistent menu: My List ---
    "menu_mylist": "📋 Мой список",

    # --- My List picker/list view ---
    "mylist_intro": "📋 <b>Мой список</b>\nВыберите раздел:",
    "mylist_cat_fav": "★ Избранное",
    "mylist_cat_stats": "📊 Статистика",
    "mylist_header": "<b>{category}</b>",
    "mylist_empty": "Здесь пока пусто",
    "mylist_item": "{n}. {title} (эп. {ep})",
    "mylist_item_no_progress": "{n}. {title}",
    "mylist_stats_text": (
        "📊 <b>Статистика</b>\n\n"
        "👁 Смотрю: {watching}\n"
        "✅ Просмотрено: {completed}\n"
        "🕒 В планах: {plan}\n"
        "🗑 Брошено: {dropped}\n"
        "★ Избранное: {favorites}\n\n"
        "Всего просмотрено серий: {episodes}"
    ),

    # --- /import backup restore ---
    "import_prompt": "Прикрепите файл бэкапа (JSON, полученный через /export) к этой команде — отправьте файл с подписью /import, либо ответьте на сообщение с файлом командой /import",
    "import_no_file": "Файл не найден. Прикрепите JSON-бэкап или ответьте на сообщение с ним",
    "import_bad_format": "Не удалось прочитать файл — это не похоже на бэкап от /export",
    "import_done": "Восстановлено тайтлов: {count}",

    # --- Similar anime recommendations ---
    "btn_similar": "🔀 Похожее",
    "similar_header": "Похоже на «{title}»:",
    "similar_empty": "Рекомендаций не нашлось",
    "similar_fetching": "Ищу похожее…",
}
