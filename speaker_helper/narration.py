"""
Narration: a document read aloud, and the timed track that follows it.

Module summary
--------------
:func:`~speaker_helper.speaker.Speaker.synthesize` answers "what does this
sentence sound like". This module answers the different question a *document*
asks: read these blocks, in this order, with the pauses their structure calls
for, and tell me **where each one landed in the audio** so a page can follow
along while it plays.

That second half is the part a plain `text -> wav` call cannot give you, and
the part that is easy to get subtly wrong. Three facts, each learned the
expensive way:

**What the voice says is not always what the page shows.** A formula is
notation on the page and a sentence in the ear; a footnote marker is a
signpost on the page and a stray number in the ear. So a :class:`Segment`
carries both: ``text`` is the page's words and goes into the cue, ``say`` is
what the engine is handed. The invariant is that the cue keeps the page's
words — that is what lets a read-along highlight land on the right ones.

**A segment with nothing speakable in it still takes its turn.** A French
page closing a quotation on its own line gives a "sentence" that is a single
``»``. Kokoro refuses it — *nothing to synthesize, produced no phonemes* —
and the obvious repair, dropping it, is worse than the crash: the page still
shows that block, so every later sentence would light up one place out. It
becomes a short silence that keeps its rank.

**The timeline and the file must agree, and something has to check.** The
offsets are exact and already known while the audio is concatenated; the risk
is a piece appended without being recorded. :meth:`Timeline.total_seconds` is
compared against the written file, and a mismatch is an error rather than a
narration whose highlighting drifts further out with every sentence.

Usage example
-------------
>>> timeline = Timeline(1000)
>>> timeline.silence(500)
500
>>> timeline.speech(2000, index=0, text="Hello.")
>>> timeline.total_seconds
2.5
>>> print(cues_to_vtt(timeline.cues))
WEBVTT
<BLANKLINE>
0
00:00:00.500 --> 00:00:02.500
Hello.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal

# How fast to read, by name rather than by number. Names travel between a
# document's structure and an engine's dial; a float does not survive the trip
# with its intent intact ("0.9" says nothing about *why*).
Pace = Literal["slow", "normal", "fast"]

#: Multipliers the engines are handed for each pace.
PACE_SPEED: dict[str, float] = {"slow": 0.85, "normal": 1.0, "fast": 1.15}

#: How long a segment with nothing speakable in it is held for. Short enough
#: to read as punctuation rather than as a gap, long enough to exist.
PUNCTUATION_PAUSE_MS: int = 120

#: Something an engine could plausibly pronounce. Deliberately broad — any
#: letter or digit in any script — because the job is to catch the segment
#: that is *only* punctuation, not to judge pronounceability.
_SPEAKABLE = re.compile(r"[^\W_]", re.UNICODE)


@dataclass
class Segment:
    """One block of a document, as the narrator receives it.

    Parameters
    ----------
    text : str
        The page's words. This is what the cue carries, and therefore what a
        read-along highlights. Never substituted.
    say : str
        What the engine should actually pronounce, when that differs — a
        formula read as a sentence, a footnote marker dropped. Empty means
        "say ``text``", which is the ordinary case.
    pause_before_ms, pause_after_ms : float
        Silence the document's structure asks for around this block — the gap
        that sets a heading apart from the paragraph before it. Requested by
        the caller, applied here.
    pace : str
        ``"slow"``, ``"normal"`` or ``"fast"``. See :data:`PACE_SPEED`.
    emotion, intensity : str
        Asked for by some documents, honoured by some engines. A backend that
        has no such dial reports the name in
        :attr:`NarrationResult.ignored_hints` rather than pretending.

    Notes
    -----
    ``pause_before_ms`` is skipped on the first segment: a "pause before" with
    nothing before it is dead air at the head of the file.
    """

    text: str
    say: str = ""
    pause_before_ms: float = 0.0
    pause_after_ms: float = 0.0
    pace: str = "normal"
    emotion: str = ""
    intensity: str = ""

    @property
    def spoken(self) -> str:
        """What to hand the engine: ``say`` when set, else ``text``."""
        return (self.say or self.text).strip() or self.text.strip()

    @property
    def is_speakable(self) -> bool:
        """Whether anything here could be pronounced at all.

        ``False`` for a segment that is only punctuation. Such a segment is
        not dropped — see this module's docstring — it becomes a silence that
        keeps its rank.
        """
        return bool(_SPEAKABLE.search(self.spoken))

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> Segment:
        """Build a segment from a plain dict, ignoring keys it does not know.

        The wire format between a document tool and this one is JSON, and the
        document side is free to carry extra keys (block ids, heading levels)
        that are none of a narrator's business. Unknown keys are dropped here
        rather than rejected, so adding one upstream is not a breaking change.
        """
        return cls(
            text=str(raw.get("text", "")),
            say=str(raw.get("say", "") or ""),
            pause_before_ms=float(raw.get("pause_before_ms", 0) or 0),
            pause_after_ms=float(raw.get("pause_after_ms", 0) or 0),
            pace=str(raw.get("pace", "normal") or "normal"),
            emotion=str(raw.get("emotion", "") or ""),
            intensity=str(raw.get("intensity", "") or ""),
        )


@dataclass(frozen=True)
class SpeechCue:
    """One narrated block, with the slice of audio that speaks it.

    Parameters
    ----------
    index : int
        Position in the **original** segment list, not in the audio. The two
        differ: a segment whose text is empty after cleaning is never
        synthesised, so counting emitted pieces drifts from counting segments.
        Carrying the original index is what lets a page map a cue back to the
        block it came from.
    text : str
        The page's words — see :class:`Segment`.
    start_seconds, end_seconds : float
        Where this block is spoken, from the head of the file.
    """

    index: int
    text: str
    start_seconds: float
    end_seconds: float


class Timeline:
    """Accumulates durations while a backend accumulates audio.

    Two jobs, one object: apply the pauses the segments ask for, and record
    where every segment landed. Both need the same running sample count, and
    keeping them apart is how they drift.

    Deliberately numpy-free: it counts samples and the caller holds the
    arrays, so this module imports with nothing but the standard library —
    which is what lets a caller build and inspect a narration plan without the
    ONNX runtime anywhere near it.

    Examples
    --------
    >>> timeline = Timeline(1000)
    >>> timeline.silence(500)
    500
    >>> timeline.speech(2000, index=0, text="Hello.")
    >>> timeline.silence(250)
    250
    >>> [(c.start_seconds, c.end_seconds) for c in timeline.cues]
    [(0.5, 2.5)]
    >>> timeline.total_seconds
    2.75
    """

    def __init__(self, sample_rate_hz: int) -> None:
        self.sample_rate_hz = int(sample_rate_hz)
        self._samples = 0
        self._cues: list[SpeechCue] = []

    def silence(self, milliseconds: float) -> int:
        """Advance the clock by ``milliseconds``; return the samples to append.

        Returning the count rather than an array is what keeps this module
        numpy-free. A caller that ignores the return value desynchronises the
        timeline from its own audio, which is exactly what
        :func:`check_timeline_matches_audio` exists to catch.
        """
        count = int(self.sample_rate_hz * max(0.0, float(milliseconds)) / 1000.0)
        self._samples += count
        return count

    def speech(self, sample_count: int, *, index: int, text: str) -> None:
        """Record that ``sample_count`` samples of audio speak ``text``."""
        start = self._samples / float(self.sample_rate_hz)
        self._samples += int(sample_count)
        end = self._samples / float(self.sample_rate_hz)
        self._cues.append(SpeechCue(index=index, text=text, start_seconds=start, end_seconds=end))

    @property
    def cues(self) -> list[SpeechCue]:
        """Every recorded cue, in playback order."""
        return list(self._cues)

    @property
    def total_seconds(self) -> float:
        """Length of the audio described so far, silences included."""
        return self._samples / float(self.sample_rate_hz)


@dataclass
class NarrationResult:
    """A narrated document: the audio, and where every block landed in it.

    Parameters
    ----------
    wav_bytes : bytes
        The complete WAV file (RIFF header + PCM).
    sample_rate : int
        Sample rate in Hz.
    duration_s : float
        Length of the audio.
    compute_s : float
        Wall-clock seconds spent synthesising.
    cues : list of SpeechCue
        Where each segment is spoken. Free to produce — the offsets were
        already computed to lay the audio out — and the only thing that lets a
        page follow a narration instead of merely playing it.
    voice_id : str
        The voice that read it.
    language : str
        The language it was phonemised in. Getting this wrong is not an
        accent: French read as ``en-us`` is an American reading French
        spelling aloud, letter patterns and all.
    detected_language : str
        What the text turned out to be written in, when nobody named a voice.
        Empty when the caller chose one — this is the detector's answer, not a
        restatement of the request.
    language_fallback : bool
        ``True`` when the text is in a language the backend has no voice for,
        so it is being read by a voice that does not speak it. Said out loud,
        because the audio alone will not make it obvious to whoever generated
        it and does not speak the language either.
    ignored_hints : list of str
        Dials the segments asked for and this backend does not have. Empty on
        a plain narration; non-empty means the caller should know which engine
        does have them.
    """

    wav_bytes: bytes
    sample_rate: int
    duration_s: float
    compute_s: float
    cues: list[SpeechCue] = field(default_factory=list)
    voice_id: str = ""
    language: str = ""
    detected_language: str = ""
    language_fallback: bool = False
    ignored_hints: list[str] = field(default_factory=list)

    @property
    def rtf(self) -> float:
        """Real-time factor ``compute_s / duration_s`` (``inf`` if silent)."""
        return self.compute_s / self.duration_s if self.duration_s > 0 else float("inf")

    def to_vtt(self) -> str:
        """The timed track, as WebVTT."""
        return cues_to_vtt(self.cues)


def format_timestamp(seconds: float) -> str:
    """Format seconds as WebVTT's ``HH:MM:SS.mmm``.

    Negative input clamps to zero: a negative timestamp is never meaningful
    and a renderer's behaviour on one is undefined rather than obvious.
    """
    # Truncated, not rounded, and the suite does it this way everywhere.
    # Rounding up lets a cue claim to start before the sample that actually
    # starts it — half a millisecond early is still early, and the highlight
    # then lands on a word the voice has not reached.
    total_ms = max(0, int(seconds * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def cues_to_vtt(cues: list[SpeechCue]) -> str:
    """Render narration cues as WebVTT.

    Each cue carries its segment index as the WebVTT *identifier* — the line
    before the timings — which is what lets a page highlight the right block
    without matching on text. The text is collapsed onto one line because a
    blank line ends a cue, so a hard-wrapped payload would silently become two
    cues and shift every index after it.
    """
    out = ["WEBVTT", ""]
    for cue in cues:
        out.append(str(cue.index))
        out.append(f"{format_timestamp(cue.start_seconds)} --> {format_timestamp(cue.end_seconds)}")
        out.append(" ".join(cue.text.split()))
        out.append("")
    return "\n".join(out)


def check_timeline_matches_audio(timeline: Timeline, duration_s: float) -> None:
    """Refuse a narration whose cues do not describe the file that was written.

    The timeline counted exactly what the backend said it appended, so a
    disagreement means a piece reached the audio without being recorded. The
    symptom of letting that through is not a crash: it is a narration that
    plays correctly and highlights further and further behind itself, which
    looks like a bug in whatever renders it.

    Raises
    ------
    ValueError
        When the two disagree by more than a sample's worth of rounding.
    """
    if abs(timeline.total_seconds - duration_s) > 1e-6:
        raise ValueError(
            f"timeline says {timeline.total_seconds:.6f}s but the audio is "
            f"{duration_s:.6f}s — a piece was appended without being recorded"
        )


def resolve_spoken_math(
    segments: list[Segment],
    lang: str,
    *,
    narrator: Any = None,
) -> list[Segment]:
    """Fill each segment's ``say`` with a readable form of its notation.

    A convenience over :func:`speaker_helper.speech_text.speakable`, which is
    where the work actually happens. Separate from :class:`Segment` on
    purpose: a segment whose ``say`` was set deliberately — a pronunciation
    override, a formula a human already phrased — must not be overwritten, so
    this only fills the empty ones.

    Parameters
    ----------
    segments : list of Segment
        Left untouched; a new list is returned.
    lang : str
        The language the page is written in. Not optional and not defaulted:
        a French page read with English operator names is worse than one that
        says nothing, because the listener hears fluent words in the wrong
        language and assumes they misheard.
    narrator : callable or None
        ``(latex, lang) -> str | None``, asked about formulas too complex to
        spell out. Optional — without one every formula gets the
        deterministic reading, which is the baseline, not a degraded mode.

    Returns
    -------
    list of Segment
        The same blocks, with ``say`` filled where it was empty and the
        notation differs from the words.
    """
    from speaker_helper.speech_text import speakable

    out: list[Segment] = []
    for seg in segments:
        if seg.say or not seg.text.strip():
            out.append(seg)
            continue
        spoken = speakable(seg.text, lang, narrator=narrator)
        # Only set `say` when it buys something. An identical string would
        # make every segment look like it carries an override, and the first
        # question anyone asks of a narration plan is which blocks do.
        out.append(seg if spoken == seg.text else replace(seg, say=spoken))
    return out


def coerce_segments(raw: list[Any]) -> list[Segment]:
    """Accept segments as dicts, as :class:`Segment`, or as bare strings.

    Three shapes because three callers: a document tool writes JSON, a Python
    caller builds dataclasses, and somebody at a REPL has a list of sentences
    and no interest in any of this.
    """
    out: list[Segment] = []
    for item in raw:
        if isinstance(item, Segment):
            out.append(item)
        elif isinstance(item, dict):
            out.append(Segment.from_mapping(item))
        else:
            out.append(Segment(text=str(item)))
    return out
