"""
Audio8: a compact realism-tuned cloner, offline, from a reference recording.

Module summary
--------------
Edge0's ``Audio8-TTS-Realistic`` (0.6B parameters, Apache-2.0, 23 languages
including French; arXiv 2610.14776) was trained SFT → GRPO on WER and speaker
similarity → GRPO on a *realism critic* that compares each output with a human
saying the same sentence in the same voice. It is the 2026-11 candidate for the
owner's offline case, where the brief is a voice that sounds alive, not a fast
one.

It renders by **cloning**: a reference recording *plus its exact transcript*
conditions every call. Without a reference the model picks a speaker of its
own, and measured on 2026-11-04 that speaker is male (median F0 139 Hz in
French, 163 Hz in English). So this backend always passes a reference, and by
default the bundled female one (``assets/ref-fr-female.wav`` + ``.txt``,
CC BY 4.0): with it the French output measured F0 274 Hz and a TitaNet
similarity of 0.72 to the reference.

One runtime, said plainly
-------------------------
Only the **MLX** path is wired: ``mlx-audio`` (≥ 0.6.4 — 0.6.1 fails to
dequantise the tied 4-bit embedding) running the community 4-bit conversion
``nativ-community/Audio8-TTS-Realistic-0.6b-4bit`` (~1.7 GB, cached once,
offline after). Upstream's PyTorch path needs ``transformers<5`` with
``trust_remote_code`` and has not been exercised here, so off a Mac this
backend reports itself unavailable instead of shipping untested code.

The codec decodes at 44.1 kHz; every other backend lays audio out at 24 kHz, so
the output is resampled — otherwise a narration mixing engines would carry
wrong cue times after the first segment.

There is **no phoneme input** and no streaming: pronunciation-lexicon entries
reach it through the respelling tier applied by
:class:`~speaker_helper.speaker.Speaker` (see :mod:`speaker_helper.lexicon`),
and each call returns one complete waveform.

Usage example
-------------
>>> from speaker_helper import Speaker, Settings
>>> # spk = Speaker(Settings.from_mapping({"backend": "audio8", "language": "fr"}))
>>> # await spk.say("Le rendez-vous est fixé au 14 novembre.")

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.util
import time
from pathlib import Path
from typing import Any

import os_helper as osh

from speaker_helper.config import Settings
from speaker_helper.types import AudioResult, Voice, VoiceList, VoiceSample

#: The rate this wrapper lays audio out at — the same as kokoro, chatterbox and
#: kyutai, so a narration can mix engines.
SAMPLE_RATE_HZ: int = 24_000

#: The codec's native rate; :func:`resample` bridges the two.
NATIVE_RATE_HZ: int = 44_100

#: The default model repository: the community MLX 4-bit conversion.
DEFAULT_REPO: str = "nativ-community/Audio8-TTS-Realistic-0.6b-4bit"

#: The oldest ``mlx-audio`` that loads the 4-bit checkpoint (0.6.1 raised a
#: matmul shape error on the tied embedding, measured 2026-11-04).
MIN_MLX_AUDIO: tuple[int, int, int] = (0, 6, 4)

#: Generation budget in codec frames. The model shares 2,048 positions between
#: text, reference and audio, and the runtime clamps to what is left; upstream's
#: 512 default stops at ~24 s (21.5 frames/s), shorter than one chunk can be.
DEFAULT_MAX_TOKENS: int = 2048

#: Fixed sampling seed, so a synthesis is reproducible run to run — the
#: evaluation layer compares takes, and a fresh draw each time is noise there.
DEFAULT_SEED: int = 0


def _version_tuple(raw: str) -> tuple[int, ...]:
    """Parse the leading numeric part of a version string.

    Examples
    --------
    >>> _version_tuple("0.6.4")
    (0, 6, 4)
    >>> _version_tuple("0.7.0rc1")
    (0, 7, 0)
    """
    parts: list[int] = []
    for piece in raw.split(".")[:3]:
        digits = "".join(ch for ch in piece if ch.isdigit()) or "0"
        parts.append(int(digits))
    return tuple(parts)


def install_problem() -> str:
    """Why this engine cannot run here, or ``""`` when it can.

    Returns
    -------
    str
        A one-line reason (not a Mac, ``mlx-audio`` missing or too old), empty
        when the MLX runtime is usable.
    """
    if not osh.macos():
        return "only the MLX (Apple Silicon) runtime is wired for this backend"
    if importlib.util.find_spec("mlx_audio") is None:
        return "mlx-audio is not installed"
    try:
        found = importlib.metadata.version("mlx-audio")
    except importlib.metadata.PackageNotFoundError:
        return "mlx-audio is not installed"
    if _version_tuple(found) < MIN_MLX_AUDIO:
        wanted = ".".join(str(n) for n in MIN_MLX_AUDIO)
        return f"mlx-audio {found} is too old to load Audio8 (needs >= {wanted})"
    return ""


def check_install() -> int:
    """Return 0 when the MLX runtime for Audio8 is usable."""
    return 0 if not install_problem() else 1


def resample(samples: Any, source_hz: int, target_hz: int) -> Any:
    """Band-limited resampling of a whole mono signal through the FFT.

    Offline synthesis hands over the complete waveform, so the exact spectral
    method costs nothing a streaming filter would save, and it keeps this
    backend free of a SciPy dependency.

    Parameters
    ----------
    samples : numpy.ndarray
        1-D float samples at ``source_hz``.
    source_hz, target_hz : int
        The two rates.

    Returns
    -------
    numpy.ndarray
        1-D float32 samples at ``target_hz``, the same duration.

    Examples
    --------
    >>> import numpy as np
    >>> resample(np.zeros(44_100), 44_100, 24_000).shape
    (24000,)
    """
    import numpy as np

    data = np.asarray(samples, dtype=np.float64).reshape(-1)
    if source_hz == target_hz or data.size == 0:
        return data.astype(np.float32)
    n_out = int(round(data.size * target_hz / source_hz))
    spectrum = np.fft.rfft(data)
    # Keep the bins both rates share (truncating = an ideal low-pass when
    # downsampling); irfft pads with zeros when upsampling.
    keep = min(spectrum.size, n_out // 2 + 1)
    out = np.fft.irfft(spectrum[:keep], n=n_out) * (n_out / data.size)
    return out.astype(np.float32)


def reference_transcript(audio: Path, *, language: str) -> str:
    """The transcript that must accompany a reference recording.

    Audio8 aligns the reference audio to its text, so a wrong or missing
    transcript degrades the clone instead of failing. Lookup order: the bundled
    reference's own transcript, a ``<stem>.txt`` beside the file, then
    :func:`~speaker_helper.transcription.ensure_transcript` (vocal-helper,
    cached as ``<file>.txt``).

    Parameters
    ----------
    audio : Path
        The reference recording.
    language : str
        ISO-639-1 hint for the ASR fallback.

    Returns
    -------
    str
        The transcript.

    Raises
    ------
    RuntimeError
        When no transcript is on disk and vocal-helper is not installed.
    """
    from speaker_helper.cloning import DEFAULT_CLONE_AUDIO, default_reference_text

    if audio == DEFAULT_CLONE_AUDIO:
        text = default_reference_text()
        if text:
            return text
    sibling = audio.with_suffix(".txt")
    if sibling.is_file():
        text = sibling.read_text(encoding="utf-8").strip()
        if text:
            return text
    from speaker_helper.transcription import ensure_transcript

    try:
        return ensure_transcript(audio, language=language)
    except ImportError as exc:
        raise RuntimeError(
            f"audio8 needs the exact transcript of {audio}: write it to "
            f"{sibling.name} beside the recording, or install vocal-helper "
            "(pip install 'speaker-helper[stt]') to derive it"
        ) from exc


class _MlxAudio8:
    """The ``mlx-audio`` implementation — the Apple-Silicon (Metal) path.

    Parameters
    ----------
    repo : str
        Hugging Face repository of an MLX conversion.
    """

    def __init__(self, repo: str) -> None:
        from mlx_audio.tts.utils import load

        self._model = load(repo)

    @property
    def sample_rate(self) -> int:
        """The codec's decoding rate in Hz."""
        return int(self._model.sample_rate)

    def generate(self, text: str, ref_audio: str, ref_text: str, **sampling: Any) -> Any:
        """Synthesise ``text`` in the voice of ``ref_audio``.

        Returns
        -------
        tuple of (numpy.ndarray, int)
            1-D float32 samples at :attr:`sample_rate`, and the number of codec
            frames generated (to detect a budget-truncated take).
        """
        import inspect

        import mlx.core as mx
        import numpy as np

        # Not every mlx-audio model takes a `seed`; seeding MLX's global RNG
        # makes the take reproducible either way.
        seed = sampling.pop("seed", None)
        if seed is not None:
            mx.random.seed(seed)
            if "seed" in inspect.signature(self._model.generate).parameters:
                sampling["seed"] = seed
        # A model may split long text into several results; one take is all of them.
        parts = list(
            self._model.generate(text=text, ref_audio=ref_audio, ref_text=ref_text, **sampling)
        )
        samples = np.concatenate([np.asarray(r.audio, dtype=np.float32).reshape(-1) for r in parts])
        return samples, max(int(getattr(r, "token_count", 0) or 0) for r in parts)


class Audio8Engine:
    """The Audio8 backend: text in, a cloned (female by default) voice out.

    Parameters
    ----------
    settings : Settings
        ``voice_sample`` (or a per-call ``voice``) names the reference
        recording; empty picks the bundled female reference. The ``audio8``
        mapping supplies the knobs:

        * ``repo`` — MLX model repository (default :data:`DEFAULT_REPO`).
        * ``temperature`` / ``top_p`` / ``top_k`` — sampling (upstream
          defaults ``0.7`` / ``0.9`` / ``50``).
        * ``seed`` — sampling seed (default ``0``; ``null`` draws fresh).
        * ``max_tokens`` — codec-frame budget (default ``2048``, clamped by
          the runtime to what the context leaves).
    """

    #: Backend name, settings section and pip extra.
    ENGINE: str = "audio8"
    #: Default model repository and its rough download size (for the log line).
    DEFAULT_REPO_ID: str = DEFAULT_REPO
    DOWNLOAD_SIZE: str = "~1.7 GB"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._impl: Any = None
        self._lock = asyncio.Lock()
        knobs = getattr(settings, self.ENGINE, {}) or {}
        self._repo: str = str(knobs.get("repo") or self.DEFAULT_REPO_ID)
        self._sampling: dict[str, Any] = self._sampling_from(knobs)
        # Always a reference: the model's own speaker measured male, and the
        # project's contract is a female voice in every language.
        from speaker_helper.cloning import DEFAULT_CLONE_AUDIO

        raw = getattr(settings, "voice_sample", "") or ""
        self._reference: Path = Path(raw) if raw else DEFAULT_CLONE_AUDIO
        # Transcripts cached per recording: the ASR fallback is not free.
        self._transcripts: dict[Path, str] = {}

    def _sampling_from(self, knobs: dict[str, Any]) -> dict[str, Any]:
        """Sampling keywords for ``generate``, upstream defaults spelled out."""
        raw_seed = knobs.get("seed", DEFAULT_SEED)
        return {
            "temperature": float(knobs.get("temperature", 0.7)),
            "top_p": float(knobs.get("top_p", 0.9)),
            "top_k": int(knobs.get("top_k", 50)),
            "max_tokens": int(knobs.get("max_tokens", DEFAULT_MAX_TOKENS)),
            "seed": None if raw_seed in (None, "", "none") else int(raw_seed),
        }

    def _language_kwargs(self, language: str) -> dict[str, Any]:
        """Per-call keywords naming the language; Audio8 reads it from the text."""
        return {}

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
        """Build the MLX implementation. Blocking; called in a thread."""
        problem = install_problem()
        if problem:
            raise RuntimeError(
                f"{self.ENGINE} cannot run here: {problem}. On a Mac, install with:\n"
                f"    pip install 'speaker-helper[{self.ENGINE}]'"
            )
        osh.info(
            "%s: loading %s — first time downloads %s", self.ENGINE, self._repo, self.DOWNLOAD_SIZE
        )
        return _MlxAudio8(self._repo)

    async def aclose(self) -> None:
        """Drop the implementation so MLX can free the weights."""
        self._impl = None

    def _transcript_for(self, audio: Path, language: str) -> str:
        """The (cached) transcript of ``audio``; see :func:`reference_transcript`."""
        if audio not in self._transcripts:
            self._transcripts[audio] = reference_transcript(audio, language=language)
        return self._transcripts[audio]

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
            Recorded on the result and used as the ASR hint for a reference
            transcript; the model itself reads the language from the text.
        voice : str or None
            Path to a reference recording for this call; empty keeps the
            configured (or bundled female) reference.

        Raises
        ------
        ValueError
            If ``text`` is empty or whitespace-only.
        """
        import numpy as np

        if not text or not text.strip():
            raise ValueError("cannot synthesise empty text")
        lang = ((language or self._settings.language or "fr").strip().lower()).split("-")[0]
        reference = Path(voice) if voice else self._reference
        if not reference.is_file():
            raise FileNotFoundError(f"{self.ENGINE}: reference recording not found: {reference}")
        ref_text = await asyncio.to_thread(self._transcript_for, reference, lang)
        impl = await self._loaded()

        started = time.perf_counter()
        samples, frames = await asyncio.to_thread(
            impl.generate,
            text,
            str(reference),
            ref_text,
            **self._sampling,
            **self._language_kwargs(lang),
        )
        compute_s = time.perf_counter() - started
        budget = self._sampling.get("max_tokens")
        if budget and frames >= budget:
            # The take ran into its budget instead of ending on the model's own
            # stop token: the tail of the text is missing. Said, not hidden.
            osh.warning(
                "%s: generation hit its %d-frame budget; the end of %r may be cut",
                self.ENGINE,
                budget,
                text[:60],
            )

        samples = resample(samples, impl.sample_rate, SAMPLE_RATE_HZ)
        pcm = (np.clip(samples, -1.0, 1.0) * 32_767).astype(np.int16)

        from speaker_helper.backends.kokoro import pcm_to_wav_bytes

        return AudioResult(
            wav_bytes=pcm_to_wav_bytes(pcm, SAMPLE_RATE_HZ),
            sample_rate=SAMPLE_RATE_HZ,
            duration_s=len(pcm) / float(SAMPLE_RATE_HZ),
            compute_s=compute_s,
            text=text,
            voice_id=reference.stem,
            language=lang,
        )

    async def list_voices(self, engine: str | None = None) -> VoiceList:
        """One entry: the reference this engine will actually clone.

        Same contract as the chatterbox backend: the bundled reference is named
        with its provenance and its gender; somebody else's recording is named
        by file, and its gender left to them.
        """
        from speaker_helper.cloning import DEFAULT_CLONE_AUDIO, DEFAULT_CLONE_NAME

        language = self._settings.language
        if self._reference == DEFAULT_CLONE_AUDIO:
            voice = Voice(
                voice_id=DEFAULT_CLONE_NAME,
                name="Bundled female reference — CML-TTS (CC BY 4.0)",
                language=language,
                gender="female",
                engine=self.ENGINE,
            )
        else:
            voice = Voice(
                voice_id=self._reference.stem,
                name=f"Cloned from {self._reference.name}",
                language=language,
                gender="",
                engine=self.ENGINE,
            )
        return VoiceList(engine=self.ENGINE, voices=[voice])

    async def health(self) -> dict:
        """Whether this engine could synthesise, without loading the model."""
        problem = install_problem()
        if problem:
            return {
                "status": "unavailable",
                "engine": self.ENGINE,
                "reason": problem,
                "fix": f"pip install 'speaker-helper[{self.ENGINE}]' (macOS, Apple Silicon)",
            }
        return {
            "status": "ok",
            "engine": self.ENGINE,
            "loaded": self._impl is not None,
            "repo": self._repo,
            "implementation": "mlx",
            "reference": str(self._reference),
            "sample_rate": SAMPLE_RATE_HZ,
        }

    async def clone_voice(
        self,
        name: str,
        samples: list[VoiceSample],
        *,
        language: str | None = None,
    ) -> str:
        """Adopt the first sample, with its transcript, as the reference.

        As with chatterbox there is no enrolment: the model conditions on the
        recording at generation time, so the honest return value is the path.
        Audio8 also needs what the recording says; an empty ``reference_text``
        falls back to :func:`reference_transcript`.
        """
        if not samples:
            raise ValueError("cloning needs at least one reference recording")
        first = samples[0]
        if isinstance(first.audio, str):
            reference = Path(first.audio)
        else:
            # The model takes a path, not bytes; kept on disk (not a temporary
            # a later generate() would find deleted), as in the chatterbox one.
            import tempfile

            handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            handle.write(first.read_bytes())
            handle.close()
            reference = Path(handle.name)
        if first.reference_text.strip():
            self._transcripts[reference] = first.reference_text.strip()
        else:
            lang = (language or self._settings.language or "fr").split("-")[0]
            self._transcripts[reference] = await asyncio.to_thread(
                reference_transcript, reference, language=lang
            )
        self._reference = reference
        return str(reference)


#: Qwen3-TTS names languages in words; anything unlisted is left to "auto".
QWEN3_LANGUAGE_NAMES: dict[str, str] = {
    "fr": "french",
    "en": "english",
    "de": "german",
    "es": "spanish",
    "it": "italian",
    "pt": "portuguese",
    "ru": "russian",
    "zh": "chinese",
    "ja": "japanese",
    "ko": "korean",
}


class Qwen3TTSEngine(Audio8Engine):
    """Qwen3-TTS 0.6B (Apache-2.0) through the same MLX cloning contract.

    Measured on 2026-11-04 (M2 Max, 8-bit, the bundled female reference, a
    two-sentence French paragraph): the closest clone of any engine here
    (TitaNet similarity 0.82, F0 233 Hz, transcript exact), sustained
    streaming RTF 0.77–0.90 and first audio after ~0.7–0.9 s. That sits on the
    router's 0.8 real-time ceiling rather than under it, and its public Elo is
    below kokoro's, so it is a candidate for the owner's ear, not a route.

    Same knobs as :class:`Audio8Engine` under ``settings.qwen3tts``, except
    that sampling defaults are the model's own (only what you set is sent).
    The codec decodes at 24 kHz, so nothing is resampled.

    Caveat met while measuring: on an exFAT/external Hugging Face cache, macOS
    AppleDouble files (``._model.safetensors``) make mlx-audio's loader fail
    with "Invalid json header length"; ``dot_clean`` on the cache fixes it.
    """

    ENGINE = "qwen3tts"
    DEFAULT_REPO_ID = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit"
    DOWNLOAD_SIZE = "~2 GB"

    def _sampling_from(self, knobs: dict[str, Any]) -> dict[str, Any]:
        """Only the knobs the caller set; the model's config holds its defaults."""
        sampling: dict[str, Any] = {}
        for key, cast in (("temperature", float), ("top_p", float), ("top_k", int)):
            if knobs.get(key) is not None:
                sampling[key] = cast(knobs[key])
        if knobs.get("max_tokens") is not None:
            sampling["max_tokens"] = int(knobs["max_tokens"])
        raw_seed = knobs.get("seed", DEFAULT_SEED)
        sampling["seed"] = None if raw_seed in (None, "", "none") else int(raw_seed)
        return sampling

    def _language_kwargs(self, language: str) -> dict[str, Any]:
        """Qwen3-TTS wants the language by name (``"french"``)."""
        return {"lang_code": QWEN3_LANGUAGE_NAMES.get(language, "auto")}
