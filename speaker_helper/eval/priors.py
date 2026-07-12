"""
Quality priors and Pareto selection, inherited from the ``speak`` study.

Module summary
--------------
The ``speak`` study established two things speaker-helper reuses directly:

1. **A quality axis even without a reference.** When no transcriber is wired in,
   fidelity can still be *estimated* from per-engine priors — order-of-magnitude
   scores in ``[0, 1]``, recalibrate from real runs. This keeps every evaluation
   reporting *both* speed and quality, which is the whole point of the study.
2. **Pareto selection.** To choose an engine/voice operationally you want the
   non-dominated set on the quality↔RTF plane — high quality *and* fast. The
   :func:`pareto_front` helper (ported from ``speak.experiment``) extracts it.

Together these turn a batch of :class:`~speaker_helper.eval.runner.EvalReport`
(one per engine) into an actionable "which engine should I ship?" answer — the
operational counterpart of the study's formal Pareto sweep.

Usage example
-------------
>>> from speaker_helper.eval.priors import engine_quality_prior
>>> engine_quality_prior("kokoro")
0.75

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

# TTS quality priors in [0, 1], inherited verbatim from ``speak.metrics``.
# Order-of-magnitude estimates keyed on the engine — recalibrate from measured
# round-trips (WER/chrF) as real data accumulates. Unknown engines get 0.80.
TTS_QUALITY_PRIORS: dict[str, float] = {
    "kokoro": 0.75,
    "chatterbox_turbo": 0.82,
    "chatterbox": 0.90,
    "qwen3_tts": 0.88,
    "qwen_customvoice": 0.90,
    "f5": 0.86,
    "xtts": 0.70,
    "mock": 1.00,  # deterministic reference signal — nominal "perfect".
}
_DEFAULT_PRIOR = 0.80


def engine_quality_prior(engine: str) -> float:
    """Return the prior quality score in ``[0, 1]`` for a TTS ``engine``.

    Parameters
    ----------
    engine : str
        Engine id (e.g. ``"kokoro"``).

    Returns
    -------
    float
        The inherited prior, or ``0.80`` for an unknown engine.
    """
    return TTS_QUALITY_PRIORS.get(engine, _DEFAULT_PRIOR)


class _ParetoPoint(Protocol):
    """A candidate carrying a quality (maximise) and an RTF (minimise)."""

    @property
    def quality(self) -> float: ...

    @property
    def mean_rtf(self) -> float: ...


def pareto_front(points: Sequence[_ParetoPoint]) -> list[_ParetoPoint]:
    """Return the non-dominated points: maximise quality, minimise RTF.

    A point A dominates B if A is at least as good on both axes (higher or equal
    ``quality``, lower or equal ``mean_rtf``) and strictly better on one. Ported
    from ``speak.experiment.pareto_front``.

    Parameters
    ----------
    points : sequence
        Candidates, each exposing ``quality`` and ``mean_rtf`` (e.g.
        :class:`~speaker_helper.eval.runner.EvalReport`).

    Returns
    -------
    list
        The Pareto-optimal subset, in input order.
    """
    front: list[_ParetoPoint] = []
    for a in points:
        dominated = False
        for b in points:
            if b is a:
                continue
            if b.quality >= a.quality and b.mean_rtf <= a.mean_rtf \
                    and (b.quality > a.quality or b.mean_rtf < a.mean_rtf):
                dominated = True
                break
        if not dominated:
            front.append(a)
    return front
