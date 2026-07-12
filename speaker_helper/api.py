"""
REST API server for speaker-helper.

Module summary
--------------
A thin FastAPI façade over :class:`~speaker_helper.speaker.Speaker`, suitable
for running as a Docker service. It exposes:

* ``GET  /health`` — liveness plus the upstream engine health.
* ``GET  /voices`` — preset voices for the configured (or requested) engine.
* ``POST /synth`` — synthesise ``{"text": ..., "language": ...}`` and return a
  ``audio/wav`` body (offline: whole text in one response).
* ``POST /synth/stream`` — same body, but stream Server-Sent Events, one per
  sentence-sized chunk, as soon as each is ready (low time-to-first-audio).
  Each event's ``data`` is JSON with ``seq``, ``duration_s``, ``rtf``,
  ``ttfa_s`` (first chunk only), ``is_final``, and base64 ``audio`` (WAV).
* ``POST /clone`` — multipart upload of reference audio (plus optional
  transcripts) to clone a voice; missing transcripts come from ``vocal-helper``.
  The clone becomes the server's active voice for subsequent ``/synth`` calls.

When ``fastapi-mcp`` is installed, a Model Context Protocol server is also
mounted at ``/mcp``, exposing these endpoints as MCP tools so an assistant can
synthesise, stream, clone, and list voices directly.

This module imports FastAPI/pydantic/uvicorn at import time, so it is only ever
imported behind the ``server`` extra (the CLI imports it lazily, and the core
package never imports it). Keeping the request model at module scope lets
FastAPI correctly resolve it as a request **body** rather than query params.

Usage example
-------------
.. code-block:: bash

    speaker-helper serve --host 0.0.0.0 --port 8080
    curl -s -X POST localhost:8080/synth -H 'content-type: application/json' \\
         -d '{"text": "Bonjour."}' -o out.wav

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import os_helper as osh
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from speaker_helper.config import Settings
from speaker_helper.speaker import Speaker
from speaker_helper.types import VoiceSample


class SynthRequest(BaseModel):
    """Request body for ``POST /synth``.

    Parameters
    ----------
    text : str
        Text to synthesise (non-empty).
    language : str or None
        Optional override of the configured target language.
    """

    text: str = Field(..., min_length=1, description="Text to synthesise.")
    language: str | None = Field(None, description="Override target language.")


def create_app(settings: Settings | None = None, *, enable_mcp: bool = True) -> FastAPI:
    """Build the FastAPI application.

    Parameters
    ----------
    settings : Settings or None
        Configuration; defaults to :meth:`Settings.load`.
    enable_mcp : bool
        When ``True`` (default) and ``fastapi-mcp`` is installed, mount a Model
        Context Protocol server at ``/mcp`` that exposes the REST endpoints as
        MCP tools — so an MCP client (an assistant) can synthesise, clone, and
        list voices directly. Silently skipped if ``fastapi-mcp`` is absent.

    Returns
    -------
    fastapi.FastAPI
        The configured application. A single shared :class:`Speaker` is created
        at startup and closed at shutdown.
    """
    settings = settings or Settings.load()
    speaker = Speaker(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # One Speaker (and its pooled HTTP client) for the app's lifetime.
        # Warm the engine up front so the first client request is not the one
        # that pays the model download / load.
        await speaker.warmup()
        yield
        await speaker.aclose()

    app = FastAPI(title="speaker-helper", version=_version(), lifespan=lifespan)

    @app.get("/health", operation_id="health")
    async def health() -> dict:
        """Return server liveness and upstream Voicebox health."""
        try:
            upstream = await speaker.engine.health()
        except Exception as exc:  # noqa: BLE001 - report upstream failure verbatim
            return {"status": "degraded", "backend": settings.backend, "engine_error": str(exc)}
        return {"status": "ok", "backend": settings.backend, "engine": upstream}

    @app.get("/voices", operation_id="list_voices")
    async def voices(engine: str | None = Query(None)) -> dict:
        """List preset voices for an engine."""
        listing = await speaker.voices(engine)
        return {"engine": listing.engine, "voices": [vars(v) for v in listing.voices]}

    @app.post("/synth", operation_id="synth")
    async def synth(req: SynthRequest) -> Response:
        """Synthesise text and return an ``audio/wav`` body."""
        try:
            result = await speaker.say(req.text, language=req.language)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - surface engine failures as 502
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        headers = {
            "X-Audio-Duration-S": f"{result.duration_s:.3f}",
            "X-Audio-RTF": f"{result.rtf:.3f}",
        }
        return Response(content=result.wav_bytes, media_type="audio/wav", headers=headers)

    @app.post("/synth/stream", operation_id="synth_stream")
    async def synth_stream(req: SynthRequest) -> StreamingResponse:
        """Stream synthesis as Server-Sent Events, one per sentence-sized chunk.

        Emits each chunk's audio (base64 WAV) and metadata as soon as it is
        ready, so a client can start playing before the whole text is
        synthesised. A terminal ``event: error`` is sent if synthesis fails
        mid-stream (the HTTP status is already 200 by then).
        """
        async def events() -> AsyncIterator[bytes]:
            try:
                async for chunk in speaker.stream(req.text, language=req.language):
                    payload = {
                        "seq": chunk.seq,
                        "duration_s": round(chunk.audio.duration_s, 3),
                        "rtf": round(chunk.audio.rtf, 3),
                        "ttfa_s": (round(chunk.ttfa_s, 3) if chunk.ttfa_s is not None else None),
                        "is_final": chunk.is_final,
                        "audio": base64.b64encode(chunk.audio.wav_bytes).decode("ascii"),
                    }
                    yield f"data: {json.dumps(payload)}\n\n".encode()
            except ValueError as exc:
                yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n".encode()
            except Exception as exc:  # noqa: BLE001 - surface engine failures to the client
                osh.warning("stream failed: %s", exc)
                yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n".encode()

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/clone", operation_id="clone_voice")
    async def clone(
        name: str = Form(..., description="Name for the cloned voice profile."),
        files: list[UploadFile] = File(..., description="Reference audio recordings."),
        reference_texts: list[str] = Form(
            default=[], description="Transcripts, one per file (auto-transcribed if omitted)."),
    ) -> dict:
        """Clone a voice from uploaded reference audio and return its id.

        Any file without a matching ``reference_texts`` entry is transcribed
        with ``vocal-helper``. The cloned voice becomes the server's active
        voice, so subsequent ``/synth`` calls use it.
        """
        samples = [
            VoiceSample(
                audio=await f.read(),
                reference_text=(reference_texts[i] if i < len(reference_texts) else ""),
            )
            for i, f in enumerate(files)
        ]
        try:
            voice_id = await speaker.clone_voice(name, samples)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - surface engine/clone failures as 502
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"voice_id": voice_id}

    if enable_mcp:
        _mount_mcp(app)

    return app


def _mount_mcp(app: FastAPI) -> None:
    """Mount an MCP server at ``/mcp`` exposing the REST endpoints as tools.

    Uses ``fastapi-mcp`` to turn each operation (``synth``, ``synth_stream``,
    ``clone_voice``, ``list_voices``, ``health``) into a Model Context Protocol
    tool, so an assistant can drive speaker-helper directly. A no-op (with a
    warning) when ``fastapi-mcp`` is not installed.
    """
    try:
        from fastapi_mcp import FastApiMCP
    except ImportError:
        osh.warning("fastapi-mcp not installed; MCP server not mounted "
                    "(install the 'mcp' extra to enable /mcp)")
        return
    mcp = FastApiMCP(
        app,
        name="speaker-helper",
        description="Text-to-speech: synthesise, stream, clone voices, list voices.",
    )
    mcp.mount_http()
    osh.info("MCP server mounted at /mcp")


def serve(settings: Settings | None = None, *, host: str = "127.0.0.1", port: int = 8080) -> None:
    """Run the API server with uvicorn (blocking).

    Parameters
    ----------
    settings : Settings or None
        Configuration; defaults to :meth:`Settings.load`.
    host : str
        Bind address.
    port : int
        Bind port.
    """
    import uvicorn

    osh.info("starting speaker-helper API on %s:%d", host, port)
    uvicorn.run(create_app(settings), host=host, port=port)


def _version() -> str:
    """Return the package version without importing the whole package eagerly."""
    from speaker_helper import __version__

    return __version__
