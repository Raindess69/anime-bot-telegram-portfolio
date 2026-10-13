"""Persistent-menu router: reply keyboard + vibe/top wizards + random + subs/help."""
import logging
import random
from datetime import date

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from db import get_lang
from db.subscriptions import list_subscriptions
from locales import t
from models import AnimeCard
from services import aggregator, jikan
from utils.cache import search_cache

from .search import send_result

router = Router(name="menu")
_log = logging.getLogger(__name__)

_LIST_SIZE = 10
_ROWS_PER_LIST = 5  # 5 buttons per row → 2 rows for 10 items


class VibeStates(StatesGroup):
    year = State()
    score = State()
    genre = State()
    type_ = State()


# --- Reply keyboard -----------------------------------------------------------

_MENU_KEYS = (
    "menu_search", "menu_vibe", "menu_mylist", "menu_top", "menu_random",
    "menu_subs", "menu_history", "menu_help", "menu_donate",
)


def _menu_texts(lang: str) -> dict[str, str]:
    return {k: t(k, lang) for k in _MENU_KEYS}


def _all_menu_texts() -> set[str]:
    """Every localized label for menu buttons — used to intercept text hits."""
    out: set[str] = set()
    for lang in ("ru", "en", "uk"):
        for k in _MENU_KEYS:
            out.add(t(k, lang))
    return out


ALL_MENU_TEXTS = _all_menu_texts()


def main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    labels = _menu_texts(lang)
    # 3×3 layout — donate lives on the last row next to help so it's always
    # visible but never in the "hot spot" where accidental taps happen.
    rows = [
        [KeyboardButton(text=labels["menu_search"]), KeyboardButton(text=labels["menu_vibe"]), KeyboardButton(text=labels["menu_mylist"])],
        [KeyboardButton(text=labels["menu_top"]), KeyboardButton(text=labels["menu_random"]), KeyboardButton(text=labels["menu_subs"])],
        [KeyboardButton(text=labels["menu_history"]), KeyboardButton(text=labels["menu_help"]), KeyboardButton(text=labels["menu_donate"])],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def _match(message: Message, lang: str, key: str) -> bool:
    return message.text == t(key, lang)


# --- List rendering (used by vibe + top) --------------------------------------

def _list_keyboard(count: int, lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i in range(count):
        row.append(InlineKeyboardButton(text=t("list_open_card", lang, n=i + 1), callback_data=f"nav:{i}"))
        if len(row) == _ROWS_PER_LIST:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _episode_progress(card: AnimeCard) -> str | None:
    """"released/total" episode count (e.g. "3/13") from whichever watch source
    got enriched — this is real availability, not MAL's often-null `episodes`
    field for still-airing titles."""
    available = len(card.episodes_available) or len(card.kodik_episodes)
    if not available:
        return None
    return f"{available}/{card.episodes}" if card.episodes else f"{available}/?"


def _format_list(cards: list[AnimeCard], lang: str, header: str) -> str:
    lines = [t("list_header", lang, title=header)]
    for i, card in enumerate(cards, 1):
        title = card.primary_title(lang)
        score = f"{card.score:.2f}" if card.score is not None else t("unknown", lang)
        if card.year:
            line = t("list_item", lang, n=i, title=title, score=score, year=card.year)
        else:
            line = t("list_item_no_year", lang, n=i, title=title, score=score)
        progress = _episode_progress(card)
        if progress:
            line += f" · {progress}"
        lines.append(line)
    return "\n".join(lines)


async def _send_list(message: Message, cards: list[AnimeCard], lang: str, header: str) -> None:
    caption = _format_list(cards, lang, header)
    kb = _list_keyboard(len(cards), lang)
    poster = cards[0].image_url if cards else None
    if poster:
        try:
            await message.answer_photo(photo=poster, caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
            return
        except Exception as e:
            _log.info("list answer_photo failed, fallback to text: %s", e)
    await message.answer(caption, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True)


async def _cache_list(cards: list[AnimeCard], lang: str, tag: str) -> None:
    """Save the list so nav:<idx> callbacks can find it via _find_cards_for_message."""
    await search_cache.set(f"{lang}:__list:{tag}", cards)


# --- Menu handlers ------------------------------------------------------------

@router.message(F.text.in_(ALL_MENU_TEXTS))
async def on_menu_text(message: Message, state: FSMContext) -> None:
    lang = await get_lang(message.from_user.id)
    await state.clear()

    if _match(message, lang, "menu_search"):
        await message.answer(t("search_prompt", lang), parse_mode=ParseMode.HTML)
        return
    if _match(message, lang, "menu_vibe"):
        await _start_vibe(message, lang, state)
        return
    if _match(message, lang, "menu_mylist"):
        await _do_mylist(message, lang)
        return
    if _match(message, lang, "menu_top"):
        await message.answer(t("top_intro", lang), parse_mode=ParseMode.HTML, reply_markup=_top_keyboard(lang))
        return
    if _match(message, lang, "menu_random"):
        await _do_random(message, lang)
        return
    if _match(message, lang, "menu_subs"):
        await _do_subs(message, lang)
        return
    if _match(message, lang, "menu_history"):
        from .history import cmd_history
        await cmd_history(message)
        return
    if _match(message, lang, "menu_help"):
        await message.answer(t("help", lang), parse_mode=ParseMode.HTML)
        return
    if _match(message, lang, "menu_donate"):
        from .donate import cmd_donate
        await cmd_donate(message)
        return


@router.message(F.text & ~F.text.startswith("/"), StateFilter(VibeStates))
async def on_vibe_stray_text(message: Message, state: FSMContext) -> None:
    """User typed instead of tapping a vibe-wizard button. Registered after
    on_menu_text so menu buttons still short-circuit here first. Cancels the
    wizard (its inline buttons go stale but harmless) and treats the text as
    a normal search instead of silently swallowing it."""
    await state.clear()
    from .search import text_search
    await text_search(message)


# --- Random -------------------------------------------------------------------

async def _do_random(message: Message, lang: str) -> None:
    status = await message.answer(t("random_searching", lang))
    try:
        raw = await aggregator.random_anime()
    except Exception as e:
        _log.exception("random_anime crashed: %s", e)
        raw = None
    try:
        await status.delete()
    except Exception:
        pass
    if not raw:
        await message.answer(t("random_failed", lang))
        return
    card = AnimeCard(**{k: v for k, v in raw.items() if v is not None})
    await aggregator._enrich_watch_links([card], lang)
    await _cache_list([card], lang, "random")
    await send_result(message, [card], 0, lang, user_id=message.from_user.id)


@router.message(Command("planrandom"))
async def cmd_plan_random(message: Message) -> None:
    """Picks a random title from the user's "plan to watch" tracking list and
    shows it as a normal result card, re-fetched fresh from Jikan (the tracked
    row only stores mal_id/title, not the full card data)."""
    lang = await get_lang(message.from_user.id)
    from db import user_titles

    plan_list = await user_titles.list_by_status(message.from_user.id, "plan")
    if not plan_list:
        await message.answer(t("planrandom_empty", lang), parse_mode=ParseMode.HTML)
        return

    pick = random.choice(plan_list)
    status = await message.answer(t("random_searching", lang))
    try:
        raw = await jikan.get_by_id(pick["mal_id"])
    except Exception as e:
        _log.exception("planrandom jikan lookup crashed: %s", e)
        raw = None
    try:
        await status.delete()
    except Exception:
        pass
    if not raw:
        await message.answer(t("random_failed", lang))
        return

    card = AnimeCard(**{k: v for k, v in raw.items() if v is not None})
    await aggregator._enrich_watch_links([card], lang)
    await _cache_list([card], lang, "planrandom")
    await send_result(message, [card], 0, lang, user_id=message.from_user.id)


# --- My list (tracker browser) -------------------------------------------------
# The actual tab list rendering / stats / open-card handlers live in
# handlers/mylist.py (separate router) — this is just the entry picker.

def _mylist_home_keyboard(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t("status_watching", lang), callback_data="mylist:cat:watching:0")],
        [InlineKeyboardButton(text=t("status_plan", lang), callback_data="mylist:cat:plan:0")],
        [InlineKeyboardButton(text=t("status_completed", lang), callback_data="mylist:cat:completed:0")],
        [InlineKeyboardButton(text=t("status_dropped", lang), callback_data="mylist:cat:dropped:0")],
        [InlineKeyboardButton(text=t("mylist_cat_fav", lang), callback_data="mylist:fav:0")],
        [InlineKeyboardButton(text=t("mylist_cat_stats", lang), callback_data="mylist:stats")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _do_mylist(message: Message, lang: str) -> None:
    await message.answer(t("mylist_intro", lang), parse_mode=ParseMode.HTML, reply_markup=_mylist_home_keyboard(lang))


@router.callback_query(F.data == "mylist:home")
async def cb_mylist_home(call: CallbackQuery) -> None:
    lang = await get_lang(call.from_user.id)
    try:
        await call.message.edit_text(
            t("mylist_intro", lang), parse_mode=ParseMode.HTML, reply_markup=_mylist_home_keyboard(lang)
        )
    except Exception as e:
        _log.info("mylist:home edit failed: %s", e)
    await call.answer()


# --- Subs & help --------------------------------------------------------------

async def _do_subs(message: Message, lang: str) -> None:
    subs = await list_subscriptions(message.from_user.id)
    if not subs:
        await message.answer(t("cmd_subs_empty", lang), parse_mode=ParseMode.HTML)
        return
    from .callbacks import subs_keyboard  # avoid circular import at module load
    await message.answer(
        t("cmd_subs_header", lang),
        reply_markup=subs_keyboard(subs, lang),
        parse_mode=ParseMode.HTML,
    )


# --- Vibe wizard --------------------------------------------------------------

_YEAR_OPTS = [
    # No upper bound on "recent" — pins to current year automatically as time
    # rolls forward, and lets airing shows show up.
    ("recent", "vibe_year_recent", 2020, None),
    ("2015_2019", "vibe_year_2015_2019", 2015, 2019),
    ("2010_2014", "vibe_year_2010_2014", 2010, 2014),
    ("2000s", "vibe_year_2000s", 2000, 2009),
    ("classic", "vibe_year_classic", None, 1999),
]

_SCORE_OPTS = [("6", "vibe_score_6", 6.0), ("7", "vibe_score_7", 7.0),
               ("8", "vibe_score_8", 8.0), ("9", "vibe_score_9", 9.0)]

_TYPE_OPTS = [("tv", "vibe_type_tv"), ("movie", "vibe_type_movie"),
              ("ova", "vibe_type_ova"), ("any", "vibe_type_any")]


def _kb_grid(buttons: list[InlineKeyboardButton], per_row: int) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for b in buttons:
        row.append(b)
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def _footer_row(lang: str, *, skip: bool = True) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = []
    if skip:
        row.append(InlineKeyboardButton(text=t("vibe_skip", lang), callback_data="vibe:skip"))
    row.append(InlineKeyboardButton(text=t("vibe_cancel", lang), callback_data="vibe:cancel"))
    return row


def _vibe_year_kb(lang: str) -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(text=t(loc, lang), callback_data=f"vibe_year:{key}") for key, loc, *_ in _YEAR_OPTS]
    rows = _kb_grid(btns, per_row=2)
    rows.append(_footer_row(lang))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _vibe_score_kb(lang: str) -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(text=t(loc, lang), callback_data=f"vibe_score:{key}") for key, loc, _ in _SCORE_OPTS]
    rows = _kb_grid(btns, per_row=4)
    rows.append(_footer_row(lang))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _vibe_genre_kb(lang: str) -> InlineKeyboardMarkup:
    btns: list[InlineKeyboardButton] = []
    for slug in jikan.GENRES:
        loc_key = f"vibe_genre_{slug}"
        btns.append(InlineKeyboardButton(text=t(loc_key, lang), callback_data=f"vibe_genre:{slug}"))
    rows = _kb_grid(btns, per_row=2)
    rows.append(_footer_row(lang))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _vibe_type_kb(lang: str) -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(text=t(loc, lang), callback_data=f"vibe_type:{key}") for key, loc in _TYPE_OPTS]
    rows = _kb_grid(btns, per_row=2)
    rows.append(_footer_row(lang, skip=False))  # last step — no skip
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _start_vibe(message: Message, lang: str, state: FSMContext) -> None:
    await state.set_state(VibeStates.year)
    await message.answer(t("vibe_intro", lang), parse_mode=ParseMode.HTML)
    await message.answer(t("vibe_step_year", lang), parse_mode=ParseMode.HTML, reply_markup=_vibe_year_kb(lang))


async def _edit_step(call: CallbackQuery, lang: str, key: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await call.message.edit_text(t(key, lang), parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        await call.message.answer(t(key, lang), parse_mode=ParseMode.HTML, reply_markup=kb)


@router.callback_query(F.data == "vibe:cancel")
async def cb_vibe_cancel(call: CallbackQuery, state: FSMContext) -> None:
    lang = await get_lang(call.from_user.id)
    await state.clear()
    try:
        await call.message.edit_text(t("vibe_cancelled", lang))
    except Exception:
        await call.message.answer(t("vibe_cancelled", lang))
    await call.answer()


@router.callback_query(F.data.startswith("vibe_year:"))
async def cb_vibe_year(call: CallbackQuery, state: FSMContext) -> None:
    lang = await get_lang(call.from_user.id)
    key = call.data.split(":", 1)[1]
    opt = next((o for o in _YEAR_OPTS if o[0] == key), None)
    if opt:
        _, _, y_from, y_to = opt
        await state.update_data(year_from=y_from, year_to=y_to)
    await _advance_to(call, state, lang, VibeStates.score, "vibe_step_score", _vibe_score_kb(lang))


@router.callback_query(F.data.startswith("vibe_score:"))
async def cb_vibe_score(call: CallbackQuery, state: FSMContext) -> None:
    lang = await get_lang(call.from_user.id)
    key = call.data.split(":", 1)[1]
    opt = next((o for o in _SCORE_OPTS if o[0] == key), None)
    if opt:
        await state.update_data(min_score=opt[2])
    await _advance_to(call, state, lang, VibeStates.genre, "vibe_step_genre", _vibe_genre_kb(lang))


@router.callback_query(F.data.startswith("vibe_genre:"))
async def cb_vibe_genre(call: CallbackQuery, state: FSMContext) -> None:
    lang = await get_lang(call.from_user.id)
    key = call.data.split(":", 1)[1]
    if key in jikan.GENRES:
        # Store the slug — aggregator.vibe_search maps it to Jikan id + AniList
        # genre string, so both sources get filtered.
        await state.update_data(genre_slug=key)
    await _advance_to(call, state, lang, VibeStates.type_, "vibe_step_type", _vibe_type_kb(lang))


async def _advance_to(
    call: CallbackQuery,
    state: FSMContext,
    lang: str,
    next_state: State,
    prompt_key: str,
    kb: InlineKeyboardMarkup,
) -> None:
    await state.set_state(next_state)
    await _edit_step(call, lang, prompt_key, kb)
    await call.answer()


@router.callback_query(F.data == "vibe:skip", StateFilter(VibeStates))
async def cb_vibe_skip(call: CallbackQuery, state: FSMContext) -> None:
    """Skip current wizard step — routes to the next state without recording a filter."""
    lang = await get_lang(call.from_user.id)
    cur = await state.get_state()
    if cur == VibeStates.year.state:
        await _advance_to(call, state, lang, VibeStates.score, "vibe_step_score", _vibe_score_kb(lang))
    elif cur == VibeStates.score.state:
        await _advance_to(call, state, lang, VibeStates.genre, "vibe_step_genre", _vibe_genre_kb(lang))
    elif cur == VibeStates.genre.state:
        await _advance_to(call, state, lang, VibeStates.type_, "vibe_step_type", _vibe_type_kb(lang))
    else:
        await call.answer()


@router.callback_query(F.data.startswith("vibe_type:"))
async def cb_vibe_type(call: CallbackQuery, state: FSMContext) -> None:
    lang = await get_lang(call.from_user.id)
    key = call.data.split(":", 1)[1]
    data = await state.get_data()
    await state.clear()

    filters = {
        "min_score": data.get("min_score"),
        "year_from": data.get("year_from"),
        "year_to": data.get("year_to"),
        "genre_slug": data.get("genre_slug"),
    }
    if key != "any":
        filters["type_"] = key

    try:
        await call.message.edit_text(t("vibe_searching", lang))
    except Exception:
        pass
    await call.answer()

    try:
        raw, relaxed = await aggregator.vibe_search(limit=_LIST_SIZE, min_results=5, **filters)
    except Exception as e:
        _log.exception("vibe_search crashed: %s", e)
        await call.message.answer(t("api_error", lang))
        return

    cards = [AnimeCard(**{k: v for k, v in x.items() if v is not None}) for x in raw]
    if not cards:
        await call.message.answer(t("vibe_empty", lang))
        return

    await aggregator._enrich_watch_links(cards, lang)
    await _cache_list(cards, lang, "vibe")
    if relaxed:
        try:
            await call.message.answer(t("vibe_relaxed", lang), parse_mode=ParseMode.HTML)
        except Exception:
            pass
    await _send_list(call.message, cards, lang, t("menu_vibe", lang))


# --- Top wizard ---------------------------------------------------------------

_TOP_CATS = [
    ("overall", "top_overall"),
    ("airing", "top_airing"),
    ("upcoming", "top_upcoming"),
    ("popular", "top_popular"),
    ("movies", "top_movies"),
    ("seasonal", "top_seasonal"),
]


def _top_keyboard(lang: str) -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(text=t(loc, lang), callback_data=f"top:{key}") for key, loc in _TOP_CATS]
    return InlineKeyboardMarkup(inline_keyboard=_kb_grid(btns, per_row=2))


def _current_season() -> tuple[int, str]:
    today = date.today()
    m = today.month
    if m <= 3:
        return today.year, "winter"
    if m <= 6:
        return today.year, "spring"
    if m <= 9:
        return today.year, "summer"
    return today.year, "fall"


@router.callback_query(F.data == "menu:home")
async def cb_menu_home(call: CallbackQuery, state: FSMContext) -> None:
    """Shortcut from any card back to the persistent menu. Sends a fresh message
    because reply keyboards can't be attached to an inline-callback response."""
    lang = await get_lang(call.from_user.id)
    await state.clear()
    await call.answer()
    try:
        await call.message.answer(t("menu_shown", lang), reply_markup=main_menu_keyboard(lang))
    except Exception as e:
        _log.info("menu:home send failed: %s", e)


@router.callback_query(F.data.startswith("top:"))
async def cb_top(call: CallbackQuery) -> None:
    lang = await get_lang(call.from_user.id)
    cat = call.data.split(":", 1)[1]
    try:
        await call.message.edit_text(t("top_searching", lang))
    except Exception:
        pass
    await call.answer()

    try:
        raw = await _fetch_top(cat)
    except Exception as e:
        _log.exception("top fetch crashed: %s", e)
        await call.message.answer(t("api_error", lang))
        return

    cards = [AnimeCard(**{k: v for k, v in x.items() if v is not None}) for x in raw]
    if not cards:
        await call.message.answer(t("top_empty", lang))
        return

    await aggregator._enrich_watch_links(cards, lang)
    await _cache_list(cards, lang, f"top:{cat}")
    header_key = next((loc for key, loc in _TOP_CATS if key == cat), "menu_top")
    await _send_list(call.message, cards, lang, t(header_key, lang))


async def _fetch_top(cat: str) -> list[dict]:
    raw = await _fetch_top_raw(cat)
    # Always show top lists sorted by score descending. The category filter
    # (popular / airing / movies / seasonal) still selects WHICH anime enter
    # the list, but within the list the highest-rated title comes first — MAL's
    # bypopularity ordering surprised users by putting 8.4-scored shows above
    # 9.0-scored ones.
    return sorted(raw, key=lambda x: (x.get("score") or 0), reverse=True)


async def _fetch_top_raw(cat: str) -> list[dict]:
    if cat == "overall":
        return await aggregator.top_anime_multi(None, None, _LIST_SIZE)
    if cat == "airing":
        return await aggregator.top_anime_multi("airing", None, _LIST_SIZE)
    if cat == "upcoming":
        return await aggregator.top_anime_multi("upcoming", None, _LIST_SIZE)
    if cat == "popular":
        return await aggregator.top_anime_multi("bypopularity", None, _LIST_SIZE)
    if cat == "movies":
        return await aggregator.top_anime_multi(None, "movie", _LIST_SIZE)
    if cat == "seasonal":
        year, season = _current_season()
        return await aggregator.seasonal_multi(year, season, _LIST_SIZE)
    return []


# --- Open-card handler for list buttons ---------------------------------------
# We reuse `nav:<idx>` from callbacks.py; but that handler uses edit_result,
# which won't work when the list message is a photo (edit_media replaces the
# poster + caption — good) or plain text (edit_text — also good). No new
# callback needed.
