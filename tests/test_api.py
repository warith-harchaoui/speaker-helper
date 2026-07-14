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
    """/health echoes an ok status and the configured backend name."""
    # Act: hit the health probe through the warmed-up test client.
    with _client() as client:
        body = client.get("/health").json()
    # Assert: the probe reports readiness and names the mock backend.
    assert body["status"] == "ok"
    assert body["backend"] == "mock"


def test_voices_lists_presets() -> None:
    """/voices names the engine and includes the mock French preset."""
    # Act: list the presets exposed by the mock backend.
    with _client() as client:
        body = client.get("/voices").json()
    # Assert: an engine is named and the known mock voice is present.
    assert body["engine"]
    assert any(v["voice_id"] == "mock-fr" for v in body["voices"])


def test_synth_returns_wav_with_headers() -> None:
    """/synth returns a RIFF WAV body plus a positive RTF header."""
    # Act: synthesise a short French utterance.
    with _client() as client:
        resp = client.post("/synth", json={"text": "Bonjour."})
    # Assert: success, WAV content type, RIFF magic bytes, and a live RTF.
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.content[:4] == b"RIFF"
    assert float(resp.headers["X-Audio-RTF"]) > 0


def test_synth_rejects_empty_text() -> None:
    """/synth rejects an empty text field with a 422 validation error."""
    with _client() as client:
        # pydantic min_length=1 rejects an empty body field with 422.
        resp = client.post("/synth", json={"text": ""})
    # Assert: the request is rejected at the validation layer.
    assert resp.status_code == 422


def test_mcp_server_mounted() -> None:
    """When fastapi-mcp is installed, an MCP endpoint is mounted at /mcp."""
    pytest.importorskip("fastapi_mcp")
    app = create_app(Settings.from_mapping({"backend": "mock"}))
    paths = {getattr(r, "path", "") for r in app.routes}
    assert any(p.startswith("/mcp") for p in paths)


def test_mcp_can_be_disabled() -> None:
    """enable_mcp=False builds the app without the MCP mount."""
    app = create_app(Settings.from_mapping({"backend": "mock"}), enable_mcp=False)
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any(p.startswith("/mcp") for p in paths)


def test_synth_stream_emits_ordered_sse_chunks() -> None:
    """/synth/stream emits SSE chunks in sequence, each carrying WAV audio."""
    # Act: stream three sentences and collect the SSE data payloads.
    with _client() as client:
        resp = client.post("/synth/stream", json={"text": "Un. Deux. Trois."})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        # Each SSE frame is a "data: <json>" line; parse only those.
        events = [
            json.loads(line[len("data: ") :])
            for line in resp.text.splitlines()
            if line.startswith("data: ")
        ]
    # Assert: one chunk per sentence, emitted strictly in order.
    assert [e["seq"] for e in events] == [0, 1, 2]
    assert events[0]["ttfa_s"] is not None  # first chunk carries TTFA
    assert events[-1]["is_final"] is True
    # every chunk carries decodable WAV audio
    assert base64.b64decode(events[0]["audio"])[:4] == b"RIFF"
