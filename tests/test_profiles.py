"""
Tests for per-language operating profiles.

Run against the deterministic mock backend — no server, no network.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio

from speaker_helper import LanguageProfile, Settings, Speaker, profile_for, tune_profiles


def test_profile_for_known_and_unknown() -> None:
    """profile_for returns tuned defaults for known langs, a fallback else."""
    # A known language carries its language tag and default engine.
    assert profile_for("fr").language == "fr"
    assert profile_for("fr").engine == "kokoro"
    # unknown language still yields a usable default profile
    assert profile_for("xx").language == "xx"


def test_default_profiles_carry_measured_reference() -> None:
    """Shipped fr/en/es profiles carry a sub-real-time reference measurement."""
    # fr/en/es ship a reference GPU-MLX operating point (< real time) and a
    # quality score in [0, 1].
    for lang in ("fr", "en", "es"):
        p = profile_for(lang)
        assert p.measured_rtf is not None and 0.0 < p.measured_rtf < 1.0
        assert p.measured_quality is not None and 0.0 < p.measured_quality <= 1.0
    # fr/en/es quality are real UTMOSv2 MOS scores (kokoro: en 0.65 > fr 0.59 > es 0.55).
    assert profile_for("fr").measured_quality == 0.59
    assert profile_for("en").measured_quality == 0.65
    assert profile_for("es").measured_quality == 0.55
    # an untuned language has no measurement
    assert profile_for("it").measured_rtf is None


def test_profile_apply_sets_settings_fields() -> None:
    """Applying a profile overlays its fields onto base settings."""
    # Arrange: a profile that sets language, voice, and chunking.
    p = LanguageProfile(language="en", voice_id="am_adam", first_chunk_sentences=2)
    # Act: overlay it onto mock-backend settings.
    s = p.apply(Settings.from_mapping({"backend": "mock"}))
    # Assert: profile fields land while unrelated base settings survive.
    assert s.language == "en"
    assert s.voice_id == "am_adam"
    assert s.first_chunk_sentences == 2
    assert s.backend == "mock"  # base settings preserved


def test_speaker_from_profile_applies_concurrency() -> None:
    """Speaker.from_profile honours the profile's language and concurrency."""
    # Arrange: build a Speaker from a profile that pins stream concurrency.
    p = LanguageProfile(language="es", stream_concurrency=3)
    spk = Speaker.from_profile(p, Settings.from_mapping({"backend": "mock"}))
    # Assert: language and concurrency carried onto the Speaker.
    assert spk.settings.language == "es"
    assert spk.stream_concurrency == 3

    async def synth() -> None:
        """Synthesise once to confirm the configured Speaker works."""
        async with spk:
            result = await spk.say("Hola mundo.")
        assert result.wav_bytes[:4] == b"RIFF"

    asyncio.run(synth())


def test_with_measurement_records_operating_point() -> None:
    """with_measurement copies an eval report's RTF/quality onto the profile."""

    class FakeReport:
        """Minimal eval-report stand-in exposing mean_rtf and quality."""

        mean_rtf = 0.42
        quality = 0.75

    # Act: fold the fake measurement into the fr profile.
    tuned = profile_for("fr").with_measurement(FakeReport())
    # Assert: the recorded operating point mirrors the report.
    assert tuned.measured_rtf == 0.42
    assert tuned.measured_quality == 0.75


def test_tune_profiles_over_mock() -> None:
    """tune_profiles measures each requested language against the mock."""

    async def go() -> None:
        """Tune fr/en over the mock and check every profile got measured."""
        profiles = await tune_profiles(Settings.from_mapping({"backend": "mock"}), ["fr", "en"])
        assert set(profiles) == {"fr", "en"}
        # Every tuned profile must carry a sub-real-time RTF and a quality.
        for p in profiles.values():
            assert p.measured_rtf is not None and p.measured_rtf < 1.0
            assert p.measured_quality is not None

    asyncio.run(go())
