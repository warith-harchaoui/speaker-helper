"""
Configuration for speaker-helper.

Module summary
--------------
speaker-helper reads a small, typed configuration describing where the
Voicebox engine lives and which voice / language / mode to use. Values come
from (in increasing precedence) dataclass defaults, an optional
``settings.yaml``, and ``SPEAKER_HELPER_*`` environment variables. Strings
spelled ``${VAR}`` inside the YAML are expanded from the environment at load
time so hosts and secrets never sit in a committed file.

See ``settings.yaml.example`` and ``speaker_config.json.example`` at the
repository root for a documented template.

Usage example
-------------
>>> from speaker_helper.config import Settings
>>> s = Settings.from_yaml_text("voicebox: {port: 17600}\\nlanguage: fr")
>>> s.voicebox.port
17600
>>> s.base_url
'http://127.0.0.1:17600'

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
class VoiceboxConfig:
    """Where the Voicebox REST service lives.

    Parameters
    ----------
    host : str
        Hostname or IP of the Voicebox server. Default ``127.0.0.1``.
    port : int
        TCP port. Voicebox's native default is ``17493``; the bundled
        ``docker-compose`` maps the container to ``17600`` on the host.
    timeout_s : float
        Per-request timeout in seconds. The first synthesis of a new engine
        pays a model download, so keep this generous.
    max_retries : int
        How many times to retry a request that fails on a *transient* error
        (network/transport error or a 5xx from the engine). ``0`` disables
        retries. Client errors (4xx) are never retried.
    retry_backoff_s : float
        Base delay for exponential backoff between retries: attempt ``k`` waits
        ``retry_backoff_s * 2**(k-1)`` seconds.
    """

    host: str = "127.0.0.1"
    port: int = 17493
    timeout_s: float = 300.0
    max_retries: int = 2
    retry_backoff_s: float = 0.5


@dataclass
class Settings:
    """Top-level speaker-helper configuration.

    Parameters
    ----------
    voicebox : VoiceboxConfig
        Connection details for the Voicebox engine.
    backend : str
        Which TTS backend to drive: ``"voicebox"`` (the real engine, default)
        or ``"mock"`` (deterministic, serverless — used by tests and the
        evaluation layer). The backend is an implementation detail; the rest of
        the package talks only to the :class:`~speaker_helper.engine.TTSEngine`
        protocol. See :func:`speaker_helper.engine.available_backends`.
    engine : str
        Backend-specific engine/model id. For Voicebox, ``kokoro`` is fast
        enough for real-time on CPU.
    voice_id : str
        Preset voice id. Empty (default) means "auto-pick a voice whose
        language matches ``language``".
    language : str
        ISO-639-1 target language (e.g. ``"fr"``).
    normalize : bool
        Ask Voicebox to loudness-normalise the output.
    mode : str
        ``"offline"`` or ``"streaming"``.
    first_chunk_sentences : int
        Streaming only: sentences in the first emitted chunk (1 → lowest TTFA).

    Notes
    -----
    Precedence, lowest to highest: dataclass defaults → ``settings.yaml`` →
    ``SPEAKER_HELPER_*`` environment variables.
    """

    voicebox: VoiceboxConfig = field(default_factory=VoiceboxConfig)
    backend: str = "voicebox"
    engine: str = "kokoro"
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

    @property
    def base_url(self) -> str:
        """Return the Voicebox base URL, e.g. ``http://127.0.0.1:17600``."""
        return f"http://{self.voicebox.host}:{self.voicebox.port}"

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
        top = {k: v for k, v in mapping.items() if k != "voicebox"}
        settings = _from_mapping(cls, top)
        settings.voicebox = _from_mapping(VoiceboxConfig, mapping.get("voicebox"))
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
        if "SPEAKER_HELPER_VOICEBOX_HOST" in env:
            self.voicebox.host = env["SPEAKER_HELPER_VOICEBOX_HOST"]
        if "SPEAKER_HELPER_VOICEBOX_PORT" in env:
            # Ports arrive as strings from the environment; coerce to int.
            self.voicebox.port = int(env["SPEAKER_HELPER_VOICEBOX_PORT"])
        if "SPEAKER_HELPER_BACKEND" in env:
            self.backend = env["SPEAKER_HELPER_BACKEND"]
        if "SPEAKER_HELPER_ENGINE" in env:
            self.engine = env["SPEAKER_HELPER_ENGINE"]
        if "SPEAKER_HELPER_VOICE_ID" in env:
            self.voice_id = env["SPEAKER_HELPER_VOICE_ID"]
        if "SPEAKER_HELPER_LANGUAGE" in env:
            self.language = env["SPEAKER_HELPER_LANGUAGE"]
