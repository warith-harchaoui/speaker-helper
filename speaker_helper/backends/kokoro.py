"""
Kokoro: the default voice, running in this process.

Module summary
--------------
Kokoro is an 82M-parameter text-to-speech model run through ONNX Runtime,
Apache-2.0 in code *and* weights, with 54 voices across nine languages. On a
laptop CPU it synthesises at roughly a fifth of real time — fast enough that
streaming a conversation is a matter of chunking, not of hardware.

It is the default here for a reason that is architectural rather than
aesthetic: it needs **no server**. The engine this package shipped before
spoke REST to a desktop application the user had to install, launch and keep
running on a fixed port; the first thing anybody met was a connection error.
``pip install 'speaker-helper[kokoro]'`` and one weights fetch is the whole
setup, and the time-to-first-audio no longer includes an HTTP round trip.

Two things pip cannot give you
------------------------------
**espeak-ng.** Kokoro phonemises through it, and the copy bundled in the
``espeakng-loader`` wheel does not find its own data on macOS — it was built
on a CI runner and resolves to that machine's home directory. The failure is
not catchable: espeak reports it from C and calls ``exit(1)``, so there is no
traceback, only a path belonging to somebody else's computer and a dead
process. :func:`espeak_config` therefore prefers a system install, which is
built against its own prefix and initialises first try.

**The weights.** ~340 MB, fetched once. The package being importable says
nothing about whether they are on disk, and discovering that at the first
sentence of a long narration is the wrong moment — so :func:`check_install`
asks both questions separately.

Usage example
-------------
>>> from speaker_helper.backends.kokoro import KokoroEngine, language_for
>>> # Voices are named for the language they speak: the first letter says which.
>>> language_for("ff_siwis")
'fr-fr'

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio
import importlib
import io
import time
import wave
from pathlib import Path
from typing import Any

from speaker_helper.config import Settings
from speaker_helper.types import AudioResult, Voice, VoiceList, VoiceSample

#: Kokoro's native sample rate (24 kHz mono). Fixed by the model, asserted at
#: synthesis time: a different rate would silently misplace every cue after
#: the first.
SAMPLE_RATE_HZ: int = 24_000

#: The ONNX graph and the voice bank, by the names their release uses.
MODEL_FILENAME: str = "kokoro-v1.0.onnx"
VOICES_FILENAME: str = "voices-v1.0.bin"

#: Where the weights are looked for, in order. This package's own cache first,
#: then sprezzature's — that suite downloaded the same two files before this
#: engine lived here, and making somebody fetch 340 MB they already have is a
#: poor welcome.
CACHE_CANDIDATES: tuple[Path, ...] = (
    Path.home() / ".cache" / "speaker-helper" / "kokoro",
    Path.home() / ".cache" / "sprezzature-skill" / "kokoro",
)

#: Where a fresh download goes.
CACHE_ROOT: Path = CACHE_CANDIDATES[0]

#: A voice *is* a language here — the name's first letter says which, and a
#: ``lang`` that disagrees with the voice produces an accent nobody asked for.
VOICE_PREFIX_LANG: dict[str, str] = {
    "a": "en-us",  # American English
    "b": "en-gb",  # British English
    "e": "es",  # Spanish
    "f": "fr-fr",  # French
    "h": "hi",  # Hindi
    "i": "it",  # Italian
    "j": "ja",  # Japanese
    "p": "pt-br",  # Brazilian Portuguese
    "z": "cmn",  # Mandarin Chinese
}

#: Detected language → the voice that reads it. Within a language the pick is
#: the model card's highest-graded voice.
#:
#: Nothing here hard-codes a single default language, and a narrator is the
#: last place to start: an American voice reading French does not produce an
#: accent, it produces nonsense, because the phonemiser is told the wrong
#: language and spells the words out as if they were English.
DEFAULT_VOICE_BY_LANG: dict[str, str] = {
    "en": "af_heart",  # graded A — the only one the card grades that high
    "fr": "ff_siwis",  # the sole French voice
    "es": "ef_dora",
    "it": "if_sara",
    "pt": "pf_dora",
    "hi": "hf_alpha",
    "ja": "jf_alpha",
    "zh": "zf_xiaoxiao",
}

#: Used when the text is in a language Kokoro has no voice for. Reported as a
#: fallback rather than passed off as a choice.
FALLBACK_VOICE: str = "af_heart"

#: All 54, grouped by the language the first letter encodes (see
#: :data:`VOICE_PREFIX_LANG`); the second letter is the speaker's gender.
#:
#: Written out rather than read from the voice bank, because the question
#: "which voices are there" is asked *before* anybody has 340 MB on disk —
#: by someone deciding whether to download them at all. :meth:`list_voices`
#: prefers the loaded model when there is one and falls back to this, so the
#: answer is never "load the weights and ask again".
BUILTIN_VOICES: tuple[str, ...] = (
    "af_alloy",
    "af_aoede",
    "af_bella",
    "af_heart",
    "af_jessica",
    "af_kore",
    "af_nicole",
    "af_nova",
    "af_river",
    "af_sarah",
    "af_sky",
    "am_adam",
    "am_echo",
    "am_eric",
    "am_fenrir",
    "am_liam",
    "am_michael",
    "am_onyx",
    "am_puck",
    "am_santa",
    "bf_alice",
    "bf_emma",
    "bf_isabella",
    "bf_lily",
    "bm_daniel",
    "bm_fable",
    "bm_george",
    "bm_lewis",
    "ef_dora",
    "em_alex",
    "em_santa",
    "ff_siwis",
    "hf_alpha",
    "hf_beta",
    "hm_omega",
    "hm_psi",
    "if_sara",
    "im_nicola",
    "jf_alpha",
    "jf_gongitsune",
    "jf_nezumi",
    "jf_tebukuro",
    "jm_kumo",
    "pf_dora",
    "pm_alex",
    "pm_santa",
    "zf_xiaobei",
    "zf_xiaoni",
    "zf_xiaoxiao",
    "zf_xiaoyi",
    "zm_yunjian",
    "zm_yunxi",
    "zm_yunxia",
    "zm_yunyang",
)


def model_paths() -> tuple[Path, Path] | None:
    """The ONNX graph and voice bank, or ``None`` when they are not fetched."""
    for root in CACHE_CANDIDATES:
        model, voices = root / MODEL_FILENAME, root / VOICES_FILENAME
        if model.is_file() and voices.is_file():
            return model, voices
    return None


def check_install() -> int:
    """Return 0 when this engine could actually synthesise, 1 otherwise.

    Both halves are checked, because they fail at different times and only one
    of them is a ``pip install``.
    """
    try:
        importlib.import_module("kokoro_onnx")
    except ImportError:
        return 1
    return 0 if model_paths() else 1


def espeak_config() -> Any:
    """Where this machine's working espeak-ng lives.

    Prefers a system install over the ``espeakng-loader`` wheel. The wheel's
    copy was built on a CI runner and looks for its ``phontab`` in that
    machine's home directory::

        Error processing file '/Users/runner/work/espeakng-loader/.../phontab'

    Handing it the data directory explicitly does not rescue it: espeak looks
    for ``<path>/espeak-ng-data`` and falls back to ``<path>`` itself, and with
    the wheel's layout neither candidate holds a readable ``phontab``. The
    failure is also not catchable — it is reported from C, followed by
    ``exit(1)``, so the calling process dies without a traceback.
    """
    from kokoro_onnx.config import EspeakConfig

    for prefix in (Path("/opt/homebrew"), Path("/usr/local"), Path("/usr")):
        library = prefix / "lib" / "libespeak-ng.dylib"
        if not library.is_file():
            library = prefix / "lib" / "libespeak-ng.so"
        data = prefix / "share" / "espeak-ng-data"
        if library.is_file() and (data / "phontab").is_file():
            return EspeakConfig(lib_path=str(library), data_path=str(data))

    import espeakng_loader

    return EspeakConfig(
        lib_path=espeakng_loader.get_library_path(),
        data_path=espeakng_loader.get_data_path(),
    )


#: ISO-639-1 → the spelling espeak-ng wants, derived from the two tables above
#: rather than written out a third time. ``fr`` is a perfectly good language
#: code and not a language espeak knows: it answers *language "fr" is not
#: supported by the espeak backend* and the synthesis fails. A caller who says
#: ``language="fr"`` is right, and the translation is this module's job.
LANG_TO_ESPEAK: dict[str, str] = {
    iso: VOICE_PREFIX_LANG.get(voice[:1], "en-us") for iso, voice in DEFAULT_VOICE_BY_LANG.items()
}


def normalise_language(code: str) -> str:
    """Turn a language code into the spelling espeak-ng accepts.

    Returns ``""`` for anything unrecognised, so the caller can fall back to
    what the voice implies rather than pass a string the engine will refuse.

    Examples
    --------
    >>> normalise_language("fr")
    'fr-fr'
    >>> normalise_language("fr-fr")
    'fr-fr'
    >>> normalise_language("klingon")
    ''
    """
    raw = (code or "").strip().lower()
    if not raw:
        return ""
    if raw in VOICE_PREFIX_LANG.values():
        return raw
    return LANG_TO_ESPEAK.get(raw.split("-")[0], "")


def language_for(voice: str) -> str:
    """The language a voice name implies — see :data:`VOICE_PREFIX_LANG`."""
    return VOICE_PREFIX_LANG.get(voice[:1], "en-us")


def voice_for_language(code: str) -> tuple[str, bool]:
    """The voice that reads ``code``, and whether this is a fallback.

    Returns ``(voice, fell_back)``. ``fell_back`` being true means the text is
    in a language this engine has no voice for, and is reported rather than
    hidden: the audio alone will not make it obvious to whoever generated it
    and does not speak the language either.
    """
    base = (code or "").split("-")[0].lower()
    voice = DEFAULT_VOICE_BY_LANG.get(base)
    return (voice, False) if voice else (FALLBACK_VOICE, True)


def detect_language(text: str, fallback: str = "en") -> str:
    """Guess what ``text`` is written in, or return ``fallback``.

    Uses ``langdetect`` when it is installed and says nothing when it is not:
    guessing the language wrong is worse than not guessing, so a caller
    without the extra gets the configured voice rather than a coin flip.
    """
    stripped = (text or "").strip()
    if not stripped:
        return fallback
    try:
        from langdetect import DetectorFactory, detect
    except ImportError:
        return fallback
    # langdetect is randomised by default; the same text must not pick a
    # different voice on a second run.
    DetectorFactory.seed = 0
    try:
        return str(detect(stripped)).split("-")[0].lower()
    except Exception:  # pragma: no cover - langdetect raises on unusable input
        return fallback


def pcm_to_wav_bytes(samples: Any, sample_rate: int = SAMPLE_RATE_HZ) -> bytes:
    """Wrap int16 PCM in a RIFF header, mono.

    Written with the standard library's :mod:`wave` rather than soundfile:
    this is the hot path of every synthesis call, and it has no reason to
    depend on anything.
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.astype("<i2").tobytes())
    return buffer.getvalue()


class KokoroEngine:
    """The in-process Kokoro backend.

    The model is loaded lazily and once: the first call pays for it, every
    later call does not. That matters more here than it looks — a conversation
    loop calls this per sentence, and reloading an ONNX graph between
    sentences would dominate the latency budget it is trying to protect.

    Parameters
    ----------
    settings : Settings
        ``voice`` names a built-in voice; empty means "read the text, detect
        the language, pick the voice that speaks it".
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._kokoro: Any = None
        self._lock = asyncio.Lock()

    # -- lifecycle ---------------------------------------------------------

    async def _model(self) -> Any:
        """The loaded model, loading it on first use.

        Guarded by a lock rather than loaded in ``__init__``: two concurrent
        first calls would otherwise each build their own ONNX session, and the
        second one would win while the first kept several hundred megabytes
        alive for nobody.
        """
        if self._kokoro is not None:
            return self._kokoro
        async with self._lock:
            if self._kokoro is not None:
                return self._kokoro
            self._kokoro = await asyncio.to_thread(self._load)
        return self._kokoro

    def _load(self) -> Any:
        """Build the Kokoro session. Blocking; called in a thread."""
        try:
            from kokoro_onnx import Kokoro
        except ImportError as exc:
            raise RuntimeError(
                "kokoro-onnx is not installed. Install it with:\n"
                "    pip install 'speaker-helper[kokoro]'"
            ) from exc

        paths = model_paths()
        if paths is None:
            raise RuntimeError(
                f"Kokoro's weights are not on this machine. Looked in "
                f"{', '.join(str(p) for p in CACHE_CANDIDATES)}.\n"
                f"Fetch them with:\n"
                f"    speaker-helper install-voice --engine kokoro"
            )
        model_path, voices_path = paths
        return Kokoro(str(model_path), str(voices_path), espeak_config=espeak_config())

    async def aclose(self) -> None:
        """Release the model.

        There is no handle to close — ONNX Runtime frees its session when the
        object is collected — so this drops the reference and lets that
        happen, which is what an ``async with Speaker(...)`` block expects.
        """
        self._kokoro = None

    # -- the TTSEngine protocol -------------------------------------------

    async def synthesize(
        self,
        text: str,
        *,
        language: str | None = None,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> AudioResult:
        """Synthesise ``text`` into one :class:`AudioResult`.

        Parameters
        ----------
        text : str
            What to say.
        language : str or None
            Overrides the language the voice implies. Normally ``None`` —
            a voice *is* a language here, and disagreeing with it produces an
            accent nobody asked for.
        voice : str or None
            A built-in voice. ``None`` falls back to the configured one, and
            an unconfigured one means "detect the language of the text".
        speed : float
            Multiplier. Past about ±20 % the vocoder sounds wound-up or
            drugged rather than paced.
        """
        import numpy as np

        model = await self._model()
        chosen = voice or self._settings.voice or ""
        if not chosen:
            # An explicit language decides the voice, because a voice *is* a
            # language here: honouring `language="fr"` with an English voice
            # would phonemise French through English rules, which is not an
            # accent but a different set of words.
            chosen, _fell_back = voice_for_language(language or detect_language(text))
        self._require_known_voice(model, chosen)
        lang = normalise_language(language or "") or language_for(chosen)

        started = time.perf_counter()
        samples, rate = await asyncio.to_thread(
            model.create, text, voice=chosen, speed=speed, lang=lang, trim=True
        )
        compute_s = time.perf_counter() - started

        if rate != SAMPLE_RATE_HZ:  # pragma: no cover - the model is fixed at 24 kHz
            raise RuntimeError(
                f"Kokoro returned {rate} Hz but this wrapper lays audio out at "
                f"{SAMPLE_RATE_HZ} Hz; every cue after the first would be wrong"
            )

        pcm = (np.clip(samples, -1.0, 1.0) * 32_767).astype(np.int16)
        return AudioResult(
            wav_bytes=pcm_to_wav_bytes(pcm, rate),
            sample_rate=rate,
            duration_s=len(pcm) / float(rate),
            compute_s=compute_s,
            text=text,
            voice_id=chosen,
            language=lang,
        )

    def _require_known_voice(self, model: Any, voice: str) -> None:
        """Fail on an unknown voice by listing the ones there are.

        An unknown voice is a typo nine times out of ten, and the engine's own
        error for it is a KeyError on a tensor name.
        """
        available = set(model.get_voices())
        if voice not in available:
            raise ValueError(
                f"unknown voice {voice!r}; this engine has {', '.join(sorted(available))}"
            )

    async def list_voices(self, engine: str | None = None) -> VoiceList:
        """Every built-in voice, with the language its name implies.

        Answered from the loaded model when there is one, and from
        :data:`BUILTIN_VOICES` otherwise. The fallback is the point: somebody
        choosing a narrator is usually deciding whether to download 340 MB at
        all, and "fetch the weights, then ask again" is a poor answer to
        "which voices are there".
        """
        names: tuple[str, ...] | list[str] = BUILTIN_VOICES
        if self._kokoro is not None:
            names = sorted(self._kokoro.get_voices())
        elif model_paths() is not None:
            # The weights are here, so the model is cheap enough to be exact.
            names = sorted((await self._model()).get_voices())
        voices = [
            Voice(
                voice_id=name,
                name=name,
                language=language_for(name).split("-")[0],
                gender="female" if name[1:2] == "f" else "male" if name[1:2] == "m" else "",
                engine="kokoro",
            )
            for name in names
        ]
        return VoiceList(engine="kokoro", voices=voices)

    async def health(self) -> dict:
        """Whether this engine could synthesise right now, and why not.

        Answers without loading the model: a health check that pays for an
        ONNX session is one nobody puts in a readiness probe.
        """
        try:
            importlib.import_module("kokoro_onnx")
        except ImportError:
            return {
                "status": "unavailable",
                "engine": "kokoro",
                "reason": "kokoro-onnx is not installed",
                "fix": "pip install 'speaker-helper[kokoro]'",
            }
        paths = model_paths()
        if paths is None:
            return {
                "status": "unavailable",
                "engine": "kokoro",
                "reason": "the weights are not on this machine",
                "fix": "speaker-helper install-voice --engine kokoro",
            }
        return {
            "status": "ok",
            "engine": "kokoro",
            "loaded": self._kokoro is not None,
            "weights": str(paths[0].parent),
            "sample_rate": SAMPLE_RATE_HZ,
        }

    async def clone_voice(
        self,
        name: str,
        samples: list[VoiceSample],
        *,
        language: str | None = None,
    ) -> str:
        """Refuse, and name the engines that do clone.

        Kokoro reads with one of its built-in voices; it has no speaker
        encoder. Saying so is more useful than a generic NotImplementedError,
        because the caller's next question is always "then which one".
        """
        raise NotImplementedError(
            "Kokoro does not clone voices — it reads with one of its built-in "
            "ones. For a reference recording use the `openvoice` or "
            "`chatterbox` backend, or pick a voice with "
            "`speaker-helper voices`."
        )
