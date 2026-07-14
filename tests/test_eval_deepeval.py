"""
Tests for the DeepEval integration of speaker-helper's metrics.

Skipped unless ``deepeval`` (the ``eval`` extra) is installed. The metrics are
deterministic and offline — no LLM, API key, or network — so they exercise the
framework binding without cost.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("deepeval")
from deepeval.test_case import LLMTestCase  # noqa: E402

from speaker_helper import Settings, Speaker  # noqa: E402
from speaker_helper.eval import load_dataset, run_eval  # noqa: E402
from speaker_helper.eval.deepeval_metrics import (  # noqa: E402
    AudioIntegrityMetric,
    RealTimeFactorMetric,
)


def _case(rtf: float, anomalies: list[str]) -> LLMTestCase:
    """Build an LLMTestCase carrying the given RTF and anomaly metadata."""
    # The metrics read rtf/anomalies straight from the case metadata.
    return LLMTestCase(
        input="Bonjour.",
        actual_output="<audio>",
        metadata={"rtf": rtf, "anomalies": anomalies},
    )


def test_rtf_metric_passes_below_threshold() -> None:
    """The RTF metric passes when RTF is under the threshold."""
    # RTF 0.3 is well under the 1.0 bar -> full score and success.
    metric = RealTimeFactorMetric(threshold=1.0)
    assert metric.measure(_case(0.3, [])) == 1.0
    assert metric.is_successful()


def test_rtf_metric_fails_above_threshold() -> None:
    """The RTF metric fails and reports the offending value when too slow."""
    # RTF 1.5 breaches the 1.0 bar -> failure, with the value in the reason.
    metric = RealTimeFactorMetric(threshold=1.0)
    metric.measure(_case(1.5, []))
    assert not metric.is_successful()
    assert "1.500" in metric.reason


def test_audio_integrity_metric() -> None:
    """The integrity metric passes on clean audio and fails on anomalies."""
    # No anomalies -> full score and success.
    clean = AudioIntegrityMetric()
    assert clean.measure(_case(0.3, [])) == 1.0
    assert clean.is_successful()
    # A clipping anomaly -> failure, with the cause named in the reason.
    dirty = AudioIntegrityMetric()
    dirty.measure(_case(0.3, ["clipping"]))
    assert not dirty.is_successful()
    assert "clipping" in dirty.reason


def test_deepeval_metrics_over_mock_eval() -> None:
    """Every case from a mock run passes both DeepEval metrics."""

    async def go() -> None:
        """Run a mock eval and assert both metrics pass for every case."""
        # Act: produce a real report over the first four mock cases.
        async with Speaker(Settings.from_mapping({"backend": "mock"})) as spk:
            report = await run_eval(spk, load_dataset()[:4])
        # Wrap each real case as a DeepEval case and score both metrics.
        rtf_metric, integrity_metric = RealTimeFactorMetric(1.0), AudioIntegrityMetric()
        for case in report.cases:
            tc = _case(case.rtf, case.anomalies)
            assert rtf_metric.measure(tc) == 1.0
            assert integrity_metric.measure(tc) == 1.0

    asyncio.run(go())
