import aiosqlite

from config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    query TEXT NOT NULL,
    ts INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_search_history_user ON search_history(user_id, id DESC);
"""

_MAX_ENTRIES = 10


async def init_history() -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


async def add(user_id: int, query: str) -> None:
    query = (query or "").strip()
    if not query:
        return
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT query FROM search_history WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
        # Skip if the same query is already the most recent — avoids clutter
        # when the user retries the same title.
        if row and row[0] == query:
            return
        await db.execute(
            "INSERT INTO search_history (user_id, query) VALUES (?, ?)",
            (user_id, query),
        )
        await db.execute(
            """DELETE FROM search_history
               WHERE user_id = ? AND id NOT IN (
                   SELECT id FROM search_history
                   WHERE user_id = ? ORDER BY id DESC LIMIT ?
               )""",
            (user_id, user_id, _MAX_ENTRIES),
        )
        await db.commit()


async def list_recent(user_id: int, limit: int = _MAX_ENTRIES) -> list[str]:
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            "SELECT query FROM search_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]


async def clear(user_id: int) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("DELETE FROM search_history WHERE user_id = ?", (user_id,))
        await db.commit()
