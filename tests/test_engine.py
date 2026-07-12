"""
Tests for the backend abstraction: registry, factory, and the mock engine.

These run everywhere (no server needed) and pin the contract the whole package
relies on: any backend is reachable only through the :class:`TTSEngine`
protocol, and the mock is a deterministic stand-in for a real engine.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio

import pytest

from speaker_helper import (
    MockEngine,
    Settings,
    Speaker,
    TTSEngine,
    VoiceboxClient,
    available_backends,
    create_engine,
    register_backend,
)


def test_registry_lists_builtin_backends() -> None:
    """Both in-tree backends are registered."""
    assert "mock" in available_backends()
    assert "voicebox" in available_backends()


def test_create_engine_dispatches_on_backend() -> None:
    """The factory returns the class named by ``settings.backend``."""
    assert isinstance(create_engine(Settings.from_mapping({"backend": "mock"})), MockEngine)
    assert isinstance(
        create_engine(Settings.from_mapping({"backend": "voicebox"})), VoiceboxClient)


def test_create_engine_rejects_unknown_backend() -> None:
    """An unknown backend name is a clear error, not a silent default."""
    with pytest.raises(ValueError, match="unknown backend"):
        create_engine(Settings.from_mapping({"backend": "nope"}))


def test_both_backends_satisfy_the_protocol() -> None:
    """Voicebox and mock both structurally implement TTSEngine."""
    assert isinstance(create_engine(Settings.from_mapping({"backend": "mock"})), TTSEngine)
    assert isinstance(create_engine(Settings.from_mapping({"backend": "voicebox"})), TTSEngine)


def test_register_backend_is_pluggable() -> None:
    """A third-party backend can be registered and then created."""
    register_backend("mock2", MockEngine)
    assert "mock2" in available_backends()
    assert isinstance(create_engine(Settings.from_mapping({"backend": "mock2"})), MockEngine)


def test_mock_engine_is_deterministic_and_decodable() -> None:
    """The mock returns a real WAV whose RTF matches its configured knob."""
    eng = MockEngine(Settings.from_mapping({"backend": "mock", "mock": {"rtf": 0.25}}))
    a = asyncio.run(eng.synthesize("Bonjour tout le monde."))
    b = asyncio.run(eng.synthesize("Bonjour tout le monde."))
    assert a.wav_bytes[:4] == b"RIFF"
    assert a.duration_s > 0
    assert a.wav_bytes == b.wav_bytes  # deterministic
    assert abs(a.rtf - 0.25) < 1e-6


def test_mock_engine_rejects_empty_text() -> None:
    """Empty text is rejected the same way the real client rejects it."""
    eng = MockEngine(Settings.from_mapping({"backend": "mock"}))
    with pytest.raises(ValueError):
        asyncio.run(eng.synthesize("   "))


def test_speaker_accepts_injected_engine() -> None:
    """A ready engine can be injected, bypassing the factory (used in tests)."""
    eng = MockEngine(Settings.from_mapping({"backend": "mock"}))
    spk = Speaker(Settings.from_mapping({"backend": "mock"}), engine=eng)
    assert spk.engine is eng
    assert spk.client is eng  # backward-compatible alias
    result = asyncio.run(spk.say("Salut."))
    assert result.wav_bytes[:4] == b"RIFF"
