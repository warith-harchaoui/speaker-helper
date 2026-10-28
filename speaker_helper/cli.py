"""
Command-line interface for speaker-helper.

Module summary
--------------
One command line, built with `click <https://click.palletsprojects.com>`_:
``speaker-helper``. It exposes the library as a terminal tool whose
sub-commands cover the three jobs the package exists for and the operations
around them:

* ``synth`` — speak text (or stdin) into a ``.wav``, offline or streaming,
  printing the measured duration and real-time factor.
* ``narrate`` — read a document aloud and write the WebVTT cues beside the
  audio, so a page can follow the reading.
* ``voices`` — list an engine's preset voices.
* ``clone`` — register a cloned voice from reference audio (default: the
  bundled ref-fr-female) and print its id; a missing transcript comes from
  ``vocal-helper``.
* ``speak-from`` — re-voice audio from a YouTube URL, a podcast feed or the
  microphone; see :mod:`speaker_helper.sources`.
* ``route`` — choose engine + mode from measured quality↔speed evidence.
* ``eval`` — measure the engine against a dataset and gate on versioned
  thresholds (exit ``0`` pass / ``1`` fail); see :mod:`speaker_helper.eval`.
* ``install-voice`` — fetch an engine's weights before anything depends on them.
* ``health`` — report whether the configured backend can run, and exit
  non-zero when it cannot.
* ``serve`` — run the REST API server; see :mod:`speaker_helper.api`.

Global options (``--backend``, ``--engine``, ``--language``, the ``--clone``
family, …) sit on the top-level **group**, so they precede the sub-command:
``speaker-helper --backend mock synth "hi"``, ``speaker-helper --engine kokoro
voices``. They are stashed on the click context and merged into the flag bag
each command handler reads.

Each ``_cmd_*`` handler takes that bag and returns a process exit code, so the
command logic stays testable without a terminal; the click layer above it only
parses.

Usage example
-------------
.. code-block:: bash

    speaker-helper synth "Bonjour le monde." -o hello.wav --engine kokoro
    echo "Texte depuis stdin." | speaker-helper synth -o out.wav
    speaker-helper --engine kokoro voices
    speaker-helper route --condition online_realtime --language fr
    speaker-helper serve --bind-host 0.0.0.0 --bind-port 8080

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import click
import os_helper as osh

from speaker_helper import __version__
from speaker_helper.config import Settings
from speaker_helper.speaker import Speaker

if TYPE_CHECKING:
    # Imported only for type-checking so the runtime import path stays lazy
    # (these pull in optional/heavier modules used by a subset of commands).
    from speaker_helper.eval import Thresholds
    from speaker_helper.transcription import VocalHelperTranscriber


def _settings_from_args(args: SimpleNamespace) -> Settings:
    """Load settings from ``--config`` and apply CLI overrides."""
    # Start from the file/defaults, then let any explicitly-passed flag win.
    # `getattr(..., None)` guards flags that only exist on some sub-commands.
    settings = Settings.load(args.config)
    if getattr(args, "backend", None):
        settings.backend = args.backend
    if getattr(args, "engine", None):
        settings.engine = args.engine
    if getattr(args, "voice", None):
        settings.voice = args.voice
    if getattr(args, "voice_sample", None):
        settings.voice_sample = args.voice_sample
    if getattr(args, "language", None):
        settings.language = args.language

    # Any --clone* flag (or the `clone` command) enables a cloned voice.
    clone_requested = (
        getattr(args, "clone", False)
        or getattr(args, "clone_audio", None)
        or getattr(args, "clone_name", None)
        or args.command == "clone"
    )
    if clone_requested:
        # Copy the settings' clone mapping so per-invocation flag overrides do
        # not mutate the loaded configuration in place.
        clone: dict[str, object] = dict(settings.clone)
        if getattr(args, "clone_name", None):
            clone["name"] = args.clone_name
        if getattr(args, "clone_audio", None):
            clone["audio"] = args.clone_audio
        if getattr(args, "clone_text", None):
            clone["reference_text"] = args.clone_text
        settings.clone = clone
    return settings


def _cmd_synth(args: SimpleNamespace, settings: Settings) -> int:
    """Handle the ``synth`` sub-command; return a process exit code."""
    # Text comes from the positional argument, or stdin when it is omitted.
    text = args.text if args.text is not None else sys.stdin.read()
    # Refuse to synthesise nothing: a blank input is a usage error (exit 2).
    if not text or not text.strip():
        osh.error("no text provided (argument or stdin)")
        return 2

    async def run() -> int:
        """Drive one synthesis (streaming or offline) and write the WAV.

        Returns
        -------
        int
            ``0`` on success; exceptions propagate to :func:`asyncio.run`.
        """
        async with Speaker(settings) as spk:
            if args.stream:
                # Streaming path: collect per-sentence chunks as they arrive,
                # tracking time-to-first-audio and total duration for the report.
                first_ttfa: float | None = None
                total_audio = 0.0
                buffers: list[bytes] = []
                async for chunk in spk.stream(text):
                    # The first chunk carries the TTFA measurement; keep it.
                    if chunk.ttfa_s is not None:
                        first_ttfa = chunk.ttfa_s
                    total_audio += chunk.audio.duration_s
                    buffers.append(chunk.audio.wav_bytes)
                    osh.info(
                        "chunk %d: %.2fs audio (RTF %.2f)",
                        chunk.seq,
                        chunk.audio.duration_s,
                        chunk.audio.rtf,
                    )
                # Stitch the streamed chunks into a single output WAV.
                _concat_wavs(buffers, args.out)
                osh.info(
                    "streamed %.2fs audio to %s (TTFA %.2fs)",
                    total_audio,
                    args.out,
                    first_ttfa or 0.0,
                )
            else:
                # Offline path: one call yields the whole audio at once.
                result = await spk.say(text)
                Path(args.out).write_bytes(result.wav_bytes)
                osh.info(
                    "wrote %s (%.2fs audio, RTF %.2f)", args.out, result.duration_s, result.rtf
                )
        return 0

    return asyncio.run(run())


def _cmd_narrate(args: SimpleNamespace, settings: Settings) -> int:
    """Handle the ``narrate`` sub-command; return a process exit code.

    Writes two files, not one. The WAV is the obvious half; the ``.vtt``
    beside it is what lets a page highlight the block being read, and it costs
    nothing to produce because the offsets were already computed to lay the
    audio out.
    """
    import json

    from speaker_helper.narration import coerce_segments, resolve_spoken_math

    raw = json.loads(args.segments.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        sys.stderr.write("the segments file must hold a JSON list\n")
        return 2
    segments = coerce_segments(raw)
    if args.read_math:
        segments = resolve_spoken_math(segments, args.read_math)

    async def run() -> int:
        async with Speaker(settings) as spk:
            result = await spk.narrate(segments)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(result.wav_bytes)
        cues_path = args.out.with_suffix(".vtt")
        cues_path.write_text(result.to_vtt(), encoding="utf-8")
        sys.stdout.write(
            f"{args.out}\t{result.duration_s:.2f}s\t{len(result.cues)} cues\t"
            f"rtf {result.rtf:.2f}\n{cues_path}\n"
        )
        if result.ignored_hints:
            # Not a failure, and not silent either: the document asked for
            # something this engine has no dial for.
            sys.stderr.write(
                f"note: this backend has no dial for {', '.join(result.ignored_hints)}\n"
            )
        return 0

    return asyncio.run(run())


def _cmd_install_voice(args: SimpleNamespace, settings: Settings) -> int:
    """Handle the ``install-voice`` sub-command; return a process exit code."""
    from speaker_helper.install import install_engine

    return install_engine(args.engine, force=args.force)


def _cmd_health(args: SimpleNamespace, settings: Settings) -> int:
    """Handle the ``health`` sub-command; return a process exit code.

    Exits non-zero when the backend could not synthesise, so this works as a
    gate in a script rather than only as something to read.
    """
    import json

    async def run() -> int:
        async with Speaker(settings) as spk:
            report = await spk.engine.health()
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        return 0 if report.get("status") == "ok" else 1

    return asyncio.run(run())


def _cmd_voices(args: SimpleNamespace, settings: Settings) -> int:
    """Handle the ``voices`` sub-command; return a process exit code."""

    async def run() -> int:
        """List the engine's preset voices, one per tab-separated line.

        Returns
        -------
        int
            ``0`` on success.
        """
        async with Speaker(settings) as spk:
            listing = await spk.voices(args.engine)
            # This is user-facing CLI output, so writing to stdout is correct.
            for voice in listing.voices:
                sys.stdout.write(
                    f"{voice.voice_id}\t{voice.language}\t{voice.gender}\t{voice.name}\n"
                )
        return 0

    return asyncio.run(run())


def _cmd_serve(args: SimpleNamespace, settings: Settings) -> int:
    """Handle the ``serve`` sub-command; return a process exit code."""
    from speaker_helper.api import serve

    serve(settings, host=args.bind_host, port=args.bind_port)
    return 0


def _cmd_route(args: SimpleNamespace, settings: Settings) -> int:
    """Handle the ``route`` sub-command; print the chosen operating point.

    Parameters
    ----------
    args : types.SimpleNamespace
        Parsed CLI flags (``condition``, ``language``, ``rtf_ceiling``,
        ``rtf_budget``, ``quality_floor``, ``json_out``).
    settings : Settings
        Unused for the decision itself (kept for a uniform handler signature).

    Returns
    -------
    int
        ``0`` on a successful decision, ``2`` when the request is infeasible
        (e.g. no engine keeps up online).
    """
    import json

    from speaker_helper.router import RouteRequest, route

    # Build the request straight from the flags; the router validates the
    # condition and constraints and raises on an infeasible ask.
    try:
        decision = route(
            RouteRequest(
                condition=args.condition,
                language=args.language,
                rtf_ceiling=args.rtf_ceiling,
                rtf_budget=args.rtf_budget,
                quality_floor=args.quality_floor,
            )
        )
    except ValueError as exc:
        # An infeasible/invalid request is a usage error, not a crash.
        osh.error("routing failed: %s", exc)
        return 2
    # Optional machine-readable dump before the human summary.
    if args.json_out is not None:
        args.json_out.write_text(
            json.dumps(decision.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        osh.info("wrote decision JSON to %s", args.json_out)
    # User-facing verdict on stdout: the headline choice plus the justification.
    # No RTF on an offline verdict. Speed is not an objective there, so the
    # router hands us mean_rtf=None; printing "mean_rtf=n/a" would still put the
    # word in front of the reader and invite them to wonder what it would have
    # been. The pair appears only for the condition that ranks on it.
    rtf_part = (
        ""
        if decision.mean_rtf is None
        else f"mean_rtf={decision.mean_rtf:.3f} ({decision.rtf_source}) "
    )
    sys.stdout.write(
        f"condition={decision.condition} engine={decision.engine} mode={decision.mode}\n"
        f"quality={decision.quality:.3f} ({decision.quality_source}) "
        f"{rtf_part}".rstrip()
        # An arbitration is headline news: without this the summary line reads
        # like the engine won on the numbers, which is exactly what it did not do.
        + (" owner_ratified=True" if decision.owner_ratified else "")
        + f"\n{decision.justification}\n"
    )
    return 0


def _cmd_clone(args: SimpleNamespace, settings: Settings) -> int:
    """Handle the ``clone`` sub-command; register a voice and print its id."""

    async def run() -> int:
        """Register the configured clone and emit its voice id.

        Returns
        -------
        int
            ``0`` on success.
        """
        async with Speaker(settings) as spk:
            # Uses the clone reference resolved from settings (default ref-fr-female).
            voice_id = await spk.clone_voice()
        # User-facing: print the id so it can be captured / reused.
        sys.stdout.write(voice_id + "\n")
        return 0

    return asyncio.run(run())


def _build_transcriber(args: SimpleNamespace) -> VocalHelperTranscriber | None:
    """Return a fidelity transcriber when ``--transcribe`` was passed, else ``None``.

    Parameters
    ----------
    args : types.SimpleNamespace
        Parsed CLI flags; only ``transcribe`` and ``language`` are read.

    Returns
    -------
    VocalHelperTranscriber or None
        A vocal-helper-backed transcriber enabling the WER/chrF round-trip, or
        ``None`` when fidelity was not requested.

    Notes
    -----
    Imported lazily so ``vocal-helper`` stays optional (the ``stt`` extra): it is
    only needed when the user opts into ``--transcribe``.
    """
    # No fidelity requested: keep vocal-helper out of the import path entirely.
    if not getattr(args, "transcribe", False):
        return None
    # Build the adapter in the configured language (defaults to French).
    from speaker_helper.transcription import VocalHelperTranscriber

    return VocalHelperTranscriber(getattr(args, "language", None) or "fr")


def _cmd_eval_multilang(args: SimpleNamespace, settings: Settings, thresholds: Thresholds) -> int:
    """Run the evaluation across ``--languages`` and print a matrix; gate on all.

    Parameters
    ----------
    args : types.SimpleNamespace
        Parsed CLI flags (``languages``, ``json_out``, ``transcribe``).
    settings : Settings
        Base configuration; language/voice are overridden per language.
    thresholds : Thresholds
        Pass/fail bar applied to every language.

    Returns
    -------
    int
        ``0`` when every language passes, ``1`` otherwise.
    """
    import json

    from speaker_helper.eval import format_matrix, run_multilang_eval

    # Split "fr,en,es" into a clean list, dropping empty entries.
    languages = [lang.strip() for lang in args.languages.split(",") if lang.strip()]
    # Optional fidelity round-trip, shared across every language.
    transcriber = _build_transcriber(args)

    async def run() -> int:
        """Evaluate every requested language, print the matrix, gate on all.

        Returns
        -------
        int
            ``0`` only if every language passes its threshold bar, else ``1``.
        """
        # Measure each language against the shared thresholds in one pass.
        reports = await run_multilang_eval(
            settings, languages, thresholds=thresholds, transcriber=transcriber
        )
        # Human-readable per-language matrix on stdout.
        sys.stdout.write(format_matrix(reports) + "\n")
        # Optional machine-readable dump for CI artifacts / dashboards.
        if args.json_out is not None:
            args.json_out.write_text(
                json.dumps(
                    {lang: r.to_dict() for lang, r in reports.items()}, ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )
            osh.info("wrote JSON matrix to %s", args.json_out)
        return 0 if all(r.passed for r in reports.values()) else 1

    return asyncio.run(run())


def _cmd_speak_from(args: SimpleNamespace, settings: Settings) -> int:
    """Handle ``speak-from``: transcribe a source and re-voice it to a WAV file."""
    from speaker_helper.sources import (
        from_microphone,
        from_podcast,
        from_youtube,
        revoice,
    )

    async def run() -> int:
        """Resolve the requested source, re-voice it, and write the WAV.

        Returns
        -------
        int
            ``0`` on success, ``2`` when a required ``--url`` is missing.
        """
        # youtube/podcast sources need a URL; the mic source does not.
        if args.source in ("youtube", "podcast") and not args.url:
            osh.error("--url is required for the %s source", args.source)
            return 2
        # Build the source adapter matching the requested origin.
        if args.source == "youtube":
            src = from_youtube(args.url)
        elif args.source == "podcast":
            src = from_podcast(args.url)
        else:
            src = await from_microphone(args.seconds)
        async with Speaker(settings) as spk:
            result = await revoice(src, spk)
            Path(args.out).write_bytes(result.wav_bytes)
            osh.info(
                "re-voiced %s -> %s (%.2fs audio, RTF %.2f)",
                src.origin,
                args.out,
                result.duration_s,
                result.rtf,
            )
        return 0

    return asyncio.run(run())


def _cmd_eval(args: SimpleNamespace, settings: Settings) -> int:
    """Handle the ``eval`` sub-command; return 0 if the gate passes, 1 if not."""
    import json

    from speaker_helper.eval import Thresholds, load_dataset, run_eval

    thresholds = Thresholds.load(args.thresholds)

    if getattr(args, "languages", None):
        return _cmd_eval_multilang(args, settings, thresholds)

    cases = load_dataset(args.dataset)
    # Optional fidelity round-trip (WER/chrF) via vocal-helper; None otherwise.
    transcriber = _build_transcriber(args)

    async def run() -> int:
        """Run the single-language evaluation and print the pass/fail verdict.

        Returns
        -------
        int
            ``0`` if the report passes the threshold bar, ``1`` otherwise.
        """
        # Evaluate every dataset case against the engine under the thresholds.
        async with Speaker(settings) as spk:
            report = await run_eval(spk, cases, thresholds=thresholds, transcriber=transcriber)
        # Optional machine-readable dump before the human summary.
        if args.json_out is not None:
            args.json_out.write_text(
                json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            osh.info("wrote JSON report to %s", args.json_out)
        # User-facing verdict on stdout so it is greppable / pipeable.
        sys.stdout.write(
            f"backend={report.backend} engine={settings.engine} cases={report.n_cases}\n"
            f"mean_rtf={report.mean_rtf} p95_rtf={report.p95_rtf} "
            f"anomaly_rate={report.anomaly_rate} "
            f"quality={report.quality} ({report.quality_source})\n"
            f"{'PASS' if report.passed else 'FAIL'}"
            + ("" if report.passed else ": " + "; ".join(report.failures))
            + "\n"
        )
        return 0 if report.passed else 1

    return asyncio.run(run())


def _concat_wavs(buffers: list[bytes], out: Path) -> None:
    """Concatenate streamed WAV chunks into one file via ``audio-helper``.

    Each in-memory chunk is written to a temporary file and stitched together
    with :func:`audio_helper.audio_concatenation`, which handles heterogeneous
    encodings robustly — the ecosystem's audio path rather than a hand-rolled
    numpy concat.
    """
    # Imported lazily so a plain `synth` (offline) never pulls in audio-helper.
    import audio_helper as ah
    import os_helper as osh

    # Spill each in-memory chunk to a temp file so audio-helper can stitch them.
    with osh.temporary_folder() as tmp:
        parts: list[str] = []
        for i, buf in enumerate(buffers):
            # Zero-pad the index so lexical order matches playback order.
            part = osh.join(tmp, f"chunk_{i:04d}.wav")
            Path(part).write_bytes(buf)
            parts.append(part)
        # Concatenate through the ecosystem's robust encoder-aware path.
        ah.audio_concatenation(parts, output_audio_filename=str(out), overwrite=True)


# Every sub-command name, mapped to the handler that runs it. Keeping the table
# explicit rather than dispatching on the click function's own name is what
# lets a test assert that no command is reachable without a handler behind it.
_HANDLERS = {
    "synth": _cmd_synth,
    "voices": _cmd_voices,
    "clone": _cmd_clone,
    "eval": _cmd_eval,
    "speak-from": _cmd_speak_from,
    "route": _cmd_route,
    "serve": _cmd_serve,
    "narrate": _cmd_narrate,
    "install-voice": _cmd_install_voice,
    "health": _cmd_health,
}


def _run(ctx: click.Context, command: str, **fields: object) -> None:
    """Merge global + command flags, then dispatch to the handler.

    Parameters
    ----------
    ctx : click.Context
        The click context; ``ctx.obj`` holds the group-level global options.
    command : str
        Sub-command name (``synth``, ``route``, …).
    **fields
        Command-specific flag values.

    Raises
    ------
    SystemExit
        Always: the handler's integer exit code is propagated to the shell.
    """
    # Globals (from the group) first, then the command's own fields — one flag
    # bag drives both the settings merge and the handler, so a handler never
    # needs to know which option sat where on the command line.
    merged = {**(ctx.obj or {}), **fields}
    args = SimpleNamespace(command=command, **merged)
    settings: Settings = _settings_from_args(args)
    raise SystemExit(_HANDLERS[command](args, settings))


# The global options live on the GROUP, not on each command, so they precede
# the sub-command: `speaker-helper --engine kokoro voices`, never the reverse.
# `-h` is declared next to `--help` because the short spelling is the first
# thing a user tries, and `-V` next to `--version` because `-v` is taken by
# verbosity everywhere in this suite. The version is passed explicitly: reading
# it from the installed distribution metadata reports whatever was last
# pip-installed, which an editable checkout then misreports.
@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", package_name="speaker-helper")
@click.option("--config", type=click.Path(path_type=Path), default=None, help="settings.yaml path.")
@click.option(
    "--backend",
    default=None,
    help="TTS backend: kokoro (default), openvoice, chatterbox or mock.",
)
@click.option("--voice-sample", default=None, help="Reference recording to clone.")
@click.option("--engine", default=None, help="Engine/model id (e.g. kokoro).")
@click.option("--voice", default=None, help="Preset voice id (default: auto).")
@click.option("--language", default=None, help="Target language (e.g. fr).")
@click.option(
    "--clone", is_flag=True, default=False, help="Use a cloned voice (default: ref-fr-female)."
)
@click.option("--clone-name", default=None, help="Name for the cloned voice profile.")
@click.option("--clone-audio", default=None, help="Reference audio file to clone from.")
@click.option("--clone-text", default=None, help="Transcript of --clone-audio (auto if omitted).")
@click.pass_context
def cli(ctx: click.Context, **globals_: object) -> None:
    """Text-to-speech (offline + streaming) over a local TTS engine.

    The options above are global: they apply to every sub-command and have to
    precede it, as in: speaker-helper --backend mock synth "hi"
    """
    # Configure the ecosystem logging surface once, at the entry point, so
    # INFO-level progress is visible rather than swallowed.
    osh.init_logging()
    # Stash the global options for the sub-command handlers to merge in.
    ctx.obj = dict(globals_)


@cli.command()
@click.argument("text", required=False, default=None)
@click.option(
    "-o",
    "--out",
    "out",
    type=click.Path(path_type=Path),
    default=Path("out.wav"),
    help="Output WAV path.",
)
@click.option("--stream", is_flag=True, default=False, help="Streaming mode: report TTFA/cadence.")
@click.pass_context
def synth(ctx: click.Context, text: str | None, out: Path, stream: bool) -> None:
    """Synthesise TEXT (or stdin) to a WAV file."""
    # text=None tells the handler to read the utterance from stdin;
    # --stream selects the low-TTFA streaming path over whole-text synthesis.
    _run(ctx, "synth", text=text, out=out, stream=stream)


@cli.command()
@click.pass_context
def clone(ctx: click.Context) -> None:
    """Register a cloned voice from reference audio and print its id."""
    # The clone reference comes from the global --clone/--clone-audio/--clone-name
    # options (merged from ctx.obj), so this command carries no options of its own.
    _run(ctx, "clone")


@cli.command()
@click.option(
    "--condition",
    type=click.Choice(["online_realtime", "offline"]),
    required=True,
    help="online_realtime (speed=RTF) or offline (quality only).",
)
@click.option("--rtf-ceiling", "rtf_ceiling", type=float, default=0.8, help="Online: max mean RTF.")
@click.option("--rtf-budget", "rtf_budget", type=float, default=None, help="Offline: RTF cap.")
@click.option(
    "--quality-floor", "quality_floor", type=float, default=None, help="Reject quality below this."
)
@click.option(
    "--json",
    "json_out",
    type=click.Path(path_type=Path),
    default=None,
    help="Write decision JSON here.",
)
@click.pass_context
def route(
    ctx: click.Context,
    condition: str,
    rtf_ceiling: float,
    rtf_budget: float | None,
    quality_floor: float | None,
    json_out: Path | None,
) -> None:
    """Choose the best engine + mode for a condition (online real-time / offline)."""
    # _cmd_route reads args.language directly; the global --language may be None,
    # so default it to fr here to match the router's own default.
    language = (ctx.obj or {}).get("language") or "fr"
    _run(
        ctx,
        "route",
        condition=condition,
        language=language,
        rtf_ceiling=rtf_ceiling,
        rtf_budget=rtf_budget,
        quality_floor=quality_floor,
        json_out=json_out,
    )


@cli.command(name="narrate")
@click.argument("segments", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--out",
    type=click.Path(path_type=Path),
    default=Path("narration.wav"),
    help="Output WAV; the cues are written beside it as .vtt.",
)
@click.option(
    "--read-math",
    metavar="LANG",
    default=None,
    help="Speak the notation as words in LANG, leaving the cues as the page reads.",
)
@click.pass_context
def narrate(ctx: click.Context, segments: Path, out: Path, read_math: str | None) -> None:
    """Read a document aloud, and write the timed track that follows it.

    SEGMENTS is a JSON list of blocks, each with `text` and optionally `say`,
    `pause_before_ms`, `pause_after_ms`, `pace` and `emotion`. A list of plain
    strings works too.
    """
    _run(ctx, "narrate", segments=segments, out=out, read_math=read_math)


@cli.command(name="install-voice")
@click.option("--engine", default="kokoro", help="Which engine to prepare.")
@click.option("--force", is_flag=True, default=False, help="Re-download even if present.")
@click.pass_context
def install_voice(ctx: click.Context, engine: str, force: bool) -> None:
    """Download the weights an engine needs, before anything depends on them."""
    _run(ctx, "install-voice", engine=engine, force=force)


@cli.command(name="health")
@click.pass_context
def health(ctx: click.Context) -> None:
    """Report whether the configured backend can run; exit non-zero if not."""
    _run(ctx, "health")


@cli.command(name="voices")
@click.pass_context
def voices_cmd(ctx: click.Context) -> None:
    """List preset voices for an engine (uses the global --engine)."""
    # Named voices_cmd (not voices) to avoid shadowing; registered as "voices".
    # The engine to list comes from the global --engine, which precedes the
    # sub-command: `speaker-helper --engine kokoro voices`.
    _run(ctx, "voices")


@cli.command(name="eval")
@click.option("--dataset", type=click.Path(path_type=Path), default=None, help="JSONL dataset.")
@click.option(
    "--thresholds", type=click.Path(path_type=Path), default=None, help="Thresholds YAML."
)
@click.option(
    "--json",
    "json_out",
    type=click.Path(path_type=Path),
    default=None,
    help="Write JSON report here.",
)
@click.option("--languages", default=None, help="Comma-separated languages (e.g. fr,en,es).")
@click.option(
    "--transcribe", is_flag=True, default=False, help="Round-trip WER/chrF via vocal-helper."
)
@click.pass_context
def eval_cmd(
    ctx: click.Context,
    dataset: Path | None,
    thresholds: Path | None,
    json_out: Path | None,
    languages: str | None,
    transcribe: bool,
) -> None:
    """Evaluate the engine against a dataset and gate on thresholds."""
    # The handler returns a non-zero exit code when the bar is missed, which
    # _run propagates as SystemExit — so `eval` gates CI. --languages runs the
    # per-language matrix; --transcribe adds the WER/chrF round-trip.
    _run(
        ctx,
        "eval",
        dataset=dataset,
        thresholds=thresholds,
        json_out=json_out,
        languages=languages,
        transcribe=transcribe,
    )


@cli.command(name="speak-from")
@click.option(
    "--source",
    type=click.Choice(["youtube", "podcast", "mic"]),
    required=True,
    help="Audio source.",
)
@click.option("--url", default=None, help="YouTube video URL or podcast feed URL.")
@click.option("--seconds", type=float, default=5.0, help="Microphone capture duration.")
@click.option(
    "-o",
    "--out",
    "out",
    type=click.Path(path_type=Path),
    default=Path("out.wav"),
    help="Output WAV path.",
)
@click.pass_context
def speak_from(ctx: click.Context, source: str, url: str | None, seconds: float, out: Path) -> None:
    """Re-voice audio from a source (youtube / podcast / microphone)."""
    # --url is required for youtube/podcast (the handler validates it); the mic
    # source uses --seconds instead. The source is transcribed then re-spoken.
    _run(ctx, "speak-from", source=source, url=url, seconds=seconds, out=out)


@cli.command()
@click.option("--bind-host", "bind_host", default="127.0.0.1", help="API server bind host.")
@click.option("--bind-port", "bind_port", type=int, default=8080, help="API server bind port.")
@click.pass_context
def serve(ctx: click.Context, bind_host: str, bind_port: int) -> None:
    """Run the REST API server.

    The bind address is spelled --bind-host / --bind-port. The longer spelling
    is deliberate: this program used to carry a global --host / --port aimed at
    a REMOTE engine, and two pairs one word apart, on the same line, pointing
    at different machines, is how a server ends up calling itself for /health.
    """
    _run(ctx, "serve", bind_host=bind_host, bind_port=bind_port)


def main() -> None:
    """Console-script entry point: run the click command group."""
    cli()


if __name__ == "__main__":  # pragma: no cover
    main()
