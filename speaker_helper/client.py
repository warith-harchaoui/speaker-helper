"""
Asynchronous client for the Voicebox text-to-speech REST engine.

Module summary
--------------
:class:`VoiceboxClient` is the thin, well-typed layer speaker-helper puts
between application code and the Voicebox HTTP API. It hides three awkward
details of that API:

* **Profiles.** Every synthesis needs a ``profile_id``. This client creates a
  preset profile once (idempotently — reusing an existing one) from the
  engine's preset voices, preferring a voice whose language matches the target.
* **Two synthesis paths.** ``POST /generate/stream`` returns WAV bytes
  synchronously but refuses to run until the engine model is downloaded; the
  async ``POST /generate`` path *does* trigger the download. The client streams
  by default and transparently falls back to the async path (enqueue → poll the
  SSE status → fetch ``/audio/{id}``) the first time, when the model is absent.
* **Voice discovery.** ``GET /profiles/presets/{engine}`` is normalised into
  typed :class:`~speaker_helper.types.Voice` objects.

``httpx`` and ``soundfile`` are imported lazily so importing speaker-helper
stays cheap for callers that only need its types.

Usage example
-------------
>>> import asyncio
>>> from speaker_helper.config import Settings
>>> from speaker_helper.client import VoiceboxClient
>>> async def demo() -> float:
...     async with VoiceboxClient(Settings.from_mapping({"engine": "kokoro"})) as c:
...         result = await c.synthesize("Bonjour le monde.")
...         return result.duration_s
>>> # asyncio.run(demo())  # requires a running Voicebox

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio
import io
import json
import time
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import TYPE_CHECKING

import os_helper as osh

from speaker_helper.config import Settings
from speaker_helper.types import AudioResult, Voice, VoiceList, VoiceSample

if TYPE_CHECKING:  # pragma: no cover - typing only
    import httpx


class VoiceboxError(RuntimeError):
    """Raised when Voicebox returns an error or an unexpected response."""


class VoiceboxClient:
    """A typed async client over the Voicebox TTS REST API.

    Parameters
    ----------
    settings : Settings
        Connection and voice configuration. See
        :class:`speaker_helper.config.Settings`.

    Notes
    -----
    The client owns an :class:`httpx.AsyncClient`. Use it as an async context
    manager (``async with``) or call :meth:`aclose` when done. A single client
    caches the resolved ``profile_id`` so repeated syntheses skip the profile
    bootstrap.
    """

    def __init__(self, settings: Settings) -> None:
        """Store configuration and prepare lazy HTTP/profile state.

        Parameters
        ----------
        settings : Settings
            Resolved connection and voice configuration.

        Notes
        -----
        No network I/O happens here: the :class:`httpx.AsyncClient` and the
        resolved ``profile_id`` are created lazily on first use.
        """
        # Keep the settings and pre-compute the base URL used for every request.
        self.settings = settings
        self.base = settings.base_url
        # HTTP client and resolved profile are built lazily (see _http /
        # ensure_profile) so construction stays cheap and side-effect free.
        self._client: httpx.AsyncClient | None = None
        self._profile_id: str | None = None
        # Guards the one-time profile bootstrap against concurrent syntheses.
        self._profile_lock = asyncio.Lock()

    # ----- lifecycle ------------------------------------------------------

    def _http(self) -> httpx.AsyncClient:
        """Return the lazily-created shared :class:`httpx.AsyncClient`."""
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(timeout=self.settings.voicebox.timeout_s)
        return self._client

    async def _send(self, make_request: Callable[[], Awaitable[httpx.Response]]) -> httpx.Response:
        """Send an HTTP request with retries on transient failures.

        Retries on transport errors (connection reset, timeout, …) and on 5xx
        responses, backing off exponentially. Client errors (4xx) are returned
        as-is on the first try so callers keep their special-case handling
        (e.g. the "model not downloaded" 400).

        Parameters
        ----------
        make_request : callable
            A zero-argument coroutine factory that performs one HTTP attempt.
            It must be safe to call more than once (idempotent request).

        Returns
        -------
        httpx.Response
            The first non-5xx response, or the last response/raise after
            exhausting retries.

        Raises
        ------
        VoiceboxError
            If every attempt fails with a transport error.
        """
        import httpx

        attempts = self.settings.voicebox.max_retries + 1
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                resp = await make_request()
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt == attempts:
                    break
            else:
                # Retry only server-side (5xx) failures; 4xx are the caller's.
                if resp.status_code < 500 or attempt == attempts:
                    return resp
                osh.warning(
                    "engine %d on attempt %d/%d; retrying", resp.status_code, attempt, attempts
                )
            await asyncio.sleep(self.settings.voicebox.retry_backoff_s * 2 ** (attempt - 1))
        raise VoiceboxError(
            f"request to {self.base} failed after {attempts} attempt(s): {last_exc}"
        ) from last_exc

    async def aclose(self) -> None:
        """Close the underlying HTTP client and release its connections."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> VoiceboxClient:
        """Enter the async context manager and return this client.

        Returns
        -------
        VoiceboxClient
            This same instance, ready for use inside ``async with``.
        """
        # Nothing to set up eagerly; the HTTP client is created on demand.
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Exit the async context manager, closing the HTTP client.

        Parameters
        ----------
        exc_type : type[BaseException] or None
            Exception class raised in the ``async with`` body, if any.
        exc : BaseException or None
            The exception instance, if any.
        tb : TracebackType or None
            The associated traceback, if any.
        """
        # Always release connections on exit, whether or not the body raised.
        await self.aclose()

    # ----- discovery ------------------------------------------------------

    async def health(self) -> dict:
        """Return the Voicebox ``/health`` payload.

        Returns
        -------
        dict
            The server health document (backend variant, gpu availability, …).

        Raises
        ------
        VoiceboxError
            If the server is unreachable or returns a non-2xx status.
        """
        resp = await self._send(lambda: self._http().get(f"{self.base}/health"))
        _raise_for_status(resp)
        return resp.json()

    async def list_voices(self, engine: str | None = None) -> VoiceList:
        """List the preset voices for an engine.

        Parameters
        ----------
        engine : str or None
            Engine id; defaults to the configured engine.

        Returns
        -------
        VoiceList
            The engine and its preset voices (possibly empty).
        """
        # Fall back to the configured engine when the caller passes none.
        engine = engine or self.settings.engine
        # Ask Voicebox for this engine's preset catalogue.
        resp = await self._send(lambda: self._http().get(f"{self.base}/profiles/presets/{engine}"))
        _raise_for_status(resp)
        # The payload's "voices" key is optional; treat a missing one as empty.
        raw = resp.json().get("voices", [])
        # Normalise each raw entry into a typed Voice, filling absent fields with
        # forgiving defaults (name falls back to the id; language/gender to "").
        voices = [
            Voice(
                voice_id=v["voice_id"],
                name=v.get("name", v["voice_id"]),
                language=v.get("language", ""),
                gender=v.get("gender", ""),
                engine=engine,
            )
            for v in raw
        ]
        return VoiceList(engine=engine, voices=voices)

    # ----- profile bootstrap ---------------------------------------------

    async def _resolve_voice_id(self, engine: str) -> str:
        """Return the configured voice id, or auto-pick one for the language."""
        # An explicit voice id always wins — no discovery needed.
        if self.settings.voice_id:
            return self.settings.voice_id
        # Otherwise pick from the engine's presets; refuse if it exposes none.
        voices = (await self.list_voices(engine)).voices
        if not voices:
            raise VoiceboxError(
                f"engine {engine!r} exposes no preset voices; set voice_id explicitly."
            )
        # Prefer the first voice whose language matches the target; if none do,
        # fall back to the first preset so synthesis can still proceed.
        match = next(
            (v for v in voices if v.language.startswith(self.settings.language)),
            None,
        )
        return (match or voices[0]).voice_id

    async def _find_profile(self, engine: str, voice_id: str, name: str) -> str | None:
        """Return an existing profile id for this preset voice, if any."""
        # List every profile and search locally (Voicebox has no query filter).
        resp = await self._send(lambda: self._http().get(f"{self.base}/profiles"))
        _raise_for_status(resp)
        profiles = resp.json()
        # Prefer an exact preset-engine + preset-voice match; only if none is
        # found do we fall back to a plain name match (handles legacy profiles).
        match = next(
            (
                p
                for p in profiles
                if p.get("preset_engine") == engine and p.get("preset_voice_id") == voice_id
            ),
            None,
        ) or next((p for p in profiles if p.get("name") == name), None)
        return match["id"] if match else None

    async def _find_profile_by_name(self, name: str) -> str | None:
        """Return an existing profile id matching ``name``, if any."""
        # Fetch all profiles and scan for the first with a matching name.
        resp = await self._send(lambda: self._http().get(f"{self.base}/profiles"))
        _raise_for_status(resp)
        match = next((p for p in resp.json() if p.get("name") == name), None)
        # Return its id, or None so callers know to create the profile.
        return match["id"] if match else None

    async def ensure_profile(self) -> str:
        """Return a usable ``profile_id``, creating a preset one idempotently.

        Returns
        -------
        str
            The profile id to pass to synthesis calls.

        Notes
        -----
        Reuses an existing profile for the resolved preset voice rather than
        creating a duplicate (Voicebox rejects duplicate names), so a fresh
        client never fails on the second run. Safe under concurrency via an
        internal lock.
        """
        if self._profile_id:
            return self._profile_id
        async with self._profile_lock:
            if self._profile_id:  # another coroutine won the race
                return self._profile_id
            # When cloning is configured, the profile is a cloned voice rather
            # than a preset — this is what makes a custom voice work everywhere
            # (lib/CLI/API) from a single ``settings.clone`` block.
            if self.settings.clone:
                return await self._ensure_cloned_profile()
            # Resolve which preset voice to use and derive a stable, unique
            # profile name from engine + voice so lookups stay idempotent.
            engine = self.settings.engine
            voice_id = await self._resolve_voice_id(engine)
            name = f"speaker-helper-{engine}-{voice_id}"

            # Reuse a matching profile from a previous run instead of duplicating.
            existing = await self._find_profile(engine, voice_id, name)
            if existing:
                self._profile_id = existing
                return existing

            # None found: create a fresh preset profile for this voice.
            resp = await self._http().post(
                f"{self.base}/profiles",
                json={
                    "name": name,
                    "voice_type": "preset",
                    "preset_engine": engine,
                    "preset_voice_id": voice_id,
                    "language": self.settings.language,
                    "default_engine": engine,
                },
            )
            # A concurrent creator (or a prior partial run) may have won the
            # race; recover by looking the just-created profile back up.
            if resp.status_code == 400 and "already exists" in resp.text.lower():
                existing = await self._find_profile(engine, voice_id, name)
                if existing:
                    self._profile_id = existing
                    return existing
            _raise_for_status(resp)
            # Cache the new id so subsequent syntheses skip this whole bootstrap.
            self._profile_id = resp.json()["id"]
            osh.info(
                "created Voicebox preset profile %s (%s/%s)", self._profile_id, engine, voice_id
            )
            return self._profile_id

    # ----- cloning --------------------------------------------------------

    async def _ensure_cloned_profile(self) -> str:
        """Resolve/create the cloned profile described by ``settings.clone``.

        Called under the profile lock from :meth:`ensure_profile`. Idempotent on
        the clone name so repeated startups reuse the same cloned voice.
        """
        from speaker_helper.cloning import (
            clone_name,
            prepare_samples,
            resolve_samples,
        )

        # Derive the deterministic clone name and reuse an existing clone by
        # that name so repeated startups don't re-upload the same samples.
        name = clone_name(self.settings.clone)
        existing = await self._find_profile_by_name(name)
        if existing:
            self._profile_id = existing
            return existing
        # Materialise the reference samples described in settings.clone.
        samples = resolve_samples(self.settings.clone)
        # Transcription (via vocal-helper) is blocking and heavy — off the loop.
        samples = await asyncio.to_thread(prepare_samples, samples, language=self.settings.language)
        return await self._create_clone(name, samples, language=self.settings.language)

    async def clone_voice(
        self,
        name: str,
        samples: list[VoiceSample],
        *,
        language: str | None = None,
    ) -> str:
        """Clone a voice from reference ``samples`` and use it for synthesis.

        Parameters
        ----------
        name : str
            Profile name for the clone (idempotency key). A matching profile is
            reused rather than duplicated.
        samples : list of VoiceSample
            Reference recordings. Any sample without a ``reference_text`` is
            transcribed with ``vocal-helper`` before upload.
        language : str or None
            Language of the cloned voice (defaults to the configured language).

        Returns
        -------
        str
            The cloned profile id (also set as this client's active profile).

        Raises
        ------
        VoiceboxError
            On a Voicebox error.
        """
        from speaker_helper.cloning import prepare_samples

        language = language or self.settings.language
        # Serialise clone creation with other profile bootstraps on this client.
        async with self._profile_lock:
            # Idempotency: reuse a clone already registered under this name.
            existing = await self._find_profile_by_name(name)
            if existing:
                self._profile_id = existing
                return existing
            # Transcription is blocking/heavy — run it off the event loop.
            samples = await asyncio.to_thread(prepare_samples, samples, language=language)
            return await self._create_clone(name, samples, language=language)

    async def _create_clone(
        self,
        name: str,
        samples: list[VoiceSample],
        *,
        language: str,
    ) -> str:
        """Create a cloned profile and upload its reference samples."""
        # A clone with no reference audio is meaningless — reject early.
        if not samples:
            raise VoiceboxError("cloning needs at least one reference sample")
        # Register the empty cloned profile first; samples are attached below.
        engine = self.settings.engine
        resp = await self._send(
            lambda: self._http().post(
                f"{self.base}/profiles",
                json={
                    "name": name,
                    "voice_type": "cloned",
                    "language": language,
                    "default_engine": engine,
                },
            )
        )
        # If the name was taken meanwhile, adopt the existing clone instead.
        if resp.status_code == 400 and "already exists" in resp.text.lower():
            existing = await self._find_profile_by_name(name)
            if existing:
                self._profile_id = existing
                return existing
        _raise_for_status(resp)
        profile_id = resp.json()["id"]

        # Voicebox aligns each recording to its transcript, so samples are
        # uploaded as multipart form data (file + reference_text).
        for s in samples:
            files = {
                "file": (s.filename(), s.read_bytes()),
                "reference_text": (None, s.reference_text),
            }
            r = await self._http().post(f"{self.base}/profiles/{profile_id}/samples", files=files)
            _raise_for_status(r)

        self._profile_id = profile_id
        osh.info(
            "created Voicebox cloned profile %s (%s) from %d sample(s)",
            profile_id,
            name,
            len(samples),
        )
        return profile_id

    # ----- synthesis ------------------------------------------------------

    async def synthesize(self, text: str, *, language: str | None = None) -> AudioResult:
        """Synthesise ``text`` into a single :class:`AudioResult`.

        Parameters
        ----------
        text : str
            The text to speak. Must be non-empty.
        language : str or None
            Override the configured target language for this call.

        Returns
        -------
        AudioResult
            The synthesised WAV plus measured duration and compute time.

        Raises
        ------
        ValueError
            If ``text`` is empty or whitespace-only.
        VoiceboxError
            On a Voicebox error or an undecodable response.

        Notes
        -----
        Uses ``POST /generate/stream`` (synchronous WAV bytes). The first call
        for a not-yet-downloaded engine model transparently falls back to the
        async ``/generate`` path, which triggers the download.
        """
        # Reject empty input before any network cost.
        if not text or not text.strip():
            raise ValueError("cannot synthesise empty text")
        language = language or self.settings.language
        # Every synthesis needs a profile id; bootstrap one (preset or clone) once.
        profile_id = await self.ensure_profile()
        payload = {
            "profile_id": profile_id,
            "text": text,
            "language": language,
            "engine": self.settings.engine,
            "normalize": self.settings.normalize,
        }
        # Time the whole round-trip (network + synthesis) to derive RTF below.
        t0 = time.perf_counter()
        resp = await self._send(
            lambda: self._http().post(f"{self.base}/generate/stream", json=payload)
        )
        # The sync path refuses when the engine model is not downloaded yet; the
        # async path *does* trigger the download, so fall back to it just then.
        if resp.status_code == 400 and "not downloaded" in resp.text.lower():
            osh.info("engine model not present; downloading via async /generate")
            wav_bytes = await self._generate_async(payload)
        else:
            _raise_for_status(resp)
            wav_bytes = resp.content
        compute_s = time.perf_counter() - t0

        # Decode duration/sample-rate from the returned WAV so callers (and the
        # evaluation layer) get RTF without a second pass.
        sr, duration_s = _wav_stats(wav_bytes)
        return AudioResult(
            wav_bytes=wav_bytes,
            sample_rate=sr,
            duration_s=duration_s,
            compute_s=compute_s,
            text=text,
            voice_id=self._profile_id or "",
            language=language,
        )

    async def _generate_async(self, payload: dict) -> bytes:
        """Async fallback: enqueue, poll the SSE status, fetch the audio file."""
        client = self._http()
        # Enqueue the job; the response carries the generation id we then poll.
        resp = await client.post(f"{self.base}/generate", json=payload)
        _raise_for_status(resp)
        gen_id = resp.json()["id"]
        # Follow the Server-Sent Events status stream until the job resolves.
        status = "generating"
        async with client.stream("GET", f"{self.base}/generate/{gen_id}/status") as s:
            async for line in s.aiter_lines():
                # SSE payload lines start with "data:"; ignore keep-alives/comments.
                if not line.startswith("data:"):
                    continue
                status = json.loads(line[5:].strip()).get("status", status)
                # Stop as soon as the job reaches a terminal state.
                if status in ("completed", "failed"):
                    break
        # Anything but "completed" (failed, or the stream ended early) is an error.
        if status != "completed":
            raise VoiceboxError(f"generation {gen_id} ended with status {status!r}")
        # Fetch the finished audio file by id.
        audio = await client.get(f"{self.base}/audio/{gen_id}")
        _raise_for_status(audio)
        return audio.content


def _raise_for_status(resp: httpx.Response) -> None:
    """Raise :class:`VoiceboxError` with the response body on a non-2xx status."""
    if resp.status_code >= 400:
        body = resp.text[:500]
        raise VoiceboxError(f"Voicebox {resp.status_code} for {resp.url}: {body}")


def _wav_stats(wav_bytes: bytes) -> tuple[int, float]:
    """Return ``(sample_rate, duration_s)`` for an in-memory WAV payload."""
    import soundfile as sf

    data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=False)
    duration_s = (len(data) / sr) if sr else 0.0
    return int(sr), duration_s
