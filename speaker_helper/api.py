"""
REST API server for speaker-helper.

Module summary
--------------
A thin FastAPI façade over :class:`~speaker_helper.speaker.Speaker`, suitable
for running as a Docker service. It exposes:

* ``GET  /health`` — liveness plus the in-process engine's own health.
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
* ``POST /eardrum`` — start the Ralph Eardrum Loop on a text and/or words; it
  answers ``202`` at once with a ``job_id``. ``GET /eardrum/{job_id}`` reads
  the job (``running``, ``done`` with one entry per word, or ``failed`` with
  the error); ``GET /eardrum/{job_id}/report`` serves the HTML report. A job,
  not a request held open: the loop takes minutes.

This module imports FastAPI/pydantic/uvicorn at import time, so it is only ever
imported behind the ``server`` extra (the CLI imports it lazily, and the core
package never imports it). Keeping the request model at module scope lets
FastAPI correctly resolve it as a request **body** rather than query params.

Usage example
-------------
.. code-block:: bash

    speaker-helper serve --bind-host 0.0.0.0 --bind-port 8080
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


class NarrateRequest(BaseModel):
    """Request body for ``POST /narrate``.

    Parameters
    ----------
    segments : list
        The document's blocks. Each is an object with ``text`` and optionally
        ``say`` (what to pronounce, when it differs from what the page shows),
        ``pause_before_ms``, ``pause_after_ms``, ``pace`` and ``emotion``.
        Plain strings are accepted for the simple case.
    language : str or None
        Override the configured target language.
    voice : str or None
        Override the configured voice.
    read_math : str or None
        Language in which to speak any notation the blocks contain. The cues
        keep the page's own text either way — that is the point of the pair.
    """

    segments: list = Field(..., min_length=1, description="The document's blocks.")
    language: str | None = Field(None, description="Override target language.")
    voice: str | None = Field(None, description="Override the voice.")
    read_math: str | None = Field(None, description="Speak notation as words in this language.")


class RouteRequestBody(BaseModel):
    """Request body for ``POST /route``.

    Parameters
    ----------
    condition : str
        ``"online_realtime"`` (delay-bounded streaming) or ``"offline"``
        (quality-only batch).
    language : str
        ISO-639-1 target language driving the candidate catalogue.
    rtf_ceiling : float
        Online only: the ``mean_rtf`` an engine must beat to keep up (default
        ``0.8``).
    rtf_budget : float or None
        Offline only: optional patience cap on ``mean_rtf``.
    quality_floor : float or None
        Reject candidates below this quality in either condition.
    """

    condition: str = Field(..., description="online_realtime | offline")
    language: str = Field("fr", description="Target language (ISO-639-1).")
    rtf_ceiling: float = Field(0.8, description="Online RTF ceiling (must keep up).")
    rtf_budget: float | None = Field(None, description="Offline RTF patience cap.")
    quality_floor: float | None = Field(None, description="Minimum quality to accept.")


class EardrumRequest(BaseModel):
    """Request body for ``POST /eardrum`` (the Ralph Eardrum Loop).

    Parameters
    ----------
    text : str or None
        A document: its lexicon words and the words at risk it holds (proper
        nouns, acronyms, foreign words) are checked.
    words : list of str
        Explicit words to check.
    language : str or None
        Override the configured language.
    include_lexicon : bool
        Also check the lexicon's entries (all of them when no ``text``).
    listen_all : bool
        Say the whole ``text`` first and add every word heard wrong.
    max_iter : int
        Most respellings the LLM proposes per word.
    threshold : float
        Phonetic distance at or below which a word counts as said right.
    web : bool
        Look targets up on Wiktionary / Wikipedia.
    llm : bool
        Let the local LLM propose respellings.
    dry_run : bool
        Report, but save nothing to the verified sidecar.
    prosody : bool
        Check intonation and arousal (text against voice) instead of
        pronunciation; ``segments`` or ``text`` give the sentences.
    segments : list or None
        Narration segments (``text``, ``say``, ``emotion``, ``intensity``,
        ``pace``) for the prosody check.
    measure_only : bool
        With ``prosody``: measure the agreement, try no lever.
    """

    text: str | None = Field(None, description="A document to check.")
    prosody: bool = Field(False, description="Check intonation and emotion instead.")
    segments: list | None = Field(None, description="Narration segments (prosody).")
    measure_only: bool = Field(False, description="Prosody: measure only, no tuning.")
    words: list[str] = Field(default_factory=list, description="Explicit words to check.")
    language: str | None = Field(None, description="Override target language.")
    include_lexicon: bool = Field(True, description="Also check lexicon entries.")
    listen_all: bool = Field(False, description="Say the whole text; add words heard wrong.")
    max_iter: int = Field(4, ge=0, le=12, description="Most LLM respellings per word.")
    threshold: float = Field(0.25, gt=0, le=1, description="Distance counted as right.")
    web: bool = Field(True, description="Look targets up on Wiktionary / Wikipedia.")
    llm: bool = Field(True, description="Let the local LLM propose respellings.")
    dry_run: bool = Field(False, description="Report only; save nothing.")


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
    # Resolve configuration once and build the single shared Speaker that every
    # request handler below closes over (one pooled HTTP client for the app).
    settings = settings or Settings.load()
    speaker = Speaker(settings)
    # /synth/stream is the streaming cell of the matrix. When the backend's
    # engine depends on the mode (`auto`, `elevenlabs`) and the configured mode
    # is offline, it needs its own Speaker — built on first use, so a server
    # that never streams never loads a second engine. Otherwise it is the same.
    from speaker_helper.engine import for_streaming

    stream_settings = for_streaming(settings)
    streamers: list[Speaker] = [] if stream_settings is not settings else [speaker]

    def stream_speaker() -> Speaker:
        """The Speaker that serves streaming requests (see above)."""
        if not streamers:
            streamers.append(Speaker(stream_settings))
        return streamers[0]

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Manage the shared engine's startup/shutdown for the app's lifetime.

        Yields
        ------
        None
            Control is yielded to the running application between warmup and
            teardown; nothing is passed back.
        """
        # One Speaker (and its pooled HTTP client) for the app's lifetime.
        # Warm the engine up front so the first client request is not the one
        # that pays the model download / load.
        await speaker.warmup()
        yield
        # On shutdown, release whatever the engine holds (ONNX session, …).
        await speaker.aclose()
        if streamers and streamers[0] is not speaker:
            await streamers[0].aclose()

    # Wire the lifespan into the app so warmup/teardown run around serving.
    app = FastAPI(title="speaker-helper", version=_version(), lifespan=lifespan)

    @app.get("/health", operation_id="health")
    async def health() -> dict:
        """Return server liveness and the backend's own health."""
        try:
            # Liveness is trivially true (we answered); the interesting signal is
            # whether the backend could synthesise right now — a missing package
            # or absent weights, not a missing socket — so ask it.
            upstream = await speaker.engine.health()
        except Exception as exc:  # noqa: BLE001 - report the failure verbatim
            # We are up but the engine is not: report "degraded" rather than 5xx
            # so callers can distinguish "server dead" from "engine unusable".
            return {"status": "degraded", "backend": settings.backend, "engine_error": str(exc)}
        return {"status": "ok", "backend": settings.backend, "engine": upstream}

    @app.get("/voices", operation_id="list_voices")
    async def voices(engine: str | None = Query(None)) -> dict:
        """List preset voices for an engine."""
        listing = await speaker.voices(engine)
        return {"engine": listing.engine, "voices": [vars(v) for v in listing.voices]}

    @app.post("/route", operation_id="route")
    async def route_endpoint(req: RouteRequestBody) -> dict:
        """Choose an engine + mode from measured quality↔speed evidence.

        Returns the routing decision (engine, mode, streaming knobs, the
        provenance of each number, and a number-citing justification) for the requested
        condition — ``online_realtime`` (speed=RTF, must keep up) or ``offline``
        (quality only). See :mod:`speaker_helper.router`.
        """
        # Imported here so the router stays out of the API's import-time cost.
        from speaker_helper.router import RouteRequest, route

        try:
            decision = route(
                RouteRequest(
                    condition=req.condition,
                    language=req.language,
                    rtf_ceiling=req.rtf_ceiling,
                    rtf_budget=req.rtf_budget,
                    quality_floor=req.quality_floor,
                )
            )
        # A bad condition or an infeasible request is the caller's fault -> 400.
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return decision.to_dict()

    @app.post("/synth", operation_id="synth")
    async def synth(req: SynthRequest) -> Response:
        """Synthesise text and return an ``audio/wav`` body."""
        try:
            # Whole-text (offline) synthesis: one WAV back in one response.
            result = await speaker.say(req.text, language=req.language)
        # Bad input (e.g. empty text) is the client's fault -> 400.
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # Anything else is an upstream engine failure -> 502 (bad gateway).
        except Exception as exc:  # noqa: BLE001 - surface engine failures as 502
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        # Expose duration/RTF as headers so callers can measure without decoding.
        headers = {
            "X-Audio-Duration-S": f"{result.duration_s:.3f}",
            "X-Audio-RTF": f"{result.rtf:.3f}",
        }
        return Response(content=result.wav_bytes, media_type="audio/wav", headers=headers)

    @app.post("/narrate", operation_id="narrate")
    async def narrate(req: NarrateRequest) -> dict:
        """Read a document aloud and return the audio *with* its cues.

        JSON rather than ``audio/wav``, unlike ``/synth``: the cues are the
        reason this route exists, and a caller that only wanted the sound
        already has ``/synth``. The audio rides along base64-encoded, which
        costs a third more bytes and keeps the answer one object.
        """
        from speaker_helper.narration import coerce_segments, resolve_spoken_math

        try:
            segments = coerce_segments(req.segments)
            if req.read_math:
                segments = resolve_spoken_math(segments, req.read_math)
            result = await speaker.narrate(segments, language=req.language, voice=req.voice)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - surface engine failures as 502
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return {
            "audio_wav_base64": base64.b64encode(result.wav_bytes).decode("ascii"),
            "vtt": result.to_vtt(),
            "duration_s": round(result.duration_s, 3),
            "rtf": round(result.rtf, 3),
            "voice_id": result.voice_id,
            "language": result.language,
            "language_fallback": result.language_fallback,
            "ignored_hints": result.ignored_hints,
            "cues": [
                {
                    "index": cue.index,
                    "text": cue.text,
                    "start_seconds": round(cue.start_seconds, 3),
                    "end_seconds": round(cue.end_seconds, 3),
                }
                for cue in result.cues
            ],
        }

    @app.post("/synth/stream", operation_id="synth_stream")
    async def synth_stream(req: SynthRequest) -> StreamingResponse:
        """Stream synthesis as Server-Sent Events, one per sentence-sized chunk.

        Emits each chunk's audio (base64 WAV) and metadata as soon as it is
        ready, so a client can start playing before the whole text is
        synthesised. A terminal ``event: error`` is sent if synthesis fails
        mid-stream (the HTTP status is already 200 by then).
        """

        async def events() -> AsyncIterator[bytes]:
            """Yield one SSE ``data:`` frame per synthesised chunk.

            Yields
            ------
            bytes
                A Server-Sent-Events frame: normally a ``data:`` line carrying
                the chunk metadata and base64 WAV; on failure, a terminal
                ``event: error`` frame with the error detail.
            """
            try:
                # Forward each streaming chunk to the client the moment it is
                # ready, so playback can start before the whole text is done.
                async for chunk in stream_speaker().stream(req.text, language=req.language):
                    # Serialise chunk metadata + audio into the SSE payload.
                    # ttfa_s is only meaningful on the first chunk (else None).
                    payload = {
                        "seq": chunk.seq,
                        "duration_s": round(chunk.audio.duration_s, 3),
                        "rtf": round(chunk.audio.rtf, 3),
                        "ttfa_s": (round(chunk.ttfa_s, 3) if chunk.ttfa_s is not None else None),
                        "is_final": chunk.is_final,
                        "audio": base64.b64encode(chunk.audio.wav_bytes).decode("ascii"),
                    }
                    # SSE frames are terminated by a blank line.
                    yield f"data: {json.dumps(payload)}\n\n".encode()
            # Bad input surfaces as an error frame (status is already 200 here).
            except ValueError as exc:
                yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n".encode()
            # Engine failures mid-stream: log and tell the client via an error frame.
            except Exception as exc:  # noqa: BLE001 - surface engine failures to the client
                osh.warning("stream failed: %s", exc)
                yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n".encode()

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/clone", operation_id="clone_voice")
    async def clone(
        name: str = Form(..., description="Name for the cloned voice profile."),
        files: list[UploadFile] = File(..., description="Reference audio recordings."),
        reference_texts: list[str] = Form(
            default=[], description="Transcripts, one per file (auto-transcribed if omitted)."
        ),
    ) -> dict:
        """Clone a voice from uploaded reference audio and return its id.

        Any file without a matching ``reference_texts`` entry is transcribed
        with ``vocal-helper``. The cloned voice becomes the server's active
        voice, so subsequent ``/synth`` calls use it.
        """
        # Pair each uploaded file with its transcript by position; a file with no
        # matching transcript gets "" and is auto-transcribed downstream.
        samples = [
            VoiceSample(
                audio=await f.read(),
                reference_text=(reference_texts[i] if i < len(reference_texts) else ""),
            )
            for i, f in enumerate(files)
        ]
        try:
            # Register the clone; it becomes the server's active voice on success.
            voice_id = await speaker.clone_voice(name, samples)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - surface engine/clone failures as 502
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"voice_id": voice_id}

    # The Ralph Eardrum Loop says every word several times through the real
    # engine: minutes, not a request to hold open. So it runs as a job — POST
    # starts it and answers at once with an id, GET reads its state and, when
    # done, the results; the HTML report with the takes is served beside them.
    # One job at a time: the loop already saturates the engine, and two of
    # them would only halve each other's speed. It gets its own Speaker,
    # because it swaps the lexicon in and out word by word and must not do
    # that under a /synth request.
    eardrum_jobs: dict[str, dict] = {}

    @app.post("/eardrum", operation_id="eardrum_start", status_code=202)
    async def eardrum_start(req: EardrumRequest) -> dict:
        """Start the Ralph Eardrum Loop; answer with a job id to poll."""
        import asyncio
        import dataclasses
        import uuid

        if req.prosody and not (req.text or req.segments):
            raise HTTPException(status_code=400, detail="prosody needs text or segments")
        if not req.text and not req.words and not req.include_lexicon:
            raise HTTPException(status_code=400, detail="nothing to check: give text or words")
        if req.listen_all and not req.text:
            raise HTTPException(status_code=400, detail="listen_all needs a text")
        if any(job["status"] == "running" for job in eardrum_jobs.values()):
            raise HTTPException(status_code=409, detail="an eardrum job is already running")
        job_settings = dataclasses.replace(settings)
        if req.language:
            job_settings.language = req.language
        job_id = uuid.uuid4().hex[:12]
        job: dict = {"id": job_id, "status": "running", "words": [], "report": None}
        eardrum_jobs[job_id] = job

        async def run() -> None:
            """Run the loop, then store its summary (or its error) on the job."""
            from speaker_helper.eardrum import run_eardrum_async

            if req.prosody:
                await run_prosody_job()
                return
            try:
                report = await run_eardrum_async(
                    job_settings,
                    text=req.text,
                    words=req.words or None,
                    include_lexicon=req.include_lexicon,
                    listen_everything=req.listen_all,
                    max_iter=req.max_iter,
                    threshold=req.threshold,
                    web=req.web,
                    llm=req.llm,
                    dry_run=req.dry_run,
                )
            except Exception as exc:  # noqa: BLE001 - reported on the job, not raised
                job.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                return
            job.update(
                status="done",
                report=str(report.html) if report.html else None,
                verified_path=str(report.verified_path) if report.verified_path else None,
                meta=report.meta,
                words=[_eardrum_summary(r) for r in report.results],
            )

        async def run_prosody_job() -> None:
            """The prosody variant: per segment, expected against measured."""
            from speaker_helper.eardrum.expressive import run_prosody_async, segments_from_text
            from speaker_helper.narration import coerce_segments

            try:
                segments = (
                    [
                        {k: v for k, v in vars(b).items() if isinstance(v, str) and v}
                        for b in coerce_segments(req.segments)
                    ]
                    if req.segments
                    else segments_from_text(req.text or "")
                )
                report = await run_prosody_async(
                    job_settings, segments, tune=not req.measure_only, infer=req.llm
                )
            except Exception as exc:  # noqa: BLE001 - reported on the job, not raised
                job.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                return
            job.update(
                status="done",
                report=str(report.html) if report.html else None,
                tuned_segments=json.loads(report.tuned.read_text(encoding="utf-8")),
                agreement=report.agreement,
                meta=report.meta,
                segments=[
                    {
                        "text": r.text,
                        "verdict": r.verdict,
                        "expected_contour": r.expected_contour,
                        "expected": r.expected,
                        "takes": [dataclasses.asdict(t) for t in r.takes],
                        "best": r.best,
                    }
                    for r in report.results
                ],
            )

        # Keep a reference so the task is not garbage-collected mid-run.
        job["_task"] = asyncio.create_task(run())
        return {"job_id": job_id, "status": "running"}

    @app.get("/eardrum/{job_id}", operation_id="eardrum_status")
    async def eardrum_status(job_id: str) -> dict:
        """State of an eardrum job: running, done (with each word), or failed."""
        job = eardrum_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no eardrum job {job_id!r}")
        return {k: v for k, v in job.items() if not k.startswith("_")}

    @app.get("/eardrum/{job_id}/report", operation_id="eardrum_report")
    async def eardrum_report(job_id: str) -> Response:
        """The job's HTML report (every attempt, its score, what was heard)."""
        from pathlib import Path

        job = eardrum_jobs.get(job_id)
        if job is None or not job.get("report"):
            raise HTTPException(status_code=404, detail=f"no report for job {job_id!r} yet")
        page = Path(job["report"]).read_text(encoding="utf-8")
        return Response(content=page, media_type="text/html")

    # Republish the routes above as agent tools. Before the GUI, because the
    # GUI mounts a catch-all at ``/``.
    _mount_mcp(app)

    # Serve the minimal single-page GUI at ``/`` (added last so the explicit API
    # routes above always take precedence over the static catch-all).
    _mount_gui(app)

    return app


def _eardrum_summary(result: object) -> dict:
    """One word's eardrum result, as the job status reports it.

    Parameters
    ----------
    result : WordResult
        The loop's result for one word.

    Returns
    -------
    dict
        Word, verdict, best spelling and score, what was heard, target,
        whether it was saved, and the note for the human.
    """
    attempts = getattr(result, "attempts", [])
    best_index = getattr(result, "best", -1)
    best = attempts[best_index] if attempts and best_index >= 0 else None
    target = getattr(result, "target", None) or {}
    return {
        "word": getattr(result, "word", ""),
        "verdict": getattr(result, "verdict", ""),
        "best": best.candidate if best else None,
        "score": best.score if best else None,
        "heard": best.takes[0].heard if best and best.takes else None,
        "target": target.get("variants"),
        "target_source": target.get("source"),
        "saved": getattr(result, "saved", False),
        "note": getattr(result, "note", ""),
    }


def _mount_mcp(app: FastAPI) -> None:
    """Mount the MCP endpoint over the routes this app already serves.

    Guarded against ``Exception``, not only ``ImportError``, and that width is
    the whole lesson of the last attempt. ``fastapi-mcp`` 0.4.0 called the
    ``mcp`` SDK with an argument count it no longer accepted; the result was a
    ``TypeError`` out of :func:`create_app`, which a narrower guard let
    through — so an optional surface took down *every* API test, not only its
    own. An agent tool nobody can reach is a missing feature; an HTTP API that
    will not construct is an outage.

    The pin that makes the pairing work lives in the ``mcp`` extra.
    """
    try:
        from fastapi_mcp import FastApiMCP
    except ImportError:
        # The ordinary case: installed without the `mcp` extra.
        return

    try:
        server = FastApiMCP(
            app,
            name="speaker-helper",
            description=(
                "Speech synthesis as agent tools: say a sentence, list the "
                "voices, clone one from a recording, narrate a document "
                "with the cues that say where each block is spoken, and run "
                "the Ralph Eardrum Loop that checks pronunciation by ear."
            ),
        )
        # Newer releases split mount() into transport-specific mount_http()
        # and mount_sse(); fall back so a range of versions keeps working.
        if hasattr(server, "mount_http"):
            server.mount_http()
        else:  # pragma: no cover - legacy fastapi-mcp
            server.mount()
    except Exception as exc:  # pragma: no cover - version-pairing guard
        osh.warning(
            f"MCP surface not mounted ({type(exc).__name__}: {exc}). The HTTP "
            f"API is unaffected; `pip install 'speaker-helper[mcp]'` installs "
            f"a pairing known to work."
        )


def _mount_gui(app: FastAPI) -> None:
    """Mount the bundled single-page GUI at ``/`` when its assets are present.

    The GUI (``speaker_helper/gui/index.html`` + ``app.js``) is a dependency-free
    vanilla-JS + Tailwind page that drives ``/synth``, ``/synth/stream``,
    ``/voices``, ``/clone`` and ``/route`` from the browser. ``html=True`` makes
    the mount serve ``index.html`` for ``/`` and the relative ``./app.js`` it
    references. A no-op (with a warning) if the assets are missing from the
    install.
    """
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    # Resolve the packaged gui/ directory next to this module.
    gui_dir = Path(__file__).parent / "gui"
    if not osh.file_exists(str(gui_dir / "index.html")):
        # Missing assets are not fatal — the JSON API works without the GUI.
        osh.warning("GUI assets not found at %s; not serving the web UI", gui_dir)
        return
    # Mounted at "/" with html=True: "/" -> index.html, "/app.js" -> app.js.
    app.mount("/", StaticFiles(directory=str(gui_dir), html=True), name="gui")
    osh.info("GUI mounted at /")


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
    # Import uvicorn lazily so the core package never requires the server extra.
    import uvicorn

    osh.info("starting speaker-helper API on %s:%d", host, port)
    # Blocking call: hands control to uvicorn's event loop until interrupted.
    uvicorn.run(create_app(settings), host=host, port=port)


def _version() -> str:
    """Return the package version without importing the whole package eagerly."""
    from speaker_helper import __version__

    return __version__
