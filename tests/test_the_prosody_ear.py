"""
The prosody ear hears melody and energy, and the text says what to expect.

Two halves of the prosody loop, checked without a TTS engine: the acoustic
measurements (on synthetic tones whose pitch is known exactly) and the
intonation rules (French and English sentence forms → expected final
contour).

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import io

import pytest

from speaker_helper.eardrum.intonation import ExpectedContour, contour_agrees, expected_contour
from speaker_helper.eardrum.prosody import ProsodyFeatures, arousal_shift, semitones

# ── 1. The rules: what each sentence form calls for ─────────────────────────


@pytest.mark.parametrize(
    ("sentence", "shape"),
    [
        ("Tu viens ce soir ?", "rise"),  # only the rise makes it a question
        ("Tu viens, non ?", "rise"),
        ("Il est là, hein ?", "rise"),
        ("Quoi ?", "rise"),
        ("Est-ce que tu viens ?", "either"),
        ("Viens-tu ce soir ?", "either"),
        ("Tu vas où ?", "either"),
        ("Pourquoi pas ?", "either"),
        ("Où vas-tu ce soir ?", "fall"),
        ("Pourquoi est-il parti ?", "fall"),
        ("Du thé ou du café ?", "fall"),
        ("C'est fini.", "fall"),
        ("Quelle surprise !", "fall"),
        ("Et puis,", "rise"),
    ],
)
def test_french_sentence_forms(sentence: str, shape: str) -> None:
    """Delais-Roussarie et al. 2015: the form of the question decides the melody."""
    assert expected_contour(sentence, "fr").shape == shape


@pytest.mark.parametrize(
    ("sentence", "shape"),
    [
        ("Are you coming tonight?", "rise"),
        ("You are coming?", "rise"),
        ("Where are you going?", "fall"),
        ("Tea or coffee?", "fall"),
        ("It's late, isn't it?", "either"),
        ("It is late.", "fall"),
    ],
)
def test_english_sentence_forms(sentence: str, shape: str) -> None:
    """Yes/no rises, wh falls, alternatives fall, tags may do either."""
    assert expected_contour(sentence, "en").shape == shape


def test_an_unknown_language_only_trusts_the_punctuation() -> None:
    """No rules: a question accepts any contour, a statement falls."""
    assert expected_contour("¿Vienes?", "es").shape == "either"
    assert expected_contour("Viene.", "es").shape == "fall"


def test_either_accepts_anything_measured_and_nothing_unmeasured() -> None:
    """``either`` is permissive; an unmeasurable take is not a pass."""
    assert contour_agrees(ExpectedContour("either", ""), "fall") is True
    assert contour_agrees(ExpectedContour("rise", ""), "level") is False
    assert contour_agrees(ExpectedContour("rise", ""), None) is None


# ── 2. The ear: measurements on tones whose pitch is known ──────────────────


def _tone(contour_hz) -> bytes:  # type: ignore[no-untyped-def]
    """A voiced-like harmonic tone following ``contour_hz`` (16 kHz WAV)."""
    import numpy as np
    import soundfile as sf

    phase = 2 * np.pi * np.cumsum(contour_hz) / 16000
    signal = 0.3 * np.sin(phase) + 0.15 * np.sin(2 * phase) + 0.05 * np.sin(3 * phase)
    buffer = io.BytesIO()
    sf.write(buffer, signal.astype("float32"), 16000, format="WAV")
    return buffer.getvalue()


@pytest.fixture
def glide():  # type: ignore[no-untyped-def]
    """A 1.5 s tone at 200 Hz that glides by ``st`` semitones over its last 0.4 s."""
    pytest.importorskip("librosa")
    import numpy as np

    t = np.arange(0, 1.5, 1 / 16000)

    def make(st: float) -> bytes:
        """The tone, as WAV bytes."""
        return _tone(200 * 2 ** (np.clip(t - 1.1, 0, None) / 0.4 * st / 12))

    return make


def test_a_rising_end_is_heard_as_a_rise(glide) -> None:  # type: ignore[no-untyped-def]
    """+6 st over the last 0.4 s: a rise, of about that size."""
    from speaker_helper.eardrum.prosody import measure

    final = measure(glide(6)).final
    assert final is not None and final.shape == "rise"
    assert 4.0 < final.rise_st < 7.0


def test_a_falling_end_is_heard_as_a_fall(glide) -> None:  # type: ignore[no-untyped-def]
    """-6 st: a fall."""
    from speaker_helper.eardrum.prosody import measure

    final = measure(glide(-6)).final
    assert final is not None and final.shape == "fall"


def test_a_flat_end_is_level(glide) -> None:  # type: ignore[no-untyped-def]
    """No movement is neither a rise nor a fall."""
    from speaker_helper.eardrum.prosody import measure

    features = measure(glide(0))
    assert features.final is not None and features.final.shape == "level"
    assert features.f0_median_hz == pytest.approx(200, abs=3)


def test_silence_has_no_melody() -> None:
    """No voicing: no F0 and no contour, rather than a made-up one."""
    pytest.importorskip("librosa")
    import numpy as np
    import soundfile as sf

    from speaker_helper.eardrum.prosody import measure

    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(16000, dtype="float32"), 16000, format="WAV")
    features = measure(buffer.getvalue())
    assert features.f0_median_hz is None and features.final is None


def test_octave_errors_are_removed_from_the_track() -> None:
    """A frame an octave and more away from the median is the tracker's mistake."""
    import numpy as np

    from speaker_helper.eardrum.prosody import _median_filter

    track = np.array([200.0, 201.0, 199.0, 410.0, 200.0, 202.0])
    assert np.nanmax(_median_filter(track, 3)) < 250


# ── 3. Arousal: relative to the same voice's neutral reading ────────────────


def test_arousal_is_measured_against_the_neutral_take() -> None:
    """Higher, wider and louder than neutral is more activated; the reverse, calmer."""
    neutral = ProsodyFeatures(200.0, 6.0, None, -20.0, 12.0, 0.6, 2.0)
    excited = ProsodyFeatures(238.0, 9.0, None, -17.0, 14.0, 0.6, 1.8)
    calm = ProsodyFeatures(180.0, 4.0, None, -23.0, 10.0, 0.6, 2.2)
    assert arousal_shift(excited, neutral) > 1.5
    assert arousal_shift(calm, neutral) < -1.0
    assert arousal_shift(neutral, neutral) == 0


def test_semitones_are_the_unit() -> None:
    """An octave is twelve semitones, whatever the voice."""
    assert semitones(440.0, 220.0) == 12.0
    assert semitones(110.0, 220.0) == -12.0


# ── 4. The loop: text expectation against audio measurement ─────────────────

from speaker_helper.eardrum.expressive import (  # noqa: E402
    TextExpression,
    arousal_agrees,
    check_expression,
    expected_arousal_from_tag,
    parse_expression,
)
from speaker_helper.eardrum.prosody import Contour  # noqa: E402


def _features(f0: float, contour: str | None) -> ProsodyFeatures:
    """Features with a chosen median pitch and final contour shape."""
    final = Contour(0.0, 0.0, 0.0, contour) if contour else None
    return ProsodyFeatures(f0, 6.0, final, -20.0, 12.0, 0.6, 2.0)


class _Engine:
    """Scripted engine: (say, emotion, intensity) → measured features."""

    def __init__(self, table: dict[tuple[str, str, str], ProsodyFeatures]) -> None:
        """Keep the table; record every request."""
        self.table = table
        self.asked: list[tuple[str, str, str]] = []

    async def say(self, dials: dict[str, str]) -> bytes:
        """Return the dials themselves as the 'audio'."""
        key = (dials["say"], dials.get("emotion", ""), dials.get("intensity", ""))
        self.asked.append(key)
        return repr(key).encode()

    def measure(self, wav: bytes) -> ProsodyFeatures:
        """Look the take up in the table."""
        return self.table[eval(wav.decode())]  # noqa: S307 - test-only round-trip of a repr


def _run(engine: _Engine, segment: dict, levers=None, infer=None):  # type: ignore[no-untyped-def]
    """check_expression, synchronously."""
    import asyncio

    return asyncio.run(
        check_expression(engine.say, engine.measure, segment, "fr", infer=infer, levers=levers)
    )


def test_a_question_that_does_not_rise_is_caught() -> None:
    """Measured on kokoro: "Tu viens ce soir ?" falls like a statement."""
    q = "Tu viens ce soir ?"
    engine = _Engine({(q, "neutral", ""): _features(220, "fall")})
    result = _run(engine, {"text": q})
    assert result.expected_contour["shape"] == "rise"
    assert result.takes[0].contour_ok is False
    assert result.verdict == "unresolved"


def test_the_tag_sets_the_expected_arousal_and_the_neutral_take_is_the_reference() -> None:
    """An angry line must sound more activated than its neutral reading."""
    s = "Tu as encore oublié."
    engine = _Engine(
        {
            (s, "neutral", ""): _features(200, "fall"),
            (s, "angry", ""): _features(240, "fall"),  # +3.2 st median
        }
    )
    result = _run(engine, {"text": s, "emotion": "angry"})
    assert result.expected == {
        "arousal": "high",
        "valence": "neutral",
        "emotion": "angry",
        "source": "tag",
    }
    assert result.takes[0].arousal_ok and result.verdict == "ok"
    assert engine.asked == [(s, "neutral", ""), (s, "angry", "")]


def test_a_lever_that_helps_is_kept_and_the_loop_stops_there() -> None:
    """The first take is flat; turning the intensity up makes it agree."""
    s = "Quelle nouvelle !"
    engine = _Engine(
        {
            (s, "neutral", ""): _features(200, "fall"),
            (s, "enthusiastic", ""): _features(205, "fall"),
            (s, "enthusiastic", "1.0"): _features(245, "fall"),
        }
    )

    def louder(dials, contour, arousal):  # type: ignore[no-untyped-def]
        """Push the emotion dial to its maximum."""
        return {**dials, "intensity": "1.0"}

    def never(dials, contour, arousal):  # type: ignore[no-untyped-def]
        """Must not be reached once the take agrees."""
        raise AssertionError("the loop went on after agreement")

    result = _run(engine, {"text": s, "emotion": "enthusiastic"}, levers=[louder, never])
    assert result.verdict == "fixed"
    assert result.takes[result.best].lever == "louder"


def test_without_a_tag_the_words_are_read_by_the_llm() -> None:
    """No tag: the expression comes from reading the sentence."""
    s = "Il nous a quittés ce matin."
    engine = _Engine(
        {
            (s, "neutral", ""): _features(200, "fall"),
            (s, "sad", ""): ProsodyFeatures(
                185.0, 4.0, Contour(0, 0, 0, "fall"), -23.0, 10.0, 0.6, 2.2
            ),
        }
    )
    result = _run(
        engine,
        {"text": s},
        infer=lambda text, lang: TextExpression(
            arousal="low", valence="negative", emotion="sad", source="llm"
        ),
    )
    assert result.expected["source"] == "llm" and result.expected["valence"] == "negative"
    assert result.verdict == "ok"  # lower, narrower, quieter: calmer


def test_the_llm_answer_must_be_strict_json() -> None:
    """Anything but the three allowed fields is refused or neutralised."""
    assert parse_expression('{"arousal": "low", "valence": "x", "emotion": "y"}') == TextExpression(
        "low", "neutral", "neutral", "llm"
    )
    assert parse_expression("not json") is None
    assert parse_expression('{"arousal": "extreme"}') is None


def test_arousal_bands_and_tags() -> None:
    """High needs a clear rise in activation, neutral a small change either way."""
    assert arousal_agrees("high", 1.0) and not arousal_agrees("high", 0.5)
    assert arousal_agrees("low", -1.2) and not arousal_agrees("low", -0.2)
    assert arousal_agrees("neutral", 0.3) and not arousal_agrees("neutral", -1.5)
    assert expected_arousal_from_tag("whispering") == "low"
    assert expected_arousal_from_tag("unknown") is None


def test_a_document_run_reports_agreement_and_writes_tuned_segments(tmp_path) -> None:
    """The whole prosody run: one segment agrees, one is fixed by a lever."""
    import asyncio
    import json
    from types import SimpleNamespace

    from speaker_helper import Settings
    from speaker_helper.eardrum.expressive import run_prosody_async, segments_from_text

    table = {
        ("Tu viens ce soir ?", "neutral", "normal"): _features(220, "fall"),
        ("Tu viens ce soir ?!", "neutral", "normal"): _features(222, "rise"),
        ("C'est fini.", "neutral", "normal"): _features(200, "fall"),
    }

    class Speaker:
        """Narrates one block as its dials, so the measure can look them up."""

        async def narrate(self, blocks, language=None):  # type: ignore[no-untyped-def]
            """Encode the block's dials in place of audio."""
            b = blocks[0]
            return SimpleNamespace(
                wav_bytes=repr((b.spoken, b.emotion or "neutral", b.pace)).encode()
            )

    def measure(wav: bytes) -> ProsodyFeatures:
        """Look the take up."""
        return table[eval(wav.decode())]  # noqa: S307 - test-only round-trip of a repr

    def marked(dials, contour, arousal):  # type: ignore[no-untyped-def]
        """The question-marking lever, alone."""
        from speaker_helper.eardrum.expressive import marked_question

        return marked_question(dials, contour, arousal)

    report = asyncio.run(
        run_prosody_async(
            Settings.from_mapping({"backend": "mock", "language": "fr"}),
            segments_from_text("Tu viens ce soir ? C'est fini."),
            infer=False,
            out_dir=tmp_path,
            speaker=Speaker(),
            measure=measure,
            levers=[marked],
        )
    )
    assert [r.verdict for r in report.results] == ["fixed", "ok"]
    assert report.agreement == {"contour": 0.5, "arousal": 1.0}
    tuned = json.loads(report.tuned.read_text(encoding="utf-8"))
    # The page keeps its question mark; only what is said changes.
    assert tuned[0] == {
        "text": "Tu viens ce soir ?",
        "say": "Tu viens ce soir ?!",
        "emotion": "neutral",
        "intensity": "",
        "pace": "normal",
    }
    assert tuned[1] == {"text": "C'est fini."}
    page = report.html.read_text(encoding="utf-8")
    assert "prosodie" in page and "50 %" in page
    assert (tmp_path / "audio" / "s000" / "take1.wav").is_file()


def test_the_levers_only_act_where_they_apply() -> None:
    """Each lever declines a situation it cannot help."""
    from speaker_helper.eardrum.expressive import (
        closer_to_the_text,
        marked_question,
        stronger_emotion,
    )

    rise = ExpectedContour("rise", "")
    either = ExpectedContour("either", "")
    dials = {"say": "Tu viens ?", "emotion": "neutral", "intensity": "", "pace": "normal"}
    assert stronger_emotion(dials, rise, "neutral") is None
    assert stronger_emotion(dials, rise, "high") == {
        **dials,
        "emotion": "enthusiastic",
        "intensity": "1.0",
    }
    assert stronger_emotion({**dials, "emotion": "angry"}, rise, "high")["emotion"] == "angry"
    assert closer_to_the_text(dials, either, "neutral") is None
    assert closer_to_the_text(dials, rise, "neutral")["pace"] == "slow"
    assert marked_question(dials, rise, "neutral")["say"] == "Tu viens ?!"
    assert marked_question({**dials, "say": "Tu viens ?!"}, rise, "neutral") is None
    assert marked_question(dials, either, "neutral") is None
