"""
speaker-helper — professional text-to-speech, offline and streaming.

Module summary
--------------
speaker-helper is the inverse of ``vocal-helper``: it turns **text into
speech**. A small, typed API over three jobs — **say** one sentence,
**stream** a reply as it is written, and **narrate** a document with the
timed track that lets a page follow along — plus a CLI, a REST API, an MCP
surface and a skill.

The default backend is ``kokoro``: 82M parameters through ONNX, Apache-2.0 in
code *and* weights, 54 voices, running **in this process**. Nothing to launch,
nothing to connect to, and a time-to-first-audio that does not include an HTTP
round trip. ``openvoice`` and ``chatterbox`` clone a voice from a recording;
``mock`` is deterministic and serverless, for tests.

Usage example
-------------
>>> from speaker_helper import Speaker, Settings
>>> spk = Speaker(Settings.from_mapping({"backend": "mock", "language": "fr"}))
>>> # spk.save("Bonjour le monde.", "hello.wav")

See ``EXAMPLES.md`` for a runnable cookbook.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

# Typed configuration (backend, voice, language, mode).
from speaker_helper.config import Settings

# Backend registry and the engine protocol the rest of the package targets.
from speaker_helper.engine import (
    MockEngine,
    TTSEngine,
    available_backends,
    create_engine,
    register_backend,
)

# Reading a document aloud: segments, the timeline, and the cues that let a
# page follow the reading.
from speaker_helper.narration import (
    PACE_SPEED,
    NarrationResult,
    Segment,
    SpeechCue,
    Timeline,
    coerce_segments,
    cues_to_vtt,
    resolve_spoken_math,
)

# Per-language operating profiles and their tuning helpers.
from speaker_helper.profiles import (
    DEFAULT_PROFILES,
    LanguageProfile,
    profile_for,
    tune_profiles,
)

# Backend router: choose engine + mode from measured quality↔speed evidence.
from speaker_helper.router import (
    OperatingPoint,
    RouteDecision,
    RouteRequest,
    default_operating_points,
    route,
    route_settings,
)

# High-level entry point most callers use.
from speaker_helper.speaker import Speaker

# What the voice says where the page shows notation.
from speaker_helper.speech_text import NARRATE_ABOVE, complexity, speak_math, speakable

# Deterministic sentence splitter used for streaming synthesis.
from speaker_helper.text import chunk_for_streaming, split_sentences

# Dataclasses exchanged across the public surface.
from speaker_helper.types import (
    AudioResult,
    Mode,
    StreamChunk,
    Voice,
    VoiceList,
    VoiceSample,
)

# Curated real presets, resolvable by language and gender.
from speaker_helper.voices import PRESET_VOICES, voice_for, voices_for

__version__ = "0.8.1"

# Explicit, sorted public API: only these names are re-exported from the
# package root; the sub-modules above hold the implementation.
__all__ = [
    "DEFAULT_PROFILES",
    "PRESET_VOICES",
    "AudioResult",
    "LanguageProfile",
    "Mode",
    "MockEngine",
    "OperatingPoint",
    "RouteDecision",
    "RouteRequest",
    "Settings",
    "Speaker",
    "StreamChunk",
    "TTSEngine",
    "Voice",
    "VoiceList",
    "VoiceSample",
    "NarrationResult",
    "Segment",
    "SpeechCue",
    "Timeline",
    "coerce_segments",
    "cues_to_vtt",
    "resolve_spoken_math",
    "PACE_SPEED",
    "speakable",
    "speak_math",
    "complexity",
    "NARRATE_ABOVE",
    "__version__",
    "available_backends",
    "chunk_for_streaming",
    "create_engine",
    "default_operating_points",
    "profile_for",
    "register_backend",
    "route",
    "route_settings",
    "split_sentences",
    "tune_profiles",
    "voice_for",
    "voices_for",
]
