# Anime Telegram Bot

Trilingual (RU / EN / UK) Telegram bot that unifies anime search across seven
public sources, notifies users about new episodes, and lets them watch them
without leaving the chat.

Built on **aiogram v3** with async orchestration, SQLite persistence,
FSM-based UI wizards, and a full internationalization layer.

---

## What it does

| Feature | How it works |
|---|---|
| Search by title | Fans out queries to Jikan (MAL), AniList and Shikimori in parallel, merges results by MAL id, ranks source-appropriately per language. |
| Watch links | For each result, enriches with Anilibria (legal RU stream), Yummy Anime (RU catalog), Crunchyroll (global), and Kodik (in-Telegram episode picker). |
| New-episode alerts | Every 12 h, probes 4 sources per subscription (Anilibria / Yummy / Kodik / Shikimori), pings the user with the highest episode number found and a button per source. |
| Vibe pick | FSM wizard asks year → score → genre → format, then runs Jikan + AniList with progressive filter relaxation. |
| Top charts | Multi-source fallback: Jikan → AniList → Shikimori (whichever answers first with results). |
| Random | Same fallback chain, one-shot. |
| Search history | Last 10 queries per user, deduped consecutively, one-tap to repeat. |
| Telegram Stars donations | `/donate` with 4 tiers, full `pre_checkout` + `successful_payment` flow. |
| Inline mode | `@bot_name title` in any chat → up to 20 photo results with Watch buttons. |

## Architecture

```
bot.py                    ── entry point, wires routers + scheduler task
config.py                 ── pydantic-settings (.env-driven)
handlers/
  commands.py             ── /start, /help, /lang, /search, /subs
  menu.py                 ── persistent reply-keyboard + vibe/top/random FSM
  search.py               ── text search, keyboard builder, card renderer
  callbacks.py            ── nav, episode pickers (Anilibria + Kodik), sub toggle
  history.py              ── /history + repeat-search callbacks
  donate.py               ── /donate + Telegram Stars payment flow
  inline.py               ── @bot inline query mode
services/
  aggregator.py           ── search fan-out, merge, ranking, enrichment
  jikan.py                ── MyAnimeList via jikan.moe (metadata, top, random)
  anilist.py              ── AniList GraphQL (search, top, seasonal, external links)
  shikimori.py            ── Russian titles + fallback source
  anilibria.py            ── AniLiberty V1 REST (episodes, torrents, direct player URLs)
  yummy.py                ── HTML scraping of yummyanime.tv with title fuzzy match
  kodik.py                ── Kodik API (in-Telegram episode player)
  scheduler.py            ── periodic multi-source episode probe → notification fan-out
db/
  users.py                ── language preference
  subscriptions.py        ── multi-source subscription schema with auto-migration v1→v2
  history.py              ── search history ring-buffer per user
locales/                  ── ru.py / en.py / uk.py + t(key, lang, **kwargs)
models/anime.py           ── AnimeCard pydantic model
utils/
  cache.py                ── TTL cache for search results
  formatting.py           ── HTML-safe card rendering
```

### Design decisions worth reading the code for

- **Search ranking is language-aware.** RU users get Shikimori first (Russian
  titles), EN users get Jikan first, UK users get a Ukrainian→Russian-ish
  translit variant added to the query pool so `і`/`ї`/`є` don't tank recall.
  See `services/aggregator.py::_search_ru` / `_search_uk` / `_search_en`.

- **Anilibria matching threshold + compact-string shortcut.** Naive
  `SequenceMatcher.ratio()` treats "Blue Lock" vs "Blue Box" as 0.67 similar
  and produces confident wrong matches. Fix: strip spaces/punctuation
  (`_compact`) and floor the score at 0.9 when one compact string is a
  substring of the other. So `Ao Ashi` ⇔ `Aoashi` = 1.0 (compact identical),
  but the fake `Blue Lock` ⇔ `Blue Box` hit stays below the 0.75 threshold.
  See `services/anilibria.py::find_release`.

- **Yummy anti-collision.** For franchises with 10 similar-slug titles
  (`mushoku-tensei`, `mushoku-tensei-2`, `mushoku-tensei-special`), the
  fuzzy match kept returning the same "longest slug". Added a top-1 vs
  top-2 margin check: if the winner is only marginally better, fall back
  to the search page instead. See `services/yummy.py::find_direct_link`.

- **Subscription schema auto-migration.** v1 rows keyed on `(user_id,
  anilibria_code)`. v2 keys on `(user_id, mal_id)` and stores per-source
  columns. `db/subscriptions.py::_ensure_schema` runs
  `ALTER RENAME → CREATE new → INSERT SELECT → DROP old` on startup if it
  detects v1.

- **Kodik episode picker fits into Telegram's keyboard limits.** 10 episodes
  per page (5×2), inline pagination via `kodep:{idx}:{page}` callback data,
  falls back to a direct URL button when the title has only one episode.
  See `handlers/callbacks.py::_kodik_episodes_keyboard`.

- **Scheduler probes all sources in parallel per subscription.** Only
  surfaces "▶ Kodik" / "▶ Anilibria" buttons that actually reached the max
  episode found across sources — cheaper sources sometimes lag by one
  release cycle. See `services/scheduler.py::check_new_episodes`.

- **AniList `externalLinks` is a batched GraphQL call.** One round-trip
  enriches Crunchyroll URLs for all 10 cards. Kodik has no batch endpoint,
  so it's a fan-out gathered with `asyncio.gather`. See
  `services/aggregator.py::_fill_streaming_links`.

- **Router order matters in aiogram.** Persistent-menu button texts must
  match before the `text_search` catch-all, otherwise pressing "🔥 Топы"
  would trigger a search for the literal string. See `bot.py`.

- **State-safe locale switching.** After a language change we resend the
  reply-keyboard immediately, otherwise the visible menu button labels
  stay stuck on the previous locale.

## Stack

`Python 3.11+`, `aiogram 3.x`, `httpx`, `aiosqlite`, `pydantic v2`,
`pydantic-settings`. No web framework, no ORM, no message broker — the
whole thing is single-process async.

## Setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# edit .env: set BOT_TOKEN from @BotFather

python bot.py
```

On Windows there's a helper: `run.bat` creates the venv, installs deps and
launches the bot.

## Configuration

All settings live in `.env` (see `.env.example`).

| Var | Required | Purpose |
|---|---|---|
| `BOT_TOKEN` | yes | Telegram Bot API token |
| `DB_PATH` | no | SQLite file location (default `bot.db`) |
| `DEFAULT_LANG` | no | Locale for new users: `ru` \| `en` \| `uk` |
| `KODIK_TOKEN` | no | Enables in-Telegram episode player + Kodik scheduler probe. Register free at https://kodik.cc/ |

## Commands

| Command | Effect |
|---|---|
| `/start` | Welcome + language picker + persistent menu |
| `/help` | Full command reference |
| `/lang` | Switch UI language |
| `/search <query>` | Search anime |
| `/subs` | List subscriptions |
| `/history` | Last 10 search queries |
| `/donate` | Support the bot via Telegram Stars |
| any text | Same as `/search` |
| `@bot query` | Inline mode in any chat |

## License

MIT — see LICENSE. Third-party API terms apply to Jikan / AniList /
Shikimori / Anilibria / Kodik.
