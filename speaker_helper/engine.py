"""
Backend-agnostic text-to-speech engine interface and registry.

Module summary
--------------
speaker-helper's value is a small, typed façade over a *local* TTS engine. The
concrete engine is deliberately an implementation detail: the
rest of the package — :class:`~speaker_helper.speaker.Speaker`, the REST API,
the CLI, the evaluation layer — talks only to the :class:`TTSEngine` protocol
defined here. Swapping or adding a backend is therefore a local change: write a
class with four coroutines and register it.

Five backends ship in-tree:

* ``kokoro`` — the default. In this process, no server, 54 built-in voices.
* ``openvoice``, ``chatterbox`` — cloning, from a reference recording.
* ``kyutai`` — native French (and English) from Kyutai's 1.6B model; voices
  picked from a published embedding bank rather than cloned.
* ``mock`` — :class:`MockEngine`, a deterministic, dependency-light
  synthesiser that needs no server and no model. It makes the test suite and
  the evaluation layer runnable in CI, and it proves the abstraction: the
  same code paths drive any backend, narration included.

A fifth used to ship — a REST client for a desktop application on a fixed
port. It was removed once the default ran in-process: an engine you have to
install, launch and keep alive, to do what a 300 MB file does here, is not a
second option but a second way to fail.

:func:`create_engine` dispatches on ``settings.backend``. Third parties can add
their own backend at runtime with :func:`register_backend`.

Usage example
-------------
>>> from speaker_helper.config import Settings
>>> from speaker_helper.engine import create_engine
>>> eng = create_engine(Settings.from_mapping({"backend": "mock"}))
>>> type(eng).__name__
'MockEngine'

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import dataclasses
import io
import math
import wave
from collections.abc import Callable
from typing import Protocol, runtime_checkable

import os_helper as osh

from speaker_helper.config import Settings
from speaker_helper.types import AudioResult, Voice, VoiceList, VoiceSample


@runtime_checkable
class TTSEngine(Protocol):
    """The minimal surface every speaker-helper backend must provide.

    A backend is any object exposing these four coroutines. Everything else in
    the package is written against this protocol, never against a concrete
    engine, so the backend stays swappable.

    Notes
    -----
    ``@runtime_checkable`` lets ``isinstance(obj, TTSEngine)`` verify the method
    names are present (not their signatures) — handy in tests and factories.
    """

    async def synthesize(
        self,
        text: str,
        *,
        language: str | None = None,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> AudioResult:
        """Synthesise ``text`` into one :class:`AudioResult`.

        ``voice`` and ``speed`` arrived with narration, where a document picks
        a voice once and varies the pace block by block. They are keyword-only
        and both have defaults, so a backend written against the original
        two-argument signature still satisfies this protocol —
        :meth:`~speaker_helper.speaker.Speaker.narrate` offers them and
        withdraws them when the backend does not declare them.
        """
        ...

    async def list_voices(self, engine: str | None = None) -> VoiceList:
        """List preset voices for an engine (or the configured one)."""
        ...

    async def health(self) -> dict:
        """Return a backend health document (must include a ``status`` key)."""
        ...

    async def clone_voice(
        self,
        name: str,
        samples: list[VoiceSample],
        *,
        language: str | None = None,
    ) -> str:
        """Clone a voice from reference ``samples`` and return its id.

        Implementations should be idempotent on ``name`` (reuse an existing
        clone rather than duplicating). A backend that cannot clone may raise
        :class:`NotImplementedError`.
        """
        ...

    async def aclose(self) -> None:
        """Release any held resources (HTTP clients, handles, …)."""
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# A factory takes the resolved Settings and returns a ready TTSEngine. Kept in a
# module-level registry so backends can be added without touching create_engine.
EngineFactory = Callable[[Settings], TTSEngine]
_REGISTRY: dict[str, EngineFactory] = {}


def register_backend(name: str, factory: EngineFactory) -> None:
    """Register (or override) a backend factory under ``name``.

    Parameters
    ----------
    name : str
        Backend identifier used in ``settings.backend`` (case-insensitive).
    factory : callable
        ``Settings -> TTSEngine``. Called lazily by :func:`create_engine`.
    """
    _REGISTRY[name.lower()] = factory


def available_backends() -> list[str]:
    """Return the sorted names of all registered backends."""
    return sorted(_REGISTRY)


#: Value of ``settings.backend`` meaning "decide from the operating mode".
AUTO = "auto"


def resolve_auto(settings: Settings) -> Settings:
    """Return ``settings`` with an ``"auto"`` backend/engine decided by mode.

    The project's operating matrix is {offline, streaming} × {local-free,
    paid-cloud}, and the owner has settled the two local-free cells: **offline
    goes to chatterbox in every language**, streaming stays on kokoro for now.
    That matrix already lives in :mod:`speaker_helper.router`, so this resolves
    through the router rather than hard-coding a second copy that could drift
    from it — the French ratification, the per-language priors and the printed
    justification all come along for free.

    Before this existed, the router's answer only reached callers who asked for
    it (``route``, :meth:`Speaker.from_route`), while a plain ``Speaker()`` or
    ``speaker-helper synth`` used the configured backend — which defaulted to
    kokoro. "Offline French uses chatterbox" was therefore true of the router
    and false of the default path. This closes that gap.

    An explicitly configured backend is never touched: ``backend: kokoro`` in a
    config file means kokoro, whatever the matrix says.

    Parameters
    ----------
    settings : Settings
        Configuration, possibly carrying ``backend="auto"``.

    Returns
    -------
    Settings
        The same object when nothing was ``"auto"``; otherwise a copy with
        ``backend`` and ``engine`` resolved.
    """
    if (settings.backend or "").lower() != AUTO:
        return settings
    from speaker_helper.router import OFFLINE, ONLINE_REALTIME, RouteRequest, route

    condition = ONLINE_REALTIME if settings.mode == "streaming" else OFFLINE
    try:
        decision = route(RouteRequest(condition=condition, language=settings.language))
    except ValueError as exc:
        # The online condition refuses a language nobody has timed, rather than
        # claiming an engine keeps up on faith. That is right for a routing
        # *question*, but it must not leave `synth --stream` with no engine at
        # all, so we fall back to the owner's stated streaming default. Said out
        # loud: a silent fallback is how a default stops matching its docs.
        osh.info("backend=auto: router declined (%s); falling back to kokoro", exc)
        return dataclasses.replace(settings, backend="kokoro", engine="kokoro")
    osh.info("backend=auto -> %s. %s", decision.backend, decision.justification)
    return dataclasses.replace(settings, backend=decision.backend, engine=decision.engine)


def create_engine(settings: Settings) -> TTSEngine:
    """Instantiate the backend named by ``settings.backend``.

    Parameters
    ----------
    settings : Settings
        Configuration; its ``backend`` field selects the engine. ``"auto"``
        (the default) is resolved from the operating mode first — see
        :func:`resolve_auto`.

    Returns
    -------
    TTSEngine
        A ready-to-use engine instance.

    Raises
    ------
    ValueError
        If ``settings.backend`` names no registered backend.
    """
    settings = resolve_auto(settings)
    name = (settings.backend or "kokoro").lower()
    factory = _REGISTRY.get(name)
    if factory is None:
        raise ValueError(f"unknown backend {name!r}; available: {', '.join(available_backends())}")
    return factory(settings)


def _kokoro_factory(settings: Settings) -> TTSEngine:
    """Lazily build a :class:`~speaker_helper.backends.kokoro.KokoroEngine`.

    Lazy on purpose: the factory is what ``create_engine`` calls, and this
    package must stay importable on a machine with no ONNX runtime and no
    weights. Nothing here touches kokoro-onnx — the engine loads the model on
    its first synthesis, not on construction.
    """
    from speaker_helper.backends.kokoro import KokoroEngine

    return KokoroEngine(settings)


register_backend("kokoro", _kokoro_factory)


def _openvoice_factory(settings: Settings) -> TTSEngine:
    """Lazily build the OpenVoice cloning backend."""
    from speaker_helper.backends.openvoice import OpenVoiceEngine

    return OpenVoiceEngine(settings)


register_backend("openvoice", _openvoice_factory)


def _chatterbox_factory(settings: Settings) -> TTSEngine:
    """Lazily build the Chatterbox cloning backend."""
    from speaker_helper.backends.chatterbox import ChatterboxEngine

    return ChatterboxEngine(settings)


register_backend("chatterbox", _chatterbox_factory)


def _kyutai_factory(settings: Settings) -> TTSEngine:
    """Lazily build the Kyutai TTS backend (native French + English)."""
    from speaker_helper.backends.kyutai import KyutaiEngine

    return KyutaiEngine(settings)


register_backend("kyutai", _kyutai_factory)


# ---------------------------------------------------------------------------
# Mock backend
# ---------------------------------------------------------------------------


class MockEngine:
    """A deterministic, serverless TTS backend for tests and evaluation.

    It produces a real (decodable) WAV whose *duration* is proportional to the
    input length at a fixed speaking rate, and reports a *compute time* derived
    from a configured real-time factor. No audio model runs and no network call
    is made, so behaviour is reproducible and fast — ideal for CI, for
    exercising the evaluation layer's anomaly checks, and for proving that
    engine-agnostic code paths work against any backend.

    Parameters
    ----------
    settings : Settings
        Used for ``language`` and ``engine`` labels and for the ``mock``
        knobs (``rtf``, ``chars_per_sec``, ``sample_rate``, ``amplitude``,
        ``frequency_hz``) read via :attr:`Settings.mock`.

    Notes
    -----
    The audio is a quiet sine tone (not silence) so evaluation's "empty audio"
    and "clipping" checks see a realistic, non-degenerate signal. Set
    ``mock.amplitude`` above 1.0 to deliberately synthesise a clipping signal
    for testing the anomaly detector.
    """

    def __init__(self, settings: Settings) -> None:
        """Read the ``mock`` knobs from settings into typed attributes.

        Parameters
        ----------
        settings : Settings
            Configuration; its :attr:`Settings.mock` mapping supplies the
            tone/duration parameters (with sensible defaults).
        """
        # Keep the full settings for language/engine labels on results.
        self.settings = settings
        # Pull the mock-specific knobs, coercing each to its declared type and
        # falling back to defaults tuned for realistic (non-degenerate) audio.
        m = settings.mock
        self.rtf: float = float(m.get("rtf", 0.3))
        self.chars_per_sec: float = float(m.get("chars_per_sec", 15.0))
        self.sample_rate: int = int(m.get("sample_rate", 24000))
        self.amplitude: float = float(m.get("amplitude", 0.2))
        self.frequency_hz: float = float(m.get("frequency_hz", 220.0))

    async def synthesize(
        self,
        text: str,
        *,
        language: str | None = None,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> AudioResult:
        """Synthesise ``text`` into a deterministic sine-tone WAV.

        Honouring ``speed`` is what makes this backend worth narrating with:
        a pace of ``fast`` has to shorten the audio, or the cues it produces
        are not the ones a real engine would produce and the timeline tests
        pass against a shape nothing ships.

        Parameters
        ----------
        text : str
            Text to "speak" (must be non-empty). Only its length drives the
            output duration; content is not spoken.
        language : str or None
            Override the configured language label on the result.
        voice : str or None
            Reported back on the result; nothing here varies with it.
        speed : float
            Divides the duration, the way a faster reading would.

        Returns
        -------
        AudioResult
            A decodable WAV plus duration and a compute time equal to
            ``duration * rtf`` (so ``result.rtf`` reproduces the configured RTF).

        Raises
        ------
        ValueError
            If ``text`` is empty or whitespace-only.
        """
        if not text or not text.strip():
            raise ValueError("cannot synthesise empty text")
        language = language or self.settings.language
        duration_s = max(0.2, len(text.strip()) / self.chars_per_sec / max(speed, 0.01))
        wav_bytes = self._render_tone(duration_s)
        return AudioResult(
            wav_bytes=wav_bytes,
            sample_rate=self.sample_rate,
            # Measured from the rendered bytes, not from the figure above: the
            # tone is a whole number of samples and `duration_s` is not, so the
            # two differ by up to a sample. Narration lays audio out by sample
            # and then checks the timeline against the file, which turns that
            # rounding into a failure — the check is right and the source of
            # truth has to be the audio.
            duration_s=self._rendered_seconds(wav_bytes),
            compute_s=duration_s * self.rtf,
            text=text,
            voice_id=voice or self.settings.voice_id or "mock-voice",
            language=language,
        )

    def _rendered_seconds(self, wav_bytes: bytes) -> float:
        """How long the WAV actually is, read back from its own header."""
        with wave.open(io.BytesIO(wav_bytes), "rb") as handle:
            return handle.getnframes() / float(handle.getframerate())

    async def list_voices(self, engine: str | None = None) -> VoiceList:
        """Return a small fixed set of fake voices for ``engine``."""
        engine = engine or self.settings.engine
        voices = [
            Voice(
                voice_id="mock-fr",
                name="Mock French",
                language="fr",
                gender="female",
                engine=engine,
            ),
            Voice(
                voice_id="mock-en", name="Mock English", language="en", gender="male", engine=engine
            ),
        ]
        return VoiceList(engine=engine, voices=voices)

    async def clone_voice(
        self,
        name: str,
        samples: list[VoiceSample],
        *,
        language: str | None = None,
    ) -> str:
        """Pretend to clone a voice; return a deterministic id (no audio model).

        Validates that at least one sample is provided (matching the real
        engine's contract) but performs no synthesis-model work, so cloning is
        testable without a server.
        """
        if not samples:
            raise ValueError("cloning needs at least one reference sample")
        self.settings.voice_id = f"cloned-{name}"
        return self.settings.voice_id

    async def health(self) -> dict:
        """Return a static healthy document identifying the mock backend."""
        return {"status": "ok", "backend": "mock", "rtf": self.rtf}

    async def aclose(self) -> None:
        """No-op: the mock holds no resources."""
        return None

    async def __aenter__(self) -> MockEngine:
        """Enter the async context manager and return this engine.

        Returns
        -------
        MockEngine
            This same instance, usable inside ``async with``.
        """
        # The mock holds no resources, so there is nothing to set up.
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Exit the async context manager, releasing any resources.

        Parameters
        ----------
        *exc : object
            The ``(exc_type, exc, tb)`` triple from the ``with`` body,
            ignored here since the mock closes cleanly regardless.
        """
        # Delegate to aclose (a no-op) so the API mirrors the real client.
        await self.aclose()

    def _render_tone(self, duration_s: float) -> bytes:
        """Render a ``duration_s`` sine tone to in-memory WAV bytes."""
        import numpy as np
        import soundfile as sf

        # Number of samples for the requested duration, and the matching time
        # axis in seconds (sample index / sample rate).
        n = int(duration_s * self.sample_rate)
        t = np.arange(n, dtype="float32") / self.sample_rate
        # A pure sine at the configured frequency/amplitude — a real, decodable
        # signal (not silence) so the evaluation's clipping/empty checks are
        # exercised; amplitude > 1.0 deliberately clips, for anomaly tests.
        signal = (self.amplitude * np.sin(2 * math.pi * self.frequency_hz * t)).astype("float32")
        # Encode to an in-memory WAV so callers get the same bytes a real engine
        # would return, without touching the disk.
        buf = io.BytesIO()
        sf.write(buf, signal, self.sample_rate, format="WAV")
        return buf.getvalue()


register_backend("mock", MockEngine)
