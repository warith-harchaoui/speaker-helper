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
            samples.append(
                VoiceSample(audio=audio, reference_text=str(item.get("reference_text", "")))
            )
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


# Cloning engines cap reference-audio length (Voicebox: 30 s). We trim to a
# little under that so a longer recording is still usable out of the box.
DEFAULT_MAX_REFERENCE_SECONDS = 28.0


def _trim_to_bytes(wav_bytes: bytes, max_seconds: float) -> tuple[bytes, bool]:
    """Trim audio to ``max_seconds`` if longer, returning ``(bytes, trimmed)``.

    Uses ``audio-helper`` for duration and slicing (the ecosystem's audio path).
    Because ``audio-helper`` works on files, the in-memory payload is bridged
    through an ``os-helper`` temporary folder.
    """
    import audio_helper as ah
    import os_helper as osh

    with osh.temporary_folder() as tmp:
        src = osh.join(tmp, "reference.wav")
        Path(src).write_bytes(wav_bytes)
        if ah.get_audio_duration(src) <= max_seconds:
            return wav_bytes, False
        clipped = ah.extract_audio_chunk(
            src, 0.0, max_seconds, output_audio_filename=osh.join(tmp, "clip.wav")
        )
        return Path(clipped).read_bytes(), True


def prepare_samples(
    samples: list[VoiceSample],
    *,
    language: str = "fr",
    max_seconds: float = DEFAULT_MAX_REFERENCE_SECONDS,
) -> list[VoiceSample]:
    """Make samples engine-ready: trim over-long audio and fill transcripts.

    This is the canonical "add a voice to clone" path — supply only a recording
    and it just works:

    * **Trim.** Audio longer than ``max_seconds`` is trimmed to that length so it
      clears the engine's reference-length cap. Because trimming changes what is
      said, the transcript is then re-derived from the trimmed audio.
    * **Transcribe.** Any sample still lacking a transcript is transcribed with
      ``vocal-helper`` (cached in a ``.txt`` sidecar for file-backed samples).

    Parameters
    ----------
    samples : list of VoiceSample
        Reference samples (audio as bytes or a file path).
    language : str
        ISO-639-1 language hint passed to ASR.
    max_seconds : float
        Maximum reference-audio length; longer audio is trimmed.

    Returns
    -------
    list of VoiceSample
        Samples with in-memory audio (bytes) and a matching, non-empty
        ``reference_text``.

    Notes
    -----
    ``soundfile`` and ``vocal-helper`` are imported lazily so importing this
    module stays cheap and ``vocal-helper`` is only required when a transcript
    must actually be derived.
    """
    from speaker_helper.transcription import ensure_transcript, transcribe_bytes

    prepared: list[VoiceSample] = []
    for s in samples:
        raw, trimmed = _trim_to_bytes(s.read_bytes(), max_seconds)
        if trimmed:
            # Trimming invalidates any supplied transcript, so re-transcribe the
            # trimmed segment to keep audio and text aligned.
            text = transcribe_bytes(raw, language=language)
            prepared.append(VoiceSample(audio=raw, reference_text=text))
            continue
        if s.reference_text.strip():
            prepared.append(VoiceSample(audio=raw, reference_text=s.reference_text))
            continue
        # Short audio without a transcript: derive one (cached for file paths).
        text = (
            ensure_transcript(s.audio, language=language)
            if isinstance(s.audio, str)
            else transcribe_bytes(raw, language=language)
        )
        prepared.append(VoiceSample(audio=raw, reference_text=text))
    return prepared
