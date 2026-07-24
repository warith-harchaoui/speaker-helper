"""
Tests for the backend router (:mod:`speaker_helper.router`).

These cover the two operating conditions and their scientific contract:

* **online real-time** — the choice must keep up (``mean_rtf`` under the ceiling)
  and, among those that do, maximise quality; an infeasible request must raise.
* **offline** — quality is the *only* objective: the highest-quality engine wins
  even when a faster, lower-quality one is available and even when the winner's
  RTF is unmeasured.

Provenance (measured vs prior) and the ``apply`` → :class:`Settings` path are
checked too, since the router's value is a *justified*, actionable decision.
"""

from __future__ import annotations

import pytest

from speaker_helper.config import Settings
from speaker_helper.router import (
    OFFLINE,
    ONLINE_REALTIME,
    OperatingPoint,
    RouteRequest,
    default_operating_points,
    route,
    route_settings,
)


def _points() -> list[OperatingPoint]:
    """A small, explicit candidate set spanning the interesting cases."""
    # fast_ok: keeps up online, mid quality, both axes measured.
    # slow_good: best quality but too slow for real time, RTF measured.
    # unknown_best: highest quality, RTF never measured (offline-only candidate).
    return [
        OperatingPoint(
            "fast_ok",
            quality=0.75,
            mean_rtf=0.16,
            quality_source="measured_chrf",
            rtf_source="measured",
        ),
        OperatingPoint(
            "slow_good",
            quality=0.90,
            mean_rtf=1.30,
            quality_source="measured_chrf",
            rtf_source="measured",
        ),
        OperatingPoint(
            "unknown_best",
            quality=0.95,
            mean_rtf=None,
            quality_source="prior",
            rtf_source="unknown",
        ),
    ]


def test_online_picks_fastest_feasible_highest_quality() -> None:
    """Online: among engines that keep up (RTF<=ceiling), maximise quality."""
    d = route(RouteRequest(condition=ONLINE_REALTIME, rtf_ceiling=0.8), points=_points())
    # Only 'fast_ok' beats the 0.8 ceiling with measured timing; the higher
    # quality 'slow_good' (RTF 1.30) cannot sustain real time and is excluded.
    assert d.engine == "fast_ok"
    assert d.mode == "streaming"
    assert d.first_chunk_sentences == 1 and d.stream_concurrency == 1
    assert d.confidence == "high"  # both axes measured


def test_online_infeasible_raises() -> None:
    """Online: if nothing keeps up under the ceiling, the router refuses."""
    slow_only = [
        OperatingPoint(
            "slow", quality=0.9, mean_rtf=2.0, quality_source="measured_chrf", rtf_source="measured"
        )
    ]
    with pytest.raises(ValueError, match="online RTF ceiling"):
        route(RouteRequest(condition=ONLINE_REALTIME, rtf_ceiling=0.8), points=slow_only)


def test_online_requires_measured_rtf_by_default() -> None:
    """Online: an engine with unknown RTF is never assumed to keep up."""
    # 'unknown_best' has the top quality but no measured RTF; with the default
    # require_measured_rtf it must not be chosen (here it is the only candidate).
    with pytest.raises(ValueError):
        route(
            RouteRequest(condition=ONLINE_REALTIME),
            points=[OperatingPoint("unknown_best", quality=0.95, mean_rtf=None)],
        )


def test_offline_is_quality_only() -> None:
    """Offline: highest quality wins, even if its RTF is unmeasured."""
    d = route(RouteRequest(condition=OFFLINE), points=_points())
    # 'unknown_best' (0.95) beats 'slow_good' (0.90) and 'fast_ok' (0.75) purely
    # on quality — speed is disregarded, and unknown RTF is not disqualifying.
    assert d.engine == "unknown_best"
    assert d.mode == "offline"
    assert d.pareto_size == 0  # offline uses a pure quality argmax, no Pareto gate


def test_offline_ignores_speed_advantage() -> None:
    """Offline: a much faster but slightly worse engine still loses."""
    pts = [
        OperatingPoint(
            "blazing",
            quality=0.70,
            mean_rtf=0.05,
            quality_source="measured_chrf",
            rtf_source="measured",
        ),
        OperatingPoint(
            "best",
            quality=0.88,
            mean_rtf=0.90,
            quality_source="measured_chrf",
            rtf_source="measured",
        ),
    ]
    d = route(RouteRequest(condition=OFFLINE), points=pts)
    assert d.engine == "best"


def test_offline_rtf_budget_filters() -> None:
    """Offline: an explicit patience budget can still exclude the slowest."""
    pts = [
        OperatingPoint(
            "ok", quality=0.80, mean_rtf=0.5, quality_source="measured_chrf", rtf_source="measured"
        ),
        OperatingPoint(
            "too_slow",
            quality=0.99,
            mean_rtf=5.0,
            quality_source="measured_chrf",
            rtf_source="measured",
        ),
    ]
    d = route(RouteRequest(condition=OFFLINE, rtf_budget=1.0), points=pts)
    # 'too_slow' is dropped by the budget even though it is the highest quality.
    assert d.engine == "ok"


def test_quality_floor_applies() -> None:
    """A quality floor rejects candidates below it in both conditions."""
    with pytest.raises(ValueError):
        route(
            RouteRequest(condition=OFFLINE, quality_floor=0.99),
            points=_points(),  # top quality is 0.95 < 0.99 → nothing qualifies
        )


def test_unknown_condition_raises() -> None:
    """A typo'd condition fails loudly rather than silently mis-routing."""
    with pytest.raises(ValueError, match="unknown condition"):
        route(RouteRequest(condition="turbo"), points=_points())


def test_default_catalogue_has_measured_kokoro() -> None:
    """The fallback catalogue seeds kokoro with its measured native-MLX RTF."""
    pts = {p.engine: p for p in default_operating_points("fr")}
    assert "kokoro" in pts
    # kokoro's RTF is measured (from the fr profile), others are unknown.
    assert pts["kokoro"].rtf_source == "measured"
    assert pts["kokoro"].mean_rtf is not None
    assert any(p.rtf_source == "unknown" for p in pts.values())


def test_online_default_catalogue_routes_to_kokoro() -> None:
    """With no evidence given, online routing falls back to measured kokoro."""
    d = route(RouteRequest(condition=ONLINE_REALTIME, language="fr"))
    # kokoro is the only engine with a measured, real-time RTF in the catalogue.
    assert d.engine == "kokoro"
    assert d.mode == "streaming"


def test_decision_apply_sets_settings() -> None:
    """apply() folds the decision into Settings without touching connection cfg."""
    settings, decision = route_settings(OFFLINE, language="es", settings=Settings())
    assert isinstance(settings, Settings)
    assert settings.engine == decision.engine
    assert settings.mode == "offline"


def test_reports_take_precedence() -> None:
    """Measured EvalReport-like objects outrank the built-in catalogue."""

    class _Report:
        """Minimal duck-typed stand-in for an EvalReport."""

        def __init__(self, engine: str, quality: float, rtf: float) -> None:
            self.engine = engine
            self.quality = quality
            self.mean_rtf = rtf
            self.quality_source = "measured_chrf"
            self.backend = "voicebox"

    reports = [_Report("kokoro", 0.7, 0.2), _Report("chatterbox", 0.9, 0.5)]
    d = route(RouteRequest(condition=OFFLINE), reports=reports)
    # Offline quality-only → chatterbox (0.9) wins; provenance is measured.
    assert d.engine == "chatterbox"
    assert d.confidence == "high"
