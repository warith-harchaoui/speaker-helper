"""
Kyutai TTS: native French speech from a Paris lab, offline, voice by embedding.

Module summary
--------------
Kyutai's ``tts-1.6b-en_fr`` (delayed-streams modeling) is the engine this
package reaches for when the text is **French and has to sound French**: the
model is trained by a French lab on French data, and the 2026-10 study
(``STUDY.md`` on the ``research`` branch) found it the best-documented native
French open model — where Chatterbox renders French through an English-first
pipeline and Kokoro's single French voice is a stated grade B-.

Voices are **precomputed embeddings** from the ``kyutai/tts-voices``
repository (CC-BY-4.0 / CC0 banks), fetched by name on first use. That is a
deliberate anti-abuse policy by Kyutai: the speaker encoder is unreleased, so
this backend *selects* voices and does not *clone* them —
:meth:`KyutaiEngine.clone_voice` says so instead of pretending.

The weights (~3 GB) download from Hugging Face on the first synthesis and are
cached; after that the engine is fully offline. Sampling uses a temperature,
so two runs of the same text differ slightly — unlike kokoro, which is
deterministic.

This backend has **no phoneme input** (plain text in), so pronunciation-lexicon
entries reach it through the respelling tier applied by
:class:`~speaker_helper.speaker.Speaker` — see :mod:`speaker_helper.lexicon`.

Usage example
-------------
>>> from speaker_helper import Speaker, Settings
>>> # spk = Speaker(Settings.from_mapping({"backend": "kyutai", "language": "fr"}))
>>> # await spk.say("Bonjour depuis Paris.")

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio
import importlib
import time
from typing import Any

import os_helper as osh

from speaker_helper.config import Settings
from speaker_helper.types import AudioResult, Voice, VoiceList, VoiceSample

#: Mimi (Kyutai's codec) decodes at 24 kHz mono — the same rate as kokoro and
#: chatterbox, which is why a narration can mix engines without resampling.
SAMPLE_RATE_HZ: int = 24_000

#: The default model repository: Kyutai's 1.6B English+French TTS.
DEFAULT_REPO: str = "kyutai/tts-1.6b-en_fr"

#: Default **female** voice per language, as names in the ``kyutai/tts-voices``
#: repository (the ``.safetensors`` embedding suffix is appended by moshi).
#: ``developpeuse-3`` is the French female voice of Kyutai's own unmute.sh
#: (CC0, voice-donation program); ``p329_022`` is VCTK speaker p329, a female
#: English voice. Chosen to honour this package's "female FR + female EN"
#: defaults; any other name from the repository works via ``voice=``.
DEFAULT_VOICE_BY_LANG: dict[str, str] = {
    "fr": "unmute-prod-website/developpeuse-3.wav",
    "en": "unmute-prod-website/p329_022.wav",
}

#: The languages the 1.6B model actually speaks. Anything else is reported
#: (then synthesised anyway): the model will read it with a French/English
#: tongue, and whoever asked should know rather than discover it by ear.
SUPPORTED_LANGUAGES: tuple[str, ...] = ("fr", "en")


def check_install() -> int:
    """Return 0 when ``moshi`` (Kyutai's runtime) is importable, 1 otherwise."""
    try:
        importlib.import_module("moshi")
        return 0
    except ImportError:
        return 1


def _base_language(code: str | None, fallback: str) -> str:
    """Reduce a language code to its bare ISO-639-1 base.

    Parameters
    ----------
    code : str or None
        Anything a caller says: ``"fr"``, ``"fr-FR"``, ``None``.
    fallback : str
        Used when ``code`` is empty.

    Returns
    -------
    str
        The lowercased base code (e.g. ``"fr"``).

    Examples
    --------
    >>> _base_language("fr-FR", "en")
    'fr'
    >>> _base_language(None, "en")
    'en'
    """
    raw = (code or "").strip().lower()
    return raw.split("-")[0] if raw else fallback


class KyutaiEngine:
    """The Kyutai TTS backend: text in, native French (or English) out.

    Parameters
    ----------
    settings : Settings
        ``voice`` may name a voice from the ``kyutai/tts-voices`` repository
        (or a local ``.safetensors`` embedding path); empty picks the female
        default for the language. The ``kyutai`` mapping supplies the knobs:

        * ``repo`` — model repository (default :data:`DEFAULT_REPO`).
        * ``device`` — torch device (default ``"cpu"``; moshi has no Metal
          path, so MPS is opt-in and unsupported upstream).
        * ``dtype`` — ``"float32"`` (default on CPU: ARM cores run fp32
          faster than emulated bf16) or ``"bfloat16"``.
        * ``cfg_coef`` — classifier-free-guidance strength (default ``2.0``;
          higher follows the voice/text more strictly, at some audio-quality
          cost).
        * ``temp`` — sampling temperature (default ``0.6``, the upstream
          default). Non-zero, so synthesis is not bit-deterministic.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model: Any = None
        self._lock = asyncio.Lock()
        # Backend knobs, with the upstream defaults spelled out once here.
        knobs = settings.kyutai or {}
        self._repo: str = str(knobs.get("repo") or DEFAULT_REPO)
        self._device: str = str(knobs.get("device") or "cpu")
        self._dtype: str = str(knobs.get("dtype") or "float32")
        self._cfg_coef: float = float(knobs.get("cfg_coef", 2.0))
        self._temp: float = float(knobs.get("temp", 0.6))

    # -- lifecycle ----------------------------------------------------------

    async def _loaded(self) -> Any:
        """The model, loaded once on first use (see KokoroEngine for why)."""
        if self._model is not None:
            return self._model
        async with self._lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load)
        return self._model

    def _load(self) -> Any:
        """Build the Kyutai TTS model. Blocking; called in a thread.

        The first call downloads the weights (~3 GB) from Hugging Face into
        the local cache; later calls load from disk and touch no network.
        """
        try:
            import torch
            from moshi.models.loaders import CheckpointInfo
            from moshi.models.tts import TTSModel
        except ImportError as exc:
            raise RuntimeError(
                "moshi (Kyutai's runtime) is not installed. Install it with:\n"
                "    pip install 'speaker-helper[kyutai]'"
            ) from exc

        # Resolve the dtype name to a torch dtype; float32 is the safe CPU
        # default (bf16 matmuls on ARM go through emulation and lose).
        dtype = {"float32": torch.float32, "bfloat16": torch.bfloat16}.get(
            self._dtype, torch.float32
        )
        osh.info(
            "kyutai: loading %s on %s (%s) — first time downloads ~3 GB",
            self._repo,
            self._device,
            self._dtype,
        )
        checkpoint = CheckpointInfo.from_hf_repo(self._repo)
        # `temp` rides through from_checkpoint_info's **kwargs onto the model,
        # matching the upstream delayed-streams-modeling examples.
        return TTSModel.from_checkpoint_info(
            checkpoint,
            device=self._device,
            dtype=dtype,
            temp=self._temp,
        )

    async def aclose(self) -> None:
        """Drop the model so torch can free it."""
        self._model = None

    # -- the TTSEngine protocol ---------------------------------------------

    async def synthesize(
        self,
        text: str,
        *,
        language: str | None = None,
        voice: str | None = None,
    ) -> AudioResult:
        """Synthesise ``text`` into one :class:`AudioResult`.

        No ``speed`` parameter on purpose: the model has no rate control, and
        resampling would shift pitch with pace.
        :meth:`~speaker_helper.speaker.Speaker.narrate` detects the missing
        keyword and withdraws the knob instead of failing.

        Parameters
        ----------
        text : str
            What to say (must be non-empty).
        language : str or None
            ``"fr"`` or ``"en"``; anything else is warned about and read with
            the model's bilingual tongue. Defaults to the configured language.
        voice : str or None
            A voice name from ``kyutai/tts-voices`` (e.g.
            ``"unmute-prod-website/developpeuse-3.wav"``) or a local
            ``.safetensors`` embedding path. Empty picks the female default
            for the language.

        Returns
        -------
        AudioResult
            The synthesised audio and its metadata.

        Raises
        ------
        ValueError
            If ``text`` is empty or whitespace-only.
        """
        import numpy as np

        if not text or not text.strip():
            raise ValueError("cannot synthesise empty text")
        model = await self._loaded()

        lang = _base_language(language, self._settings.language or "fr")
        if lang not in SUPPORTED_LANGUAGES:
            # Reported rather than hidden: the audio alone will not make it
            # obvious to a caller who does not speak the language either.
            osh.warning(
                "kyutai: %s only speaks %s; %r will be read bilingually",
                self._repo,
                "/".join(SUPPORTED_LANGUAGES),
                lang,
            )
        chosen = (
            voice
            or self._settings.voice
            or DEFAULT_VOICE_BY_LANG.get(lang, DEFAULT_VOICE_BY_LANG["fr"])
        )

        started = time.perf_counter()
        # simple_generate returns a list of 1-D float32 tensors (one per input
        # text) at mimi's sample rate; the progress bar is for notebooks, not
        # for a library call.
        tensors = await asyncio.to_thread(
            model.simple_generate,
            [text],
            [chosen],
            cfg_coef=self._cfg_coef,
            show_progress=False,
        )
        compute_s = time.perf_counter() - started

        rate = int(model.mimi.sample_rate)
        if rate != SAMPLE_RATE_HZ:  # pragma: no cover - mimi is fixed at 24 kHz
            raise RuntimeError(
                f"Kyutai returned {rate} Hz but this wrapper lays audio out at "
                f"{SAMPLE_RATE_HZ} Hz; every cue after the first would be wrong"
            )

        # float32 [-1, 1] → int16 PCM, clipped the way the other backends do.
        samples = np.clip(tensors[0].detach().cpu().numpy(), -1.0, 1.0)
        pcm = (samples * 32_767).astype(np.int16)

        from speaker_helper.backends.kokoro import pcm_to_wav_bytes

        return AudioResult(
            wav_bytes=pcm_to_wav_bytes(pcm, rate),
            sample_rate=rate,
            duration_s=len(pcm) / float(rate),
            compute_s=compute_s,
            text=text,
            voice_id=chosen,
            language=lang,
        )

    async def list_voices(self, engine: str | None = None) -> VoiceList:
        """The curated female defaults — the full bank lives on Hugging Face.

        The ``kyutai/tts-voices`` repository holds hundreds of embeddings;
        listing them all would need a network call this method must not make.
        The two defaults are real, immediately usable names; any other
        repository path works the same way.
        """
        voices = [
            Voice(
                voice_id=DEFAULT_VOICE_BY_LANG["fr"],
                name="Développeuse (unmute, CC0)",
                language="fr",
                gender="female",
                engine="kyutai",
            ),
            Voice(
                voice_id=DEFAULT_VOICE_BY_LANG["en"],
                name="VCTK p329",
                language="en",
                gender="female",
                engine="kyutai",
            ),
        ]
        return VoiceList(engine="kyutai", voices=voices)

    async def health(self) -> dict:
        """Whether this engine could synthesise, without loading the model."""
        if check_install() != 0:
            return {
                "status": "unavailable",
                "engine": "kyutai",
                "reason": "moshi (Kyutai's runtime) is not installed",
                "fix": "pip install 'speaker-helper[kyutai]'",
            }
        return {
            "status": "ok",
            "engine": "kyutai",
            "loaded": self._model is not None,
            "repo": self._repo,
            "device": self._device,
            "sample_rate": SAMPLE_RATE_HZ,
        }

    async def clone_voice(
        self,
        name: str,
        samples: list[VoiceSample],
        *,
        language: str | None = None,
    ) -> str:
        """Refuse, and explain Kyutai's deliberate policy.

        The speaker encoder that turns a recording into a voice embedding is
        **unreleased by design** (Kyutai's anti-abuse stance): voices come from
        the published bank or their voice-donation program. Saying so beats a
        generic NotImplementedError, because the caller's next question is
        always "then how do I get a voice".
        """
        raise NotImplementedError(
            "Kyutai TTS does not clone voices: the speaker encoder is "
            "deliberately unreleased. Pick a voice from the kyutai/tts-voices "
            "bank (e.g. voice='unmute-prod-website/developpeuse-3.wav'), or "
            "use the `chatterbox` / `openvoice` backend to clone from a "
            "recording."
        )
