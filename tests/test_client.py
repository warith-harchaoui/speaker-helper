"""
Tests for :mod:`speaker_helper.client` and the :class:`Speaker` façade.

Pure units run everywhere; the live synthesis test skips unless a Voicebox
engine is reachable.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import io

import pytest

from speaker_helper import Settings, Speaker, VoiceboxClient
from speaker_helper.client import _wav_stats
from speaker_helper.types import AudioResult


def test_client_base_url_from_settings() -> None:
    """The client derives its base URL from the configured host/port."""
    c = VoiceboxClient(Settings.from_mapping({"voicebox": {"port": 17600}}))
    assert c.base == "http://127.0.0.1:17600"
    assert c._profile_id is None


def test_audio_result_rtf() -> None:
    """RTF is compute/duration, and inf for silent audio."""
    r = AudioResult(b"", 24000, 2.0, 1.0, "x", "v", "fr")
    assert r.rtf == 0.5
    silent = AudioResult(b"", 24000, 0.0, 1.0, "x", "v", "fr")
    assert silent.rtf == float("inf")


def test_wav_stats_roundtrip() -> None:
    """_wav_stats reads sample rate and duration from WAV bytes."""
    np = pytest.importorskip("numpy")
    sf = pytest.importorskip("soundfile")
    buf = io.BytesIO()
    sf.write(buf, np.zeros(24000, dtype="float32"), 24000, format="WAV")
    sr, dur = _wav_stats(buf.getvalue())
    assert sr == 24000
    assert abs(dur - 1.0) < 1e-6


def test_synthesize_rejects_empty_text() -> None:
    """Empty text is rejected before any network call."""
    import asyncio

    c = VoiceboxClient(Settings.from_mapping({}))
    with pytest.raises(ValueError):
        asyncio.run(c.synthesize("   "))


@pytest.mark.slow
async def test_synthesize_live(live_port: int) -> None:
    """Live smoke test: real Voicebox returns decodable non-empty French audio."""
    settings = Settings.from_mapping(
        {"engine": "kokoro", "language": "fr", "voicebox": {"port": live_port}})
    async with Speaker(settings) as spk:
        result = await spk.say("Bonjour tout le monde.")
    assert result.duration_s > 0
    assert result.sample_rate > 0
    assert result.wav_bytes[:4] == b"RIFF"


@pytest.mark.slow
async def test_stream_live_reports_ttfa(live_port: int) -> None:
    """Live streaming yields ordered chunks; the first carries a TTFA."""
    settings = Settings.from_mapping(
        {"engine": "kokoro", "language": "fr", "voicebox": {"port": live_port}})
    seqs: list[int] = []
    ttfa: float | None = None
    async with Speaker(settings) as spk:
        async for chunk in spk.stream("Un. Deux. Trois."):
            seqs.append(chunk.seq)
            if chunk.ttfa_s is not None:
                ttfa = chunk.ttfa_s
    assert seqs == sorted(seqs)  # emission stays in order
    assert ttfa is not None and ttfa > 0
