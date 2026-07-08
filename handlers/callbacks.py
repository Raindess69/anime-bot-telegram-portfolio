import logging

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from db import get_lang
from db.subscriptions import is_subscribed, subscribe, unsubscribe, list_subscriptions
from locales import t
from services import anilibria as anilibria_service
from services.aggregator import search_cache

from .search import build_keyboard, edit_result

router = Router(name="callbacks")
_log = logging.getLogger(__name__)

_EPISODES_PER_PAGE = 10  # 5 columns × 2 rows


async def _find_cards_for_message(user_id: int, message_id: int) -> list | None:
    lang = await get_lang(user_id)
    async with search_cache._lock:  # noqa: SLF001
        matching = [
            (expires_at, value)
            for key, (expires_at, value) in search_cache._store.items()
            if key.startswith(f"{lang}:") and value
        ]
    if not matching:
        return None
    matching.sort(reverse=True)
    return matching[0][1]


@router.callback_query(lambda c: c.data == "noop")
async def cb_noop(call: CallbackQuery) -> None:
    await call.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("nav:"))
async def cb_nav(call: CallbackQuery) -> None:
    try:
        idx = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await call.answer()
        return

    lang = await get_lang(call.from_user.id)
    cards = await _find_cards_for_message(call.from_user.id, call.message.message_id if call.message else 0)

    if not cards or idx >= len(cards):
        await call.answer(t("api_error", lang), show_alert=False)
        return

    await edit_result(call.message, cards, idx, lang, user_id=call.from_user.id)
    await call.answer()


def _episodes_keyboard(
    card_idx: int,
    episodes: list[int],
    code: str,
    page: int,
    lang: str,
    uuids: dict[int, str] | None = None,
) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(episodes) + _EPISODES_PER_PAGE - 1) // _EPISODES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * _EPISODES_PER_PAGE
    chunk = episodes[start : start + _EPISODES_PER_PAGE]
    uuids = uuids or {}

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for ep in chunk:
        row.append(
            InlineKeyboardButton(
                text=t("episode_short", lang, n=ep),
                url=anilibria_service.episode_url(code, uuid=uuids.get(ep)),
            )
        )
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    nav: list[InlineKeyboardButton] = []
    if total_pages > 1:
        prev_page = (page - 1) % total_pages
        next_page = (page + 1) % total_pages
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"eps:{card_idx}:{prev_page}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"eps:{card_idx}:{next_page}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text=t("btn_back", lang), callback_data=f"nav:{card_idx}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(lambda c: c.data and c.data.startswith("eps:"))
async def cb_episodes(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer()
        return
    try:
        idx = int(parts[1])
        page = int(parts[2])
    except ValueError:
        await call.answer()
        return

    lang = await get_lang(call.from_user.id)
    cards = await _find_cards_for_message(call.from_user.id, call.message.message_id if call.message else 0)
    if not cards or idx >= len(cards):
        await call.answer(t("api_error", lang), show_alert=False)
        return

    card = cards[idx]
    if not card.anilibria_code or not card.episodes_available:
        await call.answer(t("no_episodes", lang), show_alert=True)
        return

    kb = _episodes_keyboard(
        idx, card.episodes_available, card.anilibria_code, page, lang, card.episode_uuids
    )
    text = f"<b>{card.primary_title(lang)}</b>\n{t('episodes_header', lang)}"

    if call.message.photo:
        try:
            await call.message.edit_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception as e:
            _log.info("edit_caption for episodes failed: %s", e)
    else:
        try:
            await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception as e:
            _log.info("edit_text for episodes failed: %s", e)
    await call.answer()


def _kodik_episodes_keyboard(
    card_idx: int,
    episodes: dict[int, str],
    page: int,
    lang: str,
) -> InlineKeyboardMarkup:
    """Same layout as Anilibria episode picker but each button points directly
    at a Kodik player URL. Falls back to card via the same `nav:{idx}` handler."""
    ep_nums = sorted(episodes.keys())
    total_pages = max(1, (len(ep_nums) + _EPISODES_PER_PAGE - 1) // _EPISODES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * _EPISODES_PER_PAGE
    chunk = ep_nums[start : start + _EPISODES_PER_PAGE]

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for ep in chunk:
        row.append(
            InlineKeyboardButton(
                text=t("episode_short", lang, n=ep),
                url=episodes[ep],
            )
        )
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    if total_pages > 1:
        prev_page = (page - 1) % total_pages
        next_page = (page + 1) % total_pages
        rows.append([
            InlineKeyboardButton(text="◀", callback_data=f"kodep:{card_idx}:{prev_page}"),
            InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton(text="▶", callback_data=f"kodep:{card_idx}:{next_page}"),
        ])

    rows.append([InlineKeyboardButton(text=t("btn_back", lang), callback_data=f"nav:{card_idx}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(lambda c: c.data and c.data.startswith("kodep:"))
async def cb_kodik_episodes(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer()
        return
    try:
        idx = int(parts[1])
        page = int(parts[2])
    except ValueError:
        await call.answer()
        return

    lang = await get_lang(call.from_user.id)
    cards = await _find_cards_for_message(call.from_user.id, call.message.message_id if call.message else 0)
    if not cards or idx >= len(cards):
        await call.answer(t("api_error", lang), show_alert=False)
        return

    card = cards[idx]
    if not card.kodik_episodes:
        await call.answer(t("no_episodes", lang), show_alert=True)
        return

    kb = _kodik_episodes_keyboard(idx, card.kodik_episodes, page, lang)
    header = t("kodik_pick_episode", lang, title=card.primary_title(lang))
    if card.kodik_translation:
        header = f"{header}\n<i>{t('kodik_translation', lang, name=card.kodik_translation)}</i>"

    if call.message.photo:
        try:
            await call.message.edit_caption(caption=header, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception as e:
            _log.info("edit_caption for kodik episodes failed: %s", e)
    else:
        try:
            await call.message.edit_text(header, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception as e:
            _log.info("edit_text for kodik episodes failed: %s", e)
    await call.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("sub:"))
async def cb_subscribe(call: CallbackQuery) -> None:
    try:
        idx = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await call.answer()
        return

    lang = await get_lang(call.from_user.id)
    cards = await _find_cards_for_message(call.from_user.id, call.message.message_id if call.message else 0)
    if not cards or idx >= len(cards):
        await call.answer(t("api_error", lang), show_alert=False)
        return

    card = cards[idx]
    # Subscription now works on any card with a mal_id — Anilibria isn't
    # required. Scheduler probes all known sources per subscription.
    if not card.mal_id and not card.anilibria_code:
        await call.answer(t("sub_not_available", lang), show_alert=True)
        return

    user_id = call.from_user.id
    title = card.primary_title(lang)
    current_max = max(card.episodes_available) if card.episodes_available else 0

    already = await is_subscribed(user_id, mal_id=card.mal_id, anilibria_code=card.anilibria_code)
    if already:
        await unsubscribe(user_id, mal_id=card.mal_id, anilibria_code=card.anilibria_code)
        await call.answer(t("sub_removed", lang, title=title), show_alert=False)
    else:
        await subscribe(
            user_id,
            title=title,
            lang=lang,
            last_episode=current_max,
            mal_id=card.mal_id,
            anilibria_code=card.anilibria_code,
            yummy_url=card.yummy_url,
            shikimori_id=card.shikimori_id,
        )
        await call.answer(t("sub_added", lang, title=title), show_alert=False)

    kb = await build_keyboard(cards, idx, lang, user_id=user_id)
    try:
        if call.message.photo:
            await call.message.edit_reply_markup(reply_markup=kb)
        else:
            await call.message.edit_reply_markup(reply_markup=kb)
    except Exception as e:
        _log.info("edit_reply_markup after sub toggle failed: %s", e)


@router.callback_query(lambda c: c.data and c.data.startswith("unsubid:"))
async def cb_unsubscribe_by_id(call: CallbackQuery) -> None:
    """Unsubscribe by subscription row id — works for entries without anilibria_code."""
    try:
        sub_id = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await call.answer()
        return
    lang = await get_lang(call.from_user.id)
    subs = await list_subscriptions(call.from_user.id)
    target = next((s for s in subs if s["id"] == sub_id), None)
    if target:
        await unsubscribe(
            call.from_user.id,
            mal_id=target.get("mal_id"),
            anilibria_code=target.get("anilibria_code"),
        )
    subs = await list_subscriptions(call.from_user.id)
    if subs:
        kb = subs_keyboard(subs, lang)
        try:
            await call.message.edit_text(t("cmd_subs_header", lang), reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception as e:
            _log.info("edit /subs list failed: %s", e)
    else:
        try:
            await call.message.edit_text(t("cmd_subs_empty", lang), parse_mode=ParseMode.HTML)
        except Exception as e:
            _log.info("edit /subs empty failed: %s", e)
    await call.answer(t("sub_removed_short", lang), show_alert=False)


def subs_keyboard(subs: list[dict], lang: str) -> InlineKeyboardMarkup:
    """Render the /subs list. Row opens Anilibria if we have a code, otherwise
    a MAL card as a fallback link."""
    rows: list[list[InlineKeyboardButton]] = []
    for s in subs:
        code = s.get("anilibria_code")
        mal_id = s.get("mal_id")
        if code:
            open_url = anilibria_service.release_url(code)
        elif mal_id:
            open_url = f"https://myanimelist.net/anime/{mal_id}"
        else:
            open_url = None
        if open_url:
            rows.append([
                InlineKeyboardButton(
                    text=t("btn_open_release", lang, title=s["title"]),
                    url=open_url,
                )
            ])
        rows.append([
            InlineKeyboardButton(
                text=t("btn_unsubscribe", lang),
                callback_data=f"unsubid:{s['id']}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


