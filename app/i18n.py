"""Tradução do FotoFaxina (português e inglês).

O texto-fonte do código é o português; a tradução em inglês fica em i18n_en.py, indexada pelo
próprio texto em português. Uso:  _("Enviando")  ou  _("{n} itens").format(n=3)
"""
from __future__ import annotations

from .i18n_en import EN

LANGUAGES = {"auto": "Automático (idioma do sistema)", "pt": "Português (Brasil)", "en": "English"}
_lang = "pt"


def system_language() -> str:
    try:
        from PySide6.QtCore import QLocale

        name = QLocale.system().name()  # ex.: pt_BR, en_US
    except Exception:
        import locale

        name = (locale.getlocale()[0] or "")
    return "pt" if name.lower().startswith(("pt", "portuguese")) else "en"


def set_language(setting: str) -> str:
    """setting: auto | pt | en. Retorna o idioma efetivo."""
    global _lang
    _lang = setting if setting in ("pt", "en") else system_language()
    return _lang


def language() -> str:
    return _lang


def _(text: str) -> str:
    if _lang == "en":
        return EN.get(text, text)
    return text
