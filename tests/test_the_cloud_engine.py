"""
The paid cloud backend, exercised against a fake service.

No key, no network: ``urllib.request.urlopen`` is replaced by a recorder that
answers like ElevenLabs' convert endpoint (raw ``pcm_24000``). What is pinned
here is what would cost money or privacy to get wrong — the model each mode
asks for, the lexicon reaching the service in the form that model reads, the
key never leaving the header, and ``auto`` never routing to a paid engine.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio
import io
import json
import urllib.error
import urllib.request

import pytest

from speaker_helper.backends.elevenlabs import (
    DEFAULT_VOICE_ID,
    SAMPLE_RATE_HZ,
    ElevenLabsEngine,
)
from speaker_helper.config import Settings


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> list[urllib.request.Request]:
    """A fake ElevenLabs: records every request, answers 0.5 s of PCM."""
    calls: list[urllib.request.Request] = []

    def fake_urlopen(request: urllib.request.Request, timeout: float = 0) -> _Response:
        calls.append(request)
        if "/v2/voices" in request.full_url:
            payload = {
                "voices": [{"voice_id": "v1", "name": "Léa", "labels": {"gender": "female"}}]
            }
            return _Response(json.dumps(payload).encode())
        return _Response(b"\x01\x00" * (SAMPLE_RATE_HZ // 2))

    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


def _engine(**settings: object) -> ElevenLabsEngine:
    mapping = {"backend": "elevenlabs", "language": "fr", "lexicon": {"enabled": False}}
    return ElevenLabsEngine(Settings.from_mapping({**mapping, **settings}))


def _body(request: urllib.request.Request) -> dict:
    return json.loads(request.data or b"{}")


def test_offline_asks_for_v4_and_gets_24_khz_pcm(service: list) -> None:
    """The quality model offline, at the suite's layout rate."""
    result = asyncio.run(_engine(mode="offline").synthesize("Bonjour."))

    (request,) = service
    assert "output_format=pcm_24000" in request.full_url
    assert f"/v1/text-to-speech/{DEFAULT_VOICE_ID}" in request.full_url
    assert _body(request)["model_id"] == "eleven_v4"
    assert _body(request)["language_code"] == "fr"
    assert result.sample_rate == SAMPLE_RATE_HZ
    assert result.duration_s == pytest.approx(0.5)


def test_streaming_asks_for_the_low_latency_model(service: list) -> None:
    """The streaming cell is a different model, not the same one hurried."""
    asyncio.run(_engine(mode="streaming").synthesize("Bonjour."))
    assert _body(service[0])["model_id"] == "eleven_v4_turbo"


def test_the_key_travels_in_the_header_only(service: list) -> None:
    """Never in the URL, never in the body — those end up in logs."""
    asyncio.run(_engine().synthesize("Bonjour."))
    (request,) = service
    assert request.get_header("Xi-api-key") == "sk-test"
    assert "sk-test" not in request.full_url
    assert "sk-test" not in (request.data or b"").decode()


def test_speed_is_clamped_to_the_documented_range(service: list) -> None:
    """A narration's "fast" must not become a refused request."""
    asyncio.run(_engine().synthesize("Bonjour.", speed=3.0))
    assert _body(service[0])["voice_settings"]["speed"] == 1.2


def test_a_voice_fixed_per_language_wins_over_the_default(service: list) -> None:
    """The owner's per-language female voice is what speaks once it is set."""
    engine = _engine(elevenlabs={"voice_by_lang": {"fr": "voix-fr"}})
    asyncio.run(engine.synthesize("Bonjour."))
    assert "/v1/text-to-speech/voix-fr" in service[0].full_url


def test_the_lexicon_reaches_v4_as_inline_ipa_and_turbo_as_a_respelling(
    tmp_path, service: list
) -> None:
    """Each model gets the best form it is documented to read."""
    lexicon = tmp_path / "lexicon.yaml"
    lexicon.write_text(
        "entries:\n  - {word: ONU, language: fr, ipa: oɛny, respelling: oénu}\n", encoding="utf-8"
    )
    lex = {"path": str(lexicon), "llm": False}
    v4 = ElevenLabsEngine(
        Settings.from_mapping({"backend": "elevenlabs", "language": "fr", "lexicon": lex})
    )
    turbo = ElevenLabsEngine(
        Settings.from_mapping(
            {"backend": "elevenlabs", "language": "fr", "mode": "streaming", "lexicon": lex}
        )
    )
    assert v4.apply_lexicon("Vive l'ONU !", "fr") == "Vive l'/oɛny/ !"
    assert turbo.apply_lexicon("Vive l'ONU !", "fr") == "Vive l'oénu !"


def test_a_refusal_names_the_status_not_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """An HTTP error becomes a readable RuntimeError."""

    def refuse(request: urllib.request.Request, timeout: float = 0) -> None:
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", None, io.BytesIO(b'{"detail":"invalid_api_key"}')
        )

    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-bad")
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    with pytest.raises(RuntimeError, match="HTTP 401") as caught:
        asyncio.run(_engine().synthesize("Bonjour."))
    assert "sk-bad" not in str(caught.value)


def test_without_a_key_health_says_so_and_nothing_is_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No key: a clear "unavailable", and synthesis refuses before any request."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    engine = _engine()
    report = asyncio.run(engine.health())
    assert report["status"] == "unavailable" and "ELEVENLABS_API_KEY" in report["fix"]
    with pytest.raises(RuntimeError, match="API key"):
        asyncio.run(engine.synthesize("Bonjour."))


def test_voices_are_asked_for_female_in_the_language(service: list) -> None:
    """The listing filters on the service side, by its own labels."""
    listing = asyncio.run(_engine().list_voices())
    assert "gender=female" in service[0].full_url and "language=fr" in service[0].full_url
    assert [(v.voice_id, v.gender) for v in listing.voices] == [("v1", "female")]


def test_auto_never_routes_to_the_paid_engine() -> None:
    """A default must not spend money: elevenlabs is not a routing candidate."""
    from speaker_helper.router import OFFLINE, ONLINE_REALTIME, default_operating_points

    for condition in (OFFLINE, ONLINE_REALTIME):
        for lang in ("fr", "en", "es"):
            engines = {p.engine for p in default_operating_points(lang, condition)}
            assert "elevenlabs" not in engines
