"""
Tests for the evaluation layer: metrics, dataset, thresholds, runner, priors.

Pure units run everywhere against the deterministic mock backend, so the whole
gate is exercised in CI without a server. A ``@slow`` test runs the identical
gate against a live engine when one is reachable.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio

import pytest

from speaker_helper import MockEngine, Settings, Speaker
from speaker_helper.eval import (
    Thresholds,
    chrf,
    detect_anomalies,
    engine_quality_prior,
    load_dataset,
    pareto_front,
    percentile,
    run_eval,
    word_error_rate,
)
from speaker_helper.eval.metrics import normalize_text
from speaker_helper.types import AudioResult

# ----- metrics ------------------------------------------------------------


def test_percentile_interpolates() -> None:
    """percentile interpolates between samples and is 0 for empty input."""
    # The 50th percentile of 1..4 falls between 2 and 3 -> 2.5.
    assert percentile([1, 2, 3, 4], 50) == 2.5
    # No data has no percentile; the function degrades to 0.0.
    assert percentile([], 95) == 0.0


def test_normalize_text_strips_accents_and_punct() -> None:
    """normalize_text lowercases and removes accents and punctuation."""
    # Casefold, strip diacritics, and drop the trailing question mark.
    assert normalize_text("Où est le Café ?") == "ou est le cafe"


def test_wer_exact_and_substitution() -> None:
    """word_error_rate is 0 for identical text and scales with edits."""
    # Identical strings -> no errors.
    assert word_error_rate("le chat dort", "le chat dort") == 0.0
    # One substituted word out of three -> 1/3.
    assert abs(word_error_rate("le chat dort", "le chien dort") - 1 / 3) < 1e-9
    # Two empty strings are trivially equal.
    assert word_error_rate("", "") == 0.0
    # Missing the whole hypothesis -> a full error rate of 1.0.
    assert word_error_rate("bonjour", "") == 1.0


def test_chrf_bounds() -> None:
    """chrF is 1.0 for identical text, near 0 for disjoint, 1.0 for empties."""
    # Identical strings score the maximum.
    assert chrf("bonjour le monde", "bonjour le monde") == pytest.approx(1.0)
    # Sharing no characters keeps the score close to zero.
    assert chrf("bonjour", "xyz") < 0.2
    # Two empty strings are defined as a perfect match.
    assert chrf("", "") == 1.0


def _wav(duration_s: float, amplitude: float = 0.2) -> AudioResult:
    """Build a real AudioResult via the mock, then tweak duration/text."""
    # Amplitude drives clipping tests; text length drives the target duration.
    eng = MockEngine(Settings.from_mapping({"mock": {"amplitude": amplitude}}))
    return asyncio.run(eng.synthesize("x" * max(1, int(duration_s * 15))))


def test_detect_anomalies_clean() -> None:
    """A well-formed clip reports no anomalies."""
    # Two seconds at a safe amplitude should be flagged clean.
    assert detect_anomalies(_wav(2.0)) == []


def test_detect_anomalies_empty_audio() -> None:
    """Zero-length audio is flagged as empty_audio."""
    # No samples at all -> the empty_audio anomaly must fire.
    r = AudioResult(b"", 24000, 0.0, 0.1, "hello", "v", "fr")
    assert "empty_audio" in detect_anomalies(r)


def test_detect_anomalies_clipping() -> None:
    """Over-unity amplitude is flagged as clipping."""
    # Amplitude 1.5 pushes past full scale -> clipping is detected.
    assert "clipping" in detect_anomalies(_wav(1.0, amplitude=1.5))


def test_detect_anomalies_duration_too_short() -> None:
    """Too much text for the duration is flagged as duration_too_short."""
    # Lots of text, tiny duration -> chars/sec way above the band.
    r = AudioResult(b"", 24000, 0.2, 0.1, "x" * 200, "v", "fr")
    assert "duration_too_short" in detect_anomalies(r)


# ----- dataset + thresholds ----------------------------------------------


def test_builtin_dataset_loads() -> None:
    """The default dataset loads at least ten French cases with references."""
    cases = load_dataset()
    # A meaningful gate needs a non-trivial number of French cases.
    assert len(cases) >= 10
    assert all(c.language == "fr" and c.text for c in cases)
    # reference defaults to text when absent
    assert cases[0].reference == cases[0].text


def test_thresholds_defaults() -> None:
    """Default thresholds demand real-time speed and zero anomalies."""
    # The out-of-the-box gate is strict: RTF <= 1.0 and no anomalies allowed.
    t = Thresholds()
    assert t.max_p95_rtf == 1.0
    assert t.max_anomaly_rate == 0.0


# ----- priors + pareto ----------------------------------------------------


def test_engine_quality_prior_known_and_unknown() -> None:
    """Known engines use their calibrated prior; unknowns use a neutral one."""
    # A calibrated engine gets its measured prior.
    assert engine_quality_prior("kokoro") == 0.75
    # An unrecognised engine falls back to a neutral default prior.
    assert engine_quality_prior("totally-unknown") == 0.80


def test_pareto_front_selects_non_dominated() -> None:
    """pareto_front keeps non-dominated points and drops dominated ones."""

    class P:
        """Tiny point exposing quality and mean_rtf for the frontier test."""

        def __init__(self, q: float, r: float) -> None:
            """Store a (quality, mean_rtf) operating point."""
            self.quality, self.mean_rtf = q, r

    # a: high quality, slow-ish; b: lower quality but faster -> real trade-off,
    # neither dominates the other. c: dominated by a (same quality, slower).
    a, b, c = P(0.9, 0.3), P(0.6, 0.1), P(0.9, 0.5)
    front = pareto_front([a, b, c])
    # a and b are mutually non-dominated; c is strictly worse than a.
    assert a in front and b in front and c not in front


# ----- runner (end-to-end on the mock) -----------------------------------


def test_run_eval_mock_passes() -> None:
    """A default mock run passes the gate with a prior-sourced quality."""

    async def go() -> None:
        """Run the full gate over the mock and check the passing verdict."""
        async with Speaker(Settings.from_mapping({"backend": "mock"})) as spk:
            report = await run_eval(spk)
        # The mock is fast and clean, so every gate should be satisfied.
        assert report.passed
        assert report.n_cases >= 10
        assert report.mean_rtf < 1.0
        assert report.anomaly_rate == 0.0
        assert report.quality_source == "prior"

    asyncio.run(go())


def test_run_eval_flags_clipping_and_fails() -> None:
    """A clipping mock fails the gate on a 100% anomaly rate."""

    async def go() -> None:
        """Run the gate over a clipping mock and check the failure reason."""
        settings = Settings.from_mapping({"backend": "mock", "mock": {"amplitude": 1.5}})
        async with Speaker(settings) as spk:
            report = await run_eval(spk, load_dataset()[:3])
        # Every case clips, so the anomaly gate must fail the run.
        assert not report.passed
        assert report.anomaly_rate == 1.0
        assert any("anomaly rate" in f for f in report.failures)

    asyncio.run(go())


def test_run_eval_fails_when_rtf_over_threshold() -> None:
    """A slower-than-real-time mock fails the gate on the RTF threshold."""

    async def go() -> None:
        """Run the gate over a slow mock and check the RTF failure."""
        # Mock configured slower than real time -> RTF gate must fire.
        settings = Settings.from_mapping({"backend": "mock", "mock": {"rtf": 2.0}})
        async with Speaker(settings) as spk:
            report = await run_eval(spk, load_dataset()[:3])
        # RTF 2.0 exceeds the 1.0 bar, so the run must fail citing RTF.
        assert not report.passed
        assert any("RTF" in f for f in report.failures)

    asyncio.run(go())


def test_load_dataset_by_language() -> None:
    """Datasets exist for fr/en/es and load filtered to the chosen language."""
    from speaker_helper.eval import available_languages, load_dataset

    # The shipped languages must at least include fr/en/es.
    langs = available_languages()
    assert {"fr", "en", "es"} <= set(langs)
    # Requesting English yields only English cases.
    en = load_dataset(language="en")
    assert en and all(c.language == "en" for c in en)


def test_load_dataset_unknown_language_raises() -> None:
    """Requesting a language with no dataset raises a clear FileNotFoundError."""
    # An unsupported language has no bundled dataset to load.
    with pytest.raises(FileNotFoundError, match="no built-in dataset"):
        load_dataset(language="xx")


def test_run_multilang_eval_mock() -> None:
    """A multi-language mock run passes every language and renders a matrix."""
    from speaker_helper.eval import format_matrix, run_multilang_eval

    async def go() -> None:
        """Run all three languages over the mock and check the summary matrix."""
        reports = await run_multilang_eval(
            Settings.from_mapping({"backend": "mock"}), ["fr", "en", "es"]
        )
        # Each requested language yields its own passing, fast report.
        assert set(reports) == {"fr", "en", "es"}
        assert all(r.passed and r.mean_rtf < 1.0 for r in reports.values())
        # The rendered matrix lists the languages and an overall verdict.
        matrix = format_matrix(reports)
        assert "fr" in matrix and "en" in matrix and "verdict" in matrix

    asyncio.run(go())


def test_fidelity_round_trip_gates_on_wer_chrf() -> None:
    """A perfect transcriber clears the WER/chrF gate; a broken one fails it.

    This is the CI-runnable half of fidelity evaluation: a real synthesis →
    transcription round-trip needs a live engine and STT (neither is in CI), so
    here we inject deterministic stub transcribers to exercise the round-trip
    *pipeline* and the WER/chrF *threshold gating* end-to-end. The real round-trip
    runs locally via ``speaker-helper eval --transcribe`` (the ``stt`` extra).
    """
    from speaker_helper.eval import EvalCase, Thresholds

    # Fixed reference so a stub transcriber can reproduce it exactly (the mock
    # engine emits a tone, so the transcript cannot be recovered from audio).
    cases = [
        EvalCase(id=f"c{i}", text="Bonjour le monde.", language="fr", reference="bonjour le monde")
        for i in range(3)
    ]
    # Speed/anomaly bars are trivially met by the mock; WER/chrF are the only
    # discriminating gates in this scenario.
    thr = Thresholds(
        max_mean_rtf=1.0,
        max_p95_rtf=1.0,
        max_anomaly_rate=0.0,
        max_mean_wer=0.20,
        min_mean_chrf=0.75,
    )

    class _Perfect:
        """A transcriber that returns the exact reference (ideal round-trip)."""

        async def transcribe(self, wav_bytes: bytes, *, language: str) -> str:
            """Return the reference transcript verbatim."""
            return "bonjour le monde"

    class _Broken:
        """A transcriber that returns unrelated words (a failed round-trip)."""

        async def transcribe(self, wav_bytes: bytes, *, language: str) -> str:
            """Return text sharing nothing with the reference."""
            return "zzz zzz zzz"

    async def go() -> None:
        """Run the gate with a perfect and a broken transcriber and compare."""
        async with Speaker(Settings.from_mapping({"backend": "mock"})) as spk:
            good = await run_eval(spk, cases, thresholds=thr, transcriber=_Perfect())
            bad = await run_eval(spk, cases, thresholds=thr, transcriber=_Broken())
        # Perfect transcription: zero word errors, full chrF, gate satisfied.
        assert good.mean_wer == 0.0 and good.mean_chrf == 1.0
        assert good.passed
        # Broken transcription: WER climbs above the bar and the gate fails,
        # citing a fidelity reason (WER or chrF).
        assert bad.mean_wer is not None and bad.mean_wer > 0.20
        assert not bad.passed
        assert any("WER" in f or "chrF" in f for f in bad.failures)

    asyncio.run(go())


@pytest.mark.slow
async def test_run_eval_live_kokoro(live_port: int) -> None:
    """The identical gate runs against the real engine when reachable."""
    settings = Settings.from_mapping(
        {
            "backend": "voicebox",
            "engine": "kokoro",
            "language": "fr",
            "voicebox": {"port": live_port},
        }
    )
    # Act: run the same three-case gate against the live engine.
    async with Speaker(settings) as spk:
        report = await run_eval(spk, load_dataset()[:3])
    # Assert: all three cases ran fast and clean, matching the CI contract.
    assert report.n_cases == 3
    assert report.mean_rtf < 1.0  # faster than real time, the operating point
    assert report.anomaly_rate == 0.0
