import logging

import httpx

BASE_URL = "https://shikimori.io/api"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_HEADERS = {"User-Agent": "AnimeSearchBot/1.0 (Telegram)"}
_log = logging.getLogger(__name__)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True)


def _norm_str(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return str(value) if value else None


async def search(query: str, limit: int = 10) -> list[dict]:
    if not query:
        return []
    params = {"search": query, "limit": limit}
    async with _client() as client:
        try:
            resp = await client.get(f"{BASE_URL}/animes", params=params)
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.warning("Shikimori search failed: %s", e)
            return []
        items = resp.json()
    return [_parse_short(x) for x in items if x]


_KIND_MAP = {"tv": "tv", "movie": "movie", "ova": "ova", "special": "special", "ona": "ona"}


async def top_anime(filter_: str | None = None, type_: str | None = None, limit: int = 10) -> list[dict]:
    """Top-charts fallback via Shikimori /animes with order/status params."""
    params: dict[str, str | int] = {"limit": limit, "order": "ranked", "censored": "true"}
    if filter_ == "airing":
        params["status"] = "ongoing"
    elif filter_ == "upcoming":
        params["status"] = "anons"
    elif filter_ == "bypopularity":
        params["order"] = "popularity"
    if type_ and type_ in _KIND_MAP:
        params["kind"] = _KIND_MAP[type_]
    async with _client() as client:
        try:
            resp = await client.get(f"{BASE_URL}/animes", params=params)
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.info("Shikimori top failed: %s", e)
            return []
        items = resp.json() or []
    return [_parse_short(x) for x in items if x]


async def seasonal(year: int, season: str, limit: int = 10) -> list[dict]:
    if season not in ("winter", "spring", "summer", "fall"):
        return []
    params = {"limit": limit, "season": f"{season}_{year}", "order": "popularity", "censored": "true"}
    async with _client() as client:
        try:
            resp = await client.get(f"{BASE_URL}/animes", params=params)
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.info("Shikimori seasonal failed: %s", e)
            return []
        items = resp.json() or []
    return [_parse_short(x) for x in items if x]


async def search_advanced(
    *,
    min_score: float | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    genre_id: int | None = None,
    type_: str | None = None,
    limit: int = 10,
) -> list[dict]:
    params: dict[str, str | int] = {
        "limit": limit,
        "order": "popularity",
        "censored": "true",
    }
    if min_score is not None:
        params["score"] = int(min_score)
    if genre_id is not None:
        params["genre"] = genre_id
    if type_ and type_ in _KIND_MAP:
        params["kind"] = _KIND_MAP[type_]

    if year_from and year_to:
        if year_from == year_to:
            params["season"] = str(year_from)
        else:
            params["season"] = f"{year_from}_{year_to}"
    elif year_from:
        params["season"] = f"{year_from}_2026"
    elif year_to:
        params["season"] = f"1970_{year_to}"

    async with _client() as client:
        try:
            resp = await client.get(f"{BASE_URL}/animes", params=params)
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.info("Shikimori search_advanced failed: %s", e)
            return []
        items = resp.json() or []
    return [_parse_short(x) for x in items if x]


async def random_anime() -> dict | None:
    params: dict[str, str | int] = {
        "order": "random",
        "limit": 1,
        "score": 6,
        "censored": "true",
    }
    async with _client() as client:
        try:
            resp = await client.get(f"{BASE_URL}/animes", params=params)
            resp.raise_for_status()
            items = resp.json() or []
            if not items:
                return None
            item = items[0]
            shiki_id = item.get("id")
            if shiki_id:
                full = await get_by_id(shiki_id)
                if full:
                    return full
            return _parse_short(item)
        except Exception as e:
            _log.info("Shikimori random failed: %s", e)
            return None


async def get_by_id(shikimori_id: int) -> dict | None:
    async with _client() as client:
        try:
            resp = await client.get(f"{BASE_URL}/animes/{shikimori_id}")
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.warning("Shikimori get_by_id(%s) failed: %s", shikimori_id, e)
            return None
        raw = resp.json()
    return _parse_full(raw)


def _year_from_date(date_str) -> int | None:
    if not date_str or not isinstance(date_str, str) or len(date_str) < 4:
        return None
    try:
        return int(date_str[:4])
    except ValueError:
        return None


def _parse_short(raw: dict) -> dict:
    return {
        "shikimori_id": raw.get("id"),
        "mal_id": raw.get("id"),
        "title_ru": _norm_str(raw.get("russian")) or _norm_str(raw.get("name")),
        "title_en": _norm_str(raw.get("name")),
        "score": float(raw["score"]) if raw.get("score") else None,
        "episodes": raw.get("episodes") or None,
        "status": raw.get("status"),
        "year": _year_from_date(raw.get("aired_on")),
        "image_url": _image_url(raw),
    }


def _parse_full(raw: dict) -> dict:
    return {
        "shikimori_id": raw.get("id"),
        "mal_id": raw.get("id"),
        "title_ru": _norm_str(raw.get("russian")) or _norm_str(raw.get("name")),
        "title_en": _norm_str(raw.get("name")),
        "title_jp": _norm_str(raw.get("japanese")),
        "score": float(raw["score"]) if raw.get("score") else None,
        "episodes": raw.get("episodes") or None,
        "status": raw.get("status"),
        "genres": [_norm_str(g.get("russian")) or _norm_str(g.get("name")) for g in raw.get("genres", []) if g],
        "year": _year_from_date(raw.get("aired_on")),
        "synopsis_ru": raw.get("description") or raw.get("description_html"),
        "image_url": _image_url(raw),
    }


def _image_url(raw: dict) -> str | None:
    image = raw.get("image") or {}
    url = image.get("original") or image.get("preview")
    if not url:
        return "https://shikimori.io/assets/globals/missing_original.jpg"
    if url.startswith("http"):
        return url
    return f"https://shikimori.io{url}"
