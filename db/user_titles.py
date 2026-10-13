"""Per-user title tracking — status (watching/completed/plan/dropped), episode
progress and favorites. Kept separate from `subscriptions`: that table is swept
by the scheduler every 12h to poll for new episodes, and most tracked titles
here aren't meant to be polled at all (e.g. "plan to watch")."""
import logging
import time

import aiosqlite

from config import settings

_log = logging.getLogger(__name__)

STATUSES = ("watching", "completed", "plan", "dropped")
_STATUS_CYCLE = ("watching", "completed", "plan", "dropped")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_titles (
    user_id INTEGER NOT NULL,
    mal_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT 'ru',
    status TEXT NOT NULL DEFAULT 'watching',
    current_episode INTEGER NOT NULL DEFAULT 0,
    is_favorite INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, mal_id)
);
CREATE INDEX IF NOT EXISTS idx_user_titles_user_status ON user_titles(user_id, status);
"""


async def init_user_titles() -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


def next_status(current: str | None) -> str:
    if current not in _STATUS_CYCLE:
        return _STATUS_CYCLE[0]
    i = _STATUS_CYCLE.index(current)
    return _STATUS_CYCLE[(i + 1) % len(_STATUS_CYCLE)]


async def get(user_id: int, mal_id: int) -> dict | None:
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            """SELECT title, lang, status, current_episode, is_favorite, updated_at
               FROM user_titles WHERE user_id = ? AND mal_id = ?""",
            (user_id, mal_id),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return {
        "title": row[0], "lang": row[1], "status": row[2],
        "current_episode": row[3], "is_favorite": bool(row[4]), "updated_at": row[5],
    }


async def _ensure_row(db: aiosqlite.Connection, user_id: int, mal_id: int, title: str, lang: str) -> None:
    now = int(time.time())
    await db.execute(
        """INSERT INTO user_titles (user_id, mal_id, title, lang, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(user_id, mal_id) DO UPDATE SET
               title = CASE WHEN excluded.title != '' THEN excluded.title ELSE user_titles.title END,
               lang = excluded.lang,
               updated_at = excluded.updated_at""",
        (user_id, mal_id, title, lang, now),
    )


async def get_title_state(user_id: int, mal_id: int) -> dict:
    """Returns compact state for a title (status, episode, favorite)."""
    row = await get(user_id, mal_id)
    if not row:
        return {"status": None, "current_episode": 0, "is_favorite": False}
    return {
        "status": row.get("status"),
        "current_episode": row.get("current_episode", 0),
        "is_favorite": row.get("is_favorite", False),
    }


async def set_status(user_id: int, mal_id: int, title: str, lang: str, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status}")
    now = int(time.time())
    async with aiosqlite.connect(settings.db_path) as db:
        await _ensure_row(db, user_id, mal_id, title, lang)
        await db.execute(
            "UPDATE user_titles SET status = ?, updated_at = ? WHERE user_id = ? AND mal_id = ?",
            (status, now, user_id, mal_id),
        )
        await db.commit()


async def cycle_status(user_id: int, mal_id: int, title: str, lang: str) -> str:
    """Advance to the next status in the cycle and return the new value."""
    current = await get(user_id, mal_id)
    new_status = next_status(current["status"] if current else None)
    await set_status(user_id, mal_id, title, lang, new_status)
    return new_status


async def set_episode(user_id: int, mal_id: int, title: str, lang: str, episode: int) -> None:
    """Marks progress. Auto-flips status plan → watching (you can't be 'planning'
    once you've actually watched an episode)."""
    now = int(time.time())
    async with aiosqlite.connect(settings.db_path) as db:
        await _ensure_row(db, user_id, mal_id, title, lang)
        await db.execute(
            """UPDATE user_titles SET
                 current_episode = ?,
                 status = CASE WHEN status = 'plan' THEN 'watching' ELSE status END,
                 updated_at = ?
               WHERE user_id = ? AND mal_id = ?""",
            (episode, now, user_id, mal_id),
        )
        await db.commit()


async def toggle_favorite(user_id: int, mal_id: int, title: str, lang: str) -> bool:
    """Returns the new favorite state."""
    now = int(time.time())
    async with aiosqlite.connect(settings.db_path) as db:
        await _ensure_row(db, user_id, mal_id, title, lang)
        async with db.execute(
            "SELECT is_favorite FROM user_titles WHERE user_id = ? AND mal_id = ?",
            (user_id, mal_id),
        ) as cur:
            row = await cur.fetchone()
        new_val = 0 if (row and row[0]) else 1
        await db.execute(
            "UPDATE user_titles SET is_favorite = ?, updated_at = ? WHERE user_id = ? AND mal_id = ?",
            (new_val, now, user_id, mal_id),
        )
        await db.commit()
    return bool(new_val)


async def list_by_status(user_id: int, status: str | None = None) -> list[dict]:
    async with aiosqlite.connect(settings.db_path) as db:
        if status:
            query = """SELECT mal_id, title, lang, status, current_episode, is_favorite, updated_at
                        FROM user_titles WHERE user_id = ? AND status = ? ORDER BY updated_at DESC"""
            params = (user_id, status)
        else:
            query = """SELECT mal_id, title, lang, status, current_episode, is_favorite, updated_at
                        FROM user_titles WHERE user_id = ? ORDER BY updated_at DESC"""
            params = (user_id,)
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
    return [
        {
            "mal_id": r[0], "title": r[1], "lang": r[2], "status": r[3],
            "current_episode": r[4], "is_favorite": bool(r[5]), "updated_at": r[6],
        }
        for r in rows
    ]


async def export_all(user_id: int) -> list[dict]:
    """Full snapshot for JSON backup."""
    return await list_by_status(user_id, status=None)


async def list_favorites(user_id: int) -> list[dict]:
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            """SELECT mal_id, title, lang, status, current_episode, is_favorite, updated_at
               FROM user_titles WHERE user_id = ? AND is_favorite = 1 ORDER BY updated_at DESC""",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [
        {
            "mal_id": r[0], "title": r[1], "lang": r[2], "status": r[3],
            "current_episode": r[4], "is_favorite": bool(r[5]), "updated_at": r[6],
        }
        for r in rows
    ]


async def get_stats(user_id: int) -> dict:
    """Aggregate counts for the "Мой список" stats view."""
    counts = {s: 0 for s in STATUSES}
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT status, COUNT(*) FROM user_titles WHERE user_id = ? GROUP BY status",
            (user_id,),
        ) as cur:
            for status, n in await cur.fetchall():
                if status in counts:
                    counts[status] = n
        async with db.execute(
            "SELECT COUNT(*) FROM user_titles WHERE user_id = ? AND is_favorite = 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            favorites = row[0] if row else 0
        async with db.execute(
            "SELECT COALESCE(SUM(current_episode), 0) FROM user_titles WHERE user_id = ? AND status IN ('watching', 'completed')",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            episodes_watched = row[0] if row else 0
    return {
        "watching": counts["watching"],
        "completed": counts["completed"],
        "plan": counts["plan"],
        "dropped": counts["dropped"],
        "favorites": favorites,
        "episodes_watched": episodes_watched,
    }
