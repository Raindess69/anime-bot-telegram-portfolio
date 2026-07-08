from .history import init_history
from .subscriptions import init_subscriptions
from .users import init_db as _init_users, get_lang, is_registered, set_lang


async def init_db() -> None:
    await _init_users()
    await init_subscriptions()
    await init_history()


__all__ = ["init_db", "get_lang", "is_registered", "set_lang"]
