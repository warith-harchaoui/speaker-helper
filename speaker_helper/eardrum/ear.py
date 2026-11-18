"""
The ear: a phoneme recogniser that writes what it hears, not what it expects.

Module summary
--------------
A speech-to-text model is the wrong ear for this job. Whisper has a language
model inside: a badly pronounced "GitHub" comes back spelled "GitHub", because
that is the likeliest word, and the loop would believe the engine got it
right. A **phoneme** recogniser has no dictionary to fall back on: it writes
the sounds.

The default ear is ``facebook/wav2vec2-xlsr-53-espeak-cv-ft`` — wav2vec2
XLSR-53 (pretrained on 53 languages) fine-tuned on Common Voice to output
espeak-style IPA, which is the very alphabet the targets are written in.
Greedy CTC decoding gives each phone a 20 ms frame span, which is what lets
the report cut the word's own clip out of the carrier sentence.

Where the weights come from, first match wins:

1. ``SPEAKER_HELPER_PHONEME_MODEL`` — a directory holding the model;
2. ``$SPEAKER_ENGINES_DIR/metrics/phonemes/wav2vec2-xlsr-53-espeak-cv-ft``
   (the self-hosted bundle);
3. ``~/.cache/speaker-helper/eardrum/wav2vec2-xlsr-53-espeak-cv-ft`` — what
   ``speaker-helper install-voice --engine eardrum`` fills;
4. the Hugging Face cache, read with ``local_files_only`` (never a download
   at run time).

Usage example
-------------
>>> from speaker_helper.eardrum.ear import collapse_ctc
>>> collapse_ctc([0, 5, 5, 0, 7, 7, 7, 0], blank=0)
[(5, 1, 3), (7, 4, 7)]

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from speaker_helper.eardrum.phones import tokenize

#: The recogniser's name, on the hub and as the local directory name.
PHONEME_MODEL = "facebook/wav2vec2-xlsr-53-espeak-cv-ft"

#: The exact revision the loop was measured with (pinned, so two machines
#: installing a month apart hear with the same ear).
PHONEME_REVISION = "2c733782da5604684829819a5eb744c193fe9398"

#: The local directory ``install-voice --engine eardrum`` fills.
PHONEME_CACHE: Path = (
    Path.home() / ".cache" / "speaker-helper" / "eardrum" / PHONEME_MODEL.split("/")[1]
)

#: wav2vec2 reads 16 kHz audio and emits one frame every 320 samples.
SAMPLE_RATE = 16000
FRAME_S = 320 / SAMPLE_RATE


@dataclass
class HeardPhone:
    """One phone the ear heard, with when it was heard.

    Attributes
    ----------
    phone : str
        The phone (already through :func:`~speaker_helper.eardrum.phones.tokenize`).
    start_s, end_s : float
        Its span in the audio, in seconds.
    """

    phone: str
    start_s: float
    end_s: float


class Ear(Protocol):
    """Anything that turns audio into heard phones."""

    def hear(self, wav_bytes: bytes) -> list[HeardPhone]:
        """Recognise the phones in an encoded audio payload.

        Parameters
        ----------
        wav_bytes : bytes
            WAV (or anything ``soundfile`` reads).

        Returns
        -------
        list of HeardPhone
            The phones, in order.
        """
        ...


def collapse_ctc(ids: list[int], blank: int) -> list[tuple[int, int, int]]:
    """Greedy CTC collapse: merge repeats, drop blanks, keep frame spans.

    Parameters
    ----------
    ids : list of int
        The argmax token id of each frame.
    blank : int
        The CTC blank (pad) id.

    Returns
    -------
    list of (int, int, int)
        ``(token_id, first_frame, end_frame)`` per emitted token, ``end``
        exclusive.
    """
    out: list[tuple[int, int, int]] = []
    previous = None
    for frame, token in enumerate(ids):
        if token == previous:
            if token != blank and out:
                out[-1] = (token, out[-1][1], frame + 1)
            continue
        previous = token
        if token != blank:
            out.append((token, frame, frame + 1))
    return out


def model_dir() -> str:
    """Where the phoneme recogniser's weights are read from.

    Returns
    -------
    str
        A local directory, or the hub id (resolved from the Hugging Face
        cache with ``local_files_only``).
    """
    explicit = os.environ.get("SPEAKER_HELPER_PHONEME_MODEL", "").strip()
    if explicit:
        return explicit
    bundle = os.environ.get("SPEAKER_ENGINES_DIR", "").strip()
    if bundle:
        candidate = Path(bundle) / "metrics" / "phonemes" / PHONEME_CACHE.name
        if (candidate / "config.json").is_file():
            return str(candidate)
    if (PHONEME_CACHE / "config.json").is_file():
        return str(PHONEME_CACHE)
    return PHONEME_MODEL


def check_install() -> int:
    """``0`` when the ear can load, ``1`` otherwise (for ``health``-style checks).

    Returns
    -------
    int
        A process exit code.
    """
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return 1
    where = model_dir()
    if where != PHONEME_MODEL:
        return 0
    try:
        from huggingface_hub import hf_hub_download

        # The files the model needs, not the whole repository: a cache filled
        # with only these (README and .gitattributes left out) is complete.
        for filename in ("config.json", "vocab.json", "pytorch_model.bin"):
            hf_hub_download(PHONEME_MODEL, filename, local_files_only=True)
    except Exception:  # noqa: BLE001 - not in the cache, whatever the reason
        return 1
    return 0


class PhonemeEar:
    """The wav2vec2 espeak-phoneme recogniser, loaded once and reused.

    Parameters
    ----------
    source : str or None
        Model directory or hub id; :func:`model_dir` when ``None``.
    """

    def __init__(self, source: str | None = None) -> None:
        """Remember where the weights are; loading waits for the first use.

        Parameters
        ----------
        source : str or None
            See the class docstring.
        """
        self.source = source or model_dir()
        self._model: Any = None
        self._processor: Any = None

    def _load(self) -> None:
        """Load the processor and model (CPU, eval mode).

        Raises
        ------
        ImportError
            When the ``eardrum`` extra (torch + transformers) is missing.
        OSError
            When the weights are nowhere to be found; the message says how
            to fetch them.
        """
        try:
            from transformers import AutoProcessor, Wav2Vec2ForCTC
        except ImportError as exc:  # pragma: no cover - only without the extra
            raise ImportError(
                "the Ralph Eardrum Loop needs torch + transformers: "
                "pip install 'speaker-helper[eardrum]'"
            ) from exc
        offline = self.source == PHONEME_MODEL
        try:
            self._processor = AutoProcessor.from_pretrained(self.source, local_files_only=offline)
            self._model = Wav2Vec2ForCTC.from_pretrained(
                self.source, local_files_only=offline
            ).eval()
        except OSError as exc:
            raise OSError(
                f"the phoneme recogniser is not installed ({exc}). Fetch it once "
                "with: speaker-helper install-voice --engine eardrum"
            ) from exc

    def hear(self, wav_bytes: bytes) -> list[HeardPhone]:
        """Recognise the phones in ``wav_bytes``; see :class:`Ear`.

        Parameters
        ----------
        wav_bytes : bytes
            Encoded audio.

        Returns
        -------
        list of HeardPhone
            The phones, with 20 ms-resolution spans.
        """
        import numpy as np
        import soundfile as sf
        import torch
        import torchaudio

        if self._model is None:
            self._load()
        data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=True)
        mono = torch.from_numpy(np.ascontiguousarray(data.mean(axis=1)))
        if sr != SAMPLE_RATE:
            # A proper band-limited resample: the recogniser is sensitive to
            # the aliasing a nearest-neighbour one would add.
            mono = torchaudio.functional.resample(mono, sr, SAMPLE_RATE)
        inputs = self._processor(mono.numpy(), sampling_rate=SAMPLE_RATE, return_tensors="pt")
        with torch.no_grad():
            logits = self._model(inputs.input_values).logits[0]
        ids = logits.argmax(dim=-1).tolist()
        tokenizer = self._processor.tokenizer
        heard: list[HeardPhone] = []
        for token_id, start, end in collapse_ctc(ids, blank=tokenizer.pad_token_id):
            token = tokenizer.convert_ids_to_tokens(token_id)
            if token in (tokenizer.unk_token, tokenizer.pad_token, "|", "</s>", "<s>"):
                continue
            # A vocabulary token can hold several phones (``aɪ``, ``ts``):
            # each gets an equal share of the token's span.
            phones = tokenize(token)
            if not phones:
                continue
            step = (end - start) / len(phones)
            for k, phone in enumerate(phones):
                heard.append(
                    HeardPhone(
                        phone=phone,
                        start_s=(start + k * step) * FRAME_S,
                        end_s=(start + (k + 1) * step) * FRAME_S,
                    )
                )
        return heard
