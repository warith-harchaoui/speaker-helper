"""
Intonation: the final melody a sentence's own form calls for.

Module summary
--------------
The prosody loop compares what the voice did with what the text asks for.
For the end of a sentence, what the text asks for follows from its form, and
the form is readable from the words — no model needed:

French (Delais-Roussarie et al. 2015, *Intonational phonology of French*, in
Frota & Prieto, *Intonation in Romance*, OUP; Di Cristo 1998):

* a statement (``.``) falls; an exclamation (``!``) falls, with a wider range;
* a yes/no question with no question marker ("Tu viens ?") **rises** — the
  rise is the only thing that makes it a question;
* tag and echo questions ("…, non ?", "…, n'est-ce pas ?", "Quoi ?") rise;
* "est-ce que …?" and subject-verb inversion ("Viens-tu ?") may rise or fall;
* a question opened by a wh-word ("Où vas-tu ?", "Pourquoi … ?") falls or
  may rise; a wh-word left at the end ("Tu vas où ?") may do either;
* an alternative question ("… A ou B ?") falls on its last term.

English: yes/no questions with an inverted auxiliary prefer a rise, a
declarative question rises, wh-questions and alternatives fall, statements
and exclamations fall, tags may do either.

The answer is ``"rise"``, ``"fall"`` or ``"either"``. ``"either"`` is a real
answer, not a shrug: the loop then accepts any contour, because forcing one
would correct a reading that is not wrong.

Usage example
-------------
>>> expected_contour("Tu viens ce soir ?", "fr").shape
'rise'
>>> expected_contour("Où vas-tu ce soir ?", "fr").shape
'fall'

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: French wh-words that, at the head of a question, make it fall.
_FR_WH = (
    r"qui|que|qu['’]|quoi|où|quand|comment|pourquoi|combien|quel|quelle|quels|quelles|"
    r"lequel|laquelle|lesquels|lesquelles|qu['’]est-ce"
)
_FR_WH_START = re.compile(rf"^\s*(?:et\s+|mais\s+|alors\s+)?(?:{_FR_WH})\b", re.IGNORECASE)
_FR_WH_END = re.compile(rf"\b(?:{_FR_WH})\s*\?\s*$", re.IGNORECASE)
_FR_TAG = re.compile(
    r"(?:,\s*(?:non|hein|n['’]est-ce pas|pas vrai|d['’]accord|oui|ok)\s*\?\s*$)"
    r"|^\s*(?:quoi|pardon|comment|hein|vraiment|ah bon|c['’]est vrai)\s*\?\s*$",
    re.IGNORECASE,
)
#: Short elliptic questions whose melody varies with intent ("Pourquoi pas ?"
#: as a suggestion falls, as a challenge rises).
_FR_ELLIPTIC = re.compile(
    r"^\s*(?:pourquoi pas|et toi|et vous|et alors|et après|et puis)\s*\?\s*$", re.IGNORECASE
)
_FR_EST_CE_QUE = re.compile(r"^\s*est-ce\s+qu", re.IGNORECASE)
#: Subject-verb inversion: a verb glued to a subject pronoun ("viens-tu",
#: "va-t-il", "pouvez-vous").
_FR_INVERSION = re.compile(
    r"\b\w+-(?:t-)?(?:je|tu|il|elle|on|nous|vous|ils|elles)\b", re.IGNORECASE
)
_ALTERNATIVE = {"fr": re.compile(r"\bou\b[^?]*\?\s*$", re.IGNORECASE),
                "en": re.compile(r"\bor\b[^?]*\?\s*$", re.IGNORECASE)}  # fmt: skip

_EN_WH = re.compile(
    r"^\s*(?:and\s+|but\s+|so\s+)?(?:who|whom|whose|what|which|where|when|why|how)\b",
    re.IGNORECASE,
)
_EN_AUX = re.compile(
    r"^\s*(?:am|is|are|was|were|do|does|did|have|has|had|can|could|will|would|shall|"
    r"should|may|might|must|isn['’]t|aren['’]t|don['’]t|doesn['’]t|didn['’]t|won['’]t|"
    r"can['’]t|couldn['’]t|wouldn['’]t|shouldn['’]t)\b",
    re.IGNORECASE,
)
_EN_TAG = re.compile(
    r",\s*(?:\w+n['’]t|is|are|do|does|did|will|can|right|ok|okay|eh)\s*(?:\w+)?\s*\?\s*$",
    re.IGNORECASE,
)


@dataclass
class ExpectedContour:
    """The final melody a sentence calls for, and why.

    Attributes
    ----------
    shape : str
        ``"rise"``, ``"fall"`` or ``"either"``.
    reason : str
        The form that decided it (``"yes/no question without marker"``…).
    """

    shape: str
    reason: str


def expected_contour(sentence: str, language: str) -> ExpectedContour:
    """The final contour ``sentence``'s form calls for.

    Parameters
    ----------
    sentence : str
        One sentence (its final punctuation matters).
    language : str
        ISO-639-1 code; French and English have rules, anything else gets
        the punctuation-only reading (``?`` either, otherwise fall).

    Returns
    -------
    ExpectedContour
        The shape and the reason.

    Examples
    --------
    >>> expected_contour("Tu vas où ?", "fr").shape
    'either'
    >>> expected_contour("Are you coming tonight?", "en").shape
    'rise'
    >>> expected_contour("Where are you going?", "en").shape
    'fall'
    """
    text = sentence.strip()
    lang = (language or "").lower().split("-")[0]
    if not text.endswith("?"):
        if text.endswith("!"):
            return ExpectedContour("fall", "exclamation")
        if text.endswith((",", ";", ":")):
            return ExpectedContour("rise", "continuation")
        return ExpectedContour("fall", "statement")
    alternative = _ALTERNATIVE.get(lang)
    if lang == "fr":
        if _FR_ELLIPTIC.search(text):
            return ExpectedContour("either", "elliptic question")
        if _FR_TAG.search(text):
            return ExpectedContour("rise", "tag or echo question")
        if alternative and alternative.search(text) and not _FR_WH_START.search(text):
            return ExpectedContour("fall", "alternative question")
        if _FR_WH_START.search(text):
            return ExpectedContour("fall", "wh-question, wh-word first")
        if _FR_WH_END.search(text):
            return ExpectedContour("either", "wh-question, wh-word in situ")
        if _FR_EST_CE_QUE.search(text):
            return ExpectedContour("either", "est-ce que question")
        if _FR_INVERSION.search(text):
            return ExpectedContour("either", "question with inversion")
        return ExpectedContour("rise", "yes/no question without marker")
    if lang == "en":
        if _EN_TAG.search(text):
            return ExpectedContour("either", "tag question")
        if alternative and alternative.search(text):
            return ExpectedContour("fall", "alternative question")
        if _EN_WH.search(text):
            return ExpectedContour("fall", "wh-question")
        if _EN_AUX.search(text):
            return ExpectedContour("rise", "yes/no question")
        return ExpectedContour("rise", "declarative question")
    return ExpectedContour("either", "question (no rules for this language)")


def contour_agrees(expected: ExpectedContour, heard: str | None) -> bool | None:
    """Whether a heard contour satisfies the expected one.

    Parameters
    ----------
    expected : ExpectedContour
        What the text calls for.
    heard : str or None
        ``"rise"``, ``"fall"``, ``"level"``, or ``None`` when nothing could
        be measured.

    Returns
    -------
    bool or None
        ``None`` when the contour could not be measured; ``True`` when the
        text accepts either, or the shapes match; ``False`` otherwise. A
        ``level`` ending satisfies only ``either``.

    Examples
    --------
    >>> contour_agrees(ExpectedContour("rise", ""), "fall")
    False
    >>> contour_agrees(ExpectedContour("either", ""), "level")
    True
    """
    if heard is None:
        return None
    return expected.shape == "either" or expected.shape == heard
