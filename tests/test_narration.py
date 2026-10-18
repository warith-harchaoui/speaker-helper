"""
Reading a document aloud, and the cues that let a page follow the reading.

Every test here was a bug first. The narration path was built in another
repository against a blog, and each of these is a thing that went wrong
there and cost an afternoon:

* a block that is only punctuation killed the engine eleven minutes into a
  narration, and dropping it shifted every later highlight by one;
* the pauses a document asked for were computed everywhere and applied
  nowhere, because two engine wrappers each had their own copy of the loop;
* a piece of audio appended without being recorded produced a narration that
  played correctly and highlighted further and further behind itself, which
  looks like a bug in whatever renders it;
* a formula read symbol by symbol is sound with no meaning in it.

They run against the ``mock`` backend, which needs no model and no network —
so the layout, the cues and the invariant are all exercised in CI, where the
real engine cannot go.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import pytest

from speaker_helper import Settings, Speaker
from speaker_helper.narration import (
    PUNCTUATION_PAUSE_MS,
    Segment,
    Timeline,
    check_timeline_matches_audio,
    coerce_segments,
    cues_to_vtt,
    format_timestamp,
    resolve_spoken_math,
)


def _speaker() -> Speaker:
    """A narrator over the deterministic backend."""
    return Speaker(Settings.from_mapping({"backend": "mock", "language": "fr"}))


# ── The timeline ───────────────────────────────────────────────────────────


def test_the_timeline_counts_silence_and_speech_alike() -> None:
    """Both kinds of time advance the same clock, or the cues drift."""
    timeline = Timeline(1000)
    timeline.silence(500)
    timeline.speech(2000, index=0, text="Hello.")
    timeline.silence(250)
    assert timeline.total_seconds == 2.75
    assert [(c.start_seconds, c.end_seconds) for c in timeline.cues] == [(0.5, 2.5)]


def test_a_timeline_that_disagrees_with_its_audio_is_refused() -> None:
    """The check exists because the symptom is not a crash.

    A piece appended without being recorded gives a narration that plays
    correctly and highlights behind itself, worsening with every sentence.
    """
    timeline = Timeline(1000)
    timeline.speech(1000, index=0, text="One.")
    check_timeline_matches_audio(timeline, 1.0)  # agrees: fine
    with pytest.raises(ValueError, match="appended without being recorded"):
        check_timeline_matches_audio(timeline, 1.5)


def test_timestamps_are_truncated_never_rounded() -> None:
    """Rounding up lets a cue claim to start before the sample that starts it.

    Half a millisecond early is still early, and the highlight then lands on
    a word the voice has not reached.
    """
    assert format_timestamp(1.9999) == "00:00:01.999"
    assert format_timestamp(-5.0) == "00:00:00.000"


def test_a_cue_is_written_on_one_line() -> None:
    """A blank line ends a cue, so a wrapped payload would become two.

    And the second would carry no identifier, shifting every index after it.
    """
    timeline = Timeline(1000)
    timeline.speech(1000, index=7, text="two\nlines\n\nand a gap")
    body = cues_to_vtt(timeline.cues)
    assert "two lines and a gap" in body
    assert body.splitlines()[2] == "7"  # the identifier is the segment index


# ── The layout ─────────────────────────────────────────────────────────────


async def test_a_block_with_nothing_speakable_keeps_its_rank() -> None:
    """The `»` case. It cannot be dropped and it cannot be synthesised.

    A French page closing a quotation on its own line gives a block that is
    one guillemet. The engine refuses it — *produced no phonemes* — and
    dropping it would shift every later cue, because the page still shows it.
    """
    async with _speaker() as spk:
        result = await spk.narrate(
            [Segment(text="Avant."), Segment(text="»"), Segment(text="Après.")]
        )
    indices = [cue.index for cue in result.cues]
    assert indices == [0, 1, 2], "the unspeakable block must still have a cue"
    quiet = next(c for c in result.cues if c.index == 1)
    # The cue spans its own silence rather than flashing for zero seconds: a
    # read-along has to be able to highlight the block the page shows.
    held = quiet.end_seconds - quiet.start_seconds
    assert held == pytest.approx(PUNCTUATION_PAUSE_MS / 1000, abs=1e-3)
    after = next(c for c in result.cues if c.index == 2)
    assert after.start_seconds == pytest.approx(quiet.end_seconds, abs=1e-6)


async def test_an_empty_block_leaves_no_trace_but_does_not_renumber() -> None:
    """Nothing on the page means no cue — and the indices still refer to it."""
    async with _speaker() as spk:
        result = await spk.narrate(
            [Segment(text="One."), Segment(text="   "), Segment(text="Two.")]
        )
    assert [cue.index for cue in result.cues] == [0, 2]


async def test_the_requested_pauses_are_applied() -> None:
    """`pause_before_ms` was computed by everything and applied by nothing."""
    async with _speaker() as spk:
        plain = await spk.narrate([Segment(text="One."), Segment(text="Two.")])
        spaced = await spk.narrate(
            [Segment(text="One."), Segment(text="Two.", pause_before_ms=1000)]
        )
    assert spaced.duration_s > plain.duration_s + 0.9


async def test_a_pause_before_the_first_block_is_not_dead_air() -> None:
    """A "pause before" with nothing before it would be silence at the head."""
    async with _speaker() as spk:
        result = await spk.narrate([Segment(text="One.", pause_before_ms=2000)])
    assert result.cues[0].start_seconds == 0.0


async def test_the_cue_keeps_the_pages_words_not_the_spoken_ones() -> None:
    """The invariant the whole read-along rests on."""
    async with _speaker() as spk:
        result = await spk.narrate(
            [Segment(text="La formule E = mc².", say="La formule E égale m c deux.")]
        )
    assert result.cues[0].text == "La formule E = mc²."


async def test_a_dial_the_backend_lacks_is_reported_not_swallowed() -> None:
    """"You asked for something I cannot do" must not read like "you asked for nothing"."""
    async with _speaker() as spk:
        asked = await spk.narrate([Segment(text="Hello.", emotion="cheerful", intensity="high")])
        plain = await spk.narrate([Segment(text="Hello.")])
    assert asked.ignored_hints == ["emotion", "intensity"]
    assert plain.ignored_hints == []


async def test_pace_reaches_the_backend() -> None:
    """A pace that changes nothing is a dial that lies."""
    async with _speaker() as spk:
        slow = await spk.narrate([Segment(text="A sentence of some length.", pace="slow")])
        fast = await spk.narrate([Segment(text="A sentence of some length.", pace="fast")])
    assert fast.duration_s < slow.duration_s


async def test_a_narration_with_nothing_to_say_is_an_error() -> None:
    """Returning an empty WAV would be a success nobody can hear."""
    async with _speaker() as spk:
        with pytest.raises(ValueError, match="anything speakable"):
            await spk.narrate([Segment(text="»"), Segment(text="…")])


@pytest.mark.parametrize("text", ["»", "« ", "—", "...", "…", "“”"])
def test_punctuation_alone_is_not_speakable(text: str) -> None:
    """The defect that stopped a narration twelve pages in.

    Handed to the engine, such a block raises "nothing to synthesize,
    produced no phonemes" and takes the whole run with it — after eleven
    minutes of audio already made.
    """
    assert not Segment(text=text).is_speakable


@pytest.mark.parametrize("text", ["1", "Bonjour", "x²", "N9", "été"])
def test_anything_with_a_letter_or_a_digit_is_speakable(text: str) -> None:
    """Deliberately broad: the job is to catch punctuation, not to judge."""
    assert Segment(text=text).is_speakable


def test_the_punctuation_pause_is_short_but_not_zero() -> None:
    """Long enough to exist, short enough to read as punctuation not a gap."""
    assert 0 < PUNCTUATION_PAUSE_MS <= 400


# ── Accepting what callers actually have ───────────────────────────────────


def test_segments_arrive_as_dicts_strings_or_dataclasses() -> None:
    """Three shapes because three callers: JSON, Python, and a REPL."""
    out = coerce_segments([Segment(text="a"), {"text": "b", "say": "bee"}, "c"])
    assert [s.text for s in out] == ["a", "b", "c"]
    assert out[1].spoken == "bee"


def test_an_unknown_key_in_a_segment_is_not_a_breaking_change() -> None:
    """A document tool may carry block ids; none of a narrator's business."""
    seg = Segment.from_mapping({"text": "a", "block_id": "h2-3", "heading_level": 2})
    assert seg.text == "a"


# ── Notation ───────────────────────────────────────────────────────────────


def test_notation_becomes_a_sentence_in_the_pages_language() -> None:
    """A French page read with English operator names is worse than silence.

    The listener hears fluent words in the wrong language and assumes they
    misheard.
    """
    segs = resolve_spoken_math([Segment(text=r"On a \(E = mc^2\) ici.")], "fr")
    assert segs[0].say == "On a E égale mc au carré ici."
    assert segs[0].text == r"On a \(E = mc^2\) ici."


def test_a_deliberate_override_is_never_overwritten() -> None:
    """`say` set by hand is a decision; filling it in again would undo it."""
    segs = resolve_spoken_math([Segment(text=r"\(x\)", say="the unknown")], "en")
    assert segs[0].say == "the unknown"


def test_prose_without_notation_gains_no_override() -> None:
    """An identical `say` would make every block look like it carries one."""
    segs = resolve_spoken_math([Segment(text="Just words here.")], "en")
    assert segs[0].say == ""
