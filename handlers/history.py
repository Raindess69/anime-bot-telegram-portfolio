"""Search history — last 10 queries per user with one-tap repeat."""
import logging

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from db import get_lang
from db.history import clear, list_recent
from locales import t
from services import search_anime

from .search import send_result

router = Router(name="history")
_log = logging.getLogger(__name__)

_MAX_LABEL_LEN = 48  # Telegram inline-button label limit is small; truncate long queries.


def _truncate(s: str, limit: int = _MAX_LABEL_LEN) -> str:
    return s if len(s) <= limit else s[: limit - 1] + "…"


@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    items = await list_recent(message.from_user.id)
    if not items:
        await message.answer(t("history_empty", lang), parse_mode=ParseMode.HTML)
        return
    rows: list[list[InlineKeyboardButton]] = []
    for i, q in enumerate(items):
        label = t("history_item", lang, n=i + 1, query=_truncate(q))
        rows.append([InlineKeyboardButton(text=label, callback_data=f"hist:{i}")])
    rows.append([InlineKeyboardButton(text=t("history_clear", lang), callback_data="hist_clear")])
    await message.answer(
        t("history_header", lang),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("hist:"))
async def cb_history_open(call: CallbackQuery) -> None:
    try:
        idx = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await call.answer()
        return
    user_id = call.from_user.id
    lang = await get_lang(user_id)
    items = await list_recent(user_id)
    if idx >= len(items):
        await call.answer()
        return
    query = items[idx]
    await call.answer(t("history_reopening", lang, query=_truncate(query)), show_alert=False)

    status = await call.message.answer(t("searching", lang))
    try:
        cards = await search_anime(query, lang)
    except Exception as e:
        _log.exception("history search_anime crashed: %s", e)
        try:
            await status.edit_text(t("api_error", lang))
        except Exception:
            pass
        return

    try:
        await status.delete()
    except Exception:
        pass

    if not cards:
        await call.message.answer(t("not_found", lang, query=query), parse_mode=ParseMode.HTML)
        return

    await send_result(call.message, cards, 0, lang, user_id=user_id)


@router.callback_query(F.data == "hist_clear")
async def cb_history_clear(call: CallbackQuery) -> None:
    lang = await get_lang(call.from_user.id)
    await clear(call.from_user.id)
    try:
        await call.message.edit_text(t("history_cleared", lang))
    except Exception:
        pass
    await call.answer()
