"""
ElevenLabs: the paid cloud cells of the matrix, offline and streaming.

Module summary
--------------
The owner's matrix has two cloud cells — paid, offline and paid, streaming —
and ElevenLabs is the service picked for them. This backend covers both with
one client, the operating mode choosing the model:

* **offline** → ``eleven_v4``, "our most emotive, high quality speech
  synthesis model" (ElevenLabs' models page, read 2026-11-04);
* **streaming** → ``eleven_v4_turbo``, the same family at ~100 ms median
  latency.

Both speak French. Audio is requested as ``pcm_24000`` (signed 16-bit
little-endian), the rate every in-tree backend lays out at, so a narration can
mix engines with exact cue times and nothing is resampled.

This is the only backend that sends text off the machine, and it is never
picked by ``backend: auto``: it has no entry in the router's catalogue, so it
answers only when named (``backend: elevenlabs``) — a paid service must not be
reached by a default.

The pronunciation lexicon
-------------------------
``eleven_v4`` reads IPA inline "when wrapped in forward slashes" (ElevenLabs
best-practices page), which is the best tier this backend can offer: entries
with ``ipa`` are spliced as ``/ipa/``, deterministically. Every other model —
and every entry without IPA — gets the respelling tier. The backend applies
both itself (``LEXICON_TIER = "ipa"`` tells the Speaker not to respell first,
which would hide the original word from the IPA tier). ElevenLabs'
server-side pronunciation dictionaries are not used: their creation endpoint
could not be read when this was written, and an inline splice needs no
server state.

The streaming cell is served the way every other backend serves it —
:meth:`~speaker_helper.speaker.Speaker.stream` pipelines sentence chunks
through :meth:`synthesize`. ElevenLabs' WebSocket only pays off when text
arrives token by token, which no surface of this package accepts.

Configuration
-------------
The API key comes from ``ELEVENLABS_API_KEY`` (preferred: a key in a settings
file ends up in a repository sooner or later) or ``elevenlabs.api_key``.

Usage example
-------------
>>> from speaker_helper import Speaker, Settings
>>> # spk = Speaker(Settings.from_mapping({"backend": "elevenlabs", "language": "fr"}))
>>> # await spk.say("Bonjour depuis le nuage.")

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from speaker_helper.config import Settings
from speaker_helper.types import AudioResult, Voice, VoiceList, VoiceSample

#: Requested as ``pcm_24000``: the suite's layout rate, no resampling.
SAMPLE_RATE_HZ: int = 24_000

#: The REST host; regional hosts (``https://api.eu.residency.elevenlabs.io``)
#: go through the ``base_url`` knob.
DEFAULT_BASE_URL: str = "https://api.elevenlabs.io"

#: Model per operating mode (ElevenLabs models page, read 2026-11-04).
MODEL_BY_MODE: dict[str, str] = {
    "offline": "eleven_v4",
    "streaming": "eleven_v4_turbo",
}

#: Models documented as reading ``/IPA/`` inline. ``eleven_v4_turbo`` is left
#: out until the docs say it does: a slash-wrapped IPA string read aloud
#: literally would be worse than a respelling.
INLINE_IPA_MODELS: frozenset[str] = frozenset({"eleven_v4"})

#: Default voice: "Sarah", from ElevenLabs' premade library, labelled female.
#: Premade voices are multilingual, so one id serves every language until the
#: owner fixes a voice per language (``voice_by_lang``) — chosen by ear, which
#: this default has not been.
DEFAULT_VOICE_ID: str = "EXAVITQu4vr4xnSDxMaL"

#: Documented range of ``voice_settings.speed``.
SPEED_RANGE: tuple[float, float] = (0.7, 1.2)

_ENV_KEY = "ELEVENLABS_API_KEY"


def _base_language(code: str | None, fallback: str) -> str:
    raw = (code or "").strip().lower()
    return raw.split("-")[0] if raw else fallback


class ElevenLabsEngine:
    """The ElevenLabs backend: REST synthesis, model chosen by the mode.

    Parameters
    ----------
    settings : Settings
        ``mode`` picks the model (see :data:`MODEL_BY_MODE`); ``voice`` names
        an ElevenLabs voice id. The ``elevenlabs`` mapping supplies the knobs:

        * ``api_key`` — fallback when ``ELEVENLABS_API_KEY`` is unset.
        * ``model`` — pin a model id regardless of the mode.
        * ``voice_by_lang`` — ``{"fr": "<voice id>", "en": …}``, the female
          voice fixed per language.
        * ``stability``, ``similarity_boost``, ``style`` — voice settings
          (service defaults ``0.5`` / ``0.75`` / ``0``).
        * ``seed`` — integer for repeatable takes (default unset).
        * ``base_url`` — regional host (default :data:`DEFAULT_BASE_URL`).
        * ``timeout_s`` — HTTP timeout (default ``120``).
    """

    #: This backend applies the lexicon itself (inline IPA where the model
    #: reads it, respelling elsewhere); the Speaker must not respell first.
    LEXICON_TIER: str = "ipa"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        knobs = getattr(settings, "elevenlabs", {}) or {}
        self._api_key: str = os.environ.get(_ENV_KEY) or str(knobs.get("api_key") or "")
        mode = (settings.mode or "offline").lower()
        self._model: str = str(knobs.get("model") or MODEL_BY_MODE.get(mode, "eleven_v4"))
        self._voice_by_lang: dict[str, str] = dict(knobs.get("voice_by_lang") or {})
        self._voice_settings: dict[str, float] = {
            key: float(knobs[key])
            for key in ("stability", "similarity_boost", "style")
            if key in knobs
        }
        self._seed: int | None = int(knobs["seed"]) if knobs.get("seed") is not None else None
        self._base_url: str = str(knobs.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
        self._timeout_s: float = float(knobs.get("timeout_s", 120))
        from speaker_helper.lexicon import load_lexicon

        self._lexicon = load_lexicon(settings)

    # -- helpers ------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict | None = None,
    ) -> bytes:
        """One authenticated HTTP call. Blocking; run in a thread.

        Raises
        ------
        RuntimeError
            Without an API key, or on any HTTP error (status and the service's
            own message, never the key).
        """
        if not self._api_key:
            raise RuntimeError(
                f"elevenlabs needs an API key: export {_ENV_KEY}=… (or set elevenlabs.api_key)"
            )
        url = f"{self._base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query, doseq=True)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("xi-api-key", self._api_key)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode("utf-8", "replace")
            raise RuntimeError(
                f"elevenlabs {method} {path} failed: HTTP {exc.code}: {detail}"
            ) from None

    def _voice_for(self, lang: str, voice: str | None) -> str:
        return voice or self._settings.voice or self._voice_by_lang.get(lang) or DEFAULT_VOICE_ID

    def apply_lexicon(self, text: str, language: str) -> str:
        """Splice lexicon entries the best way this model can read them.

        Parameters
        ----------
        text : str
            The text about to be sent.
        language : str
            Bare language code (entries are language-keyed).

        Returns
        -------
        str
            ``/ipa/`` for entries with IPA on a model that reads it inline,
            the respelling otherwise; ``text`` unchanged without a lexicon.
        """
        if self._lexicon is None:
            return text
        if self._model not in INLINE_IPA_MODELS:
            return self._lexicon.respell(text, language)
        out: list[str] = []
        for chunk, entry in self._lexicon.split(text, language):
            if entry is None:
                out.append(chunk)
            elif entry.ipa:
                out.append(f"/{entry.ipa}/")
            else:
                out.append(self._lexicon.ensure_respelling(entry, language) or chunk)
        return "".join(out)

    # -- the TTSEngine protocol ---------------------------------------------

    async def aclose(self) -> None:
        """Nothing is held open between calls."""

    async def synthesize(
        self,
        text: str,
        *,
        language: str | None = None,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> AudioResult:
        """Synthesise ``text`` through the REST convert endpoint.

        Parameters
        ----------
        text : str
            What to say (must be non-empty).
        language : str or None
            Sent as ``language_code`` and used for the lexicon.
        voice : str or None
            An ElevenLabs voice id; empty picks the per-language default.
        speed : float
            Clamped to the documented ``0.7``–``1.2``.

        Raises
        ------
        ValueError
            If ``text`` is empty or whitespace-only.
        RuntimeError
            Without an API key, or when the service refuses the call.
        """
        import numpy as np

        if not text or not text.strip():
            raise ValueError("cannot synthesise empty text")
        lang = _base_language(language, self._settings.language or "fr")
        voice_id = self._voice_for(lang, voice)
        low, high = SPEED_RANGE
        body: dict[str, Any] = {
            "text": self.apply_lexicon(text, lang),
            "model_id": self._model,
            "language_code": lang,
            "voice_settings": {**self._voice_settings, "speed": min(high, max(low, speed))},
        }
        if self._seed is not None:
            body["seed"] = self._seed

        started = time.perf_counter()
        raw = await asyncio.to_thread(
            self._request,
            "POST",
            f"/v1/text-to-speech/{urllib.parse.quote(voice_id)}",
            query={"output_format": "pcm_24000"},
            body=body,
        )
        compute_s = time.perf_counter() - started
        if len(raw) % 2:
            raw = raw[:-1]  # a torn last sample, never a whole one
        pcm = np.frombuffer(raw, dtype="<i2").astype(np.int16)

        from speaker_helper.backends.kokoro import pcm_to_wav_bytes

        return AudioResult(
            wav_bytes=pcm_to_wav_bytes(pcm, SAMPLE_RATE_HZ),
            sample_rate=SAMPLE_RATE_HZ,
            duration_s=len(pcm) / float(SAMPLE_RATE_HZ),
            compute_s=compute_s,
            text=text,
            voice_id=voice_id,
            language=lang,
        )

    async def list_voices(self, engine: str | None = None) -> VoiceList:
        """Female voices for the configured language, from the service.

        Without a key there is nothing to ask, so the default is listed — it is
        what would speak.
        """
        lang = _base_language(self._settings.language, "fr")
        if not self._api_key:
            return VoiceList(
                engine="elevenlabs",
                voices=[
                    Voice(
                        voice_id=self._voice_for(lang, None),
                        name="Sarah (premade)",
                        language=lang,
                        gender="female",
                        engine="elevenlabs",
                    )
                ],
            )
        raw = await asyncio.to_thread(
            self._request,
            "GET",
            "/v2/voices",
            query={"gender": "female", "language": lang, "page_size": 100},
        )
        voices = [
            Voice(
                voice_id=item.get("voice_id", ""),
                name=item.get("name", ""),
                language=(item.get("labels") or {}).get("language", lang),
                gender=(item.get("labels") or {}).get("gender", ""),
                engine="elevenlabs",
            )
            for item in json.loads(raw or b"{}").get("voices", [])
        ]
        return VoiceList(engine="elevenlabs", voices=voices)

    async def health(self) -> dict:
        """Whether a key is configured — without spending a request."""
        if not self._api_key:
            return {
                "status": "unavailable",
                "engine": "elevenlabs",
                "reason": f"no API key ({_ENV_KEY} is unset)",
                "fix": f"export {_ENV_KEY}=<your key>",
            }
        return {
            "status": "ok",
            "engine": "elevenlabs",
            "model": self._model,
            "base_url": self._base_url,
            "sample_rate": SAMPLE_RATE_HZ,
            "inline_ipa": self._model in INLINE_IPA_MODELS,
        }

    async def clone_voice(
        self,
        name: str,
        samples: list[VoiceSample],
        *,
        language: str | None = None,
    ) -> str:
        """Refuse: cloning on ElevenLabs uploads a person's voice to a third party.

        That is a decision for whoever owns the recording, taken in their
        ElevenLabs account; once the voice exists there, its id goes in
        ``voice`` or ``elevenlabs.voice_by_lang``.
        """
        raise NotImplementedError(
            "elevenlabs cloning is not done from here: it uploads a recording to a "
            "third party. Create the voice in your ElevenLabs account, then pass its "
            "id as voice= or elevenlabs.voice_by_lang."
        )
