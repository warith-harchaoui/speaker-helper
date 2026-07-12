"""
High-level speaker-helper API: text in, speech out.

Module summary
--------------
:class:`Speaker` is the façade most applications use. It wraps a
:class:`~speaker_helper.engine.TTSEngine` backend and offers two modes:

* **offline** — :meth:`Speaker.say` synthesises the whole text into one
  :class:`~speaker_helper.types.AudioResult`, optimising throughput/quality.
* **streaming** — :meth:`Speaker.stream` splits the text into sentence-sized
  chunks and yields audio as soon as each is ready, minimising time to first
  audio (TTFA). Synthesis is pipelined (bounded concurrency) while emission
  stays strictly in order.

Blocking convenience wrappers (:meth:`Speaker.say_sync`,
:meth:`Speaker.save`) are provided for scripts and CLIs that are not already
inside an event loop.

Usage example
-------------
>>> from speaker_helper import Speaker
>>> # sync, offline — the simplest possible call:
>>> # Speaker().save("Bonjour le monde.", "hello.wav")   # requires Voicebox

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

from speaker_helper.config import Settings
from speaker_helper.engine import TTSEngine, create_engine
from speaker_helper.logging_utils import get_logger
from speaker_helper.text import chunk_for_streaming
from speaker_helper.types import AudioResult, StreamChunk, VoiceList

log = get_logger(__name__)


class Speaker:
    """Turn text into speech via a pluggable TTS engine, offline or streaming.

    The concrete engine (Voicebox, mock, …) is selected by
    ``settings.backend`` and reached only through the
    :class:`~speaker_helper.engine.TTSEngine` protocol, so :class:`Speaker`
    never depends on a specific backend.

    Parameters
    ----------
    settings : Settings or None
        Configuration; when ``None``, :meth:`Settings.load` is used (reads
        ``./settings.yaml`` if present, then ``SPEAKER_HELPER_*`` env vars).
    engine : TTSEngine or None
        Inject a ready backend instance (e.g. a mock in tests). When ``None``
        (default), one is built from ``settings`` via
        :func:`~speaker_helper.engine.create_engine`.
    stream_concurrency : int
        Maximum number of chunks synthesised in parallel in streaming mode.
        The default of ``1`` (a strict pipeline) gives the lowest time to
        first audio: the first chunk gets the whole engine to itself, and
        because kokoro synthesises faster than real time (RTF < 1) each later
        chunk is ready before playback of the previous one finishes. Raise it
        only to favour total throughput over first-audio latency.

    Examples
    --------
    >>> from speaker_helper import Speaker, Settings
    >>> spk = Speaker(Settings.from_mapping({"engine": "kokoro", "language": "fr"}))
    >>> spk.settings.engine
    'kokoro'
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        engine: TTSEngine | None = None,
        stream_concurrency: int = 1,
    ) -> None:
        self.settings = settings or Settings.load()
        self.stream_concurrency = max(1, stream_concurrency)
        self.engine: TTSEngine = engine or create_engine(self.settings)

    @property
    def client(self) -> TTSEngine:
        """Backward-compatible alias for :attr:`engine`.

        Earlier releases exposed the backend as ``speaker.client`` (it was
        always a Voicebox client). It is now any :class:`TTSEngine`; this alias
        keeps old call sites working.
        """
        return self.engine

    async def aclose(self) -> None:
        """Release the underlying engine's resources."""
        await self.engine.aclose()

    async def warmup(self) -> None:
        """Prime the engine so the first real request is not the slow one.

        Synthesises a tiny throwaway utterance, which forces backend-specific
        one-time costs (profile bootstrap, model download / load) to happen now
        rather than on a user's first call. Failures are logged and swallowed —
        warm-up is best-effort and must never break startup.
        """
        try:
            await self.engine.synthesize(".", language=self.settings.language)
            log.info("engine warm-up complete (backend=%s)", self.settings.backend)
        except Exception as exc:  # noqa: BLE001 - warm-up is best-effort
            log.warning("engine warm-up failed (continuing): %s", exc)

    async def __aenter__(self) -> Speaker:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ----- discovery ------------------------------------------------------

    async def voices(self, engine: str | None = None) -> VoiceList:
        """List preset voices for an engine (defaults to the configured one)."""
        return await self.engine.list_voices(engine)

    # ----- offline --------------------------------------------------------

    async def say(self, text: str, *, language: str | None = None) -> AudioResult:
        """Synthesise ``text`` into one :class:`AudioResult` (offline mode).

        Parameters
        ----------
        text : str
            The text to speak.
        language : str or None
            Override the configured target language for this call.

        Returns
        -------
        AudioResult
            The synthesised audio and its metadata.
        """
        return await self.engine.synthesize(text, language=language)

    # ----- streaming ------------------------------------------------------

    async def stream(
        self, text: str, *, language: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Yield audio chunks as they are synthesised (streaming mode).

        Parameters
        ----------
        text : str
            The text to speak, split into sentence-sized chunks.
        language : str or None
            Override the configured target language for this call.

        Yields
        ------
        StreamChunk
            Chunks in order. The first carries ``ttfa_s`` (time to first
            audio); the last has ``is_final=True``.

        Notes
        -----
        Synthesis is pipelined up to ``stream_concurrency`` chunks at a time so
        later chunks are produced while earlier ones are being consumed, but
        emission order matches the text.
        """
        chunks = chunk_for_streaming(text, self.settings.first_chunk_sentences)
        if not chunks:
            return
        sem = asyncio.Semaphore(self.stream_concurrency)
        t0 = time.perf_counter()

        async def _synth(chunk_text: str) -> AudioResult:
            async with sem:
                return await self.engine.synthesize(chunk_text, language=language)

        tasks = [asyncio.create_task(_synth(c)) for c in chunks]
        try:
            for i, task in enumerate(tasks):
                audio = await task
                yield StreamChunk(
                    seq=i,
                    audio=audio,
                    ttfa_s=(time.perf_counter() - t0) if i == 0 else None,
                    is_final=(i == len(tasks) - 1),
                )
        finally:
            # If the consumer stops early, don't leave synthesis tasks running.
            for task in tasks:
                if not task.done():
                    task.cancel()

    # ----- blocking convenience ------------------------------------------

    def say_sync(self, text: str, *, language: str | None = None) -> AudioResult:
        """Blocking wrapper around :meth:`say` for non-async callers.

        Parameters
        ----------
        text : str
            The text to speak.
        language : str or None
            Override the configured target language.

        Returns
        -------
        AudioResult
            The synthesised audio.

        Raises
        ------
        RuntimeError
            If called from within a running event loop (use ``await say``).
        """
        return _run_sync(self._say_and_close(text, language))

    async def _say_and_close(self, text: str, language: str | None) -> AudioResult:
        try:
            return await self.say(text, language=language)
        finally:
            await self.aclose()

    def save(self, text: str, path: str | Path, *, language: str | None = None) -> AudioResult:
        """Synthesise ``text`` and write the WAV to ``path`` (blocking).

        Parameters
        ----------
        text : str
            The text to speak.
        path : str or Path
            Destination ``.wav`` file.
        language : str or None
            Override the configured target language.

        Returns
        -------
        AudioResult
            The synthesised audio (also written to ``path``).
        """
        result = self.say_sync(text, language=language)
        Path(path).write_bytes(result.wav_bytes)
        log.info("wrote %s (%.2fs audio, RTF %.2f)", path, result.duration_s, result.rtf)
        return result


def _run_sync(coro):  # type: ignore[no-untyped-def]
    """Run a coroutine to completion, refusing to nest inside a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError(
        "sync helpers cannot run inside an active event loop; await the async "
        "API (say / stream) instead."
    )
