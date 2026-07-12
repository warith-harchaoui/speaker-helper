"""
Voice-cloning defaults and sample resolution.

Module summary
--------------
Cloning a voice means "here is a recording of the voice I want, use it". This
module makes that easy and uniform across the library, CLI, and REST API by
turning a small, permissive *clone configuration* into a concrete list of
:class:`~speaker_helper.types.VoiceSample`.

A ready-to-use default ships with the project: ``assets/ref-malo.wav`` and its
transcript ``assets/ref-malo.txt`` (produced with ``vocal-helper``). So enabling
cloning with no further input clones that reference voice; any field can be
overridden.

The clone configuration is a plain mapping (mirroring ``settings.clone``) so it
travels unchanged through YAML, environment, CLI flags, and JSON request bodies:

* ``name`` — profile name for the clone (idempotency key). Default ``ref-malo``.
* ``audio`` — path to a reference recording. Default the bundled ref-malo file.
* ``reference_text`` — transcript of ``audio``. Default the bundled transcript.
* ``samples`` — an explicit list of ``{audio, reference_text}`` objects; when
  present it takes precedence over the single ``audio``/``reference_text`` pair
  (use it to clone from several recordings).

Usage example
-------------
>>> from speaker_helper.cloning import resolve_samples
>>> samples = resolve_samples({})          # the bundled ref-malo reference
>>> samples[0].reference_text[:11]
'Je m'appell'

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from speaker_helper.types import VoiceSample

# The bundled default reference voice. Assets live at the repository root (they
# are development/operational data, not importable code), so we resolve relative
# to the package's parent directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLONE_NAME = "ref-malo"
DEFAULT_CLONE_AUDIO = _REPO_ROOT / "assets" / "ref-malo.wav"
DEFAULT_CLONE_TEXT_FILE = _REPO_ROOT / "assets" / "ref-malo.txt"


def default_reference_text() -> str:
    """Return the bundled ref-malo transcript, or ``""`` if it is missing."""
    try:
        return DEFAULT_CLONE_TEXT_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def clone_name(clone: dict[str, Any]) -> str:
    """Return the profile name for a clone configuration (default ``ref-malo``)."""
    return str(clone.get("name") or DEFAULT_CLONE_NAME)


def resolve_samples(clone: dict[str, Any]) -> list[VoiceSample]:
    """Turn a clone configuration mapping into concrete voice samples.

    Parameters
    ----------
    clone : dict
        The clone configuration (see the module docstring). An empty mapping
        yields the single bundled ref-malo reference.

    Returns
    -------
    list of VoiceSample
        One or more samples ready to upload to a cloning engine.

    Raises
    ------
    ValueError
        If an explicit ``samples`` entry lacks an ``audio`` field, or if the
        resolved default reference audio does not exist on disk.

    Notes
    -----
    A sample's ``reference_text`` falls back to the bundled default transcript
    only for the bundled default audio; a custom audio with no transcript keeps
    an empty string (the engine may reject it — supply the transcript).
    """
    explicit = clone.get("samples")
    if explicit:
        samples: list[VoiceSample] = []
        for i, item in enumerate(explicit):
            audio = item.get("audio")
            if not audio:
                raise ValueError(f"clone.samples[{i}] is missing 'audio'")
            samples.append(VoiceSample(
                audio=audio, reference_text=str(item.get("reference_text", ""))))
        return samples

    audio = clone.get("audio") or str(DEFAULT_CLONE_AUDIO)
    is_default_audio = str(audio) == str(DEFAULT_CLONE_AUDIO)
    reference_text = clone.get("reference_text")
    if reference_text is None:
        reference_text = default_reference_text() if is_default_audio else ""

    if is_default_audio and not DEFAULT_CLONE_AUDIO.is_file():
        raise ValueError(
            f"default clone reference not found: {DEFAULT_CLONE_AUDIO}. "
            "Provide clone.audio explicitly or restore the bundled asset."
        )
    return [VoiceSample(audio=str(audio), reference_text=str(reference_text))]


def fill_missing_transcripts(
    samples: list[VoiceSample], *, language: str = "fr",
) -> list[VoiceSample]:
    """Fill any empty ``reference_text`` by transcribing the audio.

    This is the canonical "add a voice to clone" path: the caller supplies only
    a recording, and its transcript is derived with ``vocal-helper`` (cached in a
    ``.txt`` sidecar for file-backed samples). Samples that already carry a
    transcript are returned untouched.

    Parameters
    ----------
    samples : list of VoiceSample
        Samples, some possibly without a transcript.
    language : str
        ISO-639-1 language hint passed to ASR.

    Returns
    -------
    list of VoiceSample
        Samples all carrying a non-empty ``reference_text`` (unless ASR itself
        returned nothing).

    Notes
    -----
    Imported lazily so ``vocal-helper`` stays an optional dependency: it is only
    required when a sample actually lacks a transcript.
    """
    from speaker_helper.transcription import ensure_transcript, transcribe_bytes

    filled: list[VoiceSample] = []
    for s in samples:
        if s.reference_text.strip():
            filled.append(s)
            continue
        if isinstance(s.audio, str):
            text = ensure_transcript(s.audio, language=language)
        else:
            text = transcribe_bytes(s.audio, language=language)
        filled.append(VoiceSample(audio=s.audio, reference_text=text))
    return filled
