from .ru import STRINGS as RU
from .en import STRINGS as EN
from .uk import STRINGS as UK

_LOCALES = {"ru": RU, "en": EN, "uk": UK}


def t(key: str, lang: str, **kwargs) -> str:
    lang = lang if lang in _LOCALES else "en"
    template = _LOCALES[lang].get(key) or _LOCALES["en"].get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template


__all__ = ["t"]
