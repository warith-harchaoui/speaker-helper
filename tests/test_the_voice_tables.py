"""
What the Kokoro backend must get right before it ever loads a model.

Everything here runs without the 340 MB of weights, without a network and
without espeak-ng. That is deliberate: the expensive half is the model, and
none of the mistakes this file is written for live there. They live in the
tables — a default voice that does not exist, a language paired with a voice
that does not speak it, a prefix with no entry.

The pairing is the one that matters and the one a careless edit breaks
silently. Kokoro encodes the language in the voice name's first letter, and
the language is what the phonemiser works from. Pair ``fr`` with an ``a``
voice and the result is not French in an American accent — it is an American
reading French spelling aloud. It sounds like a bad voice rather than a wrong
setting, which is why it would be looked for in the wrong place.

These checks arrived with the engine, from the package that used to carry it.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio

import pytest

from speaker_helper.backends.kokoro import (
    BUILTIN_VOICES,
    DEFAULT_VOICE_BY_LANG,
    FALLBACK_VOICE,
    VOICE_PREFIX_LANG,
    KokoroEngine,
    language_for,
    normalise_language,
    voice_for_language,
)
from speaker_helper.config import Settings

# ── The tables agree with each other ───────────────────────────────────────


def test_every_default_voice_is_a_voice_this_engine_has() -> None:
    """A default that does not exist fails at the first narration.

    And in a language nobody on the team necessarily speaks, which is where
    the time goes.
    """
    catalogue = set(BUILTIN_VOICES)
    for language, voice in DEFAULT_VOICE_BY_LANG.items():
        assert voice in catalogue, f"{language} defaults to {voice!r}, which is not a voice"
    assert FALLBACK_VOICE in catalogue


@pytest.mark.parametrize(("language", "voice"), sorted(DEFAULT_VOICE_BY_LANG.items()))
def test_a_languages_default_voice_speaks_that_language(language: str, voice: str) -> None:
    """The pairing the whole module rests on. See this file's docstring."""
    implied = language_for(voice)
    assert implied.split("-")[0].replace("cmn", "zh") == language


def test_every_voice_in_the_catalogue_names_a_language_we_know() -> None:
    """A prefix with no entry silently becomes American English."""
    for voice in BUILTIN_VOICES:
        assert voice[:1] in VOICE_PREFIX_LANG, voice


def test_the_catalogue_covers_every_language_the_model_ships() -> None:
    """Guards the direction the parametrised test above cannot.

    That one only checks languages already in the table, so a language
    *dropped* from it would take its own test case with it and the suite
    would stay green while the voice became unreachable.
    """
    prefixes = {voice[:1] for voice in BUILTIN_VOICES}
    covered = {DEFAULT_VOICE_BY_LANG[lang][:1] for lang in DEFAULT_VOICE_BY_LANG}
    # en has two prefixes (a = American, b = British) and one default.
    assert prefixes - covered == {"b"}, f"no default voice for prefixes {prefixes - covered}"


def test_the_catalogue_is_the_whole_catalogue() -> None:
    """54 voices. A sample would make "which voices are there" unanswerable."""
    assert len(BUILTIN_VOICES) == 54
    assert len(set(BUILTIN_VOICES)) == 54, "a duplicate would hide a missing voice"


# ── Choosing, without the weights ──────────────────────────────────────────


def test_listing_the_voices_does_not_need_the_weights() -> None:
    """Somebody choosing a narrator is deciding whether to download at all.

    "Fetch 340 MB, then ask again" is a poor answer to "which voices are
    there".
    """
    engine = KokoroEngine(Settings())
    listing = asyncio.run(engine.list_voices())
    assert len(listing.voices) >= 54
    assert all(voice.language for voice in listing.voices)


@pytest.mark.parametrize(
    ("code", "expected"),
    [("fr", "ff_siwis"), ("en", "af_heart"), ("ja", "jf_alpha"), ("zh", "zf_xiaoxiao")],
)
def test_a_language_picks_the_voice_that_speaks_it(code: str, expected: str) -> None:
    voice, fell_back = voice_for_language(code)
    assert (voice, fell_back) == (expected, False)


def test_a_language_with_no_voice_says_so_rather_than_pretending() -> None:
    """The audio alone will not make this obvious to whoever generated it.

    They are, by construction, someone who does not speak the language.
    """
    voice, fell_back = voice_for_language("sw")
    assert voice == FALLBACK_VOICE
    assert fell_back is True


# ── The language code espeak will actually accept ──────────────────────────


@pytest.mark.parametrize(
    ("given", "expected"),
    [("fr", "fr-fr"), ("fr-FR", "fr-fr"), ("en", "en-us"), ("en-gb", "en-gb"), ("", "")],
)
def test_a_language_code_is_translated_for_the_phonemiser(given: str, expected: str) -> None:
    """``fr`` is a valid language code and not a language espeak knows.

    It answers *language "fr" is not supported by the espeak backend* and the
    synthesis fails. A caller who says ``language="fr"`` is right; translating
    it is this module's job.
    """
    assert normalise_language(given) == expected


def test_an_unknown_language_normalises_to_nothing_rather_than_a_guess() -> None:
    """Empty lets the caller fall back to what the voice implies.

    Guessing would hand espeak a string it refuses, which fails later and
    further away.
    """
    assert normalise_language("klingon") == ""


# ── Refusals that name the alternative ─────────────────────────────────────


def test_cloning_is_refused_rather_than_ignored() -> None:
    """An engine that accepts a sample it cannot use is worse than one that says no.

    The caller's next question is always "then which one", so the refusal
    answers it.
    """
    engine = KokoroEngine(Settings())
    with pytest.raises(NotImplementedError) as raised:
        asyncio.run(engine.clone_voice("x", []))
    message = str(raised.value)
    assert "openvoice" in message and "chatterbox" in message


def test_health_names_what_is_missing_without_loading_anything() -> None:
    """A health check that pays for an ONNX session is not a readiness probe."""
    import sys

    engine = KokoroEngine(Settings())
    report = asyncio.run(engine.health())
    assert report["engine"] == "kokoro"
    assert report["status"] in {"ok", "unavailable"}
    if report["status"] == "unavailable":
        assert report["fix"], "an unavailable engine must say what would fix it"
    assert "onnxruntime" not in sys.modules or report["status"] == "ok"
