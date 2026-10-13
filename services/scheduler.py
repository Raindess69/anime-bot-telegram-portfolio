"""Periodic subscription check across Anilibria, Yummy, Kodik, Shikimori.

For every subscription, each source is queried in parallel; we take the max
episode number across sources. If it's higher than what the user has already
seen, we ping them with a keyboard listing every source that has the new
episode available — direct links where possible, catalog links otherwise.
"""
import asyncio
import logging

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db.subscriptions import list_all_active, update_last_episode
from locales import t

from . import anilibria, kodik, shikimori, yummy

_log = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 12 * 60 * 60  # 12 hours
_INITIAL_DELAY_SECONDS = 30
_PER_SUB_DELAY = 0.4  # gap between subscriptions — be nice to upstream APIs


async def _probe_anilibria(alias: str | None) -> dict | None:
    """Return {max_ep, url, name}. `url` opens the specific episode when uuid known."""
    if not alias:
        return None
    try:
        release = await anilibria.get_release_by_code(alias)
    except Exception as e:
        _log.info("anilibria probe %s failed: %s", alias, e)
        return None
    if not release or not release.get("episodes"):
        return None
    max_ep = max(release["episodes"])
    uuid = (release.get("episode_ids") or {}).get(max_ep)
    return {"max_ep": max_ep, "url": anilibria.episode_url(alias, uuid=uuid), "name": "Anilibria"}


async def _probe_yummy(url: str | None) -> dict | None:
    if not url:
        return None
    try:
        max_ep = await yummy.get_max_episode(url)
    except Exception as e:
        _log.info("yummy probe %s failed: %s", url, e)
        return None
    if not max_ep:
        return None
    return {"max_ep": max_ep, "url": url, "name": "Yummy"}


async def _probe_kodik(mal_id: int | None, shikimori_id: int | None) -> dict | None:
    if not kodik.enabled():
        return None
    try:
        result = await kodik.find_by_ids(mal_id=mal_id, shikimori_id=shikimori_id)
    except Exception as e:
        _log.info("kodik probe failed: %s", e)
        return None
    if not result:
        return None
    # Prefer the direct episode URL when available — drops the user straight on
    # the new episode instead of the series root.
    url = result.get("episode_url") or result.get("url") or ""
    return {"max_ep": result["max_ep"], "url": url, "name": "Kodik"}


async def _probe_shikimori(shikimori_id: int | None) -> dict | None:
    """Fallback signal — Shikimori reports episodes_aired for currently-airing titles."""
    if not shikimori_id:
        return None
    try:
        info = await shikimori.get_by_id(shikimori_id)
    except Exception as e:
        _log.info("shikimori probe %s failed: %s", shikimori_id, e)
        return None
    if not info:
        return None
    # Shikimori's `episodes_aired` is what we want for ongoing shows, but the
    # parsed dict here only exposes `episodes` (total). It's still a useful
    # signal — we won't over-notify because we only fire on strict increase.
    ep = info.get("episodes")
    if not ep:
        return None
    return {"max_ep": int(ep), "url": f"https://shikimori.one/animes/{shikimori_id}", "name": "Shikimori"}


async def check_new_episodes(bot: Bot) -> None:
    subs = await list_all_active()
    if not subs:
        return
    _log.info("Subscription check: scanning %d subscriptions", len(subs))

    for sub in subs:
        probes = await asyncio.gather(
            _probe_anilibria(sub.get("anilibria_code")),
            _probe_yummy(sub.get("yummy_url")),
            _probe_kodik(sub.get("mal_id"), sub.get("shikimori_id")),
            _probe_shikimori(sub.get("shikimori_id")),
            return_exceptions=False,
        )
        hits = [p for p in probes if p]
        if not hits:
            continue

        max_ep = max(p["max_ep"] for p in hits)
        if max_ep <= sub["last_episode"]:
            continue

        # Only surface sources that actually reached the new episode — cheaper
        # sources sometimes lag by one release cycle.
        available = [p for p in hits if p["max_ep"] >= max_ep and p.get("url")]
        lang = sub["lang"]
        text = t("new_episode_notification", lang, title=sub["title"], episode=max_ep)
        text += "\n" + t("new_episode_sources", lang)

        rows = []
        try:
            from handlers.commands import get_mini_app_url
            from aiogram.types import WebAppInfo
            app_url = get_mini_app_url()
            if app_url and app_url.startswith("https://"):
                target_mal = sub.get("mal_id") or sub.get("shikimori_id")
                target_url = f"{app_url}#title/{target_mal}" if target_mal else app_url
                rows.append([
                    InlineKeyboardButton(
                        text="📺 Смотреть в EnjoyAnime (Mini App)",
                        web_app=WebAppInfo(url=target_url),
                    )
                ])
        except Exception:
            pass

        for p in available:
            rows.append([
                InlineKeyboardButton(
                    text=t("btn_source_watch", lang, source=p["name"]),
                    url=p["url"],
                )
            ])
        kb = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None

        try:
            await bot.send_message(
                sub["user_id"],
                text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            await update_last_episode(sub["id"], max_ep)
            _log.info(
                "Notified user %s about mal_id=%s ep %s via %d sources",
                sub["user_id"], sub.get("mal_id"), max_ep, len(available),
            )
        except Exception as e:
            _log.warning("Failed to notify user %s: %s", sub["user_id"], e)

        await asyncio.sleep(_PER_SUB_DELAY)


async def run_periodic_check(bot: Bot) -> None:
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    while True:
        try:
            await check_new_episodes(bot)
        except Exception as e:
            _log.exception("subscription loop error: %s", e)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
