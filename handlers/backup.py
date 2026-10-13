"""/export — sends the user their tracked-titles list as a JSON backup document."""
import json
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from db import get_lang, user_titles
from locales import t

router = Router(name="backup")
_log = logging.getLogger(__name__)


@router.message(Command("export"))
async def cmd_export(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    try:
        rows = await user_titles.export_all(message.from_user.id)
    except Exception as e:
        _log.exception("export_all failed: %s", e)
        await message.answer(t("api_error", lang))
        return

    if not rows:
        await message.answer(t("export_empty", lang))
        return

    try:
        data = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
    except Exception as e:
        _log.exception("export serialize failed: %s", e)
        await message.answer(t("api_error", lang))
        return

    await message.answer_document(
        BufferedInputFile(data, filename="anime_tracking_backup.json"),
        caption=t("export_caption", lang, count=len(rows)),
    )


@router.message(Command("import"))
async def cmd_import(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    doc = message.document or (message.reply_to_message.document if message.reply_to_message else None)
    if not doc:
        await message.answer(t("import_prompt", lang))
        return

    try:
        buf = await message.bot.download(doc)
        rows = json.loads(buf.read().decode("utf-8"))
        if not isinstance(rows, list) or not rows:
            raise ValueError("expected a non-empty JSON list")
    except Exception as e:
        _log.exception("import parse/validate failed: %s", e)
        await message.answer(t("import_bad_format", lang))
        return

    user_id = message.from_user.id
    count = 0
    for row in rows:
        try:
            if not isinstance(row, dict):
                continue
            mal_id = row.get("mal_id")
            title = row.get("title")
            if not isinstance(mal_id, int) or not isinstance(title, str) or not title:
                continue

            lang_row = row.get("lang") or lang
            status = row.get("status")
            if status not in user_titles.STATUSES:
                status = "plan"

            await user_titles.set_status(user_id, mal_id, title, lang_row, status)

            episode = row.get("current_episode")
            if isinstance(episode, int) and episode > 0:
                await user_titles.set_episode(user_id, mal_id, title, lang_row, episode)

            if row.get("is_favorite"):
                current = await user_titles.get(user_id, mal_id)
                if current and not current["is_favorite"]:
                    await user_titles.toggle_favorite(user_id, mal_id, title, lang_row)

            count += 1
        except Exception as e:
            _log.info("import row skipped (mal_id=%s): %s", row.get("mal_id") if isinstance(row, dict) else "?", e)
            continue

    await message.answer(t("import_done", lang, count=count))
