import asyncio
import logging

import httpx

BASE_URL = "https://api.jikan.moe/v4"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_RETRIES = 3
_RETRY_DELAY = 0.8
_log = logging.getLogger(__name__)

# MAL genre IDs — kept static so we don't hit /genres/anime each time.
# Curated set covering the most-requested tastes for the "vibe pick" wizard.
GENRES: dict[str, int] = {
    "action": 1,
    "adventure": 2,
    "comedy": 4,
    "drama": 8,
    "fantasy": 10,
    "horror": 14,
    "mystery": 7,
    "romance": 22,
    "sci_fi": 24,
    "slice_of_life": 36,
    "sports": 30,
    "supernatural": 37,
    "thriller": 41,
    "psychological": 40,
    "mecha": 18,
    "music": 19,
}

VALID_TOP_FILTERS = ("airing", "upcoming", "bypopularity", "favorite")
VALID_TYPES = ("tv", "movie", "ova", "special", "ona")
VALID_SEASONS = ("winter", "spring", "summer", "fall")


async def _get_with_retry(client: httpx.AsyncClient, url: str, params: dict | None = None) -> httpx.Response | None:
    last_exc: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            resp = await client.get(url, params=params)
            if resp.status_code >= 500 or resp.status_code == 429:
                _log.info("Jikan %s returned %s (attempt %s/%s)", url, resp.status_code, attempt + 1, _RETRIES)
                last_exc = httpx.HTTPStatusError("retry", request=resp.request, response=resp)
                await asyncio.sleep(_RETRY_DELAY * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_exc = e
            _log.info("Jikan %s network error (attempt %s/%s): %s", url, attempt + 1, _RETRIES, e)
            await asyncio.sleep(_RETRY_DELAY * (attempt + 1))
        except httpx.HTTPError as e:
            last_exc = e
            break
    _log.warning("Jikan %s failed after %s attempts: %s", url, _RETRIES, last_exc)
    return None


async def search(query: str, limit: int = 10) -> list[dict]:
    if not query:
        return []
    params = {"q": query, "limit": limit, "sfw": "true"}
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await _get_with_retry(client, f"{BASE_URL}/anime", params=params)
        if resp is None:
            return []
        data = resp.json().get("data", [])
    return [_parse_item(x) for x in data if x]


async def search_advanced(
    *,
    min_score: float | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    genre_id: int | None = None,
    type_: str | None = None,
    limit: int = 10,
    order_by: str = "score",
    sort: str = "desc",
) -> list[dict]:
    params: dict[str, str | int | float] = {
        "limit": limit,
        "sfw": "true",
        "order_by": order_by,
        "sort": sort,
    }
    if min_score is not None:
        params["min_score"] = min_score
    if year_from is not None:
        params["start_date"] = f"{year_from}-01-01"
    if year_to is not None:
        params["end_date"] = f"{year_to}-12-31"
    if genre_id is not None:
        params["genres"] = genre_id
    if type_ and type_ in VALID_TYPES:
        params["type"] = type_

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await _get_with_retry(client, f"{BASE_URL}/anime", params=params)
        if resp is None:
            return []
        data = resp.json().get("data", [])
    return [_parse_item(x) for x in data if x]


async def top_anime(filter_: str | None = None, type_: str | None = None, limit: int = 10) -> list[dict]:
    params: dict[str, str | int] = {"limit": limit, "sfw": "true"}
    if filter_ and filter_ in VALID_TOP_FILTERS:
        params["filter"] = filter_
    if type_ and type_ in VALID_TYPES:
        params["type"] = type_
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await _get_with_retry(client, f"{BASE_URL}/top/anime", params=params)
        if resp is None:
            return []
        data = resp.json().get("data", [])
    return [_parse_item(x) for x in data if x]


async def seasonal(year: int, season: str, limit: int = 10) -> list[dict]:
    if season not in VALID_SEASONS:
        return []
    params = {"limit": limit, "sfw": "true"}
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await _get_with_retry(client, f"{BASE_URL}/seasons/{year}/{season}", params=params)
        if resp is None:
            return []
        data = resp.json().get("data", [])
    parsed = [_parse_item(x) for x in data if x]
    parsed.sort(key=lambda a: (a.get("score") or 0), reverse=True)
    return parsed[:limit]


async def random_anime() -> dict | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await _get_with_retry(client, f"{BASE_URL}/random/anime")
        if resp is None:
            return None
        data = resp.json().get("data")
    return _parse_item(data) if data else None


async def get_by_id(mal_id: int) -> dict | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await _get_with_retry(client, f"{BASE_URL}/anime/{mal_id}/full")
        if resp is None:
            return None
        data = resp.json().get("data")
    return _parse_item(data) if data else None


def _parse_item(raw: dict) -> dict:
    images = raw.get("images") or {}
    jpg = images.get("jpg") or {}

    year = raw.get("year")
    if not year:
        aired = raw.get("aired") or {}
        prop = aired.get("prop") or {}
        from_year = (prop.get("from") or {}).get("year")
        year = from_year

    titles = {t.get("type"): t.get("title") for t in raw.get("titles", []) if t}
    title_en = titles.get("English") or raw.get("title_english") or raw.get("title")
    title_jp = titles.get("Japanese") or raw.get("title_japanese")

    return {
        "mal_id": raw.get("mal_id"),
        "title_en": title_en,
        "title_jp": title_jp,
        "score": raw.get("score"),
        "episodes": raw.get("episodes"),
        "status": raw.get("status"),
        "genres": [g.get("name") for g in raw.get("genres", []) if g and g.get("name")],
        "year": year,
        "synopsis_en": raw.get("synopsis"),
        "image_url": jpg.get("large_image_url") or jpg.get("image_url"),
        "mal_url": raw.get("url"),
    }
