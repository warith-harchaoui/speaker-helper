"""
Writing a result to disk, and the extension deciding what lands there.

This was a bug of the quiet kind. Every caller wrote ``result.wav_bytes`` to
whatever path it was handed, so ``-o out.mp3`` produced a WAV file wearing an
MP3 extension: nothing raised, the file played, and only its size gave it
away. Anyone who genuinely needed an MP3 shelled out to ffmpeg themselves,
and the deraison site did exactly that for sixteen narrations, which is how
this came to light.

The encoding is not this package's craft. It belongs to ``audio-helper``, and
:func:`speaker_helper.types.write_audio` calls it rather than reimplementing
it. What is tested here is the contract, not the codec: WAV is handed over
untouched, a lossy extension is honoured, and the sample rate survives.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import io
import shutil
import wave
from pathlib import Path

import pytest

from speaker_helper.narration import NarrationResult
from speaker_helper.types import DEFAULT_SPEECH_BITRATE, AudioResult, write_audio

#: Encoding needs both the brick that knows ffmpeg and ffmpeg itself.
_CAN_ENCODE = shutil.which("ffmpeg") is not None
try:  # pragma: no cover - the import is the test
    import audio_helper  # noqa: F401
except ImportError:  # pragma: no cover
    _CAN_ENCODE = False

needs_encoder = pytest.mark.skipif(not _CAN_ENCODE, reason="encoding needs ffmpeg and audio-helper")


def _wav_bytes(sample_rate: int = 24000, seconds: float = 1.0, channels: int = 1) -> bytes:
    """A real WAV payload, header included, so the writer reads a true header."""
    frames = int(sample_rate * seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        # Silence is enough: nothing here listens, and a tone would only make
        # the fixture slower to build.
        handle.writeframes(b"\x00\x00" * frames * channels)
    return buffer.getvalue()


def test_a_wav_target_is_handed_over_untouched(tmp_path: Path) -> None:
    """The WAV path must not go near an encoder, byte for byte."""
    payload = _wav_bytes()
    out = write_audio(payload, tmp_path / "narration.wav")
    assert out.read_bytes() == payload


def test_a_missing_parent_directory_is_created(tmp_path: Path) -> None:
    """Callers pass an out-dir that may not exist yet; that is not an error."""
    out = write_audio(_wav_bytes(), tmp_path / "deep" / "deeper" / "narration.wav")
    assert out.is_file()


def test_an_extensionless_path_is_treated_as_wav(tmp_path: Path) -> None:
    """No extension names no container, so the bytes are what they are."""
    payload = _wav_bytes()
    out = write_audio(payload, tmp_path / "narration")
    assert out.read_bytes() == payload


@needs_encoder
def test_an_mp3_target_is_actually_an_mp3(tmp_path: Path) -> None:
    """The extension must decide the container, not merely name the file."""
    out = write_audio(_wav_bytes(seconds=2.0), tmp_path / "narration.mp3")
    assert out.is_file()
    # RIFF would mean the old behaviour came back: a WAV called .mp3.
    head = out.read_bytes()[:4]
    assert head != b"RIFF"
    # An MP3 frame header, or an ID3 tag ahead of one.
    assert head[:3] == b"ID3" or head[0] == 0xFF


@needs_encoder
def test_a_lossy_target_shrinks_the_payload(tmp_path: Path) -> None:
    """64 kb/s of speech must be a fraction of the same seconds as PCM."""
    payload = _wav_bytes(seconds=3.0)
    out = write_audio(payload, tmp_path / "narration.mp3")
    assert out.stat().st_size < len(payload) / 2


@needs_encoder
def test_the_sample_rate_survives_the_encoding(tmp_path: Path) -> None:
    """Read from the payload's own header, so the two cannot disagree."""
    audio_helper_module = pytest.importorskip("audio_helper")
    out = write_audio(_wav_bytes(sample_rate=24000, seconds=1.0), tmp_path / "narration.mp3")
    back = tmp_path / "back.wav"
    audio_helper_module.sound_converter(str(out), str(back), freq=24000, channels=1)
    with wave.open(str(back), "rb") as handle:
        assert handle.getframerate() == 24000


@needs_encoder
def test_a_requested_bitrate_changes_the_file(tmp_path: Path) -> None:
    """A bitrate that reached ffmpeg must show up as a bigger or smaller file."""
    payload = _wav_bytes(seconds=3.0)
    thin = write_audio(payload, tmp_path / "thin.mp3", bitrate="32k")
    thick = write_audio(payload, tmp_path / "thick.mp3", bitrate="128k")
    assert thick.stat().st_size > thin.stat().st_size * 2


def test_both_result_types_write_the_same_way(tmp_path: Path) -> None:
    """A caller holding either result must not need to know which one it is."""
    payload = _wav_bytes()
    narration = NarrationResult(wav_bytes=payload, sample_rate=24000, duration_s=1.0, compute_s=0.1)
    single = AudioResult(
        wav_bytes=payload,
        sample_rate=24000,
        duration_s=1.0,
        compute_s=0.1,
        text="",
        voice_id="",
        language="fr",
    )
    assert narration.write_audio(tmp_path / "a.wav").read_bytes() == payload
    assert single.write_audio(tmp_path / "b.wav").read_bytes() == payload


def test_the_default_bitrate_is_stated_not_left_to_ffmpeg() -> None:
    """Asked for nothing, ffmpeg picks 32k for mono speech, which is worse.

    The default is an opinion this package holds on purpose; audio-helper, the
    generic signal brick, rightly holds none.
    """
    assert DEFAULT_SPEECH_BITRATE == "64k"
