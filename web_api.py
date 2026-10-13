import hashlib
import hmac
import json
import logging
import os
import urllib.parse
from pathlib import Path
from typing import Optional

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

from config import settings
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


def verify_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    """
    Validates Telegram WebApp initData string using HMAC-SHA256 according to Telegram specifications.
    Returns parsed dictionary (including parsed user dict) if valid, else None.
    """
    if not init_data or not bot_token:
        return None
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        if "hash" not in parsed:
            return None
        received_hash = parsed.pop("hash")

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
    Falls back gracefully if running in development / test mode without initData.
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

    if user_id:
        return {"id": user_id, "first_name": "DevUser", "is_dev": True}

    return {"id": 0, "first_name": "Гость", "is_anonymous": True}


class StatusUpdateRequest(BaseModel):
    user_id: Optional[int] = None
    mal_id: int
    title: str = ""
    lang: str = "ru"
    status: str
    image_url: str = ""


class EpisodeUpdateRequest(BaseModel):
    user_id: Optional[int] = None
    mal_id: int
    title: str = ""
    lang: str = "ru"
    episode: int
    image_url: str = ""


class FavoriteToggleRequest(BaseModel):
    user_id: Optional[int] = None
    mal_id: int
    title: str = ""
    lang: str = "ru"
    image_url: str = ""


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


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": "EnjoyAnime TMA"}


@app.get("/api/feed")
async def get_feed(
    lang: str = "ru",
    user_id: Optional[int] = None,
    user: dict = Depends(get_current_user),
):
    """Returns curated collections for the main page + continue watching."""
    try:
        airing = await shikimori.top_anime(filter_="airing", limit=12)
        popular = await shikimori.top_anime(filter_="bypopularity", limit=12)
        ranked = await shikimori.top_anime(filter_=None, limit=12)
        hero = popular[0] if popular else (airing[0] if airing else None)

        target_id = user["id"] if user.get("id") else (user_id or 0)
        continue_watching = []
        if target_id:
            try:
                watching_items = await user_titles.list_by_status(target_id, "watching")
                continue_watching = watching_items[:8]
            except Exception as e:
                _log.warning("Continue watching fetch failed: %s", e)

        return {
            "hero": hero,
            "continue_watching": continue_watching,
            "airing": airing,
            "popular": popular,
            "top": ranked,
        }
    except Exception as e:
        _log.exception("Feed error: %s", e)
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

        sources = {
            "shikimori": f"https://shikimori.one/animes/{anime_id}",
            "anilibria": anilibria_info.get("url") if anilibria_info else None,
            "anilibria_episodes": anilibria_info.get("episodes") if anilibria_info else [],
            "anilibria_code": anilibria_info.get("code") if anilibria_info else None,
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
    if not kodik.enabled():
        return {"url": None, "episodes": {}, "translations": []}
    try:
        player_info = await kodik.get_player(
            shikimori_id=anime_id,
            mal_id=anime_id,
            translation_id=translation_id,
        )
        return player_info or {"url": None, "episodes": {}, "translations": []}
    except Exception as e:
        _log.warning("Player stream error: %s", e)
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
    target_id = user["id"] if user.get("id") else (user_id or 0)
    if not target_id:
        return {"watching": 0, "completed": 0, "plan": 0, "dropped": 0, "favorites": 0, "episodes_watched": 0}
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
    """Get user tracked titles from SQLite."""
    target_id = user["id"] if user.get("id") else (user_id or 0)
    if not target_id:
        return []
    try:
        items = await user_titles.list_by_status(target_id, status)
        return items
    except Exception as e:
        _log.exception("Library error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/library/title/{anime_id}")
async def get_title_library_state(
    anime_id: int,
    user_id: Optional[int] = None,
    user: dict = Depends(get_current_user),
):
    """Returns whether the title is saved, which episode, and favorite status."""
    target_id = user["id"] if user.get("id") else (user_id or 0)
    if not target_id:
        return {"status": None, "current_episode": 0, "is_favorite": False}
    try:
        state = await user_titles.get_title_state(target_id, anime_id)
        return state
    except Exception as e:
        _log.exception("Title state error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/library/status")
async def update_library_status(
    req: StatusUpdateRequest,
    user: dict = Depends(get_current_user),
):
    target_id = user["id"] if user.get("id") else (req.user_id or 0)
    if not target_id:
        raise HTTPException(status_code=400, detail="Missing user identification")
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
    target_id = user["id"] if user.get("id") else (req.user_id or 0)
    if not target_id:
        raise HTTPException(status_code=400, detail="Missing user identification")
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
    target_id = user["id"] if user.get("id") else (req.user_id or 0)
    if not target_id:
        raise HTTPException(status_code=400, detail="Missing user identification")
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
    Saves video playback progress and auto-advances episode if 85%+ watched or finished.
    """
    target_id = user["id"] if user.get("id") else (req.user_id or 0)
    if not target_id:
        raise HTTPException(status_code=400, detail="Missing user identification")

    is_completed = req.completed or (req.duration > 0 and (req.position / req.duration) >= 0.85)
    try:
        if is_completed:
            await user_titles.set_episode(
                user_id=target_id,
                mal_id=req.mal_id,
                title=req.title,
                lang=req.lang,
                episode=req.episode,
                image_url=req.image_url,
            )
        return {
            "ok": True,
            "completed": is_completed,
            "episode": req.episode,
            "position": req.position,
            "user_id": target_id,
        }
    except Exception as e:
        _log.exception("Progress save error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# Mount static assets and serve single-page Mini App
if (STATIC_DIR / "index.html").exists():
    @app.get("/", response_class=HTMLResponse)
    async def serve_index():
        return FileResponse(STATIC_DIR / "index.html")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
