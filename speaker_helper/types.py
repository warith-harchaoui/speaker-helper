"""
Typed data structures exchanged across speaker-helper's public surface.

Module summary
--------------
speaker-helper turns text into speech through the Voicebox engine. The values
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

from dataclasses import dataclass, field
from typing import Literal

# A synthesis run targets one of two modes, mirroring the ``speak`` study:
# ``offline`` optimises throughput/quality, ``streaming`` optimises time to
# first audio by splitting the text and emitting chunks as they are ready.
Mode = Literal["offline", "streaming"]


@dataclass(frozen=True)
class Voice:
    """A preset voice offered by a Voicebox engine.

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
        return self.compute_s / self.duration_s if self.duration_s > 0 else float("inf")


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
        if isinstance(self.audio, bytes):
            return self.audio
        from pathlib import Path

        return Path(self.audio).read_bytes()

    def filename(self) -> str:
        """Return a filename to send with the upload (from the path, or a default)."""
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
