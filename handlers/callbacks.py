import logging

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from db import get_lang, user_titles
from db.subscriptions import is_subscribed, subscribe, unsubscribe, list_subscriptions
from locales import t
from services import anilibria as anilibria_service
from services import jikan
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


def _torrents_keyboard(
    card_idx: int,
    torrents: list[dict],
    page: int,
    lang: str,
) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(torrents) + _EPISODES_PER_PAGE - 1) // _EPISODES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * _EPISODES_PER_PAGE
    chunk = torrents[start : start + _EPISODES_PER_PAGE]

    rows: list[list[InlineKeyboardButton]] = []
    for tr in chunk:
        if tr.get("size_gb") is not None:
            label = t(
                "download_button", lang,
                quality=tr.get("quality") or "?",
                size=t("size_gb", lang, value=tr["size_gb"]),
                episodes=tr.get("episodes") or "",
            )
        else:
            label = t(
                "download_button_no_size", lang,
                quality=tr.get("quality") or "?",
                episodes=tr.get("episodes") or "",
            )
        rows.append([InlineKeyboardButton(text=label, callback_data=f"trdl:{card_idx}:{tr['id']}")])

    if total_pages > 1:
        prev_page = (page - 1) % total_pages
        next_page = (page + 1) % total_pages
        rows.append([
            InlineKeyboardButton(text="◀", callback_data=f"trlist:{card_idx}:{prev_page}"),
            InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton(text="▶", callback_data=f"trlist:{card_idx}:{next_page}"),
        ])

    rows.append([InlineKeyboardButton(text=t("btn_back", lang), callback_data=f"nav:{card_idx}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(lambda c: c.data and c.data.startswith("trlist:"))
async def cb_torrents_list(call: CallbackQuery) -> None:
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
    if not card.torrents:
        await call.answer(t("no_torrents", lang), show_alert=True)
        return

    kb = _torrents_keyboard(idx, card.torrents, page, lang)
    text = t("download_header", lang, title=card.primary_title(lang))

    if call.message.photo:
        try:
            await call.message.edit_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception as e:
            _log.info("edit_caption for torrents failed: %s", e)
    else:
        try:
            await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception as e:
            _log.info("edit_text for torrents failed: %s", e)
    await call.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("trdl:"))
async def cb_torrent_download(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer()
        return
    try:
        idx = int(parts[1])
        tid = int(parts[2])
    except ValueError:
        await call.answer()
        return

    lang = await get_lang(call.from_user.id)
    cards = await _find_cards_for_message(call.from_user.id, call.message.message_id if call.message else 0)
    if not cards or idx >= len(cards):
        await call.answer(t("api_error", lang), show_alert=False)
        return

    card = cards[idx]
    tr = next((x for x in card.torrents if x.get("id") == tid), None)
    if not tr:
        await call.answer(t("torrent_failed", lang), show_alert=True)
        return

    await call.answer(t("torrent_fetching", lang))
    title = card.primary_title(lang)
    caption = t(
        "torrent_caption", lang,
        title=title,
        quality=tr.get("quality") or "?",
        episodes=tr.get("episodes") or "",
    )

    data = await anilibria_service.download_torrent_file(tid)
    if data:
        try:
            await call.message.answer_document(
                BufferedInputFile(data, filename=f"{title}.torrent"),
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception as e:
            _log.info("answer_document for torrent failed: %s", e)

    magnet = tr.get("magnet")
    if magnet:
        await call.message.answer(caption, parse_mode=ParseMode.HTML)
        await call.message.answer(magnet)
    else:
        await call.message.answer(t("torrent_failed", lang))


def _similar_keyboard(
    mal_id: int,
    recs: list[dict],
    page: int,
    lang: str,
    back_idx: int | None,
) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(recs) + _EPISODES_PER_PAGE - 1) // _EPISODES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * _EPISODES_PER_PAGE
    chunk = recs[start : start + _EPISODES_PER_PAGE]

    rows: list[list[InlineKeyboardButton]] = []
    for rec in chunk:
        rows.append([
            InlineKeyboardButton(text=(rec.get("title") or str(rec["mal_id"]))[:60], callback_data=f"mlopen:{rec['mal_id']}")
        ])

    if total_pages > 1:
        prev_page = (page - 1) % total_pages
        next_page = (page + 1) % total_pages
        rows.append([
            InlineKeyboardButton(text="◀", callback_data=f"similar:{mal_id}:{prev_page}"),
            InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton(text="▶", callback_data=f"similar:{mal_id}:{next_page}"),
        ])

    if back_idx is not None:
        rows.append([InlineKeyboardButton(text=t("btn_back", lang), callback_data=f"nav:{back_idx}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(lambda c: c.data and c.data.startswith("similar:"))
async def cb_similar(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer()
        return
    try:
        mal_id = int(parts[1])
        page = int(parts[2])
    except ValueError:
        await call.answer()
        return

    await call.answer()
    lang = await get_lang(call.from_user.id)
    cards = await _find_cards_for_message(call.from_user.id, call.message.message_id if call.message else 0)
    idx, card = _find_card_by_mal(cards, mal_id)
    title = card.primary_title(lang) if card else str(mal_id)

    recs = await jikan.get_recommendations(mal_id)

    if not recs:
        text = t("similar_empty", lang)
        kb = None
        if idx is not None:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t("btn_back", lang), callback_data=f"nav:{idx}")]
            ])
        if call.message.photo:
            try:
                await call.message.edit_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
            except Exception as e:
                _log.info("edit_caption for similar (empty) failed: %s", e)
        else:
            try:
                await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
            except Exception as e:
                _log.info("edit_text for similar (empty) failed: %s", e)
        return

    kb = _similar_keyboard(mal_id, recs, page, lang, idx)
    text = t("similar_header", lang, title=title)

    if call.message.photo:
        try:
            await call.message.edit_caption(caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception as e:
            _log.info("edit_caption for similar failed: %s", e)
    else:
        try:
            await call.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception as e:
            _log.info("edit_text for similar failed: %s", e)


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


def _find_card_by_mal(cards: list | None, mal_id: int):
    if not cards:
        return None, None
    for i, c in enumerate(cards):
        if c.mal_id == mal_id:
            return i, c
    return None, None


@router.callback_query(lambda c: c.data and c.data.startswith("ut:"))
async def cb_user_title(call: CallbackQuery) -> None:
    """Status cycle / favorite toggle / episode-progress mark. callback_data is
    keyed by mal_id (not the search-cache idx), so it keeps working even after
    the cache entry backing the current card list expires — only the keyboard
    refresh (which needs the cached card list) degrades gracefully in that case."""
    parts = call.data.split(":")
    if len(parts) < 3:
        await call.answer()
        return
    try:
        mal_id = int(parts[1])
    except ValueError:
        await call.answer()
        return
    action = parts[2]

    lang = await get_lang(call.from_user.id)
    user_id = call.from_user.id
    cards = await _find_cards_for_message(user_id, call.message.message_id if call.message else 0)
    idx, card = _find_card_by_mal(cards, mal_id)
    title = card.primary_title(lang) if card else str(mal_id)

    if action == "st":
        new_status = await user_titles.cycle_status(user_id, mal_id, title, lang)
        await call.answer(t(f"status_{new_status}", lang), show_alert=False)
    elif action == "fav":
        is_fav = await user_titles.toggle_favorite(user_id, mal_id, title, lang)
        await call.answer(t("fav_added" if is_fav else "fav_removed", lang), show_alert=False)
    elif action == "ep" and len(parts) == 4:
        try:
            ep = int(parts[3])
        except ValueError:
            await call.answer()
            return
        await user_titles.set_episode(user_id, mal_id, title, lang, ep)
        await call.answer(t("progress_saved", lang, ep=ep), show_alert=False)
    else:
        await call.answer()
        return

    if cards is not None and idx is not None:
        kb = await build_keyboard(cards, idx, lang, user_id=user_id)
        try:
            await call.message.edit_reply_markup(reply_markup=kb)
        except Exception as e:
            _log.info("edit_reply_markup after ut toggle failed: %s", e)


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


