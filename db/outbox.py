"""Outbox queue and tracked titles storage for reliable push notifications.

Guarantees:
- Deduplication via UNIQUE(user_id, mal_id, episode, event_type).
- Atomic SQLite transactions for enqueuing events and updating baseline.
- Safe concurrency via atomic state transition: pending -> processing.
- Idempotent migrations with baseline migration from existing subscriptions.
"""
import logging
import time

import aiosqlite

from config import settings

_log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tracked_titles (
    mal_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    anilibria_code TEXT,
    yummy_url TEXT,
    shikimori_id INTEGER,
    last_known_episode INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    mal_id INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'new_episode',
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    claimed_at INTEGER DEFAULT 0,
    claim_token INTEGER DEFAULT 0,
    sent_at INTEGER,
    last_error TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_outbox_unique_event
    ON notification_outbox(user_id, mal_id, episode, event_type);

CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON notification_outbox(status, next_attempt_at);
"""


async def init_outbox(db_path: str | None = None) -> None:
    path = db_path or settings.db_path
    now = int(time.time())
    async with aiosqlite.connect(path) as db:
        await db.executescript(_SCHEMA)
        try:
            await db.execute("ALTER TABLE notification_outbox ADD COLUMN claimed_at INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE notification_outbox ADD COLUMN claim_token INTEGER DEFAULT 0")
        except Exception:
            pass

        # Check migration version
        async with db.execute("SELECT 1 FROM schema_migrations WHERE version = 'v3_outbox'") as cur:
            migrated = await cur.fetchone()

        if not migrated:
            # Safe baseline migration from existing subscriptions table if present
            try:
                async with db.execute("PRAGMA table_info(subscriptions)") as cur:
                    cols = {r[1] for r in await cur.fetchall()}
                if "mal_id" in cols and "last_episode" in cols:
                    ac_expr = "anilibria_code" if "anilibria_code" in cols else "NULL"
                    yu_expr = "yummy_url" if "yummy_url" in cols else "NULL"
                    shiki_expr = "shikimori_id" if "shikimori_id" in cols else "NULL"
                    title_expr = "title" if "title" in cols else "''"
                    created_expr = "created_at" if "created_at" in cols else "0"
                    await db.execute(
                        f"""INSERT OR IGNORE INTO tracked_titles
                           (mal_id, title, anilibria_code, yummy_url, shikimori_id, last_known_episode, updated_at)
                           SELECT mal_id, {title_expr}, {ac_expr}, {yu_expr}, {shiki_expr}, MAX(last_episode), MAX({created_expr})
                           FROM subscriptions
                           WHERE mal_id IS NOT NULL AND mal_id > 0
                           GROUP BY mal_id"""
                    )
            except Exception as e:
                _log.debug("Outbox migration baseline check skipped: %s", e)

            await db.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES ('v3_outbox', ?)",
                (now,),
            )
        await db.commit()


async def get_tracked_title(mal_id: int, db_path: str | None = None) -> dict | None:
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            """SELECT mal_id, title, anilibria_code, yummy_url, shikimori_id, last_known_episode, updated_at
               FROM tracked_titles WHERE mal_id = ?""",
            (mal_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return {
        "mal_id": row[0],
        "title": row[1],
        "anilibria_code": row[2],
        "yummy_url": row[3],
        "shikimori_id": row[4],
        "last_known_episode": row[5],
        "updated_at": row[6],
    }


async def set_tracked_title_baseline(
    mal_id: int,
    episode: int,
    title: str = "",
    anilibria_code: str | None = None,
    yummy_url: str | None = None,
    shikimori_id: int | None = None,
    db_path: str | None = None,
) -> None:
    path = db_path or settings.db_path
    now = int(time.time())
    async with aiosqlite.connect(path) as db:
        await db.execute(
            """INSERT INTO tracked_titles (mal_id, title, anilibria_code, yummy_url, shikimori_id, last_known_episode, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(mal_id) DO UPDATE SET
                   title = CASE WHEN excluded.title != '' THEN excluded.title ELSE tracked_titles.title END,
                   anilibria_code = COALESCE(excluded.anilibria_code, tracked_titles.anilibria_code),
                   yummy_url = COALESCE(excluded.yummy_url, tracked_titles.yummy_url),
                   shikimori_id = COALESCE(excluded.shikimori_id, tracked_titles.shikimori_id),
                   last_known_episode = excluded.last_known_episode,
                   updated_at = excluded.updated_at""",
            (mal_id, title, anilibria_code, yummy_url, shikimori_id, episode, now),
        )
        await db.commit()


async def get_all_monitored_titles(db_path: str | None = None) -> list[dict]:
    """Returns unique titles monitored across user_titles (watching/favorite) and subscriptions."""
    path = db_path or settings.db_path
    titles_map: dict[int, dict] = {}
    async with aiosqlite.connect(path) as db:
        # 1. From user_titles (status='watching' OR is_favorite=1)
        async with db.execute(
            """SELECT ut.mal_id, ut.title
               FROM user_titles ut
               WHERE (ut.status = 'watching' OR ut.is_favorite = 1) AND ut.mal_id > 0"""
        ) as cur:
            for mal_id, title in await cur.fetchall():
                if mal_id not in titles_map:
                    titles_map[mal_id] = {
                        "mal_id": mal_id,
                        "title": title or "",
                        "anilibria_code": None,
                        "yummy_url": None,
                        "shikimori_id": None,
                    }

        # 2. From subscriptions
        async with db.execute(
            """SELECT s.mal_id, s.title, s.anilibria_code, s.yummy_url, s.shikimori_id
               FROM subscriptions s
               WHERE s.mal_id IS NOT NULL AND s.mal_id > 0"""
        ) as cur:
            for mal_id, title, ac, yu, shiki in await cur.fetchall():
                if mal_id not in titles_map:
                    titles_map[mal_id] = {
                        "mal_id": mal_id,
                        "title": title or "",
                        "anilibria_code": ac,
                        "yummy_url": yu,
                        "shikimori_id": shiki,
                    }
                else:
                    if not titles_map[mal_id]["title"] and title:
                        titles_map[mal_id]["title"] = title
                    if not titles_map[mal_id]["anilibria_code"] and ac:
                        titles_map[mal_id]["anilibria_code"] = ac
                    if not titles_map[mal_id]["yummy_url"] and yu:
                        titles_map[mal_id]["yummy_url"] = yu
                    if not titles_map[mal_id]["shikimori_id"] and shiki:
                        titles_map[mal_id]["shikimori_id"] = shiki

        # 3. Augment with metadata and last_known_episode from tracked_titles if present
        async with db.execute(
            "SELECT mal_id, title, anilibria_code, yummy_url, shikimori_id, last_known_episode FROM tracked_titles"
        ) as cur:
            for mal_id, title, ac, yu, shiki, lk in await cur.fetchall():
                if mal_id in titles_map:
                    titles_map[mal_id]["last_known_episode"] = lk
                    if not titles_map[mal_id]["anilibria_code"] and ac:
                        titles_map[mal_id]["anilibria_code"] = ac
                    if not titles_map[mal_id]["yummy_url"] and yu:
                        titles_map[mal_id]["yummy_url"] = yu
                    if not titles_map[mal_id]["shikimori_id"] and shiki:
                        titles_map[mal_id]["shikimori_id"] = shiki
                    if not titles_map[mal_id]["title"] and title:
                        titles_map[mal_id]["title"] = title
                else:
                    # Title exists in tracked_titles but no active watchers/subscribers currently
                    pass

    return list(titles_map.values())


async def get_eligible_subscribers(mal_id: int, db_path: str | None = None) -> list[int]:
    """Returns unique user_ids who should receive new episode notifications for mal_id.

    Rules:
    - watching = True
    - OR is_favorite = True (independent condition, even if completed or dropped)
    - OR has active row in subscriptions
    - Excludes blocked users (is_blocked = 1)
    """
    path = db_path or settings.db_path
    user_ids: set[int] = set()
    async with aiosqlite.connect(path) as db:
        # Check user_titles
        async with db.execute(
            """SELECT ut.user_id
               FROM user_titles ut
               LEFT JOIN users u ON u.user_id = ut.user_id
               WHERE ut.mal_id = ?
                 AND (ut.status = 'watching' OR ut.is_favorite = 1)
                 AND COALESCE(u.is_blocked, 0) = 0""",
            (mal_id,),
        ) as cur:
            for row in await cur.fetchall():
                user_ids.add(row[0])

        # Check subscriptions
        async with db.execute(
            """SELECT s.user_id
               FROM subscriptions s
               LEFT JOIN users u ON u.user_id = s.user_id
               WHERE s.mal_id = ?
                 AND COALESCE(u.is_blocked, 0) = 0""",
            (mal_id,),
        ) as cur:
            for row in await cur.fetchall():
                user_ids.add(row[0])

    return list(user_ids)


async def is_user_eligible(user_id: int, mal_id: int, db_path: str | None = None) -> bool:
    """Re-check eligibility before actually sending out a queued notification."""
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        # Check blocked
        async with db.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if row and row[0] == 1:
                return False

        # Check user_titles
        async with db.execute(
            "SELECT status, is_favorite FROM user_titles WHERE user_id = ? AND mal_id = ?",
            (user_id, mal_id),
        ) as cur:
            row = await cur.fetchone()
            if row:
                status, is_fav = row[0], bool(row[1])
                if status == "watching" or is_fav:
                    return True

        # Check subscriptions
        async with db.execute(
            "SELECT 1 FROM subscriptions WHERE user_id = ? AND mal_id = ?",
            (user_id, mal_id),
        ) as cur:
            if await cur.fetchone():
                return True

    return False


async def enqueue_events_and_update_baseline(
    mal_id: int,
    episodes: list[int],
    recipients: list[int],
    title: str,
    *,
    anilibria_code: str | None = None,
    yummy_url: str | None = None,
    shikimori_id: int | None = None,
    db_path: str | None = None,
) -> int:
    """Enqueues notification_outbox events and updates tracked_titles in a single atomic transaction."""
    if not episodes:
        return 0

    path = db_path or settings.db_path
    now = int(time.time())
    max_ep = max(episodes)
    enqueued_count = 0

    async with aiosqlite.connect(path) as db:
        await db.execute("BEGIN TRANSACTION")
        try:
            # 1. Insert into notification_outbox for every (user, episode)
            for ep in sorted(episodes):
                for uid in recipients:
                    cur = await db.execute(
                        """INSERT OR IGNORE INTO notification_outbox
                           (user_id, mal_id, episode, event_type, title, status, attempts, next_attempt_at, created_at)
                           VALUES (?, ?, ?, 'new_episode', ?, 'pending', 0, 0, ?)""",
                        (uid, mal_id, ep, title, now),
                    )
                    if cur.rowcount > 0:
                        enqueued_count += 1

            # 2. Update tracked_titles baseline
            await db.execute(
                """INSERT INTO tracked_titles (mal_id, title, anilibria_code, yummy_url, shikimori_id, last_known_episode, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(mal_id) DO UPDATE SET
                       title = CASE WHEN excluded.title != '' THEN excluded.title ELSE tracked_titles.title END,
                       anilibria_code = COALESCE(excluded.anilibria_code, tracked_titles.anilibria_code),
                       yummy_url = COALESCE(excluded.yummy_url, tracked_titles.yummy_url),
                       shikimori_id = COALESCE(excluded.shikimori_id, tracked_titles.shikimori_id),
                       last_known_episode = MAX(excluded.last_known_episode, tracked_titles.last_known_episode),
                       updated_at = excluded.updated_at""",
                (mal_id, title, anilibria_code, yummy_url, shikimori_id, max_ep, now),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    return enqueued_count


async def fetch_pending_events(limit: int = 20, now: int | None = None, db_path: str | None = None) -> list[dict]:
    path = db_path or settings.db_path
    cur_time = now if now is not None else int(time.time())
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            """SELECT id, user_id, mal_id, episode, event_type, title, status, attempts, next_attempt_at, created_at
               FROM notification_outbox
               WHERE status = 'pending' AND next_attempt_at <= ?
               ORDER BY id ASC LIMIT ?""",
            (cur_time, limit),
        ) as cur:
            rows = await cur.fetchall()

    return [
        {
            "id": r[0],
            "user_id": r[1],
            "mal_id": r[2],
            "episode": r[3],
            "event_type": r[4],
            "title": r[5],
            "status": r[6],
            "attempts": r[7],
            "next_attempt_at": r[8],
            "created_at": r[9],
        }
        for r in rows
    ]


async def claim_event_for_processing(event_id: int, db_path: str | None = None) -> int:
    """Atomic concurrency guard: transition status from pending -> processing.
    
    Increments generation counter (claim_token) and sets claimed_at lease timestamp.
    
    Returns:
        New generation claim_token (> 0) if claimed successfully, or 0 if claim failed.
    """
    path = db_path or settings.db_path
    now = int(time.time())
    async with aiosqlite.connect(path) as db:
        await db.execute(
            """UPDATE notification_outbox
               SET status = 'processing',
                   claimed_at = ?,
                   claim_token = COALESCE(claim_token, 0) + 1
               WHERE id = ? AND status = 'pending'""",
            (now, event_id),
        )
        if db.total_changes == 0:
            return 0

        async with db.execute(
            "SELECT claim_token FROM notification_outbox WHERE id = ?", (event_id,)
        ) as cur:
            row = await cur.fetchone()
            token = row[0] if row else 0

        await db.commit()
        return token


async def defer_event(
    event_id: int,
    retry_delay: int,
    error: str,
    claim_token: int,
    db_path: str | None = None,
) -> bool:
    """Postpones event due to external infrastructure dependency (e.g. missing tunnel URL).
    
    Guarantees:
    - Does NOT increment delivery attempt counter ('attempts').
    - Event does NOT fail due to missing tunnel.
    - Status is reset back to 'pending' with next_attempt_at = now + retry_delay.
    - Strict fencing token: only succeeds if claim_token matches current generation.
    """
    if not claim_token:
        raise ValueError("claim_token is required to defer an event safely")

    path = db_path or settings.db_path
    now = int(time.time())
    next_attempt = now + retry_delay
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            """UPDATE notification_outbox
               SET status = 'pending', next_attempt_at = ?, claimed_at = 0, last_error = ?
               WHERE id = ? AND status = 'processing' AND claim_token = ?""",
            (next_attempt, str(error)[:500], event_id, claim_token),
        )
        await db.commit()
        return cur.rowcount == 1


async def mark_event_sent(event_id: int, claim_token: int, db_path: str | None = None) -> bool:
    """Marks event as sent with strict generation counter fencing token verification."""
    if not claim_token:
        raise ValueError("claim_token is required to mark event sent safely")

    path = db_path or settings.db_path
    now = int(time.time())
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            """UPDATE notification_outbox
               SET status = 'sent', sent_at = ?, claimed_at = 0, last_error = NULL
               WHERE id = ? AND status = 'processing' AND claim_token = ?""",
            (now, event_id, claim_token),
        )
        await db.commit()
        return cur.rowcount == 1


async def mark_event_failed(
    event_id: int,
    error: str,
    retry_delay: int | None = None,
    max_attempts: int = 5,
    claim_token: int = 0,
    db_path: str | None = None,
) -> bool:
    """Handles transient or fatal error with limited retries and strict fencing token."""
    if not claim_token:
        raise ValueError("claim_token is required to mark event failed safely")

    path = db_path or settings.db_path
    now = int(time.time())
    async with aiosqlite.connect(path) as db:
        async with db.execute("SELECT attempts FROM notification_outbox WHERE id = ?", (event_id,)) as cur:
            row = await cur.fetchone()
        attempts = (row[0] + 1) if row else 1

        if retry_delay is None or attempts >= max_attempts:
            new_status = "failed"
            next_attempt = 0
        else:
            new_status = "pending"
            next_attempt = now + retry_delay

        cur = await db.execute(
            """UPDATE notification_outbox
               SET status = ?, attempts = ?, next_attempt_at = ?, claimed_at = 0, last_error = ?
               WHERE id = ? AND status = 'processing' AND claim_token = ?""",
            (new_status, attempts, next_attempt, str(error)[:500], event_id, claim_token),
        )
        await db.commit()
        return cur.rowcount == 1


async def mark_event_cancelled(
    event_id: int,
    reason: str,
    claim_token: int,
    db_path: str | None = None,
) -> bool:
    """Marks event as cancelled with strict fencing token verification."""
    if not claim_token:
        raise ValueError("claim_token is required to mark event cancelled safely")

    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            """UPDATE notification_outbox
               SET status = 'cancelled', claimed_at = 0, last_error = ?
               WHERE id = ? AND status = 'processing' AND claim_token = ?""",
            (str(reason)[:500], event_id, claim_token),
        )
        await db.commit()
        return cur.rowcount == 1


async def recover_stale_processing(timeout_seconds: int = 0, db_path: str | None = None) -> int:
    """Recovers events stuck in 'processing' (e.g. following process crash or expired lease).
    
    If timeout_seconds <= 0, recovers ALL events currently in 'processing' (ideal for startup crash recovery).
    If timeout_seconds > 0, recovers only events where claimed_at is older than timeout_seconds.
    """
    path = db_path or settings.db_path
    now = int(time.time())
    async with aiosqlite.connect(path) as db:
        if timeout_seconds <= 0:
            cur = await db.execute(
                "UPDATE notification_outbox SET status = 'pending', claimed_at = 0 WHERE status = 'processing'"
            )
        else:
            cur = await db.execute(
                """UPDATE notification_outbox
                   SET status = 'pending', claimed_at = 0
                   WHERE status = 'processing' AND (? - COALESCE(claimed_at, 0) >= ?)""",
                (now, timeout_seconds),
            )
        recovered = cur.rowcount
        await db.commit()
    return recovered
