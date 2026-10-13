"""Kodik search API — optional streaming source with wide coverage.

Kodik aggregates dozens of Russian pirate CDNs; if a title exists anywhere on
the Ru-net, Kodik usually indexes it. The catch: the API needs a partner
token. Users register one for free at https://kodik.cc/. Without KODIK_TOKEN
set, every function here returns None gracefully — the scheduler simply skips
this source.
"""
import logging

import httpx

from config import settings

BASE_URL = "https://kodik-api.com"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_log = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(settings.kodik_token)


async def find_by_ids(
    *,
    mal_id: int | None = None,
    shikimori_id: int | None = None,
    title: str | None = None,
) -> dict | None:
    """Return {max_ep, url, episode_url} for the newest available episode, or None.

    Kodik returns one result per (translation, series) pair — we keep only the
    highest last_episode across translations, which corresponds to the newest
    episode available on any of Kodik's CDNs. `episode_url` points directly at
    that latest episode when we can extract it; `url` is the series base URL
    used as a fallback.
    """
    if not enabled() or (not mal_id and not shikimori_id and not title):
        return None
    params: dict[str, str | int] = {
        "token": settings.kodik_token,
        "limit": 100,
        "with_episodes": "true",
    }
    if shikimori_id:
        params["shikimori_id"] = shikimori_id
    elif mal_id:
        params["mal_id"] = mal_id
    elif title:
        params["title"] = title

    results = []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(f"{BASE_URL}/search", params=params)
            resp.raise_for_status()
            results = resp.json().get("results") or []
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.info("Kodik search failed: %s", e)

        if not results and title and (shikimori_id or mal_id):
            try:
                p2 = {"token": settings.kodik_token, "title": title, "limit": 50, "with_episodes": "true"}
                resp2 = await client.get(f"{BASE_URL}/search", params=p2)
                resp2.raise_for_status()
                results = resp2.json().get("results") or []
            except Exception:
                pass

    best_ep = 0
    best_url: str | None = None
    best_item: dict | None = None
    for item in results:
        if not isinstance(item, dict):
            continue
        last_ep = _int_or_zero(item.get("last_episode") or item.get("episodes_count"))
        if last_ep > best_ep:
            best_ep = last_ep
            best_url = _norm_link(item.get("link") or "")
            best_item = item
    if best_ep <= 0 or not best_item:
        return None

    episode_url = _extract_episode_link(best_item, best_ep) or best_url
    return {"max_ep": best_ep, "url": best_url, "episode_url": episode_url}


def _extract_episode_link(item: dict, ep: int) -> str | None:
    for season in (item.get("seasons") or {}).values():
        eps = (season or {}).get("episodes") or {}
        raw = eps.get(str(ep)) or eps.get(ep)
        link = _episode_link_value(raw)
        if link:
            return link
    raw_eps = item.get("episodes") or {}
    if isinstance(raw_eps, dict):
        raw = raw_eps.get(str(ep)) or raw_eps.get(ep)
        link = _episode_link_value(raw)
        if link:
            return link
    return None


def _episode_link_value(raw) -> str | None:
    if isinstance(raw, str) and raw:
        return _norm_link(raw)
    if isinstance(raw, dict):
        link = raw.get("link")
        if isinstance(link, str) and link:
            return _norm_link(link)
    return None


async def get_player(
    *,
    mal_id: int | None = None,
    shikimori_id: int | None = None,
    title: str | None = None,
    translation_id: int | None = None,
) -> dict | None:
    """Full player payload for a card: base URL + per-episode URLs + translation.

    Returns {url, episodes: {n: url}, last_ep, translation, translation_id, translations} or None.
    If translation_id is specified, picks that variant; otherwise picks the highest last_episode.
    """
    if not enabled() or (not mal_id and not shikimori_id and not title):
        return None
    params: dict[str, str | int] = {
        "token": settings.kodik_token,
        "limit": 100,
        "with_episodes": "true",
        "with_material_data": "false",
    }
    if shikimori_id:
        params["shikimori_id"] = shikimori_id
    elif mal_id:
        params["mal_id"] = mal_id
    elif title:
        params["title"] = title

    results = []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(f"{BASE_URL}/search", params=params)
            resp.raise_for_status()
            results = resp.json().get("results") or []
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            _log.info("Kodik player fetch failed: %s", e)

        # Fallback to search by title if id returned nothing
        if not results and title and (shikimori_id or mal_id):
            try:
                p2 = {
                    "token": settings.kodik_token,
                    "title": title,
                    "limit": 50,
                    "with_episodes": "true",
                    "with_material_data": "false",
                }
                resp2 = await client.get(f"{BASE_URL}/search", params=p2)
                resp2.raise_for_status()
                results = resp2.json().get("results") or []
            except Exception:
                pass

    if not results:
        return None

    def _score(item: dict) -> tuple:
        last_ep = _int_or_zero(item.get("last_episode") or item.get("episodes_count"))
        trans = item.get("translation") or {}
        # Prefer dubs (voice) over subs when episode counts tie.
        voice_bonus = 1 if (trans.get("type") == "voice") else 0
        return (last_ep, voice_bonus)

    # Collect all available translations
    available_translations = []
    seen_trans_ids = set()
    for item in results:
        trans_obj = item.get("translation") or {}
        t_id = trans_obj.get("id")
        t_title = trans_obj.get("title")
        if t_id and t_title and t_id not in seen_trans_ids:
            seen_trans_ids.add(t_id)
            available_translations.append({
                "id": t_id,
                "title": t_title,
                "type": trans_obj.get("type") or "voice",
                "episodes_count": _int_or_zero(item.get("last_episode") or item.get("episodes_count")),
            })

    # Pick specific translation if requested, otherwise best by score
    chosen = None
    if translation_id:
        for item in results:
            if (item.get("translation") or {}).get("id") == translation_id:
                chosen = item
                break

    if not chosen:
        chosen = max(results, key=_score)

    last_ep = _int_or_zero(chosen.get("last_episode") or chosen.get("episodes_count"))
    base_url = _norm_link(chosen.get("link") or "")
    if not base_url:
        return None

    episodes: dict[int, str] = {}
    raw_seasons = chosen.get("seasons") or {}
    if isinstance(raw_seasons, dict) and raw_seasons:
        for season_data in raw_seasons.values():
            eps = (season_data or {}).get("episodes") or {}
            for k, v in eps.items():
                _put_ep(episodes, k, v)
            if episodes:
                break
    if not episodes:
        raw_eps = chosen.get("episodes") or {}
        if isinstance(raw_eps, dict):
            for k, v in raw_eps.items():
                _put_ep(episodes, k, v)

    curr_trans = chosen.get("translation") or {}
    translation = curr_trans.get("title") or ""
    curr_trans_id = curr_trans.get("id")

    return {
        "url": base_url,
        "episodes": episodes,
        "last_ep": last_ep,
        "translation": translation,
        "translation_id": curr_trans_id,
        "translations": available_translations,
    }


def _put_ep(target: dict[int, str], key, value) -> None:
    try:
        n = int(key)
    except (TypeError, ValueError):
        return
    link = _episode_link_value(value)
    if not link:
        return
    target[n] = link


def _norm_link(url: str) -> str:
    if not url:
        return url
    if url.startswith("//"):
        return "https:" + url
    return url


def _int_or_zero(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0
