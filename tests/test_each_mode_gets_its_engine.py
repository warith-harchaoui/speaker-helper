"""
The owner's matrix, as each surface actually resolves it.

Four cells — local free offline, local free streaming, cloud paid offline,
cloud paid streaming — and one transverse rule: a female voice in every one.
The router already answers the question when asked; what is pinned here is
that the *default paths* answer it the same way. That was not true before
2026-11-04: ``synth --stream`` and ``POST /synth/stream`` under the default
``mode: offline`` resolved ``auto`` to chatterbox and streamed two to five
times slower than real time.

Nothing here loads a model.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import pytest

from speaker_helper.config import Settings
from speaker_helper.engine import for_streaming, resolve_auto


def _resolved(**mapping: object) -> str:
    return resolve_auto(Settings.from_mapping(mapping)).backend


# ── Local, free ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("language", ["fr", "en", "es", "de"])
def test_offline_goes_to_chatterbox_in_every_language(language: str) -> None:
    """Quality only offline; chatterbox picks Turbo or Multilingual itself."""
    assert _resolved(backend="auto", mode="offline", language=language) == "chatterbox"


@pytest.mark.parametrize("language", ["fr", "en"])
def test_streaming_goes_to_kokoro(language: str) -> None:
    """The one ranked engine that keeps well under the real-time ceiling."""
    assert _resolved(backend="auto", mode="streaming", language=language) == "kokoro"


@pytest.mark.parametrize("language", ["fr", "en"])
def test_a_streaming_call_under_an_offline_config_still_streams_kokoro(language: str) -> None:
    """``synth --stream`` with the default ``mode: offline`` must not stream chatterbox."""
    offline = Settings.from_mapping({"backend": "auto", "language": language})
    assert offline.mode == "offline"
    assert resolve_auto(for_streaming(offline)).backend == "kokoro"


def test_a_named_local_backend_is_not_rebuilt_for_streaming() -> None:
    """Same engine in both modes: no second copy of its weights."""
    named = Settings.from_mapping({"backend": "chatterbox"})
    assert for_streaming(named) is named


def test_the_new_candidates_never_take_a_default_route() -> None:
    """audio8 and qwen3tts are for the owner's ear, not for `auto`."""
    for mode in ("offline", "streaming"):
        for language in ("fr", "en", "es"):
            assert _resolved(backend="auto", mode=mode, language=language) not in {
                "audio8",
                "qwen3tts",
                "elevenlabs",
            }


# ── Cloud, paid ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("mode", "model"), [("offline", "eleven_v4"), ("streaming", "eleven_v4_turbo")]
)
def test_the_cloud_model_follows_the_mode(mode: str, model: str) -> None:
    """Quality model offline, low-latency model streaming."""
    from speaker_helper.backends.elevenlabs import ElevenLabsEngine

    engine = ElevenLabsEngine(Settings.from_mapping({"backend": "elevenlabs", "mode": mode}))
    assert engine._model == model


def test_a_streaming_call_under_an_offline_config_uses_the_cloud_streaming_model() -> None:
    """``for_streaming`` reaches the cloud cell too."""
    from speaker_helper.backends.elevenlabs import ElevenLabsEngine

    offline = Settings.from_mapping({"backend": "elevenlabs"})
    assert ElevenLabsEngine(for_streaming(offline))._model == "eleven_v4_turbo"


# ── A female voice, every cell ─────────────────────────────────────────────


def test_every_kokoro_default_voice_is_female() -> None:
    """Kokoro ids encode gender in their second letter (``af_``, ``ff_``…)."""
    from speaker_helper.backends.kokoro import DEFAULT_VOICE_BY_LANG, FALLBACK_VOICE

    for language, voice in {**DEFAULT_VOICE_BY_LANG, "*": FALLBACK_VOICE}.items():
        assert voice[1] == "f", (language, voice)


@pytest.mark.parametrize("backend", ["chatterbox", "audio8", "qwen3tts", "elevenlabs"])
def test_every_cloning_or_cloud_default_is_a_female_voice(
    backend: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without configuration each of these names a female voice."""
    import asyncio

    # No key: the cloud backend names its default instead of calling the service.
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    from speaker_helper.engine import create_engine

    engine = create_engine(Settings.from_mapping({"backend": backend, "language": "fr"}))
    voices = asyncio.run(engine.list_voices()).voices
    assert voices and voices[0].gender == "female", (backend, voices)
