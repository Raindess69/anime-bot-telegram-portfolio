"""Browsing UI for the per-user title tracker (db/user_titles.py): category
lists (watching/plan/completed/dropped), favorites, stats, and opening a
tracked entry back into a full result card.

Entry point lives in handlers/menu.py (the "📋 Мой список" picker + the
"mylist:home" back-handler) — this router only handles what the picker's
buttons point at, plus the "open card" callback for items inside a list."""
import logging

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from db import get_lang, user_titles
from locales import t
from models import AnimeCard
from services import aggregator, jikan
from utils.cache import search_cache

from .search import send_result

router = Router(name="mylist")
_log = logging.getLogger(__name__)

_PAGE_SIZE = 10

_CATEGORY_KEYS = {
    "watching": "status_watching",
    "plan": "status_plan",
    "completed": "status_completed",
    "dropped": "status_dropped",
}


def _category_label(status: str, lang: str) -> str:
    key = _CATEGORY_KEYS.get(status)
    return t(key, lang) if key else t("mylist_cat_fav", lang)


def _list_keyboard(items: list[dict], page: int, lang: str, nav_prefix: str) -> InlineKeyboardMarkup:
    total = len(items)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * _PAGE_SIZE
    chunk = items[start : start + _PAGE_SIZE]

    rows: list[list[InlineKeyboardButton]] = []
    for i, row in enumerate(chunk):
        n = start + i + 1
        ep = row.get("current_episode", 0)
        if ep and ep > 0:
            label = t("mylist_item", lang, n=n, title=row["title"], ep=ep)
        else:
            label = t("mylist_item_no_progress", lang, n=n, title=row["title"])
        rows.append([InlineKeyboardButton(text=label, callback_data=f"mlopen:{row['mal_id']}")])

    if total_pages > 1:
        prev_page = (page - 1) % total_pages
        next_page = (page + 1) % total_pages
        rows.append([
            InlineKeyboardButton(text="◀", callback_data=f"{nav_prefix}:{prev_page}"),
            InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton(text="▶", callback_data=f"{nav_prefix}:{next_page}"),
        ])

    rows.append([InlineKeyboardButton(text=t("btn_back", lang), callback_data="mylist:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _edit_view(call: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        if call.message.photo:
            await call.message.edit_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception as e:
        _log.info("mylist view edit failed: %s", e)


async def _render_list(call: CallbackQuery, lang: str, category_label: str, items: list[dict], page: int, nav_prefix: str) -> None:
    header = t("mylist_header", lang, category=category_label)
    if not items:
        text = f"{header}\n\n{t('mylist_empty', lang)}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t("btn_back", lang), callback_data="mylist:home")]])
    else:
        text = header
        kb = _list_keyboard(items, page, lang, nav_prefix)
    await _edit_view(call, text, kb)


@router.callback_query(lambda c: c.data and c.data.startswith("mylist:cat:"))
async def cb_mylist_cat(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    if len(parts) != 4:
        await call.answer()
        return
    status = parts[2]
    try:
        page = int(parts[3])
    except ValueError:
        page = 0

    lang = await get_lang(call.from_user.id)
    items = await user_titles.list_by_status(call.from_user.id, status)
    await _render_list(call, lang, _category_label(status, lang), items, page, f"mylist:cat:{status}")
    await call.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("mylist:fav:"))
async def cb_mylist_fav(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer()
        return
    try:
        page = int(parts[2])
    except ValueError:
        page = 0

    lang = await get_lang(call.from_user.id)
    items = await user_titles.list_favorites(call.from_user.id)
    await _render_list(call, lang, t("mylist_cat_fav", lang), items, page, "mylist:fav")
    await call.answer()


@router.callback_query(lambda c: c.data == "mylist:stats")
async def cb_mylist_stats(call: CallbackQuery) -> None:
    lang = await get_lang(call.from_user.id)
    stats = await user_titles.get_stats(call.from_user.id)
    text = t(
        "mylist_stats_text", lang,
        watching=stats["watching"], completed=stats["completed"], plan=stats["plan"],
        dropped=stats["dropped"], favorites=stats["favorites"], episodes=stats["episodes_watched"],
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t("btn_back", lang), callback_data="mylist:home")]])
    await _edit_view(call, text, kb)
    await call.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("mlopen:"))
async def cb_mylist_open(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    if len(parts) != 2:
        await call.answer()
        return
    try:
        mal_id = int(parts[1])
    except ValueError:
        await call.answer()
        return

    lang = await get_lang(call.from_user.id)
    try:
        raw = await jikan.get_by_id(mal_id)
    except Exception as e:
        _log.exception("mylist open jikan lookup crashed: %s", e)
        raw = None

    if not raw:
        await call.answer(t("api_error", lang), show_alert=True)
        return

    await call.answer(t("searching", lang))
    card = AnimeCard(**{k: v for k, v in raw.items() if v is not None})
    await aggregator._enrich_watch_links([card], lang)
    await search_cache.set(f"{lang}:__list:mylist", [card])
    await send_result(call.message, [card], 0, lang, user_id=call.from_user.id)
