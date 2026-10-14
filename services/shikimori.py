import logging

import httpx

BASE_URL = "https://shikimori.io/api"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_HEADERS = {"User-Agent": "AnimeSearchBot/1.0 (Telegram)"}
_log = logging.getLogger(__name__)


async def _get(
    path: str,
    params: dict | None = None,
    timeout: float | httpx.Timeout | None = None,
    max_retries: int = 1,
) -> httpx.Response:
    from services.http_client import request_with_retry
    return await request_with_retry(
        "GET",
        f"{BASE_URL}{path}",
        params=params,
        timeout=timeout,
        max_retries=max_retries,
    )


def _norm_str(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return str(value) if value else None


async def search(query: str, limit: int = 10, timeout: float = 5.0) -> list[dict]:
    if not query:
        return []
    params = {"search": query, "limit": limit}
    try:
        resp = await _get("/animes", params=params, timeout=timeout, max_retries=1)
        resp.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        _log.warning("Shikimori search failed: %s", e)
        return []
    items = resp.json()
    return [_parse_short(x) for x in items if x]


_KIND_MAP = {"tv": "tv", "movie": "movie", "ova": "ova", "special": "special", "ona": "ona"}


async def top_anime(
    filter_: str | None = None,
    type_: str | None = None,
    limit: int = 10,
    timeout: float = 4.0,
) -> list[dict]:
    """Top-charts fallback via Shikimori /animes with order/status params."""
    fetch_limit = min(limit * 3, 50)
    params: dict[str, str | int] = {"limit": fetch_limit, "order": "ranked", "censored": "true"}
    if filter_ == "airing":
        params["status"] = "ongoing"
        params["order"] = "popularity"
    elif filter_ == "upcoming":
        params["status"] = "anons"
    elif filter_ == "bypopularity":
        params["order"] = "popularity"
    if type_ and type_ in _KIND_MAP:
        params["kind"] = _KIND_MAP[type_]
    try:
        resp = await _get("/animes", params=params, timeout=timeout, max_retries=1)
        resp.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        _log.info("Shikimori top failed: %s", e)
        return []
    items = resp.json() or []
    valid = [
        _parse_short(x)
        for x in items
        if x and x.get("image", {}).get("original") and "missing" not in x.get("image", {}).get("original")
    ]
    return valid[:limit]


async def seasonal(year: int, season: str, limit: int = 10, timeout: float = 4.0) -> list[dict]:
    if season not in ("winter", "spring", "summer", "fall"):
        return []
    fetch_limit = min(limit * 3, 50)
    params = {"limit": fetch_limit, "season": f"{season}_{year}", "order": "popularity", "censored": "true"}
    try:
        resp = await _get("/animes", params=params, timeout=timeout, max_retries=1)
        resp.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        _log.info("Shikimori seasonal failed: %s", e)
        return []
    items = resp.json() or []
    valid = [
        _parse_short(x)
        for x in items
        if x and x.get("image", {}).get("original") and "missing" not in x.get("image", {}).get("original")
    ]
    return valid[:limit]


async def search_advanced(
    *,
    min_score: float | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    genre_id: int | None = None,
    type_: str | None = None,
    limit: int = 10,
) -> list[dict]:
    fetch_limit = min(limit * 3, 50)
    params: dict[str, str | int] = {
        "limit": fetch_limit,
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

    try:
        resp = await _get("/animes", params=params, timeout=5.0, max_retries=1)
        resp.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        _log.info("Shikimori search_advanced failed: %s", e)
        return []
    items = resp.json() or []
    valid = [
        _parse_short(x)
        for x in items
        if x and x.get("image", {}).get("original") and "missing" not in x.get("image", {}).get("original")
    ]
    return valid[:limit]


async def random_anime(timeout: float = 5.0) -> dict | None:
    params: dict[str, str | int] = {
        "order": "random",
        "limit": 1,
        "score": 6,
        "censored": "true",
    }
    try:
        resp = await _get("/animes", params=params, timeout=timeout, max_retries=1)
        resp.raise_for_status()
        items = resp.json() or []
        if not items:
            return None
        item = items[0]
        shiki_id = item.get("id")
        if shiki_id:
            full = await get_by_id(shiki_id, timeout=timeout)
            if full:
                return full
        return _parse_short(item)
    except Exception as e:
        _log.info("Shikimori random failed: %s", e)
        return None


async def get_by_id(shikimori_id: int, timeout: float = 6.0) -> dict | None:
    try:
        resp = await _get(f"/animes/{shikimori_id}", timeout=timeout, max_retries=1)
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


FALLBACK_POSTER_SVG = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='300' height='450' viewBox='0 0 300 450'>"
    "<defs><linearGradient id='g' x1='0%' y1='0%' x2='100%' y2='100%'>"
    "<stop offset='0%' stop-color='%23181825'/><stop offset='50%' stop-color='%2311111b'/><stop offset='100%' stop-color='%230b0b12'/>"
    "</linearGradient></defs>"
    "<rect width='100%' height='100%' fill='url(%23g)'/>"
    "<circle cx='150' cy='200' r='42' fill='%236366f1' fill-opacity='0.25' stroke='%23818cf8' stroke-width='1.5'/>"
    "<polygon points='142,185 166,200 142,215' fill='%23ffffff'/>"
    "<text x='150' y='275' font-family='sans-serif' font-size='13' font-weight='800' fill='%2394a3b8' text-anchor='middle' letter-spacing='3'>ENJOYANIME</text>"
    "</svg>"
)


def _clean_bbcode(text: str | None) -> str | None:
    if not text:
        return text
    import re
    # Strip BBCode tags like [character=7407]...[/character], [anime=...], [b], etc.
    cleaned = re.sub(r"\[/?[a-zA-Z0-9_-]+(?:=[^\]]*)?\]", "", text)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"\r\n", "\n", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


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
        "synopsis_ru": _clean_bbcode(raw.get("description") or raw.get("description_html")),
        "image_url": _image_url(raw),
    }


def _image_url(raw: dict) -> str:
    image = raw.get("image") or {}
    url = image.get("original") or image.get("preview")
    if not url or "missing" in url or "globals" in url:
        return FALLBACK_POSTER_SVG
    if url.startswith("https://shikimori.one/"):
        return "https://shikimori.io/" + url[len("https://shikimori.one/"):]
    if url.startswith("http://shikimori.one/"):
        return "https://shikimori.io/" + url[len("http://shikimori.one/"):]
    if url.startswith("http"):
        return url
    return f"https://shikimori.io{url}"
