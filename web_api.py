import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import user_titles
from services import aggregator, kodik, shikimori

_log = logging.getLogger(__name__)

app = FastAPI(title="EnjoyAnime Mini App API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)


class StatusUpdateRequest(BaseModel):
    user_id: int
    mal_id: int
    title: str
    lang: str = "ru"
    status: str


class EpisodeUpdateRequest(BaseModel):
    user_id: int
    mal_id: int
    episode: int


class FavoriteToggleRequest(BaseModel):
    user_id: int
    mal_id: int
    title: str
    lang: str = "ru"


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "app": "EnjoyAnime TMA"}


@app.get("/api/feed")
async def get_feed(lang: str = "ru"):
    """Returns curated collections for the main page."""
    try:
        airing = await shikimori.top_anime(filter_="airing", limit=10)
        popular = await shikimori.top_anime(filter_="bypopularity", limit=10)
        ranked = await shikimori.top_anime(filter_=None, limit=10)
        return {
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


@app.get("/api/anime/{anime_id}")
async def get_anime_details(anime_id: int, lang: str = "ru"):
    """Get rich title info with embedded Kodik player & episodes."""
    try:
        full = await shikimori.get_by_id(anime_id)
        if not full:
            raise HTTPException(status_code=404, detail="Anime not found")

        # Enrich with Kodik player for in-app watching
        player_info = None
        if kodik.enabled():
            try:
                player_info = await kodik.get_player(shikimori_id=anime_id, mal_id=anime_id)
            except Exception as e:
                _log.info("Kodik player enrich failed for %s: %s", anime_id, e)

        full["kodik"] = player_info
        return full
    except HTTPException:
        raise
    except Exception as e:
        _log.exception("Details error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/library")
async def get_user_library(user_id: int, status: Optional[str] = None):
    """Get user tracked titles from SQLite."""
    try:
        items = await user_titles.list_by_status(user_id, status)
        return items
    except Exception as e:
        _log.exception("Library error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/library/status")
async def update_library_status(req: StatusUpdateRequest):
    try:
        await user_titles.set_status(
            user_id=req.user_id,
            mal_id=req.mal_id,
            title=req.title,
            lang=req.lang,
            status=req.status,
        )
        return {"ok": True, "status": req.status}
    except Exception as e:
        _log.exception("Update status error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/library/episode")
async def update_library_episode(req: EpisodeUpdateRequest):
    try:
        await user_titles.set_episode(
            user_id=req.user_id,
            mal_id=req.mal_id,
            episode=req.episode,
        )
        return {"ok": True, "episode": req.episode}
    except Exception as e:
        _log.exception("Update episode error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/library/favorite")
async def toggle_library_favorite(req: FavoriteToggleRequest):
    try:
        new_fav = await user_titles.toggle_favorite(
            user_id=req.user_id,
            mal_id=req.mal_id,
            title=req.title,
            lang=req.lang,
        )
        return {"ok": True, "is_favorite": new_fav}
    except Exception as e:
        _log.exception("Toggle favorite error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# Mount static assets and serve single-page Mini App
if (STATIC_DIR / "index.html").exists():
    @app.get("/", response_class=HTMLResponse)
    async def serve_index():
        return FileResponse(STATIC_DIR / "index.html")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
