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

import os_helper as osh

from speaker_helper.config import Settings
from speaker_helper.engine import TTSEngine, create_engine
from speaker_helper.text import chunk_for_streaming
from speaker_helper.types import AudioResult, StreamChunk, VoiceList, VoiceSample


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
        """Wire up configuration and the TTS backend for this speaker.

        Parameters
        ----------
        settings : Settings or None
            Configuration; ``None`` loads defaults via :meth:`Settings.load`.
        engine : TTSEngine or None
            Pre-built backend to inject; ``None`` builds one from ``settings``.
        stream_concurrency : int
            Max chunks synthesised in parallel while streaming (floored at 1).
        """
        # Fall back to file/env-derived settings when none are supplied.
        self.settings = settings or Settings.load()
        # A concurrency of at least 1 is required for the streaming pipeline.
        self.stream_concurrency = max(1, stream_concurrency)
        # Reuse an injected engine (tests/mocks) or build one from settings.
        self.engine: TTSEngine = engine or create_engine(self.settings)
        # The routing decision that built this speaker, when created via
        # :meth:`from_route` (else ``None``) — kept for provenance / logging.
        self.route: object | None = None

    @classmethod
    def from_profile(
        cls,
        profile: object,
        settings: Settings | None = None,
        *,
        engine: TTSEngine | None = None,
    ) -> Speaker:
        """Build a :class:`Speaker` from a per-language operating profile.

        Applies the profile's language/engine/voice/producer settings and its
        ``stream_concurrency`` (a consumer-parallelism argument, not a
        :class:`Settings` field).

        Parameters
        ----------
        profile : LanguageProfile
            The profile to apply (see :mod:`speaker_helper.profiles`).
        settings : Settings or None
            Base configuration to derive from; ``None`` uses defaults.
        engine : TTSEngine or None
            Optional injected backend (e.g. a mock in tests).

        Returns
        -------
        Speaker
            A speaker configured for the profile's language.
        """
        # Let the profile fold its language/engine/voice choices into settings.
        applied = profile.apply(settings)  # type: ignore[attr-defined]
        # stream_concurrency is a consumer knob, not a Settings field, so it is
        # read off the profile object and forwarded separately.
        return cls(
            applied,
            engine=engine,
            stream_concurrency=getattr(profile, "stream_concurrency", 1),
        )

    @classmethod
    def from_route(
        cls,
        condition: str,
        *,
        language: str = "fr",
        settings: Settings | None = None,
        engine: TTSEngine | None = None,
        **route_kwargs: object,
    ) -> Speaker:
        """Build a :class:`Speaker` from a routed operating point.

        Asks :func:`speaker_helper.router.route` to choose an engine + mode from
        measured quality↔speed evidence for the given **condition**
        (``"online_realtime"`` or ``"offline"``), applies that choice, and
        forwards the decision's ``stream_concurrency``.

        Parameters
        ----------
        condition : str
            ``"online_realtime"`` (delay-bounded streaming) or ``"offline"``.
        language : str
            Target language driving the candidate catalogue.
        settings : Settings or None
            Base configuration to reconfigure; ``None`` uses defaults.
        engine : TTSEngine or None
            Optional injected backend (e.g. a mock in tests); when given, the
            routing choice still sets language/mode but this engine is used.
        **route_kwargs
            Extra :class:`~speaker_helper.router.RouteRequest` fields
            (``rtf_ceiling``, ``rtf_budget``, ``quality_floor``,
            ``require_measured_rtf``).

        Returns
        -------
        Speaker
            A speaker configured for the routed operating point. The chosen
            :class:`~speaker_helper.router.RouteDecision` is attached as
            ``speaker.route`` for inspection / logging.
        """
        # Imported here (not at module top) to avoid a router→speaker cycle.
        from speaker_helper.router import RouteRequest
        from speaker_helper.router import route as route_fn

        req = RouteRequest(condition=condition, language=language, **route_kwargs)  # type: ignore[arg-type]
        decision = route_fn(req)
        # Log the justification so the operating-point choice is visible, not magic.
        osh.info("router: %s", decision.justification)
        spk = cls(
            decision.apply(settings),
            engine=engine,
            stream_concurrency=decision.stream_concurrency,
        )
        # Attach the decision for callers that want the provenance/confidence.
        spk.route = decision
        return spk

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
            osh.info("engine warm-up complete (backend=%s)", self.settings.backend)
        except Exception as exc:  # noqa: BLE001 - warm-up is best-effort
            osh.warning("engine warm-up failed (continuing): %s", exc)

    async def __aenter__(self) -> Speaker:
        """Enter the async context, returning this speaker unchanged.

        Returns
        -------
        Speaker
            This instance, ready for use inside ``async with``.
        """
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Leave the async context, releasing engine resources.

        Parameters
        ----------
        *exc : object
            Exception type/value/traceback (ignored; cleanup runs regardless).
        """
        # Always release the backend, whether or not the block raised.
        await self.aclose()

    # ----- discovery ------------------------------------------------------

    async def voices(self, engine: str | None = None) -> VoiceList:
        """List preset voices for an engine (defaults to the configured one)."""
        return await self.engine.list_voices(engine)

    # ----- cloning --------------------------------------------------------

    async def clone_voice(
        self,
        name: str | None = None,
        samples: list[VoiceSample] | None = None,
        *,
        language: str | None = None,
    ) -> str:
        """Clone a voice and make this speaker synthesise with it.

        Parameters
        ----------
        name : str or None
            Profile name for the clone (idempotency key). Defaults to the
            configured clone name, or ``"ref-fr-female"``.
        samples : list of VoiceSample or None
            Reference recordings. When ``None``, they are resolved from
            ``settings.clone`` — falling back to the bundled ref-fr-female reference.
            A sample without a transcript is transcribed with ``vocal-helper``.
        language : str or None
            Language of the cloned voice (defaults to the configured language).

        Returns
        -------
        str
            The cloned voice/profile id.

        Examples
        --------
        >>> from speaker_helper import Speaker, Settings, VoiceSample
        >>> spk = Speaker(Settings.from_mapping({"backend": "mock"}))
        >>> # give only the audio; the transcript is derived automatically:
        >>> # await spk.clone_voice("my-voice", [VoiceSample("ref.wav", "")])
        """
        from speaker_helper.cloning import clone_name, resolve_samples

        # The clone config (possibly empty) supplies defaults for both the
        # reference samples and the profile name when the caller omits them.
        cfg = self.settings.clone or {}
        if samples is None:
            samples = resolve_samples(cfg)
        if name is None:
            name = clone_name(cfg)
        # Hand off to the backend, which registers the voice and returns its id.
        return await self.engine.clone_voice(name, samples, language=language)

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
        self,
        text: str,
        *,
        language: str | None = None,
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
        # Producer side: split the text into chunks (first one kept small so the
        # first audio comes out fast). Nothing to do for empty input.
        chunks = chunk_for_streaming(text, self.settings.first_chunk_sentences)
        if not chunks:
            return
        # The semaphore caps how many chunks synthesise at once (consumer
        # parallelism); ``t0`` anchors the time-to-first-audio measurement.
        sem = asyncio.Semaphore(self.stream_concurrency)
        t0 = time.perf_counter()

        async def _synth(chunk_text: str) -> AudioResult:
            """Synthesise one chunk, respecting the concurrency limit."""
            async with sem:
                return await self.engine.synthesize(chunk_text, language=language)

        # Kick off every chunk immediately; the semaphore throttles actual work.
        tasks = [asyncio.create_task(_synth(c)) for c in chunks]
        try:
            # Await tasks in text order so emission stays ordered even though
            # synthesis may finish out of order.
            for i, task in enumerate(tasks):
                audio = await task
                yield StreamChunk(
                    seq=i,
                    audio=audio,
                    # Only the first chunk reports TTFA (time since t0).
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
        """Synthesise once, then close the engine (drives the sync wrappers).

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
        """
        try:
            # Do the actual synthesis...
            return await self.say(text, language=language)
        finally:
            # ...and tear down the engine even if synthesis raised, since the
            # sync wrappers create and own this speaker for a single call.
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
        # Synthesise synchronously, then persist the raw WAV bytes to disk.
        result = self.say_sync(text, language=language)
        Path(path).write_bytes(result.wav_bytes)
        osh.info("wrote %s (%.2fs audio, RTF %.2f)", path, result.duration_s, result.rtf)
        return result


def _run_sync(coro):  # type: ignore[no-untyped-def]
    """Run a coroutine to completion, refusing to nest inside a running loop."""
    # If get_running_loop() raises, there is no active loop, so it is safe to
    # spin up our own with asyncio.run(). If it succeeds, we are already inside
    # a loop and nesting asyncio.run() would deadlock — refuse instead.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError(
        "sync helpers cannot run inside an active event loop; await the async "
        "API (say / stream) instead."
    )
