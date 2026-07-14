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
    # Arrange/Act: build a client from a port-only override.
    c = VoiceboxClient(Settings.from_mapping({"voicebox": {"port": 17600}}))
    # Assert: host/port compose into the base URL; no profile is bound yet.
    assert c.base == "http://127.0.0.1:17600"
    assert c._profile_id is None


def test_audio_result_rtf() -> None:
    """RTF is compute/duration, and inf for silent audio."""
    # 1.0 s compute over 2.0 s of audio -> RTF 0.5 (faster than real time).
    r = AudioResult(b"", 24000, 2.0, 1.0, "x", "v", "fr")
    assert r.rtf == 0.5
    # Zero-duration audio has no real-time baseline -> RTF is infinite.
    silent = AudioResult(b"", 24000, 0.0, 1.0, "x", "v", "fr")
    assert silent.rtf == float("inf")


def test_wav_stats_roundtrip() -> None:
    """_wav_stats reads sample rate and duration from WAV bytes."""
    # Skip cleanly when the audio stack is unavailable.
    np = pytest.importorskip("numpy")
    sf = pytest.importorskip("soundfile")
    # Arrange: encode exactly one second of silence at 24 kHz.
    buf = io.BytesIO()
    sf.write(buf, np.zeros(24000, dtype="float32"), 24000, format="WAV")
    # Act: recover the header stats from the encoded bytes.
    sr, dur = _wav_stats(buf.getvalue())
    # Assert: the sample rate and ~1 s duration round-trip faithfully.
    assert sr == 24000
    assert abs(dur - 1.0) < 1e-6


def test_synthesize_rejects_empty_text() -> None:
    """Empty text is rejected before any network call."""
    import asyncio

    # Arrange: a client that would otherwise reach out to the network.
    c = VoiceboxClient(Settings.from_mapping({}))
    # Act/Assert: blank input fails validation before any request is made.
    with pytest.raises(ValueError):
        asyncio.run(c.synthesize("   "))


@pytest.mark.slow
async def test_synthesize_live(live_port: int) -> None:
    """Live smoke test: real Voicebox returns decodable non-empty French audio."""
    # Arrange: point the client at the reachable live engine.
    settings = Settings.from_mapping(
        {"engine": "kokoro", "language": "fr", "voicebox": {"port": live_port}}
    )
    # Act: synthesise one utterance end-to-end.
    async with Speaker(settings) as spk:
        result = await spk.say("Bonjour tout le monde.")
    # Assert: non-empty, positive-rate, decodable RIFF audio came back.
    assert result.duration_s > 0
    assert result.sample_rate > 0
    assert result.wav_bytes[:4] == b"RIFF"


@pytest.mark.slow
async def test_stream_live_reports_ttfa(live_port: int) -> None:
    """Live streaming yields ordered chunks; the first carries a TTFA."""
    # Arrange: point the client at the reachable live engine.
    settings = Settings.from_mapping(
        {"engine": "kokoro", "language": "fr", "voicebox": {"port": live_port}}
    )
    # Collect the emitted sequence numbers and the first TTFA we observe.
    seqs: list[int] = []
    ttfa: float | None = None
    # Act: consume the streamed chunks as they arrive.
    async with Speaker(settings) as spk:
        async for chunk in spk.stream("Un. Deux. Trois."):
            seqs.append(chunk.seq)
            if chunk.ttfa_s is not None:
                ttfa = chunk.ttfa_s
    # Assert: chunks arrived in order and a positive TTFA was reported.
    assert seqs == sorted(seqs)  # emission stays in order
    assert ttfa is not None and ttfa > 0
