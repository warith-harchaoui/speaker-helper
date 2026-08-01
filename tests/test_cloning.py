"""
Tests for voice cloning: sample resolution, defaults, and the engine surface.

These run without a server (mock backend) and without ``vocal-helper``: the
bundled reference transcript is committed, so default resolution needs no ASR.
Auto-transcription is covered by monkeypatching the transcription helper.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio

import pytest

from speaker_helper import MockEngine, Settings, Speaker, VoiceSample
from speaker_helper.cloning import (
    DEFAULT_CLONE_AUDIO,
    clone_name,
    prepare_samples,
    resolve_samples,
)


def _short_wav(seconds: float = 1.0, sr: int = 16000) -> bytes:
    """Return a real, decodable WAV payload of the given length."""
    import io

    import numpy as np
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, np.zeros(int(seconds * sr), dtype="float32"), sr, format="WAV")
    return buf.getvalue()


def test_default_clone_resolves_to_bundled_reference() -> None:
    """An empty clone config resolves to the bundled reference voice."""
    # Act: resolve with no config at all.
    samples = resolve_samples({})
    # Assert: exactly the one bundled reference audio is selected.
    assert len(samples) == 1
    assert samples[0].audio == str(DEFAULT_CLONE_AUDIO)
    # the committed transcript is loaded as the reference text
    assert samples[0].reference_text.lower().startswith("elle voyait l'avenir")


def test_clone_name_default_and_override() -> None:
    """Clone name defaults to ref-fr-female and honours an explicit override."""
    # Empty config -> the bundled default name.
    assert clone_name({}) == "ref-fr-female"
    # An explicit name overrides the default.
    assert clone_name({"name": "my-voice"}) == "my-voice"


def test_resolve_samples_explicit_list() -> None:
    """An explicit sample list is passed through verbatim."""
    # Arrange: one fully specified sample entry.
    cfg = {"samples": [{"audio": "a.wav", "reference_text": "bonjour"}]}
    # Act/Assert: audio path and transcript survive resolution unchanged.
    samples = resolve_samples(cfg)
    assert samples[0].audio == "a.wav"
    assert samples[0].reference_text == "bonjour"


def test_resolve_samples_rejects_sample_without_audio() -> None:
    """A sample entry lacking an 'audio' key is a clear error."""
    # A transcript alone is not enough; audio is mandatory.
    with pytest.raises(ValueError, match="missing 'audio'"):
        resolve_samples({"samples": [{"reference_text": "x"}]})


def test_voice_sample_reads_bytes_and_filename(tmp_path) -> None:
    """VoiceSample reads file bytes and derives a sensible filename."""
    # Arrange: write a tiny file the sample will point at.
    p = tmp_path / "ref.wav"
    p.write_bytes(b"RIFFabcd")
    # Act/Assert: a path-backed sample reads its bytes and keeps its name.
    s = VoiceSample(audio=str(p), reference_text="hi")
    assert s.read_bytes() == b"RIFFabcd"
    assert s.filename() == "ref.wav"
    # A bytes-backed sample has no path, so it falls back to a default name.
    assert VoiceSample(audio=b"RIFF", reference_text="hi").filename() == "sample.wav"


def test_prepare_samples_transcribes_when_missing(monkeypatch) -> None:
    """A short sample without a transcript is filled via the transcriber."""
    # Record every audio blob the stub transcriber receives.
    calls: list[bytes] = []

    def fake_transcribe(audio: bytes, *, language: str = "fr") -> str:
        """Stub transcriber that records its input and returns fixed text."""
        calls.append(audio)
        return "texte transcrit"

    # Arrange: swap in the stub so no real ASR runs.
    monkeypatch.setattr(
        "speaker_helper.transcription.transcribe_bytes", fake_transcribe, raising=True
    )
    # Act: prepare a sample whose transcript is empty.
    out = prepare_samples([VoiceSample(audio=_short_wav(), reference_text="")])
    # Assert: the missing transcript was filled from the stub's output.
    assert out[0].reference_text == "texte transcrit"
    assert calls  # the transcriber was actually invoked


def test_prepare_samples_keeps_existing_transcript() -> None:
    """A short sample that already has a transcript needs no ASR."""
    # An in-range sample with a transcript is returned untouched.
    out = prepare_samples([VoiceSample(audio=_short_wav(), reference_text="deja la")])
    assert out[0].reference_text == "deja la"


def test_prepare_samples_trims_long_audio_and_retranscribes(monkeypatch) -> None:
    """Audio over the cap is trimmed, and its transcript is re-derived."""

    def fake_transcribe(audio: bytes, *, language: str = "fr") -> str:
        """Stub transcriber returning fixed text for the trimmed clip."""
        return "trimmed transcript"

    # Arrange: swap in the stub so trimming re-transcription is deterministic.
    monkeypatch.setattr(
        "speaker_helper.transcription.transcribe_bytes", fake_transcribe, raising=True
    )
    # 5 s of audio, cap at 2 s -> trimmed even though a transcript was supplied.
    long_sample = VoiceSample(audio=_short_wav(seconds=5.0), reference_text="ignored")
    # Act: prepare with a 2 s cap, forcing a trim and re-transcription.
    out = prepare_samples([long_sample], max_seconds=2.0)
    # Assert: the supplied transcript was discarded for the re-derived one.
    assert out[0].reference_text == "trimmed transcript"
    # the returned audio really is ~2 s, not 5 s
    import io

    import soundfile as sf

    # Decode the returned bytes and confirm the duration was actually shortened.
    info = sf.info(io.BytesIO(out[0].audio))
    assert info.frames / info.samplerate < 3.0


def test_mock_engine_clone_is_idempotent_stub() -> None:
    """The mock's clone_voice returns a stable, name-derived voice id."""
    # The mock does no real cloning; it echoes a deterministic id.
    eng = MockEngine(Settings.from_mapping({"backend": "mock"}))
    vid = asyncio.run(eng.clone_voice("my-voice", [VoiceSample(b"RIFF", "hi")]))
    assert vid == "cloned-my-voice"


def test_mock_engine_clone_rejects_no_samples() -> None:
    """Cloning with no reference samples is rejected."""
    # At least one sample is required to clone a voice.
    eng = MockEngine(Settings.from_mapping({"backend": "mock"}))
    with pytest.raises(ValueError):
        asyncio.run(eng.clone_voice("my-voice", []))


def test_speaker_clone_voice_delegates_to_engine() -> None:
    """Speaker.clone_voice resolves defaults and calls the engine."""
    # Arrange: a Speaker whose clone config names the target voice.
    spk = Speaker(Settings.from_mapping({"backend": "mock", "clone": {"name": "my-voice"}}))
    # Act/Assert: the façade delegates to the engine's deterministic id.
    vid = asyncio.run(spk.clone_voice(samples=[VoiceSample(b"RIFF", "hi")]))
    assert vid == "cloned-my-voice"
