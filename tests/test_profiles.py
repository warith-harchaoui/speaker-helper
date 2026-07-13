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
    assert profile_for("fr").language == "fr"
    assert profile_for("fr").engine == "kokoro"
    # unknown language still yields a usable default profile
    assert profile_for("xx").language == "xx"


def test_default_profiles_carry_measured_reference() -> None:
    # fr/en/es ship a reference GPU-MLX operating point (< real time)
    for lang in ("fr", "en", "es"):
        p = profile_for(lang)
        assert p.measured_rtf is not None and 0.0 < p.measured_rtf < 1.0
        assert p.measured_quality == 0.75
    # an untuned language has no measurement
    assert profile_for("it").measured_rtf is None


def test_profile_apply_sets_settings_fields() -> None:
    p = LanguageProfile(language="en", voice_id="am_adam", first_chunk_sentences=2)
    s = p.apply(Settings.from_mapping({"backend": "mock"}))
    assert s.language == "en"
    assert s.voice_id == "am_adam"
    assert s.first_chunk_sentences == 2
    assert s.backend == "mock"  # base settings preserved


def test_speaker_from_profile_applies_concurrency() -> None:
    p = LanguageProfile(language="es", stream_concurrency=3)
    spk = Speaker.from_profile(p, Settings.from_mapping({"backend": "mock"}))
    assert spk.settings.language == "es"
    assert spk.stream_concurrency == 3

    async def synth() -> None:
        async with spk:
            result = await spk.say("Hola mundo.")
        assert result.wav_bytes[:4] == b"RIFF"

    asyncio.run(synth())


def test_with_measurement_records_operating_point() -> None:
    class FakeReport:
        mean_rtf = 0.42
        quality = 0.75

    tuned = profile_for("fr").with_measurement(FakeReport())
    assert tuned.measured_rtf == 0.42
    assert tuned.measured_quality == 0.75


def test_tune_profiles_over_mock() -> None:
    async def go() -> None:
        profiles = await tune_profiles(
            Settings.from_mapping({"backend": "mock"}), ["fr", "en"])
        assert set(profiles) == {"fr", "en"}
        for p in profiles.values():
            assert p.measured_rtf is not None and p.measured_rtf < 1.0
            assert p.measured_quality is not None

    asyncio.run(go())
