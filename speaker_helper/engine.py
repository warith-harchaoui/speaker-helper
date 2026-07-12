"""
Backend-agnostic text-to-speech engine interface and registry.

Module summary
--------------
speaker-helper's value is a small, typed façade over a *local* TTS engine. The
concrete engine (Voicebox today) is deliberately an implementation detail: the
rest of the package — :class:`~speaker_helper.speaker.Speaker`, the REST API,
the CLI, the evaluation layer — talks only to the :class:`TTSEngine` protocol
defined here. Swapping or adding a backend is therefore a local change: write a
class with four coroutines and register it.

Two backends ship in-tree:

* ``voicebox`` — the real engine, :class:`~speaker_helper.client.VoiceboxClient`.
* ``mock`` — :class:`MockEngine`, a deterministic, dependency-light synthesiser
  that needs no server. It makes the test suite and the evaluation layer
  runnable in CI (and proves the abstraction: the same code paths drive any
  backend).

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

import io
import math
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from speaker_helper.config import Settings
from speaker_helper.logging_utils import get_logger
from speaker_helper.types import AudioResult, Voice, VoiceList, VoiceSample

log = get_logger(__name__)


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

    async def synthesize(self, text: str, *, language: str | None = None) -> AudioResult:
        """Synthesise ``text`` into one :class:`AudioResult`."""
        ...

    async def list_voices(self, engine: str | None = None) -> VoiceList:
        """List preset voices for an engine (or the configured one)."""
        ...

    async def health(self) -> dict:
        """Return a backend health document (must include a ``status`` key)."""
        ...

    async def clone_voice(
        self, name: str, samples: list[VoiceSample], *, language: str | None = None,
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


def create_engine(settings: Settings) -> TTSEngine:
    """Instantiate the backend named by ``settings.backend``.

    Parameters
    ----------
    settings : Settings
        Configuration; its ``backend`` field selects the engine.

    Returns
    -------
    TTSEngine
        A ready-to-use engine instance.

    Raises
    ------
    ValueError
        If ``settings.backend`` names no registered backend.
    """
    name = (settings.backend or "voicebox").lower()
    factory = _REGISTRY.get(name)
    if factory is None:
        raise ValueError(
            f"unknown backend {name!r}; available: {', '.join(available_backends())}"
        )
    return factory(settings)


def _voicebox_factory(settings: Settings) -> TTSEngine:
    """Lazily build a :class:`VoiceboxClient` (keeps httpx out of import path)."""
    from speaker_helper.client import VoiceboxClient

    return VoiceboxClient(settings)


register_backend("voicebox", _voicebox_factory)


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
        self.settings = settings
        m = settings.mock
        self.rtf: float = float(m.get("rtf", 0.3))
        self.chars_per_sec: float = float(m.get("chars_per_sec", 15.0))
        self.sample_rate: int = int(m.get("sample_rate", 24000))
        self.amplitude: float = float(m.get("amplitude", 0.2))
        self.frequency_hz: float = float(m.get("frequency_hz", 220.0))

    async def synthesize(self, text: str, *, language: str | None = None) -> AudioResult:
        """Synthesise ``text`` into a deterministic sine-tone WAV.

        Parameters
        ----------
        text : str
            Text to "speak" (must be non-empty). Only its length drives the
            output duration; content is not spoken.
        language : str or None
            Override the configured language label on the result.

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
        duration_s = max(0.2, len(text.strip()) / self.chars_per_sec)
        wav_bytes = self._render_tone(duration_s)
        return AudioResult(
            wav_bytes=wav_bytes,
            sample_rate=self.sample_rate,
            duration_s=duration_s,
            compute_s=duration_s * self.rtf,
            text=text,
            voice_id=self.settings.voice_id or "mock-voice",
            language=language,
        )

    async def list_voices(self, engine: str | None = None) -> VoiceList:
        """Return a small fixed set of fake voices for ``engine``."""
        engine = engine or self.settings.engine
        voices = [
            Voice(voice_id="mock-fr", name="Mock French", language="fr",
                  gender="female", engine=engine),
            Voice(voice_id="mock-en", name="Mock English", language="en",
                  gender="male", engine=engine),
        ]
        return VoiceList(engine=engine, voices=voices)

    async def clone_voice(
        self, name: str, samples: list[VoiceSample], *, language: str | None = None,
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
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def _render_tone(self, duration_s: float) -> bytes:
        """Render a ``duration_s`` sine tone to in-memory WAV bytes."""
        import numpy as np
        import soundfile as sf

        n = int(duration_s * self.sample_rate)
        t = np.arange(n, dtype="float32") / self.sample_rate
        signal = (self.amplitude * np.sin(2 * math.pi * self.frequency_hz * t)).astype("float32")
        buf = io.BytesIO()
        sf.write(buf, signal, self.sample_rate, format="WAV")
        return buf.getvalue()


register_backend("mock", MockEngine)
