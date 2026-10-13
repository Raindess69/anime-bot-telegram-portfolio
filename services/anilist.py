import logging

import httpx

BASE_URL = "https://graphql.anilist.co"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_log = logging.getLogger(__name__)

_COVER_QUERY = """
query ($id: Int) {
  Media(idMal: $id, type: ANIME) {
    coverImage { extraLarge large }
    bannerImage
  }
}
"""

_STREAMS_QUERY = """
query ($ids: [Int]) {
  Page(perPage: 50) {
    media(idMal_in: $ids, type: ANIME) {
      idMal
      externalLinks { site url type }
    }
  }
}
"""

_SEARCH_QUERY = """
query ($search: String, $perPage: Int) {
  Page(page: 1, perPage: $perPage) {
    media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
      idMal
      title { romaji english native }
      averageScore
      episodes
      status
      genres
      startDate { year }
      description(asHtml: false)
      coverImage { extraLarge large }
      siteUrl
    }
  }
}
"""

_STATUS_MAP = {
    "RELEASING": "Currently Airing",
    "FINISHED": "Finished Airing",
    "NOT_YET_RELEASED": "Not yet aired",
    "CANCELLED": "Finished Airing",
    "HIATUS": "Currently Airing",
}

_SEASON_MAP = {"winter": "WINTER", "spring": "SPRING", "summer": "SUMMER", "fall": "FALL"}
_FORMAT_MAP = {"tv": "TV", "movie": "MOVIE", "ova": "OVA", "special": "SPECIAL", "ona": "ONA"}

# Vibe-wizard genre slugs → AniList genre labels. Kept in sync with jikan.GENRES
# so the wizard can dispatch the same slug to both sources.
_ANILIST_GENRES = {
    "action": "Action",
    "adventure": "Adventure",
    "comedy": "Comedy",
    "drama": "Drama",
    "fantasy": "Fantasy",
    "horror": "Horror",
    "mystery": "Mystery",
    "romance": "Romance",
    "sci_fi": "Sci-Fi",
    "slice_of_life": "Slice of Life",
    "sports": "Sports",
    "supernatural": "Supernatural",
    "thriller": "Thriller",
    "psychological": "Psychological",
    "mecha": "Mecha",
    "music": "Music",
}

_ADVANCED_QUERY = """
query ($perPage: Int, $genre_in: [String], $format: MediaFormat, $startDate_greater: FuzzyDateInt, $startDate_lesser: FuzzyDateInt, $averageScore_greater: Int) {
  Page(page: 1, perPage: $perPage) {
    media(type: ANIME, sort: [SCORE_DESC, POPULARITY_DESC], genre_in: $genre_in, format: $format, startDate_greater: $startDate_greater, startDate_lesser: $startDate_lesser, averageScore_greater: $averageScore_greater, isAdult: false) {
      idMal
      title { romaji english native }
      averageScore
      episodes
      status
      genres
      startDate { year }
      description(asHtml: false)
      coverImage { extraLarge large }
      siteUrl
    }
  }
}
"""

_TOP_QUERY = """
query ($perPage: Int, $sort: [MediaSort], $status: MediaStatus, $format: MediaFormat, $season: MediaSeason, $seasonYear: Int) {
  Page(page: 1, perPage: $perPage) {
    media(type: ANIME, sort: $sort, status: $status, format: $format, season: $season, seasonYear: $seasonYear, isAdult: false) {
      idMal
      title { romaji english native }
      averageScore
      episodes
      status
      genres
      startDate { year }
      description(asHtml: false)
      coverImage { extraLarge large }
      siteUrl
    }
  }
}
"""

_BY_MAL_QUERY = """
query ($id: Int) {
  Media(idMal: $id, type: ANIME) {
    idMal
    title { romaji english native }
    averageScore
    episodes
    status
    genres
    startDate { year }
    description(asHtml: false)
    coverImage { extraLarge large }
    siteUrl
  }
}
"""

_RECS_QUERY = """
query ($id: Int, $perPage: Int) {
  Media(idMal: $id, type: ANIME) {
    recommendations(perPage: $perPage, sort: RATING_DESC) {
      nodes {
        mediaRecommendation {
          idMal
          title { romaji english native }
          coverImage { large }
          siteUrl
        }
      }
    }
  }
}
"""


async def get_by_mal(mal_id: int) -> dict | None:
    if not mal_id:
        return None
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(
                BASE_URL,
                json={"query": _BY_MAL_QUERY, "variables": {"id": mal_id}},
            )
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.info("AniList get_by_mal failed for mal_id=%s: %s", mal_id, e)
            return None
        data = resp.json()
    media = ((data.get("data") or {}).get("Media")) or {}
    if not media:
        return None
    return _parse(media)


async def get_recommendations(mal_id: int, limit: int = 10) -> list[dict]:
    if not mal_id:
        return []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(
                BASE_URL,
                json={"query": _RECS_QUERY, "variables": {"id": mal_id, "perPage": limit}},
            )
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.info("AniList recommendations failed for mal_id=%s: %s", mal_id, e)
            return []
        data = resp.json()
    media = ((data.get("data") or {}).get("Media")) or {}
    nodes = ((media.get("recommendations") or {}).get("nodes")) or []
    results: list[dict] = []
    for node in nodes:
        rec = node.get("mediaRecommendation") or {}
        rec_id = rec.get("idMal")
        if not rec_id:
            continue
        title = (rec.get("title") or {}).get("english") or (rec.get("title") or {}).get("romaji")
        cover = rec.get("coverImage") or {}
        results.append({
            "mal_id": rec_id,
            "title": title,
            "image_url": cover.get("large"),
            "mal_url": f"https://myanimelist.net/anime/{rec_id}",
        })
    return results[:limit]


async def get_cover_by_mal(mal_id: int) -> str | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(
                BASE_URL,
                json={"query": _COVER_QUERY, "variables": {"id": mal_id}},
            )
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.info("AniList cover failed for mal_id=%s: %s", mal_id, e)
            return None
        data = resp.json()
    media = ((data.get("data") or {}).get("Media")) or {}
    cover = media.get("coverImage") or {}
    return cover.get("extraLarge") or cover.get("large")


async def get_streams_by_mal(mal_ids: list[int]) -> dict[int, dict[str, str]]:
    """Batched external-links lookup: {mal_id: {site_lower: url}}.

    Uses AniList's externalLinks field — authoritative for legal streaming
    availability on Crunchyroll, Netflix, HIDIVE, Bilibili, etc.
    """
    ids = [i for i in mal_ids if isinstance(i, int) and i > 0]
    if not ids:
        return {}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(
                BASE_URL,
                json={"query": _STREAMS_QUERY, "variables": {"ids": ids}},
            )
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.info("AniList streams lookup failed: %s", e)
            return {}
        data = resp.json()
    media_list = ((data.get("data") or {}).get("Page") or {}).get("media") or []
    result: dict[int, dict[str, str]] = {}
    for m in media_list:
        mid = m.get("idMal")
        if not mid:
            continue
        links: dict[str, str] = {}
        for link in m.get("externalLinks") or []:
            if not isinstance(link, dict):
                continue
            # Filter to actual streaming sources — AniList also lists info sites
            # (Wikipedia, Twitter, etc.) which we don't want to render as watch buttons.
            if (link.get("type") or "").upper() != "STREAMING":
                continue
            site = (link.get("site") or "").strip().lower()
            url = link.get("url")
            if site and url:
                links[site] = url
        result[mid] = links
    return result


async def top_anime(filter_: str | None = None, type_: str | None = None, limit: int = 10) -> list[dict]:
    """Top-charts fallback: Jikan's filter names → AniList sort/status/format variables."""
    variables: dict[str, object] = {"perPage": limit}
    if filter_ == "airing":
        variables["status"] = "RELEASING"
        variables["sort"] = ["POPULARITY_DESC"]
    elif filter_ == "upcoming":
        variables["status"] = "NOT_YET_RELEASED"
        variables["sort"] = ["POPULARITY_DESC"]
    elif filter_ == "bypopularity":
        variables["sort"] = ["POPULARITY_DESC"]
    else:
        variables["sort"] = ["SCORE_DESC"]
    if type_ and type_ in _FORMAT_MAP:
        variables["format"] = _FORMAT_MAP[type_]
    return await _run_top_query(variables)


async def seasonal(year: int, season: str, limit: int = 10) -> list[dict]:
    season_norm = _SEASON_MAP.get(season)
    if not season_norm:
        return []
    return await _run_top_query({
        "perPage": limit,
        "season": season_norm,
        "seasonYear": year,
        "sort": ["POPULARITY_DESC"],
    })


async def _run_top_query(variables: dict) -> list[dict]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(
                BASE_URL,
                json={"query": _TOP_QUERY, "variables": variables},
            )
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.info("AniList top query failed: %s", e)
            return []
        data = resp.json()
    media_list = ((data.get("data") or {}).get("Page") or {}).get("media") or []
    return [_parse(m) for m in media_list if m]


async def search_advanced(
    *,
    min_score: float | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    genre_slug: str | None = None,
    type_: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Vibe-wizard search: AniList side. Same filter surface as jikan.search_advanced,
    but AniList takes genre names (via slug map) and averageScore on a 0-100 scale."""
    variables: dict[str, object] = {"perPage": limit}
    if genre_slug and genre_slug in _ANILIST_GENRES:
        variables["genre_in"] = [_ANILIST_GENRES[genre_slug]]
    if type_ and type_ in _FORMAT_MAP:
        variables["format"] = _FORMAT_MAP[type_]
    if year_from:
        variables["startDate_greater"] = year_from * 10000  # FuzzyDateInt YYYYMMDD
    if year_to:
        variables["startDate_lesser"] = year_to * 10000 + 1231
    if min_score is not None:
        # AniList averageScore is 0-100; subtract 1 so 7.0 threshold catches 70.
        variables["averageScore_greater"] = max(0, int(min_score * 10) - 1)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(
                BASE_URL,
                json={"query": _ADVANCED_QUERY, "variables": variables},
            )
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.info("AniList advanced search failed: %s", e)
            return []
        data = resp.json()
    media_list = ((data.get("data") or {}).get("Page") or {}).get("media") or []
    return [_parse(m) for m in media_list if m]


_RANDOM_QUERY = """
query ($page: Int) {
  Page(page: $page, perPage: 1) {
    media(type: ANIME, sort: POPULARITY_DESC, isAdult: false, averageScore_greater: 60) {
      idMal
      title { romaji english native }
      averageScore
      episodes
      status
      genres
      startDate { year }
      description(asHtml: false)
      coverImage { extraLarge large }
      siteUrl
    }
  }
}
"""


async def random_anime() -> dict | None:
    """Random popular anime — used as fallback when Jikan's /random/anime 504s.

    We pick a random page across the top ~2000 most-popular anime (score ≥ 6.0)
    and take the single item on it. Bounded to popular titles so we don't roll
    obscure filler; caller can call again if the user re-rolls.
    """
    import random
    page = random.randint(1, 2000)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(
                BASE_URL,
                json={"query": _RANDOM_QUERY, "variables": {"page": page}},
            )
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.info("AniList random failed: %s", e)
            return None
        data = resp.json()
    media_list = ((data.get("data") or {}).get("Page") or {}).get("media") or []
    if not media_list:
        return None
    return _parse(media_list[0])


async def search(query: str, limit: int = 10) -> list[dict]:
    if not query:
        return []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(
                BASE_URL,
                json={"query": _SEARCH_QUERY, "variables": {"search": query, "perPage": limit}},
            )
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.warning("AniList search failed: %s", e)
            return []
        data = resp.json()
    media_list = ((data.get("data") or {}).get("Page") or {}).get("media") or []
    return [_parse(m) for m in media_list if m]


def _parse(m: dict) -> dict:
    title = m.get("title") or {}
    cover = m.get("coverImage") or {}
    start_date = m.get("startDate") or {}
    score = m.get("averageScore")
    return {
        "mal_id": m.get("idMal"),
        "title_en": title.get("english") or title.get("romaji"),
        "title_jp": title.get("native"),
        "score": (score / 10.0) if isinstance(score, (int, float)) else None,
        "episodes": m.get("episodes"),
        "status": _STATUS_MAP.get(m.get("status") or "", m.get("status")),
        "genres": m.get("genres") or [],
        "year": start_date.get("year"),
        "synopsis_en": _strip_html(m.get("description")),
        "image_url": cover.get("extraLarge") or cover.get("large"),
        "mal_url": f"https://myanimelist.net/anime/{m['idMal']}" if m.get("idMal") else m.get("siteUrl"),
    }


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    import re
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip() or None
