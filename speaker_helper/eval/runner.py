"""
Run an evaluation over a dataset and gate on versioned thresholds.

Module summary
--------------
The runner ties the pieces together: it drives a
:class:`~speaker_helper.speaker.Speaker` (any backend — Voicebox, mock, a future
engine) over a list of :class:`~speaker_helper.eval.dataset.EvalCase`, measures
speed and signal integrity for each, optionally re-transcribes the audio to
score fidelity, aggregates everything into an :class:`EvalReport`, and compares
that report to committed :class:`~speaker_helper.eval.thresholds.Thresholds`.

Because it targets the :class:`Speaker` façade, the evaluation is completely
engine-agnostic: the same run measures the mock backend in CI or the real
Voicebox engine locally, with no code change — only ``settings.backend`` differs.

Fidelity (WER/chrF) is a *round-trip*: it needs a speech-to-text transcriber.
That is injected through the :class:`Transcriber` protocol (e.g. a ``vocal-helper``
adapter), so speaker-helper takes no hard STT dependency. Without one, speed and
anomaly gates still run.

Usage example
-------------
>>> import asyncio
>>> from speaker_helper import Speaker, Settings
>>> from speaker_helper.eval import load_dataset, run_eval
>>> async def demo() -> bool:
...     async with Speaker(Settings.from_mapping({"backend": "mock"})) as spk:
...         report = await run_eval(spk, load_dataset())
...         return report.passed
>>> asyncio.run(demo())
True

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol, runtime_checkable

import os_helper as osh

from speaker_helper.eval.dataset import EvalCase, load_dataset
from speaker_helper.eval.metrics import (
    chrf,
    detect_anomalies,
    mean,
    percentile,
    word_error_rate,
)
from speaker_helper.eval.priors import engine_quality_prior
from speaker_helper.eval.thresholds import Thresholds
from speaker_helper.speaker import Speaker


@runtime_checkable
class Transcriber(Protocol):
    """Optional speech-to-text used for the fidelity round-trip.

    Any object with this coroutine can be injected (e.g. a ``vocal-helper``
    adapter) to enable WER/chrF scoring. speaker-helper never imports one.
    """

    async def transcribe(self, wav_bytes: bytes, *, language: str) -> str:
        """Return the transcript of a WAV payload in ``language``."""
        ...


@dataclass
class CaseResult:
    """Per-utterance evaluation outcome.

    Parameters
    ----------
    id : str
        The originating :class:`EvalCase` id.
    language : str
        Language synthesised.
    duration_s : float
        Audio duration produced.
    rtf : float
        Real-time factor for this case (below 1.0 is faster than real time).
    anomalies : list of str
        Anomaly labels (empty means clean); see
        :func:`~speaker_helper.eval.metrics.detect_anomalies`.
    wer : float or None
        Round-trip word error rate, or ``None`` when no transcriber ran.
    chrf : float or None
        Round-trip chrF, or ``None`` when no transcriber ran.
    error : str or None
        Synthesis error message when the case failed outright (counts as an
        anomaly), else ``None``.
    """

    id: str
    language: str
    duration_s: float
    rtf: float
    anomalies: list[str] = field(default_factory=list)
    wer: float | None = None
    chrf: float | None = None
    error: str | None = None

    @property
    def is_anomalous(self) -> bool:
        """True if the case errored or produced any audio anomaly."""
        return bool(self.error) or bool(self.anomalies)


@dataclass
class EvalReport:
    """Aggregated evaluation results plus the pass/fail verdict.

    Parameters
    ----------
    backend : str
        The backend that was evaluated (echoed for provenance).
    n_cases : int
        Number of cases run.
    mean_rtf, p95_rtf : float
        RTF summary statistics.
    anomaly_rate : float
        Fraction of cases that errored or were anomalous.
    mean_wer, mean_chrf : float or None
        Round-trip fidelity means, or ``None`` when no transcriber ran.
    quality : float
        A quality score in ``[0, 1]`` that is always present: the measured mean
        chrF when a transcriber ran, otherwise the engine's inherited prior
        (see :mod:`speaker_helper.eval.priors`). Paired with ``mean_rtf`` it
        places the run on the quality↔RTF plane for :func:`pareto_front`.
    quality_source : str
        ``"measured_chrf"`` or ``"prior"`` — how ``quality`` was obtained.
    passed : bool
        Whether every gated threshold was met.
    failures : list of str
        Human-readable reasons the run failed (empty when ``passed``).
    cases : list of CaseResult
        Per-utterance detail.
    thresholds : dict
        The thresholds applied (echoed for provenance).
    """

    backend: str
    n_cases: int
    mean_rtf: float
    p95_rtf: float
    anomaly_rate: float
    mean_wer: float | None
    mean_chrf: float | None
    quality: float
    quality_source: str
    passed: bool
    failures: list[str]
    cases: list[CaseResult]
    thresholds: dict

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict of the whole report."""
        # ``asdict`` recurses into the nested CaseResult dataclasses too, giving a
        # fully plain-dict tree ready for JSON serialisation.
        d = asdict(self)
        return d


async def run_eval(
    speaker: Speaker,
    cases: list[EvalCase] | None = None,
    *,
    thresholds: Thresholds | None = None,
    transcriber: Transcriber | None = None,
) -> EvalReport:
    """Evaluate ``speaker`` over ``cases`` and gate on ``thresholds``.

    Parameters
    ----------
    speaker : Speaker
        The façade to drive; its backend is whatever ``settings.backend`` chose.
    cases : list of EvalCase or None
        Cases to run; defaults to the built-in French dataset.
    thresholds : Thresholds or None
        Pass/fail bar; defaults to :meth:`Thresholds.load` (bundled YAML).
    transcriber : Transcriber or None
        Optional STT enabling the WER/chrF round-trip. When ``None``, fidelity
        metrics are skipped (and their thresholds are not gated).

    Returns
    -------
    EvalReport
        The aggregated report and verdict.
    """
    # Fall back to the bundled dataset and threshold bar when the caller omits
    # them, so ``run_eval(speaker)`` is a valid, fully-defaulted invocation.
    cases = cases if cases is not None else load_dataset()
    thresholds = thresholds or Thresholds.load()

    # Run cases sequentially so RTF is measured under a single, uncontended
    # engine rather than distorted by concurrent synthesis load.
    results: list[CaseResult] = []
    for case in cases:
        results.append(await _run_case(speaker, case, transcriber))
        # Log each case's headline numbers as it lands for live progress.
        osh.info(
            "eval %s: rtf=%.3f anomalies=%s", case.id, results[-1].rtf, results[-1].anomalies or "-"
        )

    # Fold the per-case results into a single report and apply the gate. Fidelity
    # thresholds are only enforced when a transcriber actually produced scores.
    return _aggregate(
        speaker.settings.backend,
        speaker.settings.engine,
        results,
        thresholds,
        gated_fidelity=transcriber is not None,
    )


async def _run_case(
    speaker: Speaker,
    case: EvalCase,
    transcriber: Transcriber | None,
) -> CaseResult:
    """Synthesise one case, measure it, and optionally score its round-trip."""
    # A synthesis failure is data, not a crash: record it as an inf-RTF anomaly
    # so one bad case fails the gate without aborting the whole run.
    try:
        audio = await speaker.say(case.text, language=case.language)
    except Exception as exc:  # noqa: BLE001 - a failed synthesis is a data point
        return CaseResult(
            id=case.id,
            language=case.language,
            duration_s=0.0,
            rtf=float("inf"),
            anomalies=["synthesis_error"],
            error=str(exc),
        )

    # Always-available measurements: duration, RTF, and signal anomalies.
    result = CaseResult(
        id=case.id,
        language=case.language,
        duration_s=round(audio.duration_s, 4),
        rtf=round(audio.rtf, 4),
        anomalies=detect_anomalies(audio),
    )
    # Fidelity round-trip only when a transcriber is supplied.
    if transcriber is not None:
        # Best-effort: a transcription hiccup leaves WER/chrF unset (None) rather
        # than failing the whole case.
        try:
            hyp = await transcriber.transcribe(audio.wav_bytes, language=case.language)
            result.wer = round(word_error_rate(case.reference, hyp), 4)
            result.chrf = round(chrf(case.reference, hyp), 4)
        except Exception as exc:  # noqa: BLE001 - transcription is best-effort
            osh.warning("transcription failed for %s: %s", case.id, exc)
    return result


def _aggregate(
    backend: str,
    engine: str,
    results: list[CaseResult],
    thresholds: Thresholds,
    *,
    gated_fidelity: bool,
) -> EvalReport:
    """Fold per-case results into an :class:`EvalReport` and apply the gate."""
    n = len(results)
    # Speed stats ignore inf RTFs (a failed synthesis has no meaningful RTF);
    # the failure still counts as an anomaly below.
    rtfs = [r.rtf for r in results if r.rtf != float("inf")]
    mean_rtf = round(mean(rtfs), 4)
    p95_rtf = round(percentile(rtfs, 95), 4)
    # Fraction of cases that errored or produced any audio anomaly.
    anomaly_rate = round(sum(r.is_anomalous for r in results) / n, 4) if n else 0.0

    # Fidelity means are computed only over cases a transcriber actually scored;
    # None when no transcriber ran (so the gate below stays disabled).
    wers = [r.wer for r in results if r.wer is not None]
    chrfs = [r.chrf for r in results if r.chrf is not None]
    mean_wer = round(mean(wers), 4) if wers else None
    mean_chrf = round(mean(chrfs), 4) if chrfs else None

    # Always report a quality axis: measured chrF when available (from a
    # round-trip), else the engine's quality prior — so speed↔quality Pareto
    # selection works even without a transcriber. The prior keys on the engine
    # model (kokoro, chatterbox, …), not the backend.
    if mean_chrf is not None:
        quality, quality_source = mean_chrf, "measured_chrf"
    else:
        prior_key = "mock" if backend == "mock" else engine
        quality, quality_source = round(engine_quality_prior(prior_key), 4), "prior"

    # Collect a human-readable reason for every breached threshold; a non-empty
    # list means the run failed. Speed and anomaly gates always apply.
    failures: list[str] = []
    if mean_rtf > thresholds.max_mean_rtf:
        failures.append(f"mean RTF {mean_rtf} > {thresholds.max_mean_rtf}")
    if p95_rtf > thresholds.max_p95_rtf:
        failures.append(f"p95 RTF {p95_rtf} > {thresholds.max_p95_rtf}")
    if anomaly_rate > thresholds.max_anomaly_rate:
        failures.append(f"anomaly rate {anomaly_rate} > {thresholds.max_anomaly_rate}")
    # Fidelity gates (WER/chrF) only fire when a transcriber ran AND the bar is
    # configured AND a mean was computed — otherwise fidelity is not gated.
    if (
        gated_fidelity
        and thresholds.max_mean_wer is not None
        and mean_wer is not None
        and mean_wer > thresholds.max_mean_wer
    ):
        failures.append(f"mean WER {mean_wer} > {thresholds.max_mean_wer}")
    if (
        gated_fidelity
        and thresholds.min_mean_chrf is not None
        and mean_chrf is not None
        and mean_chrf < thresholds.min_mean_chrf
    ):
        failures.append(f"mean chrF {mean_chrf} < {thresholds.min_mean_chrf}")

    # Echo the applied thresholds alongside the numbers so a report is a complete,
    # self-describing provenance record. ``passed`` is simply "no failures".
    return EvalReport(
        backend=backend,
        n_cases=n,
        mean_rtf=mean_rtf,
        p95_rtf=p95_rtf,
        anomaly_rate=anomaly_rate,
        mean_wer=mean_wer,
        mean_chrf=mean_chrf,
        quality=quality,
        quality_source=quality_source,
        passed=not failures,
        failures=failures,
        cases=results,
        thresholds={
            "max_mean_rtf": thresholds.max_mean_rtf,
            "max_p95_rtf": thresholds.max_p95_rtf,
            "max_anomaly_rate": thresholds.max_anomaly_rate,
            "max_mean_wer": thresholds.max_mean_wer,
            "min_mean_chrf": thresholds.min_mean_chrf,
        },
    )
