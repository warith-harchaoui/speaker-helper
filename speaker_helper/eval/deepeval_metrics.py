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
        return "Real-Time Factor"


class AudioIntegrityMetric(BaseMetric):
    """DeepEval metric: passes when the synthesised audio has no anomaly.

    Notes
    -----
    Reads ``test_case.additional_metadata['anomalies']`` (a list of labels from
    :func:`~speaker_helper.eval.metrics.detect_anomalies`); an empty list passes.
    """

    def __init__(self) -> None:
        self.threshold = 1.0
        self.score: float = 0.0
        self.success: bool = False
        self.reason: str = ""

    def measure(self, test_case: Any) -> float:
        """Score 1.0 when there are no audio anomalies, else 0.0."""
        anomalies = list(_metadata(test_case).get("anomalies", []))
        self.score = 1.0 if not anomalies else 0.0
        self.success = self.score >= 1.0
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
        return "Audio Integrity"
