"""
Speech-to-speech sources: bring audio from the wild into speaker-helper.

Module summary
--------------
speaker-helper turns *text* into speech. To close the **speech-to-speech** loop
— take an existing recording and re-voice it (a different voice via cloning, or
simply a clean re-synthesis) — it needs to *get* audio first. This module wraps
the AI Helpers source packages behind a uniform :class:`SourceAudio` (a local
audio file), then :func:`revoice` transcribes it with ``vocal-helper`` and speaks
the result back through a :class:`~speaker_helper.speaker.Speaker`:

    source ──▶ audio file ──[vocal-helper]──▶ text ──[speaker-helper]──▶ speech

Three sources ship, each behind an optional extra so the heavy dependency is
only pulled when used:

* :func:`from_youtube` — a YouTube URL (``youtube-helper``, extra ``youtube``).
* :func:`from_podcast` — the latest episode of a podcast feed
  (``podcast-helper``, extra ``podcast``).
* :func:`from_microphone` — a few seconds of live capture
  (``capture-helper``, extra ``mic``).

All third-party imports are lazy, and a clear error names the extra to install.

Usage example
-------------
>>> import asyncio
>>> from speaker_helper import Speaker, Settings
>>> from speaker_helper.sources import from_youtube, revoice
>>> async def demo() -> float:
...     src = from_youtube("https://youtu.be/…")            # needs youtube-helper
...     async with Speaker(Settings.from_mapping({"voicebox": {"port": 17600}})) as spk:
...         out = await revoice(src, spk)                    # needs vocal-helper + engine
...     return out.duration_s

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import os_helper as osh

from speaker_helper.types import AudioResult

if TYPE_CHECKING:  # pragma: no cover - typing only
    from speaker_helper.speaker import Speaker


class _Transcriber(Protocol):
    """A callable that turns an audio file path into text (e.g. vocal-helper)."""

    def __call__(self, path: str, *, language: str) -> str: ...


@dataclass
class SourceAudio:
    """A local audio file obtained from some speech source.

    Parameters
    ----------
    path : str
        Filesystem path to the downloaded/captured audio.
    origin : str
        Where it came from: ``"youtube"``, ``"podcast"``, or ``"microphone"``.
    title : str
        A human-readable label (video/episode title, or ``"microphone"``).
    """

    path: str
    origin: str
    title: str = ""


def _require(module: str, extra: str):  # type: ignore[no-untyped-def]
    """Import an optional source helper or raise a helpful error naming the extra."""
    import importlib

    try:
        return importlib.import_module(module)
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise ImportError(
            f"this source needs '{module.replace('_', '-')}'. "
            f"Install it with the '{extra}' extra: pip install 'speaker-helper[{extra}]'."
        ) from exc


def from_youtube(
    url: str, *, output_path: str | None = None, sample_rate: int = 44100,
) -> SourceAudio:
    """Download a YouTube video's audio track as a :class:`SourceAudio`.

    Parameters
    ----------
    url : str
        A YouTube video URL.
    output_path : str or None
        Where to write the audio; when ``None``, ``youtube-helper`` picks a name.
    sample_rate : int
        Target sample rate for the extracted audio.

    Returns
    -------
    SourceAudio
        The downloaded audio file and its title.

    Raises
    ------
    ImportError
        If ``youtube-helper`` (extra ``youtube``) is not installed.
    """
    yh = _require("youtube_helper", "youtube")
    osh.info("downloading YouTube audio: %s", url)
    path = yh.download_audio(url, output_path=output_path, target_sample_rate=sample_rate)
    title = ""
    try:  # metadata is best-effort; never fail the download over a missing title
        title = yh.video_url_meta_data(url).get("title", "")
    except Exception:  # noqa: BLE001
        pass
    return SourceAudio(path=path, origin="youtube", title=title)


def from_podcast(feed_url: str, *, output_path: str | None = None) -> SourceAudio:
    """Download the latest episode of a podcast feed as a :class:`SourceAudio`.

    Parameters
    ----------
    feed_url : str
        RSS/Atom feed URL of the podcast.
    output_path : str or None
        Destination file; when ``None``, a temporary file is used.

    Returns
    -------
    SourceAudio
        The downloaded episode audio and its title.

    Raises
    ------
    ImportError
        If ``podcast-helper`` (extra ``podcast``) is not installed.
    ValueError
        If the latest episode carries no downloadable audio enclosure.
    """
    ph = _require("podcast_helper", "podcast")
    episode = ph.latest_episode(feed_url)
    enclosure = episode.get("enclosure_url")
    if not enclosure:
        raise ValueError(f"latest episode of {feed_url!r} has no audio enclosure")
    if output_path is None:
        output_path = str(Path(tempfile.mkdtemp(prefix="speaker-helper-")) / "episode.mp3")
    osh.info("downloading podcast episode: %s", episode.get("title", enclosure))
    osh.download_file(enclosure, output_path)
    return SourceAudio(path=output_path, origin="podcast", title=episode.get("title", ""))


async def from_microphone(
    seconds: float = 5.0,
    *,
    sample_rate: int = 16000,
    frame_ms: int = 20,
    name_substring: str | None = None,
    output_path: str | None = None,
) -> SourceAudio:
    """Capture a few seconds of live microphone audio as a :class:`SourceAudio`.

    Parameters
    ----------
    seconds : float
        How long to record.
    sample_rate : int
        Capture sample rate.
    frame_ms : int
        Frame size of the capture stream in milliseconds.
    name_substring : str or None
        Pick a specific input device whose name contains this substring;
        ``None`` uses the default device.
    output_path : str or None
        Destination WAV file; when ``None``, a temporary file is used.

    Returns
    -------
    SourceAudio
        The captured audio written to a WAV file.

    Raises
    ------
    ImportError
        If ``capture-helper`` (extra ``mic``) is not installed.
    """
    ch = _require("capture_helper", "mic")
    import numpy as np
    import soundfile as sf

    source = ch.pick_source("microphone", name_substring=name_substring)
    max_frames = max(1, int(seconds * 1000 / frame_ms))
    osh.info("recording %.1fs from microphone (%s)", seconds, getattr(source, "name", "default"))
    chunks: list = []
    async for frame in ch.iter_mic_audio(
        source, target_sample_rate=sample_rate, to_mono=True,
        frame_ms=frame_ms, max_frames=max_frames,
    ):
        chunks.append(frame.pcm)
    pcm = np.concatenate(chunks) if chunks else np.zeros(0, dtype="float32")

    if output_path is None:
        output_path = str(Path(tempfile.mkdtemp(prefix="speaker-helper-")) / "mic.wav")
    sf.write(output_path, pcm.astype("float32"), sample_rate)
    return SourceAudio(path=output_path, origin="microphone", title="microphone")


async def revoice(
    source: SourceAudio | str,
    speaker: Speaker,
    *,
    language: str | None = None,
    transcriber: _Transcriber | None = None,
) -> AudioResult:
    """Transcribe a source recording and speak it back through ``speaker``.

    This is the speech-to-speech step: the source audio is transcribed with
    ``vocal-helper`` (or an injected ``transcriber``), then synthesised by
    ``speaker`` — in a cloned voice if the speaker is configured to clone, and/or
    in a different language.

    Parameters
    ----------
    source : SourceAudio or str
        The recording (a :class:`SourceAudio` or a plain file path).
    speaker : Speaker
        The synthesiser to speak the transcript.
    language : str or None
        Language to synthesise in (defaults to the speaker's configured one).
    transcriber : callable or None
        ``(path, *, language) -> str``. Defaults to ``vocal-helper``'s
        file transcription.

    Returns
    -------
    AudioResult
        The re-voiced audio.

    Raises
    ------
    ImportError
        If no ``transcriber`` is given and ``vocal-helper`` is not installed.
    ValueError
        If the transcript is empty (nothing to speak).
    """
    path = source.path if isinstance(source, SourceAudio) else source
    lang = language or speaker.settings.language
    if transcriber is None:
        from speaker_helper.transcription import transcribe_file

        transcriber = transcribe_file
    text = transcriber(path, language=lang)
    if not text or not text.strip():
        raise ValueError(f"transcription of {path!r} produced no text to speak")
    osh.info("re-voicing %d characters transcribed from %s", len(text), path)
    return await speaker.say(text, language=language)
