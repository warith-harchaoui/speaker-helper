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
    """Write a short silent WAV to ``path`` and return its path string."""
    import numpy as np
    import soundfile as sf

    # Encode a run of silence so downstream helpers have a real file to read.
    sf.write(str(path), np.zeros(int(seconds * sr), dtype="float32"), sr)
    return str(path)


def test_require_missing_names_the_extra() -> None:
    """_require's ImportError names the pip extra that provides the module."""
    from speaker_helper.sources import _require

    # A missing optional dependency should point the user at the [youtube] extra.
    with pytest.raises(ImportError, match=r"\[youtube\]"):
        _require("definitely_not_a_real_module_xyz", "youtube")


def test_from_youtube_wraps_helper(monkeypatch) -> None:
    """from_youtube adapts the helper's download + metadata into a SourceAudio."""

    class FakeYT:
        """Stub of the youtube helper module used by from_youtube."""

        @staticmethod
        def download_audio(url, output_path=None, target_sample_rate=44100):
            """Return a fixed local audio path instead of downloading."""
            return "/tmp/audio.wav"

        @staticmethod
        def video_url_meta_data(url):
            """Return canned video metadata instead of hitting the network."""
            return {"title": "A talk"}

    # Arrange: make _require hand back the stub instead of the real module.
    monkeypatch.setattr("speaker_helper.sources._require", lambda *a, **k: FakeYT)
    # Act: wrap a YouTube URL into a source descriptor.
    src = from_youtube("https://youtu.be/abc")
    # Assert: origin, downloaded path, and title are threaded through.
    assert src.origin == "youtube"
    assert src.path == "/tmp/audio.wav"
    assert src.title == "A talk"


def test_from_podcast_without_enclosure_raises(monkeypatch) -> None:
    """from_podcast errors when the latest episode has no audio enclosure."""

    class FakePodcast:
        """Stub of the podcast helper returning an enclosure-less episode."""

        @staticmethod
        def latest_episode(url):
            """Return an episode whose enclosure URL is empty."""
            return {"title": "Ep", "enclosure_url": ""}

    # Arrange: swap in the stub feed reader.
    monkeypatch.setattr("speaker_helper.sources._require", lambda *a, **k: FakePodcast)
    # Act/Assert: a missing enclosure is a clear, actionable error.
    with pytest.raises(ValueError, match="no audio enclosure"):
        from_podcast("https://feed.example/rss")


def test_revoice_transcribes_then_speaks(tmp_path) -> None:
    """revoice transcribes the source and synthesises the transcript."""
    # Arrange: a real on-disk source file for the transcriber to consume.
    wav = _short_wav(tmp_path / "in.wav")

    def fake_transcriber(path: str, *, language: str) -> str:
        """Assert the expected path and return a fixed transcript."""
        # The source file path must reach the transcriber unchanged.
        assert path == wav
        return "Bonjour, ceci vient d'une source."

    async def go() -> None:
        """Run revoice end-to-end and check the synthesised output."""
        # Act: transcribe the source, then synthesise the transcript.
        async with Speaker(Settings.from_mapping({"backend": "mock"})) as spk:
            out = await revoice(SourceAudio(wav, "youtube"), spk, transcriber=fake_transcriber)
        # Assert: the transcript was spoken into decodable, non-empty audio.
        assert out.wav_bytes[:4] == b"RIFF"
        assert out.duration_s > 0

    asyncio.run(go())


def test_revoice_empty_transcript_raises(tmp_path) -> None:
    """revoice refuses to synthesise when the transcript is blank."""
    # Arrange: a real source file whose transcriber yields only whitespace.
    wav = _short_wav(tmp_path / "in.wav")

    async def go() -> None:
        """Drive revoice with a transcriber that returns empty text."""
        async with Speaker(Settings.from_mapping({"backend": "mock"})) as spk:
            await revoice(wav, spk, transcriber=lambda path, *, language: "   ")

    # Assert: an empty transcript is rejected before any synthesis.
    with pytest.raises(ValueError, match="no text to speak"):
        asyncio.run(go())
