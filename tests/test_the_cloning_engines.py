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
