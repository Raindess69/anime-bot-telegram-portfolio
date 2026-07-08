import logging
from difflib import SequenceMatcher

import httpx

BASE_URL = "https://anilibria.top/api/v1"
SITE_URL = "https://anilibria.top"
_TIMEOUT = httpx.Timeout(8.0, connect=5.0)
_SEARCH_LIMIT = 5
# Anilibria's fuzzy search happily returns tangentially-related hits. We compare
# the query against every candidate name via SequenceMatcher on a whitespace-and-
# punctuation-stripped ("compact") form and reject anything below this bar.
# Blue Lock (which anilibria doesn't have) vs "Blue Box" alt name of Ao no Hako
# scored 0.67 at 0.65 threshold — 0.75 kills that noise. Genuine matches survive
# because a compact substring check floors them at ~0.9 (see _title_similarity).
_MIN_SIMILARITY = 0.75
_log = logging.getLogger(__name__)


def release_url(alias: str) -> str:
    return f"{SITE_URL}/anime/releases/release/{alias}"


def episode_url(alias: str, uuid: str | None = None) -> str:
    if uuid:
        return f"{SITE_URL}/anime/video/episode/{uuid}"
    return f"{SITE_URL}/anime/releases/release/{alias}/episodes"


def torrent_download_url(torrent_id: int) -> str:
    return f"{BASE_URL}/anime/torrents/{torrent_id}/file"


async def find_release(
    query: str,
    *,
    extra_queries: list[str] | None = None,
    min_similarity: float = _MIN_SIMILARITY,
) -> dict | None:
    """Return {code, url, episodes, episode_ids, torrents} for the best match, or None.

    `code` is the V1 `alias` (slug like "one-punch-man"). We query multiple candidates
    and pick the one whose name (main/english/alternative) is most similar to the query
    (or any of `extra_queries` — used to pass the English title alongside the Russian one).
    Anilibria's fuzzy search happily returns unrelated hits on short substrings
    (e.g. "Ао Аси" matched "Midara na Ao-chan…"), so we score-filter here.
    """
    queries = [q.strip() for q in ([query] + list(extra_queries or [])) if q and q.strip()]
    if not queries:
        return None

    candidates: dict[str, tuple[float, dict]] = {}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for q in queries:
            try:
                resp = await client.get(
                    f"{BASE_URL}/app/search/releases",
                    params={"query": q, "limit": _SEARCH_LIMIT},
                )
                resp.raise_for_status()
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                _log.info("Anilibria search failed for %r: %s", q, e)
                continue
            data = resp.json()
            items = data if isinstance(data, list) else (data.get("data") if isinstance(data, dict) else None)
            if not items:
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                alias = item.get("alias")
                if not alias:
                    continue
                score = max(_title_similarity(qq, item.get("name") or {}) for qq in queries)
                prev = candidates.get(alias)
                if prev is None or score > prev[0]:
                    candidates[alias] = (score, item)

    if not candidates:
        return None

    best_alias, (best_score, best_item) = max(candidates.items(), key=lambda kv: kv[1][0])
    if best_score < min_similarity:
        _log.info(
            "Anilibria: rejecting %s — best similarity %.2f < %.2f for %r",
            best_alias, best_score, min_similarity, queries[0],
        )
        return None

    return await get_release_by_code(best_alias) or {
        "code": best_alias,
        "url": release_url(best_alias),
        "episodes": _extract_episodes(best_item),
        "episode_ids": _extract_episode_ids(best_item),
        "torrents": _extract_torrents(best_item),
    }


async def get_release_by_code(alias: str) -> dict | None:
    """Fetch full release info by alias. Used for subscription checks."""
    if not alias:
        return None
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        try:
            resp = await client.get(f"{BASE_URL}/anime/releases/{alias}")
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.info("Anilibria get_release_by_code(%s) failed: %s", alias, e)
            return None
        data = resp.json()
    if not isinstance(data, dict) or not data.get("alias"):
        return None
    return {
        "code": data["alias"],
        "url": release_url(data["alias"]),
        "episodes": _extract_episodes(data),
        "episode_ids": _extract_episode_ids(data),
        "torrents": _extract_torrents(data),
    }


async def download_torrent_file(torrent_id: int) -> bytes | None:
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        try:
            resp = await client.get(torrent_download_url(torrent_id))
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.warning("Anilibria torrent download %s failed: %s", torrent_id, e)
            return None
        return resp.content


def _compact(s: str) -> str:
    """Lowercase + strip everything except letters/digits — 'Ao Ashi' → 'aoashi'."""
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _title_similarity(query: str, names: dict) -> float:
    qc = _compact(query)
    if not qc:
        return 0.0
    best = 0.0
    for key in ("main", "english", "alternative"):
        candidate = names.get(key) if isinstance(names, dict) else None
        if not candidate:
            continue
        nc = _compact(candidate)
        if not nc:
            continue
        if qc == nc:
            return 1.0
        if qc in nc or nc in qc:
            # One is a substring of the other — strong signal even if lengths differ.
            # Floor at 0.9 so a legit near-hit ("Ao Ashi" vs "Aoashi") always
            # clears the threshold, while a tiny query lost in a giant title is
            # capped by the length ratio.
            r = min(len(qc), len(nc)) / max(len(qc), len(nc))
            best = max(best, max(r, 0.9))
        else:
            r = SequenceMatcher(None, qc, nc).ratio()
            if r > best:
                best = r
    return best


def _extract_torrents(release: dict) -> list[dict]:
    torrents = release.get("torrents") or []
    result: list[dict] = []
    for tr in torrents:
        if not isinstance(tr, dict):
            continue
        tid = tr.get("id")
        if tid is None:
            continue

        quality_obj = tr.get("quality")
        if isinstance(quality_obj, dict):
            quality = quality_obj.get("value") or quality_obj.get("description") or "?"
        else:
            quality = tr.get("label") or "?"

        size_bytes = tr.get("size")
        try:
            size_gb = round(float(size_bytes) / (1024 ** 3), 2) if size_bytes else None
        except (TypeError, ValueError):
            size_gb = None

        result.append({
            "id": int(tid),
            "quality": str(quality),
            "episodes": tr.get("label") or "",
            "size_gb": size_gb,
            "seeders": tr.get("seeders"),
            "magnet": tr.get("magnet"),
        })
    return result


def _extract_episodes(release: dict) -> list[int]:
    episodes = release.get("episodes") or []
    numbers: list[int] = []
    if isinstance(episodes, list):
        for ep in episodes:
            if not isinstance(ep, dict):
                continue
            ordinal = ep.get("ordinal")
            if ordinal is None:
                continue
            try:
                numbers.append(int(ordinal))
            except (ValueError, TypeError):
                continue
    return sorted(set(numbers))


def _extract_episode_ids(release: dict) -> dict[int, str]:
    """Returns {ordinal: uuid} — the site's per-episode player URL uses the uuid."""
    episodes = release.get("episodes") or []
    result: dict[int, str] = {}
    if not isinstance(episodes, list):
        return result
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        ordinal = ep.get("ordinal")
        eid = ep.get("id")
        if ordinal is None or not eid:
            continue
        try:
            result[int(ordinal)] = str(eid)
        except (ValueError, TypeError):
            continue
    return result
