STRINGS = {
    "welcome": (
        "Hi, {name}! 👋\n\n"
        "I'm your anime bot 🍿. I'll help you find any show and <b>never miss a new episode</b>.\n\n"
        "🔔 <b>Main feature</b>: subscribe to your favourite title and I'll ping you the moment a new "
        "episode drops. I scan several sources (Anilibria, Yummy and more) every 12 hours.\n\n"
        "I can also:\n"
        "🔍 Search anime by title (RU / EN / JP / UA)\n"
        "🎯 Vibe-pick by year · score · genre\n"
        "🔥 Show MyAnimeList top charts\n"
        "🎲 Roll a random anime\n"
        "🕘 Remember your recent searches (/history)\n"
        "💖 Accept Stars support (/donate)\n\n"
        "Tap the buttons below 👇 or just send a title."
    ),
    "help": (
        "<b>How to use:</b>\n"
        "• Just send a title — I'll fetch the card.\n"
        "• 🔔 Press <b>Subscribe</b> on a card to get pinged about new episodes.\n"
        "• 🎯 <b>Vibe pick</b> — I'll ask a few questions (year / score / genre) and hand-pick a top list.\n"
        "• 🔥 <b>Top charts</b> — MyAnimeList rankings: overall, seasonal, currently airing, etc.\n"
        "• 🎲 <b>Random</b> — a random anime from MAL.\n\n"
        "<b>Commands:</b>\n"
        "/search <i>title</i> — search\n"
        "/subs — my subscriptions\n"
        "/history — my search history\n"
        "/donate — support the project ⭐\n"
        "/lang — switch language\n"
        "/help — this help\n\n"
        "Inline mode also works: <code>@bot_name title</code>"
    ),
    "choose_lang": "Choose interface language:",
    "choose_lang_first": (
        "👋 <b>Привет! / Hi! / Привіт!</b>\n\n"
        "🇷🇺 Выбери язык интерфейса\n"
        "🇬🇧 Choose your language\n"
        "🇺🇦 Обери мову інтерфейсу"
    ),
    "lang_set": "Language switched to English ✅",
    "empty_query": "Add a title after the command. Example: <code>/search Naruto</code>",
    "searching": "🔍 Searching…",
    "not_found": "Nothing found for «<b>{query}</b>». Try another title.",
    "api_error": "⚠️ Data source is temporarily unavailable, try again in a minute.",

    "score": "Score",
    "episodes": "Episodes",
    "status": "Status",
    "genres": "Genres",
    "year": "Year",
    "unknown": "n/a",

    "status_airing": "🟢 Airing",
    "status_finished": "✅ Finished",
    "status_upcoming": "🕒 Upcoming",

    "btn_prev": "◀",
    "btn_next": "▶",
    "btn_watch": "▶️ Watch",
    "btn_episodes": "📺 Episodes",
    "btn_anilibria": "▶️ Watch on Anilibria",
    "btn_download": "💾 Download",
    "btn_yummy": "🌐 Watch on Yummy Anime",
    "btn_crunchyroll": "🍥 Crunchyroll",
    "btn_kodik": "🎬 Watch here",
    "btn_kodik_episodes": "🎬 Watch here (episodes)",
    "kodik_pick_episode": "🎬 <b>{title}</b>\nPick an episode — the player opens right here:",
    "kodik_translation": "🎙 Dub: {name}",
    "btn_subscribe": "🔔 Subscribe",
    "btn_unsubscribe": "🔕 Unsubscribe",
    "btn_open_release": "🎬 {title}",
    "btn_watch_episode": "▶️ Watch episode {ep}",
    "btn_back": "⬅ Back to card",
    "btn_menu": "🏠 Menu",
    "btn_mal": "MAL",
    "episode_short": "{n}",
    "episodes_header": "Pick an episode — the player opens in Telegram's in-app browser:",
    "no_episodes": "Anilibria hasn't matched episodes for this title yet.",
    "download_header": (
        "<b>{title}</b>\n"
        "Pick a quality. I'll send you a .torrent file — open it in qBittorrent or any torrent client.\n"
    ),
    "download_button": "{quality} • {size} • {episodes}",
    "download_button_no_size": "{quality} • {episodes}",
    "no_torrents": "No torrents matched for this title yet.",
    "torrent_caption": "<b>{title}</b>\nQuality: {quality}\nEpisodes: {episodes}\nOpen with qBittorrent to download.",
    "torrent_fetching": "⬇️ Fetching .torrent…",
    "torrent_failed": "⚠️ Failed to fetch torrent, try again.",
    "size_gb": "{value} GB",

    "sub_added": "🔔 Subscribed to «{title}». Checking for new episodes every 12h.",
    "sub_removed": "🔕 Unsubscribed from «{title}».",
    "sub_removed_short": "🔕 Unsubscribed",
    "sub_not_available": "Subscription unavailable — couldn't identify this title on MAL.",
    "cmd_subs_header": "🔔 <b>Your subscriptions:</b>",
    "cmd_subs_empty": "You have no subscriptions. Open any anime card and press 🔔 Subscribe.",

    # --- Title tracking (status / favorites / progress) ---
    "status_track": "📌 Track",
    "status_watching": "👁 Watching",
    "status_completed": "✅ Completed",
    "status_plan": "🕒 Plan to watch",
    "status_dropped": "🗑 Dropped",
    "btn_favorite_on": "★ In favourites",
    "btn_favorite_off": "☆ Add to favourites",
    "btn_mark_watched": "✅ Watched it",
    "fav_added": "Added to favourites",
    "fav_removed": "Removed from favourites",
    "progress_saved": "Marked: episode {ep}",

    # --- JSON backup export ---
    "export_caption": "Backup: {count} titles",
    "export_empty": "Your tracking list is empty — nothing to export",

    # --- Plan-to-watch random ---
    "planrandom_empty": "Your plan-to-watch list is empty. Add something with the 🕒 Plan to watch button on a title card",
    "new_episode_notification": (
        "🎬 <b>{title}</b>\n"
        "<b>Episode {episode}</b> is out! 🎉"
    ),
    "new_episode_push": "New episode released: <b>{title}</b>\nEpisode {episode}",
    "new_episode_sources": "▶️ Watch on:",
    "btn_source_watch": "▶️ {source}",
    "btn_watch_episode_generic": "▶ Watch episode",

    "result_position": "Result {current} of {total}",
    "no_synopsis": "No synopsis available.",

    # --- Persistent menu ---
    "menu_search": "🔍 Search",
    "menu_vibe": "🎯 Vibe pick",
    "menu_top": "🔥 Top charts",
    "menu_random": "🎲 Random",
    "menu_subs": "🔔 My subs",
    "menu_history": "🕘 History",
    "menu_help": "❓ Help",
    "menu_donate": "💖 Donate ⭐",
    "menu_shown": "Done! Use the buttons below 👇",
    "search_prompt": "Send the anime title in the next message 🔍",
    "random_searching": "🎲 Rolling a random anime…",
    "random_failed": "⚠️ Couldn't fetch a random anime, try again.",

    # --- Vibe wizard ---
    "vibe_intro": "🎯 <b>Vibe pick</b>\nA few questions — I'll hand-pick a list. Any step can be skipped.",
    "vibe_step_year": "🗓 <b>Which era?</b>",
    "vibe_step_score": "⭐ <b>Minimum score?</b>",
    "vibe_step_genre": "🎭 <b>Genre?</b>",
    "vibe_step_type": "🎬 <b>Format?</b>",
    "vibe_skip": "⏭ Skip",
    "vibe_cancel": "✖ Cancel",
    "vibe_cancelled": "Ok, cancelled the vibe pick.",
    "vibe_searching": "🔎 Building your list…",
    "vibe_empty": "Nothing matched. Try loosening the filters.",
    "vibe_relaxed": "😅 Filters were too strict — loosened them a bit, here's what I found:",
    "vibe_year_recent": "2020+",
    "vibe_year_2015_2019": "2015–2019",
    "vibe_year_2010_2014": "2010–2014",
    "vibe_year_2000s": "2000–2009",
    "vibe_year_classic": "Before 2000",
    "vibe_score_6": "6+",
    "vibe_score_7": "7+",
    "vibe_score_8": "8+",
    "vibe_score_9": "9+",
    "vibe_type_tv": "TV series",
    "vibe_type_movie": "Movie",
    "vibe_type_ova": "OVA/ONA",
    "vibe_type_any": "Any",
    "vibe_genre_action": "⚔ Action",
    "vibe_genre_adventure": "🗺 Adventure",
    "vibe_genre_comedy": "😂 Comedy",
    "vibe_genre_drama": "🎭 Drama",
    "vibe_genre_fantasy": "🧙 Fantasy",
    "vibe_genre_horror": "👻 Horror",
    "vibe_genre_mystery": "🕵 Mystery",
    "vibe_genre_romance": "💘 Romance",
    "vibe_genre_sci_fi": "🚀 Sci-Fi",
    "vibe_genre_slice_of_life": "☕ Slice of Life",
    "vibe_genre_sports": "⚽ Sports",
    "vibe_genre_supernatural": "✨ Supernatural",
    "vibe_genre_thriller": "🔪 Thriller",
    "vibe_genre_psychological": "🧠 Psychological",
    "vibe_genre_mecha": "🤖 Mecha",
    "vibe_genre_music": "🎵 Music",

    # --- Top wizard ---
    "top_intro": "🔥 <b>Top charts</b>\nPick a category:",
    "top_overall": "🏆 Overall",
    "top_airing": "📡 Airing now",
    "top_upcoming": "🕒 Upcoming",
    "top_popular": "👀 Popular",
    "top_movies": "🎬 Movies",
    "top_seasonal": "🌸 Season",
    "top_searching": "🔎 Fetching top…",
    "top_empty": "This chart is empty right now, try another category.",

    # --- List rendering (used for vibe/top results) ---
    "list_header": "<b>{title}</b>\nPick a number to open the card:",
    "list_item": "{n}. <b>{title}</b> — ⭐ {score} ({year})",
    "list_item_no_year": "{n}. <b>{title}</b> — ⭐ {score}",
    "list_open_card": "{n}",

    # --- Donations (Telegram Stars) ---
    "donate_intro": (
        "💖 <b>You're awesome for even opening this!</b>\n\n"
        "The anime bot is 100% free: no ads, no paid features, no «premium» tier. "
        "It runs on voluntary support only.\n\n"
        "What your donation buys:\n"
        "🌐 24/7 hosting — so the bot never sleeps\n"
        "🛠 New sources & features (Kodik, Crunchyroll, etc.)\n"
        "⚡ Speed and stability\n\n"
        "💡 <b>What are ⭐?</b> Telegram Stars are Telegram's built-in currency. "
        "You're <b>not spending real money</b> — it's paid from your Telegram Stars balance.\n\n"
        "Pick how you'd like to treat the bot 👇"
    ),
    "donate_option": "{amount} ⭐",
    "donate_invoice_title": "Thanks, anime bot ⭐",
    "donate_invoice_desc": "Donation {amount} ⭐ — thanks for keeping the bot alive 💖",
    "donate_invoice_label": "Donate {amount} ⭐",
    "donate_thanks": (
        "🎉 <b>Huge thanks for the {amount} ⭐!</b>\n\n"
        "You just gave the bot a bit more life 🫂\n"
        "Your support is fuel for new features. A big hug from every otaku out there 🍿"
    ),
    "donate_failed": "⚠️ Couldn't create the invoice, try again.",

    # --- Search history ---
    "history_empty": "🕘 History is empty. Send a title — I'll remember it.",
    "history_header": "🕘 <b>Last 10 searches</b>\nTap to repeat:",
    "history_item": "{n}. {query}",
    "history_clear": "🗑 Clear history",
    "history_cleared": "🗑 History cleared.",
    "history_reopening": "🔍 Repeating: {query}",

    # --- Persistent menu: My List ---
    "menu_mylist": "📋 My List",

    # --- My List picker/list view ---
    "mylist_intro": "📋 <b>My List</b>\nPick a section:",
    "mylist_cat_fav": "★ Favourites",
    "mylist_cat_stats": "📊 Stats",
    "mylist_header": "<b>{category}</b>",
    "mylist_empty": "Nothing here yet",
    "mylist_item": "{n}. {title} (ep. {ep})",
    "mylist_item_no_progress": "{n}. {title}",
    "mylist_stats_text": (
        "📊 <b>Stats</b>\n\n"
        "👁 Watching: {watching}\n"
        "✅ Completed: {completed}\n"
        "🕒 Plan to watch: {plan}\n"
        "🗑 Dropped: {dropped}\n"
        "★ Favourites: {favorites}\n\n"
        "Total episodes watched: {episodes}"
    ),

    # --- /import backup restore ---
    "import_prompt": "Attach the backup file (JSON from /export) to this command — send the file with caption /import, or reply to the message with the file using /import",
    "import_no_file": "No file found. Attach a JSON backup or reply to the message with it",
    "import_bad_format": "Couldn't read the file — it doesn't look like an /export backup",
    "import_done": "Restored titles: {count}",

    # --- Similar anime recommendations ---
    "btn_similar": "🔀 Similar",
    "similar_header": "Similar to «{title}»:",
    "similar_empty": "No recommendations found",
    "similar_fetching": "Looking for similar titles…",
}
