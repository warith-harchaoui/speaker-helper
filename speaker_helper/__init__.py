"""
speaker-helper — professional text-to-speech, offline and streaming.

Module summary
--------------
speaker-helper is the inverse of ``vocal-helper``: it turns **text into
speech**. It wraps the local `Voicebox <https://github.com/jamiepine/voicebox>`_
engine behind a small, typed API with two modes — **offline** (whole text →
one audio) and **streaming** (sentence-split, low time-to-first-audio) — and
ships a CLI and a REST API. It runs locally (conda + pip) or as a Docker
server.

The default engine is ``kokoro``, which synthesises faster than real time on
CPU (real-time factor well below 1.0).

Usage example
-------------
>>> from speaker_helper import Speaker, Settings
>>> spk = Speaker(Settings.from_mapping({"engine": "kokoro", "language": "fr"}))
>>> # spk.save("Bonjour le monde.", "hello.wav")   # requires a running Voicebox

See ``EXAMPLES.md`` for a runnable cookbook.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

from speaker_helper.client import VoiceboxClient, VoiceboxError
from speaker_helper.config import Settings, VoiceboxConfig
from speaker_helper.engine import (
    MockEngine,
    TTSEngine,
    available_backends,
    create_engine,
    register_backend,
)
from speaker_helper.profiles import (
    DEFAULT_PROFILES,
    LanguageProfile,
    profile_for,
    tune_profiles,
)
from speaker_helper.speaker import Speaker
from speaker_helper.text import chunk_for_streaming, split_sentences
from speaker_helper.types import (
    AudioResult,
    Mode,
    StreamChunk,
    Voice,
    VoiceList,
    VoiceSample,
)

__version__ = "0.7.0"

__all__ = [
    "DEFAULT_PROFILES",
    "AudioResult",
    "LanguageProfile",
    "Mode",
    "MockEngine",
    "Settings",
    "Speaker",
    "StreamChunk",
    "TTSEngine",
    "Voice",
    "VoiceList",
    "VoiceSample",
    "VoiceboxClient",
    "VoiceboxConfig",
    "VoiceboxError",
    "__version__",
    "available_backends",
    "chunk_for_streaming",
    "create_engine",
    "profile_for",
    "register_backend",
    "split_sentences",
    "tune_profiles",
]
