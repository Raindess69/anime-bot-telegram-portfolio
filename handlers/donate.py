"""Telegram Stars donations. XTR currency — provider_token stays empty."""
import logging

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from db import get_lang
from locales import t

router = Router(name="donate")
_log = logging.getLogger(__name__)

_TIERS = (50, 100, 250, 500)


def _donate_keyboard(lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for n in _TIERS:
        row.append(InlineKeyboardButton(
            text=t("donate_option", lang, amount=n),
            callback_data=f"donate:{n}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("donate"))
async def cmd_donate(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    await message.answer(
        t("donate_intro", lang),
        parse_mode=ParseMode.HTML,
        reply_markup=_donate_keyboard(lang),
    )


@router.callback_query(F.data.startswith("donate:"))
async def cb_donate(call: CallbackQuery) -> None:
    try:
        amount = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await call.answer()
        return
    if amount not in _TIERS:
        await call.answer()
        return
    lang = await get_lang(call.from_user.id)
    try:
        await call.message.answer_invoice(
            title=t("donate_invoice_title", lang),
            description=t("donate_invoice_desc", lang, amount=amount),
            payload=f"donate:{amount}:{call.from_user.id}",
            provider_token="",  # empty for Telegram Stars (XTR)
            currency="XTR",
            prices=[LabeledPrice(
                label=t("donate_invoice_label", lang, amount=amount),
                amount=amount,
            )],
        )
    except Exception as e:
        _log.exception("send_invoice failed: %s", e)
        await call.answer(t("donate_failed", lang), show_alert=True)
        return
    await call.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    # Telegram Stars invoices go through without payment provider — always OK.
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    amount = message.successful_payment.total_amount
    await message.answer(
        t("donate_thanks", lang, amount=amount),
        parse_mode=ParseMode.HTML,
    )
