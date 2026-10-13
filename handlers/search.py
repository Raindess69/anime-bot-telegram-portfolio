import logging

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from db import get_lang, user_titles
from db.history import add as history_add
from db.subscriptions import is_subscribed
from locales import t
from models import AnimeCard
from services import anilibria as anilibria_service
from services import search_anime
from utils.formatting import format_card

router = Router(name="search")
_log = logging.getLogger(__name__)


async def build_keyboard(
    cards: list[AnimeCard],
    idx: int,
    lang: str,
    *,
    user_id: int | None = None,
) -> InlineKeyboardMarkup:
    total = len(cards)
    card = cards[idx]

    nav_row: list[InlineKeyboardButton] = []
    if total > 1:
        prev_idx = (idx - 1) % total
        next_idx = (idx + 1) % total
        nav_row.append(InlineKeyboardButton(text=t("btn_prev", lang), callback_data=f"nav:{prev_idx}"))
        nav_row.append(
            InlineKeyboardButton(
                text=t("result_position", lang, current=idx + 1, total=total),
                callback_data="noop",
            )
        )
        nav_row.append(InlineKeyboardButton(text=t("btn_next", lang), callback_data=f"nav:{next_idx}"))

    action_row: list[InlineKeyboardButton] = []
    if card.anilibria_url and card.anilibria_code:
        action_row.append(InlineKeyboardButton(text=t("btn_anilibria", lang), url=card.anilibria_url))
    if card.anilibria_code and card.episodes_available:
        action_row.append(InlineKeyboardButton(text=t("btn_episodes", lang), callback_data=f"eps:{idx}:0"))
    if card.torrents:
        action_row.append(InlineKeyboardButton(text=t("btn_download", lang), callback_data=f"trlist:{idx}:0"))
    if card.mal_id:
        action_row.append(InlineKeyboardButton(text=t("btn_similar", lang), callback_data=f"similar:{card.mal_id}:0"))

    watch_row: list[InlineKeyboardButton] = [
        InlineKeyboardButton(text=t("btn_yummy", lang), url=card.yummy_search_url())
    ]
    if card.title_ru or card.title_en:
        import urllib.parse
        q_title = urllib.parse.quote(card.title_ru or card.title_en)
        watch_row.append(InlineKeyboardButton(text="⚡ AnimeGO", url=f"https://animego.org/search/anime?q={q_title}"))
    if card.crunchyroll_url:
        watch_row.append(
            InlineKeyboardButton(text=t("btn_crunchyroll", lang), url=card.crunchyroll_url)
        )

    # Kodik — the "watch inside Telegram" button. Multi-episode titles get a
    # picker (opens episode-selection keyboard); single-episode/movie titles go
    # straight to the player URL so it's one tap.
    kodik_row: list[InlineKeyboardButton] = []
    if card.kodik_url:
        if len(card.kodik_episodes) > 1:
            kodik_row.append(InlineKeyboardButton(
                text=t("btn_kodik_episodes", lang),
                callback_data=f"kodep:{idx}:0",
            ))
        else:
            kodik_row.append(InlineKeyboardButton(
                text=t("btn_kodik", lang), url=card.kodik_url,
            ))

    sub_row: list[InlineKeyboardButton] = []
    # Subscription now needs only a mal_id — Anilibria is one of several
    # sources the scheduler probes, no longer the sole gate.
    if (card.mal_id or card.anilibria_code) and user_id is not None:
        subscribed = await is_subscribed(
            user_id, mal_id=card.mal_id, anilibria_code=card.anilibria_code
        )
        label = t("btn_unsubscribe" if subscribed else "btn_subscribe", lang)
        sub_row.append(InlineKeyboardButton(text=label, callback_data=f"sub:{idx}"))

    meta_row: list[InlineKeyboardButton] = []
    if card.mal_url:
        meta_row.append(InlineKeyboardButton(text=t("btn_mal", lang), url=card.mal_url))

    # Tracking rows: status cycle + favorite toggle, and (if the user is mid-watch)
    # a "next episode" pair — url button to actually watch it, callback button to
    # record it as seen. Can't be one button: Telegram buttons take url OR
    # callback_data, never both.
    track_row: list[InlineKeyboardButton] = []
    progress_row: list[InlineKeyboardButton] = []
    if card.mal_id and user_id is not None:
        entry = await user_titles.get(user_id, card.mal_id)
        status = entry["status"] if entry else None
        is_fav = entry["is_favorite"] if entry else False
        status_label = t(f"status_{status}", lang) if status else t("status_track", lang)
        track_row.append(InlineKeyboardButton(text=status_label, callback_data=f"ut:{card.mal_id}:st"))
        fav_label = t("btn_favorite_on" if is_fav else "btn_favorite_off", lang)
        track_row.append(InlineKeyboardButton(text=fav_label, callback_data=f"ut:{card.mal_id}:fav"))

        if status in ("watching", "plan"):
            current_ep = entry["current_episode"] if entry else 0
            next_ep = current_ep + 1
            watch_url = _next_episode_watch_url(card, next_ep)
            if watch_url:
                progress_row.append(
                    InlineKeyboardButton(text=t("btn_watch_episode", lang, ep=next_ep), url=watch_url)
                )
                progress_row.append(
                    InlineKeyboardButton(text=t("btn_mark_watched", lang), callback_data=f"ut:{card.mal_id}:ep:{next_ep}")
                )

    # Mini App direct link row
    tma_row: list[InlineKeyboardButton] = []
    if card.mal_id:
        try:
            from handlers.commands import get_mini_app_url
            from aiogram.types import WebAppInfo
            app_url = get_mini_app_url()
            if app_url and app_url.startswith("https://"):
                tma_row.append(
                    InlineKeyboardButton(
                        text="📺 Открыть в EnjoyAnime (Mini App)",
                        web_app=WebAppInfo(url=f"{app_url}#title/{card.mal_id}"),
                    )
                )
        except Exception:
            pass

    # Bottom row: shortcut back to the persistent menu — saves users from
    # typing /start after browsing a card.
    menu_row: list[InlineKeyboardButton] = [
        InlineKeyboardButton(text=t("btn_menu", lang), callback_data="menu:home")
    ]

    keyboard = [
        row for row in
        (nav_row, tma_row, action_row, watch_row, kodik_row, sub_row, track_row, progress_row, meta_row, menu_row)
        if row
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _next_episode_watch_url(card: AnimeCard, ep: int) -> str | None:
    if card.anilibria_code and ep in card.episode_uuids:
        return anilibria_service.episode_url(card.anilibria_code, card.episode_uuids[ep])
    if card.anilibria_code and ep in card.episodes_available:
        return anilibria_service.episode_url(card.anilibria_code)
    if ep in card.kodik_episodes:
        return card.kodik_episodes[ep]
    return None


async def send_result(message: Message, cards: list[AnimeCard], idx: int, lang: str, *, user_id: int | None = None) -> None:
    card = cards[idx]
    caption = format_card(card, lang)
    kb = await build_keyboard(cards, idx, lang, user_id=user_id)

    if card.image_url:
        try:
            await message.answer_photo(
                photo=card.image_url,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
            )
            return
        except Exception as e:
            _log.info("answer_photo failed, falling back to text: %s", e)

    await message.answer(caption, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=False)


async def edit_result(message: Message, cards: list[AnimeCard], idx: int, lang: str, *, user_id: int | None = None) -> None:
    card = cards[idx]
    caption = format_card(card, lang)
    kb = await build_keyboard(cards, idx, lang, user_id=user_id)

    if message.photo and card.image_url:
        try:
            await message.edit_media(
                media=InputMediaPhoto(media=card.image_url, caption=caption, parse_mode=ParseMode.HTML),
                reply_markup=kb,
            )
            return
        except Exception as e:
            _log.info("edit_media failed: %s", e)

    try:
        if message.photo:
            await message.edit_caption(caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            await message.edit_text(caption, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception as e:
        _log.info("edit failed: %s", e)


@router.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject) -> None:
    lang = await get_lang(message.from_user.id)
    query = (command.args or "").strip()
    if not query:
        await message.answer(t("empty_query", lang), parse_mode=ParseMode.HTML)
        return
    await _handle_query(message, query, lang)


@router.message(F.text & ~F.text.startswith("/"))
async def text_search(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    await _handle_query(message, message.text.strip(), lang)


async def _handle_query(message: Message, query: str, lang: str) -> None:
    status = await message.answer(t("searching", lang))
    try:
        cards = await search_anime(query, lang)
    except Exception as e:
        _log.exception("search_anime crashed: %s", e)
        await status.edit_text(t("api_error", lang))
        return

    try:
        await status.delete()
    except Exception:
        pass

    if not cards:
        await message.answer(t("not_found", lang, query=query), parse_mode=ParseMode.HTML)
        return

    try:
        await history_add(message.from_user.id, query)
    except Exception as e:
        _log.info("history_add failed: %s", e)

    await send_result(message, cards, 0, lang, user_id=message.from_user.id)
