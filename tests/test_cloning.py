"""
Tests for voice cloning: sample resolution, defaults, and the engine surface.

These run without a server (mock backend) and without ``vocal-helper``: the
bundled ref-malo transcript is committed, so default resolution needs no ASR.
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


def test_default_clone_resolves_to_ref_malo() -> None:
    """An empty clone config resolves to the bundled ref-malo reference."""
    samples = resolve_samples({})
    assert len(samples) == 1
    assert samples[0].audio == str(DEFAULT_CLONE_AUDIO)
    # the committed transcript is loaded as the reference text
    assert samples[0].reference_text.lower().startswith("je m'appelle malorie")


def test_clone_name_default_and_override() -> None:
    assert clone_name({}) == "ref-malo"
    assert clone_name({"name": "malo"}) == "malo"


def test_resolve_samples_explicit_list() -> None:
    cfg = {"samples": [{"audio": "a.wav", "reference_text": "bonjour"}]}
    samples = resolve_samples(cfg)
    assert samples[0].audio == "a.wav"
    assert samples[0].reference_text == "bonjour"


def test_resolve_samples_rejects_sample_without_audio() -> None:
    with pytest.raises(ValueError, match="missing 'audio'"):
        resolve_samples({"samples": [{"reference_text": "x"}]})


def test_voice_sample_reads_bytes_and_filename(tmp_path) -> None:
    p = tmp_path / "ref.wav"
    p.write_bytes(b"RIFFabcd")
    s = VoiceSample(audio=str(p), reference_text="hi")
    assert s.read_bytes() == b"RIFFabcd"
    assert s.filename() == "ref.wav"
    assert VoiceSample(audio=b"RIFF", reference_text="hi").filename() == "sample.wav"


def test_prepare_samples_transcribes_when_missing(monkeypatch) -> None:
    """A short sample without a transcript is filled via the transcriber."""
    calls: list[bytes] = []

    def fake_transcribe(audio: bytes, *, language: str = "fr") -> str:
        calls.append(audio)
        return "texte transcrit"

    monkeypatch.setattr(
        "speaker_helper.transcription.transcribe_bytes", fake_transcribe, raising=True)
    out = prepare_samples([VoiceSample(audio=_short_wav(), reference_text="")])
    assert out[0].reference_text == "texte transcrit"
    assert calls  # the transcriber was actually invoked


def test_prepare_samples_keeps_existing_transcript() -> None:
    """A short sample that already has a transcript needs no ASR."""
    out = prepare_samples([VoiceSample(audio=_short_wav(), reference_text="deja la")])
    assert out[0].reference_text == "deja la"


def test_prepare_samples_trims_long_audio_and_retranscribes(monkeypatch) -> None:
    """Audio over the cap is trimmed, and its transcript is re-derived."""
    def fake_transcribe(audio: bytes, *, language: str = "fr") -> str:
        return "trimmed transcript"

    monkeypatch.setattr(
        "speaker_helper.transcription.transcribe_bytes", fake_transcribe, raising=True)
    # 5 s of audio, cap at 2 s -> trimmed even though a transcript was supplied.
    long_sample = VoiceSample(audio=_short_wav(seconds=5.0), reference_text="ignored")
    out = prepare_samples([long_sample], max_seconds=2.0)
    assert out[0].reference_text == "trimmed transcript"
    # the returned audio really is ~2 s, not 5 s
    import io

    import soundfile as sf
    info = sf.info(io.BytesIO(out[0].audio))
    assert info.frames / info.samplerate < 3.0


def test_mock_engine_clone_is_idempotent_stub() -> None:
    eng = MockEngine(Settings.from_mapping({"backend": "mock"}))
    vid = asyncio.run(eng.clone_voice("malo", [VoiceSample(b"RIFF", "hi")]))
    assert vid == "cloned-malo"


def test_mock_engine_clone_rejects_no_samples() -> None:
    eng = MockEngine(Settings.from_mapping({"backend": "mock"}))
    with pytest.raises(ValueError):
        asyncio.run(eng.clone_voice("malo", []))


def test_speaker_clone_voice_delegates_to_engine() -> None:
    """Speaker.clone_voice resolves defaults and calls the engine."""
    spk = Speaker(Settings.from_mapping({"backend": "mock", "clone": {"name": "malo"}}))
    vid = asyncio.run(spk.clone_voice(samples=[VoiceSample(b"RIFF", "hi")]))
    assert vid == "cloned-malo"
