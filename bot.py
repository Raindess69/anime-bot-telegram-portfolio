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


def sanitize_no_proxy() -> None:
    """Fix common proxy/no_proxy formatting errors in sandbox environments."""
    for key in ("NO_PROXY", "no_proxy"):
        val = os.getenv(key)
        if val:
            cleaned = []
            for item in val.split(","):
                item = item.strip().lstrip("*.")
                if item:
                    cleaned.append(item)
            cleaned_str = ",".join(cleaned)
            os.environ[key] = cleaned_str


def get_current_proxy() -> str | None:
    """Read proxy from os.environ or reload fresh credentials from .env."""
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except Exception:
        pass
    return (
        os.getenv("HTTPS_PROXY")
        or os.getenv("HTTP_PROXY")
        or os.getenv("https_proxy")
        or os.getenv("http_proxy")
    )


def mask_proxy(proxy_url: str | None) -> str:
    if not proxy_url:
        return "direct"
    if "@" in proxy_url:
        schema_and_creds, host = proxy_url.split("@", 1)
        schema = schema_and_creds.split("://", 1)[0] if "://" in schema_and_creds else "http"
        return f"{schema}://***@{host}"
    return proxy_url


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    sanitize_no_proxy()
    await init_db()

    initial_proxy = get_current_proxy()
    session = AiohttpSession(proxy=initial_proxy) if initial_proxy else None

    bot = Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(commands_router)
    dp.include_router(donate_router)
    dp.include_router(backup_router)
    dp.include_router(history_router)
    dp.include_router(menu_router)
    dp.include_router(mylist_router)
    dp.include_router(callbacks_router)
    dp.include_router(inline_router)
    dp.include_router(search_router)

    logging.info("Bot initializing…")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.warning("Initial delete_webhook failed (will retry in polling): %s", e)

    # Configure Chat Menu Button to open Mini App directly
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
    logging.info("Mini App web server listening on %s:%s", settings.web_host, settings.web_port)

    scheduler_task = asyncio.create_task(run_periodic_check(bot))

    # Self-healing polling loop: auto-recovers within 3s when sandbox rotates proxy credentials
    try:
        while True:
            try:
                sanitize_no_proxy()
                current_proxy = get_current_proxy()
                logging.info("Starting Telegram polling (proxy=%s)…", mask_proxy(current_proxy))
                await dp.start_polling(bot)
                break
            except asyncio.CancelledError:
                break
            except Exception as err:
                logging.warning(
                    "Telegram polling interrupted (%s: %s). Re-reading fresh proxy and reconnecting in 3s…",
                    type(err).__name__,
                    err,
                )
                await asyncio.sleep(3)

                # Reconnect with fresh proxy session
                try:
                    if bot.session and not bot.session.closed:
                        await bot.session.close()
                except Exception:
                    pass
                fresh_proxy = get_current_proxy()
                bot.session = AiohttpSession(proxy=fresh_proxy) if fresh_proxy else None
    finally:
        scheduler_task.cancel()
        web_server.should_exit = True
        try:
            if bot.session and not bot.session.closed:
                await bot.session.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")
