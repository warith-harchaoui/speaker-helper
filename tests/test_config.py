"""
Tests for :mod:`speaker_helper.config` — loading, env expansion, overrides.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

from speaker_helper.config import Settings


def test_defaults_need_no_server() -> None:
    """An empty mapping must produce a configuration that can synthesise.

    This test used to assert a hostname and a port. That it no longer can is
    the change: the default backend runs in this process, so there is nothing
    to point a URL at.
    """
    s = Settings.from_mapping({})
    assert s.backend == "kokoro"
    assert s.voice == ""  # empty means "detect the language and pick"
    assert not hasattr(s, "base_url")


def test_yaml_overrides_and_unknown_keys_are_ignored() -> None:
    """Top-level YAML keys populate the dataclass; unknown keys are dropped."""
    s = Settings.from_yaml_text("backend: mock\nlanguage: fr\nbogus: 1")
    assert s.backend == "mock"
    assert s.language == "fr"


def test_a_settings_file_from_the_rest_era_still_loads() -> None:
    """A ``voicebox:`` section must be ignored, not refused.

    Those files are on disk on real machines. Refusing to load one would be a
    worse welcome than ignoring a key that now means nothing, and the keys
    beside it are still good.
    """
    s = Settings.from_yaml_text("voicebox: {port: 17600}\nlanguage: fr")
    assert s.language == "fr"
    assert s.backend == "kokoro"


def test_voice_id_still_names_the_voice() -> None:
    """The old spelling has to keep working, or it silently picks the wrong voice."""
    s = Settings.from_mapping({"voice_id": "ff_siwis"})
    assert s.voice == "ff_siwis"
    # And the new spelling wins when both are given, rather than the later one.
    s = Settings.from_mapping({"voice_id": "af_heart", "voice": "ff_siwis"})
    assert s.voice == "ff_siwis"


def test_env_var_expansion(monkeypatch) -> None:
    """``${VAR}`` in YAML expands from the environment at load time."""
    monkeypatch.setenv("SH_VOICE", "ff_siwis")
    s = Settings.from_yaml_text("voice: '${SH_VOICE}'")
    assert s.voice == "ff_siwis"


def test_env_overrides_take_precedence(monkeypatch) -> None:
    """SPEAKER_HELPER_* env variables override file/default values."""
    # Arrange: set env overrides that conflict with the mapping below.
    monkeypatch.setenv("SPEAKER_HELPER_VOICE", "ff_siwis")
    monkeypatch.setenv("SPEAKER_HELPER_ENGINE", "chatterbox")
    # Act: load with explicit mapping values the env should trump.
    s = Settings.from_mapping({"voice": "af_heart", "engine": "kokoro"})
    # Assert: env wins over the mapping for both fields.
    assert s.voice == "ff_siwis"
    assert s.engine == "chatterbox"
