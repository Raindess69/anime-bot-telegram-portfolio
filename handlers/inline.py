import hashlib
import logging

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultPhoto,
    InputTextMessageContent,
)

from db import get_lang
from locales import t
from services import search_anime
from utils.formatting import format_card

router = Router(name="inline")
_log = logging.getLogger(__name__)


def _result_id(query: str, idx: int) -> str:
    raw = f"{query}:{idx}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:32]


@router.inline_query()
async def inline_search(inline_query: InlineQuery) -> None:
    query = (inline_query.query or "").strip()
    lang = await get_lang(inline_query.from_user.id)

    if len(query) < 2:
        await inline_query.answer([], cache_time=5, is_personal=True)
        return

    try:
        cards = await search_anime(query, lang)
    except Exception as e:
        _log.warning("inline search failed: %s", e)
        cards = []

    results = []
    for idx, card in enumerate(cards[:20]):
        caption = format_card(card, lang)
        title = card.primary_title(lang)
        watch_url = card.watch_url(lang)
        kb = None
        if watch_url:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=t("btn_watch", lang), url=watch_url)]]
            )

        rid = _result_id(query, idx)
        description_parts = []
        if card.score is not None:
            description_parts.append(f"⭐ {card.score:.2f}")
        if card.episodes:
            description_parts.append(f"📺 {card.episodes}")
        if card.year:
            description_parts.append(str(card.year))
        description = "  •  ".join(description_parts) or ""

        if card.image_url:
            results.append(
                InlineQueryResultPhoto(
                    id=rid,
                    photo_url=card.image_url,
                    thumbnail_url=card.image_url,
                    title=title,
                    description=description,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                )
            )
        else:
            results.append(
                InlineQueryResultArticle(
                    id=rid,
                    title=title,
                    description=description,
                    input_message_content=InputTextMessageContent(
                        message_text=caption, parse_mode=ParseMode.HTML
                    ),
                    reply_markup=kb,
                )
            )

    await inline_query.answer(results, cache_time=60, is_personal=True)
