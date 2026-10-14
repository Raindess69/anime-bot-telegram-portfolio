import asyncio
import logging

from models import AnimeCard
from utils.cache import search_cache

from . import anilibria, anilist, jikan, kodik, shikimori, yummy

_log = logging.getLogger(__name__)

MAX_RESULTS = 10

# Ukrainian → Russian-ish char substitution. Ukrainian anime titles are usually
# just Russian titles with a few letters swapped, so this hits Shikimori's
# fuzzy search well enough without needing a real translator.
_UK_TO_RU_LIKE = str.maketrans({
    "і": "и", "І": "И",
    "ї": "и", "Ї": "И",
    "є": "е", "Є": "Е",
    "ґ": "г", "Ґ": "Г",
    "'": "", "ʼ": "", "’": "",
})


def _uk_to_ru_like(text: str) -> str:
    return (text or "").translate(_UK_TO_RU_LIKE)


async def top_anime_multi(filter_: str | None, type_: str | None, limit: int) -> list[dict]:
    """Top charts with source fallback: Jikan → AniList → Shikimori.

    Jikan (MAL) sometimes disconnects mid-response; when it does, retries in
    jikan._get_with_retry give up and return []. Rather than showing an empty
    top list, we roll to the next source. Each source parses into the same
    dict shape ({mal_id, title_en, title_ru?, score, ...}) so callers can
    consume them uniformly.
    """
    for source_name, fn in (
        ("jikan", lambda: jikan.top_anime(filter_=filter_, type_=type_, limit=limit)),
        ("anilist", lambda: anilist.top_anime(filter_=filter_, type_=type_, limit=limit)),
        ("shikimori", lambda: shikimori.top_anime(filter_=filter_, type_=type_, limit=limit)),
    ):
        try:
            result = await fn()
        except Exception as e:
            _log.info("Top source %s crashed: %s", source_name, e)
            continue
        if result:
            _log.info("Top served from %s (%d items)", source_name, len(result))
            return result
        _log.info("Top source %s returned empty — trying next", source_name)
    return []


async def random_anime() -> dict | None:
    """Random anime with source fallback: Shikimori → Jikan → AniList.

    Shikimori provides fast, localized random picks. If it fails, we fall back
    to Jikan or AniList.
    """
    for source_name, fn in (
        ("shikimori", lambda: shikimori.random_anime()),
        ("jikan", lambda: jikan.random_anime()),
        ("anilist", lambda: anilist.random_anime()),
    ):
        try:
            result = await fn()
        except Exception as e:
            _log.info("Random source %s crashed: %s", source_name, e)
            continue
        if result:
            _log.info("Random served from %s", source_name)
            return result
        _log.info("Random source %s returned None — trying next", source_name)
    return None


async def vibe_search(
    *,
    min_score: float | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    genre_slug: str | None = None,
    type_: str | None = None,
    min_results: int = 5,
    limit: int = 10,
) -> tuple[list[dict], bool]:
    """Vibe pick with progressive filter relaxation across Jikan + AniList.

    Each pass fans out to both sources in parallel and merges by mal_id. If the
    merged set has fewer than `min_results`, we drop one filter and try again:
    type → score → year → genre. Returns (results, relaxed) — `relaxed=True`
    lets the UI hint that we widened the search.
    """
    genre_id = jikan.GENRES.get(genre_slug) if genre_slug else None

    passes = [
        (min_score, year_from, year_to, genre_slug, genre_id, type_),
        # Drop format first — it's the tightest gate (movie/OVA excludes 90% of catalog).
        (min_score, year_from, year_to, genre_slug, genre_id, None),
        # Then loosen the score bar.
        (None, year_from, year_to, genre_slug, genre_id, None),
        # Then widen the era.
        (None, None, None, genre_slug, genre_id, None),
        # Last-resort — drop the genre.
        (None, None, None, None, None, None),
    ]

    relaxed = False
    fallback: list[dict] = []
    for ms, yf, yt, gs, gi, tp in passes:
        results = await _vibe_fanout(
            min_score=ms, year_from=yf, year_to=yt,
            genre_slug=gs, genre_id=gi, type_=tp, limit=limit,
        )
        if len(results) >= min_results:
            return results, relaxed
        if len(results) > len(fallback):
            fallback = results
        relaxed = True
    return fallback, relaxed


async def _vibe_fanout(
    *,
    min_score: float | None,
    year_from: int | None,
    year_to: int | None,
    genre_slug: str | None,
    genre_id: int | None,
    type_: str | None,
    limit: int,
) -> list[dict]:
    """One relaxation-pass: hit Shikimori + Jikan + AniList in parallel and merge."""
    async def _shikimori() -> list[dict]:
        try:
            return await shikimori.search_advanced(
                min_score=min_score, year_from=year_from, year_to=year_to,
                genre_id=genre_id, type_=type_, limit=limit,
            )
        except Exception as e:
            _log.info("Shikimori vibe search failed: %s", e)
            return []

    async def _jikan() -> list[dict]:
        try:
            return await jikan.search_advanced(
                min_score=min_score, year_from=year_from, year_to=year_to,
                genre_id=genre_id, type_=type_, limit=limit,
            )
        except Exception as e:
            _log.info("Jikan vibe search failed: %s", e)
            return []

    async def _anilist() -> list[dict]:
        try:
            return await anilist.search_advanced(
                min_score=min_score, year_from=year_from, year_to=year_to,
                genre_slug=genre_slug, type_=type_, limit=limit,
            )
        except Exception as e:
            _log.info("AniList vibe search failed: %s", e)
            return []

    s, j, a = await asyncio.gather(_shikimori(), _jikan(), _anilist())
    return _merge_by_mal(s, j, a, limit=limit)


def _merge_by_mal(*sources: list[dict], limit: int) -> list[dict]:
    """Merge sources by mal_id, keep the source-1 slot but fill blanks from later."""
    merged: dict[str, dict] = {}
    order: list[str] = []
    for src in sources:
        for item in src or []:
            key = str(item.get("mal_id") or item.get("shikimori_id") or (item.get("title_en") or "").lower())
            if not key or key == "None":
                continue
            if key in merged:
                for k, v in item.items():
                    if v not in (None, "", [], {}) and merged[key].get(k) in (None, "", [], {}):
                        merged[key][k] = v
                continue
            merged[key] = dict(item)
            order.append(key)
    items = [merged[k] for k in order]
    items.sort(key=lambda x: (x.get("score") or 0), reverse=True)
    return items[:limit]


async def seasonal_multi(year: int, season: str, limit: int) -> list[dict]:
    for source_name, fn in (
        ("jikan", lambda: jikan.seasonal(year, season, limit=limit)),
        ("anilist", lambda: anilist.seasonal(year, season, limit=limit)),
        ("shikimori", lambda: shikimori.seasonal(year, season, limit=limit)),
    ):
        try:
            result = await fn()
        except Exception as e:
            _log.info("Seasonal source %s crashed: %s", source_name, e)
            continue
        if result:
            _log.info("Seasonal served from %s (%d items)", source_name, len(result))
            return result
    return []


async def search_anime(query: str, lang: str) -> list[AnimeCard]:
    query = (query or "").strip()
    if not query:
        return []

    cache_key = f"{lang}:{query.lower()}"

    async def _compute():
        if lang == "ru":
            cards = await _search_ru(query)
        elif lang == "uk":
            cards = await _search_uk(query)
        else:
            cards = await _search_en(query)

        cards = cards[:MAX_RESULTS]
        await _enrich_watch_links(cards, lang)
        return cards

    return await search_cache.get_or_compute(cache_key, _compute)


async def _search_all_sources(queries: list[str]) -> dict[str, list[dict]]:
    """Fan out every query across Shikimori/Jikan/AniList in parallel.

    Returns {source_name: results}. Source is queried once per query string —
    a UK translit + original UK, or a RU + JP romaji, etc.
    """
    async def _many(fn, name: str) -> list[dict]:
        merged: list[dict] = []
        seen: set = set()
        results = await asyncio.gather(
            *(fn(q, limit=MAX_RESULTS) for q in queries),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception) or not r:
                continue
            for item in r:
                key = item.get("mal_id") or item.get("shikimori_id") or (item.get("title_en") or "").lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(item)
        return merged

    shiki_task = _many(shikimori.search, "shikimori")
    jikan_task = _many(jikan.search, "jikan")
    anilist_task = _many(anilist.search, "anilist")
    shiki_r, jikan_r, anilist_r = await asyncio.gather(shiki_task, jikan_task, anilist_task)
    return {"shikimori": shiki_r, "jikan": jikan_r, "anilist": anilist_r}


def _merge_ranked(source_order: list[list[dict]]) -> list[AnimeCard]:
    """Merge items keyed by mal_id (fallback shikimori_id / title). Earlier
    sources win the slot; later sources only fill missing fields. Preserves
    the first-source ranking, so language-appropriate hits stay on top."""
    merged: dict[str, dict] = {}
    order: list[str] = []
    for source_items in source_order:
        for item in source_items:
            key = str(item.get("mal_id") or item.get("shikimori_id") or (item.get("title_en") or "").lower())
            if not key or key == "None":
                continue
            if key in merged:
                # Fill blanks from later sources — e.g. shikimori has title_ru,
                # jikan brings title_en if the first hit didn't.
                for k, v in item.items():
                    if v not in (None, "", [], {}) and merged[key].get(k) in (None, "", [], {}):
                        merged[key][k] = v
                continue
            merged[key] = dict(item)
            order.append(key)
    items = [merged[k] for k in order][:MAX_RESULTS]
    return [AnimeCard(**{k: v for k, v in x.items() if v is not None}) for x in items]


async def _search_ru(query: str) -> list[AnimeCard]:
    sources = await _search_all_sources([query])
    # Priority for RU users: shikimori (RU titles) → jikan → anilist.
    return _merge_ranked([sources["shikimori"], sources["jikan"], sources["anilist"]])


async def _search_uk(query: str) -> list[AnimeCard]:
    """UK: same wide net as RU, plus a translit variant so і/ї/є don't tank recall."""
    queries = [query]
    alt = _uk_to_ru_like(query)
    if alt and alt != query:
        queries.append(alt)
    sources = await _search_all_sources(queries)
    return _merge_ranked([sources["shikimori"], sources["jikan"], sources["anilist"]])


async def _search_en(query: str) -> list[AnimeCard]:
    sources = await _search_all_sources([query])
    # Priority for EN users: jikan (MAL) → anilist → shikimori (still useful
    # when the user typed romaji or the JP native title).
    return _merge_ranked([sources["jikan"], sources["anilist"], sources["shikimori"]])


async def _enrich_watch_links(cards: list[AnimeCard], lang: str) -> None:
    if not cards:
        return

    # For ru/uk, run Shikimori backfill first: it fills title_ru (needed by
    # Yummy) AND shikimori_id (needed by Kodik search when a card lacks
    # mal_id — happens for shikimori-only hits on odd titles).
    if lang in ("ru", "uk"):
        await _fill_ru_titles(cards)

    # Crunchyroll + Kodik enrichment runs for every language. Batched AniList
    # GraphQL for Crunchyroll (one round-trip); per-card Kodik search (no-op
    # when KODIK_TOKEN unset).
    await _fill_streaming_links(cards)

    # Anilibria/Yummy are Russian sites; Ukrainian users should still see them.
    # For EN we skip this branch entirely — enrichment above already ran.
    if lang not in ("ru", "uk"):
        return

    async def _anilibria(card: AnimeCard):
        title = card.title_ru or card.title_en
        if not title:
            return
        # Also pass the English/Japanese titles — the search on the RU side
        # sometimes returns fuzzy garbage (e.g. "Ao Ashi" → "Midara na Ao-chan"),
        # so we let find_release cross-check candidates against every known title.
        extras = [t for t in (card.title_en, card.title_jp) if t and t != title]
        try:
            release = await anilibria.find_release(title, extra_queries=extras)
            if release and release.get("code") and release.get("url"):
                card.anilibria_code = release["code"]
                card.anilibria_url = release["url"]
                card.episodes_available = release.get("episodes") or []
                card.episode_uuids = release.get("episode_ids") or {}
                card.torrents = release.get("torrents") or []
        except Exception as e:
            _log.info("Anilibria enrich failed: %s", e)

    async def _yummy(card: AnimeCard):
        title = card.title_ru or card.title_en
        if not title:
            return
        try:
            direct = await yummy.find_direct_link(
                title, title_ru=card.title_ru, title_en=card.title_en
            )
            if direct:
                card.yummy_url = direct
        except Exception as e:
            _log.info("Yummy enrich failed: %s", e)

    tasks: list = []
    for c in cards:
        tasks.append(_anilibria(c))
        tasks.append(_yummy(c))
    await asyncio.gather(*tasks, return_exceptions=True)


async def _fill_streaming_links(cards: list[AnimeCard]) -> None:
    """Populate crunchyroll_url + kodik player for every card.

    AniList's externalLinks is a batched GraphQL call — one round-trip for all
    10 cards. Kodik has no batch endpoint, so we fan-out per-card; the token
    check keeps it a no-op when KODIK_TOKEN isn't set.
    """
    mal_ids = [c.mal_id for c in cards if c.mal_id]
    if mal_ids:
        try:
            streams = await anilist.get_streams_by_mal(mal_ids)
        except Exception as e:
            _log.info("AniList streams enrich failed: %s", e)
            streams = {}
        for card in cards:
            if not card.mal_id:
                continue
            links = streams.get(card.mal_id) or {}
            cr = links.get("crunchyroll")
            if cr:
                card.crunchyroll_url = cr

    if kodik.enabled():
        async def _kodik(card: AnimeCard):
            if not (card.mal_id or card.shikimori_id):
                return
            try:
                player = await kodik.get_player(
                    mal_id=card.mal_id, shikimori_id=card.shikimori_id,
                )
            except Exception as e:
                _log.info("Kodik player enrich failed: %s", e)
                return
            if not player:
                return
            card.kodik_url = player["url"]
            card.kodik_episodes = player["episodes"]
            card.kodik_last_ep = player["last_ep"] or None
            card.kodik_translation = player["translation"] or None

        await asyncio.gather(*(_kodik(c) for c in cards), return_exceptions=True)


async def _fill_ru_titles(cards: list[AnimeCard]) -> None:
    """For cards without title_ru, look them up on Shikimori by English title."""
    async def _fetch(card: AnimeCard):
        if card.title_ru or not card.title_en:
            return
        try:
            items = await shikimori.search(card.title_en, limit=1)
        except Exception as e:
            _log.info("Shikimori translation lookup failed for %r: %s", card.title_en, e)
            return
        if not items:
            return
        item = items[0]
        card.title_ru = item.get("title_ru") or card.title_ru
    await asyncio.gather(*(_fetch(c) for c in cards), return_exceptions=True)


async def get_recommendations(
    *,
    genre_slug: str | None = None,
    exclude_mal_ids: set[int] | None = None,
    limit: int = 10,
    seed_title: str | None = None,
) -> list[dict]:
    """Generates verifiable genre/theme recommendations with reasons and stable sorting.

    Guarantees:
    - Zero hallucinated titles (sourced directly from verified upstream APIs).
    - Stable sorting by score descending.
    - Excludes completed/dropped titles when requested.
    - Provides explicit explanation for each recommendation.
    """
    from utils.cache import vibe_cache

    exclude = exclude_mal_ids or set()
    candidates, _ = await vibe_search(
        min_score=7.0,
        genre_slug=genre_slug,
        limit=limit * 2,
    )

    filtered = []
    for item in candidates:
        mid = item.get("mal_id")
        if mid and mid in exclude:
            continue
        score = item.get("score") or "7.5+"
        if seed_title:
            reason = f"Похоже на «{seed_title}»"
        elif genre_slug:
            reason = f"Топ жанра #{genre_slug} (рейтинг {score})"
        else:
            reason = f"Высокий рейтинг зрителей (оценка {score})"

        item_copy = dict(item)
        item_copy["recommendation_reason"] = reason
        filtered.append(item_copy)
        if len(filtered) >= limit:
            break

    filtered.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    return filtered
