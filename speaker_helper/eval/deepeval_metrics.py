"""
DeepEval metrics wrapping speaker-helper's speed and integrity measurements.

Module summary
--------------
The evaluation contract asks for a *dedicated* evaluation framework, not just
hand-rolled asserts. speaker-helper's native metrics (RTF, audio anomalies) are
audio-specific, so instead of forcing a text-only framework to measure audio we
**adapt** those measurements as `DeepEval <https://github.com/confident-ai/deepeval>`_
custom metrics. That plugs speaker-helper into DeepEval's test-case model,
reporting, and thresholds while keeping the actual measurement in this project.

Both metrics are deterministic and offline — they read values a caller stores in
``test_case.additional_metadata`` (``rtf`` and ``anomalies``), so no LLM, API
key, or network is involved.

``deepeval`` is imported at module import time, so this module is optional: it is
only imported by callers that installed the ``eval`` extra.

Usage example
-------------
>>> # from deepeval.test_case import LLMTestCase
>>> # tc = LLMTestCase(input="Bonjour.", actual_output="<audio>",
>>> #                   additional_metadata={"rtf": 0.3, "anomalies": []})
>>> # RealTimeFactorMetric(threshold=1.0).measure(tc)  # -> 1.0 (passes)

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

from typing import Any

from deepeval.metrics import BaseMetric


def _metadata(test_case: Any) -> dict:
    """Return a test case's metadata across DeepEval versions (metadata first)."""
    # DeepEval renamed the attribute across releases: newer builds expose
    # ``metadata``, older ones ``additional_metadata``. Try both, then fall
    # back to an empty dict so a missing attribute is not an error.
    return (
        getattr(test_case, "metadata", None)
        or getattr(test_case, "additional_metadata", None)
        or {}
    )


class RealTimeFactorMetric(BaseMetric):
    """DeepEval metric: passes when synthesis is faster than real time.

    Parameters
    ----------
    threshold : float
        Maximum acceptable real-time factor (``compute_s / duration_s``).
        Defaults to ``1.0`` — the operating point (faster than real time).

    Notes
    -----
    Reads ``test_case.additional_metadata['rtf']``; a missing value scores 0.
    """

    def __init__(self, threshold: float = 1.0) -> None:
        """Store the RTF bar and initialise DeepEval's result fields."""
        # ``threshold`` is the pass bar; the remaining fields are the standard
        # DeepEval result slots, populated on the first ``measure`` call.
        self.threshold = threshold
        self.score: float = 0.0
        self.success: bool = False
        self.reason: str = ""

    def measure(self, test_case: Any) -> float:
        """Score 1.0 if the case's RTF is below the threshold, else 0.0."""
        # RTF is carried in the test case's metadata; a missing value defaults to
        # inf so an unmeasured case fails rather than silently passing.
        rtf = float(_metadata(test_case).get("rtf", float("inf")))
        # Binary pass/fail against the bar, mirrored into DeepEval's fields.
        self.score = 1.0 if rtf < self.threshold else 0.0
        self.success = self.score >= 1.0
        # Human-readable reason DeepEval prints in its report.
        rel = "<" if self.success else ">="
        self.reason = f"RTF {rtf:.3f} {rel} threshold {self.threshold}"
        return self.score

    async def a_measure(self, test_case: Any) -> float:
        """Async wrapper around :meth:`measure` (the work is synchronous)."""
        return self.measure(test_case)

    def is_successful(self) -> bool:
        """Return whether the last :meth:`measure` passed the threshold."""
        return self.success

    @property
    def __name__(self) -> str:  # noqa: A003 - DeepEval reads this for reporting
        """Human-readable metric name DeepEval shows in its report."""
        return "Real-Time Factor"


class AudioIntegrityMetric(BaseMetric):
    """DeepEval metric: passes when the synthesised audio has no anomaly.

    Notes
    -----
    Reads ``test_case.additional_metadata['anomalies']`` (a list of labels from
    :func:`~speaker_helper.eval.metrics.detect_anomalies`); an empty list passes.
    """

    def __init__(self) -> None:
        """Initialise DeepEval's result fields (integrity is all-or-nothing)."""
        # No tunable bar: a clean case scores 1.0 and a flagged one 0.0, so the
        # threshold is fixed at 1.0. The rest are DeepEval's result slots.
        self.threshold = 1.0
        self.score: float = 0.0
        self.success: bool = False
        self.reason: str = ""

    def measure(self, test_case: Any) -> float:
        """Score 1.0 when there are no audio anomalies, else 0.0."""
        # Anomaly labels are carried in the test case metadata; absent means clean.
        anomalies = list(_metadata(test_case).get("anomalies", []))
        # Any anomaly at all fails the case; mirror the verdict into DeepEval.
        self.score = 1.0 if not anomalies else 0.0
        self.success = self.score >= 1.0
        # Report either a clean bill or the comma-joined list of offending labels.
        self.reason = "clean audio" if self.success else f"anomalies: {', '.join(anomalies)}"
        return self.score

    async def a_measure(self, test_case: Any) -> float:
        """Async wrapper around :meth:`measure` (the work is synchronous)."""
        return self.measure(test_case)

    def is_successful(self) -> bool:
        """Return whether the last :meth:`measure` found clean audio."""
        return self.success

    @property
    def __name__(self) -> str:  # noqa: A003 - DeepEval reads this for reporting
        """Human-readable metric name DeepEval shows in its report."""
        return "Audio Integrity"


class RoundTripIdempotenceMetric(BaseMetric):
    """DeepEval metric: text → speech → text should recover the text.

    This formalises the **idempotence** view of synthesis quality: if you
    synthesise a sentence and transcribe the audio back (with ``vocal-helper``,
    the STT sibling), an intelligible voice yields a transcript close to the
    original. We score that closeness with **chrF** (character n-gram F-score,
    robust to the ASR's tokenisation) and pass when it clears a bar.

    What this does and does *not* measure
    -------------------------------------
    It measures **intelligibility** — a necessary lower bound on quality — not
    **naturalness** (a clear-but-robotic voice can still score high). It also
    couples TTS quality with the ASR's quality, so absolute chrF is best read as
    a *relative* ranking across engines scored by the *same* ASR (the ASR's
    error is largely common-mode and cancels when comparing engines). For a
    naturalness axis, pair this with a MOS predictor (e.g. UTMOSv2) measured in
    the ``speak`` study.

    Parameters
    ----------
    threshold : float
        Minimum acceptable round-trip chrF in ``[0, 1]``. Defaults to ``0.75``,
        matching the bundled fidelity bar (``thresholds.yaml``: ``min_mean_chrf``).

    Notes
    -----
    Reads ``test_case.metadata['chrf']`` (the round-trip chrF a caller stored
    from :func:`~speaker_helper.eval.metrics.chrf`); a missing value scores 0.
    """

    def __init__(self, threshold: float = 0.75) -> None:
        """Store the chrF bar and initialise DeepEval's result fields."""
        # ``threshold`` is the minimum chrF to pass; the rest are DeepEval's
        # standard result slots, filled on the first ``measure`` call.
        self.threshold = threshold
        self.score: float = 0.0
        self.success: bool = False
        self.reason: str = ""

    def measure(self, test_case: Any) -> float:
        """Score the round-trip chrF (0 when unmeasured) and gate on the bar."""
        # chrF is carried in the case metadata; a missing round-trip scores 0 so
        # an unmeasured case fails rather than passing on an assumption.
        score = float(_metadata(test_case).get("chrf", 0.0))
        # DeepEval convention: score IS the chrF; success is score >= threshold.
        self.score = score
        self.success = score >= self.threshold
        rel = ">=" if self.success else "<"
        self.reason = f"round-trip chrF {score:.3f} {rel} threshold {self.threshold}"
        return self.score

    async def a_measure(self, test_case: Any) -> float:
        """Async wrapper around :meth:`measure` (the work is synchronous)."""
        return self.measure(test_case)

    def is_successful(self) -> bool:
        """Return whether the last :meth:`measure` cleared the chrF bar."""
        return self.success

    @property
    def __name__(self) -> str:  # noqa: A003 - DeepEval reads this for reporting
        """Human-readable metric name DeepEval shows in its report."""
        return "Round-Trip Idempotence (chrF)"
