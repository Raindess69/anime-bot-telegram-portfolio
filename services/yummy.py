import asyncio
import logging
import re
from difflib import SequenceMatcher
from urllib.parse import quote_plus

import httpx

BASE_URL = "https://yummyanime.tv"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_SEMAPHORE = asyncio.Semaphore(3)  # don't hammer their site
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
# Captures: (full-or-relative URL, path like "1304-aoj-asito-r1.html", inner HTML of <a>)
_ANIME_A_RE = re.compile(
    r'<a\s+[^>]*href=["\']((?:https?://[^"\']+)?/(\d+-[a-z0-9-]+\.html))["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Minimum similarity ratio to consider a link as matching the query.
# 0.3 was too loose — for Mushoku Tensei, every season's card matched the same
# special (long slug, high overlap with the base title). 0.5 filters that out.
_MIN_SIMILARITY = 0.5
# When several related pages score close to each other (same franchise —
# different seasons/specials/OVAs), we can't tell which is right. Fall back
# to a per-title search URL instead of pinning everyone to one page.
_MIN_MARGIN = 0.1

_log = logging.getLogger(__name__)


def fallback_search_url(query: str) -> str:
    return f"{BASE_URL}/index.php?do=search&subaction=search&story={quote_plus(query)}"


def _strip_html(text: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


def _slug_to_text(path: str) -> str:
    # "1304-aoj-asito-r1.html" -> "aoj asito r1"
    body = path.rsplit(".html", 1)[0]
    parts = body.split("-", 1)
    if len(parts) == 2:
        return parts[1].replace("-", " ")
    return body.replace("-", " ")


def _score(query: str, candidate: str) -> float:
    if not query or not candidate:
        return 0.0
    return SequenceMatcher(None, query.lower(), candidate.lower()).ratio()


def _best_score(candidate_text: str, queries: list[str]) -> float:
    return max((_score(q, candidate_text) for q in queries if q), default=0.0)


async def find_direct_link(
    query: str,
    *,
    title_ru: str | None = None,
    title_en: str | None = None,
) -> str | None:
    """Return the top yummyanime.tv anime page URL matching the query, or None if no confident match.

    Tries multiple search queries in order (Russian first — the site indexes by
    Russian titles) and returns the first confident hit. Retries even when the
    HTML is non-empty, because the site answers 200 with a "no results" page
    which used to be treated as a match.
    """
    if not query and not title_ru and not title_en:
        return None

    # De-duplicated, ordered candidates. Russian first — yummy indexes titles in Russian.
    search_queries: list[str] = []
    for q in (title_ru, title_en, query):
        if q and q not in search_queries:
            search_queries.append(q)

    # For scoring we compare against every known form of the title.
    score_queries = [q for q in (title_ru, title_en, query) if q]

    headers = {
        "User-Agent": _UA,
        "Referer": BASE_URL + "/",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ru,en;q=0.9",
    }

    async with _SEMAPHORE:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, headers=headers) as client:
            for q in search_queries:
                html = await _fetch_search_html(client, q)
                if not html:
                    continue
                best_url = _pick_best(html, score_queries)
                if best_url:
                    return best_url

    _log.info("Yummy: no confident match for %r / %r (tried %d queries)", title_ru, title_en, len(search_queries))
    return None


def _pick_best(html: str, score_queries: list[str]) -> str | None:
    scored: list[tuple[float, str]] = []
    seen_urls: set[str] = set()
    for match in _ANIME_A_RE.finditer(html):
        full_or_rel, path, inner = match.group(1), match.group(2), match.group(3)
        anchor_text = _strip_html(inner)
        slug_text = _slug_to_text(path)
        s = max(_best_score(anchor_text, score_queries), _best_score(slug_text, score_queries))
        url = full_or_rel if full_or_rel.startswith("http") else f"{BASE_URL}/{path}"
        # Same URL can appear multiple times on the search page (poster + title
        # link). Keep only the best score per URL for a clean margin check.
        if url in seen_urls:
            for i, (ps, pu) in enumerate(scored):
                if pu == url and s > ps:
                    scored[i] = (s, url)
                    break
            continue
        seen_urls.add(url)
        scored.append((s, url))

    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    best_score, best_url = scored[0]
    if best_score < _MIN_SIMILARITY:
        return None
    if len(scored) > 1:
        second_score = scored[1][0]
        if best_score - second_score < _MIN_MARGIN:
            _log.info(
                "Yummy: ambiguous top match (%.2f vs %.2f) — deferring to search fallback",
                best_score, second_score,
            )
            return None
    return best_url


_EPISODE_NUM_RE = re.compile(
    r'(?:серия|episode|episod|эпизод)[\s\W]*?(\d{1,3})',
    re.IGNORECASE,
)
_DATA_EPISODE_RE = re.compile(r'data-episode(?:-num|-number)?=["\'](\d{1,3})["\']', re.IGNORECASE)


async def get_max_episode(page_url: str) -> int | None:
    """Scrape a yummyanime title page and return the highest episode number, or None.

    Used by the scheduler to detect fresh episodes. Yummy renders episode
    lists inside the title page's DOM with either a `data-episode="N"` attr
    on each item or text like "Серия 5". We grep both — HTML shape may vary
    between templates, so overlap is fine.
    """
    if not page_url:
        return None
    headers = {
        "User-Agent": _UA,
        "Referer": BASE_URL + "/",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ru,en;q=0.9",
    }
    async with _SEMAPHORE:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, headers=headers) as client:
            try:
                resp = await client.get(page_url)
                if resp.status_code >= 400:
                    return None
                html = resp.text
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                _log.info("Yummy episode fetch failed for %s: %s", page_url, e)
                return None
    if not html:
        return None
    nums: set[int] = set()
    for m in _DATA_EPISODE_RE.finditer(html):
        try:
            nums.add(int(m.group(1)))
        except ValueError:
            continue
    for m in _EPISODE_NUM_RE.finditer(html):
        try:
            nums.add(int(m.group(1)))
        except ValueError:
            continue
    return max(nums) if nums else None


async def _fetch_search_html(client: httpx.AsyncClient, query: str) -> str | None:
    data = {"do": "search", "subaction": "search", "story": query}
    # POST first (DLE convention)
    try:
        resp = await client.post(f"{BASE_URL}/index.php?do=search", data=data)
        if resp.status_code < 400 and resp.text:
            return resp.text
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        _log.info("Yummy POST search failed for %r: %s", query, e)

    # GET fallback (some DLE forks accept it)
    try:
        resp = await client.get(fallback_search_url(query))
        if resp.status_code < 400 and resp.text:
            return resp.text
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        _log.info("Yummy GET search failed for %r: %s", query, e)

    return None
