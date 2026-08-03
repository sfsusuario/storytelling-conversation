"""Text normalization for the TTS input of the cloned-voice engines.

Chatterbox/XTTS read digits badly ("23" comes out garbled or in English),
so numbers are expanded to words in the dialogue language BEFORE synthesis.
Only the spoken text changes: subtitles keep the original line, digits
included, because those engines have no word timings and the caption
fallback renders turn.line as written.
"""
from __future__ import annotations

import re

# Language-specific connectors; num2words covers the numbers themselves.
_PERCENT = {"es": "por ciento", "en": "percent", "pt": "por cento",
            "fr": "pour cent", "de": "Prozent", "it": "per cento"}
_DECIMAL = {"es": "coma", "en": "point", "pt": "vírgula",
            "fr": "virgule", "de": "Komma", "it": "virgola"}

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*(?:\s*%)?")


def _to_words(value: int | float, lang: str) -> str:
    from num2words import num2words

    try:
        return num2words(value, lang=lang)
    except NotImplementedError:
        return num2words(value, lang="en")


def _split_number(raw: str) -> tuple[int, str | None]:
    """(integer_part, decimal_digits|None), understanding thousands
    separators: "1.000" / "1,000,000" are integers, "3,14" is a decimal."""
    if re.fullmatch(r"\d{1,3}(?:([.,])\d{3})+", raw):
        return int(re.sub(r"[.,]", "", raw)), None
    m = re.fullmatch(r"(\d+)[.,](\d+)", raw)
    if m:
        return int(m.group(1)), m.group(2)
    return int(re.sub(r"[.,]", "", raw)), None


def expand_numbers_for_tts(text: str, language: str) -> str:
    """Replace every number (and trailing %) with its spelled-out words."""
    lang = (language or "es").split("-")[0].lower()

    def repl(match: re.Match) -> str:
        token = match.group(0)
        percent = token.rstrip().endswith("%")
        raw = token.rstrip("% \t")
        integer, decimals = _split_number(raw)
        words = _to_words(integer, lang)
        if decimals is not None:
            digit_words = " ".join(_to_words(int(d), lang) for d in decimals)
            words = f"{words} {_DECIMAL.get(lang, _DECIMAL['en'])} {digit_words}"
        if percent:
            words = f"{words} {_PERCENT.get(lang, _PERCENT['en'])}"
        return words

    return _NUMBER_RE.sub(repl, text)
