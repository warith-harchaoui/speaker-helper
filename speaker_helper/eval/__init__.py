"""
speaker-helper evaluation layer — measure speed and quality, gate on thresholds.

Module summary
--------------
The project's coding contract forbids "vibe checks": anything AI must be
evaluated against a committed dataset with versioned metrics and thresholds.
This package provides speaker-helper's measurement machinery and makes it a
first-class, CI-gating layer.

It is **engine-agnostic**: everything runs against the
:class:`~speaker_helper.speaker.Speaker` façade, so the exact same evaluation
grades the deterministic ``mock`` backend in CI or the real Voicebox ``kokoro``
engine locally — only ``settings.backend`` differs.

Public surface
--------------
* :func:`~speaker_helper.eval.dataset.load_dataset`, :class:`EvalCase`
* :class:`~speaker_helper.eval.thresholds.Thresholds`
* :func:`~speaker_helper.eval.runner.run_eval`, :class:`EvalReport`,
  :class:`CaseResult`, :class:`Transcriber`
* metrics: :func:`word_error_rate`, :func:`chrf`, :func:`detect_anomalies`,
  :func:`percentile`

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

# Datasets: the versioned reference utterances an evaluation runs against.
from speaker_helper.eval.dataset import (
    DEFAULT_DATASET,
    EvalCase,
    available_languages,
    load_dataset,
)

# Metrics: the raw speed/fidelity/integrity measurements.
from speaker_helper.eval.metrics import (
    chrf,
    detect_anomalies,
    percentile,
    word_error_rate,
)

# Multi-language sweep: one report per language plus a text matrix renderer.
from speaker_helper.eval.multilang import format_matrix, run_multilang_eval

# Quality priors and Pareto selection over the quality↔RTF plane.
from speaker_helper.eval.priors import (
    TTS_QUALITY_PRIORS,
    engine_quality_prior,
    pareto_front,
)

# Runner: drives a Speaker over cases and gates on thresholds.
from speaker_helper.eval.runner import (
    CaseResult,
    EvalReport,
    Transcriber,
    run_eval,
)

# The versioned pass/fail bar the runner compares each report against.
from speaker_helper.eval.thresholds import Thresholds

# Explicit public surface: the names above are the eval layer's stable API;
# everything else in the sub-modules is an implementation detail.
__all__ = [
    "DEFAULT_DATASET",
    "TTS_QUALITY_PRIORS",
    "CaseResult",
    "EvalCase",
    "EvalReport",
    "Thresholds",
    "Transcriber",
    "available_languages",
    "chrf",
    "detect_anomalies",
    "engine_quality_prior",
    "format_matrix",
    "load_dataset",
    "pareto_front",
    "percentile",
    "run_eval",
    "run_multilang_eval",
    "word_error_rate",
]
