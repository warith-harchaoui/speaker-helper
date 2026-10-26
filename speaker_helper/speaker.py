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
>>> # Speaker().save("Bonjour le monde.", "hello.wav")

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import os_helper as osh

from speaker_helper.config import Settings
from speaker_helper.engine import TTSEngine, create_engine
from speaker_helper.narration import (
    PACE_SPEED,
    PUNCTUATION_PAUSE_MS,
    NarrationResult,
    Segment,
    Timeline,
    check_timeline_matches_audio,
    coerce_segments,
)
from speaker_helper.text import chunk_for_streaming
from speaker_helper.types import AudioResult, StreamChunk, VoiceList, VoiceSample


class Speaker:
    """Turn text into speech via a pluggable TTS engine, offline or streaming.

    The concrete engine (kokoro, chatterbox, mock, …) is selected by
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
        # The pronunciation lexicon (None when none is configured). Loaded
        # here so every surface that speaks through a Speaker — say, stream,
        # narrate, and the CLI/REST/GUI built on them — honours it by default.
        from speaker_helper.lexicon import load_lexicon

        self.lexicon = load_lexicon(self.settings)

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
        always an HTTP client). It is now any :class:`TTSEngine`; this alias
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

        A long text is not synthesised in one engine call: past their comfort
        zone the neural engines audibly degrade, so the text is cut into
        sentence-group chunks (boundaries placed by the local LLM when
        available, greedily otherwise — see :mod:`speaker_helper.chunking`),
        synthesised chunk by chunk, and concatenated. The caller still gets
        one result; short texts skip all of it.

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
        from speaker_helper.chunking import chunk_long_text

        # Lexicon first (one pass over the whole text), chunking second — so a
        # respelling never straddles a chunk boundary.
        spoken = self._respelled(text, language)
        chunks = chunk_long_text(spoken, language or self.settings.language, self.settings)
        if len(chunks) <= 1:
            return await self.engine.synthesize(spoken, language=language)
        return await self._say_chunked(chunks, text, language)

    async def _say_chunked(
        self,
        chunks: list[str],
        original_text: str,
        language: str | None,
    ) -> AudioResult:
        """Synthesise ``chunks`` in order and concatenate into one result.

        Parameters
        ----------
        chunks : list of str
            The synthesis-sized pieces (from :func:`chunk_long_text`).
        original_text : str
            The caller's text, reported on the merged result (the chunks are
            an implementation detail the caller never asked about).
        language : str or None
            Forwarded to every chunk's synthesis.

        Returns
        -------
        AudioResult
            One result spanning all chunks, with a short breath of silence
            between them and durations/compute summed.

        Raises
        ------
        RuntimeError
            When the backend changes sample rate between chunks (no engine
            does; the check keeps the concatenation honest).
        """
        import numpy as np

        # Bounded like narration: later chunks may synthesise while earlier
        # ones are awaited, but emission order is the text's order.
        sem = asyncio.Semaphore(self.stream_concurrency)

        async def _synth(chunk: str) -> AudioResult:
            async with sem:
                return await self.engine.synthesize(chunk, language=language)

        tasks = [asyncio.create_task(_synth(c)) for c in chunks]
        try:
            results = [await task for task in tasks]
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

        rate = results[0].sample_rate
        if any(r.sample_rate != rate for r in results):
            raise RuntimeError("backend changed sample rate between chunks")
        # A short breath between chunks: the cut sits at a sentence (often a
        # paragraph) boundary, where silence is what a reader would do anyway.
        breath = np.zeros(int(rate * PUNCTUATION_PAUSE_MS / 1000.0), dtype=np.int16)
        pieces: list[Any] = []
        for i, result in enumerate(results):
            if i:
                pieces.append(breath)
            pieces.append(_wav_to_pcm16(result.wav_bytes))
        merged = np.concatenate(pieces)

        from speaker_helper.backends.kokoro import pcm_to_wav_bytes

        return AudioResult(
            wav_bytes=pcm_to_wav_bytes(merged, rate),
            sample_rate=rate,
            duration_s=len(merged) / float(rate),
            # Compute time is the sum of the engine's work, not the wall time
            # of the bounded pipeline — RTF must reflect the engine, not our
            # scheduling.
            compute_s=sum(r.compute_s for r in results),
            text=original_text,
            voice_id=results[0].voice_id,
            language=results[0].language,
        )

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
        # The lexicon rewrites the whole text before chunking — rewriting per
        # chunk would re-scan the same words and could split one across a
        # chunk boundary the sentence splitter chose.
        text = self._respelled(text, language)
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

    # ----- narration ------------------------------------------------------

    async def narrate(
        self,
        segments: list[Any],
        *,
        language: str | None = None,
        voice: str | None = None,
    ) -> NarrationResult:
        """Read a document aloud and say where every block landed in the audio.

        The difference from :meth:`stream` is not the engine, it is the
        bookkeeping: a document has structure — pauses its headings ask for,
        blocks whose spoken form differs from their printed form — and a
        caller that wants to *follow* the reading needs to know which stretch
        of audio speaks which block. See :mod:`speaker_helper.narration`.

        Parameters
        ----------
        segments : list
            :class:`~speaker_helper.narration.Segment` objects, plain dicts,
            or bare strings — see
            :func:`~speaker_helper.narration.coerce_segments`.
        language, voice : str or None
            Override the configured ones for this reading.

        Returns
        -------
        NarrationResult
            The audio, the cues, and what the backend could not honour.

        Raises
        ------
        ValueError
            When no segment holds anything speakable, or when the laid-out
            audio and the timeline disagree.

        Notes
        -----
        Synthesis happens first, for every speakable block at once (bounded by
        ``stream_concurrency``), and the layout second. Two passes rather than
        one because the sample rate is the backend's answer, not ours, and the
        timeline cannot start counting before it knows what a sample is worth.
        """
        import numpy as np

        items: list[Segment] = coerce_segments(segments)
        speakable = [
            (i, seg) for i, seg in enumerate(items) if seg.text.strip() and seg.is_speakable
        ]
        if not speakable:
            raise ValueError("no segment holds anything speakable")

        sem = asyncio.Semaphore(self.stream_concurrency)
        started = time.perf_counter()

        async def _synth(seg: Segment) -> AudioResult:
            async with sem:
                return await self.engine.synthesize(
                    # The lexicon applies to what is *spoken* (text or its
                    # `say` override), never to the page's own text — cues
                    # keep showing the document's words.
                    self._respelled(seg.spoken, language),
                    language=language,
                    **self._voice_and_speed(voice, seg),
                )

        tasks = {index: asyncio.create_task(_synth(seg)) for index, seg in speakable}
        try:
            rendered = {index: await task for index, task in tasks.items()}
        finally:
            for task in tasks.values():
                if not task.done():
                    task.cancel()
        compute_s = time.perf_counter() - started

        first = rendered[speakable[0][0]]
        sample_rate = first.sample_rate
        timeline = Timeline(sample_rate)
        pieces: list[Any] = []
        ignored: set[str] = set()

        for index, seg in enumerate(items):
            if not seg.text.strip():
                # Nothing on the page either: no cue, no silence, no trace.
                continue
            if seg.emotion and seg.emotion != "neutral":
                ignored.add("emotion")
                if seg.intensity:
                    ignored.add("intensity")

            # Skipped on the first piece: a "pause before" with nothing before
            # it is dead air at the head of the file.
            if pieces:
                lead = timeline.silence(seg.pause_before_ms)
                if lead > 0:
                    pieces.append(np.zeros(lead, dtype=np.int16))

            if index not in rendered:
                # Punctuation alone. It cannot be dropped — the page shows it,
                # so every later cue would be one place out — so it becomes a
                # short silence that still takes its turn.
                #
                # The silence is recorded *as the cue's own span*, not as a gap
                # before a zero-length one. Both lay the audio out identically;
                # only the second makes a read-along highlight the block for
                # 120 ms instead of flashing it for none, which is the whole
                # reason the block was kept.
                quiet = int(sample_rate * PUNCTUATION_PAUSE_MS / 1000.0)
                if quiet > 0:
                    pieces.append(np.zeros(quiet, dtype=np.int16))
                timeline.speech(quiet, index=index, text=seg.text)
                continue

            pcm = _wav_to_pcm16(rendered[index].wav_bytes)
            timeline.speech(len(pcm), index=index, text=seg.text)
            pieces.append(pcm)

            trail = timeline.silence(seg.pause_after_ms)
            if trail > 0:
                pieces.append(np.zeros(trail, dtype=np.int16))

        full = np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.int16)
        duration_s = len(full) / float(sample_rate)
        check_timeline_matches_audio(timeline, duration_s)

        from speaker_helper.backends.kokoro import pcm_to_wav_bytes

        return NarrationResult(
            wav_bytes=pcm_to_wav_bytes(full, sample_rate),
            sample_rate=sample_rate,
            duration_s=duration_s,
            compute_s=compute_s,
            cues=timeline.cues,
            voice_id=first.voice_id,
            language=first.language,
            ignored_hints=sorted(ignored),
        )

    def _respelled(self, text: str, language: str | None) -> str:
        """Apply the lexicon's respelling tier when the backend needs it.

        A backend that declares ``LEXICON_TIER = "ipa"`` (kokoro) splices the
        lexicon's phonemes itself, deterministically — rewriting its input
        here would hide the original words from that better tier. Every other
        backend has no phoneme access, so the only lever is rewriting the text
        before it leaves this class.

        Parameters
        ----------
        text : str
            The text about to be synthesised.
        language : str or None
            The call's language override; falls back to the configured one
            (lexicon entries are language-keyed).

        Returns
        -------
        str
            The text to hand the engine — unchanged when no lexicon is
            configured, when the backend owns the IPA tier, or when nothing
            matched.
        """
        if self.lexicon is None:
            return text
        # The class attribute (not the instance) is consulted so a mock
        # wrapping/spec-ing a real engine still answers honestly.
        if getattr(type(self.engine), "LEXICON_TIER", "respelling") == "ipa":
            return text
        # The house rule on language: stated → believed, unstated → detected
        # (langdetect, seeded), with the configured language as the fallback a
        # detector-less install degrades to. Lexicon entries are
        # language-keyed, so respelling with the wrong language would apply
        # the wrong entries, not merely mis-accent them.
        if not language:
            from speaker_helper.backends.kokoro import detect_language

            language = detect_language(text, fallback=self.settings.language)
        return self.lexicon.respell(text, language)

    def _voice_and_speed(self, voice: str | None, seg: Segment) -> dict[str, Any]:
        """The per-segment knobs, passed only to backends that accept them.

        ``synthesize`` grew ``voice`` and ``speed`` for this; a third-party
        backend written against the older two-argument signature must keep
        working, so they are offered and withdrawn rather than required.
        """
        extra: dict[str, Any] = {}
        signature = getattr(type(self.engine).synthesize, "__kwdefaults__", None) or {}
        if "voice" in signature and voice:
            extra["voice"] = voice
        if "speed" in signature:
            extra["speed"] = PACE_SPEED.get(seg.pace, 1.0)
        return extra

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


def _wav_to_pcm16(wav_bytes: bytes):  # type: ignore[no-untyped-def]
    """Decode a WAV payload to mono int16 samples.

    ``dtype="int16"`` rather than the float default: the backends produce
    int16 and the layout writes int16, so a float round trip would be two
    conversions that can only lose.
    """
    import io

    import numpy as np
    import soundfile as sf

    data, _rate = sf.read(io.BytesIO(wav_bytes), dtype="int16", always_2d=False)
    if data.ndim > 1:  # pragma: no cover - the backends are mono
        data = data[:, 0]
    return np.asarray(data, dtype=np.int16)


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
