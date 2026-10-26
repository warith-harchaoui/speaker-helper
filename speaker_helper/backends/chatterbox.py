"""
Chatterbox: a voice library, an emotion dial, and cloning from a sample.

Module summary
--------------
Where :mod:`~speaker_helper.backends.kokoro` reads with one of 54 fixed
voices, Chatterbox renders from a reference recording and takes an
*exaggeration* dial that maps well onto what a document means by "say this
cheerfully". It is the backend to reach for when the request is "sound like
this person" or "sound like you mean it", and the wrong one for "read me this
article" — it pulls torch, and a reader who wants a page read aloud should not
have to install a deep-learning stack to get it.

Three variants, one backend
---------------------------
Since ``chatterbox-tts`` 0.1.7 the one distribution ships three models, and
``settings.chatterbox["variant"]`` picks among them:

* ``"turbo"`` — the 2025-12 Turbo model: faster, the most lively English of
  the shippable open models (the 2026-10 survey's English pick — see
  ``STUDY.md`` on the ``research`` branch). English only.
* ``"multilingual"`` — 23 languages including French. The quality is honest
  rather than native (the survey records 6–8% French CER), which is why the
  router prefers ``kyutai`` for French and keeps this as the challenger.
* ``"base"`` — the original English model, kept for continuity.
* ``"auto"`` (default) — Turbo for English, Multilingual for anything else,
  base when a chosen variant is missing from the installed package.

Two dials, and what they are for
--------------------------------
``exaggeration`` (0–2, neutral at 0.5) carries emotion. ``cfg_weight`` carries
stability: higher is more predictable, lower lets the model vary. They are
driven from the segment's ``emotion``/``intensity`` and ``pace`` respectively,
because those are the words a document uses — a float in a config file says
nothing about why it is that value.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio
import importlib
import time
from pathlib import Path
from typing import Any

from speaker_helper.config import Settings
from speaker_helper.types import AudioResult, Voice, VoiceList, VoiceSample

#: ChatterboxTTS's native sample rate (24 kHz mono) — the same as Kokoro's,
#: which is why a narration can mix engines without resampling.
SAMPLE_RATE_HZ: int = 24_000

#: ``emotion`` → the neutral-relative base of the exaggeration dial. 0.5 is
#: ordinary conversational delivery; the intensity scales the distance from it.
EMOTION_EXAGGERATION_BASE: dict[str, float] = {
    "neutral": 0.50,
    "cheerful": 0.80,
    "sad": 0.35,
    "cautious": 0.45,
    "enthusiastic": 1.00,
    "contemplative": 0.40,
    "warm": 0.65,
    "calm": 0.40,
    "angry": 1.20,
    "whispering": 0.20,
    "friendly": 0.70,
    "terrified": 1.10,
}

#: ``pace`` → ``cfg_weight``. Higher is more stable and predictable, lower
#: more expressive. Slow reading wants stability; fast reading can afford
#: variation without sounding careless.
PACE_CFG_WEIGHT: dict[str, float] = {"slow": 0.7, "normal": 0.5, "fast": 0.3}


def check_install() -> int:
    """Return 0 when ``chatterbox`` is importable, 1 otherwise.

    Two module names are tried because the distribution has shipped under
    both; which one a given install exposes is not something a caller should
    have to know.
    """
    for name in ("chatterbox.tts", "chatterbox_tts"):
        try:
            importlib.import_module(name)
            return 0
        except ImportError:
            continue
    return 1


def emotion_to_exaggeration(emotion: str, intensity: float) -> float:
    """Map an ``emotion`` and an ``intensity`` onto the engine's dial.

    Clamped to ``[0, 2]`` so a hallucinated intensity from a model never blows
    the dial — the kind of input that arrives as ``2.7`` and comes back as a
    scream.

    Parameters
    ----------
    emotion : str
        A key of :data:`EMOTION_EXAGGERATION_BASE`; anything else is neutral.
    intensity : float
        ``0.0`` flat … ``1.0`` full effect. ``0.5`` means "use the base",
        below pulls towards neutral, above pushes past it.
    """
    base = EMOTION_EXAGGERATION_BASE.get(emotion, 0.50)
    offset = (intensity - 0.5) * 2.0  # -1 … +1
    if base >= 0.5:
        value = 0.5 + (base - 0.5) * (1.0 + offset)
    else:
        value = 0.5 - (0.5 - base) * (1.0 + offset)
    return max(0.0, min(2.0, value))


def _intensity_of(raw: str) -> float:
    """Read an intensity written as a number or as a word.

    Documents say "high"; configuration files say ``0.8``. Both arrive here.
    """
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return {"low": 0.25, "medium": 0.5, "high": 0.85}.get(str(raw).lower(), 0.5)


class ChatterboxEngine:
    """The Chatterbox backend: cloning, and an emotion dial.

    Parameters
    ----------
    settings : Settings
        ``voice_sample`` names a reference recording to clone; without one the
        model's default speaker reads.
    """

    #: variant → (module, class) in the installed ``chatterbox`` package.
    #: ``base`` is also importable as ``chatterbox_tts`` on very old installs,
    #: which :meth:`_load` still tries last.
    VARIANT_CLASSES: dict[str, tuple[str, str]] = {
        "base": ("chatterbox.tts", "ChatterboxTTS"),
        "turbo": ("chatterbox.tts_turbo", "ChatterboxTurboTTS"),
        "multilingual": ("chatterbox.mtl_tts", "ChatterboxMultilingualTTS"),
    }

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # One lazily-loaded model per variant: a narration can mix languages,
        # and reloading Turbo and Multilingual alternately would dominate it.
        self._models: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._reference: Path | None = None
        raw = getattr(settings, "voice_sample", "") or ""
        if raw:
            self._reference = Path(raw)
        else:
            # No reference configured: default to the bundled female voice
            # (CC BY 4.0, see assets/ref-fr-female.NOTICE.md) rather than the
            # model's own default speaker. The project's contract is a female
            # voice in every language, and the built-in speaker's gender is
            # nothing the model card promises; cloning is this engine's native
            # operation, so the guarantee costs one bundled file. Point
            # ``voice_sample`` at any recording to choose a different voice.
            from speaker_helper.cloning import DEFAULT_CLONE_AUDIO

            if DEFAULT_CLONE_AUDIO.is_file():
                self._reference = DEFAULT_CLONE_AUDIO
        # "auto" (default) resolves per call from the language; anything else
        # pins the variant regardless of language.
        knobs = getattr(settings, "chatterbox", {}) or {}
        self._variant: str = str(knobs.get("variant") or "auto").lower()

    def _variant_for(self, language: str) -> str:
        """Which model variant serves ``language`` under the current knob.

        Parameters
        ----------
        language : str
            Bare ISO-639-1 code of the text about to be synthesised.

        Returns
        -------
        str
            ``"turbo"``, ``"multilingual"`` or ``"base"``.
        """
        if self._variant != "auto":
            return self._variant
        # Auto: English gets the lively Turbo model; anything else needs the
        # multilingual one (Turbo and base are English-only).
        return "turbo" if language.startswith("en") else "multilingual"

    async def _loaded(self, variant: str) -> Any:
        """The ``variant`` model, loaded once on first use (see KokoroEngine)."""
        if variant in self._models:
            return self._models[variant]
        async with self._lock:
            if variant not in self._models:
                self._models[variant] = await asyncio.to_thread(self._load, variant)
        return self._models[variant]

    def _load(self, variant: str) -> Any:
        """Build one Chatterbox model. Blocking; called in a thread.

        Parameters
        ----------
        variant : str
            A key of :data:`VARIANT_CLASSES`.

        Raises
        ------
        RuntimeError
            When the package is missing entirely, or too old to ship the
            requested variant (the message says which and how to fix it).
        """
        module_name, class_name = self.VARIANT_CLASSES.get(variant, self.VARIANT_CLASSES["base"])
        try:
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
        except (ImportError, AttributeError):
            # The requested variant is not in this install. For `base` try the
            # historical distribution name before giving up; for the newer
            # variants name the actual fix (upgrade) rather than a bare error.
            if variant == "base":
                try:
                    module = importlib.import_module("chatterbox_tts")
                    cls = module.ChatterboxTTS
                except ImportError as exc:
                    raise RuntimeError(
                        "chatterbox-tts is not installed. Install it with:\n"
                        "    pip install 'speaker-helper[chatterbox]'"
                    ) from exc
            else:
                # `from None`: the ImportError behind this is an implementation
                # detail; the actionable story is "your install is too old".
                raise RuntimeError(
                    f"this chatterbox-tts install has no {variant!r} model; "
                    "upgrade it with:\n"
                    "    pip install -U 'speaker-helper[chatterbox]' chatterbox-tts"
                ) from None
        # device="cpu" is the floor, not the choice: the class detects an
        # accelerator itself and uses it when there is one.
        return cls.from_pretrained(device="cpu")

    async def aclose(self) -> None:
        """Drop the models so torch can free them."""
        self._models.clear()

    async def synthesize(
        self,
        text: str,
        *,
        language: str | None = None,
        voice: str | None = None,
        speed: float = 1.0,
        emotion: str = "neutral",
        intensity: str = "",
    ) -> AudioResult:
        """Synthesise one piece of text.

        ``speed`` is read as a pace and turned into ``cfg_weight``: this model
        has no speed multiplier, and pretending otherwise by resampling the
        output would change the pitch along with the rate.
        """
        import numpy as np

        # The variant is a per-call decision because a narration can mix
        # languages: English lines get Turbo, French ones Multilingual.
        base_lang = ((language or self._settings.language or "en").strip().lower()).split("-")[0]
        variant = self._variant_for(base_lang)
        model = await self._loaded(variant)
        pace = "slow" if speed < 0.95 else "fast" if speed > 1.05 else "normal"
        exaggeration = emotion_to_exaggeration(emotion, _intensity_of(intensity))

        # Assemble the per-variant keyword set. The three generate() methods
        # share text / audio_prompt_path but disagree on the rest:
        # * multilingual requires a `language_id`;
        # * turbo's neutral exaggeration is 0.0 (not base's 0.5) and its
        #   cfg_weight defaults to 0.0 — shift our dial onto its scale and
        #   leave its cfg alone rather than impose base's pacing trick.
        kwargs: dict[str, Any] = {
            "text": text,
            "audio_prompt_path": str(self._reference) if self._reference else None,
        }
        if variant == "multilingual":
            kwargs["language_id"] = base_lang
            kwargs["exaggeration"] = exaggeration
            kwargs["cfg_weight"] = PACE_CFG_WEIGHT.get(pace, 0.5)
        elif variant == "turbo":
            kwargs["exaggeration"] = max(0.0, exaggeration - 0.5)
            # Upstream dtype bug (chatterbox-tts 0.1.7): Turbo's prompt
            # loudness-normalisation goes through pyloudnorm, which returns
            # float64, and the s3 tokenizer then crashes multiplying it
            # against float32 mel filters ("expected m1 and m2 to have the
            # same dtype"). Disabling it keeps the prompt path float32; the
            # evaluation gate already watches output levels for anomalies.
            kwargs["norm_loudness"] = False
        else:
            kwargs["exaggeration"] = exaggeration
            kwargs["cfg_weight"] = PACE_CFG_WEIGHT.get(pace, 0.5)

        started = time.perf_counter()
        wav = await asyncio.to_thread(model.generate, **kwargs)
        compute_s = time.perf_counter() - started

        samples = np.clip(wav.squeeze().detach().cpu().numpy(), -1.0, 1.0)
        pcm = (samples * 32_767).astype(np.int16)

        from speaker_helper.backends.kokoro import pcm_to_wav_bytes

        return AudioResult(
            wav_bytes=pcm_to_wav_bytes(pcm, SAMPLE_RATE_HZ),
            sample_rate=SAMPLE_RATE_HZ,
            duration_s=len(pcm) / float(SAMPLE_RATE_HZ),
            compute_s=compute_s,
            text=text,
            voice_id=voice or (self._reference.name if self._reference else "default"),
            language=language or self._settings.language,
        )

    async def list_voices(self, engine: str | None = None) -> VoiceList:
        """One entry, and it is honest about what it is.

        This engine has no catalogue: it renders from a reference recording or
        from its default speaker. Returning an empty list would read as "not
        loaded yet"; returning a fake catalogue would be worse.
        """
        return VoiceList(
            engine="chatterbox",
            voices=[
                Voice(
                    voice_id="default",
                    name="Chatterbox default speaker",
                    language=self._settings.language,
                    engine="chatterbox",
                )
            ],
        )

    async def health(self) -> dict:
        """Whether this engine could synthesise, without loading the model."""
        if check_install() != 0:
            return {
                "status": "unavailable",
                "engine": "chatterbox",
                "reason": "chatterbox-tts is not installed",
                "fix": "pip install 'speaker-helper[chatterbox]'",
            }
        return {
            "status": "ok",
            "engine": "chatterbox",
            "loaded": sorted(self._models),
            "variant": self._variant,
            "reference": str(self._reference) if self._reference else "",
            "sample_rate": SAMPLE_RATE_HZ,
        }

    async def clone_voice(
        self,
        name: str,
        samples: list[VoiceSample],
        *,
        language: str | None = None,
    ) -> str:
        """Adopt the first sample as the reference this engine renders from.

        There is no enrolment step and nothing to store on a server: the model
        conditions on the recording at generation time. So "cloning" here is
        remembering which file to pass, and the honest return value is the
        path rather than an invented voice id.
        """
        if not samples:
            raise ValueError("cloning needs at least one reference recording")
        first = samples[0]
        if isinstance(first.audio, str):
            self._reference = Path(first.audio)
        else:
            # An in-memory sample has to reach the model as a file: it takes a
            # path, not bytes. Written beside the cache rather than to a
            # temporary that a later generate() would find deleted.
            import tempfile

            handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            handle.write(first.read_bytes())
            handle.close()
            self._reference = Path(handle.name)
        return str(self._reference)
