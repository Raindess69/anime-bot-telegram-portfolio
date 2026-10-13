"""Shikicinema (Shikivideos) video aggregator service.

Fetches free public embedded anime player streams by Shikimori ID.
Used as an in-app streaming fallback when Kodik token is unset or AniLibria
does not have all episodes.
"""
import logging
from collections import defaultdict
import httpx

_BASE_URL = "https://smarthard.net/v1/api"
_TIMEOUT = httpx.Timeout(6.0, connect=3.0)
_log = logging.getLogger(__name__)


async def get_player(shikimori_id: int, translation_id: int | None = None) -> dict | None:
    """Fetch embedded player info from Shikicinema for in-app watching."""
    if not shikimori_id:
        return None

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_BASE_URL}/shikivideos/{shikimori_id}", params={"limit": 600})
            if resp.status_code != 200:
                return None
            items = resp.json()
    except Exception as e:
        _log.info("Shikicinema fetch error for %s: %s", shikimori_id, e)
        return None

    if not items or not isinstance(items, list):
        return None

    translations_map: dict[str, dict[int, str]] = defaultdict(dict)
    for item in items:
        url = item.get("url")
        ep = item.get("episode")
        if not url or ep is None or not isinstance(ep, int):
            continue
        if url.startswith("http://"):
            url = url.replace("http://", "https://", 1)
        author = item.get("author") or "Оригинал"
        # Only keep the first valid link per (author, episode)
        if ep not in translations_map[author]:
            translations_map[author][ep] = url

    if not translations_map:
        return None

    sorted_authors = sorted(
        translations_map.keys(),
        key=lambda a: (1 if 1 in translations_map[a] else 0, len(translations_map[a])),
        reverse=True,
    )

    translations_list = []
    selected_author = sorted_authors[0]
    selected_id = 1

    for idx, auth in enumerate(sorted_authors[:10], start=1):
        auth_eps = translations_map[auth]
        translations_list.append({
            "id": idx,
            "title": auth,
            "type": "embed",
            "episodes_count": len(auth_eps),
            "episodes": auth_eps,
        })
        if translation_id is not None and translation_id == idx:
            selected_author = auth
            selected_id = idx

    chosen_episodes = translations_map[selected_author]
    ep_keys = sorted(chosen_episodes.keys())
    first_ep = ep_keys[0] if ep_keys else 1

    return {
        "type": "iframe",
        "url": chosen_episodes.get(first_ep, ""),
        "episodes": chosen_episodes,
        "last_ep": max(ep_keys) if ep_keys else 1,
        "first_ep": first_ep,
        "translation": selected_author,
        "translation_id": selected_id,
        "translations": translations_list,
    }
