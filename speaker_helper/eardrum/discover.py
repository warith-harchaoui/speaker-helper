"""
Discovery: the words of a text that are not in the lexicon yet, but should be.

Module summary
--------------
A lexicon only fixes the words somebody thought of. A document brings new
ones every time — a surname, an acronym, a product, an English term in a
French sentence — and the first time anyone notices is when the narration
says it wrong. This module reads the text first and lists the words at risk,
each with the reasons it was picked:

``proper``
    Capitalised, but not because it opens a sentence ("Feynman", "Grasse").
``acronym``
    Two or more capitals and no lowercase ("ONU", "BMAD", "GPT-4").
``mixed``
    Mixed case or letters with digits inside one word ("GitHub", "ChatGPT",
    "mp3").
``foreign``
    espeak-ng itself switches language to read it ("Tailwind", "Apple").

Consecutive capitalised words make one phrase ("Van Gogh", "Deep Blue"): the
lexicon matches phrases, and a surname is often only wrong next to its first
name. Words the lexicon already covers are left out — they are checked from
the lexicon's side.

Usage example
-------------
>>> [w.word for w in discover("Hier, Feynman parlait de l'ONU sur GitHub.", "fr")]
['Feynman', 'ONU', 'GitHub']

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

#: A word: letters, digits, inner apostrophes and hyphens ("aujourd'hui",
#: "Jean-Pierre", "GPT-4"), never starting with a digit.
_WORD = re.compile(r"[^\W\d_](?:[\w'’-]*[\w])?")

#: French elisions glued to the next word: "l'ONU" is about "ONU".
_ELISION = re.compile(r"^(?:[cdjlmnst]|qu|jusqu|lorsqu|puisqu)['’](?=\w)", re.IGNORECASE)

#: What ends a sentence, so the next word's capital means nothing.
_SENTENCE_END = re.compile(r"(?:^|[.!?…:;»\n]\s*|[\"«]\s*)$")


@dataclass
class Discovered:
    """A word of the text at risk of being mispronounced.

    Attributes
    ----------
    word : str
        The word or phrase, as first written in the text.
    reasons : list of str
        Why it was picked (``proper``, ``acronym``, ``mixed``, ``foreign``,
        ``heard``).
    count : int
        How many times it occurs.
    example : str
        The first sentence it occurs in (for the report).
    """

    word: str
    reasons: list[str] = field(default_factory=list)
    count: int = 0
    example: str = ""


def _sentence_around(text: str, start: int, end: int) -> str:
    """The sentence containing ``text[start:end]``, trimmed.

    Parameters
    ----------
    text : str
        The whole text.
    start, end : int
        The word's span.

    Returns
    -------
    str
        The surrounding sentence, at most about 200 characters.
    """
    left = max(text.rfind(c, 0, start) for c in ".!?\n") + 1
    rights = [i for i in (text.find(c, end) for c in ".!?\n") if i != -1]
    right = min(rights) + 1 if rights else len(text)
    return " ".join(text[left:right].split())[:200]


def _shape_reasons(token: str, sentence_initial: bool) -> list[str]:
    """The written-shape reasons a token is at risk.

    Parameters
    ----------
    token : str
        One word.
    sentence_initial : bool
        Whether it opens a sentence (its capital then proves nothing).

    Returns
    -------
    list of str
        Subset of ``["acronym", "mixed", "proper"]``.

    Examples
    --------
    >>> _shape_reasons("ONU", False), _shape_reasons("GitHub", True)
    (['acronym'], ['mixed'])
    >>> _shape_reasons("Le", True), _shape_reasons("Grasse", False)
    ([], ['proper'])
    """
    letters = [c for c in token if c.isalpha()]
    if not letters:
        return []
    reasons: list[str] = []
    uppers = sum(c.isupper() for c in letters)
    if uppers >= 2 and uppers == len(letters):
        reasons.append("acronym")
    elif any(c.isdigit() for c in token) or (uppers >= 1 and any(c.isupper() for c in token[1:])):
        # A capital after the first letter, or a digit inside: brand-shaped.
        reasons.append("mixed")
    elif token[0].isupper() and not sentence_initial:
        reasons.append("proper")
    return reasons


class _Span:
    """A word's text and position, shaped like the ``re.Match`` it replaces.

    Parameters
    ----------
    text : str
        The word.
    start : int
        Its offset in the document.
    """

    def __init__(self, text: str, start: int) -> None:
        """Store the word and where it starts.

        Parameters
        ----------
        text : str
            The word.
        start : int
            Its offset in the document.
        """
        self._text, self._start = text, start

    def group(self, _: int = 0) -> str:
        """The word itself, as ``match.group(0)`` would give it."""
        return self._text

    def start(self) -> int:
        """Offset of the word's first character."""
        return self._start

    def end(self) -> int:
        """Offset just past the word's last character."""
        return self._start + len(self._text)


def _strip_elision(text: str, match: re.Match[str]) -> _Span:
    """Cut a French elided article off the front of a matched word.

    Parameters
    ----------
    text : str
        The document (unused, kept for symmetry with the match).
    match : re.Match
        One :data:`_WORD` match.

    Returns
    -------
    _Span
        The word without its elision, at its shifted position.

    Examples
    --------
    >>> m = _WORD.search("l'ONU")
    >>> _strip_elision("l'ONU", m).group(0)
    'ONU'
    """
    word = match.group(0)
    cut = _ELISION.match(word)
    if cut is None:
        return _Span(word, match.start())
    return _Span(word[cut.end() :], match.start() + cut.end())


def _split_phrases_said_apart(found: dict[str, Discovered]) -> None:
    """Replace a phrase by its words when one of them also stands alone.

    "Richard Feynman" and later "Feynman": the surname is the word at risk
    and must be fixed wherever it occurs, so the phrase gives way to its
    words. "Van Gogh", never split in the text, stays a phrase.

    Parameters
    ----------
    found : dict
        Discoveries keyed by casefolded word, edited in place.
    """
    for key, discovered in list(found.items()):
        parts = discovered.word.split()
        if len(parts) < 2 or not any(p.casefold() in found for p in parts):
            continue
        del found[key]
        for part in parts:
            entry = found.setdefault(
                part.casefold(), Discovered(word=part, example=discovered.example)
            )
            entry.count += discovered.count
            for reason in discovered.reasons:
                if reason not in entry.reasons:
                    entry.reasons.append(reason)


def discover(
    text: str,
    language: str,
    *,
    known: Callable[[str], bool] | None = None,
    foreign: Callable[[list[str], str], set[str]] | None = None,
) -> list[Discovered]:
    """List the words of ``text`` likely to be mispronounced.

    Parameters
    ----------
    text : str
        The document.
    language : str
        ISO-639-1 code of the text.
    known : callable or None
        ``word -> bool``: whether the lexicon already covers the word (those
        are skipped). ``None`` skips nothing.
    foreign : callable or None
        ``(words, language) -> set``: the words espeak reads as foreign
        (:func:`speaker_helper.eardrum.espeak.foreign_words`). ``None`` turns
        that rule off — handy in tests, and on machines without espeak.

    Returns
    -------
    list of Discovered
        In order of first appearance.
    """
    found: dict[str, Discovered] = {}
    # Words, with any elided article cut off the front (as its own span, so
    # "l'ONU" is checked as "ONU" and nothing else changes).
    tokens = [_strip_elision(text, m) for m in _WORD.finditer(text)]
    plain_words: list[str] = []
    i = 0
    while i < len(tokens):
        match = tokens[i]
        token = match.group(0)
        initial = bool(_SENTENCE_END.search(text[: match.start()]))
        reasons = _shape_reasons(token, initial)
        span_end = match.end()
        word = token
        if reasons == ["proper"] or (initial and token[:1].isupper() and not reasons):
            # Grow a phrase over the following capitalised words, separated by
            # one space only ("Van Gogh", "Deep Blue", "Jean Dupont").
            j = i + 1
            while (
                j < len(tokens)
                and text[span_end : tokens[j].start()] == " "
                and tokens[j].group(0)[:1].isupper()
                and _shape_reasons(tokens[j].group(0), False) not in (["acronym"], ["mixed"])
            ):
                span_end = tokens[j].end()
                j += 1
            if j > i + 1:
                word = text[match.start() : span_end]
                # A phrase that opens a sentence still names something when
                # it carries two capitals ("Deep Blue a battu…").
                reasons = ["proper"]
                i = j - 1
        if not reasons:
            plain_words.append(token)
        if reasons and not (known and known(word)):
            entry = found.setdefault(word.casefold(), Discovered(word=word))
            entry.count += 1
            for reason in reasons:
                if reason not in entry.reasons:
                    entry.reasons.append(reason)
            if not entry.example:
                entry.example = _sentence_around(text, match.start(), span_end)
        i += 1
    _split_phrases_said_apart(found)
    if foreign is not None:
        # Plain lowercase words can still be foreign ("le cache", "un
        # template"); espeak decides, in one batch.
        candidates = list(dict.fromkeys(w for w in plain_words if len(w) > 2))
        for word in sorted(foreign(candidates, language)):
            if known and known(word):
                continue
            entry = found.setdefault(word.casefold(), Discovered(word=word))
            if "foreign" not in entry.reasons:
                entry.reasons.append("foreign")
            entry.count = entry.count or sum(
                1 for t in tokens if t.group(0).casefold() == word.casefold()
            )
            if not entry.example:
                at = next(t for t in tokens if t.group(0).casefold() == word.casefold())
                entry.example = _sentence_around(text, at.start(), at.end())
        # The already-picked words, too: "Tailwind" is proper AND foreign.
        flagged = foreign([d.word for d in found.values()], language)
        for discovered in found.values():
            if discovered.word in flagged and "foreign" not in discovered.reasons:
                discovered.reasons.append("foreign")
    return list(found.values())
