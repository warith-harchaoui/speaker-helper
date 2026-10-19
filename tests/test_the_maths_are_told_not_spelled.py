"""
What a formula sounds like when somebody hears it once, with no page.

`speech_text` is the part of this package that decides what the voice *says*
where the page *shows* notation. It carried 40 % coverage and no test of its
own: the suite exercised it only through the live Kokoro round-trip, which
means it was covered by actually synthesising speech — and when that test
moved behind the `slow` marker (it gates on a real-time factor, which measures
the machine), the coverage it was lending vanished with it.

That is the right reading of the drop. The module was never tested; it was
*visited* by something slow and unrelated.

These tests assert the distinction the module exists to make, stated in its
own comments: a named operator reads as a phrase — "the expected value of
theta given m" — rather than as a transliteration of its symbols. Telling a
formula, not spelling it.

Author
------
Warith HARCHAOUI <warithmetics@deraison.ai>
"""

from __future__ import annotations

import pytest

from speaker_helper import speech_text as st

# ── The constructs, in both languages the package claims ──────────────────


@pytest.mark.parametrize(
    ("latex", "english", "french"),
    [
        (r"x^2", "x squared", "x au carré"),
        (r"\frac{a}{b}", "a over b", "a sur b"),
        (r"\sqrt{x}", "the square root of x", "la racine carrée de x"),
        (r"\alpha + \beta", "alpha plus beta", "alpha plus beta"),
    ],
)
def test_a_construct_reads_the_same_way_in_each_language(
    latex: str, english: str, french: str
) -> None:
    """The vocabulary differs; the shape of the sentence does not."""
    assert st.speak_math(latex, "en") == english
    assert st.speak_math(latex, "fr") == french


def test_a_named_operator_becomes_a_phrase_not_a_transliteration() -> None:
    """The distinction this module exists to make.

    ``\\mathbb{E}[\\theta \\mid m]`` is "the expected value of theta given m",
    not "E, open bracket, theta, mid, m, close bracket". Only the first
    survives being heard once with no page in front of you — which is the
    whole situation a narration is in.
    """
    said = st.speak_math(r"\mathbb{E}[\theta \mid m]", "en")
    assert said == "the expected value of theta given m"
    # Nothing of the bracket notation leaks through.
    for symbol in ("[", "]", r"\mid", "mathbb"):
        assert symbol not in said

    assert st.speak_math(r"\mathbb{E}[\theta]", "fr") == "l'espérance de theta"


def test_backslashes_and_braces_never_reach_the_voice() -> None:
    """A reader hears the formula; they must not hear the markup."""
    for latex in (
        r"\sum_{i=1}^{n} x_i",
        r"\int_0^1 f(x)\,dx",
        r"P(A \cap B)",
        r"\frac{\alpha}{\beta}",
    ):
        said = st.speak_math(latex, "en")
        assert "\\" not in said, f"{latex} leaked a backslash: {said}"
        assert "{" not in said and "}" not in said, f"{latex} leaked a brace: {said}"
        assert said.strip(), f"{latex} produced nothing"


def test_set_and_function_notation_keeps_its_names() -> None:
    """`P(A \\cap B)` is read, not decoded: the letters are the author's."""
    said = st.speak_math(r"P(A \cap B)", "en")
    assert "intersection" in said
    assert "P" in said and "A" in said and "B" in said


# ── The threshold that decides whether a model is asked at all ────────────


def test_complexity_grows_with_the_formula() -> None:
    """A bare symbol is not a formula; a sum of fractions is."""
    assert st.complexity("x") == 0
    assert st.complexity("x^2") > st.complexity("x")
    assert st.complexity(r"\sum_{i=1}^{n}\frac{x_i}{n}") > st.complexity("x^2")


def test_the_narration_threshold_sits_above_the_simple_cases() -> None:
    """`NARRATE_ABOVE` is what separates "spell it" from "ask a model".

    It has to be above the everyday constructs, or every squared term would
    cost a model call; and below a nested sum, or the hard ones would be
    transliterated. Both halves are asserted, because a threshold is only
    meaningful relative to what falls either side of it.
    """
    assert st.complexity("x^2") <= st.NARRATE_ABOVE
    assert st.complexity(r"\frac{a}{b}") <= st.NARRATE_ABOVE
    assert st.complexity(r"\sum_{i=1}^{n}\frac{x_i}{n}") > st.NARRATE_ABOVE


# ── Prose, which is where this is actually used ───────────────────────────


def test_inline_maths_is_folded_into_the_sentence() -> None:
    """The cue keeps the page's words; only the notation changes."""
    assert st.speakable("See $x^2$ here.", "en") == "See x squared here."
    assert st.speakable("Plain prose.", "en") == "Plain prose."


def test_prose_without_maths_is_returned_unchanged() -> None:
    """A sentence the voice can already say must not be rewritten at all."""
    for text in ("Hello.", "Une phrase simple.", "Numbers 1, 2 and 3."):
        assert st.speakable(text, "en") == text


# ── The refusal ───────────────────────────────────────────────────────────


def test_a_language_without_vocabulary_is_refused_not_served_in_english() -> None:
    """Reading a German page with English operators is worse than failing.

    The listener would hear "squared" in the middle of a German sentence and
    have no way to know the page said something else. The module raises
    instead, and names what to do about it.
    """
    for lang in ("de", "es", "xx"):
        with pytest.raises(st.SpeechMismatch) as raised:
            st.speak_math(r"x^2", lang)
        assert lang in str(raised.value)
        assert "WORDS" in str(raised.value)


def test_the_languages_with_vocabulary_are_the_ones_that_work() -> None:
    """`WORDS` is the registry, and it is what the refusal consults."""
    assert set(st.WORDS) == {"en", "fr"}
    for lang in st.WORDS:
        assert st.speak_math(r"x^2", lang)
