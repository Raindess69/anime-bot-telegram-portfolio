"""Periodic subscription and library check for new episodes with reliable SQLite Outbox.

Features:
- Monitors unique titles across user_titles (status='watching' or is_favorite=1) and subscriptions.
- One probe query per unique title per cycle across video providers (Anilibria, Kodik, Yummy).
- First observation sets baseline without sending old episodes.
- Enqueues events into notification_outbox in an atomic SQLite transaction.
- Dispatcher claims events atomically, re-checks recipient eligibility, formats safe HTML,
  builds Mini App button (startapp=w_{mal_id}_{episode}), and handles Telegram rate limits
  (RetryAfter) and blocks (Forbidden).
- Clean cancellation support (CancelledError is never swallowed).
"""
import asyncio
import html
import logging
import time

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from config import settings
from db import outbox as outbox_db
from db import users as users_db
from locales import t

from . import anilibria, kodik, yummy

_log = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 12 * 60 * 60  # 12 hours
_INITIAL_DELAY_SECONDS = 30
_PER_TITLE_DELAY = 0.4  # gap between upstream API probes
_OUTBOX_BATCH_SIZE = 20

_scan_lock = asyncio.Lock()
_telegram_flood_until: float = 0.0


def build_watch_url(mal_id: int, episode: int) -> str | None:
    """Builds Mini App launch URL retaining startapp=w_{mal_id}_{episode} format."""
    try:
        from handlers.commands import get_mini_app_url
        app_url = get_mini_app_url()
        if app_url and app_url.startswith("https://"):
            return f"{app_url}?startapp=w_{mal_id}_{episode}#w_{mal_id}_{episode}"
    except Exception as e:
        _log.debug("Failed to get mini app url: %s", e)
    return None


def build_watch_keyboard(mal_id: int, episode: int, lang: str = "ru") -> InlineKeyboardMarkup | None:
    """Constructs keyboard with Watch button or None if URL is missing/invalid."""
    url = build_watch_url(mal_id, episode)
    if not url:
        return None
    button_text = t("btn_watch_episode_generic", lang)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=button_text,
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )


async def _probe_anilibria(alias: str | None) -> dict | None:
    """Probes Anilibria API for available episodes list."""
    if not alias:
        return None
    try:
        release = await anilibria.get_release_by_code(alias)
    except Exception as e:
        _log.info("Anilibria probe %s failed: %s", alias, e)
        return None
    if not release or not release.get("episodes"):
        return None
    eps = [int(x) for x in release["episodes"] if isinstance(x, (int, str)) and str(x).isdigit()]
    if not eps:
        return None
    return {"episodes": eps, "max_ep": max(eps), "name": "Anilibria"}


async def _probe_kodik(mal_id: int | None, shikimori_id: int | None) -> dict | None:
    """Probes Kodik CDN for newest available episode."""
    if not kodik.enabled():
        return None
    try:
        result = await kodik.find_by_ids(mal_id=mal_id, shikimori_id=shikimori_id)
    except Exception as e:
        _log.info("Kodik probe failed: %s", e)
        return None
    if not result or not result.get("max_ep"):
        return None
    return {"max_ep": int(result["max_ep"]), "name": "Kodik"}


async def _probe_yummy(url: str | None) -> dict | None:
    """Probes YummyAnime player page for newest available episode."""
    if not url:
        return None
    try:
        max_ep = await yummy.get_max_episode(url)
    except Exception as e:
        _log.info("Yummy probe %s failed: %s", url, e)
        return None
    if not max_ep:
        return None
    return {"max_ep": int(max_ep), "name": "Yummy"}


async def check_new_episodes(bot: Bot | None = None, db_path: str | None = None) -> int:
    """Scans all unique monitored titles once per sweep and enqueues new episode notifications.

    Returns the number of newly enqueued outbox events.
    """
    if _scan_lock.locked():
        _log.warning("Subscription check is already running. Skipping overlapping execution.")
        return 0

    async with _scan_lock:
        monitored = await outbox_db.get_all_monitored_titles(db_path=db_path)
        if not monitored:
            return 0

        _log.info("Checking new episodes across %d monitored titles", len(monitored))
        total_enqueued = 0

        for item in monitored:
            mal_id = item["mal_id"]
            title = item.get("title") or f"Anime #{mal_id}"
            anilibria_code = item.get("anilibria_code")
            yummy_url = item.get("yummy_url")
            shikimori_id = item.get("shikimori_id")

            # Check existing baseline
            tracked = await outbox_db.get_tracked_title(mal_id, db_path=db_path)

            try:
                # Query video sources in parallel
                probes = await asyncio.gather(
                    _probe_anilibria(anilibria_code),
                    _probe_kodik(mal_id, shikimori_id),
                    _probe_yummy(yummy_url),
                    return_exceptions=True,
                )
            except Exception as e:
                _log.warning("Probes error for mal_id=%s: %s", mal_id, e)
                continue

            confirmed_episodes: set[int] = set()
            for p in probes:
                if isinstance(p, dict):
                    if p.get("episodes"):
                        confirmed_episodes.update(p["episodes"])
                    elif p.get("max_ep"):
                        # Only the latest confirmed episode from this source
                        confirmed_episodes.add(p["max_ep"])

            if not confirmed_episodes:
                # Upstream error, timeout, or no video found; do not alter baseline
                await asyncio.sleep(_PER_TITLE_DELAY)
                continue

            max_confirmed = max(confirmed_episodes)

            # First observation of this title: set baseline point without sending historical catalogue
            if tracked is None:
                await outbox_db.set_tracked_title_baseline(
                    mal_id=mal_id,
                    episode=max_confirmed,
                    title=title,
                    anilibria_code=anilibria_code,
                    yummy_url=yummy_url,
                    shikimori_id=shikimori_id,
                    db_path=db_path,
                )
                _log.info("Established baseline for new title mal_id=%s (%s) at ep %s", mal_id, title, max_confirmed)
                await asyncio.sleep(_PER_TITLE_DELAY)
                continue

            baseline = tracked["last_known_episode"]

            # Filter for genuinely new confirmed episodes above baseline
            new_eps = sorted([ep for ep in confirmed_episodes if ep > baseline])
            if not new_eps:
                await asyncio.sleep(_PER_TITLE_DELAY)
                continue

            # Identify eligible recipients
            recipients = await outbox_db.get_eligible_subscribers(mal_id, db_path=db_path)
            if recipients:
                count = await outbox_db.enqueue_events_and_update_baseline(
                    mal_id=mal_id,
                    episodes=new_eps,
                    recipients=recipients,
                    title=title,
                    anilibria_code=anilibria_code,
                    yummy_url=yummy_url,
                    shikimori_id=shikimori_id,
                    db_path=db_path,
                )
                total_enqueued += count
                _log.info(
                    "Enqueued %d notifications for mal_id=%s eps=%s across %d recipients",
                    count, mal_id, new_eps, len(recipients),
                )
            else:
                # No current recipients, but advance baseline so historical episodes aren't queued later
                await outbox_db.set_tracked_title_baseline(
                    mal_id=mal_id,
                    episode=max(new_eps),
                    title=title,
                    anilibria_code=anilibria_code,
                    yummy_url=yummy_url,
                    shikimori_id=shikimori_id,
                    db_path=db_path,
                )

            await asyncio.sleep(_PER_TITLE_DELAY)

        return total_enqueued


async def dispatch_pending_outbox(bot: Bot, db_path: str | None = None, limit: int = _OUTBOX_BATCH_SIZE) -> int:
    """Dispatches pending notifications from the SQLite Outbox queue.

    Returns the number of successfully delivered messages.
    """
    if settings.disable_outbox_dispatch:
        _log.info("Outbox dispatch is disabled (DISABLE_OUTBOX_DISPATCH=True); skipping notification dispatch.")
        return 0

    global _telegram_flood_until
    if time.time() < _telegram_flood_until:
        _log.warning("Telegram flood control active; skipping dispatch until %s", _telegram_flood_until)
        return 0

    pending = await outbox_db.fetch_pending_events(limit=limit, db_path=db_path)
    if not pending:
        return 0

    sent_count = 0

    for event in pending:
        event_id = event["id"]
        user_id = event["user_id"]
        mal_id = event["mal_id"]
        episode = event["episode"]

        # Atomic concurrency claim
        claimed = await outbox_db.claim_event_for_processing(event_id, db_path=db_path)
        if not claimed:
            continue

        # Re-check recipient eligibility before sending
        eligible = await outbox_db.is_user_eligible(user_id, mal_id, db_path=db_path)
        if not eligible:
            await outbox_db.mark_event_cancelled(
                event_id,
                "User no longer eligible (unsubscribed/cancelled)",
                claim_token=claimed,
                db_path=db_path,
            )
            continue

        # Get recipient language
        lang = await users_db.get_lang(user_id, db_path=db_path)

        # Check Mini App URL and build keyboard
        kb = build_watch_keyboard(mal_id, episode, lang)
        if kb is None:
            # URL missing or invalid; postpone without consuming delivery attempts!
            await outbox_db.defer_event(
                event_id,
                retry_delay=60,
                error="Mini App URL not available or not HTTPS",
                claim_token=claimed,
                db_path=db_path,
            )
            continue

        # Safe HTML formatting
        raw_title = event["title"] or f"Anime #{mal_id}"
        escaped_title = html.escape(raw_title)
        message_text = t("new_episode_push", lang, title=escaped_title, episode=episode)

        try:
            await bot.send_message(
                chat_id=user_id,
                text=message_text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            await outbox_db.mark_event_sent(event_id, claim_token=claimed, db_path=db_path)
            sent_count += 1
        except TelegramForbiddenError as err:
            # User blocked the bot or deactivated account
            _log.info("User %s blocked bot: %s", user_id, err)
            await users_db.set_user_blocked(user_id, True, db_path=db_path)
            await outbox_db.mark_event_failed(event_id, f"Forbidden: {err}", retry_delay=None, claim_token=claimed, db_path=db_path)
        except TelegramRetryAfter as err:
            retry_after = getattr(err, "retry_after", 30)
            _telegram_flood_until = time.time() + retry_after
            _log.warning("Telegram flood control: retry after %ss", retry_after)
            await outbox_db.mark_event_failed(
                event_id,
                f"Flood control: {retry_after}s",
                retry_delay=retry_after,
                max_attempts=10,
                claim_token=claimed,
                db_path=db_path,
            )
            # Break batch early to respect Telegram's rate limit
            break
        except Exception as err:
            attempts = event["attempts"] + 1
            delay = 60 * (2 ** min(attempts - 1, 4))
            _log.warning("Failed to send notification %s to user %s: %s", event_id, user_id, err)
            await outbox_db.mark_event_failed(
                event_id,
                f"{type(err).__name__}: {err}",
                retry_delay=delay,
                max_attempts=5,
                claim_token=claimed,
                db_path=db_path,
            )

    return sent_count


async def run_periodic_check(bot: Bot, db_path: str | None = None) -> None:
    """Long-running background task for periodic subscription polling and queue processing."""
    _log.info("Scheduler started.")
    try:
        # Recover any stale events left in 'processing' from prior process runs on startup
        recovered = await outbox_db.recover_stale_processing(timeout_seconds=0, db_path=db_path)
        if recovered:
            _log.info("Recovered %d stale processing events on startup", recovered)

        await asyncio.sleep(_INITIAL_DELAY_SECONDS)
        while True:
            try:
                # Recover expired leases during periodic sweep
                await outbox_db.recover_stale_processing(timeout_seconds=300, db_path=db_path)
                await check_new_episodes(bot, db_path=db_path)
                await dispatch_pending_outbox(bot, db_path=db_path)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                _log.exception("Scheduler sweep error: %s", e)

            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        _log.info("Scheduler background task cancelled cleanly.")
        raise
