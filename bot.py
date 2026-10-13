import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
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

    # Support proxy when running in sandboxed or firewalled cloud environments
    proxy = (
        os.getenv("HTTPS_PROXY")
        or os.getenv("HTTP_PROXY")
        or os.getenv("https_proxy")
        or os.getenv("http_proxy")
    )
    session = AiohttpSession(proxy=proxy) if proxy else None

    bot = Bot(
        token=settings.bot_token,
        session=session,
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

    # Optional: configure Chat Menu Button to open Mini App directly
    try:
        from aiogram.types import MenuButtonWebApp, WebAppInfo
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="📺 Mini App",
                web_app=WebAppInfo(url=settings.mini_app_url),
            )
        )
    except Exception as e:
        logging.info("Could not set chat menu button: %s", e)

    import uvicorn
    from web_api import app as api_app

    web_config = uvicorn.Config(
        app=api_app,
        host=settings.web_host,
        port=settings.web_port,
        log_level="warning",
    )
    web_server = uvicorn.Server(web_config)
    web_task = asyncio.create_task(web_server.serve())

    scheduler_task = asyncio.create_task(run_periodic_check(bot))
    try:
        logging.info("Mini App web server listening on %s:%s", settings.web_host, settings.web_port)
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()
        web_server.should_exit = True


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")
