"""
Typed data structures exchanged across speaker-helper's public surface.

Module summary
--------------
speaker-helper turns text into speech. The values
that cross its API boundaries are described here as dataclasses so callers
never guess dictionary shapes and editors can autocomplete. Audio is carried
as an in-memory ``bytes`` WAV payload plus the metadata a caller needs to save,
stream, or measure it (sample rate, duration, real-time factor).

Usage example
-------------
>>> from speaker_helper.types import Voice
>>> v = Voice(voice_id="ff_siwis", name="Siwis", language="fr", gender="female")
>>> v.language
'fr'

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import io
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# A synthesis run targets one of two modes: ``offline`` optimises
# throughput/quality, ``streaming`` optimises time to first audio by splitting
# the text and emitting chunks as they are ready.
Mode = Literal["offline", "streaming"]

#: Default bitrate when audio is written to a lossy container. Speech at
#: 64 kb/s mono is the rate this suite ships narrations at, and it is a
#: deliberate opinion rather than a passthrough. ``audio-helper`` carries the
#: input's bitrate over when asked for nothing, which is right for a
#: conversion but says nothing here: what this package hands over is always an
#: uncompressed WAV, so there is no bitrate to carry, and the fallback is
#: ffmpeg's own choice of 32 kb/s for a 24 kHz mono stream, audibly worse for
#: a voice. ``audio-helper`` is the generic signal brick and rightly holds no
#: opinion about speech; this one is the speech brick, so it holds one.
DEFAULT_SPEECH_BITRATE = "64k"


def write_audio(
    wav_bytes: bytes,
    path: str | Path,
    *,
    bitrate: str | int | None = DEFAULT_SPEECH_BITRATE,
) -> Path:
    """Write a WAV payload to ``path``, encoding it if ``path`` is not a WAV.

    Parameters
    ----------
    wav_bytes : bytes
        A complete WAV file (RIFF header + PCM), as every result object here
        carries it.
    path : str or pathlib.Path
        Where to write. **The extension decides the container**: ``.wav``
        writes the bytes untouched, anything else (``.mp3``, ``.m4a``,
        ``.ogg``) is encoded by ``audio-helper``.
    bitrate : str or int or None, optional
        Bitrate for a lossy container: bits per second (``64000``) or an
        ffmpeg-style string (``"64k"``). Defaults to
        :data:`DEFAULT_SPEECH_BITRATE`. None hands the choice down to
        ``audio-helper``, which carries the input's bitrate over; the payload
        here is always an uncompressed WAV, so nothing is carried and ffmpeg
        decides. Meaningless for a WAV target, where it is ignored.

    Returns
    -------
    pathlib.Path
        The path written.

    Raises
    ------
    RuntimeError
        If a lossy container is asked for and ``audio-helper`` is missing.

    Notes
    -----
    Callers used to write ``result.wav_bytes`` to whatever name they were
    given, so ``-o out.mp3`` produced a WAV file wearing an MP3 extension, and
    anyone who genuinely wanted an MP3 reached for ffmpeg themselves. The
    encoding is not this package's craft: it belongs to ``audio-helper``, and
    is called here rather than reimplemented. ``audio-helper`` is imported
    lazily so the WAV path, which is most of them, pays nothing for it.

    The sample rate and channel count are read from the payload's own RIFF
    header rather than taken from a neighbouring field, so the conversion
    cannot disagree with the audio it is converting.
    """
    target = Path(path)
    if target.parent != Path(""):
        target.parent.mkdir(parents=True, exist_ok=True)

    if target.suffix.lower() in ("", ".wav"):
        target.write_bytes(wav_bytes)
        return target

    try:
        import audio_helper as ah
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise RuntimeError(
            f"writing {target.name} means encoding, which audio-helper does.\n"
            "    pip install 'audio-helper>=2.6.0'\n"
            "Or ask for a .wav, which needs no encoder."
        ) from exc

    with wave.open(io.BytesIO(wav_bytes), "rb") as handle:
        frame_rate = handle.getframerate()
        channels = handle.getnchannels()

    with tempfile.TemporaryDirectory(prefix="speaker-helper-write-") as tmp:
        source = Path(tmp) / "audio.wav"
        source.write_bytes(wav_bytes)
        ah.sound_converter(
            str(source),
            str(target),
            freq=frame_rate,
            channels=channels,
            bitrate=bitrate,
            overwrite=True,
        )
    return target


@dataclass(frozen=True)
class Voice:
    """A preset voice offered by a backend.

    Parameters
    ----------
    voice_id : str
        Engine-specific identifier (e.g. ``"ff_siwis"`` for kokoro French).
    name : str
        Human-readable display name.
    language : str
        ISO-639-1 language code the voice speaks (e.g. ``"fr"``, ``"en"``).
    gender : str
        Reported voice gender, or ``""`` when the engine does not expose one.
    engine : str
        Engine the voice belongs to (e.g. ``"kokoro"``).
    """

    voice_id: str
    name: str
    language: str
    gender: str = ""
    engine: str = ""


@dataclass
class AudioResult:
    """A synthesised audio payload and its measured metadata.

    Parameters
    ----------
    wav_bytes : bytes
        The complete WAV file contents (RIFF header + PCM), ready to write to
        disk or stream to a client.
    sample_rate : int
        Sample rate of the audio in Hz.
    duration_s : float
        Audio duration in seconds.
    compute_s : float
        Wall-clock seconds spent producing this audio (network + synthesis).
    text : str
        The text that was synthesised.
    voice_id : str
        The voice used.
    language : str
        The language used.

    Notes
    -----
    ``rtf`` (real-time factor) is derived, not stored: ``compute_s /
    duration_s``. A value below ``1.0`` means synthesis was faster than
    real time — the operating point speaker-helper aims for.
    """

    wav_bytes: bytes
    sample_rate: int
    duration_s: float
    compute_s: float
    text: str
    voice_id: str
    language: str

    @property
    def rtf(self) -> float:
        """Real-time factor ``compute_s / duration_s`` (``inf`` if silent).

        Returns
        -------
        float
            Below ``1.0`` means faster than real time.
        """
        # Guard against a zero-duration (silent/empty) result: dividing would
        # raise, so report ``inf`` — treated as "infinitely slower than real
        # time" and caught as an anomaly downstream.
        return self.compute_s / self.duration_s if self.duration_s > 0 else float("inf")

    def write_audio(
        self, path: str | Path, *, bitrate: str | int | None = DEFAULT_SPEECH_BITRATE
    ) -> Path:
        """Write the audio to ``path``; the extension picks the container.

        See :func:`write_audio` for the rules. Prefer this over writing
        ``wav_bytes`` by hand: the extension is then honoured instead of being
        a label on a WAV file.
        """
        return write_audio(self.wav_bytes, path, bitrate=bitrate)


@dataclass
class StreamChunk:
    """One chunk of a streaming synthesis (one sentence-sized unit).

    Parameters
    ----------
    seq : int
        Zero-based index of this chunk within the stream.
    audio : AudioResult
        The synthesised audio for this chunk.
    ttfa_s : float | None
        Time-to-first-audio in seconds, set only on the first chunk
        (``seq == 0``); ``None`` afterwards.
    is_final : bool
        ``True`` for the last chunk of the stream.
    """

    seq: int
    audio: AudioResult
    ttfa_s: float | None = None
    is_final: bool = False


@dataclass
class VoiceSample:
    """One reference recording used to clone a voice.

    Parameters
    ----------
    audio : bytes or str
        The reference audio: raw bytes, or a filesystem path to an audio file.
    reference_text : str
        A transcript of exactly what is said in ``audio``. Cloning engines align
        the audio to this text, so it must match the recording.

    Notes
    -----
    Keep samples short and clean (a few seconds of clear speech). Provide several
    for a more robust clone.
    """

    audio: bytes | str
    reference_text: str

    def read_bytes(self) -> bytes:
        """Return the audio as bytes, reading from disk if a path was given."""
        # ``audio`` is either the raw payload already, or a path to read from.
        if isinstance(self.audio, bytes):
            return self.audio
        from pathlib import Path

        return Path(self.audio).read_bytes()

    def filename(self) -> str:
        """Return a filename to send with the upload (from the path, or a default)."""
        # A path-backed sample keeps its basename (helps the engine label it);
        # an in-memory sample has no name, so fall back to a generic one.
        if isinstance(self.audio, str):
            from pathlib import Path

            return Path(self.audio).name
        return "sample.wav"


@dataclass
class VoiceList:
    """Voices available for an engine.

    Parameters
    ----------
    engine : str
        The engine the voices belong to.
    voices : list[Voice]
        The preset voices, possibly empty.
    """

    engine: str
    voices: list[Voice] = field(default_factory=list)
