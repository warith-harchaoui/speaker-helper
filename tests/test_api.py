"""
Tests for the REST API façade, driven against the deterministic mock backend.

They run only when FastAPI (the ``server`` extra) is installed; otherwise they
skip. No TTS server is needed — the mock backend makes the endpoints fully
exercisable in CI.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import base64
import json

import pytest

from speaker_helper import Settings

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from speaker_helper.api import create_app  # noqa: E402


def _client() -> TestClient:
    """A TestClient wired to the mock backend (runs the app lifespan/warm-up)."""
    return TestClient(create_app(Settings.from_mapping({"backend": "mock"})))


def test_health_reports_backend() -> None:
    with _client() as client:
        body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["backend"] == "mock"


def test_voices_lists_presets() -> None:
    with _client() as client:
        body = client.get("/voices").json()
    assert body["engine"]
    assert any(v["voice_id"] == "mock-fr" for v in body["voices"])


def test_synth_returns_wav_with_headers() -> None:
    with _client() as client:
        resp = client.post("/synth", json={"text": "Bonjour."})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.content[:4] == b"RIFF"
    assert float(resp.headers["X-Audio-RTF"]) > 0


def test_synth_rejects_empty_text() -> None:
    with _client() as client:
        # pydantic min_length=1 rejects an empty body field with 422.
        resp = client.post("/synth", json={"text": ""})
    assert resp.status_code == 422


def test_synth_stream_emits_ordered_sse_chunks() -> None:
    with _client() as client:
        resp = client.post("/synth/stream", json={"text": "Un. Deux. Trois."})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = [
            json.loads(line[len("data: "):])
            for line in resp.text.splitlines()
            if line.startswith("data: ")
        ]
    assert [e["seq"] for e in events] == [0, 1, 2]
    assert events[0]["ttfa_s"] is not None  # first chunk carries TTFA
    assert events[-1]["is_final"] is True
    # every chunk carries decodable WAV audio
    assert base64.b64decode(events[0]["audio"])[:4] == b"RIFF"
