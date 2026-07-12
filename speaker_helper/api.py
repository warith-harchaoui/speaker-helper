"""
REST API server for speaker-helper.

Module summary
--------------
A thin FastAPI façade over :class:`~speaker_helper.speaker.Speaker`, suitable
for running as a Docker service. It exposes:

* ``GET  /health`` — liveness plus the upstream Voicebox health.
* ``GET  /voices`` — preset voices for the configured (or requested) engine.
* ``POST /synth`` — synthesise ``{"text": ..., "language": ...}`` and return a
  ``audio/wav`` body.

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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from speaker_helper.config import Settings
from speaker_helper.logging_utils import get_logger
from speaker_helper.speaker import Speaker

log = get_logger(__name__)


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


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    Parameters
    ----------
    settings : Settings or None
        Configuration; defaults to :meth:`Settings.load`.

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
        yield
        await speaker.aclose()

    app = FastAPI(title="speaker-helper", version=_version(), lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        """Return server liveness and upstream Voicebox health."""
        try:
            upstream = await speaker.client.health()
        except Exception as exc:  # noqa: BLE001 - report upstream failure verbatim
            return {"status": "degraded", "voicebox_error": str(exc)}
        return {"status": "ok", "voicebox": upstream}

    @app.get("/voices")
    async def voices(engine: str | None = Query(None)) -> dict:
        """List preset voices for an engine."""
        listing = await speaker.voices(engine)
        return {"engine": listing.engine, "voices": [vars(v) for v in listing.voices]}

    @app.post("/synth")
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

    return app


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

    log.info("starting speaker-helper API on %s:%d", host, port)
    uvicorn.run(create_app(settings), host=host, port=port)


def _version() -> str:
    """Return the package version without importing the whole package eagerly."""
    from speaker_helper import __version__

    return __version__
