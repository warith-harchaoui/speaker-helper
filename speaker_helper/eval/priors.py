"""
Quality priors and Pareto selection for choosing an engine.

Module summary
--------------
Two ideas make engine choice operational:

1. **A quality axis even without a reference.** When no transcriber is wired in,
   fidelity is *estimated* from per-engine priors — order-of-magnitude scores in
   ``[0, 1]``, recalibrated from real runs. This keeps every evaluation
   reporting *both* speed and quality.
2. **Pareto selection.** To pick an engine/voice you want the non-dominated set
   on the quality↔RTF plane — high quality *and* fast. :func:`pareto_front`
   extracts it.

Together these turn a batch of :class:`~speaker_helper.eval.runner.EvalReport`
(one per engine) into an actionable "which engine should I ship?" answer.

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

# TTS quality priors in [0, 1]: order-of-magnitude estimates keyed on the
# engine — recalibrate from measured round-trips (WER/chrF) as real data
# accumulates. Unknown engines get 0.80.
TTS_QUALITY_PRIORS: dict[str, float] = {
    "kokoro": 0.75,
    "chatterbox_turbo": 0.82,
    "chatterbox": 0.90,
    "kyutai": 0.88,
    "qwen3_tts": 0.88,
    "qwen_customvoice": 0.90,
    "f5": 0.86,
    "xtts": 0.70,
    "mock": 1.00,  # deterministic reference signal — nominal "perfect".
}
_DEFAULT_PRIOR = 0.80

# Per-language refinements of the priors above, where the 2026-10 survey
# (STUDY.md, `research` branch) found language-specific evidence — a single
# number per engine hides exactly the asymmetry that matters here:
#
# * **kyutai** speaks native French (a French lab, FR WER 3.29% on its card)
#   and good-but-not-leading English → fr above its base, en below.
# * **chatterbox** is the most expressive English open model but renders
#   French at 6–8% CER through an English-first pipeline → en keeps the base,
#   fr drops well under kyutai's.
#
# These are still *priors* (quality_source="prior", confidence="low" at the
# router): the ~/speak study's measured UTMOSv2/chrF numbers replace them as
# they land, exactly as kokoro's already did (see profiles._MEASURED_KOKORO).
#
# The ``"*"`` key is a per-engine floor for every *other* language: kyutai
# only speaks French and English, and would read Spanish with a
# French/English tongue — so outside fr/en it must lose to chatterbox's
# multilingual model (23 languages), which keeps its base prior there.
TTS_QUALITY_PRIORS_BY_LANG: dict[str, dict[str, float]] = {
    "kyutai": {"fr": 0.92, "en": 0.85, "*": 0.30},
    "chatterbox": {"fr": 0.78, "en": 0.90},
}


def engine_quality_prior(engine: str, language: str | None = None) -> float:
    """Return the prior quality score in ``[0, 1]`` for a TTS ``engine``.

    Parameters
    ----------
    engine : str
        Engine id (e.g. ``"kokoro"``).
    language : str or None
        ISO-639 code (regional variants accepted, e.g. ``"fr-fr"``). When a
        per-language refinement exists for the engine it wins over the base
        prior; ``None`` keeps the language-blind base.

    Returns
    -------
    float
        The most specific prior available, or ``0.80`` for an unknown engine.

    Examples
    --------
    >>> engine_quality_prior("kyutai", "fr")
    0.92
    >>> engine_quality_prior("kyutai")
    0.88
    """
    # The language key is the bare ISO base: "fr-FR" and "fr" are one prior.
    if language:
        base = language.strip().lower().split("-")[0]
        by_lang = TTS_QUALITY_PRIORS_BY_LANG.get(engine, {})
        if base in by_lang:
            return by_lang[base]
        # The engine's own floor for languages it was never refined on —
        # how kyutai is kept away from Spanish (see the table's comment).
        if "*" in by_lang:
            return by_lang["*"]
    return TTS_QUALITY_PRIORS.get(engine, _DEFAULT_PRIOR)


class _ParetoPoint(Protocol):
    """A candidate carrying a quality (maximise) and an RTF (minimise)."""

    @property
    def quality(self) -> float:
        """Quality score to maximise (higher is better)."""
        ...

    @property
    def mean_rtf(self) -> float:
        """Mean real-time factor to minimise (lower is faster)."""
        ...


def pareto_front(points: Sequence[_ParetoPoint]) -> list[_ParetoPoint]:
    """Return the non-dominated points: maximise quality, minimise RTF.

    A point A dominates B if A is at least as good on both axes (higher or equal
    ``quality``, lower or equal ``mean_rtf``) and strictly better on one.

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
        # ``a`` stays on the front unless some other point dominates it.
        dominated = False
        for b in points:
            # A point never dominates itself.
            if b is a:
                continue
            # b dominates a when it is at least as good on BOTH axes (higher or
            # equal quality, lower or equal RTF) and strictly better on one —
            # i.e. b is a free improvement over a, so a is not Pareto-optimal.
            if (
                b.quality >= a.quality
                and b.mean_rtf <= a.mean_rtf
                and (b.quality > a.quality or b.mean_rtf < a.mean_rtf)
            ):
                dominated = True
                break
        # Undominated points form the quality↔RTF frontier.
        if not dominated:
            front.append(a)
    return front
