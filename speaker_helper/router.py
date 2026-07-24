"""
Backend router: pick an engine + mode from measured quality↔speed evidence.

Module summary
--------------
The rest of speaker-helper *measures* a TTS operating point — real-time factor
(RTF), anomaly rate, and a quality score (measured chrF, or an engine prior) —
and can rank engines on the quality↔RTF plane (:func:`~speaker_helper.eval.priors.pareto_front`).
What it historically did **not** do is *act* on that evidence: :func:`create_engine`
just read ``settings.backend``. This module closes that loop. Given an operating
**condition** it returns a concrete, justified choice of engine, mode, and
streaming knobs — never a vibe, always traceable to numbers.

Two conditions, two different objectives (this is the scientific core):

* **online real-time** (delay-bounded / streaming). To sustain playback without
  underrun the engine must synthesise *faster than real time*: ``RTF < 1`` is a
  hard feasibility boundary. We keep a margin for time-to-first-audio and jitter
  (default ceiling ``0.8``). Among the engines that keep up, we **maximise
  quality**. Mode is ``streaming`` with low-TTFA knobs (small first chunk, strict
  pipeline). If nothing keeps up, that is reported, not hidden.

* **offline** (batch). There is no real-time constraint — ``RTF`` may exceed 1 —
  and **quality is the only objective**: speed is disregarded entirely. We pick
  the highest-quality engine outright (an optional RTF *patience* budget and an
  equal-quality speed tie-break are the only places RTF appears). Mode is
  ``offline``.

For the **online** condition the choice is taken only from the Pareto front (the
non-dominated set), so the router never returns a point some other engine beats
on both axes while still keeping up. Offline is a pure quality argmax.

Where does the evidence come from? In order of confidence:

1. **Measured reports** — pass a list of :class:`~speaker_helper.eval.runner.EvalReport`
   (from ``run_eval`` / ``run_multilang_eval`` / ``tune_profiles``). Both axes are
   then measured on *your* host → highest confidence.
2. **The built-in operating-point catalogue** (:func:`default_operating_points`)
   — seeded from the per-language profiles (kokoro RTF measured on native-MLX)
   and the engine quality priors. RTF is known only where it was measured; other
   engines carry a quality prior and an *unknown* RTF, and are therefore excluded
   from online routing (we will not claim an engine keeps up if we never timed
   it). Confidence is flagged on every decision.

Further characterisation of new engines is a *study*, not a toolbox concern — run
it in the ``speak`` experiment repo and fold the resulting numbers back into the
catalogue or pass them as reports.

Usage example
-------------
>>> from speaker_helper.router import route, RouteRequest
>>> d = route(RouteRequest(condition="online_realtime", language="fr"))
>>> d.engine
'kokoro'
>>> d.mode
'streaming'

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass

from speaker_helper.config import Settings
from speaker_helper.eval.priors import engine_quality_prior, pareto_front
from speaker_helper.profiles import MEASURED_MOS, profile_for

# The two operating conditions the router knows how to plan for. Kept as plain
# strings (not an enum) so they cross the CLI / JSON / MCP boundaries unchanged.
ONLINE_REALTIME = "online_realtime"
OFFLINE = "offline"
CONDITIONS = (ONLINE_REALTIME, OFFLINE)

# Default real-time-factor ceiling for the online condition. RTF < 1 is the hard
# boundary (compute must be faster than audio); 0.8 leaves ~20% headroom to
# absorb the first-chunk latency and per-chunk jitter that a pure mean RTF hides.
DEFAULT_RTF_CEILING = 0.8


@dataclass(frozen=True)
class OperatingPoint:
    """One engine's position on the quality↔speed plane, with provenance.

    Parameters
    ----------
    engine : str
        Engine/model id (e.g. ``"kokoro"``).
    quality : float
        Quality score in ``[0, 1]`` to **maximise** (measured chrF or a prior).
    mean_rtf : float or None
        Mean real-time factor to **minimise**; ``None`` when never measured (the
        engine then cannot be routed for the online condition).
    quality_source : str
        ``"measured_chrf"`` or ``"prior"`` — how ``quality`` was obtained.
    rtf_source : str
        ``"measured"``, ``"estimate"``, or ``"unknown"`` — how ``mean_rtf`` was
        obtained.
    backend : str
        The backend that serves this engine (default ``"voicebox"``).
    language : str or None
        Language the measurement pertains to, when language-specific.
    """

    engine: str
    quality: float
    mean_rtf: float | None
    quality_source: str = "prior"
    rtf_source: str = "unknown"
    backend: str = "voicebox"
    language: str | None = None


@dataclass(frozen=True)
class RouteRequest:
    """What the caller needs; the router turns it into a justified choice.

    Parameters
    ----------
    condition : str
        ``"online_realtime"`` (delay-bounded streaming) or ``"offline"``
        (throughput / quality). See :data:`CONDITIONS`.
    language : str
        ISO-639-1 target language (drives the default catalogue and profile).
    rtf_ceiling : float
        Online only: the hard ``mean_rtf`` bound an engine must beat to be
        feasible. Defaults to :data:`DEFAULT_RTF_CEILING` (``0.8``).
    rtf_budget : float or None
        Offline only: optional patience cap on ``mean_rtf`` (``None`` = no cap,
        quality is all that matters).
    quality_floor : float or None
        Reject any candidate below this quality, in both conditions (``None`` =
        no floor).
    require_measured_rtf : bool
        Online only: refuse engines whose RTF was never measured (default
        ``True`` — do not claim an untimed engine keeps up).
    """

    condition: str
    language: str = "fr"
    rtf_ceiling: float = DEFAULT_RTF_CEILING
    rtf_budget: float | None = None
    quality_floor: float | None = None
    require_measured_rtf: bool = True


@dataclass(frozen=True)
class RouteDecision:
    """A concrete, justified operating point the caller can act on.

    Parameters
    ----------
    condition : str
        The condition this decision answers.
    engine, backend : str
        The chosen engine and the backend that serves it.
    mode : str
        ``"streaming"`` (online) or ``"offline"``.
    first_chunk_sentences, stream_concurrency : int
        Streaming producer/consumer knobs implied by the condition (only
        meaningful when ``mode == "streaming"``).
    quality : float
        The chosen point's quality score.
    mean_rtf : float or None
        The chosen point's mean RTF (``None`` only in the offline, RTF-unknown
        fallback).
    quality_source, rtf_source : str
        Provenance of the two axes (see :class:`OperatingPoint`).
    confidence : str
        ``"high"`` (both axes measured), ``"medium"`` (one measured), or
        ``"low"`` (both from priors/estimates).
    justification : str
        A human-readable, number-citing explanation of *why* this point won.
    candidates_considered, pareto_size : int
        How many candidates were weighed and how many survived to the Pareto
        front — for auditability.
    """

    condition: str
    engine: str
    backend: str
    mode: str
    first_chunk_sentences: int
    stream_concurrency: int
    quality: float
    mean_rtf: float | None
    quality_source: str
    rtf_source: str
    confidence: str
    justification: str
    candidates_considered: int
    pareto_size: int

    def apply(self, settings: Settings | None = None) -> Settings:
        """Return ``settings`` (or fresh defaults) reconfigured for this decision.

        Parameters
        ----------
        settings : Settings or None
            Base configuration to derive from; ``None`` uses defaults.

        Returns
        -------
        Settings
            A copy carrying the chosen backend, engine, mode, and (for
            streaming) the first-chunk granularity. ``stream_concurrency`` is a
            :class:`~speaker_helper.speaker.Speaker` argument, not a
            :class:`Settings` field, so read it off this decision separately (see
            :meth:`~speaker_helper.speaker.Speaker.from_route`).
        """
        # Start from the caller's settings (or defaults) and fold in only the
        # fields the routing decision actually determines, leaving connection
        # details (host/port/timeouts) untouched.
        base = settings if settings is not None else Settings()
        return dataclasses.replace(
            base,
            backend=self.backend,
            engine=self.engine,
            mode=self.mode,
            first_chunk_sentences=self.first_chunk_sentences,
        )

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict of the decision (for API / MCP / CLI)."""
        return dataclasses.asdict(self)


def default_operating_points(language: str = "fr") -> list[OperatingPoint]:
    """Build the fallback candidate set for ``language`` from profiles + priors.

    The per-language profile supplies the *measured* kokoro operating point (RTF
    from native-MLX tuning; quality is the engine prior until a round-trip
    recalibrates it). Every other engine in the priors table contributes a
    *quality-only* candidate with an unknown RTF — enough to reason about offline
    quality, but deliberately not enough to claim it keeps up online.

    Parameters
    ----------
    language : str
        Language whose profile seeds the measured kokoro point.

    Returns
    -------
    list of OperatingPoint
        One candidate per known engine, provenance flagged on both axes.
    """
    points: list[OperatingPoint] = []

    # 1) The measured kokoro point for this language, straight off the profile.
    #    ``measured_rtf`` is real (native-MLX tuning); quality is still the prior
    #    until a WER/chrF round-trip recalibrates it, so flag the axes honestly.
    prof = profile_for(language)
    kokoro_rtf = prof.measured_rtf
    # Quality is a real UTMOSv2 MOS only for (engine, language) pairs the study
    # has measured (see profiles.MEASURED_MOS); otherwise it is the engine prior.
    kokoro_quality_measured = language in MEASURED_MOS.get("kokoro", set())
    points.append(
        OperatingPoint(
            engine="kokoro",
            quality=prof.measured_quality or engine_quality_prior("kokoro"),
            mean_rtf=kokoro_rtf,
            quality_source="measured_mos" if kokoro_quality_measured else "prior",
            rtf_source="measured" if kokoro_rtf is not None else "unknown",
            language=language,
        )
    )

    # 2) Every other engine we hold a quality prior for. RTF is unknown (never
    #    timed here), so these are quality-only candidates: usable for offline
    #    quality maximisation, excluded from online routing by default.
    from speaker_helper.eval.priors import TTS_QUALITY_PRIORS

    for engine, quality in TTS_QUALITY_PRIORS.items():
        # kokoro already added with its measured RTF; mock is a test signal, not
        # a shippable voice, so it never competes for a real routing decision.
        if engine in ("kokoro", "mock"):
            continue
        points.append(
            OperatingPoint(
                engine=engine,
                quality=quality,
                mean_rtf=None,
                quality_source="prior",
                rtf_source="unknown",
                language=language,
            )
        )
    return points


def _points_from_reports(reports: Sequence[object]) -> list[OperatingPoint]:
    """Convert measured :class:`EvalReport`-like objects into operating points.

    Parameters
    ----------
    reports : sequence
        Objects duck-typed with ``mean_rtf``, ``quality``, ``quality_source``
        and (optionally) ``backend`` — i.e. :class:`~speaker_helper.eval.runner.EvalReport`.
        Each report is expected to carry its engine id; when it does not, the
        report is skipped rather than guessed.

    Returns
    -------
    list of OperatingPoint
        Points with both axes measured (RTF is always measured in a report).
    """
    points: list[OperatingPoint] = []
    for r in reports:
        # A report measures RTF directly, so rtf_source is always "measured";
        # quality_source is whatever the report recorded (chrF vs prior).
        engine = getattr(r, "engine", None) or getattr(r, "engine_id", None)
        if not engine:
            # Without an engine label the point is unusable for a decision.
            continue
        points.append(
            OperatingPoint(
                engine=str(engine),
                quality=float(r.quality),
                mean_rtf=float(r.mean_rtf),
                quality_source=str(getattr(r, "quality_source", "prior")),
                rtf_source="measured",
                backend=str(getattr(r, "backend", "voicebox")),
            )
        )
    return points


def _confidence(point: OperatingPoint) -> str:
    """Rate how trustworthy a point is from its two provenance flags."""
    # Both axes measured → we stand on real numbers; one measured → medium; a
    # decision resting entirely on priors is explicitly low-confidence. Quality
    # counts as measured whether it came from a round-trip chrF or a UTMOSv2 MOS.
    measured_q = point.quality_source in ("measured_chrf", "measured_mos")
    measured_r = point.rtf_source == "measured"
    if measured_q and measured_r:
        return "high"
    if measured_q or measured_r:
        return "medium"
    return "low"


def route(
    request: RouteRequest,
    *,
    points: Sequence[OperatingPoint] | None = None,
    reports: Sequence[object] | None = None,
) -> RouteDecision:
    """Choose a justified engine + mode for ``request`` from the evidence.

    Parameters
    ----------
    request : RouteRequest
        The condition and its constraints.
    points : sequence of OperatingPoint or None
        Explicit candidate operating points. When ``None`` and ``reports`` is
        also ``None``, the built-in catalogue for ``request.language`` is used.
    reports : sequence of EvalReport or None
        Measured reports to derive candidates from (highest confidence). Takes
        precedence over ``points`` when both are given.

    Returns
    -------
    RouteDecision
        The chosen operating point, mode, streaming knobs, and a number-citing
        justification.

    Raises
    ------
    ValueError
        If ``request.condition`` is unknown, or no candidate satisfies the
        condition's constraints (e.g. no engine keeps up online).

    Examples
    --------
    >>> route(RouteRequest(condition="offline", language="fr")).mode
    'offline'
    """
    # Validate the condition up front so a typo fails loudly, not silently.
    if request.condition not in CONDITIONS:
        raise ValueError(f"unknown condition {request.condition!r}; expected one of {CONDITIONS}")

    # Resolve the candidate set, most-trusted source first: explicit reports >
    # explicit points > the built-in per-language catalogue.
    if reports is not None:
        candidates = _points_from_reports(reports)
    elif points is not None:
        candidates = list(points)
    else:
        candidates = default_operating_points(request.language)
    n_considered = len(candidates)
    if not candidates:
        raise ValueError("no candidate operating points to route over")

    # A global quality floor applies to both conditions when set.
    if request.quality_floor is not None:
        candidates = [c for c in candidates if c.quality >= request.quality_floor]

    if request.condition == ONLINE_REALTIME:
        decision = _route_online(request, candidates)
    else:
        decision = _route_offline(request, candidates)
    # Stamp how many candidates were weighed so the decision is auditable.
    return dataclasses.replace(decision, candidates_considered=n_considered)


def _route_online(request: RouteRequest, candidates: list[OperatingPoint]) -> RouteDecision:
    """Plan the online real-time (delay-bounded, streaming) condition."""
    # Feasibility first: an engine must synthesise faster than the ceiling to
    # sustain streaming. Points with an unknown RTF are dropped unless the caller
    # explicitly allows unmeasured engines — we will not claim they keep up.
    feasible = [
        c for c in candidates if c.mean_rtf is not None and c.mean_rtf <= request.rtf_ceiling
    ]
    if request.require_measured_rtf:
        feasible = [c for c in feasible if c.rtf_source == "measured"]
    if not feasible:
        # No engine provably keeps up: surface it rather than shipping a guess.
        raise ValueError(
            f"no engine meets the online RTF ceiling {request.rtf_ceiling} "
            f"for language {request.language!r} with measured timing; "
            "measure more engines (see the 'speak' study) or relax the ceiling / "
            "set require_measured_rtf=False"
        )
    # Among engines that keep up, pick the highest quality; break ties toward the
    # faster engine (more headroom for jitter). Only the Pareto front can win, so
    # a slower-and-worse point never sneaks through.
    front = pareto_front(_as_pareto(feasible))
    chosen = _best_quality(front, tie_break_faster=True)
    mean_rtf = chosen.mean_rtf if chosen.mean_rtf is not None else float("nan")
    justification = (
        f"online_realtime: require mean_rtf <= {request.rtf_ceiling} "
        f"(RTF<1 is the real-time feasibility boundary; margin absorbs TTFA + jitter). "
        f"{len(feasible)}/{len(candidates)} candidates keep up; on the "
        f"{len(front)}-point Pareto front, chose '{chosen.engine}' "
        f"(mean_rtf={mean_rtf:.3f} [{chosen.rtf_source}], "
        f"quality={chosen.quality:.3f} [{chosen.quality_source}]) as the highest "
        f"quality that sustains real time. mode=streaming, first_chunk_sentences=1, "
        f"stream_concurrency=1 for minimal time-to-first-audio."
    )
    return RouteDecision(
        condition=ONLINE_REALTIME,
        engine=chosen.engine,
        backend=chosen.backend,
        mode="streaming",
        # Low-TTFA streaming knobs: a one-sentence first chunk and a strict
        # pipeline get the first audio out as early as possible.
        first_chunk_sentences=1,
        stream_concurrency=1,
        quality=chosen.quality,
        mean_rtf=chosen.mean_rtf,
        quality_source=chosen.quality_source,
        rtf_source=chosen.rtf_source,
        confidence=_confidence(chosen),
        justification=justification,
        candidates_considered=len(candidates),
        pareto_size=len(front),
    )


def _route_offline(request: RouteRequest, candidates: list[OperatingPoint]) -> RouteDecision:
    """Plan the offline condition: **only synthesis quality matters**.

    Offline has no real-time constraint, so speed is *not* an objective at all —
    we maximise quality over the whole candidate pool. RTF appears only as an
    optional *patience* budget the caller may set, and as a last-resort tie-break
    between candidates of exactly equal quality (so a needless compute cost is
    avoided when quality cannot distinguish them). Engines with an unmeasured RTF
    stay in the running: not knowing an engine's speed never disqualifies it when
    speed does not matter.
    """
    # Apply only the optional patience budget; RTF-unknown engines are kept
    # (offline never rejects a candidate for being slow unless a budget says so).
    pool = candidates
    if request.rtf_budget is not None:
        pool = [c for c in candidates if c.mean_rtf is None or c.mean_rtf <= request.rtf_budget]
    if not pool:
        raise ValueError(f"no engine meets the offline RTF budget {request.rtf_budget}")
    # Pure quality argmax over the entire pool (ties broken toward the faster
    # engine only when quality is identical). No Pareto gate: dropping a
    # higher-quality engine because its RTF is unknown would violate the
    # offline objective of caring about quality alone.
    chosen = _best_quality(pool, tie_break_faster=True)
    rtf_str = "n/a" if chosen.mean_rtf is None else f"{chosen.mean_rtf:.3f}"
    justification = (
        f"offline: quality is the ONLY objective (no real-time constraint). "
        f"Maximise quality over {len(pool)} candidate(s)"
        + (
            f" within optional RTF budget {request.rtf_budget}"
            if request.rtf_budget is not None
            else ""
        )
        + f"; chose '{chosen.engine}' (quality={chosen.quality:.3f} "
        f"[{chosen.quality_source}], mean_rtf={rtf_str} [{chosen.rtf_source}]). "
        f"mode=offline (whole-text synthesis; speed disregarded)."
    )
    return RouteDecision(
        condition=OFFLINE,
        engine=chosen.engine,
        backend=chosen.backend,
        mode="offline",
        # Streaming knobs are inert in offline mode but kept at sane defaults.
        first_chunk_sentences=1,
        stream_concurrency=1,
        quality=chosen.quality,
        mean_rtf=chosen.mean_rtf,
        quality_source=chosen.quality_source,
        rtf_source=chosen.rtf_source,
        confidence=_confidence(chosen),
        justification=justification,
        candidates_considered=len(candidates),
        # No Pareto front is used offline (quality-only), so report 0.
        pareto_size=0,
    )


class _ParetoAdapter:
    """Expose an :class:`OperatingPoint` through the ``pareto_front`` protocol.

    Parameters
    ----------
    point : OperatingPoint
        The wrapped candidate (must have a non-``None`` ``mean_rtf``).
    """

    def __init__(self, point: OperatingPoint) -> None:
        """Store the wrapped point for property access."""
        self.point = point

    @property
    def quality(self) -> float:
        """Quality to maximise (delegates to the wrapped point)."""
        return self.point.quality

    @property
    def mean_rtf(self) -> float:
        """RTF to minimise (delegates; caller guarantees it is not ``None``)."""
        assert self.point.mean_rtf is not None
        return self.point.mean_rtf


def _as_pareto(points: list[OperatingPoint]) -> list[_ParetoAdapter]:
    """Wrap RTF-known points so :func:`pareto_front` can rank them."""
    # pareto_front needs both axes; callers pass only RTF-known points here.
    return [_ParetoAdapter(p) for p in points]


def _best_quality(front: Sequence[object], *, tie_break_faster: bool) -> OperatingPoint:
    """Return the highest-quality point on ``front`` (ties broken by speed).

    Parameters
    ----------
    front : sequence
        Either :class:`_ParetoAdapter` wrappers or bare :class:`OperatingPoint`
        (the offline RTF-unknown fallback passes bare points).
    tie_break_faster : bool
        On equal quality, prefer the lower RTF (unknown RTF sorts last).

    Returns
    -------
    OperatingPoint
        The winning candidate.
    """
    # Normalise wrappers back to the underlying OperatingPoint for a uniform key.
    unwrapped = [p.point if isinstance(p, _ParetoAdapter) else p for p in front]

    def _key(p: OperatingPoint) -> tuple[float, float]:
        # Sort by quality descending (negate) then RTF ascending; an unknown RTF
        # is treated as +inf so it loses every speed tie-break.
        rtf = p.mean_rtf if p.mean_rtf is not None else float("inf")
        return (-p.quality, rtf if tie_break_faster else 0.0)

    return sorted(unwrapped, key=_key)[0]


def route_settings(
    condition: str,
    *,
    language: str = "fr",
    settings: Settings | None = None,
    **request_kwargs: object,
) -> tuple[Settings, RouteDecision]:
    """Convenience: route for ``condition`` and return applied settings + decision.

    Parameters
    ----------
    condition : str
        ``"online_realtime"`` or ``"offline"``.
    language : str
        Target language.
    settings : Settings or None
        Base settings to reconfigure; ``None`` uses defaults.
    **request_kwargs
        Extra :class:`RouteRequest` fields (``rtf_ceiling``, ``rtf_budget``,
        ``quality_floor``, ``require_measured_rtf``).

    Returns
    -------
    tuple of (Settings, RouteDecision)
        Settings reconfigured for the decision, and the decision itself (its
        ``stream_concurrency`` still needs forwarding to :class:`Speaker`).
    """
    req = RouteRequest(condition=condition, language=language, **request_kwargs)  # type: ignore[arg-type]
    decision = route(req)
    return decision.apply(settings), decision
