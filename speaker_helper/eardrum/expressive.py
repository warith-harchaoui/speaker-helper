"""
The prosody side of the Ralph Eardrum Loop: does the voice say it the way the
text means it?

Module summary
--------------
Two readers of the same sentence, kept independent on purpose:

* **the text side** says what the sentence calls for — the final contour its
  form implies (:mod:`.intonation`), and the **arousal** it expresses (calm,
  neutral, activated): from the narration's own ``emotion`` tag when the
  document gives one, otherwise from the local LLM reading the sentence;
* **the audio side** says what the voice did, from the signal alone, never a
  transcript (:mod:`.prosody`): the measured final contour, and the arousal
  shift against a *neutral take of the same sentence by the same voice*.

Arousal and contour are the two things the voice carries reliably. Valence
(positive or negative) travels mostly through the words — Juslin & Laukka
2003; Wagner et al. 2023 found audio-only recognisers take it from implicit
linguistic content — so it is reported from the text side and never judged
from the audio.

The comparison is relative: a take is judged against a neutral take of the
same sentence, because absolute emotion labels from recognisers trained on
acted human speech collapse on synthetic speech (arXiv 2603.16483, 2026).

:func:`check_expression` measures; :func:`tune_expression` also tries the
engine's levers in order until the take agrees, keeping the best.

Usage example
-------------
>>> expected_arousal_from_tag("angry"), expected_arousal_from_tag("sad")
('high', 'low')

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import os_helper as osh

from speaker_helper.eardrum.intonation import ExpectedContour, contour_agrees, expected_contour
from speaker_helper.eardrum.prosody import ProsodyFeatures, arousal_shift

#: The narration's emotion tags (the chatterbox vocabulary) → the arousal
#: each one means. Valence is deliberately absent: the voice does not carry it
#: reliably, so the loop does not pretend to check it.
TAG_AROUSAL: dict[str, str] = {
    "angry": "high",
    "enthusiastic": "high",
    "terrified": "high",
    "cheerful": "high",
    "neutral": "neutral",
    "warm": "neutral",
    "friendly": "neutral",
    "cautious": "neutral",
    "sad": "low",
    "calm": "low",
    "contemplative": "low",
    "whispering": "low",
}

#: Arousal shift (in roughly semitone-sized units, see
#: :func:`~.prosody.arousal_shift`) a take must reach against its neutral
#: reading to count as activated (``high``) or calmed (``low``). Set above the
#: take-to-take noise measured on repeated neutral takes.
AROUSAL_STEP = 1.0


def expected_arousal_from_tag(emotion: str) -> str | None:
    """The arousal an emotion tag means, or ``None`` for an unknown tag.

    Parameters
    ----------
    emotion : str
        A narration ``emotion`` value.

    Returns
    -------
    str or None
        ``"low"``, ``"neutral"`` or ``"high"``.
    """
    return TAG_AROUSAL.get((emotion or "").strip().lower())


@dataclass
class TextExpression:
    """What a sentence expresses, read from its words.

    Attributes
    ----------
    arousal : str
        ``"low"``, ``"neutral"`` or ``"high"``.
    valence : str
        ``"negative"``, ``"neutral"`` or ``"positive"`` — reported, never
        judged against the audio.
    emotion : str
        The closest tag of :data:`TAG_AROUSAL`, so the engine's emotion dial
        can be set from it.
    source : str
        ``"tag"`` (the document said so) or ``"llm"``.
    """

    arousal: str
    valence: str = "neutral"
    emotion: str = "neutral"
    source: str = "tag"


def infer_expression(sentence: str, language: str) -> TextExpression | None:
    """Ask the local LLM what emotion the words of ``sentence`` express.

    The model reads the text only. It answers in JSON with arousal, valence
    and the closest emotion tag; anything else is refused.

    Parameters
    ----------
    sentence : str
        The sentence.
    language : str
        Its language (for the prompt).

    Returns
    -------
    TextExpression or None
        ``None`` when the LLM stack is unavailable or the answer is malformed.
    """
    try:
        import best_engine_ai_helper as be
        import ollama
    except ImportError:
        return None
    try:
        model = be.text_model()
    except Exception as exc:  # noqa: BLE001 - no env file / no detection yet
        osh.warning("eardrum: best-engine-ai-helper could not resolve a model (%s)", exc)
        return None
    tags = ", ".join(sorted(TAG_AROUSAL))
    prompt = (
        "Read this sentence as a voice actor would, from its words alone. "
        f"Sentence ({language}): {sentence!r}\n"
        "Answer with JSON only, no prose: "
        '{"arousal": "low|neutral|high", "valence": "negative|neutral|positive", '
        f'"emotion": "one of: {tags}"}}\n'
        "arousal is the energy the delivery needs (calm, ordinary, activated). "
        "Most sentences of an ordinary text are neutral; do not over-read."
    )
    try:
        reply = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0, "num_predict": 80},
            format="json",
            think=False,
        )
        return parse_expression(str(reply["message"]["content"]))
    except Exception as exc:  # noqa: BLE001 - daemon down, model missing, old client
        osh.warning("eardrum: the local LLM did not read the sentence (%s)", exc)
        return None


def parse_expression(answer: str) -> TextExpression | None:
    """Validate the LLM's JSON answer.

    Parameters
    ----------
    answer : str
        Raw model output.

    Returns
    -------
    TextExpression or None
        ``None`` unless every field is one of the allowed values.

    Examples
    --------
    >>> parse_expression('{"arousal": "high", "valence": "negative", "emotion": "angry"}')
    TextExpression(arousal='high', valence='negative', emotion='angry', source='llm')
    >>> parse_expression('Sure! {"arousal": "very"}') is None
    True
    """
    match = re.search(r"\{.*\}", answer, re.DOTALL)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    arousal = str(data.get("arousal", "")).lower()
    valence = str(data.get("valence", "")).lower()
    emotion = str(data.get("emotion", "")).lower()
    if arousal not in ("low", "neutral", "high"):
        return None
    if valence not in ("negative", "neutral", "positive"):
        valence = "neutral"
    if emotion not in TAG_AROUSAL:
        emotion = "neutral"
    return TextExpression(arousal=arousal, valence=valence, emotion=emotion, source="llm")


def arousal_agrees(expected: str, shift: float, step: float = AROUSAL_STEP) -> bool:
    """Whether a measured arousal shift matches what the text calls for.

    Parameters
    ----------
    expected : str
        ``"low"``, ``"neutral"`` or ``"high"``.
    shift : float
        :func:`~.prosody.arousal_shift` against the neutral take.
    step : float
        How far a take must move to count as activated or calmed.

    Returns
    -------
    bool
        ``high`` needs ``shift ≥ step``, ``low`` needs ``shift ≤ -step``,
        ``neutral`` needs ``|shift| < step``.

    Examples
    --------
    >>> arousal_agrees("high", 1.4), arousal_agrees("neutral", 1.4)
    (True, False)
    """
    if expected == "high":
        return shift >= step
    if expected == "low":
        return shift <= -step
    return abs(shift) < step


@dataclass
class ExpressionTake:
    """One reading of a sentence with given dials, and what was measured.

    Attributes
    ----------
    lever : str
        What was changed for this take (``"as written"``, ``"intensity 0.9"``…).
    say : str
        The text the engine was handed.
    emotion, intensity, pace : str
        The dials.
    contour : str or None
        Measured final contour shape.
    contour_ok : bool or None
        Agreement with the expected contour (``None``: not measurable).
    arousal_shift : float
        Against the neutral take.
    arousal_ok : bool
        Agreement with the expected arousal.
    audio : str
        Path of the take, relative to the report directory.
    """

    lever: str
    say: str
    emotion: str
    intensity: str
    pace: str
    contour: str | None
    contour_ok: bool | None
    arousal_shift: float
    arousal_ok: bool
    audio: str = ""

    @property
    def agrees(self) -> bool:
        """Contour and arousal both agree (an unmeasurable contour does not block)."""
        return self.arousal_ok and self.contour_ok is not False


@dataclass
class ExpressionResult:
    """Everything the prosody loop did for one sentence.

    Attributes
    ----------
    text : str
        The sentence as the page shows it.
    language : str
        Its language.
    expected_contour : dict
        :class:`~.intonation.ExpectedContour`, as a dict.
    expected : dict or None
        :class:`TextExpression`, as a dict (``None``: no tag and no LLM).
    neutral : dict
        The neutral take's :class:`~.prosody.ProsodyFeatures`.
    takes : list of ExpressionTake
        In the order tried.
    best : int
        Index of the best take.
    verdict : str
        ``ok`` (the first take agrees), ``fixed`` (a lever made it agree),
        ``unresolved``, or ``unjudged`` (nothing to compare against).
    """

    text: str
    language: str
    expected_contour: dict[str, Any]
    expected: dict[str, Any] | None
    neutral: dict[str, Any] = field(default_factory=dict)
    takes: list[ExpressionTake] = field(default_factory=list)
    best: int = -1
    verdict: str = "unjudged"


#: A lever: given the segment's dials, the dials of the next try (or ``None``
#: when this lever does not apply). Tried in order until one agrees.
Lever = Callable[[dict[str, str], ExpectedContour, str], "dict[str, str] | None"]


def _score(take: ExpressionTake, expected_arousal: str) -> float:
    """How far a take is from agreeing (0 agrees), to rank takes.

    Parameters
    ----------
    take : ExpressionTake
        The take.
    expected_arousal : str
        What the text calls for.

    Returns
    -------
    float
        Contour miss counts 1; the arousal miss counts its distance to the
        accepted band, in steps.
    """
    miss = 1.0 if take.contour_ok is False else 0.0
    shift = take.arousal_shift
    if expected_arousal == "high":
        miss += max(0.0, AROUSAL_STEP - shift) / AROUSAL_STEP
    elif expected_arousal == "low":
        miss += max(0.0, shift + AROUSAL_STEP) / AROUSAL_STEP
    else:
        miss += max(0.0, abs(shift) - AROUSAL_STEP) / AROUSAL_STEP
    return round(miss, 4)


async def check_expression(
    say: Callable[[dict[str, str]], Any],
    measure: Callable[[bytes], ProsodyFeatures],
    segment: dict[str, str],
    language: str,
    *,
    infer: Callable[[str, str], TextExpression | None] | None = infer_expression,
    levers: list[Lever] | None = None,
    save: Callable[[str, bytes], str] | None = None,
) -> ExpressionResult:
    """Judge (and, with ``levers``, tune) how one sentence is said.

    Parameters
    ----------
    say : callable
        ``async (dials) -> wav_bytes``: synthesise the sentence with these
        dials (``say``, ``emotion``, ``intensity``) through the real engine.
    measure : callable
        ``wav_bytes -> ProsodyFeatures`` (:func:`~.prosody.measure`).
    segment : dict
        ``text`` and optionally ``say``, ``emotion``, ``intensity``.
    language : str
        Its language.
    infer : callable or None
        Reads the expression from the words when the segment has no emotion
        tag (:func:`infer_expression`); ``None`` judges the contour only.
    levers : list of Lever or None
        Changes to try, in order, while the take disagrees. ``None`` only
        measures.
    save : callable or None
        ``(name, wav_bytes) -> relative path`` to keep each take.

    Returns
    -------
    ExpressionResult
        Expectations, the neutral reference, every take and the verdict.
    """
    text = segment["text"]
    spoken = segment.get("say") or text
    expected_shape = expected_contour(spoken, language)
    tag = segment.get("emotion", "")
    arousal = expected_arousal_from_tag(tag) if tag else None
    expression: TextExpression | None
    if arousal is not None:
        expression = TextExpression(arousal=arousal, emotion=tag, source="tag")
    else:
        expression = infer(spoken, language) if infer else None
    expected_arousal = expression.arousal if expression else "neutral"
    result = ExpressionResult(
        text=text,
        language=language,
        expected_contour=asdict(expected_shape),
        expected=asdict(expression) if expression else None,
    )
    # The neutral reference: the same words, the same voice, no emotion.
    neutral_dials = {
        "say": spoken,
        "emotion": "neutral",
        "intensity": "",
        "pace": segment.get("pace", "") or "normal",
    }
    neutral_wav = await say(neutral_dials)
    neutral = measure(neutral_wav)
    result.neutral = asdict(neutral)
    if save:
        save("neutral", neutral_wav)

    first = {
        "say": spoken,
        # No emotion is the neutral one: the first take then IS the neutral
        # reference, and is not synthesised twice.
        "emotion": (expression.emotion if expression else "")
        or segment.get("emotion", "")
        or "neutral",
        "intensity": segment.get("intensity", ""),
        "pace": segment.get("pace", "") or "normal",
    }

    async def take(name: str, dials: dict[str, str], number: int) -> ExpressionTake:
        """Say the sentence with ``dials``, measure it, judge it."""
        if dials == neutral_dials:
            wav, features = neutral_wav, neutral
        else:
            wav = await say(dials)
            features = measure(wav)
        contour = features.final.shape if features.final else None
        shift = arousal_shift(features, neutral)
        judged = ExpressionTake(
            lever=name,
            say=dials["say"],
            emotion=dials.get("emotion", ""),
            intensity=dials.get("intensity", ""),
            pace=dials.get("pace", "normal"),
            contour=contour,
            contour_ok=contour_agrees(expected_shape, contour),
            arousal_shift=shift,
            arousal_ok=arousal_agrees(expected_arousal, shift),
        )
        if save:
            judged.audio = save(f"take{number}", wav)
        return judged

    result.takes.append(await take("as asked", first, 0))
    current = first
    for lever in levers or []:
        if result.takes[-1].agrees:
            break
        proposal = lever(current, expected_shape, expected_arousal)
        if proposal is None:
            continue
        result.takes.append(await take(lever.__name__, proposal, len(result.takes)))
        current = proposal
    scores = [_score(t, expected_arousal) for t in result.takes]
    result.best = min(range(len(scores)), key=scores.__getitem__)
    if result.takes[0].agrees:
        result.verdict, result.best = "ok", 0
    elif result.takes[result.best].agrees:
        result.verdict = "fixed"
    else:
        result.verdict = "unresolved"
    return result


# ---------------------------------------------------------------------------
# Levers: what the loop may change, in order
# ---------------------------------------------------------------------------

#: Emotion tags to fall back on when the requested one cannot move the
#: arousal far enough: the strongest of each band.
_STRONGEST = {"high": "enthusiastic", "low": "calm"}


def stronger_emotion(
    dials: dict[str, str], contour: ExpectedContour, arousal: str
) -> dict[str, str] | None:
    """Push the emotion dial to the end of its range, towards the expected arousal.

    Parameters
    ----------
    dials : dict
        The current take's dials.
    contour : ExpectedContour
        The expected contour (unused: this lever acts on arousal).
    arousal : str
        The expected arousal.

    Returns
    -------
    dict or None
        New dials, or ``None`` when arousal is neutral or the dial is already
        at its end.
    """
    if arousal not in _STRONGEST:
        return None
    emotion = dials.get("emotion", "")
    if expected_arousal_from_tag(emotion) != arousal:
        emotion = _STRONGEST[arousal]
    if emotion == dials.get("emotion") and dials.get("intensity") == "1.0":
        return None
    return {**dials, "emotion": emotion, "intensity": "1.0"}


def closer_to_the_text(
    dials: dict[str, str], contour: ExpectedContour, arousal: str
) -> dict[str, str] | None:
    """Read slower, which on chatterbox raises text guidance (``cfg_weight``).

    Classifier-free guidance weighs the text against the voice prompt; more of
    it makes the reading follow the text — punctuation included — more
    closely. Applied only when the contour is wrong.

    Parameters
    ----------
    dials : dict
        The current take's dials.
    contour : ExpectedContour
        The expected contour.
    arousal : str
        The expected arousal (unused).

    Returns
    -------
    dict or None
        New dials with ``pace`` slow, or ``None`` when already slow or when
        the text accepts any contour.
    """
    if contour.shape == "either" or dials.get("pace") == "slow":
        return None
    return {**dials, "pace": "slow"}


def marked_question(
    dials: dict[str, str], contour: ExpectedContour, arousal: str
) -> dict[str, str] | None:
    """Mark a rising question harder in what is said (never in what is shown).

    Only for a sentence whose form calls for a rise: the final ``?`` is
    doubled into ``?!``, the spelling engines trained on web text associate
    with a strong rise. The page keeps its own punctuation — this changes the
    segment's ``say``, not its ``text``.

    Parameters
    ----------
    dials : dict
        The current take's dials.
    contour : ExpectedContour
        The expected contour.
    arousal : str
        The expected arousal (unused).

    Returns
    -------
    dict or None
        New dials, or ``None`` when no rise is expected or already marked.
    """
    said = dials.get("say", "").rstrip()
    if contour.shape != "rise" or not said.endswith("?") or said.endswith("?!"):
        return None
    return {**dials, "say": said + "!"}


#: The order the loop tries them in. Arousal first (the dial made for it),
#: then the two contour levers, gentlest first.
DEFAULT_LEVERS: list[Lever] = [stronger_emotion, closer_to_the_text, marked_question]


# ---------------------------------------------------------------------------
# A whole document
# ---------------------------------------------------------------------------


@dataclass
class ProsodyReport:
    """What a prosody run produced.

    Attributes
    ----------
    results : list of ExpressionResult
        One per segment.
    html : Path or None
        The report to listen to.
    tuned : Path or None
        The segments with the winning dials, ready for ``narrate``.
    meta : dict
        Engine, language, date, whether it tuned.
    """

    results: list[ExpressionResult] = field(default_factory=list)
    html: Any = None
    tuned: Any = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def agreement(self) -> dict[str, float | None]:
        """Share of segments whose *first* take agreed, per dimension.

        This is the answer to "does the voice say it the way the text means
        it?" before any tuning: contour over the segments where it could be
        measured and is not ``either``, arousal over all.
        """
        judged = [r for r in self.results if r.takes]
        contour = [
            r.takes[0].contour_ok
            for r in judged
            if r.takes[0].contour_ok is not None and r.expected_contour["shape"] != "either"
        ]
        arousal = [r.takes[0].arousal_ok for r in judged]
        return {
            "contour": round(sum(contour) / len(contour), 3) if contour else None,
            "arousal": round(sum(arousal) / len(arousal), 3) if arousal else None,
        }


def segments_from_text(text: str) -> list[dict[str, str]]:
    """Cut a plain text into one segment per sentence.

    Parameters
    ----------
    text : str
        The document.

    Returns
    -------
    list of dict
        ``{"text": sentence}`` each.

    Examples
    --------
    >>> segments_from_text("Tu viens ? Oui. Super !")
    [{'text': 'Tu viens ?'}, {'text': 'Oui.'}, {'text': 'Super !'}]
    """
    parts = re.split(r"(?<=[.!?…])\s+|\n+", text)
    return [{"text": " ".join(p.split())} for p in parts if p.strip()]


async def run_prosody_async(
    settings: Any,
    segments: list[dict[str, str]],
    *,
    tune: bool = True,
    infer: bool = True,
    out_dir: Any = None,
    speaker: Any = None,
    measure: Callable[[bytes], ProsodyFeatures] | None = None,
    levers: list[Lever] | None = None,
) -> ProsodyReport:
    """Check (and tune) how every segment of a document is said.

    Parameters
    ----------
    settings : Settings
        Engine and language.
    segments : list of dict
        ``text`` and optionally ``say``, ``emotion``, ``intensity``, ``pace``
        (the narration format), or build them with :func:`segments_from_text`.
    tune : bool
        Try the levers on segments that disagree; ``False`` only measures
        the agreement between text and voice.
    infer : bool
        Let the local LLM read the expression of untagged segments.
    out_dir : Path or None
        Report directory (a dated folder under ``.private/eardrum-loop/``).
    speaker, measure, levers : optional
        Injected collaborators (tests).

    Returns
    -------
    ProsodyReport
        Results, agreement rates, report and tuned segments paths.
    """
    import datetime as _dt
    from pathlib import Path

    from speaker_helper.engine import resolve_auto
    from speaker_helper.narration import Segment
    from speaker_helper.speaker import Speaker

    settings = resolve_auto(settings)
    language = (settings.language or "fr").split("-")[0].lower()
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(out_dir) if out_dir else Path(".private") / "eardrum-loop" / f"prosody-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    if measure is None:
        from speaker_helper.eardrum.prosody import measure as measure_take

        measure = measure_take
    own = speaker is None
    spk = speaker or Speaker(settings)
    results: list[ExpressionResult] = []
    try:
        for index, segment in enumerate(segments):

            async def say(dials: dict[str, str], segment: dict[str, str] = segment) -> bytes:
                """Narrate the segment with ``dials``: the same path a reading takes."""
                block = Segment(
                    text=segment["text"],
                    say=dials["say"],
                    emotion=dials.get("emotion", ""),
                    intensity=dials.get("intensity", ""),
                    pace=dials.get("pace", "normal"),
                )
                return (await spk.narrate([block], language=language)).wav_bytes

            def save(name: str, wav: bytes, index: int = index) -> str:
                """Keep the take beside the report."""
                folder = out / "audio" / f"s{index:03d}"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{name}.wav").write_bytes(wav)
                return f"audio/s{index:03d}/{name}.wav"

            results.append(
                await check_expression(
                    say,
                    measure,
                    segment,
                    language,
                    infer=infer_expression if infer else None,
                    levers=(levers if levers is not None else DEFAULT_LEVERS) if tune else None,
                    save=save,
                )
            )
            osh.info("eardrum prosody: %s — %s", segment["text"][:60], results[-1].verdict)
    finally:
        if own:
            await spk.aclose()
    report = ProsodyReport(
        results=results,
        meta={
            "engine": settings.backend,
            "language": language,
            "tuned": tune,
            "date": _dt.datetime.now().isoformat(timespec="seconds"),
        },
    )
    report.meta["agreement"] = report.agreement
    tuned = []
    for segment, result in zip(segments, results, strict=True):
        best = result.takes[result.best] if result.takes else None
        row = dict(segment)
        if best is not None and result.verdict == "fixed":
            if best.say != (segment.get("say") or segment["text"]):
                row["say"] = best.say
            row.update(emotion=best.emotion, intensity=best.intensity, pace=best.pace)
        tuned.append(row)
    report.tuned = out / "segments.tuned.json"
    report.tuned.write_text(json.dumps(tuned, ensure_ascii=False, indent=2), encoding="utf-8")
    from speaker_helper.eardrum.report import write_prosody_report

    report.html = write_prosody_report(out, results, report.meta)
    return report


def run_prosody(settings: Any, segments: list[dict[str, str]], **kwargs: Any) -> ProsodyReport:
    """Synchronous wrapper around :func:`run_prosody_async`.

    Parameters
    ----------
    settings : Settings
        Engine and language.
    segments : list of dict
        The narration segments.
    **kwargs
        Forwarded unchanged.

    Returns
    -------
    ProsodyReport
        Results, agreement, report and tuned segments.
    """
    import asyncio

    return asyncio.run(run_prosody_async(settings, segments, **kwargs))
