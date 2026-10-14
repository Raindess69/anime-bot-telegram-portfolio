from .history import init_history
from .outbox import init_outbox
from .subscriptions import init_subscriptions
from .user_titles import init_user_titles
from .users import init_db as _init_users, get_lang, is_registered, set_lang


async def init_db(db_path: str | None = None) -> None:
    await _init_users(db_path)
    await init_subscriptions(db_path)
    await init_history(db_path)
    await init_user_titles(db_path)
    await init_outbox(db_path)


__all__ = ["init_db", "get_lang", "is_registered", "set_lang", "init_outbox"]
