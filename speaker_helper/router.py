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

* **offline** (batch). There is no real-time constraint, and **quality is the
  only objective**: speed is not an objective at all. We pick the highest-quality
  engine outright, and the decision carries **no RTF** — ``mean_rtf`` is ``None``
  and ``rtf_source`` is ``"not_considered"``, so a timing cannot be mistaken for
  part of the reasoning. The single exception is a *patience* budget the caller
  sets explicitly, which filters candidates and is named as the caller's own
  constraint. ``confidence`` likewise rates the quality evidence alone. Mode is
  ``offline``. Where the owner has arbitrated a language himself
  (:data:`OFFLINE_RATIFIED_ENGINE` — French since 2026-10-28), his choice takes
  the decision and the justification says which candidate it overrode: an
  arbitration is reported as an arbitration, never folded into the quality
  numbers.

For the **online** condition the choice is taken only from the Pareto front (the
non-dominated set), so the router never returns a point some other engine beats
on both axes while still keeping up. Offline is a pure quality argmax.

Where does the evidence come from? In order of confidence:

1. **Measured reports** — pass a list of :class:`~speaker_helper.eval.runner.EvalReport`
   (from ``run_eval`` / ``run_multilang_eval`` / ``tune_profiles``). Both axes are
   then measured on *your* host → highest confidence.
2. **The built-in operating-point catalogue** (:func:`default_operating_points`)
   — seeded from the per-language profiles (kokoro RTF measured in-process on
   this suite's reference host) and the engine quality priors. RTF is known only
   where it was measured; other engines carry a quality prior and an *unknown*
   RTF, and are therefore excluded
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
# strings (not an enum) so they cross the CLI / JSON boundaries unchanged.
ONLINE_REALTIME = "online_realtime"
OFFLINE = "offline"
CONDITIONS = (ONLINE_REALTIME, OFFLINE)

# Default real-time-factor ceiling for the online condition. RTF < 1 is the hard
# boundary (compute must be faster than audio); 0.8 leaves ~20% headroom to
# absorb the first-chunk latency and per-chunk jitter that a pure mean RTF hides.
DEFAULT_RTF_CEILING = 0.8

# Which in-tree backend serves each engine id the catalogue may propose. An
# engine absent from this table has no backend in this package: routing to it
# would produce Settings no `create_engine` call can honour, so the default
# catalogue excludes it (its prior stays available to the eval layer).
# `chatterbox_turbo` is deliberately NOT a routing candidate: the chatterbox
# backend picks its Turbo/Multilingual variant from the language itself, so a
# separate catalogue row would only duplicate `chatterbox` — and its
# never-measured prior would outrank the measured numbers.
ENGINE_BACKENDS: dict[str, str] = {
    "kokoro": "kokoro",
    "chatterbox": "chatterbox",
    "kyutai": "kyutai",
    "openvoice": "openvoice",
}

# Owner-ratified offline engine, per language. This is a DECISION, not a
# measurement, and it is kept apart from the quality tables on purpose: the
# documented evidence stays untouched and keeps saying what it said (for
# French, kyutai's 0.92 prior still outranks chatterbox's 0.78 — see
# `TTS_QUALITY_PRIORS_BY_LANG` and its CER note). What this table says is that
# for the listed languages the owner has arbitrated the offline case himself,
# so the router must follow the choice rather than the argmax, and say out
# loud in its justification what it overrode.
#
# * **fr → chatterbox** (ratified 2026-10-28). The owner's ear, on the offline
#   case, prefers chatterbox's French to kyutai's. Which chatterbox: the best
#   documented one that actually speaks French, i.e. the **Multilingual**
#   model (23 languages, base prior 0.90) — Turbo and base are English-only,
#   so they were never candidates here. No knob is needed: the backend's
#   `variant="auto"` already resolves any non-English language to Multilingual
#   (see `backends/chatterbox.py::_variant_for`).
#
# The honest counterpart: this ordering is one listener's judgement, exactly
# like the editorial priors it overrides, and it is pending the same
# replacement — a human pairwise-listening protocol (STUDY.md §8 bis), whose
# scores would land as `quality_source="measured_human"` and settle the fr
# case on evidence instead of arbitration.
OFFLINE_RATIFIED_ENGINE: dict[str, str] = {"fr": "chatterbox"}

#: As-of date of the ratifications above — a decision carries its date, same
#: rule as `PUBLIC_ELO_AS_OF` and LANDSCAPE.md's licence table.
OFFLINE_RATIFIED_AS_OF: str = "2026-10-28"


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
        The backend that serves this engine (default ``"kokoro"``).
    language : str or None
        Language the measurement pertains to, when language-specific.
    """

    engine: str
    quality: float
    mean_rtf: float | None
    quality_source: str = "prior"
    rtf_source: str = "unknown"
    backend: str = "kokoro"
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
        Offline only: an optional patience cap the **caller** may impose
        (``None``, the default, = no cap — quality is all that matters). This is
        the one place RTF can touch an offline route, and it is opt-in: the
        router never introduces a speed criterion of its own there.
    quality_floor : float or None
        Reject any candidate below this quality, in both conditions (``None`` =
        no floor).
    require_measured_rtf : bool
        Online only: refuse engines whose RTF was never measured (default
        ``True`` — do not claim an untimed engine keeps up).
    respect_ratification : bool
        Offline only: honour :data:`OFFLINE_RATIFIED_ENGINE` for this language
        (default ``True``). Set ``False`` to see the unarbitrated quality
        argmax — what a study comparing engines wants, and what makes the
        owner's override visible as an override.
    """

    condition: str
    language: str = "fr"
    rtf_ceiling: float = DEFAULT_RTF_CEILING
    rtf_budget: float | None = None
    quality_floor: float | None = None
    require_measured_rtf: bool = True
    respect_ratification: bool = True


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
        The chosen point's mean RTF. **Always ``None`` for an offline
        decision**: RTF is not an objective there, so it is not reported.
    quality_source, rtf_source : str
        Provenance of the two axes (see :class:`OperatingPoint`). Offline
        decisions carry ``rtf_source="not_considered"``.
    confidence : str
        Online: ``"high"`` (both axes measured), ``"medium"`` (one), ``"low"``
        (neither). Offline: the confidence in the QUALITY evidence alone —
        ``"high"`` if measured, ``"low"`` if a prior.
    justification : str
        A human-readable, number-citing explanation of *why* this point won.
    candidates_considered, pareto_size : int
        How many candidates were weighed and how many survived to the Pareto
        front — for auditability.
    owner_ratified : bool
        ``True`` when this engine was taken from :data:`OFFLINE_RATIFIED_ENGINE`
        rather than won on the quality axis. The ``justification`` then names
        the candidate it overrode and that candidate's score.
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
    owner_ratified: bool = False

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
        """Return a JSON-serialisable dict of the decision (for API / CLI)."""
        return dataclasses.asdict(self)


def _quality_for(engine: str, language: str, condition: str) -> tuple[float, str]:
    """The quality score and its provenance for one engine under one condition.

    The two conditions deliberately rank quality on **different criteria**,
    both chosen by the project owner (STREAMING.md / STUDY.md §8 bis):

    * **offline** — the ratified editorial choice, encoded as language-aware
      priors (``"prior"``), except kokoro whose per-language UTMOSv2
      measurement predates the criterion debate (``"measured_mos"``). These
      scores stay as documented even where :data:`OFFLINE_RATIFIED_ENGINE`
      takes the decision out of the argmax's hands: an override must not
      rewrite the evidence it overrides.
    * **online_realtime** — the **public arena Elo** (human pairwise votes,
      ``"public_elo"``). An engine absent from every public arena has no
      evidence under this criterion: it scores 0.0 with provenance
      ``"no_public_elo"`` — a documented data gap that ranks it below every
      publicly-ranked engine, never a flattering prior in disguise.

    Parameters
    ----------
    engine : str
        Engine id (e.g. ``"kokoro"``).
    language : str
        ISO-639 target language (drives the per-language prior / MOS tables).
    condition : str
        :data:`ONLINE_REALTIME` or :data:`OFFLINE`.

    Returns
    -------
    tuple of (float, str)
        ``(quality, quality_source)`` ready for an :class:`OperatingPoint`.
    """
    from speaker_helper.eval.priors import PUBLIC_ELO, elo_to_unit

    # Online: the ratified public-Elo criterion, or an explicit gap.
    if condition == ONLINE_REALTIME:
        elo = PUBLIC_ELO.get(engine)
        if elo is not None:
            return elo_to_unit(elo), "public_elo"
        return 0.0, "no_public_elo"
    # Offline: kokoro's per-language UTMOSv2 measurement where it exists,
    # the owner-ratified language-aware prior everywhere else.
    if engine == "kokoro":
        prof = profile_for(language)
        if prof.measured_quality is not None and language in MEASURED_MOS.get("kokoro", set()):
            return prof.measured_quality, "measured_mos"
    return engine_quality_prior(engine, language), "prior"


def default_operating_points(
    language: str = "fr", condition: str = OFFLINE
) -> list[OperatingPoint]:
    """Build the fallback candidate set for ``language`` under ``condition``.

    The per-language profile supplies kokoro's *measured* RTF (in-process
    tuning) and :data:`~speaker_helper.profiles.MEASURED_RTF` supplies the
    other engines' (the speak study's streaming bench) — performance is one
    axis for both conditions. Quality, by contrast, is **condition-specific**
    (see :func:`_quality_for`): the owner-ratified priors offline, the public
    arena Elo online.

    Parameters
    ----------
    language : str
        Language whose profile seeds the measured kokoro point.
    condition : str
        :data:`ONLINE_REALTIME` or :data:`OFFLINE` (default — the historical
        behaviour of this function).

    Returns
    -------
    list of OperatingPoint
        One candidate per known engine, provenance flagged on both axes.
    """
    from speaker_helper.eval.priors import TTS_QUALITY_PRIORS
    from speaker_helper.profiles import MEASURED_RTF

    base = (language or "").lower().split("-")[0]
    points: list[OperatingPoint] = []

    # 1) The measured kokoro point for this language, straight off the profile.
    prof = profile_for(language)
    kokoro_rtf = prof.measured_rtf
    quality, quality_source = _quality_for("kokoro", language, condition)
    points.append(
        OperatingPoint(
            engine="kokoro",
            quality=quality,
            mean_rtf=kokoro_rtf,
            quality_source=quality_source,
            rtf_source="measured" if kokoro_rtf is not None else "unknown",
            language=language,
        )
    )

    # 2) Every other engine with an in-tree backend. Engines without one
    #    (qwen3_tts, f5, xtts, …) keep their priors for the eval layer but
    #    never enter a routing decision no `create_engine` could honour.
    for engine in TTS_QUALITY_PRIORS:
        # kokoro already added with its measured RTF; mock is a test signal, not
        # a shippable voice, so it never competes for a real routing decision.
        if engine in ("kokoro", "mock"):
            continue
        backend = ENGINE_BACKENDS.get(engine)
        if backend is None:
            continue
        quality, quality_source = _quality_for(engine, language, condition)
        # RTF from the streaming bench where measured (sustained RTF through
        # Speaker.stream on the reference host), honestly unknown elsewhere —
        # and the online condition refuses unknown-RTF engines by default.
        measured_rtf = MEASURED_RTF.get(engine, {}).get(base)
        points.append(
            OperatingPoint(
                engine=engine,
                quality=quality,
                mean_rtf=measured_rtf,
                quality_source=quality_source,
                rtf_source="measured" if measured_rtf is not None else "unknown",
                backend=backend,
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
                backend=str(getattr(r, "backend", "kokoro")),
            )
        )
    return points


def _confidence(point: OperatingPoint, condition: str) -> str:
    """Rate how trustworthy a point is, on the axes the condition actually uses.

    Quality counts as evidenced whether it came from a round-trip chrF, a
    UTMOSv2 MOS, or a public arena Elo (human pairwise votes — the online
    condition's ratified criterion); ``"no_public_elo"`` and ``"prior"`` do not.

    The two conditions weigh different numbers of axes, so they cannot share a
    scale:

    * **offline** — RTF is not an objective here, so it must not prop up a
      confidence score either. Rating an offline decision "medium" because we
      happened to time the engine would dress a bare prior up as half-evidence.
      Confidence is therefore the confidence in the QUALITY evidence, full
      stop: measured → ``"high"``, prior → ``"low"``.
    * **online_realtime** — both axes are load-bearing (quality to maximise,
      RTF to clear the feasibility ceiling), so both count: two measured axes
      → ``"high"``, one → ``"medium"``, neither → ``"low"``.

    Parameters
    ----------
    point : OperatingPoint
        The winning candidate.
    condition : str
        :data:`ONLINE_REALTIME` or :data:`OFFLINE`.

    Returns
    -------
    str
        ``"high"``, ``"medium"`` or ``"low"``.
    """
    measured_q = point.quality_source in ("measured_chrf", "measured_mos", "public_elo")
    if condition == OFFLINE:
        return "high" if measured_q else "low"
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
        # The catalogue is condition-aware: quality is ranked by the public
        # arena Elo online and by the owner-ratified priors offline.
        candidates = default_operating_points(request.language, request.condition)
    n_considered = len(candidates)
    if not candidates:
        raise ValueError("no candidate operating points to route over")

    # A global quality floor applies to both conditions when set.
    if request.quality_floor is not None:
        best_before = max(candidates, key=lambda c: c.quality)
        candidates = [c for c in candidates if c.quality >= request.quality_floor]
        # Diagnose an empty pool HERE, where the cause is known. Left to the
        # per-condition code below, the floor's victims were blamed on that
        # condition's own filter: an offline caller who set only a quality
        # floor was told "no engine meets the offline RTF budget None" --
        # naming a budget they never set, and printing None as its value --
        # while an online one was advised to relax an RTF ceiling that had
        # rejected nothing. Both messages sent the caller to the wrong knob.
        if not candidates:
            raise ValueError(
                f"no engine for language {request.language!r} reaches the quality "
                f"floor {request.quality_floor} under the {request.condition} "
                f"criterion (best available: {best_before.engine!r} at "
                f"{best_before.quality:.3f} [{best_before.quality_source}]); "
                "lower the floor or measure more engines"
            )

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
        confidence=_confidence(chosen, ONLINE_REALTIME),
        justification=justification,
        candidates_considered=len(candidates),
        pareto_size=len(front),
    )


def _route_offline(request: RouteRequest, candidates: list[OperatingPoint]) -> RouteDecision:
    """Plan the offline condition: **only synthesis quality matters**.

    Offline has no real-time constraint, so speed is *not* an objective at all —
    we maximise quality over the whole candidate pool. RTF does not rank, does
    not break ties, and does not reach the returned decision (``mean_rtf`` is
    ``None``, ``rtf_source`` is ``"not_considered"``) or its confidence score.
    Equal quality is broken by catalogue order, deterministically, rather than by
    reaching for a speed number the condition has no use for. The caller's
    optional patience budget is the sole exception, and is named as the caller's
    constraint. Engines with an unmeasured RTF stay in the running: not knowing
    an engine's speed cannot disqualify it when speed does not matter.

    One thing outranks the argmax: an owner ratification for the language
    (:data:`OFFLINE_RATIFIED_ENGINE`). It is applied *after* the quality floor
    and the RTF budget — so those vetoes still bite — and it is always declared,
    via ``owner_ratified=True`` and a justification naming what it set aside.
    """
    # Apply only the optional patience budget; RTF-unknown engines are kept
    # (offline never rejects a candidate for being slow unless a budget says so).
    pool = candidates
    if request.rtf_budget is not None:
        pool = [c for c in candidates if c.mean_rtf is None or c.mean_rtf <= request.rtf_budget]
        # Nested under the budget on purpose. `candidates` is non-empty by
        # route()'s own guards, so with no budget set `pool is candidates` and
        # this cannot fire -- which is the point: offline does not care about
        # speed, so it must not be able to refuse on speed grounds the caller
        # never asked for. The budget is the one RTF knob offline honours, it
        # is opt-in and off by default, and this is the only sentence offline
        # is allowed to spend on RTF.
        if not pool:
            raise ValueError(
                f"no engine meets the offline RTF budget {request.rtf_budget} for "
                f"language {request.language!r}; offline ranks on quality alone, "
                "so raising or dropping the budget is the usual fix"
            )
    # Pure quality argmax over the entire pool (ties broken toward the faster
    # engine only when quality is identical). No Pareto gate: dropping a
    # higher-quality engine because its RTF is unknown would violate the
    # offline objective of caring about quality alone.
    argmax = _best_quality(pool, tie_break_faster=False)
    # The owner may have arbitrated this language himself. When he has, his
    # choice wins over the argmax — but never silently: the overridden
    # candidate and its score go into the justification, so a reader sees both
    # the decision and the evidence it set aside.
    chosen, overridden = argmax, None
    if request.respect_ratification:
        ratified = OFFLINE_RATIFIED_ENGINE.get((request.language or "").lower().split("-")[0])
        if ratified is not None and ratified != argmax.engine:
            match = next((c for c in pool if c.engine == ratified), None)
            if match is not None:
                chosen, overridden = match, argmax
    # The caller's optional patience cap is the ONLY reason RTF may be named in
    # an offline exposé, and then only as the caller's own constraint — never
    # as a property of the winner, which would read as a reason it won.
    budget_clause = (
        f" within the caller's optional RTF patience budget {request.rtf_budget}"
        if request.rtf_budget is not None
        else ""
    )
    if overridden is not None:
        justification = (
            f"offline: engine fixed by the owner's ratified choice for "
            f"{request.language!r} (as of {OFFLINE_RATIFIED_AS_OF}) — "
            f"'{chosen.engine}' (quality={chosen.quality:.3f} "
            f"[{chosen.quality_source}]). This OVERRIDES the quality argmax over "
            f"{len(pool)} candidate(s){budget_clause}, which was "
            f"'{overridden.engine}' (quality={overridden.quality:.3f} "
            f"[{overridden.quality_source}]): a decision, not a measurement. "
            f"Pass respect_ratification=False for the unarbitrated ranking. "
            f"mode=offline (whole-text synthesis; speed is not an objective "
            f"and no RTF enters this decision)."
        )
    else:
        justification = (
            f"offline: quality is the ONLY objective (no real-time constraint). "
            f"Maximise quality over {len(pool)} candidate(s){budget_clause}"
            f"; chose '{chosen.engine}' (quality={chosen.quality:.3f} "
            f"[{chosen.quality_source}]). "
            f"mode=offline (whole-text synthesis; speed is not an objective "
            f"and no RTF enters this decision)."
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
        # Deliberately None, whatever the catalogue knows about this engine's
        # speed. Offline does not rank on RTF, so an offline decision has no
        # RTF to report — carrying one invites a reader (or a dashboard) to
        # treat it as part of the reasoning. Structural, not cosmetic: the
        # number cannot leak because it is not there.
        mean_rtf=None,
        quality_source=chosen.quality_source,
        rtf_source="not_considered",
        confidence=_confidence(chosen, OFFLINE),
        justification=justification,
        candidates_considered=len(candidates),
        # No Pareto front is used offline (quality-only), so report 0.
        pareto_size=0,
        owner_ratified=overridden is not None,
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
