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

Two implementations, one backend
--------------------------------
The same weights run through two runtimes, picked by the ``device`` knob:

* **MLX** (``moshi-mlx``, Kyutai's own Apple-Silicon implementation) — the
  Metal GPU path. ``device: "auto"`` (the default) selects it when
  ``os-helper`` says this is a Mac and ``moshi_mlx`` is importable, because
  the CPU fallback measured ~8× slower than real time on an M2 Max while the
  MLX path is the operating point Kyutai themselves ship for Macs.
* **PyTorch** (``moshi``) — everywhere else, on the device named by the knob
  (``"cpu"``, ``"cuda"``…).

Both load the *same* Hugging Face files (~3 GB, cached once, offline after).

The weights download on the first synthesis and are cached; after that the
engine is fully offline. Sampling uses a temperature (the MLX path pins the
upstream seed, so it is reproducible run to run; the PyTorch path is not).

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
import importlib.util
import json
import time
from pathlib import Path
from typing import Any

import os_helper as osh

from speaker_helper.config import Settings
from speaker_helper.types import AudioResult, Voice, VoiceList, VoiceSample

#: Mimi (Kyutai's codec) decodes at 24 kHz mono — the same rate as kokoro and
#: chatterbox, which is why a narration can mix engines without resampling.
SAMPLE_RATE_HZ: int = 24_000

#: The default model repository: Kyutai's 1.6B English+French TTS.
DEFAULT_REPO: str = "kyutai/tts-1.6b-en_fr"

#: The default voice-embedding repository.
DEFAULT_VOICE_REPO: str = "kyutai/tts-voices"

#: Default **female** voice per language, as names in the voice repository
#: (the ``.safetensors`` embedding suffix is appended by the runtime).
#:
#: The French default is a CML-TTS speaker (CC BY 4.0), picked by
#: *measurement* in the ~/speak A/B study (2026-10-26): screened against
#: four other female CML voices and unmute's ``developpeuse-3``, it scored
#: highest on UTMOSv2 by a wide margin (≈3.4 vs ≈2.0 for developpeuse-3 on
#: the same sentences, F0 ≈ 226 Hz — female). ``developpeuse-3``
#: (``unmute-prod-website/developpeuse-3.wav``, CC0) remains a fine lighter
#: -licence alternative via ``voice=``. ``p329_022`` is VCTK speaker p329, a
#: female English voice.
DEFAULT_VOICE_BY_LANG: dict[str, str] = {
    "fr": "cml-tts/fr/10087_11650_000028-0002_enhanced.wav",
    "en": "unmute-prod-website/p329_022.wav",
}

#: The languages the 1.6B model actually speaks. Anything else is reported
#: (then synthesised anyway): the model will read it with a French/English
#: tongue, and whoever asked should know rather than discover it by ear.
SUPPORTED_LANGUAGES: tuple[str, ...] = ("fr", "en")

#: The upstream MLX script's RNG seed, reused so MLX synthesis is reproducible
#: run to run (sampling at temperature 0.6 is otherwise a different take each
#: time — fine for a demo, noise for an evaluation).
_MLX_SEED: int = 299_792_458


def check_install() -> int:
    """Return 0 when a Kyutai runtime (``moshi`` or ``moshi_mlx``) is importable."""
    for name in ("moshi", "moshi_mlx"):
        if importlib.util.find_spec(name) is not None:
            return 0
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


def resolve_implementation(device: str) -> str:
    """Turn the ``device`` knob into a concrete implementation name.

    Parameters
    ----------
    device : str
        ``"auto"`` (default), ``"mlx"``, or a torch device (``"cpu"``,
        ``"cuda"``, …).

    Returns
    -------
    str
        ``"mlx"`` or ``"torch:<device>"``.

    Examples
    --------
    >>> resolve_implementation("cpu")
    'torch:cpu'
    >>> resolve_implementation("mlx")
    'mlx'
    """
    knob = (device or "auto").strip().lower()
    if knob == "mlx":
        return "mlx"
    if knob == "auto":
        # The whole point of "auto": on a Mac (os-helper's verdict, not a
        # platform-string guess scattered here) with Kyutai's own MLX runtime
        # installed, take the Metal path — measured ~8× faster than the CPU
        # fallback on an M2 Max. Anywhere else, torch on CPU.
        if osh.macos() and importlib.util.find_spec("moshi_mlx") is not None:
            return "mlx"
        return "torch:cpu"
    return f"torch:{knob}"


class _TorchKyutai:
    """The PyTorch (``moshi``) implementation — the portable fallback.

    Parameters
    ----------
    repo : str
        Hugging Face model repository.
    voice_repo : str
        Hugging Face voice-embedding repository.
    device : str
        torch device string (``"cpu"``, ``"cuda"``, …).
    dtype_name : str
        ``"float32"`` (the CPU default: ARM cores run fp32 faster than
        emulated bf16) or ``"bfloat16"``.
    cfg_coef, temp : float
        Classifier-free-guidance strength and sampling temperature.
    """

    def __init__(
        self,
        repo: str,
        voice_repo: str,
        device: str,
        dtype_name: str,
        cfg_coef: float,
        temp: float,
    ) -> None:
        import torch
        from moshi.models.loaders import CheckpointInfo
        from moshi.models.tts import TTSModel

        self._cfg_coef = cfg_coef
        # Resolve the dtype name to a torch dtype; float32 is the safe CPU
        # default (bf16 matmuls on ARM go through emulation and lose).
        dtype = {"float32": torch.float32, "bfloat16": torch.bfloat16}.get(
            dtype_name, torch.float32
        )
        checkpoint = CheckpointInfo.from_hf_repo(repo)
        # `temp` rides through from_checkpoint_info's **kwargs onto the model,
        # matching the upstream delayed-streams-modeling examples.
        self._model = TTSModel.from_checkpoint_info(
            checkpoint,
            voice_repo=voice_repo,
            device=device,
            dtype=dtype,
            temp=temp,
        )

    @property
    def sample_rate(self) -> int:
        """Mimi's decoding rate in Hz."""
        return int(self._model.mimi.sample_rate)

    def generate(self, text: str, voice: str) -> Any:
        """Synthesise ``text`` with ``voice``; return mono float32 samples.

        Parameters
        ----------
        text : str
            The text to speak.
        voice : str
            Voice name in the voice repository (or a local ``.safetensors``).

        Returns
        -------
        numpy.ndarray
            1-D float32 samples in ``[-1, 1]`` at :attr:`sample_rate`.
        """
        import numpy as np

        # simple_generate returns a list of 1-D float32 tensors (one per input
        # text) at mimi's sample rate; the progress bar is for notebooks.
        tensors = self._model.simple_generate(
            [text], [voice], cfg_coef=self._cfg_coef, show_progress=False
        )
        return np.clip(tensors[0].detach().cpu().numpy(), -1.0, 1.0)


class _MlxKyutai:
    """Kyutai's own MLX implementation — the Apple-Silicon (Metal) path.

    Construction and generation transcribe ``moshi_mlx/run_tts.py`` (the
    upstream reference script) into library form: same files, same knobs,
    same CFG-distillation handling, same end-step trimming.

    Parameters
    ----------
    repo : str
        Hugging Face model repository (the same files as the torch path).
    voice_repo : str
        Hugging Face voice-embedding repository.
    cfg_coef, temp : float
        Classifier-free-guidance strength and sampling temperature.
    """

    def __init__(
        self,
        repo: str,
        voice_repo: str,
        cfg_coef: float,
        temp: float,
        quantize: int | None = None,
    ) -> None:
        import mlx.core as mx
        import mlx.nn as nn
        import sentencepiece
        from moshi_mlx import models
        from moshi_mlx.models.tts import TTSModel
        from moshi_mlx.utils.loaders import hf_get

        # The repo's config names every other file; all are fetched through
        # the HF cache (shared with the torch path — nothing downloads twice).
        raw_config = json.loads(Path(hf_get("config.json", repo)).read_text(encoding="utf-8"))
        mimi_weights = hf_get(raw_config["mimi_name"], repo)
        moshi_weights = hf_get(raw_config.get("moshi_name", "model.safetensors"), repo)
        tokenizer = hf_get(raw_config["tokenizer_name"], repo)

        # The language model, in bf16 on the Metal GPU (upstream's choice).
        lm_config = models.LmConfig.from_config_dict(raw_config)
        model = models.Lm(lm_config)
        model.set_dtype(mx.bfloat16)
        model.load_pytorch_weights(str(moshi_weights), lm_config, strict=True)

        # Optional weight quantization — the knob Kyutai's own on-device
        # deployments turn (run_tts.py --quantize). On an M2 Max the bf16
        # model misses real time by a wide margin; q8 is the operating point
        # that makes the Metal path worth having. Same layers as upstream.
        if quantize is not None:
            nn.quantize(model.depformer, bits=quantize)
            for layer in model.transformer.layers:
                nn.quantize(layer.self_attn, bits=quantize)
                nn.quantize(layer.gating, bits=quantize)

        # Text tokenizer (sentencepiece) and audio tokenizer (mimi).
        text_tokenizer = sentencepiece.SentencePieceProcessor(str(tokenizer))
        audio_tokenizer = models.mimi.Mimi(models.mimi_202407(lm_config.generated_codebooks))
        audio_tokenizer.load_pytorch_weights(str(mimi_weights), strict=True)

        self._model = TTSModel(
            model,
            audio_tokenizer,
            text_tokenizer,
            voice_repo=voice_repo,
            n_q=32,
            temp=temp,
            cfg_coef=cfg_coef,
            max_padding=8,
            initial_padding=2,
            final_padding=4,
            padding_bonus=0.0,
            raw_config=raw_config,
        )
        self._voice_repo = voice_repo
        # CFG-distilled checkpoints carry their guidance in the conditioning
        # (cfg_coef must then be 1.0 at generation); others apply it live.
        # This mirrors run_tts.py verbatim.
        self._cfg_coef_conditioning: float | None = None
        if self._model.valid_cfg_conditionings:
            self._cfg_coef_conditioning = self._model.cfg_coef
            self._model.cfg_coef = 1.0
            self._cfg_is_no_text = False
            self._cfg_is_no_prefix = False
        else:
            self._cfg_is_no_text = True
            self._cfg_is_no_prefix = True
        # Pin the upstream seed: sampled synthesis becomes reproducible run to
        # run, which the evaluation layer relies on.
        mx.random.seed(_MLX_SEED)

    @property
    def sample_rate(self) -> int:
        """Mimi's decoding rate in Hz."""
        return int(self._model.mimi.sample_rate)

    def generate(self, text: str, voice: str) -> Any:
        """Synthesise ``text`` with ``voice``; return mono float32 samples.

        Parameters
        ----------
        text : str
            The text to speak.
        voice : str
            Voice name in the voice repository (or a local ``.safetensors``).

        Returns
        -------
        numpy.ndarray
            1-D float32 samples in ``[-1, 1]`` at :attr:`sample_rate`.
        """
        import mlx.core as mx
        import numpy as np
        from moshi_mlx.utils.loaders import hf_get

        model = self._model
        entries = model.prepare_script([text], padding_between=1)

        # Voice conditioning: embedding-bank models (the 1.6B) take voice
        # paths; audio-prefix models take the recording itself as a prefix.
        prefixes: list[Any] | None = None
        if model.multi_speaker:
            voices = [model.get_voice_path(voice)]
        else:
            voices = []
            prefix_path = hf_get(voice, self._voice_repo, check_local_file_exists=True)
            prefixes = [model.get_prefix(prefix_path)]
        attributes = model.make_condition_attributes(voices, self._cfg_coef_conditioning)

        result = model.generate(
            [entries],
            [attributes],
            prefixes=prefixes,
            cfg_is_no_prefix=self._cfg_is_no_prefix,
            cfg_is_no_text=self._cfg_is_no_text,
        )

        # Decode the generated mimi frames to PCM, then trim at the model's
        # own end-of-utterance step (past it is only padding noise).
        pcm_frames = [model.mimi.decode_step(frame) for frame in result.frames]
        wavs = mx.concat(pcm_frames, axis=-1)
        mimi = model.mimi
        end_step = result.end_steps[0]
        if end_step is None:
            # The model never emitted its end token (very long input): keep
            # everything rather than guess a cut.
            wav_length = wavs.shape[-1]
        else:
            wav_length = int(mimi.sample_rate * (end_step + model.final_padding) / mimi.frame_rate)
        wav = wavs[0, :, :wav_length]
        if prefixes is not None:
            # Prefix-conditioned models replay the prefix first; drop it.
            start = int(mimi.sample_rate * prefixes[0].shape[-1] / mimi.frame_rate)
            wav = wav[:, start:]
        return np.asarray(mx.clip(wav, -1, 1)).reshape(-1).astype("float32")


class KyutaiEngine:
    """The Kyutai TTS backend: text in, native French (or English) out.

    Parameters
    ----------
    settings : Settings
        ``voice`` may name a voice from the ``kyutai/tts-voices`` repository
        (or a local ``.safetensors`` embedding path); empty picks the female
        default for the language. The ``kyutai`` mapping supplies the knobs:

        * ``repo`` — model repository (default :data:`DEFAULT_REPO`).
        * ``voice_repo`` — voice-embedding repository (default
          :data:`DEFAULT_VOICE_REPO`).
        * ``device`` — ``"auto"`` (default: Kyutai's MLX runtime on a Mac
          when installed, torch CPU elsewhere), ``"mlx"``, or a torch device.
        * ``dtype`` — torch path only: ``"float32"`` (default) or
          ``"bfloat16"``.
        * ``cfg_coef`` — classifier-free-guidance strength (default ``2.0``;
          higher follows the voice/text more strictly, at some audio-quality
          cost).
        * ``temp`` — sampling temperature (default ``0.6``, the upstream
          default).
        * ``quantize`` — MLX path only: weight-quantization bits (default
          ``8``, Kyutai's own on-device setting — measured RTF 0.84 vs 7.5
          unquantized on an M2 Max; ``null`` keeps full bf16).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._impl: Any = None
        self._lock = asyncio.Lock()
        # Backend knobs, with the upstream defaults spelled out once here.
        knobs = settings.kyutai or {}
        self._repo: str = str(knobs.get("repo") or DEFAULT_REPO)
        self._voice_repo: str = str(knobs.get("voice_repo") or DEFAULT_VOICE_REPO)
        self._device: str = str(knobs.get("device") or "auto")
        self._dtype: str = str(knobs.get("dtype") or "float32")
        self._cfg_coef: float = float(knobs.get("cfg_coef", 2.0))
        self._temp: float = float(knobs.get("temp", 0.6))
        # MLX path only: weight quantization bits (None = full bf16). The
        # default follows Kyutai's own on-device deployments (8 bits) because
        # the bf16 1.6B misses real time on Apple GPUs by a wide margin.
        raw_q = knobs.get("quantize", 8)
        self._quantize: int | None = None if raw_q in (None, "", "none") else int(raw_q)
        # Resolved once so health() can answer without loading anything.
        self._implementation: str = resolve_implementation(self._device)

    # -- lifecycle ----------------------------------------------------------

    async def _loaded(self) -> Any:
        """The implementation, loaded once on first use (see KokoroEngine)."""
        if self._impl is not None:
            return self._impl
        async with self._lock:
            if self._impl is None:
                self._impl = await asyncio.to_thread(self._load)
        return self._impl

    def _load(self) -> Any:
        """Build the resolved implementation. Blocking; called in a thread.

        The first call downloads the weights (~3 GB) from Hugging Face into
        the local cache; later calls load from disk and touch no network.
        Both implementations read the *same* cached files.
        """
        if check_install() != 0:
            raise RuntimeError(
                "no Kyutai runtime is installed (moshi / moshi-mlx). "
                "Install one with:\n"
                "    pip install 'speaker-helper[kyutai]'"
            )
        osh.info(
            "kyutai: loading %s as %s — first time downloads ~3 GB",
            self._repo,
            self._implementation,
        )
        if self._implementation == "mlx":
            return _MlxKyutai(
                self._repo, self._voice_repo, self._cfg_coef, self._temp, self._quantize
            )
        device = self._implementation.split(":", 1)[1]
        return _TorchKyutai(
            self._repo, self._voice_repo, device, self._dtype, self._cfg_coef, self._temp
        )

    async def aclose(self) -> None:
        """Drop the implementation so its runtime can free the weights."""
        self._impl = None

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
        impl = await self._loaded()

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
        samples = await asyncio.to_thread(impl.generate, text, chosen)
        compute_s = time.perf_counter() - started

        rate = impl.sample_rate
        if rate != SAMPLE_RATE_HZ:  # pragma: no cover - mimi is fixed at 24 kHz
            raise RuntimeError(
                f"Kyutai returned {rate} Hz but this wrapper lays audio out at "
                f"{SAMPLE_RATE_HZ} Hz; every cue after the first would be wrong"
            )

        # float32 [-1, 1] → int16 PCM, the same wrapping as the other backends.
        pcm = (np.clip(samples, -1.0, 1.0) * 32_767).astype(np.int16)

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
                name="CML-TTS 10087 enhanced (CC BY 4.0)",
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
                "reason": "no Kyutai runtime (moshi / moshi-mlx) is installed",
                "fix": "pip install 'speaker-helper[kyutai]'",
            }
        return {
            "status": "ok",
            "engine": "kyutai",
            "loaded": self._impl is not None,
            "repo": self._repo,
            "implementation": self._implementation,
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
