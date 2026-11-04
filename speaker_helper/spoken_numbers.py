"""
Numbers, dates, times and amounts, said as words before an engine reads them.

Module summary
--------------
A neural engine trained on prose reads "le 14/11 à 9h30, 3 200 €" however its
training data happened to: measured on 2026-11-04, Audio8 said "14/11" as an
hour and swallowed the colon after "Correction". Whisper hearing the right
words back does not prove the listener did. The robust fix is the oldest one in
speech synthesis: hand the engine words, not digits.

This module is that step for **French and English**, deterministic and
dependency-free. Other languages pass through untouched — a wrong verbalisation
is worse than the engine's own guess. What it rewrites:

* dates ``14/11``, ``14/11/2026`` (fr: day/month; en: month/day unless the
  first number cannot be a month);
* times ``9h30``, ``14 h``, ``9:30``, ``2:30 p.m.``;
* amounts ``3 200 €``, ``12,50 €``, ``3 M€``, ``$3,200``, ``€12.50``, ``£5``;
* percentages ``7,94 %``, ``12%``;
* ordinals ``1er``, ``2e``, ``3ème``, ``1st``, ``14th``;
* grouped and decimal numbers ``3 200``, ``7,94`` (fr) / ``3,200``, ``2.91``
  (en), negatives, leading zeros (``06`` → "zéro six"), English years
  (``2026`` → "twenty twenty-six").

It is applied by :class:`~speaker_helper.speaker.Speaker` to what is *spoken*,
never to what a page *shows*: a narration's cues keep the document's digits.
``settings.numbers_to_words = False`` turns it off.

Usage example
-------------
>>> from speaker_helper.spoken_numbers import verbalize
>>> verbalize("Rendez-vous le 14/11 à 9h30 pour 3 200 €.", "fr")
'Rendez-vous le quatorze novembre à neuf heures trente pour trois mille deux cents euros.'
>>> verbalize("Meet on July 12th at 2:30 p.m., $3,200.", "en")
'Meet on July twelfth at two thirty p.m., three thousand two hundred dollars.'

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import re
from collections.abc import Callable

#: Languages this module verbalises; anything else is returned unchanged.
SUPPORTED_LANGUAGES: tuple[str, ...] = ("fr", "en")

#: Beyond this the digits are read one by one — nobody says a 13-digit number.
_MAX_CARDINAL = 999_999_999_999

# ── French cardinals ───────────────────────────────────────────────────────

_FR_UNITS = (
    "zéro un deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze seize"
).split()
_FR_TENS = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}


def _fr_below_100(n: int) -> str:
    """French words for ``0 <= n < 100`` (traditional spelling, "et un")."""
    if n <= 16:
        return _FR_UNITS[n]
    if n < 20:
        return "dix-" + _FR_UNITS[n - 10]
    tens, unit = divmod(n, 10)
    if tens in (7, 9):
        # 70–79 = soixante + 10–19, 90–99 = quatre-vingt + 10–19.
        base = "soixante" if tens == 7 else "quatre-vingt"
        rest = n - (60 if tens == 7 else 80)
        joiner = " et " if (tens == 7 and rest == 11) else "-"
        return base + joiner + _fr_below_100(rest)
    if tens == 8:
        return "quatre-vingts" if unit == 0 else "quatre-vingt-" + _FR_UNITS[unit]
    word = _FR_TENS[tens]
    if unit == 0:
        return word
    if unit == 1:
        return word + " et un"
    return word + "-" + _FR_UNITS[unit]


def _fr_below_1000(n: int, *, final: bool) -> str:
    """French words for ``0 <= n < 1000``.

    ``final`` says whether nothing multiplies this group (``cents`` and
    ``quatre-vingts`` keep their plural *s* only when they end the number).
    """
    hundreds, rest = divmod(n, 100)
    parts: list[str] = []
    if hundreds:
        if hundreds == 1:
            parts.append("cent")
        else:
            plural = rest == 0 and final
            parts.append(_FR_UNITS[hundreds] + (" cents" if plural else " cent"))
    if rest or not hundreds:
        words = _fr_below_100(rest)
        if not final and words == "quatre-vingts":
            words = "quatre-vingt"
        parts.append(words)
    return " ".join(parts)


def fr_cardinal(n: int) -> str:
    """Spell a non-negative integer in French.

    Examples
    --------
    >>> fr_cardinal(71)
    'soixante et onze'
    >>> fr_cardinal(3200)
    'trois mille deux cents'
    >>> fr_cardinal(80_000)
    'quatre-vingt mille'
    >>> fr_cardinal(2_000_001)
    'deux millions un'
    """
    if n < 1000:
        return _fr_below_1000(n, final=True)
    parts: list[str] = []
    for value, singular, plural in (
        (1_000_000_000, "milliard", "milliards"),
        (1_000_000, "million", "millions"),
    ):
        count, n = divmod(n, value)
        if count:
            # Million and milliard are nouns: they take "un" and a plural.
            parts.append(f"{fr_cardinal(count)} {singular if count == 1 else plural}")
    thousands, n = divmod(n, 1000)
    if thousands:
        # Mille is invariable, and takes no "un" before it.
        parts.append(
            "mille" if thousands == 1 else _fr_below_1000(thousands, final=False) + " mille"
        )
    if n:
        parts.append(_fr_below_1000(n, final=True))
    return " ".join(parts)


def fr_ordinal(n: int) -> str:
    """Spell a French ordinal (``1`` → "premier").

    Examples
    --------
    >>> fr_ordinal(1), fr_ordinal(5), fr_ordinal(9), fr_ordinal(21)
    ('premier', 'cinquième', 'neuvième', 'vingt et unième')
    """
    if n == 1:
        return "premier"
    word = fr_cardinal(n)
    if word.endswith("cinq"):
        return word + "uième"
    if word.endswith("neuf"):
        return word[:-1] + "vième"
    if word.endswith(("cents", "vingts")):
        word = word[:-1]
    if word.endswith("e"):
        word = word[:-1]
    return word + "ième"


# ── English cardinals ──────────────────────────────────────────────────────

_EN_UNITS = (
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_EN_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _en_below_1000(n: int) -> str:
    """English words for ``0 <= n < 1000`` (no "and", the US reading)."""
    hundreds, rest = divmod(n, 100)
    parts: list[str] = []
    if hundreds:
        parts.append(_EN_UNITS[hundreds] + " hundred")
    if rest or not hundreds:
        if rest < 20:
            parts.append(_EN_UNITS[rest])
        else:
            tens, unit = divmod(rest, 10)
            parts.append(_EN_TENS[tens] + (f"-{_EN_UNITS[unit]}" if unit else ""))
    return " ".join(parts)


def en_cardinal(n: int) -> str:
    """Spell a non-negative integer in English.

    Examples
    --------
    >>> en_cardinal(3200)
    'three thousand two hundred'
    >>> en_cardinal(1_000_001)
    'one million one'
    """
    if n < 1000:
        return _en_below_1000(n)
    parts: list[str] = []
    for value, name in ((1_000_000_000, "billion"), (1_000_000, "million"), (1000, "thousand")):
        count, n = divmod(n, value)
        if count:
            parts.append(f"{en_cardinal(count)} {name}")
    if n:
        parts.append(_en_below_1000(n))
    return " ".join(parts)


_EN_ORDINAL_IRREGULAR = {
    "one": "first",
    "two": "second",
    "three": "third",
    "five": "fifth",
    "eight": "eighth",
    "nine": "ninth",
    "twelve": "twelfth",
}


def en_ordinal(n: int) -> str:
    """Spell an English ordinal.

    Examples
    --------
    >>> en_ordinal(1), en_ordinal(12), en_ordinal(14), en_ordinal(21), en_ordinal(40)
    ('first', 'twelfth', 'fourteenth', 'twenty-first', 'fortieth')
    """
    word = en_cardinal(n)
    # Only the last word (or the part after the last hyphen) takes the suffix.
    cut = max(word.rfind(" "), word.rfind("-"))
    head, last = word[: cut + 1], word[cut + 1 :]
    if last in _EN_ORDINAL_IRREGULAR:
        last = _EN_ORDINAL_IRREGULAR[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last += "th"
    return head + last


def en_year(n: int) -> str:
    """Read a year the way English speakers do.

    Examples
    --------
    >>> en_year(2026), en_year(2000), en_year(2005)
    ('twenty twenty-six', 'two thousand', 'two thousand five')
    >>> en_year(1999), en_year(1900)
    ('nineteen ninety-nine', 'nineteen hundred')
    """
    century, rest = divmod(n, 100)
    if 2000 <= n <= 2009:
        return en_cardinal(n)
    if rest == 0:
        return en_cardinal(century) + " hundred"
    if rest < 10:
        return f"{en_cardinal(century)} oh {en_cardinal(rest)}"
    return f"{en_cardinal(century)} {en_cardinal(rest)}"


# ── Shared reading of a digit string ───────────────────────────────────────

_FR_MONTHS = (
    "janvier février mars avril mai juin juillet août septembre octobre novembre décembre"
).split()
_EN_MONTHS = (
    "January February March April May June July August September October November December"
).split()


def _cardinal(lang: str) -> Callable[[int], str]:
    return fr_cardinal if lang == "fr" else en_cardinal


def _integer(digits: str, lang: str) -> str:
    """Read a bare digit string: leading zeros and huge numbers digit by digit."""
    say = _cardinal(lang)
    zero = "zéro" if lang == "fr" else "zero"
    if len(digits) > 1 and digits.startswith("0"):
        stripped = digits.lstrip("0")
        zeros = " ".join([zero] * (len(digits) - len(stripped)))
        return f"{zeros} {_integer(stripped, lang)}" if stripped else zeros
    value = int(digits)
    if value > _MAX_CARDINAL:
        return " ".join(say(int(d)) for d in digits)
    return say(value)


def _decimal(int_part: str, frac: str, lang: str) -> str:
    """Read ``int_part`` [,.] ``frac``; a fraction starting with 0 digit by digit."""
    point = "virgule" if lang == "fr" else "point"
    head = _integer(int_part, lang)
    if lang == "en" or frac.startswith("0"):
        # English reads decimals digit by digit ("two point nine one"); French
        # does too when the fraction starts with a zero ("sept virgule zéro cinq").
        tail = " ".join(_integer(d, lang) for d in frac)
    else:
        tail = _integer(frac, lang)
    return f"{head} {point} {tail}"


# ── Patterns ───────────────────────────────────────────────────────────────

_SP = "[   ]"  # space, no-break space, narrow no-break space
_FR_NUM = rf"\d{{1,3}}(?:{_SP}\d{{3}})+|\d+"
_EN_NUM = r"\d{1,3}(?:,\d{3})+|\d+"


def _digits(raw: str) -> str:
    return re.sub(rf"[{_SP[1:-1]},]", "", raw)


def _fr_number(int_raw: str, frac: str | None) -> str:
    digits = _digits(int_raw)
    return _decimal(digits, frac, "fr") if frac else _integer(digits, "fr")


def _en_number(int_raw: str, frac: str | None) -> str:
    digits = _digits(int_raw)
    return _decimal(digits, frac, "en") if frac else _integer(digits, "en")


def _fr_hour(h: int) -> str:
    """ "une heure", "vingt et une heures" — heure is feminine."""
    word = fr_cardinal(h)
    if word.endswith("un"):
        word = word[:-2] + "une"
    return f"{word} {'heure' if h in (0, 1) else 'heures'}"


def _verbalize_fr(text: str) -> str:
    # Dates: 14/11, 14/11/2026, 1/1/26.
    def date(m: re.Match) -> str:
        day, month, year = int(m["d"]), int(m["m"]), m["y"]
        if not (1 <= day <= 31 and 1 <= month <= 12):
            return m[0]
        out = f"{fr_ordinal(1) if day == 1 else fr_cardinal(day)} {_FR_MONTHS[month - 1]}"
        if year:
            out += " " + fr_cardinal(int(year) + (2000 if len(year) == 2 else 0))
        return out

    text = re.sub(
        r"(?<![\d/])(?P<d>\d{1,2})/(?P<m>\d{1,2})(?:/(?P<y>\d{4}|\d{2}))?(?![\d/])", date, text
    )

    # Times: 9h30, 14 h, 9 h 05, 9:30.
    def hour(m: re.Match) -> str:
        h, minutes = int(m["h"]), m["min"]
        if h > 24 or (minutes and int(minutes) > 59):
            return m[0]
        out = _fr_hour(h)
        return out + (f" {fr_cardinal(int(minutes))}" if minutes and int(minutes) else "")

    text = re.sub(r"(?<![\d,.])(?P<h>\d{1,2}) ?h ?(?P<min>\d{2})?(?![\wÀ-ÿ])", hour, text)
    text = re.sub(r"(?<![\d,.:])(?P<h>\d{1,2}):(?P<min>\d{2})(?![\d:])", hour, text)

    # Amounts: 3 200 €, 12,50 €, 3 M€, 2 k€, €12, 5 $, $5, 5 £.
    currency = {"€": ("euro", "euros", "centime"), "EUR": ("euro", "euros", "centime"),
                "$": ("dollar", "dollars", "cent"), "USD": ("dollar", "dollars", "cent"),
                "£": ("livre", "livres", "penny")}  # fmt: skip

    def money(m: re.Match) -> str:
        sym = m["sym"] or m["presym"]
        one, many, _ = currency[sym.upper() if sym.isalpha() else sym]
        scale = m["scale"]
        if scale:
            count = _fr_number(m["n"], m["f"])
            if scale == "k":
                return f"{count} mille {many}"
            unit = "million" if count == "un" else "millions"
            return f"{count} {unit} d'{many}" if many[0] in "aeiou" else f"{count} {unit} de {many}"
        value = _digits(m["n"])
        words = _fr_number(m["n"], None)
        noun = one if int(value) in (0, 1) else many
        frac = m["f"]
        if frac:
            cents = frac.ljust(2, "0")[:2]
            return f"{words} {noun} {fr_cardinal(int(cents))}" if int(cents) else f"{words} {noun}"
        return f"{words} {noun}"

    text = re.sub(
        rf"(?P<presym>[€$£])?(?P<n>{_FR_NUM})(?:,(?P<f>\d+))?{_SP}?(?:(?P<scale>[kM]){_SP}?)?"
        r"(?P<sym>€|EUR\b|\$|USD\b|£)",
        money,
        text,
    )
    text = re.sub(
        rf"(?P<presym>[€$£])(?P<n>{_FR_NUM})(?:,(?P<f>\d+))?(?P<scale>)(?P<sym>)",
        lambda m: money(m),
        text,
    )

    # Percentages.
    text = re.sub(
        rf"(?P<n>{_FR_NUM})(?:,(?P<f>\d+))?{_SP}?%",
        lambda m: _fr_number(m["n"], m["f"]) + " pour cent",
        text,
    )

    # Ordinals: 1er, 1re, 2e, 3ème, 2nd(e).
    def ordinal(m: re.Match) -> str:
        n, suffix = int(m["n"]), m["s"]
        if n == 1:
            return "première" if suffix.startswith("r") else "premier"
        if suffix.startswith("nd"):
            return "seconde" if suffix.endswith("e") else "second"
        return fr_ordinal(n)

    text = re.sub(r"\b(?P<n>\d+)(?P<s>er|re|ère|e|ème|è|nde|nd)\b", ordinal, text)

    # Plain numbers last, with negatives and decimals.
    def number(m: re.Match) -> str:
        words = _fr_number(m["n"], m["f"])
        return ("moins " if m["neg"] else "") + words

    return re.sub(
        rf"(?P<neg>(?<![\w\d])[-−](?=\d))?(?<![\w])(?P<n>{_FR_NUM})(?:,(?P<f>\d+))?(?![\w])",
        number,
        text,
    )


def _verbalize_en(text: str) -> str:
    # Dates: 11/14/2026 (US), or day-first when the first part cannot be a month.
    def date(m: re.Match) -> str:
        a, b, year = int(m["a"]), int(m["b"]), m["y"]
        month, day = (a, b) if a <= 12 else (b, a)
        if not (1 <= day <= 31 and 1 <= month <= 12):
            return m[0]
        out = f"{_EN_MONTHS[month - 1]} {en_ordinal(day)}"
        if year:
            out += ", " + en_year(int(year) + (2000 if len(year) == 2 else 0))
        return out

    text = re.sub(
        r"(?<![\d/])(?P<a>\d{1,2})/(?P<b>\d{1,2})(?:/(?P<y>\d{4}|\d{2}))?(?![\d/])", date, text
    )

    # Times: 2:30, 2:05 p.m., 14:00.
    def clock(m: re.Match) -> str:
        h, minutes = int(m["h"]), int(m["min"])
        if h > 24 or minutes > 59:
            return m[0]
        if minutes == 0 and h > 12 and not m["ampm"]:
            out = en_cardinal(h) + " hundred"  # 24-hour clock: "fourteen hundred"
        elif minutes == 0:
            out = en_cardinal(h) + ("" if m["ampm"] else " o'clock")
        elif minutes < 10:
            out = f"{en_cardinal(h)} oh {en_cardinal(minutes)}"
        else:
            out = f"{en_cardinal(h)} {en_cardinal(minutes)}"
        return out + (m["sp"] + m["ampm"] if m["ampm"] else "")

    text = re.sub(
        r"(?<![\d.:])(?P<h>\d{1,2}):(?P<min>\d{2})(?![\d:])(?P<sp>\s?)(?P<ampm>[ap]\.?m\.?(?!\w))?",
        clock,
        text,
    )

    # Amounts: $3,200, $12.50, €5, £5, 5 euros stays as is (already words).
    currency = {"$": ("dollar", "dollars", "cent", "cents"),
                "€": ("euro", "euros", "cent", "cents"),
                "£": ("pound", "pounds", "penny", "pence")}  # fmt: skip

    def money(m: re.Match) -> str:
        one, many, sub_one, sub_many = currency[m["sym"]]
        value = int(_digits(m["n"]))
        out = f"{_en_number(m['n'], None)} {one if value == 1 else many}"
        scale = m["scale"]
        if scale:
            return (
                f"{_en_number(m['n'], m['f'])} {'million' if scale in 'mM' else 'thousand'} {many}"
            )
        if m["f"]:
            cents = int(m["f"].ljust(2, "0")[:2])
            if cents:
                out += f" and {en_cardinal(cents)} {sub_one if cents == 1 else sub_many}"
        return out

    text = re.sub(
        rf"(?P<sym>[$€£])(?P<n>{_EN_NUM})(?:\.(?P<f>\d+))?(?P<scale>[kKmM](?![a-zA-Z]))?",
        money,
        text,
    )
    text = re.sub(
        rf"(?P<n>{_EN_NUM})(?:\.(?P<f>\d+))? ?(?P<sym>[€£$])(?P<scale>)",
        money,
        text,
    )

    # Percentages.
    text = re.sub(
        rf"(?P<n>{_EN_NUM})(?:\.(?P<f>\d+))? ?%",
        lambda m: _en_number(m["n"], m["f"]) + " percent",
        text,
    )

    # Ordinals: 1st, 2nd, 3rd, 14th.
    text = re.sub(r"\b(?P<n>\d+)(?:st|nd|rd|th)\b", lambda m: en_ordinal(int(m["n"])), text)

    # Plain numbers; a bare four-digit 1100–2099 reads as a year.
    def number(m: re.Match) -> str:
        raw, frac = m["n"], m["f"]
        if not frac and re.fullmatch(r"(1[1-9]|20)\d\d", raw):
            words = en_year(int(raw))
        else:
            words = _en_number(raw, frac)
        return ("minus " if m["neg"] else "") + words

    return re.sub(
        rf"(?P<neg>(?<![\w\d])[-−](?=\d))?(?<![\w])(?P<n>{_EN_NUM})(?:\.(?P<f>\d+))?(?![\w])",
        number,
        text,
    )


def verbalize(text: str, language: str) -> str:
    """Rewrite the digits in ``text`` as the words a speaker would say.

    Parameters
    ----------
    text : str
        Text about to be synthesised.
    language : str
        ISO-639-1 code (``"fr-FR"`` is fine); anything but French or English
        returns ``text`` unchanged.

    Returns
    -------
    str
        The text with dates, times, amounts, percentages, ordinals and numbers
        spelled out; unchanged when it holds no digit.

    Examples
    --------
    >>> verbalize("Correction : non pas le 14, mais le 15.", "fr")
    'Correction : non pas le quatorze, mais le quinze.'
    >>> verbalize("Un WER de 7,94 %.", "fr")
    'Un WER de sept virgule quatre-vingt-quatorze pour cent.'
    >>> verbalize("Hola 12", "es")
    'Hola 12'
    """
    lang = (language or "").strip().lower().split("-")[0]
    if lang not in SUPPORTED_LANGUAGES or not any(ch.isdigit() for ch in text):
        return text
    return _verbalize_fr(text) if lang == "fr" else _verbalize_en(text)
