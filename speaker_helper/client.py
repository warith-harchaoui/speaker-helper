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

from speaker_helper.config import Settings
from speaker_helper.logging_utils import get_logger
from speaker_helper.types import AudioResult, Voice, VoiceList, VoiceSample

if TYPE_CHECKING:  # pragma: no cover - typing only
    import httpx

log = get_logger(__name__)


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
        self.settings = settings
        self.base = settings.base_url
        self._client: httpx.AsyncClient | None = None
        self._profile_id: str | None = None
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
                log.warning("engine %d on attempt %d/%d; retrying",
                            resp.status_code, attempt, attempts)
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
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
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
        engine = engine or self.settings.engine
        resp = await self._send(lambda: self._http().get(f"{self.base}/profiles/presets/{engine}"))
        _raise_for_status(resp)
        raw = resp.json().get("voices", [])
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
        if self.settings.voice_id:
            return self.settings.voice_id
        voices = (await self.list_voices(engine)).voices
        if not voices:
            raise VoiceboxError(
                f"engine {engine!r} exposes no preset voices; "
                "set voice_id explicitly."
            )
        match = next(
            (v for v in voices if v.language.startswith(self.settings.language)),
            None,
        )
        return (match or voices[0]).voice_id

    async def _find_profile(self, engine: str, voice_id: str, name: str) -> str | None:
        """Return an existing profile id for this preset voice, if any."""
        resp = await self._http().get(f"{self.base}/profiles")
        _raise_for_status(resp)
        profiles = resp.json()
        match = next(
            (p for p in profiles
             if p.get("preset_engine") == engine
             and p.get("preset_voice_id") == voice_id),
            None,
        ) or next((p for p in profiles if p.get("name") == name), None)
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
            engine = self.settings.engine
            voice_id = await self._resolve_voice_id(engine)
            name = f"speaker-helper-{engine}-{voice_id}"

            existing = await self._find_profile(engine, voice_id, name)
            if existing:
                self._profile_id = existing
                return existing

            resp = await self._http().post(f"{self.base}/profiles", json={
                "name": name,
                "voice_type": "preset",
                "preset_engine": engine,
                "preset_voice_id": voice_id,
                "language": self.settings.language,
                "default_engine": engine,
            })
            if resp.status_code == 400 and "already exists" in resp.text.lower():
                existing = await self._find_profile(engine, voice_id, name)
                if existing:
                    self._profile_id = existing
                    return existing
            _raise_for_status(resp)
            self._profile_id = resp.json()["id"]
            log.info("created Voicebox preset profile %s (%s/%s)",
                     self._profile_id, engine, voice_id)
            return self._profile_id

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
        if not text or not text.strip():
            raise ValueError("cannot synthesise empty text")
        language = language or self.settings.language
        profile_id = await self.ensure_profile()
        payload = {
            "profile_id": profile_id,
            "text": text,
            "language": language,
            "engine": self.settings.engine,
            "normalize": self.settings.normalize,
        }
        t0 = time.perf_counter()
        resp = await self._send(
            lambda: self._http().post(f"{self.base}/generate/stream", json=payload))
        if resp.status_code == 400 and "not downloaded" in resp.text.lower():
            log.info("engine model not present; downloading via async /generate")
            wav_bytes = await self._generate_async(payload)
        else:
            _raise_for_status(resp)
            wav_bytes = resp.content
        compute_s = time.perf_counter() - t0

        sr, duration_s = _wav_stats(wav_bytes)
        return AudioResult(
            wav_bytes=wav_bytes, sample_rate=sr, duration_s=duration_s,
            compute_s=compute_s, text=text,
            voice_id=self._profile_id or "", language=language,
        )

    async def _generate_async(self, payload: dict) -> bytes:
        """Async fallback: enqueue, poll the SSE status, fetch the audio file."""
        client = self._http()
        resp = await client.post(f"{self.base}/generate", json=payload)
        _raise_for_status(resp)
        gen_id = resp.json()["id"]
        status = "generating"
        async with client.stream("GET", f"{self.base}/generate/{gen_id}/status") as s:
            async for line in s.aiter_lines():
                if not line.startswith("data:"):
                    continue
                status = json.loads(line[5:].strip()).get("status", status)
                if status in ("completed", "failed"):
                    break
        if status != "completed":
            raise VoiceboxError(f"generation {gen_id} ended with status {status!r}")
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
