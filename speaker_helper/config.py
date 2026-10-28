"""
Configuration for speaker-helper.

Module summary
--------------
speaker-helper reads a small, typed configuration describing where the
backend reads, and which voice / language / mode to use. Values come
from (in increasing precedence) dataclass defaults, an optional
``settings.yaml``, and ``SPEAKER_HELPER_*`` environment variables. Strings
spelled ``${VAR}`` inside the YAML are expanded from the environment at load
time so hosts and secrets never sit in a committed file.

See ``settings.yaml.example`` and ``speaker_config.json.example`` at the
repository root for a documented template.

Usage example
-------------
>>> from speaker_helper.config import Settings
>>> s = Settings.from_yaml_text("backend: kokoro\\nlanguage: fr\\nvoice: ff_siwis")
>>> s.backend, s.voice
('kokoro', 'ff_siwis')

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import os_helper as osh
import yaml

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any) -> Any:
    """Recursively expand ``${VAR}`` references from the environment.

    Parameters
    ----------
    value : Any
        A scalar, list, or dict loaded from YAML.

    Returns
    -------
    Any
        The same structure with ``${VAR}`` replaced by ``os.environ[VAR]``
        (empty string when the variable is unset — the loader stays permissive).
    """
    # Scalars: substitute every ${VAR} with its environment value (empty when
    # unset — the loader stays permissive rather than raising on missing vars).
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)
    # Containers: recurse so ${VAR} inside nested lists/dicts is expanded too.
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    # Non-string leaves (int, bool, None) pass through untouched.
    return value


def _from_mapping(cls: type, mapping: dict[str, Any] | None) -> Any:
    """Build a dataclass from a mapping, ignoring unknown keys."""
    # Keep only keys that are real dataclass fields, so a stray/extra YAML key
    # is silently ignored instead of raising a TypeError on construction.
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (mapping or {}).items() if k in known})


@dataclass
class Settings:
    """Top-level speaker-helper configuration.

    Parameters
    ----------
    backend : str
        Which TTS backend to drive. ``"kokoro"`` (default) runs in this
        process and needs no server; ``"openvoice"`` and ``"chatterbox"``
        clone a voice from a recording; ``"mock"`` is deterministic and
        serverless, for tests and the evaluation layer. The backend is an
        implementation detail — the rest of the package talks only to the
        :class:`~speaker_helper.engine.TTSEngine` protocol. See
        :func:`speaker_helper.engine.available_backends`.
    engine : str
        A label carried on results, for callers that record which model
        produced what. It does not select the backend; ``backend`` does.
    voice : str
        Which built-in voice reads. Empty (default) means "read the text,
        detect the language, and pick the voice that speaks it" — which is
        not a convenience: the detected language is what the phonemiser
        works from, and French read as English is not French in an American
        accent, it is an American spelling the words out.
    voice_sample : str
        Path to a reference recording, for the cloning backends. Kokoro
        refuses one rather than ignoring it.
    voice_id : str
        Deprecated spelling of ``voice``, kept because configuration files in
        the wild use it. ``voice`` wins when both are set.
    language : str
        ISO-639-1 target language (e.g. ``"fr"``).
    normalize : bool
        Loudness-normalise the output where the backend can.
    mode : str
        ``"offline"`` or ``"streaming"``.
    first_chunk_sentences : int
        Streaming only: sentences in the first emitted chunk (1 → lowest
        time-to-first-audio, which is the number a conversation feels).

    Notes
    -----
    Precedence, lowest to highest: dataclass defaults → ``settings.yaml`` →
    ``SPEAKER_HELPER_*`` environment variables.
    """

    # "auto" (the default) decides from `mode` through the router, so the
    # default path obeys the project's operating matrix instead of a hard-coded
    # engine name: offline goes to chatterbox in every language, streaming
    # stays on kokoro. Name a backend explicitly and it is honoured as-is.
    # See :func:`speaker_helper.engine.resolve_auto`.
    backend: str = "auto"
    engine: str = "auto"
    voice: str = ""
    voice_sample: str = ""
    voice_id: str = ""
    language: str = "fr"
    normalize: bool = True
    mode: str = "offline"
    first_chunk_sentences: int = 1
    # Backend-specific knobs for the ``mock`` engine (rtf, chars_per_sec,
    # sample_rate, amplitude, frequency_hz). Ignored by other backends.
    mock: dict[str, Any] = field(default_factory=dict)
    # Voice-cloning configuration. Empty (default) means "use a preset voice".
    # When non-empty, synthesis uses a cloned voice built from reference audio;
    # keys: name, audio, reference_text, samples. See
    # :mod:`speaker_helper.cloning`. A missing transcript is derived with
    # ``vocal-helper``; an empty ``audio`` falls back to the bundled ref-fr-female.
    clone: dict[str, Any] = field(default_factory=dict)
    # Backend-specific knobs for the ``chatterbox`` engine. Key: ``variant`` —
    # "auto" (default: Turbo for English, Multilingual elsewhere), "base",
    # "turbo", or "multilingual". See
    # :class:`speaker_helper.backends.chatterbox.ChatterboxEngine`.
    chatterbox: dict[str, Any] = field(default_factory=dict)
    # Backend-specific knobs for the ``kyutai`` engine (repo, device, dtype,
    # cfg_coef, temp). Ignored by other backends; see
    # :class:`speaker_helper.backends.kyutai.KyutaiEngine`.
    kyutai: dict[str, Any] = field(default_factory=dict)
    # Long-text chunking (see :mod:`speaker_helper.chunking`). Keys:
    # ``enabled`` (default True), ``llm`` (default True — let the local LLM
    # place chunk boundaries at discourse breaks; greedy packing otherwise),
    # ``max_chars`` (default 500, ~30 s of speech per chunk).
    chunking: dict[str, Any] = field(default_factory=dict)
    # Pronunciation-lexicon configuration (see :mod:`speaker_helper.lexicon`).
    # Keys: ``path`` (default: ``./lexicon.yaml`` when it exists), ``enabled``
    # (default True), ``llm`` (default True — allow deriving missing
    # respellings with the local LLM resolved via best-engine-ai-helper).
    # Empty means "use the defaults": the feature is on, and quietly inert
    # when no lexicon file exists.
    lexicon: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Let ``voice_id`` stand in for ``voice``.

        ``voice_id`` is what the REST-engine era called it, and settings files
        written then still say it. Silently ignoring those would start the
        wrong voice with no error anywhere — the worst shape of a rename.
        """
        if not self.voice and self.voice_id:
            self.voice = self.voice_id

    # ----- constructors ---------------------------------------------------

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any] | None) -> Settings:
        """Build settings from a plain mapping (unknown keys ignored).

        Parameters
        ----------
        mapping : dict or None
            Nested mapping mirroring the dataclass fields.

        Returns
        -------
        Settings
            The populated settings, with environment overrides applied.
        """
        mapping = _expand_env(mapping or {})
        # A `voicebox:` section is dropped rather than rejected: settings files
        # written for the REST engine are still on disk, and refusing to load
        # one would be a worse welcome than ignoring a key that now means
        # nothing. `_from_mapping` already drops unknown keys; this comment is
        # here so the silence is deliberate rather than accidental.
        settings = _from_mapping(cls, mapping)
        settings._apply_env_overrides()
        return settings

    @classmethod
    def from_yaml_text(cls, text: str) -> Settings:
        """Build settings from a YAML document string.

        Parameters
        ----------
        text : str
            YAML source.

        Returns
        -------
        Settings
            The populated settings.
        """
        return cls.from_mapping(yaml.safe_load(text) or {})

    @classmethod
    def load(cls, path: str | Path | None = None) -> Settings:
        """Load settings from a YAML file if present, else defaults + env.

        Parameters
        ----------
        path : str or Path or None
            Path to a ``settings.yaml``. When ``None``, ``./settings.yaml`` is
            used if it exists; otherwise dataclass defaults apply. Environment
            overrides are always applied last.

        Returns
        -------
        Settings
            The populated settings.
        """
        if path is None:
            default = Path("settings.yaml")
            path = default if osh.file_exists(str(default)) else None
        if path is None:
            return cls.from_mapping({})
        return cls.from_yaml_text(Path(path).read_text(encoding="utf-8"))

    def _apply_env_overrides(self) -> None:
        """Override selected fields from ``SPEAKER_HELPER_*`` env variables."""
        # Environment variables are the highest-precedence source, applied last
        # so they win over both dataclass defaults and any YAML file. Each key is
        # optional; only present ones override, keeping the rest untouched.
        env = os.environ
        if "SPEAKER_HELPER_VOICE" in env:
            self.voice = env["SPEAKER_HELPER_VOICE"]
        if "SPEAKER_HELPER_VOICE_SAMPLE" in env:
            self.voice_sample = env["SPEAKER_HELPER_VOICE_SAMPLE"]
        if "SPEAKER_HELPER_BACKEND" in env:
            self.backend = env["SPEAKER_HELPER_BACKEND"]
        if "SPEAKER_HELPER_ENGINE" in env:
            self.engine = env["SPEAKER_HELPER_ENGINE"]
        if "SPEAKER_HELPER_VOICE_ID" in env:
            self.voice_id = env["SPEAKER_HELPER_VOICE_ID"]
            if not self.voice:
                self.voice = self.voice_id
        if "SPEAKER_HELPER_LANGUAGE" in env:
            self.language = env["SPEAKER_HELPER_LANGUAGE"]
        # The lexicon path override keeps the rest of the `lexicon` mapping
        # intact: an operator pointing every process at one shared lexicon
        # should not thereby re-enable an LLM a settings file disabled.
        if "SPEAKER_HELPER_LEXICON" in env:
            self.lexicon = {**self.lexicon, "path": env["SPEAKER_HELPER_LEXICON"]}
