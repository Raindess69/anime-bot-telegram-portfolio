import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
from db import init_db
from handlers import (
    backup_router,
    callbacks_router,
    commands_router,
    donate_router,
    history_router,
    inline_router,
    menu_router,
    mylist_router,
    search_router,
)
from services import run_periodic_check


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Order matters: commands & menu (reply-keyboard hits) first, then callbacks,
    # then inline, and finally the text_search catch-all which would otherwise
    # swallow menu button texts.
    dp.include_router(commands_router)
    dp.include_router(donate_router)
    dp.include_router(backup_router)
    dp.include_router(history_router)
    dp.include_router(menu_router)
    dp.include_router(mylist_router)
    dp.include_router(callbacks_router)
    dp.include_router(inline_router)
    dp.include_router(search_router)

    logging.info("Bot starting…")
    await bot.delete_webhook(drop_pending_updates=True)

    scheduler_task = asyncio.create_task(run_periodic_check(bot))
    try:
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")
