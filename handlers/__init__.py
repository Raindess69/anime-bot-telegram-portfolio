from .backup import router as backup_router
from .commands import router as commands_router
from .donate import router as donate_router
from .history import router as history_router
from .menu import router as menu_router, main_menu_keyboard
from .mylist import router as mylist_router
from .search import router as search_router
from .callbacks import router as callbacks_router
from .inline import router as inline_router

__all__ = [
    "backup_router",
    "commands_router",
    "donate_router",
    "history_router",
    "menu_router",
    "main_menu_keyboard",
    "mylist_router",
    "search_router",
    "callbacks_router",
    "inline_router",
]
