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
    available_backends,
    create_engine,
    register_backend,
)
from speaker_helper.backends.kokoro import KokoroEngine


def test_registry_lists_builtin_backends() -> None:
    """Every in-tree backend is registered."""
    registered = available_backends()
    assert {"kokoro", "openvoice", "chatterbox", "mock"} <= set(registered)


def test_the_default_backend_needs_no_server() -> None:
    """An unconfigured Settings must produce a usable engine.

    The point of the whole in-process move: somebody who has installed this
    package and configured nothing should get a backend, not a connection
    error naming a port they have never heard of.
    """
    assert isinstance(create_engine(Settings()), KokoroEngine)


def test_create_engine_dispatches_on_backend() -> None:
    """The factory returns the class named by ``settings.backend``."""
    assert isinstance(create_engine(Settings.from_mapping({"backend": "mock"})), MockEngine)
    assert isinstance(create_engine(Settings.from_mapping({"backend": "kokoro"})), KokoroEngine)


def test_building_an_engine_imports_no_model() -> None:
    """Constructing a backend must not load several hundred megabytes.

    ``create_engine`` is called by the CLI before it knows whether the user
    asked for `--help`; a factory that imported the ONNX runtime would make
    every command pay for the one that synthesises.
    """
    import sys

    create_engine(Settings.from_mapping({"backend": "kokoro"}))
    assert "onnxruntime" not in sys.modules


def test_create_engine_rejects_unknown_backend() -> None:
    """An unknown backend name is a clear error, not a silent default."""
    # An unregistered name must raise rather than fall back silently.
    with pytest.raises(ValueError, match="unknown backend"):
        create_engine(Settings.from_mapping({"backend": "nope"}))


@pytest.mark.parametrize("backend", ["kokoro", "openvoice", "chatterbox", "mock"])
def test_every_backend_satisfies_the_protocol(backend: str) -> None:
    """Structural conformance, for every backend that ships.

    Parametrised rather than written out: a backend added to the registry and
    forgotten here would otherwise pass by not being tested.
    """
    assert isinstance(create_engine(Settings.from_mapping({"backend": backend})), TTSEngine)


def test_register_backend_is_pluggable() -> None:
    """A third-party backend can be registered and then created."""
    # Arrange: register a new backend name against an existing class.
    register_backend("mock2", MockEngine)
    # Assert: it becomes discoverable and constructable through the factory.
    assert "mock2" in available_backends()
    assert isinstance(create_engine(Settings.from_mapping({"backend": "mock2"})), MockEngine)


def test_mock_engine_is_deterministic_and_decodable() -> None:
    """The mock returns a real WAV whose RTF matches its configured knob."""
    # Arrange: a mock pinned to an RTF of 0.25.
    eng = MockEngine(Settings.from_mapping({"backend": "mock", "mock": {"rtf": 0.25}}))
    # Act: synthesise the same text twice to check determinism.
    a = asyncio.run(eng.synthesize("Bonjour tout le monde."))
    b = asyncio.run(eng.synthesize("Bonjour tout le monde."))
    # Assert: valid RIFF audio, positive duration, identical bytes, pinned RTF.
    assert a.wav_bytes[:4] == b"RIFF"
    assert a.duration_s > 0
    assert a.wav_bytes == b.wav_bytes  # deterministic
    assert abs(a.rtf - 0.25) < 1e-6


def test_mock_engine_rejects_empty_text() -> None:
    """Empty text is rejected the same way the real client rejects it."""
    # Blank input must fail validation, matching the real client's contract.
    eng = MockEngine(Settings.from_mapping({"backend": "mock"}))
    with pytest.raises(ValueError):
        asyncio.run(eng.synthesize("   "))


def test_speaker_accepts_injected_engine() -> None:
    """A ready engine can be injected, bypassing the factory (used in tests)."""
    # Arrange: hand a pre-built engine straight to the Speaker façade.
    eng = MockEngine(Settings.from_mapping({"backend": "mock"}))
    spk = Speaker(Settings.from_mapping({"backend": "mock"}), engine=eng)
    # Assert: the injected engine is used verbatim (and via its legacy alias).
    assert spk.engine is eng
    assert spk.client is eng  # backward-compatible alias
    # Act/Assert: synthesis through the façade still yields decodable audio.
    result = asyncio.run(spk.say("Salut."))
    assert result.wav_bytes[:4] == b"RIFF"
