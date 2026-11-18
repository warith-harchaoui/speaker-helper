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


def test_route_returns_decision() -> None:
    """/route returns a justified engine + mode for a condition."""
    with _client() as client:
        resp = client.post("/route", json={"condition": "online_realtime", "language": "fr"})
    assert resp.status_code == 200
    body = resp.json()
    # The online condition must return a streaming decision with a justification.
    assert body["mode"] == "streaming"
    assert body["engine"]
    assert body["justification"]
    # Provenance is what a caller gets to reason with — there is no derived
    # confidence grade on the payload any more.
    assert body["quality_source"]
    assert "confidence" not in body


def test_route_rejects_bad_condition() -> None:
    """/route surfaces an unknown condition as a 400 (client error)."""
    with _client() as client:
        resp = client.post("/route", json={"condition": "turbo"})
    assert resp.status_code == 400


def test_gui_served_at_root() -> None:
    """The bundled single-page GUI is served at / (index.html)."""
    with _client() as client:
        resp = client.get("/")
    # The static mount serves the HTML shell; assert it is the GUI page.
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "speaker-helper" in resp.text.lower()


def test_synth_stream_emits_ordered_sse_chunks() -> None:
    """/synth/stream emits SSE chunks in sequence, each carrying WAV audio."""
    # Act: stream three sentences and collect the SSE data payloads. The
    # sentences are full-length on purpose: fragments under MIN_CHUNK_CHARS are
    # folded into a neighbour by the chunker, so toy inputs like "Un. Deux."
    # would arrive as a single chunk and test nothing about ordering.
    with _client() as client:
        resp = client.post(
            "/synth/stream",
            json={"text": "Bonjour à tous. Comment allez-vous ? Très bien, merci."},
        )
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


def test_every_os_helper_reference_resolves() -> None:
    """A name this package calls on `os_helper` must actually exist there.

    Found the hard way: `api.py` called `osh.warn(...)` — which has never
    existed, the function is `osh.warning` — from inside the `except` branch
    that exists to degrade gracefully when the MCP surface cannot mount. So a
    handled, benign condition ("MCP unavailable, the HTTP API is unaffected")
    became an `AttributeError` at application startup instead.

    Nothing caught it because the branch carries `# pragma: no cover`: the
    pragma excused the error path from coverage, and the error path was where
    the error was. A missing attribute on a sibling package is exactly the
    kind of thing a static read cannot excuse and an import can confirm, so it
    is checked here for every reference at once rather than trusted per call
    site.
    """
    import re
    from pathlib import Path

    import os_helper as osh

    package = Path(__file__).resolve().parent.parent / "speaker_helper"
    missing = {
        f"osh.{name} ({path.name})"
        for path in package.rglob("*.py")
        for name in re.findall(r"\bosh\.([a-zA-Z_][a-zA-Z0-9_]*)", path.read_text(encoding="utf-8"))
        if not hasattr(osh, name)
    }
    assert not missing, f"these os_helper names do not exist: {sorted(missing)}"


def test_the_eardrum_loop_runs_as_a_job_and_reports_each_word(monkeypatch, tmp_path) -> None:
    """POST starts it and answers 202 at once; GET reads the words when done."""
    from speaker_helper.eardrum import EardrumReport
    from speaker_helper.eardrum.loop import Attempt, Take, WordResult

    seen: dict = {}

    async def fake_run(settings, **kwargs):  # type: ignore[no-untyped-def]
        """Record the call, return one fixed word."""
        seen.update(kwargs, language=settings.language)
        page = tmp_path / "index.html"
        page.write_text("<h1>Ralph Eardrum Loop</h1>", encoding="utf-8")
        word = WordResult(
            "Feynman",
            "fr",
            "mock",
            target={"variants": ["fajnman"], "source": "wikipedia"},
            attempts=[
                Attempt("Faïnemane", "respelling", "llm", 0.06, [Take("", 0.06, "f a j n", "")])
            ],
            best=0,
            verdict="fixed",
            saved=True,
        )
        return EardrumReport(results=[word], html=page, meta={"engine": "mock"})

    monkeypatch.setattr("speaker_helper.eardrum.run_eardrum_async", fake_run)
    with _client() as client:
        started = client.post("/eardrum", json={"words": ["Feynman"], "language": "fr"})
        assert started.status_code == 202
        job_id = started.json()["job_id"]
        status = client.get(f"/eardrum/{job_id}").json()
        for _ in range(50):
            if status["status"] != "running":
                break
            status = client.get(f"/eardrum/{job_id}").json()
        assert status["status"] == "done"
        assert status["words"][0] == {
            "word": "Feynman",
            "verdict": "fixed",
            "best": "Faïnemane",
            "score": 0.06,
            "heard": "f a j n",
            "target": ["fajnman"],
            "target_source": "wikipedia",
            "saved": True,
            "note": "",
        }
        assert "Ralph Eardrum Loop" in client.get(f"/eardrum/{job_id}/report").text
    assert seen["words"] == ["Feynman"] and seen["language"] == "fr"


def test_the_eardrum_route_refuses_what_it_cannot_do() -> None:
    """Nothing to check, listen_all without text, an unknown job: all said plainly."""
    with _client() as client:
        nothing = {"include_lexicon": False}
        assert client.post("/eardrum", json=nothing).status_code == 400
        assert client.post("/eardrum", json={"listen_all": True}).status_code == 400
        assert client.get("/eardrum/nope").status_code == 404
        assert client.get("/eardrum/nope/report").status_code == 404


def test_a_failing_eardrum_job_says_why(monkeypatch) -> None:
    """An error inside the loop lands on the job, not in a 500."""

    async def boom(settings, **kwargs):  # type: ignore[no-untyped-def]
        """Fail like a missing extra would."""
        raise ImportError("pip install 'speaker-helper[eardrum]'")

    monkeypatch.setattr("speaker_helper.eardrum.run_eardrum_async", boom)
    with _client() as client:
        job_id = client.post("/eardrum", json={"words": ["x"]}).json()["job_id"]
        status = client.get(f"/eardrum/{job_id}").json()
        for _ in range(50):
            if status["status"] != "running":
                break
            status = client.get(f"/eardrum/{job_id}").json()
        assert status["status"] == "failed" and "eardrum" in status["error"]


def test_the_prosody_check_runs_as_the_same_kind_of_job(monkeypatch, tmp_path) -> None:
    """prosody: true runs the intonation/arousal loop and returns agreement + tuned segments."""
    import json

    from speaker_helper.eardrum.expressive import ExpressionResult, ExpressionTake, ProsodyReport

    async def fake_run(settings, segments, **kwargs):  # type: ignore[no-untyped-def]
        """One segment, fixed by marking the question."""
        take = ExpressionTake(
            "marked_question", "Tu viens ?!", "neutral", "", "normal", "rise", True, 0.1, True
        )
        result = ExpressionResult(
            text=segments[0]["text"],
            language="fr",
            expected_contour={"shape": "rise", "reason": "yes/no question without marker"},
            expected=None,
            takes=[take],
            best=0,
            verdict="fixed",
        )
        tuned = tmp_path / "segments.tuned.json"
        tuned.write_text(
            json.dumps([{"text": "Tu viens ?", "say": "Tu viens ?!"}]), encoding="utf-8"
        )
        page = tmp_path / "index.html"
        page.write_text("<h1>prosodie</h1>", encoding="utf-8")
        assert kwargs["tune"] is True
        return ProsodyReport(results=[result], html=page, tuned=tuned, meta={})

    monkeypatch.setattr("speaker_helper.eardrum.expressive.run_prosody_async", fake_run)
    with _client() as client:
        assert (
            client.post("/eardrum", json={"prosody": True, "include_lexicon": False}).status_code
            == 400
        )
        job_id = client.post("/eardrum", json={"prosody": True, "text": "Tu viens ?"}).json()[
            "job_id"
        ]
        status = client.get(f"/eardrum/{job_id}").json()
        for _ in range(50):
            if status["status"] != "running":
                break
            status = client.get(f"/eardrum/{job_id}").json()
        assert status["status"] == "done", status
        assert status["segments"][0]["verdict"] == "fixed"
        assert status["tuned_segments"][0]["say"] == "Tu viens ?!"


def test_narrate_can_choose_its_takes_by_ear() -> None:
    """select > 0: each block's choice comes back in the response."""
    import pytest

    pytest.importorskip("librosa")
    with _client() as client:
        answer = client.post("/narrate", json={"segments": ["Un.", "Deux."], "select": 2})
        assert answer.status_code == 200, answer.text
        selection = answer.json()["selection"]
        assert [r["index"] for r in selection] == [0, 1]
        assert all(1 <= r["draws"] <= 2 for r in selection)
