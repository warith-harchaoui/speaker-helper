"""
Tests for :mod:`speaker_helper.config` — loading, env expansion, overrides.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

from speaker_helper.config import Settings


def test_defaults_and_base_url() -> None:
    """Defaults give the native Voicebox port and a well-formed base URL."""
    # Arrange/Act: build settings from an empty mapping (pure defaults).
    s = Settings.from_mapping({})
    # Assert: the native port, its derived base URL, and the default engine.
    assert s.voicebox.port == 17493
    assert s.base_url == "http://127.0.0.1:17493"
    assert s.engine == "kokoro"


def test_yaml_overrides_nested() -> None:
    """Nested YAML keys populate the dataclasses; unknown keys are ignored."""
    # Act: load YAML with a nested override plus an unrecognised key.
    s = Settings.from_yaml_text("voicebox: {port: 17600}\nlanguage: fr\nbogus: 1")
    # Assert: nested and top-level fields land; the "bogus" key is dropped.
    assert s.voicebox.port == 17600
    assert s.language == "fr"


def test_env_var_expansion(monkeypatch) -> None:
    """``${VAR}`` in YAML expands from the environment at load time."""
    # Arrange: publish the variable the YAML template references.
    monkeypatch.setenv("VB_HOST", "example.local")
    # Act: load YAML that interpolates ${VB_HOST}.
    s = Settings.from_yaml_text("voicebox: {host: '${VB_HOST}'}")
    # Assert: the placeholder resolved to the environment value.
    assert s.voicebox.host == "example.local"


def test_env_overrides_take_precedence(monkeypatch) -> None:
    """SPEAKER_HELPER_* env variables override file/default values."""
    # Arrange: set env overrides that conflict with the mapping below.
    monkeypatch.setenv("SPEAKER_HELPER_VOICEBOX_PORT", "9999")
    monkeypatch.setenv("SPEAKER_HELPER_ENGINE", "chatterbox")
    # Act: load with explicit mapping values the env should trump.
    s = Settings.from_mapping({"voicebox": {"port": 17600}, "engine": "kokoro"})
    # Assert: env wins over the mapping for both fields.
    assert s.voicebox.port == 9999
    assert s.engine == "chatterbox"
