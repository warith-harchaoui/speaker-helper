"""
Speech-to-text via ``vocal-helper`` — the canonical transcription path.

Module summary
--------------
speaker-helper is the inverse of ``vocal-helper`` (speech→text); when it needs
to go the other way — to read what a recording *says* — it reuses ``vocal-helper``
rather than reinventing an ASR stack. Two places need this:

1. **Cloning.** Adding a voice to clone should be as easy as pointing at a
   recording. Cloning engines need a transcript of that recording; when the
   caller does not supply one, :func:`ensure_transcript` derives it with
   ``vocal-helper`` and caches it in a ``.txt`` sidecar so it is computed once.
2. **Evaluation round-trip.** :class:`VocalHelperTranscriber` implements the
   evaluation layer's :class:`~speaker_helper.eval.runner.Transcriber` protocol,
   enabling WER/chrF fidelity scoring of synthesised audio.

``vocal-helper`` (and its whisper.cpp backend) is an *optional* dependency: it is
imported lazily, and a clear error tells the user how to proceed if it is absent.

Usage example
-------------
>>> from speaker_helper.transcription import ensure_transcript
>>> # ensure_transcript("assets/ref-fr-female.wav")  # -> transcript str (needs vocal-helper)

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import os_helper as osh

# whisper.cpp consumes 16 kHz mono PCM; we resample/downmix to that.
_ASR_SAMPLE_RATE = 16000


def _require_vocal_helper():  # type: ignore[no-untyped-def]
    """Return ``vocal_helper.transcribe_pcm`` or raise a helpful ImportError."""
    # Import lazily so vocal-helper is only needed when transcription runs;
    # turn a missing dependency into an actionable install hint.
    try:
        from vocal_helper import transcribe_pcm
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise ImportError(
            "transcription needs 'vocal-helper' (speech-to-text). Install it "
            "(pip install vocal-helper) or pass an explicit reference_text."
        ) from exc
    return transcribe_pcm


def _to_asr_pcm(data, sr: int):  # type: ignore[no-untyped-def]
    """Downmix to mono and resample to 16 kHz for whisper.cpp.

    Nearest-neighbour resampling is deliberate: ASR is robust to it and it keeps
    this helper free of a SciPy dependency.
    """
    import numpy as np

    if getattr(data, "ndim", 1) == 2:  # stereo -> mono
        data = data.mean(axis=1)
    if sr != _ASR_SAMPLE_RATE:
        n = int(len(data) * _ASR_SAMPLE_RATE / sr)
        idx = np.clip((np.arange(n) * sr / _ASR_SAMPLE_RATE).astype("int64"), 0, len(data) - 1)
        data = data[idx]
    return np.asarray(data, dtype="float32")


def transcribe_bytes(wav_bytes: bytes, *, language: str = "fr") -> str:
    """Transcribe an in-memory WAV/audio payload with ``vocal-helper``.

    Parameters
    ----------
    wav_bytes : bytes
        Encoded audio (WAV or anything ``soundfile`` can read).
    language : str
        ISO-639-1 language hint for ASR (``"auto"`` to auto-detect).

    Returns
    -------
    str
        The whitespace-normalised transcript.
    """
    import soundfile as sf

    transcribe_pcm = _require_vocal_helper()
    # Decode the encoded payload to float PCM, then normalise it to the mono
    # 16 kHz format whisper.cpp expects before handing it to the ASR backend.
    data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=False)
    pcm = _to_asr_pcm(data, sr)
    text = transcribe_pcm(pcm, _ASR_SAMPLE_RATE, language=language)
    # Collapse runs of whitespace so downstream text/WER handling is stable.
    return " ".join(text.split()).strip()


def transcribe_file(path: str | Path, *, language: str = "fr") -> str:
    """Transcribe an audio file on disk with ``vocal-helper``.

    Parameters
    ----------
    path : str or Path
        Audio file to transcribe.
    language : str
        ISO-639-1 language hint (``"auto"`` to auto-detect).

    Returns
    -------
    str
        The whitespace-normalised transcript.
    """
    return transcribe_bytes(Path(path).read_bytes(), language=language)


def ensure_transcript(audio_path: str | Path, *, language: str = "fr") -> str:
    """Return the transcript of ``audio_path``, caching it in a ``.txt`` sidecar.

    The first call transcribes with ``vocal-helper`` and writes
    ``<audio_path>.txt``; later calls read that file. This makes "add a voice to
    clone" a one-liner (supply only the audio) while paying the ASR cost once.

    Parameters
    ----------
    audio_path : str or Path
        The reference recording.
    language : str
        ISO-639-1 language hint.

    Returns
    -------
    str
        The transcript.
    """
    audio_path = Path(audio_path)
    # The cache is a ``.txt`` sidecar sitting next to the audio file.
    sidecar = audio_path.with_suffix(audio_path.suffix + ".txt")
    # Fast path: a non-empty sidecar means we already transcribed this file.
    if osh.file_exists(str(sidecar)):
        cached = sidecar.read_text(encoding="utf-8").strip()
        if cached:
            return cached
    # Cache miss: run ASR once...
    osh.info("transcribing %s with vocal-helper (cached to %s)", audio_path, sidecar)
    text = transcribe_file(audio_path, language=language)
    # ...and persist the result for next time (never fatal if the write fails).
    try:
        sidecar.write_text(text + "\n", encoding="utf-8")
    except OSError as exc:  # caching is best-effort
        osh.warning("could not cache transcript to %s: %s", sidecar, exc)
    return text


class VocalHelperTranscriber:
    """Adapter exposing ``vocal-helper`` as an evaluation :class:`Transcriber`.

    Parameters
    ----------
    language : str
        Default language hint used when a call does not specify one.

    Notes
    -----
    ``vocal-helper``'s ASR is CPU/GPU-bound and blocking, so
    :meth:`transcribe` runs it in a worker thread to avoid stalling the event
    loop.
    """

    def __init__(self, language: str = "fr") -> None:
        """Store the default language hint for later transcription calls.

        Parameters
        ----------
        language : str
            ISO-639-1 hint used when :meth:`transcribe` gets no explicit one.
        """
        # Remembered so per-call language can stay optional.
        self.language = language

    async def transcribe(self, wav_bytes: bytes, *, language: str | None = None) -> str:
        """Transcribe ``wav_bytes`` off the event loop; see :class:`Transcriber`."""
        # ASR is blocking and CPU/GPU-bound, so run it in a worker thread to
        # keep the event loop responsive.
        return await asyncio.to_thread(
            transcribe_bytes, wav_bytes, language=language or self.language
        )
