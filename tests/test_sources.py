"""
Tests for speech-to-speech sources.

The third-party source helpers (youtube/podcast/capture) and the transcriber are
stubbed, so these run offline with no network, microphone, or vocal-helper —
they pin the orchestration, not the heavy dependencies.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio

import pytest

from speaker_helper import Settings, Speaker
from speaker_helper.sources import SourceAudio, from_podcast, from_youtube, revoice


def _short_wav(path, seconds: float = 1.0, sr: int = 16000) -> str:
    import numpy as np
    import soundfile as sf

    sf.write(str(path), np.zeros(int(seconds * sr), dtype="float32"), sr)
    return str(path)


def test_require_missing_names_the_extra() -> None:
    from speaker_helper.sources import _require

    with pytest.raises(ImportError, match=r"\[youtube\]"):
        _require("definitely_not_a_real_module_xyz", "youtube")


def test_from_youtube_wraps_helper(monkeypatch) -> None:
    class FakeYT:
        @staticmethod
        def download_audio(url, output_path=None, target_sample_rate=44100):
            return "/tmp/audio.wav"

        @staticmethod
        def video_url_meta_data(url):
            return {"title": "A talk"}

    monkeypatch.setattr("speaker_helper.sources._require", lambda *a, **k: FakeYT)
    src = from_youtube("https://youtu.be/abc")
    assert src.origin == "youtube"
    assert src.path == "/tmp/audio.wav"
    assert src.title == "A talk"


def test_from_podcast_without_enclosure_raises(monkeypatch) -> None:
    class FakePodcast:
        @staticmethod
        def latest_episode(url):
            return {"title": "Ep", "enclosure_url": ""}

    monkeypatch.setattr("speaker_helper.sources._require", lambda *a, **k: FakePodcast)
    with pytest.raises(ValueError, match="no audio enclosure"):
        from_podcast("https://feed.example/rss")


def test_revoice_transcribes_then_speaks(tmp_path) -> None:
    """revoice transcribes the source and synthesises the transcript."""
    wav = _short_wav(tmp_path / "in.wav")

    def fake_transcriber(path: str, *, language: str) -> str:
        assert path == wav
        return "Bonjour, ceci vient d'une source."

    async def go() -> None:
        async with Speaker(Settings.from_mapping({"backend": "mock"})) as spk:
            out = await revoice(SourceAudio(wav, "youtube"), spk, transcriber=fake_transcriber)
        assert out.wav_bytes[:4] == b"RIFF"
        assert out.duration_s > 0

    asyncio.run(go())


def test_revoice_empty_transcript_raises(tmp_path) -> None:
    wav = _short_wav(tmp_path / "in.wav")

    async def go() -> None:
        async with Speaker(Settings.from_mapping({"backend": "mock"})) as spk:
            await revoice(wav, spk, transcriber=lambda path, *, language: "   ")

    with pytest.raises(ValueError, match="no text to speak"):
        asyncio.run(go())
