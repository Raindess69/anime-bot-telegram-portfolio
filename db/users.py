import aiosqlite

from config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    lang TEXT NOT NULL DEFAULT 'ru',
    is_blocked INTEGER NOT NULL DEFAULT 0
);
"""


async def init_db(db_path: str | None = None) -> None:
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        await db.execute(_SCHEMA)
        try:
            await db.execute("ALTER TABLE users ADD COLUMN is_blocked INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        await db.commit()


async def get_lang(user_id: int, db_path: str | None = None) -> str:
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        async with db.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
    if row is None:
        return settings.default_lang
    return row[0]


async def is_registered(user_id: int, db_path: str | None = None) -> bool:
    """True once the user has picked a language — gates the first-time onboarding."""
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cur:
            return await cur.fetchone() is not None


async def set_lang(user_id: int, lang: str, db_path: str | None = None) -> None:
    if lang not in ("ru", "en", "uk"):
        raise ValueError(f"Unsupported language: {lang}")
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "INSERT INTO users (user_id, lang, is_blocked) VALUES (?, ?, 0) "
            "ON CONFLICT(user_id) DO UPDATE SET lang = excluded.lang, is_blocked = 0",
            (user_id, lang),
        )
        await db.commit()


async def is_user_blocked(user_id: int, db_path: str | None = None) -> bool:
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        async with db.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
    if not row:
        return False
    return bool(row[0])


async def set_user_blocked(user_id: int, is_blocked: bool = True, db_path: str | None = None) -> None:
    path = db_path or settings.db_path
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "INSERT INTO users (user_id, is_blocked) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET is_blocked = excluded.is_blocked",
            (user_id, 1 if is_blocked else 0),
        )
        await db.commit()
