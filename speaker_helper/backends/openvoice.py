"""
OpenVoice v2: clone a voice from a short recording.

Module summary
--------------
OpenVoice splits the job in two, and that split is why it clones well from
very little audio. A *base speaker* model produces the speech — the words, the
prosody, the style — and a *tone colour converter* then morphs that speech
onto the timbre of a target speaker, taken from an embedding extracted from a
reference recording. Six to sixty seconds of clean speech is enough, because
the reference only has to supply timbre; it never has to teach the model to
talk.

The practical consequence is in the error messages below: there are two
checkpoints and an extracted embedding, and they fail at three different
moments. Telling them apart is most of what this wrapper does beyond calling
the model.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio
import importlib
import json
import time
from pathlib import Path
from typing import Any

from speaker_helper.config import Settings
from speaker_helper.types import AudioResult, Voice, VoiceList, VoiceSample

#: OpenVoice v2 produces 24 kHz mono; kept, so narration can lay its output
#: out beside another engine's without resampling.
SAMPLE_RATE_HZ: int = 24_000

#: Where the installer puts the checkpoints and the little config that points
#: at them. This package's cache first, then sprezzature's — the same two
#: downloads, and no reason to fetch them twice.
CACHE_CANDIDATES: tuple[Path, ...] = (
    Path.home() / ".cache" / "speaker-helper" / "openvoice",
    Path.home() / ".cache" / "sprezzature-skill" / "openvoice",
)

#: A segment's ``emotion`` → the style the base speaker recognises. Anything
#: outside this set reads as ``default`` rather than failing: a document is
#: free to ask for a mood this model has never heard of.
EMOTION_STYLE: dict[str, str] = {
    "neutral": "default",
    "cheerful": "cheerful",
    "friendly": "friendly",
    "warm": "friendly",
    "sad": "sad",
    "angry": "angry",
    "terrified": "terrified",
    "whispering": "whispering",
    "shouting": "shouting",
    "excited": "excited",
    "enthusiastic": "excited",
}


def config_path() -> Path | None:
    """The installer's ``config.json``, or ``None`` when nothing is installed."""
    for root in CACHE_CANDIDATES:
        candidate = root / "config.json"
        if candidate.is_file():
            return candidate
    return None


def check_install() -> int:
    """Return 0 when this engine could synthesise, 1 otherwise.

    Two questions, because they fail at different times and have different
    answers: the package may be importable while the checkpoints were never
    fetched, and no amount of ``pip install`` fixes the second.
    """
    try:
        importlib.import_module("openvoice")
    except ImportError:
        return 1
    return 0 if config_path() else 1


class OpenVoiceEngine:
    """The OpenVoice v2 backend: a base speaker plus a tone colour converter.

    Parameters
    ----------
    settings : Settings
        ``voice_sample`` names the recording to clone. Without one, the
        built-in base speaker reads in its own timbre.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._parts: dict[str, Any] | None = None
        self._lock = asyncio.Lock()
        raw = getattr(settings, "voice_sample", "") or ""
        self._reference: Path | None = Path(raw) if raw else None
        self._target_embedding: Any = None

    async def _loaded(self) -> dict[str, Any]:
        """Both models and the config, loaded once on first use."""
        if self._parts is not None:
            return self._parts
        async with self._lock:
            if self._parts is None:
                self._parts = await asyncio.to_thread(self._load)
        return self._parts

    def _load(self) -> dict[str, Any]:
        """Build the two models from the installed checkpoints."""
        try:
            api = importlib.import_module("openvoice.api")
            se_extractor = importlib.import_module("openvoice.se_extractor")
        except ImportError as exc:
            raise RuntimeError(
                "openvoice is not installed. Install it with:\n"
                "    pip install 'speaker-helper[openvoice]'"
            ) from exc

        found = config_path()
        if found is None:
            raise RuntimeError(
                f"OpenVoice's checkpoints are not on this machine. Looked in "
                f"{', '.join(str(p) for p in CACHE_CANDIDATES)}.\n"
                f"Fetch them with:\n"
                f"    speaker-helper install-voice --engine openvoice"
            )
        cfg = json.loads(found.read_text(encoding="utf-8"))
        device = cfg.get("device", "cpu")

        base_dir = Path(cfg["base_speakers_dir"])
        base = api.BaseSpeakerTTS(str(base_dir / "config.json"), device=device)
        base.load_ckpt(str(base_dir / "checkpoint.pth"))

        converter_ckpt = Path(cfg["converter_ckpt"])
        converter = api.ToneColorConverter(
            str(converter_ckpt.parent / "config.json"), device=device
        )
        converter.load_ckpt(str(converter_ckpt))

        target = None
        if self._reference is not None:
            target, _ = se_extractor.get_se(str(self._reference), converter, vad=True)
        return {
            "base": base,
            "converter": converter,
            "config": cfg,
            "target_se": target,
        }

    async def aclose(self) -> None:
        """Drop both models so torch can free them."""
        self._parts = None

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
        """Synthesise one piece of text, in the cloned timbre when there is one."""
        import numpy as np

        parts = await self._loaded()
        cfg = parts["config"]
        style = EMOTION_STYLE.get(emotion, "default")

        started = time.perf_counter()
        spoken = await asyncio.to_thread(
            parts["base"].tts,
            text=text,
            speaker=voice or self._settings.voice or "default",
            language=cfg.get("default_language", "English"),
            style=style,
            speed=speed,
            sdp_ratio=cfg.get("sdp_ratio", 0.2),
        )
        if parts["target_se"] is not None:
            # Morph the delivery onto the reference speaker's timbre. Skipped
            # entirely without a reference: running the converter from the
            # base speaker onto itself is a round trip through a vocoder that
            # can only lose.
            spoken = await asyncio.to_thread(
                parts["converter"].convert,
                audio_src_path=None,
                src_se=cfg["default_source_se"],
                tgt_se=parts["target_se"],
                output_path=None,
                tau=cfg.get("tau", 0.3),
                audio_np=spoken,
            )
        compute_s = time.perf_counter() - started

        pcm = np.asarray(spoken)
        if pcm.dtype != np.int16:
            pcm = (np.clip(pcm, -1.0, 1.0) * 32_767).astype(np.int16)

        from speaker_helper.backends.kokoro import pcm_to_wav_bytes

        return AudioResult(
            wav_bytes=pcm_to_wav_bytes(pcm, SAMPLE_RATE_HZ),
            sample_rate=SAMPLE_RATE_HZ,
            duration_s=len(pcm) / float(SAMPLE_RATE_HZ),
            compute_s=compute_s,
            text=text,
            voice_id=voice or (self._reference.name if self._reference else "base"),
            language=language or self._settings.language,
        )

    async def list_voices(self, engine: str | None = None) -> VoiceList:
        """The base speakers the installed checkpoint ships with."""
        found = config_path()
        names: list[str] = []
        if found is not None:
            cfg = json.loads(found.read_text(encoding="utf-8"))
            names = list(cfg.get("base_speakers", ["default"]))
        return VoiceList(
            engine="openvoice",
            voices=[
                Voice(
                    voice_id=name,
                    name=name,
                    language=self._settings.language,
                    engine="openvoice",
                )
                for name in (names or ["default"])
            ],
        )

    async def health(self) -> dict:
        """Which of the two halves is missing, named separately."""
        try:
            importlib.import_module("openvoice")
        except ImportError:
            return {
                "status": "unavailable",
                "engine": "openvoice",
                "reason": "openvoice is not installed",
                "fix": "pip install 'speaker-helper[openvoice]'",
            }
        found = config_path()
        if found is None:
            return {
                "status": "unavailable",
                "engine": "openvoice",
                "reason": "the checkpoints are not on this machine",
                "fix": "speaker-helper install-voice --engine openvoice",
            }
        return {
            "status": "ok",
            "engine": "openvoice",
            "loaded": self._parts is not None,
            "checkpoints": str(found.parent),
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
        """Extract the timbre of ``samples`` and speak in it from now on.

        Idempotent on the reference, not on ``name``: the embedding is derived
        from the recording, so handing the same file a second time produces
        the same voice and re-extracting it would only cost time.
        """
        if not samples:
            raise ValueError("cloning needs at least one reference recording")
        first = samples[0]
        if isinstance(first.audio, str):
            reference = Path(first.audio)
        else:
            import tempfile

            handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            handle.write(first.read_bytes())
            handle.close()
            reference = Path(handle.name)

        if reference != self._reference:
            self._reference = reference
            # Force a reload: the embedding is extracted during _load, and
            # keeping the old models would keep the old timbre.
            self._parts = None
        return str(reference)
