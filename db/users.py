import aiosqlite

from config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    lang TEXT NOT NULL DEFAULT 'ru'
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(_SCHEMA)
        await db.commit()


async def get_lang(user_id: int) -> str:
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
    if row is None:
        return settings.default_lang
    return row[0]


async def is_registered(user_id: int) -> bool:
    """True once the user has picked a language — gates the first-time onboarding."""
    async with aiosqlite.connect(settings.db_path) as db:
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cur:
            return await cur.fetchone() is not None


async def set_lang(user_id: int, lang: str) -> None:
    if lang not in ("ru", "en", "uk"):
        raise ValueError(f"Unsupported language: {lang}")
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            "INSERT INTO users (user_id, lang) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET lang = excluded.lang",
            (user_id, lang),
        )
        await db.commit()
