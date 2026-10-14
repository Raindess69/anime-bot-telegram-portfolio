import asyncio
import itertools
import logging

import httpx

from config import settings

BASE_URL = "https://api.jikan.moe/v4"
_TIMEOUT = httpx.Timeout(3.0, connect=1.5)
_RETRIES = 1
_RETRY_DELAY = 0.5
_log = logging.getLogger(__name__)


def _build_proxy_pool() -> list[str]:
    pool: list[str] = []
    for entry in settings.jikan_proxies.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) == 4:
            host, port, user, pwd = parts
            pool.append(f"http://{user}:{pwd}@{host}:{port}")
        else:
            pool.append(entry)  # assume it's already a full proxy URL
    return pool


_PROXY_POOL = _build_proxy_pool()
_proxy_cycle = itertools.cycle(_PROXY_POOL) if _PROXY_POOL else None


def _next_proxy() -> str | None:
    return next(_proxy_cycle) if _proxy_cycle else None


def _mask_proxy(proxy: str | None) -> str:
    if not proxy:
        return "direct"
    return proxy.rsplit("@", 1)[-1]  # drop user:pass, keep host:port


def _make_client(proxy: str | None) -> httpx.AsyncClient:
    kwargs: dict = {"timeout": _TIMEOUT, "follow_redirects": True}
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.AsyncClient(**kwargs)

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


async def _get_with_retry(url: str, params: dict | None = None) -> httpx.Response | None:
    """Each attempt gets a fresh client on the next proxy in the pool (round-robin).
    If no proxies are configured, returns None immediately so fallback sources take over."""
    if not _PROXY_POOL:
        return None
    last_exc: Exception | None = None
    for attempt in range(_RETRIES):
        proxy = _next_proxy()
        try:
            async with _make_client(proxy) as client:
                resp = await client.get(url, params=params)
            if resp.status_code >= 500 or resp.status_code == 429:
                _log.info(
                    "Jikan %s returned %s via %s (attempt %s/%s)",
                    url, resp.status_code, _mask_proxy(proxy), attempt + 1, _RETRIES,
                )
                last_exc = httpx.HTTPStatusError("retry", request=resp.request, response=resp)
                await asyncio.sleep(_RETRY_DELAY * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_exc = e
            _log.debug(
                "Jikan %s network error via %s (attempt %s/%s): %s",
                url, _mask_proxy(proxy), attempt + 1, _RETRIES, e,
            )
            await asyncio.sleep(_RETRY_DELAY * (attempt + 1))
        except httpx.HTTPError as e:
            last_exc = e
            break
    _log.debug("Jikan %s failed after %s attempts: %s", url, _RETRIES, last_exc)
    return None


async def search(query: str, limit: int = 10) -> list[dict]:
    if not query:
        return []
    params = {"q": query, "limit": limit, "sfw": "true"}
    resp = await _get_with_retry(f"{BASE_URL}/anime", params=params)
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

    resp = await _get_with_retry(f"{BASE_URL}/anime", params=params)
    if resp is None:
        return []
    data = resp.json().get("data", [])
    return [_parse_item(x) for x in data if x]


async def top_anime(
    filter_: str | None = None,
    type_: str | None = None,
    limit: int = 10,
    page: int = 1,
) -> list[dict]:
    params: dict[str, str | int] = {"limit": limit, "page": page, "sfw": "true"}
    if filter_ and filter_ in VALID_TOP_FILTERS:
        params["filter"] = filter_
    if type_ and type_ in VALID_TYPES:
        params["type"] = type_
    resp = await _get_with_retry(f"{BASE_URL}/top/anime", params=params)
    if resp is None:
        return []
    data = resp.json().get("data", [])
    return [_parse_item(x) for x in data if x]


async def seasonal(year: int, season: str, limit: int = 10) -> list[dict]:
    if season not in VALID_SEASONS:
        return []
    params = {"limit": limit, "sfw": "true"}
    resp = await _get_with_retry(f"{BASE_URL}/seasons/{year}/{season}", params=params)
    if resp is None:
        return []
    data = resp.json().get("data", [])
    parsed = [_parse_item(x) for x in data if x]
    parsed.sort(key=lambda a: (a.get("score") or 0), reverse=True)
    return parsed[:limit]


_EXPLICIT_TAGS = {"hentai", "erotica"}


def _is_unsafe(raw: dict) -> bool:
    """/random/anime has no `sfw` param (Jikan doesn't support it there), so we
    filter client-side: reject Rx-rated titles and Hentai/Erotica genre/demographic tags."""
    rating = (raw.get("rating") or "").lower()
    if rating.startswith("rx"):
        return True
    tags = (raw.get("genres") or []) + (raw.get("demographics") or [])
    return any(isinstance(g, dict) and (g.get("name") or "").lower() in _EXPLICIT_TAGS for g in tags)


async def random_anime(*, max_attempts: int = 5) -> dict | None:
    for _ in range(max_attempts):
        resp = await _get_with_retry(f"{BASE_URL}/random/anime")
        if resp is None:
            return None
        data = resp.json().get("data")
        if not data or _is_unsafe(data):
            continue
        return _parse_item(data)
    return None


async def get_by_id(mal_id: int) -> dict | None:
    resp = await _get_with_retry(f"{BASE_URL}/anime/{mal_id}/full")
    if resp is not None:
        data = resp.json().get("data")
        if data:
            return _parse_item(data)
    from . import anilist
    return await anilist.get_by_mal(mal_id)


async def get_recommendations(mal_id: int, limit: int = 10) -> list[dict]:
    resp = await _get_with_retry(f"{BASE_URL}/anime/{mal_id}/recommendations")
    if resp is not None:
        data = resp.json().get("data", [])
        results: list[dict] = []
        for item in data:
            try:
                entry = item.get("entry") or {}
                rec_id = entry.get("mal_id")
                if not rec_id:
                    continue
                jpg = (entry.get("images") or {}).get("jpg") or {}
                results.append({
                    "mal_id": rec_id,
                    "title": entry.get("title"),
                    "image_url": jpg.get("large_image_url") or jpg.get("image_url"),
                    "mal_url": entry.get("url"),
                })
            except Exception as e:
                _log.info("get_recommendations: skipping malformed entry: %s", e)
                continue
        if results:
            return results[:limit]
    from . import anilist
    return await anilist.get_recommendations(mal_id, limit=limit)


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
