"""Subscriptions v2 — keyed by mal_id, aware of multiple streaming sources.

Old schema (v1) was keyed on (user_id, anilibria_code) — a title without an
Anilibria release couldn't be subscribed to at all. The new schema stores
mal_id as the identity and keeps every known source URL alongside it, so the
scheduler can check Anilibria, Yummy, Shikimori and (optionally) Kodik in one
sweep and tell the user *where* the new episode dropped.
"""
import logging
import time

import aiosqlite

from config import settings

_log = logging.getLogger(__name__)

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    mal_id INTEGER,
    anilibria_code TEXT,
    yummy_url TEXT,
    shikimori_id INTEGER,
    title TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT 'ru',
    last_episode INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_subs_user_mal ON subscriptions(user_id, mal_id) WHERE mal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(user_id);
"""


async def init_subscriptions(db_path: str | None = None) -> None:
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        # Detect legacy v1 schema: `subscriptions` exists but has no `id` column.
        async with db.execute("PRAGMA table_info(subscriptions)") as cur:
            columns = {row[1] for row in await cur.fetchall()}
        if columns and "id" not in columns:
            _log.info("Migrating subscriptions v1 → v2")
            await db.execute("ALTER TABLE subscriptions RENAME TO subscriptions_v1")
        await db.executescript(_SCHEMA_V2)
        if columns and "id" not in columns:
            # Best-effort port: legacy rows have anilibria_code but no mal_id.
            # Scheduler tolerates NULL mal_id — it'll just use anilibria_code alone.
            await db.execute(
                """INSERT INTO subscriptions
                   (user_id, anilibria_code, title, lang, last_episode, created_at)
                   SELECT user_id, anilibria_code, title, lang, last_episode, created_at
                   FROM subscriptions_v1"""
            )
            await db.execute("DROP TABLE subscriptions_v1")
        await db.commit()


async def is_subscribed(user_id: int, mal_id: int | None = None, anilibria_code: str | None = None) -> bool:
    """Match by mal_id when present; falls back to anilibria_code for legacy entries."""
    async with aiosqlite.connect(settings.db_path) as db:
        if mal_id:
            async with db.execute(
                "SELECT 1 FROM subscriptions WHERE user_id = ? AND mal_id = ?",
                (user_id, mal_id),
            ) as cur:
                if await cur.fetchone():
                    return True
        if anilibria_code:
            async with db.execute(
                "SELECT 1 FROM subscriptions WHERE user_id = ? AND anilibria_code = ?",
                (user_id, anilibria_code),
            ) as cur:
                if await cur.fetchone():
                    return True
    return False


async def subscribe(
    user_id: int,
    *,
    title: str,
    lang: str,
    last_episode: int,
    mal_id: int | None = None,
    anilibria_code: str | None = None,
    yummy_url: str | None = None,
    shikimori_id: int | None = None,
) -> None:
    """Upsert by (user_id, mal_id). At least one identifier must be provided."""
    if not mal_id and not anilibria_code:
        raise ValueError("subscribe: need at least mal_id or anilibria_code")
    now = int(time.time())
    async with aiosqlite.connect(settings.db_path) as db:
        # If a row with the same mal_id already exists — refresh sources & title.
        if mal_id:
            async with db.execute(
                "SELECT id FROM subscriptions WHERE user_id = ? AND mal_id = ?",
                (user_id, mal_id),
            ) as cur:
                row = await cur.fetchone()
            if row:
                await db.execute(
                    """UPDATE subscriptions SET
                         title = ?, lang = ?,
                         anilibria_code = COALESCE(?, anilibria_code),
                         yummy_url = COALESCE(?, yummy_url),
                         shikimori_id = COALESCE(?, shikimori_id)
                       WHERE id = ?""",
                    (title, lang, anilibria_code, yummy_url, shikimori_id, row[0]),
                )
                await db.commit()
                return
        await db.execute(
            """INSERT INTO subscriptions
               (user_id, mal_id, anilibria_code, yummy_url, shikimori_id, title, lang, last_episode, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, mal_id, anilibria_code, yummy_url, shikimori_id, title, lang, last_episode, now),
        )
        await db.commit()


async def unsubscribe(user_id: int, *, mal_id: int | None = None, anilibria_code: str | None = None) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        if mal_id:
            await db.execute(
                "DELETE FROM subscriptions WHERE user_id = ? AND mal_id = ?",
                (user_id, mal_id),
            )
        elif anilibria_code:
            await db.execute(
                "DELETE FROM subscriptions WHERE user_id = ? AND anilibria_code = ?",
                (user_id, anilibria_code),
            )
        await db.commit()


async def list_subscriptions(user_id: int) -> list[dict]:
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            """SELECT id, mal_id, anilibria_code, yummy_url, shikimori_id,
                      title, lang, last_episode
               FROM subscriptions WHERE user_id = ? ORDER BY created_at DESC""",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [
        {
            "id": r[0], "mal_id": r[1], "anilibria_code": r[2], "yummy_url": r[3],
            "shikimori_id": r[4], "title": r[5], "lang": r[6], "last_episode": r[7],
        }
        for r in rows
    ]


async def list_all_active() -> list[dict]:
    """Every row, for the scheduler sweep."""
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute(
            """SELECT id, user_id, mal_id, anilibria_code, yummy_url, shikimori_id,
                      title, lang, last_episode
               FROM subscriptions"""
        ) as cur:
            rows = await cur.fetchall()
    return [
        {
            "id": r[0], "user_id": r[1], "mal_id": r[2], "anilibria_code": r[3],
            "yummy_url": r[4], "shikimori_id": r[5], "title": r[6],
            "lang": r[7], "last_episode": r[8],
        }
        for r in rows
    ]


async def update_last_episode(sub_id: int, episode: int) -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            "UPDATE subscriptions SET last_episode = ? WHERE id = ?",
            (episode, sub_id),
        )
        await db.commit()
