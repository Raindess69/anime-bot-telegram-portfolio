STRINGS = {
    "welcome": (
        "Привіт, {name}! 👋\n\n"
        "Я — твій аніме-бот 🍿. Допоможу знайти будь-яке аніме і <b>не пропустити жодної нової серії</b>.\n\n"
        "🔔 <b>Головна фішка</b>: підпишись на улюблений тайтл — і я сповіщу, щойно вийде нова серія. "
        "Сканую кілька джерел (Anilibria, Yummy та інші) кожні 12 годин.\n\n"
        "Ще вмію:\n"
        "🔍 Шукати аніме за назвою (RU / EN / JP / UA)\n"
        "🎯 Підбирати за настроєм (рік · рейтинг · жанр)\n"
        "🔥 Показувати топ-чарти MyAnimeList\n"
        "🎲 Кидати випадкове аніме\n"
        "🕘 Пам'ятати історію твоїх пошуків (/history)\n"
        "💖 Приймати підтримку зірочками (/donate)\n\n"
        "Тисни кнопки нижче 👇 або надішли назву аніме."
    ),
    "help": (
        "<b>Як користуватися:</b>\n"
        "• Просто надішли назву — я знайду картку.\n"
        "• 🔔 На картці тисни <b>Підписатись</b>, щоб отримувати сповіщення про нові серії.\n"
        "• 🎯 <b>Підбір за настроєм</b> — задам кілька питань (рік / рейтинг / жанр) і підберу топ.\n"
        "• 🔥 <b>Топи</b> — рейтинги MyAnimeList: загальний, сезонний, ті що виходять зараз тощо.\n"
        "• 🎲 <b>Випадкове</b> — випадкове аніме з MAL.\n\n"
        "<b>Команди:</b>\n"
        "/search <i>назва</i> — пошук\n"
        "/subs — мої підписки\n"
        "/history — історія моїх пошуків\n"
        "/donate — підтримати проект ⭐\n"
        "/lang — змінити мову\n"
        "/help — ця довідка\n\n"
        "Також працює inline-режим: <code>@ім'я_бота назва</code>"
    ),
    "choose_lang": "Оберіть мову інтерфейсу:",
    "choose_lang_first": (
        "👋 <b>Привет! / Hi! / Привіт!</b>\n\n"
        "🇷🇺 Выбери язык интерфейса\n"
        "🇬🇧 Choose your language\n"
        "🇺🇦 Обери мову інтерфейсу"
    ),
    "lang_set": "Мову перемкнено на українську ✅",
    "empty_query": "Введіть назву аніме після команди. Приклад: <code>/search Наруто</code>",
    "searching": "🔍 Шукаю…",
    "not_found": "Нічого не знайшов за запитом «<b>{query}</b>». Спробуй іншу назву.",
    "api_error": "⚠️ Джерело даних тимчасово недоступне, спробуй за хвилину.",

    "score": "Рейтинг",
    "episodes": "Серій",
    "status": "Статус",
    "genres": "Жанри",
    "year": "Рік",
    "unknown": "н/д",

    "status_airing": "🟢 Виходить",
    "status_finished": "✅ Завершено",
    "status_upcoming": "🕒 Анонс",

    "btn_prev": "◀",
    "btn_next": "▶",
    "btn_watch": "▶️ Дивитись",
    "btn_episodes": "📺 Серії",
    "btn_anilibria": "▶️ Дивитись Anilibria",
    "btn_download": "💾 Завантажити",
    "btn_yummy": "🌐 Дивитись Yummy Anime",
    "btn_crunchyroll": "🍥 Crunchyroll",
    "btn_kodik": "🎬 Дивитись тут",
    "btn_kodik_episodes": "🎬 Дивитись тут (серії)",
    "kodik_pick_episode": "🎬 <b>{title}</b>\nОбери серію — плеєр відкриється прямо тут:",
    "kodik_translation": "🎙 Озвучка: {name}",
    "btn_subscribe": "🔔 Підписатись",
    "btn_unsubscribe": "🔕 Відписатись",
    "btn_open_release": "🎬 {title}",
    "btn_watch_episode": "▶️ Дивитись серію {ep}",
    "btn_back": "⬅ Назад до картки",
    "btn_menu": "🏠 Меню",
    "btn_mal": "MAL",
    "episode_short": "{n}",
    "episodes_header": "Обери серію — плеєр відкриється у вбудованому браузері Telegram:",
    "no_episodes": "Для цього тайтлу Anilibria поки не підібрала епізодів.",
    "download_header": (
        "<b>{title}</b>\n"
        "Обери якість. Надішлю .torrent файл — відкрий його в qBittorrent або іншому торент-клієнті.\n"
    ),
    "download_button": "{quality} • {size} • {episodes}",
    "download_button_no_size": "{quality} • {episodes}",
    "no_torrents": "Для цього тайтлу торентів поки немає.",
    "torrent_caption": "<b>{title}</b>\nЯкість: {quality}\nСерії: {episodes}\nВідкрий у qBittorrent для завантаження.",
    "torrent_fetching": "⬇️ Завантажую .torrent…",
    "torrent_failed": "⚠️ Не вдалося завантажити torrent, спробуй ще раз.",
    "size_gb": "{value} ГБ",

    "sub_added": "🔔 Підписан на «{title}». Перевіряю нові серії кожні 12г.",
    "sub_removed": "🔕 Відписаний від «{title}».",
    "sub_removed_short": "🔕 Відписано",
    "sub_not_available": "Підписка недоступна — не зміг ідентифікувати тайтл на MAL.",
    "cmd_subs_header": "🔔 <b>Твої підписки:</b>",
    "cmd_subs_empty": "У тебе немає підписок. Відкрий картку будь-якого аніме та натисни 🔔 Підписатись.",

    # --- Title tracking (status / favorites / progress) ---
    "status_track": "📌 Відстежувати",
    "status_watching": "👁 Дивлюсь",
    "status_completed": "✅ Переглянуто",
    "status_plan": "🕒 У планах",
    "status_dropped": "🗑 Покинуто",
    "btn_favorite_on": "★ В обраному",
    "btn_favorite_off": "☆ В обране",
    "btn_mark_watched": "✅ Переглянув(ла)",
    "fav_added": "Додано в обране",
    "fav_removed": "Прибрано з обраного",
    "progress_saved": "Відмічено: серія {ep}",

    # --- JSON backup export ---
    "export_caption": "Бекап: {count} тайтлів",
    "export_empty": "Список відстеження порожній — нема чого експортувати",

    # --- Plan-to-watch random ---
    "planrandom_empty": "У планах поки порожньо. Додай щось через кнопку «У планах» на картці тайтла",
    "new_episode_notification": (
        "🎬 <b>{title}</b>\n"
        "Вийшла <b>серія {episode}</b>! 🎉"
    ),
    "new_episode_push": "Вийшла нова серія: <b>{title}</b>\nСерія {episode}",
    "new_episode_sources": "▶️ Дивитись:",
    "btn_source_watch": "▶️ {source}",
    "btn_watch_episode_generic": "▶ Дивитись серію",

    "result_position": "Результат {current} з {total}",
    "no_synopsis": "Опис відсутній.",

    # --- Persistent menu ---
    "menu_search": "🔍 Пошук",
    "menu_vibe": "🎯 Підбір за настроєм",
    "menu_top": "🔥 Топи",
    "menu_random": "🎲 Випадкове",
    "menu_subs": "🔔 Мої підписки",
    "menu_history": "🕘 Історія",
    "menu_help": "❓ Довідка",
    "menu_donate": "💖 Донат ⭐",
    "menu_shown": "Готово! Користуйся кнопками нижче 👇",
    "search_prompt": "Надішли назву аніме наступним повідомленням 🔍",
    "random_searching": "🎲 Тягну випадкове аніме…",
    "random_failed": "⚠️ Не зміг дістати випадкове аніме, спробуй ще раз.",

    # --- Vibe wizard ---
    "vibe_intro": "🎯 <b>Підбір за настроєм</b>\nВідповім парою питань — підберу топ. Будь-який крок можна пропустити.",
    "vibe_step_year": "🗓 <b>Який період цікавить?</b>",
    "vibe_step_score": "⭐ <b>Мінімальний рейтинг?</b>",
    "vibe_step_genre": "🎭 <b>Жанр?</b>",
    "vibe_step_type": "🎬 <b>Формат?</b>",
    "vibe_skip": "⏭ Пропустити",
    "vibe_cancel": "✖ Скасувати",
    "vibe_cancelled": "Ок, скасував підбір.",
    "vibe_searching": "🔎 Збираю підбірку…",
    "vibe_empty": "За цими фільтрами нічого не знайшлося. Спробуй послабити умови.",
    "vibe_relaxed": "😅 Занадто суворі фільтри — трохи розширив, ось що підібрав:",
    "vibe_year_recent": "2020+",
    "vibe_year_2015_2019": "2015–2019",
    "vibe_year_2010_2014": "2010–2014",
    "vibe_year_2000s": "2000–2009",
    "vibe_year_classic": "До 2000",
    "vibe_score_6": "6+",
    "vibe_score_7": "7+",
    "vibe_score_8": "8+",
    "vibe_score_9": "9+",
    "vibe_type_tv": "TV-серіал",
    "vibe_type_movie": "Фільм",
    "vibe_type_ova": "OVA/ONA",
    "vibe_type_any": "Будь-який",
    "vibe_genre_action": "⚔ Екшн",
    "vibe_genre_adventure": "🗺 Пригоди",
    "vibe_genre_comedy": "😂 Комедія",
    "vibe_genre_drama": "🎭 Драма",
    "vibe_genre_fantasy": "🧙 Фентезі",
    "vibe_genre_horror": "👻 Жахи",
    "vibe_genre_mystery": "🕵 Детектив",
    "vibe_genre_romance": "💘 Романтика",
    "vibe_genre_sci_fi": "🚀 Фантастика",
    "vibe_genre_slice_of_life": "☕ Повсякденність",
    "vibe_genre_sports": "⚽ Спорт",
    "vibe_genre_supernatural": "✨ Містика",
    "vibe_genre_thriller": "🔪 Трилер",
    "vibe_genre_psychological": "🧠 Психологічне",
    "vibe_genre_mecha": "🤖 Меха",
    "vibe_genre_music": "🎵 Музика",

    # --- Top wizard ---
    "top_intro": "🔥 <b>Топи</b>\nОбирай категорію:",
    "top_overall": "🏆 Загальний топ",
    "top_airing": "📡 Виходять зараз",
    "top_upcoming": "🕒 Скоро виходять",
    "top_popular": "👀 Популярні",
    "top_movies": "🎬 Фільми",
    "top_seasonal": "🌸 Сезон",
    "top_searching": "🔎 Збираю топ…",
    "top_empty": "Тут поки порожньо, спробуй іншу категорію.",

    # --- List rendering (used for vibe/top results) ---
    "list_header": "<b>{title}</b>\nОбери номер, щоб відкрити картку:",
    "list_item": "{n}. <b>{title}</b> — ⭐ {score} ({year})",
    "list_item_no_year": "{n}. <b>{title}</b> — ⭐ {score}",
    "list_open_card": "{n}",

    # --- Donations (Telegram Stars) ---
    "donate_intro": (
        "💖 <b>Ти класний, що взагалі відкрив цю кнопку!</b>\n\n"
        "Аніме-бот на 100% безкоштовний: без реклами, без платних фішок, без «преміум-підписки». "
        "Він живе тільки на добровільній підтримці.\n\n"
        "Куди йде твій донат:\n"
        "🌐 Хостинг 24/7 — щоб бот не спав ночами\n"
        "🛠 Нові джерела та фішки (Kodik, Crunchyroll тощо)\n"
        "⚡ Швидкість відповідей і стабільність\n\n"
        "💡 <b>Що таке ⭐?</b> Telegram Stars — вбудована валюта Telegram. "
        "Реальні гроші <b>не витрачаються</b>, платиш зірочками зі свого Telegram-балансу.\n\n"
        "Обери, чим пригостити бота 👇"
    ),
    "donate_option": "{amount} ⭐",
    "donate_invoice_title": "Дякую, аніме-бот ⭐",
    "donate_invoice_desc": "Донат {amount} ⭐ — дякую, що тримаєш бота живим 💖",
    "donate_invoice_label": "Донат {amount} ⭐",
    "donate_thanks": (
        "🎉 <b>Величезне дякую за {amount} ⭐!</b>\n\n"
        "Ти щойно допоміг боту прожити ще трохи 🫂\n"
        "Твоя підтримка — це паливо для нових фішок. Обіймаю від імені всіх отаку 🍿"
    ),
    "donate_failed": "⚠️ Не вдалося створити рахунок, спробуй ще раз.",

    # --- Search history ---
    "history_empty": "🕘 Історія порожня. Надішли назву аніме — запам'ятаю.",
    "history_header": "🕘 <b>Останні 10 запитів</b>\nТисни, щоб повторити:",
    "history_item": "{n}. {query}",
    "history_clear": "🗑 Очистити історію",
    "history_cleared": "🗑 Історію очищено.",
    "history_reopening": "🔍 Повторюю: {query}",

    # --- Persistent menu: My List ---
    "menu_mylist": "📋 Мій список",

    # --- My List picker/list view ---
    "mylist_intro": "📋 <b>Мій список</b>\nОбери розділ:",
    "mylist_cat_fav": "★ Обране",
    "mylist_cat_stats": "📊 Статистика",
    "mylist_header": "<b>{category}</b>",
    "mylist_empty": "Тут поки порожньо",
    "mylist_item": "{n}. {title} (еп. {ep})",
    "mylist_item_no_progress": "{n}. {title}",
    "mylist_stats_text": (
        "📊 <b>Статистика</b>\n\n"
        "👁 Дивлюсь: {watching}\n"
        "✅ Переглянуто: {completed}\n"
        "🕒 У планах: {plan}\n"
        "🗑 Покинуто: {dropped}\n"
        "★ Обране: {favorites}\n\n"
        "Всього переглянуто серій: {episodes}"
    ),

    # --- /import backup restore ---
    "import_prompt": "Прикріпи файл бекапу (JSON, отриманий через /export) до цієї команди — надішли файл з підписом /import, або дай відповідь на повідомлення з файлом командою /import",
    "import_no_file": "Файл не знайдено. Прикріпи JSON-бекап або дай відповідь на повідомлення з ним",
    "import_bad_format": "Не вдалося прочитати файл — це не схоже на бекап від /export",
    "import_done": "Відновлено тайтлів: {count}",

    # --- Similar anime recommendations ---
    "btn_similar": "🔀 Схоже",
    "similar_header": "Схоже на «{title}»:",
    "similar_empty": "Рекомендацій не знайшлося",
    "similar_fetching": "Шукаю схоже…",
}
