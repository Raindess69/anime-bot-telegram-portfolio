from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery

from db import get_lang, set_lang
from db.subscriptions import list_subscriptions
from locales import t

from .callbacks import subs_keyboard
from .menu import main_menu_keyboard

router = Router(name="commands")


def _lang_keyboard(prefix: str = "lang") -> InlineKeyboardMarkup:
    """Prefix controls which callback fires — 'startlang' for first-time onboarding
    (fires welcome after selection), 'lang' for subsequent /lang switches."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data=f"{prefix}:ru"),
                InlineKeyboardButton(text="🇺🇦 Українська", callback_data=f"{prefix}:uk"),
            ],
            [
                InlineKeyboardButton(text="🇬🇧 English", callback_data=f"{prefix}:en"),
            ],
        ]
    )


async def _send_welcome(message: Message, user_id: int, lang: str) -> None:
    name = message.from_user.first_name or ""
    await message.answer(
        t("welcome", lang, name=name),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(lang),
    )


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    # Always ask for language first, even for returning users — the picker was
    # previously buried under the welcome for registered users and got missed.
    # cb_start_lang upserts via set_lang, so this works identically for both.
    await message.answer(
        t("choose_lang_first", "ru"),  # trilingual banner, language-agnostic
        reply_markup=_lang_keyboard(prefix="startlang"),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    await message.answer(t("help", lang))


@router.message(Command("lang"))
async def cmd_lang(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    await message.answer(t("choose_lang", lang), reply_markup=_lang_keyboard())


@router.message(Command("subs"))
async def cmd_subs(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    subs = await list_subscriptions(message.from_user.id)
    if not subs:
        await message.answer(t("cmd_subs_empty", lang), parse_mode=ParseMode.HTML)
        return
    await message.answer(
        t("cmd_subs_header", lang),
        reply_markup=subs_keyboard(subs, lang),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("lang:"))
async def cb_lang(call: CallbackQuery) -> None:
    new_lang = call.data.split(":", 1)[1]
    if new_lang not in ("ru", "en", "uk"):
        await call.answer()
        return
    await set_lang(call.from_user.id, new_lang)
    await call.answer(t("lang_set", new_lang), show_alert=False)
    if call.message:
        try:
            await call.message.edit_text(t("lang_set", new_lang))
        except Exception:
            pass
        try:
            await call.message.answer(
                t("menu_shown", new_lang), reply_markup=main_menu_keyboard(new_lang)
            )
        except Exception:
            pass


@router.callback_query(lambda c: c.data and c.data.startswith("startlang:"))
async def cb_start_lang(call: CallbackQuery) -> None:
    """First-time language pick — persists the language then fires the welcome."""
    new_lang = call.data.split(":", 1)[1]
    if new_lang not in ("ru", "en", "uk"):
        await call.answer()
        return
    await set_lang(call.from_user.id, new_lang)
    await call.answer()
    if call.message:
        try:
            # Replace the "choose language" prompt with a confirmation so the
            # chat log doesn't show the trilingual banner forever.
            await call.message.edit_text(t("lang_set", new_lang))
        except Exception:
            pass
        try:
            await _send_welcome(call.message, call.from_user.id, new_lang)
        except Exception:
            pass


def get_mini_app_url() -> str:
    try:
        from dotenv import dotenv_values
        vals = dotenv_values(".env")
        url = vals.get("WEB_APP_URL") or vals.get("MINI_APP_URL")
        if url and url.startswith("https://"):
            return url
    except Exception:
        pass
    from config import settings
    return settings.mini_app_url


@router.message(Command("app"))
@router.message(Command("webapp"))
async def cmd_webapp(message: Message) -> None:
    from aiogram.types import WebAppInfo

    # Refresh menu button on demand
    try:
        from bot import refresh_menu_button
        await refresh_menu_button(message.bot)
    except Exception:
        pass

    current_url = get_mini_app_url()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📺 Открыть EnjoyAnime (Mini App)",
                    web_app=WebAppInfo(url=current_url),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🌐 Открыть в браузере",
                    url=current_url,
                )
            ]
        ]
    )
    await message.answer(
        f"✨ <b>EnjoyAnime WebApp</b>\n\n"
        f"🔗 <b>Актуальный адрес:</b>\n<code>{current_url}</code>\n\n"
        "💡 <i>Если у вас открывается старый адрес или ошибка DNS: закройте окно Mini App (крестик вверху) и нажмите кнопку ниже заново.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )
