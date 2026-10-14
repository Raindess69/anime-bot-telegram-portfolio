import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
from pathlib import Path
from typing import Any, Optional

# Fix any invalid wildcards or spaces in NO_PROXY from sandbox
for _key in ("NO_PROXY", "no_proxy"):
    _val = os.getenv(_key)
    if _val:
        _cleaned = [item.strip().lstrip("*.") for item in _val.split(",") if item.strip()]
        os.environ[_key] = ",".join(_cleaned)

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import mask_secret, settings
from db import user_titles
from services import aggregator, kodik, shikimori

_log = logging.getLogger(__name__)

app = FastAPI(title="EnjoyAnime Mini App API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

VALID_STATUSES = {"watching", "completed", "plan", "dropped"}


def verify_telegram_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400 * 7) -> dict | None:
    """
    Validates Telegram WebApp initData string using HMAC-SHA256 according to Telegram specifications.
    Enforces maximum auth age (default 7 days for long-running Mini App sessions) and clock skew tolerance.
    Returns parsed dictionary (including parsed user dict) if valid, else None.
    """
    if not init_data or not bot_token:
        return None
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        if "hash" not in parsed:
            return None
        received_hash = parsed.pop("hash")

        # Check auth_date for expiration
        if "auth_date" in parsed:
            try:
                auth_date = int(parsed["auth_date"])
                now = int(time.time())
                if max_age_seconds and (now - auth_date > max_age_seconds):
                    _log.warning("Telegram initData expired: auth_date=%s now=%s", auth_date, now)
                    return None
                if auth_date - now > 300:
                    _log.warning("Telegram initData future auth_date: auth_date=%s now=%s", auth_date, now)
                    return None
            except (ValueError, TypeError):
                return None

        # 1. Sort all key=value pairs alphabetically by key, separated by '\n'
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

        # 2. secret_key = HMAC_SHA256(b"WebAppData", bot_token)
        secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()

        # 3. hash = HMAC_SHA256(secret_key, data_check_string).hexdigest()
        computed_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(computed_hash, received_hash):
            return None

        # Parse user field if present
        if "user" in parsed:
            try:
                parsed["user"] = json.loads(parsed["user"])
            except Exception:
                pass
        return parsed
    except Exception as e:
        _log.warning("Telegram initData verification exception: %s", e)
        return None


async def get_current_user(
    request: Request,
    x_telegram_init_data: Optional[str] = Header(None, alias="X-Telegram-Init-Data"),
    user_id: Optional[int] = Query(None),
) -> dict:
    """
    Resolves the Telegram user for the current request.
    If initData header is provided, it validates the signature against BOT_TOKEN.
    In development mode only, allows falling back to user_id query param.
    """
    raw_data = x_telegram_init_data
    if not raw_data:
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr.startswith("tma "):
            raw_data = auth_hdr[4:].strip()
        elif auth_hdr.startswith("Bearer "):
            raw_data = auth_hdr[7:].strip()

    if raw_data:
        verified = verify_telegram_init_data(raw_data, settings.bot_token)
        if verified and "user" in verified and isinstance(verified["user"], dict):
            return verified["user"]
        raise HTTPException(status_code=401, detail="Invalid Telegram initData signature")

    if settings.dev_mode and user_id:
        return {"id": user_id, "first_name": "DevUser", "is_dev": True}

    return {"id": 0, "first_name": "Гость", "is_anonymous": True}


def resolve_target_user_id(user: dict, requested_user_id: Optional[int] = None) -> int:
    """Enforces zero trust on client-supplied user_id:
    - If user is authenticated via initData, user['id'] is strictly used.
    - An authenticated user CANNOT read or modify another user's library.
    - If user is anonymous, access is rejected with 401 unless dev_mode is active.
    """
    if user.get("id") and not user.get("is_anonymous"):
        return user["id"]
    if settings.dev_mode and requested_user_id:
        return requested_user_id
    raise HTTPException(status_code=401, detail="Authentication required")


class StatusUpdateRequest(BaseModel):
    user_id: Optional[int] = None
    mal_id: int
    title: str = ""
    lang: str = "ru"
    status: str
    image_url: str = ""

    def validate_input(self):
        if self.mal_id <= 0:
            raise HTTPException(status_code=400, detail="Invalid mal_id")
        if self.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {self.status}. Must be one of {VALID_STATUSES}")


class EpisodeUpdateRequest(BaseModel):
    user_id: Optional[int] = None
    mal_id: int
    title: str = ""
    lang: str = "ru"
    episode: int
    image_url: str = ""

    def validate_input(self):
        if self.mal_id <= 0:
            raise HTTPException(status_code=400, detail="Invalid mal_id")
        if self.episode < 0 or self.episode > 10000:
            raise HTTPException(status_code=400, detail="Invalid episode number")


class FavoriteToggleRequest(BaseModel):
    user_id: Optional[int] = None
    mal_id: int
    title: str = ""
    lang: str = "ru"
    image_url: str = ""

    def validate_input(self):
        if self.mal_id <= 0:
            raise HTTPException(status_code=400, detail="Invalid mal_id")


class PlaybackProgressRequest(BaseModel):
    user_id: Optional[int] = None
    mal_id: int
    title: str = ""
    lang: str = "ru"
    episode: int = 1
    position: int = 0
    duration: int = 0
    completed: bool = False
    image_url: str = ""

    def validate_input(self):
        if self.mal_id <= 0:
            raise HTTPException(status_code=400, detail="Invalid mal_id")
        if self.episode < 0 or self.episode > 10000:
            raise HTTPException(status_code=400, detail="Invalid episode number")
        if self.position < 0 or self.duration < 0:
            raise HTTPException(status_code=400, detail="Invalid position or duration")


@app.get("/health")
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": "EnjoyAnime TMA"}


@app.get("/health/live")
async def health_live():
    return {"status": "live"}


@app.get("/health/ready")
async def health_ready():
    try:
        import aiosqlite
        async with aiosqlite.connect(settings.db_path) as db:
            async with db.execute("SELECT 1") as cur:
                await cur.fetchone()
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database not ready: {e}")


async def _fetch_category(filter_val: str | None, deadline: float) -> tuple[list[dict], str]:
    """Fetches a single feed category within the remaining deadline budget with semantic fallback."""
    now = time.monotonic()
    remaining = deadline - now
    if remaining <= 0.02:
        return [], "timeout"

    # Stage 1: Fast path via Shikimori (capped to 60% of remaining time or 2.5s)
    shiki_budget = max(0.02, min(remaining * 0.6, 2.5))
    try:
        res = await shikimori.top_anime(filter_=filter_val, limit=12, timeout=shiki_budget)
        if res:
            return res, "ok"
    except Exception as e:
        _log.info("Shikimori top (filter=%s) failed: %s", filter_val, e)

    # Stage 2: Fallback within the EXACT remaining deadline budget (does not get a new budget)
    rem_fallback = deadline - time.monotonic()
    if rem_fallback <= 0.02:
        _log.info("No remaining deadline budget for fallback (filter=%s): %.2fs", filter_val, rem_fallback)
        return [], "timeout"

    try:
        async with asyncio.timeout(rem_fallback):
            fallback_res = await aggregator.top_anime_multi(filter_=filter_val, type_=None, limit=12)
            if fallback_res:
                return fallback_res, "fallback"
            return [], "empty"
    except (asyncio.TimeoutError, TimeoutError):
        _log.warning("Fallback timed out for filter=%s within remaining budget", filter_val)
        return [], "timeout"
    except Exception as e:
        _log.warning("Fallback crashed for filter=%s: %s", filter_val, e)
        return [], "error"


async def _fetch_public_feed(lang: str = "ru", budget: float | None = None) -> dict:
    """Fetches curated public feed collections concurrently under an overall deadline budget.

    Guarantees:
    - Overall deadline budget covers all network operations (semaphores, Shikimori, retries, fallbacks).
    - Already finished categories are preserved even if one slow category hits the deadline.
    - Category semantics (airing, popular, top) are strictly preserved across primary and fallback sources.
    - Unfinished tasks are cancelled cleanly without leaking in-flight futures.
    """
    total_budget = budget if budget is not None else settings.feed_timeout_seconds
    deadline = time.monotonic() + total_budget

    tasks = {
        "airing": asyncio.create_task(_fetch_category("airing", deadline)),
        "popular": asyncio.create_task(_fetch_category("bypopularity", deadline)),
        "top": asyncio.create_task(_fetch_category(None, deadline)),
    }

    try:
        async with asyncio.timeout(total_budget):
            await asyncio.gather(*tasks.values(), return_exceptions=True)
    except (asyncio.TimeoutError, TimeoutError):
        _log.warning("Public feed overall deadline budget (%.1fs) expired; preserving partial results.", total_budget)

    results: dict[str, list[dict]] = {}
    section_status: dict[str, str] = {}
    unavailable_sections: list[str] = []

    for name, t in tasks.items():
        if t.done() and not t.cancelled():
            exc = t.exception()
            if exc is None:
                items, status = t.result()
                results[name] = items
                section_status[name] = status
                if status in ("timeout", "error") or not items:
                    unavailable_sections.append(name)
            else:
                _log.error("Feed task %s raised unhandled exception: %s", name, exc)
                results[name] = []
                section_status[name] = "error"
                unavailable_sections.append(name)
        else:
            t.cancel()
            results[name] = []
            section_status[name] = "timeout"
            unavailable_sections.append(name)

    airing = results.get("airing", [])
    popular = results.get("popular", [])
    top = results.get("top", [])
    hero = popular[0] if popular else (airing[0] if airing else (top[0] if top else None))

    is_complete_failure = not (airing or popular or top)
    feed_state = "error" if is_complete_failure else ("partial" if unavailable_sections else "ok")

    return {
        "hero": hero,
        "airing": airing,
        "popular": popular,
        "top": top,
        "feed_state": feed_state,
        "section_status": section_status,
        "unavailable_sections": unavailable_sections,
    }


@app.get("/api/feed")
async def get_feed(
    lang: str = "ru",
    user_id: Optional[int] = None,
    user: dict = Depends(get_current_user),
):
    """Returns curated collections for the main page + continue watching.

    Guarantees:
    - Bounded overall deadline budget (settings.feed_timeout_seconds).
    - Preserves partial results if only part of collections completed within budget.
    - Local continue_watching is returned even upon upstream source failure.
    - Never caches total failures for 300 seconds.
    """
    try:
        from utils.cache import feed_cache

        cache_key = f"public_feed:{lang}"

        # Only cache when feed produced at least one valid collection
        def _should_cache_feed(data: Any) -> bool:
            if not isinstance(data, dict):
                return False
            return bool(data.get("airing") or data.get("popular") or data.get("top"))

        public_data = await feed_cache.get_or_compute(
            cache_key,
            lambda: _fetch_public_feed(lang),
            should_cache=_should_cache_feed,
        )
        if not isinstance(public_data, dict):
            public_data = await _fetch_public_feed(lang)

        # Local continue watching from SQLite (local DB read, resilient to upstream failures)
        target_id = user["id"] if user.get("id") else (user_id or 0)
        continue_watching = []
        if target_id:
            try:
                watching_items = await user_titles.list_by_status(target_id, "watching")
                continue_watching = watching_items[:8]
            except Exception as e:
                _log.warning("Continue watching fetch failed: %s", e)

        return {
            "hero": public_data.get("hero"),
            "continue_watching": continue_watching,
            "airing": public_data.get("airing", []),
            "popular": public_data.get("popular", []),
            "top": public_data.get("top", []),
            "feed_state": public_data.get("feed_state", "ok"),
            "section_status": public_data.get("section_status", {}),
            "unavailable_sections": public_data.get("unavailable_sections", []),
        }
    except Exception as e:
        _log.exception("Feed error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/recommendations")
async def get_recommendations_endpoint(
    genre: Optional[str] = None,
    exclude_watched: bool = True,
    limit: int = 10,
    seed_title: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """Returns verifiable recommendations with explanations, optionally excluding watched titles."""
    exclude_ids = set()
    if exclude_watched and user.get("id") and not user.get("is_anonymous"):
        try:
            completed_items = await user_titles.list_by_status(user["id"], "completed")
            dropped_items = await user_titles.list_by_status(user["id"], "dropped")
            exclude_ids = {it["mal_id"] for it in completed_items + dropped_items if it.get("mal_id")}
        except Exception as e:
            _log.warning("Failed to fetch watched items for exclusion: %s", e)

    try:
        recs = await aggregator.get_recommendations(
            genre_slug=genre,
            exclude_mal_ids=exclude_ids,
            limit=min(max(limit, 1), 30),
            seed_title=seed_title,
        )
        return recs
    except Exception as e:
        _log.exception("Recommendations error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/api/search")
async def search_anime(q: str = Query(..., min_length=1), lang: str = "ru"):
    """Text search across Shikimori / AniList / Kodik."""
    try:
        cards = await aggregator.search_anime(q, lang)
        return [c.model_dump() for c in cards]
    except Exception as e:
        _log.exception("Search error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/vibe")
async def get_vibe(
    genre: Optional[str] = None,
    min_score: Optional[float] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    type_: Optional[str] = None,
    limit: int = 10,
):
    """Vibe filter search (genre, score, years, type)."""
    try:
        results, relaxed = await aggregator.vibe_search(
            min_score=min_score,
            year_from=year_from,
            year_to=year_to,
            genre_slug=genre,
            type_=type_,
            limit=limit,
        )
        return {"results": results, "relaxed": relaxed}
    except Exception as e:
        _log.exception("Vibe error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/random")
async def get_random():
    """Roll a high-rated random anime."""
    try:
        res = await aggregator.random_anime()
        return res or {}
    except Exception as e:
        _log.exception("Random error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/anime/{anime_id}")
async def get_anime_details(
    anime_id: int,
    lang: str = "ru",
    translation_id: Optional[int] = None,
):
    """Get rich title info with embedded Kodik player & episodes."""
    try:
        full = await shikimori.get_by_id(anime_id)
        if not full:
            raise HTTPException(status_code=404, detail="Anime not found")

        # Enrich with Kodik player for in-app watching
        player_info = None
        title_ru = full.get("title_ru") or full.get("title_en") or ""
        if kodik.enabled():
            try:
                player_info = await kodik.get_player(
                    shikimori_id=anime_id,
                    mal_id=anime_id,
                    title=title_ru,
                    translation_id=translation_id,
                )
            except Exception as e:
                _log.info("Kodik player enrich failed for %s: %s", anime_id, e)

        # Enrich with AniLibria release for guaranteed streaming sources
        anilibria_info = None
        try:
            from services import anilibria
            extras = [t for t in (full.get("title_en"), full.get("title_jp")) if t and t != title_ru]
            anilibria_info = await anilibria.find_release(title_ru, extra_queries=extras)
        except Exception as e:
            _log.info("AniLibria enrich failed for %s: %s", anime_id, e)

        # Build AniLibria / AniLiberty HLS payload if streams exist
        if not player_info and anilibria_info and anilibria_info.get("episode_streams"):
            streams = anilibria_info["episode_streams"]
            ep_keys = sorted(streams.keys())
            first_ep = ep_keys[0] if ep_keys else 1
            first_stream = streams[first_ep].get("720") or streams[first_ep].get("1080") or streams[first_ep].get("480") or ""
            ep_urls = {
                ep_num: (q_map.get("720") or q_map.get("1080") or q_map.get("480") or "")
                for ep_num, q_map in streams.items()
            }
            anili_label = f"AniLibria (DUB {first_ep}–{max(ep_keys)})" if first_ep > 1 else "AniLibria (DUB)"
            player_info = {
                "type": "hls",
                "url": first_stream,
                "episodes": ep_urls,
                "episode_streams": streams,
                "first_ep": first_ep,
                "last_ep": max(ep_keys) if ep_keys else 1,
                "translation": anili_label,
                "translation_id": 999,
                "translations": [{
                    "id": 999,
                    "title": anili_label,
                    "type": "voice",
                    "episodes_count": len(ep_keys),
                }],
            }
        elif player_info and anilibria_info and anilibria_info.get("episode_streams"):
            player_info.setdefault("translations", []).append({
                "id": 999,
                "title": "AniLibria (HLS)",
                "type": "voice",
                "episodes_count": len(anilibria_info.get("episodes", [])),
            })
            player_info["anilibria_streams"] = anilibria_info.get("episode_streams")

        import urllib.parse
        q_search = urllib.parse.quote(title_ru or full.get("title_en") or "")
        sources = {
            "shikimori": f"https://shikimori.one/animes/{anime_id}",
            "anilibria": (anilibria_info.get("url") if anilibria_info and anilibria_info.get("code") else None),
            "anilibria_episodes": anilibria_info.get("episodes") if anilibria_info else [],
            "anilibria_streams": anilibria_info.get("episode_streams") if anilibria_info else {},
            "anilibria_code": anilibria_info.get("code") if anilibria_info else None,
            "yummy": f"https://yummyanime.tv/search?q={q_search}",
            "animego": f"https://animego.org/search/anime?q={q_search}",
        }

        full["kodik"] = player_info
        full["sources"] = sources
        return full
    except HTTPException:
        raise
    except Exception as e:
        _log.exception("Details error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/player/{anime_id}")
async def get_player_stream(
    anime_id: int,
    translation_id: Optional[int] = None,
):
    """Fast player-only stream URL with translation/voice switching."""
    if translation_id == 999 or not kodik.enabled():
        try:
            full = await shikimori.get_by_id(anime_id)
            title_ru = (full.get("title_ru") or full.get("title_en") or "") if full else ""
            from services import anilibria
            anilibria_info = await anilibria.find_release(title_ru)
            if anilibria_info and anilibria_info.get("episode_streams"):
                streams = anilibria_info["episode_streams"]
                ep_keys = sorted(streams.keys())
                first_ep = ep_keys[0] if ep_keys else 1
                first_stream = streams[first_ep].get("720") or streams[first_ep].get("1080") or streams[first_ep].get("480") or ""
                ep_urls = {
                    ep_num: (q_map.get("720") or q_map.get("1080") or q_map.get("480") or "")
                    for ep_num, q_map in streams.items()
                }
                anili_label = f"AniLibria (DUB {first_ep}–{max(ep_keys)})" if first_ep > 1 else "AniLibria (DUB)"
                return {
                    "type": "hls",
                    "url": first_stream,
                    "episodes": ep_urls,
                    "episode_streams": streams,
                    "first_ep": first_ep,
                    "last_ep": max(ep_keys) if ep_keys else 1,
                    "translation": anili_label,
                    "translation_id": 999,
                    "translations": [{
                        "id": 999,
                        "title": anili_label,
                        "type": "voice",
                        "episodes_count": len(ep_keys),
                    }],
                }
        except Exception as e:
            _log.info("AniLibria fallback player failed: %s", e)

    if kodik.enabled():
        try:
            player_info = await kodik.get_player(
                shikimori_id=anime_id,
                mal_id=anime_id,
                translation_id=translation_id,
            )
            if player_info:
                return player_info
        except Exception as e:
            _log.info("Kodik player switch failed: %s", e)

    return {"url": None, "episodes": {}, "translations": []}


@app.get("/api/user/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Returns the verified Telegram user profile."""
    return {
        "authenticated": not user.get("is_anonymous", False),
        "user": user,
    }


@app.get("/api/user/stats")
async def get_user_statistics(
    user_id: Optional[int] = None,
    user: dict = Depends(get_current_user),
):
    """Returns user library counts and total watched episodes."""
    if not (user.get("id") and not user.get("is_anonymous")) and not (settings.dev_mode and user_id):
        return {"watching": 0, "completed": 0, "plan": 0, "dropped": 0, "favorites": 0, "episodes_watched": 0}
    target_id = resolve_target_user_id(user, user_id)
    try:
        return await user_titles.get_stats(target_id)
    except Exception as e:
        _log.exception("Stats error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/library")
async def get_user_library(
    status: Optional[str] = None,
    user_id: Optional[int] = None,
    user: dict = Depends(get_current_user),
):
    """Get user tracked titles from SQLite with zero-trust auth."""
    if status and status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    if not (user.get("id") and not user.get("is_anonymous")) and not (settings.dev_mode and user_id):
        return []
    target_id = resolve_target_user_id(user, user_id)
    try:
        return await user_titles.list_by_status(target_id, status)
    except Exception as e:
        _log.exception("Library error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/library/title/{anime_id}")
async def get_title_library_state(
    anime_id: int,
    user_id: Optional[int] = None,
    user: dict = Depends(get_current_user),
):
    """Returns whether the title is saved, which episode, favorite status, and completed episodes."""
    if anime_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid anime_id")
    if not (user.get("id") and not user.get("is_anonymous")) and not (settings.dev_mode and user_id):
        return {"status": None, "current_episode": 0, "last_position": 0, "is_favorite": False, "completed_episodes": []}
    target_id = resolve_target_user_id(user, user_id)
    try:
        return await user_titles.get_title_state(target_id, anime_id)
    except Exception as e:
        _log.exception("Title state error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/library/status")
async def update_library_status(
    req: StatusUpdateRequest,
    user: dict = Depends(get_current_user),
):
    req.validate_input()
    target_id = resolve_target_user_id(user, req.user_id)
    try:
        await user_titles.set_status(
            user_id=target_id,
            mal_id=req.mal_id,
            title=req.title,
            lang=req.lang,
            status=req.status,
            image_url=req.image_url,
        )
        return {"ok": True, "status": req.status, "user_id": target_id}
    except Exception as e:
        _log.exception("Update status error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/library/episode")
async def update_library_episode(
    req: EpisodeUpdateRequest,
    user: dict = Depends(get_current_user),
):
    req.validate_input()
    target_id = resolve_target_user_id(user, req.user_id)
    try:
        await user_titles.set_episode(
            user_id=target_id,
            mal_id=req.mal_id,
            title=req.title,
            lang=req.lang,
            episode=req.episode,
            image_url=req.image_url,
        )
        return {"ok": True, "episode": req.episode, "user_id": target_id}
    except Exception as e:
        _log.exception("Update episode error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/library/favorite")
async def toggle_library_favorite(
    req: FavoriteToggleRequest,
    user: dict = Depends(get_current_user),
):
    req.validate_input()
    target_id = resolve_target_user_id(user, req.user_id)
    try:
        new_fav = await user_titles.toggle_favorite(
            user_id=target_id,
            mal_id=req.mal_id,
            title=req.title,
            lang=req.lang,
            image_url=req.image_url,
        )
        return {"ok": True, "is_favorite": new_fav, "user_id": target_id}
    except Exception as e:
        _log.exception("Toggle favorite error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/library/progress")
async def save_playback_progress(
    req: PlaybackProgressRequest,
    user: dict = Depends(get_current_user),
):
    """
    Saves video playback progress, position and marks episode completed when 85%+ watched or finished.
    Does not mark the entire title as completed.
    """
    req.validate_input()
    target_id = resolve_target_user_id(user, req.user_id)
    try:
        res = await user_titles.save_playback_progress(
            user_id=target_id,
            mal_id=req.mal_id,
            episode=req.episode,
            position=req.position,
            duration=req.duration,
            completed=req.completed,
            title=req.title,
            lang=req.lang,
            image_url=req.image_url,
        )
        res["user_id"] = target_id
        return res
    except Exception as e:
        _log.exception("Progress save error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# Mount static assets and serve single-page Mini App
if (STATIC_DIR / "index.html").exists():
    @app.get("/", response_class=HTMLResponse)
    async def serve_index():
        return FileResponse(STATIC_DIR / "index.html")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("shutdown")
async def on_shutdown():
    from services.http_client import close_http_client
    await close_http_client()
