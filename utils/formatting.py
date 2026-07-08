from html import escape

from locales import t
from models import AnimeCard


_STATUS_KEYS = {
    "Currently Airing": "status_airing",
    "Finished Airing": "status_finished",
    "Not yet aired": "status_upcoming",
    "ongoing": "status_airing",
    "released": "status_finished",
    "anons": "status_upcoming",
}


def _status_label(raw: str | None, lang: str) -> str:
    if not raw:
        return t("unknown", lang)
    key = _STATUS_KEYS.get(raw)
    if key:
        return t(key, lang)
    return raw


def _trim(text: str, limit: int = 500) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def format_card(card: AnimeCard, lang: str, *, full: bool = False) -> str:
    title = escape(card.primary_title(lang))
    lines: list[str] = [f"<b>{title}</b>"]

    alt_titles: list[str] = []
    for alt in (card.title_en, card.title_ru, card.title_jp):
        if alt and alt != card.primary_title(lang) and alt not in alt_titles:
            alt_titles.append(alt)
    if alt_titles:
        lines.append("<i>" + " / ".join(escape(x) for x in alt_titles[:2]) + "</i>")

    meta_parts: list[str] = []
    if card.score is not None:
        meta_parts.append(f"⭐ <b>{card.score:.2f}</b>")
    if card.episodes is not None:
        meta_parts.append(f"📺 {card.episodes} {t('episodes', lang).lower()}")
    meta_parts.append(_status_label(card.status, lang))
    lines.append("  •  ".join(meta_parts))

    if card.genres:
        lines.append("🎭 " + escape(", ".join(card.genres[:6])))
    if card.year:
        lines.append(f"📅 {card.year}")

    synopsis = card.synopsis(lang)
    if synopsis:
        limit = 1500 if full else 400
        lines.append("")
        lines.append(f"<i>{escape(_trim(synopsis, limit))}</i>")
    elif full:
        lines.append("")
        lines.append(f"<i>{t('no_synopsis', lang)}</i>")

    return "\n".join(lines)
