"""Per-user title tracking — status (watching/completed/plan/dropped), episode
progress, playback position, and favorites.

Guarantees:
- Favorites are independent of watch status (watching, plan, completed, dropped).
- Progress of individual episodes is tracked in `episode_progress`.
- Reaching 85% in episode N does NOT mark episodes 1..(N-1) as watched.
- Reaching 85% in an episode marks that episode completed, NOT the entire title.
- Outdated or delayed progress events do not regress playback timestamp.
"""
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
    last_position INTEGER NOT NULL DEFAULT 0,
    is_favorite INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    image_url TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, mal_id)
);
CREATE INDEX IF NOT EXISTS idx_user_titles_user_status ON user_titles(user_id, status);

CREATE TABLE IF NOT EXISTS episode_progress (
    user_id INTEGER NOT NULL,
    mal_id INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    duration INTEGER NOT NULL DEFAULT 0,
    is_completed INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, mal_id, episode)
);
CREATE INDEX IF NOT EXISTS idx_ep_progress_user_mal ON episode_progress(user_id, mal_id);
"""


async def init_user_titles(db_path: str | None = None) -> None:
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        await db.executescript(_SCHEMA)
        try:
            await db.execute("ALTER TABLE user_titles ADD COLUMN image_url TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE user_titles ADD COLUMN last_position INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        await db.commit()


def next_status(current: str | None) -> str:
    if current not in _STATUS_CYCLE:
        return _STATUS_CYCLE[0]
    i = _STATUS_CYCLE.index(current)
    return _STATUS_CYCLE[(i + 1) % len(_STATUS_CYCLE)]


async def get(user_id: int, mal_id: int, db_path: str | None = None) -> dict | None:
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            """SELECT title, lang, status, current_episode, is_favorite, updated_at, image_url,
                      COALESCE(last_position, 0)
               FROM user_titles WHERE user_id = ? AND mal_id = ?""",
            (user_id, mal_id),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return {
        "title": row[0],
        "lang": row[1],
        "status": row[2],
        "current_episode": row[3],
        "is_favorite": bool(row[4]),
        "updated_at": row[5],
        "image_url": row[6] if len(row) > 6 and row[6] else "",
        "last_position": row[7] if len(row) > 7 else 0,
    }


async def _ensure_row(
    db: aiosqlite.Connection,
    user_id: int,
    mal_id: int,
    title: str,
    lang: str,
    image_url: str = "",
) -> None:
    now = int(time.time())
    await db.execute(
        """INSERT INTO user_titles (user_id, mal_id, title, lang, image_url, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, mal_id) DO UPDATE SET
               title = CASE WHEN excluded.title != '' THEN excluded.title ELSE user_titles.title END,
               image_url = CASE WHEN excluded.image_url != '' THEN excluded.image_url ELSE user_titles.image_url END,
               lang = excluded.lang,
               updated_at = excluded.updated_at""",
        (user_id, mal_id, title, lang, image_url, now),
    )


async def get_title_state(user_id: int, mal_id: int, db_path: str | None = None) -> dict:
    """Returns compact state for a title (status, episode, favorite, completed episodes)."""
    row = await get(user_id, mal_id, db_path=db_path)
    completed_eps = await get_completed_episodes(user_id, mal_id, db_path=db_path)
    if not row:
        return {
            "status": None,
            "current_episode": 0,
            "last_position": 0,
            "is_favorite": False,
            "completed_episodes": completed_eps,
        }
    return {
        "status": row.get("status"),
        "current_episode": row.get("current_episode", 0),
        "last_position": row.get("last_position", 0),
        "is_favorite": row.get("is_favorite", False),
        "completed_episodes": completed_eps,
    }


async def set_status(
    user_id: int,
    mal_id: int,
    title: str,
    lang: str,
    status: str,
    image_url: str = "",
    db_path: str | None = None,
) -> None:
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status}")
    path = db_path or settings.db_path
    now = int(time.time())
    async with aiosqlite.connect(path) as db:
        await _ensure_row(db, user_id, mal_id, title, lang, image_url)
        await db.execute(
            "UPDATE user_titles SET status = ?, updated_at = ? WHERE user_id = ? AND mal_id = ?",
            (status, now, user_id, mal_id),
        )
        await db.commit()


async def cycle_status(
    user_id: int,
    mal_id: int,
    title: str,
    lang: str,
    image_url: str = "",
    db_path: str | None = None,
) -> str:
    """Advance to the next status in the cycle and return the new value."""
    current = await get(user_id, mal_id, db_path=db_path)
    new_status = next_status(current["status"] if current else None)
    await set_status(user_id, mal_id, title, lang, new_status, image_url, db_path=db_path)
    return new_status


async def set_episode(
    user_id: int,
    mal_id: int,
    title: str,
    lang: str,
    episode: int,
    image_url: str = "",
    db_path: str | None = None,
) -> None:
    """Marks progress. Auto-flips status plan → watching."""
    path = db_path or settings.db_path
    now = int(time.time())
    async with aiosqlite.connect(path) as db:
        await _ensure_row(db, user_id, mal_id, title, lang, image_url)
        await db.execute(
            """UPDATE user_titles SET
                 current_episode = ?,
                 status = CASE WHEN status = 'plan' THEN 'watching' ELSE status END,
                 updated_at = ?
               WHERE user_id = ? AND mal_id = ?""",
            (episode, now, user_id, mal_id),
        )
        await db.commit()


async def toggle_favorite(
    user_id: int,
    mal_id: int,
    title: str,
    lang: str,
    image_url: str = "",
    db_path: str | None = None,
) -> bool:
    """Returns the new favorite state."""
    path = db_path or settings.db_path
    now = int(time.time())
    async with aiosqlite.connect(path) as db:
        await _ensure_row(db, user_id, mal_id, title, lang, image_url)
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


async def save_playback_progress(
    user_id: int,
    mal_id: int,
    episode: int,
    position: int = 0,
    duration: int = 0,
    completed: bool = False,
    title: str = "",
    lang: str = "ru",
    image_url: str = "",
    db_path: str | None = None,
) -> dict:
    """Saves playback position within episode and marks episode completed when threshold reached.

    Guarantees:
    - Position within episode is tracked separately from episode counter.
    - Watching episode 10 does NOT mark episodes 1..9 as watched.
    - Watching a single episode does NOT mark the entire anime title completed.
    - Outdated events with older updated_at do not regress position.
    """
    path = db_path or settings.db_path
    now = int(time.time())
    is_completed = 1 if (completed or (duration > 60 and (position / duration) >= 0.85)) else 0

    async with aiosqlite.connect(path) as db:
        await _ensure_row(db, user_id, mal_id, title, lang, image_url)

        # 1. Update episode_progress atomically
        await db.execute(
            """INSERT INTO episode_progress (user_id, mal_id, episode, position, duration, is_completed, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, mal_id, episode) DO UPDATE SET
                   position = excluded.position,
                   duration = CASE WHEN excluded.duration > 0 THEN excluded.duration ELSE episode_progress.duration END,
                   is_completed = CASE WHEN episode_progress.is_completed = 1 THEN 1 ELSE excluded.is_completed END,
                   updated_at = excluded.updated_at
               WHERE excluded.updated_at >= episode_progress.updated_at""",
            (user_id, mal_id, episode, position, duration, is_completed, now),
        )

        # 2. Update user_titles (current_episode, last_position), never auto-completing whole title
        await db.execute(
            """UPDATE user_titles SET
                 current_episode = ?,
                 last_position = ?,
                 status = CASE WHEN status = 'plan' THEN 'watching' ELSE status END,
                 updated_at = ?
               WHERE user_id = ? AND mal_id = ?""",
            (episode, position, now, user_id, mal_id),
        )
        await db.commit()

    return {
        "ok": True,
        "episode": episode,
        "position": position,
        "duration": duration,
        "is_completed": bool(is_completed),
    }


async def get_episodes_progress(user_id: int, mal_id: int, db_path: str | None = None) -> dict[int, dict]:
    """Returns mapping of episode number to progress info: {ep: {position, duration, is_completed}}."""
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            "SELECT episode, position, duration, is_completed FROM episode_progress WHERE user_id = ? AND mal_id = ?",
            (user_id, mal_id),
        ) as cur:
            rows = await cur.fetchall()
    return {
        r[0]: {"position": r[1], "duration": r[2], "is_completed": bool(r[3])}
        for r in rows
    }


async def get_completed_episodes(user_id: int, mal_id: int, db_path: str | None = None) -> list[int]:
    """Returns list of completed episode numbers for a title."""
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            "SELECT episode FROM episode_progress WHERE user_id = ? AND mal_id = ? AND is_completed = 1 ORDER BY episode ASC",
            (user_id, mal_id),
        ) as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]


async def list_by_status(user_id: int, status: str | None = None, db_path: str | None = None) -> list[dict]:
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        if status:
            query = """SELECT mal_id, title, lang, status, current_episode, is_favorite, updated_at, image_url,
                              COALESCE(last_position, 0)
                        FROM user_titles WHERE user_id = ? AND status = ? ORDER BY updated_at DESC"""
            params = (user_id, status)
        else:
            query = """SELECT mal_id, title, lang, status, current_episode, is_favorite, updated_at, image_url,
                              COALESCE(last_position, 0)
                        FROM user_titles WHERE user_id = ? ORDER BY updated_at DESC"""
            params = (user_id,)
        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()
    return [
        {
            "mal_id": r[0],
            "title": r[1],
            "lang": r[2],
            "status": r[3],
            "current_episode": r[4],
            "is_favorite": bool(r[5]),
            "updated_at": r[6],
            "image_url": r[7] if len(r) > 7 and r[7] else "",
            "last_position": r[8] if len(r) > 8 else 0,
        }
        for r in rows
    ]


async def export_all(user_id: int, db_path: str | None = None) -> list[dict]:
    """Full snapshot for JSON backup."""
    return await list_by_status(user_id, status=None, db_path=db_path)


async def list_favorites(user_id: int, db_path: str | None = None) -> list[dict]:
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            """SELECT mal_id, title, lang, status, current_episode, is_favorite, updated_at, image_url,
                      COALESCE(last_position, 0)
               FROM user_titles WHERE user_id = ? AND is_favorite = 1 ORDER BY updated_at DESC""",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [
        {
            "mal_id": r[0],
            "title": r[1],
            "lang": r[2],
            "status": r[3],
            "current_episode": r[4],
            "is_favorite": bool(r[5]),
            "updated_at": r[6],
            "image_url": r[7] if len(r) > 7 and r[7] else "",
            "last_position": r[8] if len(r) > 8 else 0,
        }
        for r in rows
    ]


async def get_stats(user_id: int, db_path: str | None = None) -> dict:
    """Aggregate counts for the "Мой список" stats view."""
    counts = {s: 0 for s in STATUSES}
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
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

        # Count actual distinct completed episodes from episode_progress
        async with db.execute(
            "SELECT COUNT(DISTINCT mal_id || ':' || episode) FROM episode_progress WHERE user_id = ? AND is_completed = 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            completed_count = row[0] if row else 0

        # Fallback to current_episode if no episode_progress records exist yet
        if completed_count == 0:
            async with db.execute(
                "SELECT COALESCE(SUM(current_episode), 0) FROM user_titles WHERE user_id = ? AND status IN ('watching', 'completed')",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
                completed_count = row[0] if row else 0

    return {
        "watching": counts["watching"],
        "completed": counts["completed"],
        "plan": counts["plan"],
        "dropped": counts["dropped"],
        "favorites": favorites,
        "episodes_watched": completed_count,
    }
