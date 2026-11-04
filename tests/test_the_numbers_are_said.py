"""
Digits reach the engine as words, and the page keeps its digits.

The failure this guards against was heard, not imagined: on 2026-11-04 Audio8
read "le 14/11" as an hour and swallowed "Correction :" in a sentence full of
digits. A neural engine reads numbers however its training data did; the cure
is to hand it words. These tests pin the readings a listener would notice
first — dates, times, amounts, the plural rules of French — and the one
invariant the read-along rests on: cues show the document, not the rewrite.

Nothing here loads a model.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import pytest

from speaker_helper import Segment, Settings, Speaker
from speaker_helper.spoken_numbers import en_cardinal, en_ordinal, fr_cardinal, verbalize

# ── French: the spelling rules that change what is said ───────────────────


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (21, "vingt et un"),
        (71, "soixante et onze"),
        (72, "soixante-douze"),
        (80, "quatre-vingts"),
        (81, "quatre-vingt-un"),
        (91, "quatre-vingt-onze"),
        (200, "deux cents"),
        (201, "deux cent un"),
        (1000, "mille"),
        (3200, "trois mille deux cents"),
        (200_000, "deux cent mille"),
        (1_000_000, "un million"),
        (2_000_000, "deux millions"),
    ],
)
def test_french_cardinals(n: int, words: str) -> None:
    """The 70/80/90 forms and the plurals are where hand-rolled spellers fail."""
    assert fr_cardinal(n) == words


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("le 14/11", "le quatorze novembre"),
        ("le 1/1/2026", "le premier janvier deux mille vingt-six"),
        ("à 9h30", "à neuf heures trente"),
        ("à 1h", "à une heure"),
        ("à 21 h", "à vingt et une heures"),
        ("à 14 h 05", "à quatorze heures cinq"),
        ("3 200 €", "trois mille deux cents euros"),
        ("12,50 €", "douze euros cinquante"),
        ("1 €", "un euro"),
        ("3 M€", "trois millions d'euros"),
        ("7,94 %", "sept virgule quatre-vingt-quatorze pour cent"),
        ("7,05 m", "sept virgule zéro cinq m"),
        ("le 1er mai", "le premier mai"),
        ("le 3ème", "le troisième"),
        ("-5 degrés", "moins cinq degrés"),
        ("le 06 12 34 56 78", "le zéro six douze trente-quatre cinquante-six soixante-dix-huit"),
    ],
)
def test_french_readings(text: str, said: str) -> None:
    """What a French listener expects to hear for the common written forms."""
    assert verbalize(text, "fr") == said


def test_the_sentence_that_failed_by_ear_now_reaches_the_engine_as_words() -> None:
    """The exact text Audio8 mangled, end to end."""
    text = (
        "Rendez-vous le 14/11 à 9h30 pour un budget de 3 200 €. "
        "Correction : non pas le 14, mais le 15."
    )
    assert verbalize(text, "fr") == (
        "Rendez-vous le quatorze novembre à neuf heures trente pour un budget de "
        "trois mille deux cents euros. Correction : non pas le quatorze, mais le quinze."
    )


def test_identifiers_with_digits_are_left_alone() -> None:
    """ "4G", "RN7", "H2O" are names; spelling their digit would break them."""
    assert verbalize("La 4G sur la RN7, H2O, 3D.", "fr") == "La 4G sur la RN7, H2O, 3D."


# ── English ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("n", "ordinal"),
    [(1, "first"), (2, "second"), (12, "twelfth"), (21, "twenty-first"), (40, "fortieth")],
)
def test_english_ordinals(n: int, ordinal: str) -> None:
    """Irregular ordinals and the -y → -ieth rule."""
    assert en_ordinal(n) == ordinal


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("July 12th, 2026", "July twelfth, twenty twenty-six"),
        ("at 2:30 p.m.", "at two thirty p.m."),
        ("at 9:05", "at nine oh five"),
        ("at 14:00", "at fourteen hundred"),
        ("$3,200", "three thousand two hundred dollars"),
        ("$12.50", "twelve dollars and fifty cents"),
        ("2.91%", "two point nine one percent"),
        ("11/14/2026", "November fourteenth, twenty twenty-six"),
        ("14/11", "November fourteenth"),
    ],
)
def test_english_readings(text: str, said: str) -> None:
    """US-style readings; a day-first date is recognised when unambiguous."""
    assert verbalize(text, "en") == said


def test_english_cardinal_has_no_and() -> None:
    """One reading, chosen once (US), so a take does not flip style."""
    assert en_cardinal(205) == "two hundred five"


def test_other_languages_pass_through() -> None:
    """A wrong verbalisation is worse than the engine's own guess."""
    assert verbalize("El 14/11 a las 9:30.", "es") == "El 14/11 a las 9:30."


# ── Through the Speaker ────────────────────────────────────────────────────


def _speaker(**extra: object) -> Speaker:
    return Speaker(Settings.from_mapping({"backend": "mock", "language": "fr", **extra}))


async def test_the_engine_hears_words_and_the_cue_keeps_the_digits() -> None:
    """The read-along invariant survives the rewrite."""
    async with _speaker() as spk:
        heard: list[str] = []
        original = spk.engine.synthesize

        async def spy(text: str, **kwargs: object):  # type: ignore[no-untyped-def]
            heard.append(text)
            return await original(text, **kwargs)

        spk.engine.synthesize = spy  # type: ignore[method-assign]
        result = await spk.narrate([Segment(text="Le 14/11 à 9h30.")])

    assert heard == ["Le quatorze novembre à neuf heures trente."]
    assert result.cues[0].text == "Le 14/11 à 9h30."


async def test_the_rewrite_can_be_switched_off() -> None:
    """``numbers_to_words: false`` hands the engine the text as written."""
    async with _speaker(numbers_to_words=False) as spk:
        result = await spk.say("Le 14/11.")
    assert result.text == "Le 14/11."
