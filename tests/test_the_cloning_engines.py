"""
The two engines that clone, and the dials they do and do not have.

Neither test here loads a model: the arithmetic that maps a document's words
— "cheerful", "high" — onto an engine's dial is where the mistakes live, and
it is pure. A hallucinated intensity arriving as ``999`` and coming back as a
scream is the failure these clamps exist for.

These checks arrived with the engines, from the package that used to carry
them.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui/
"""

from __future__ import annotations

import asyncio

import pytest

from speaker_helper.backends.chatterbox import (
    EMOTION_EXAGGERATION_BASE,
    PACE_CFG_WEIGHT,
    ChatterboxEngine,
    emotion_to_exaggeration,
)
from speaker_helper.backends.openvoice import EMOTION_STYLE, OpenVoiceEngine
from speaker_helper.cloning import DEFAULT_CLONE_NAME
from speaker_helper.config import Settings

# ── Chatterbox: emotion and intensity onto one dial ────────────────────────


def test_neutral_at_half_intensity_is_the_base() -> None:
    """0.5 means "use the base", not "halve it"."""
    assert emotion_to_exaggeration("neutral", 0.5) == pytest.approx(0.5)


def test_intensity_moves_the_dial_monotonically() -> None:
    """A dial that does not order its own inputs is not a dial."""
    low = emotion_to_exaggeration("cheerful", 0.0)
    mid = emotion_to_exaggeration("cheerful", 0.5)
    high = emotion_to_exaggeration("cheerful", 1.0)
    assert low < mid < high
    assert 0.0 <= low <= 2.0 and 0.0 <= high <= 2.0


def test_an_unknown_emotion_reads_as_neutral_rather_than_failing() -> None:
    """A document may ask for a mood this model has never heard of."""
    assert emotion_to_exaggeration("nope", 0.5) == pytest.approx(0.5)


def test_an_impossible_intensity_is_clamped_not_obeyed() -> None:
    """The input that arrives as 999 and comes back as a scream."""
    assert 0.0 <= emotion_to_exaggeration("angry", 999.0) <= 2.0
    assert 0.0 <= emotion_to_exaggeration("sad", -40.0) <= 2.0


def test_every_base_sits_inside_the_dials_range() -> None:
    """A base outside 0–2 would clamp for every intensity, silently flattening it."""
    for emotion, base in EMOTION_EXAGGERATION_BASE.items():
        assert 0.0 <= base <= 2.0, emotion


def test_the_pace_weights_order_the_way_the_names_do() -> None:
    """Slow reading wants stability; fast can afford variation."""
    assert PACE_CFG_WEIGHT["slow"] > PACE_CFG_WEIGHT["normal"] > PACE_CFG_WEIGHT["fast"]


# ── OpenVoice: emotions it knows, and the ones it does not ─────────────────


def test_an_unmapped_emotion_becomes_the_default_style() -> None:
    """Failing on an unknown mood would make the document's vocabulary brittle."""
    assert EMOTION_STYLE.get("not-a-mood", "default") == "default"


def test_the_neutral_emotion_maps_to_the_default_style() -> None:
    """Otherwise every ordinary sentence would carry a style it never asked for."""
    assert EMOTION_STYLE["neutral"] == "default"


# ── Both: cloning needs a reference, and says so ───────────────────────────


@pytest.mark.parametrize("engine_class", [ChatterboxEngine, OpenVoiceEngine])
def test_cloning_with_no_sample_is_refused(engine_class: type) -> None:
    """An empty clone would silently fall back to the default speaker.

    Which sounds like the model ignoring the request, rather than like a call
    that was missing its argument.
    """
    engine = engine_class(Settings())
    with pytest.raises(ValueError, match="at least one reference"):
        asyncio.run(engine.clone_voice("someone", []))


@pytest.mark.parametrize("engine_class", [ChatterboxEngine, OpenVoiceEngine])
def test_health_names_what_is_missing_without_loading_a_model(engine_class: type) -> None:
    """A probe that pays for torch is not a probe."""
    report = asyncio.run(engine_class(Settings()).health())
    assert report["status"] in {"ok", "unavailable"}
    if report["status"] == "unavailable":
        assert report["fix"]


def test_chatterbox_refuses_empty_text_before_loading_a_model() -> None:
    """Empty input is refused here, because upstream does something worse.

    ``chatterbox.mtl_tts.punc_norm("")`` does not raise — it SUBSTITUTES the
    English sentence "You need to add some text for me to talk.", which the
    model then speaks. Emitting an unrequested English sentence in the middle
    of a French narration is worse than a crash: it sounds deliberate. The
    refusal matches the kyutai backend's, so the surfaces behave alike, and it
    happens before any weights are touched.
    """
    engine = ChatterboxEngine(Settings.from_mapping({"backend": "chatterbox", "language": "fr"}))
    for blank in ("", "   ", "\n\t "):
        with pytest.raises(ValueError, match="empty"):
            asyncio.run(engine.synthesize(blank))


# ── Chatterbox: what the catalogue says about the voice that will speak ────


def test_chatterbox_lists_the_bundled_reference_as_female() -> None:
    """The listed voice must carry the gender the engine actually guarantees.

    ``ChatterboxEngine.__init__`` deliberately falls back to the bundled
    CC BY 4.0 reference rather than the model's own speaker, because "a female
    voice in every language" is a contract this engine keeps and the model card
    promises nothing about its built-in speaker. That guarantee was invisible:
    the catalogue answered ``default`` with a blank gender, so anyone choosing a
    narrator from ``voices`` — the CLI, the GUI, an agent reading the HTTP API —
    saw an engine with no female voice and reached for another one.

    The gender is the assertion; the id and provenance travel with it because
    CC BY 4.0 asks for attribution wherever the voice is named.
    """
    engine = ChatterboxEngine(Settings.from_mapping({"backend": "chatterbox", "language": "en"}))
    listing = asyncio.run(engine.list_voices())

    assert listing.engine == "chatterbox"
    assert listing.voices, "chatterbox must name the voice it will clone"
    female = [v for v in listing.voices if v.gender == "female"]
    assert female, f"no female voice listed: {[(v.voice_id, v.gender) for v in listing.voices]}"
    assert female[0].voice_id == DEFAULT_CLONE_NAME
    assert "CC BY 4.0" in female[0].name


def test_chatterbox_does_not_claim_a_gender_for_somebody_elses_recording() -> None:
    """A custom ``voice_sample`` is reported, and its gender is left unstated.

    Guessing it would be worse than the blank the dataclass already means:
    whoever supplied the recording is the one who knows, and a wrong label is
    harder to notice than a missing one.
    """
    engine = ChatterboxEngine(
        Settings.from_mapping(
            {"backend": "chatterbox", "language": "en", "voice_sample": "/tmp/somebody-else.wav"}
        )
    )
    listing = asyncio.run(engine.list_voices())

    assert listing.voices
    assert listing.voices[0].gender == ""
    assert "somebody-else" in listing.voices[0].voice_id
