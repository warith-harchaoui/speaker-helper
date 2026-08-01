"""
Command-line interface for speaker-helper.

Module summary
--------------
Exposes the library as a terminal tool with four sub-commands:

* ``synth`` — synthesise text (or stdin) to a ``.wav`` file, offline or
  streaming, printing the measured duration and real-time factor.
* ``voices`` — list the preset voices of an engine.
* ``clone`` — register a cloned voice from reference audio (default: the bundled
  ref-fr-female) and print its id; missing transcripts come from ``vocal-helper``.
* ``eval`` — evaluate the engine against a dataset and gate on versioned
  thresholds (exit code ``0`` pass / ``1`` fail); see :mod:`speaker_helper.eval`.
* ``speak-from`` — re-voice audio from a YouTube URL, podcast feed, or the
  microphone (speech-to-speech); see :mod:`speaker_helper.sources`.
* ``serve`` — run the REST API server (see :mod:`speaker_helper.api`).

The ``--clone`` family of flags works with any command: ``speaker-helper --clone
synth "Bonjour"`` synthesises in the cloned ref-fr-female voice.

Argument parsing uses the standard-library :mod:`argparse` so the CLI has no
third-party dependency of its own.

Usage example
-------------
.. code-block:: bash

    speaker-helper synth "Bonjour le monde." -o hello.wav --engine kokoro
    echo "Texte depuis stdin." | speaker-helper synth -o out.wav
    speaker-helper voices --engine kokoro
    speaker-helper serve --host 0.0.0.0 --port 8080

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import os_helper as osh

from speaker_helper.config import Settings
from speaker_helper.speaker import Speaker

if TYPE_CHECKING:
    # Imported only for type-checking so the runtime import path stays lazy
    # (these pull in optional/heavier modules used by a subset of commands).
    from speaker_helper.eval import Thresholds
    from speaker_helper.transcription import VocalHelperTranscriber


def _build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser and its sub-commands."""
    parser = argparse.ArgumentParser(
        prog="speaker-helper",
        description="Text-to-speech (offline + streaming) over a local TTS engine.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to settings.yaml (default: ./settings.yaml if present).",
    )
    # Global overrides: they precede the sub-command and win over settings.yaml.
    parser.add_argument("--backend", default=None, help="TTS backend: voicebox (default) or mock.")
    parser.add_argument("--host", default=None, help="Voicebox host override.")
    parser.add_argument("--port", type=int, default=None, help="Voicebox port override.")
    parser.add_argument("--engine", default=None, help="Engine/model id (e.g. kokoro).")
    parser.add_argument("--voice", default=None, help="Preset voice id (default: auto).")
    parser.add_argument("--language", default=None, help="Target language (e.g. fr).")
    # Cloning: enable a cloned voice for any command. --clone alone uses the
    # bundled ref-fr-female reference; --clone-audio/--clone-text override it. A
    # missing transcript is derived automatically with vocal-helper.
    parser.add_argument(
        "--clone",
        action="store_true",
        help="Use a cloned voice (default reference: bundled ref-fr-female).",
    )
    parser.add_argument(
        "--clone-name",
        default=None,
        help="Name for the cloned voice profile (default: ref-fr-female).",
    )
    parser.add_argument("--clone-audio", default=None, help="Reference audio file to clone from.")
    parser.add_argument(
        "--clone-text",
        default=None,
        help="Transcript of --clone-audio (auto-transcribed if omitted).",
    )

    # One sub-command is mandatory; each gets its own argument group below.
    sub = parser.add_subparsers(dest="command", required=True)

    # `synth`: text (or stdin) -> WAV, offline or streaming.
    p_synth = sub.add_parser("synth", help="Synthesise text to a WAV file.")
    p_synth.add_argument(
        "text", nargs="?", default=None, help="Text to speak; omit to read from stdin."
    )
    p_synth.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("out.wav"),
        help="Output WAV path (default: out.wav).",
    )
    p_synth.add_argument(
        "--stream",
        action="store_true",
        help="Streaming mode: report time-to-first-audio and cadence.",
    )

    # `voices`: enumerate an engine's preset voices.
    p_voices = sub.add_parser("voices", help="List preset voices for an engine.")
    p_voices.add_argument("--engine", default=None, help="Engine id (default: configured).")

    # `clone`: register a cloned voice (uses the global --clone* flags) and print its id.
    sub.add_parser("clone", help="Register a cloned voice from reference audio and print its id.")

    # `eval`: measure the engine against a dataset and gate on thresholds.
    p_eval = sub.add_parser(
        "eval", help="Evaluate the engine against a dataset and gate on thresholds."
    )
    p_eval.add_argument(
        "--dataset", type=Path, default=None, help="JSONL dataset (default: built-in French set)."
    )
    p_eval.add_argument(
        "--thresholds", type=Path, default=None, help="Thresholds YAML (default: built-in bar)."
    )
    p_eval.add_argument(
        "--json",
        dest="json_out",
        type=Path,
        default=None,
        help="Write the full JSON report to this path.",
    )
    p_eval.add_argument(
        "--languages",
        default=None,
        help="Comma-separated language codes to measure "
        "(e.g. fr,en,es); prints a per-language matrix.",
    )
    # Opt-in fidelity round-trip: re-transcribe the synthesised audio with
    # vocal-helper (the ``stt`` extra) and gate on WER/chrF. Off by default
    # because it needs a real engine and STT, which CI does not have.
    p_eval.add_argument(
        "--transcribe",
        action="store_true",
        help="Re-transcribe output (vocal-helper) and gate on WER/chrF.",
    )

    # `speak-from`: speech-to-speech — pull audio from a source and re-voice it.
    p_from = sub.add_parser(
        "speak-from", help="Re-voice audio from a source (youtube / podcast / microphone)."
    )
    p_from.add_argument(
        "--source",
        choices=["youtube", "podcast", "mic"],
        required=True,
        help="Where the audio comes from.",
    )
    p_from.add_argument("--url", default=None, help="YouTube video URL or podcast feed URL.")
    p_from.add_argument(
        "--seconds", type=float, default=5.0, help="Microphone capture duration (mic source)."
    )
    p_from.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("out.wav"),
        help="Output WAV path (default: out.wav).",
    )

    # `route`: choose an engine + mode from measured quality<->speed evidence.
    p_route = sub.add_parser(
        "route",
        help="Choose the best engine + mode for a condition (online real-time / offline).",
    )
    p_route.add_argument(
        "--condition",
        choices=["online_realtime", "offline"],
        required=True,
        help="online_realtime (delay-bounded streaming; speed=RTF) or offline (quality only).",
    )
    p_route.add_argument("--language", default="fr", help="Target language (default: fr).")
    p_route.add_argument(
        "--rtf-ceiling",
        dest="rtf_ceiling",
        type=float,
        default=0.8,
        help="Online only: max mean RTF an engine must beat to keep up (default 0.8).",
    )
    p_route.add_argument(
        "--rtf-budget",
        dest="rtf_budget",
        type=float,
        default=None,
        help="Offline only: optional patience cap on mean RTF.",
    )
    p_route.add_argument(
        "--quality-floor",
        dest="quality_floor",
        type=float,
        default=None,
        help="Reject candidates below this quality (0..1).",
    )
    p_route.add_argument(
        "--json",
        dest="json_out",
        type=Path,
        default=None,
        help="Write the full decision JSON to this path.",
    )

    # Distinct dests so the server's *bind* address never collides with the
    # top-level *Voicebox* --host/--port in the shared argparse namespace.
    p_serve = sub.add_parser("serve", help="Run the REST API server.")
    p_serve.add_argument("--host", dest="bind_host", default="127.0.0.1", help="Bind host.")
    p_serve.add_argument("--port", dest="bind_port", type=int, default=8080, help="Bind port.")

    return parser


def _settings_from_args(args: argparse.Namespace) -> Settings:
    """Load settings from ``--config`` and apply CLI overrides."""
    # Start from the file/defaults, then let any explicitly-passed flag win.
    # `getattr(..., None)` guards flags that only exist on some sub-commands.
    settings = Settings.load(args.config)
    if getattr(args, "backend", None):
        settings.backend = args.backend
    if getattr(args, "host", None):
        settings.voicebox.host = args.host
    if getattr(args, "port", None):
        settings.voicebox.port = args.port
    if getattr(args, "engine", None):
        settings.engine = args.engine
    if getattr(args, "voice", None):
        settings.voice_id = args.voice
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


def _cmd_synth(args: argparse.Namespace, settings: Settings) -> int:
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


def _cmd_voices(args: argparse.Namespace, settings: Settings) -> int:
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


def _cmd_serve(args: argparse.Namespace, settings: Settings) -> int:
    """Handle the ``serve`` sub-command; return a process exit code."""
    from speaker_helper.api import serve

    serve(settings, host=args.bind_host, port=args.bind_port)
    return 0


def _cmd_route(args: argparse.Namespace, settings: Settings) -> int:
    """Handle the ``route`` sub-command; print the chosen operating point.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed CLI arguments (``condition``, ``language``, ``rtf_ceiling``,
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
    rtf = "n/a" if decision.mean_rtf is None else f"{decision.mean_rtf:.3f}"
    sys.stdout.write(
        f"condition={decision.condition} engine={decision.engine} mode={decision.mode}\n"
        f"quality={decision.quality:.3f} ({decision.quality_source}) "
        f"mean_rtf={rtf} ({decision.rtf_source}) confidence={decision.confidence}\n"
        f"{decision.justification}\n"
    )
    return 0


def _cmd_clone(args: argparse.Namespace, settings: Settings) -> int:
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


def _build_transcriber(args: argparse.Namespace) -> VocalHelperTranscriber | None:
    """Return a fidelity transcriber when ``--transcribe`` was passed, else ``None``.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed CLI arguments; only ``transcribe`` and ``language`` are read.

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


def _cmd_eval_multilang(
    args: argparse.Namespace, settings: Settings, thresholds: Thresholds
) -> int:
    """Run the evaluation across ``--languages`` and print a matrix; gate on all.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed CLI arguments (``languages``, ``json_out``, ``transcribe``).
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


def _cmd_speak_from(args: argparse.Namespace, settings: Settings) -> int:
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


def _cmd_eval(args: argparse.Namespace, settings: Settings) -> int:
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


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Parameters
    ----------
    argv : list of str or None
        Argument vector; defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Process exit code (0 on success).
    """
    # Configure the ecosystem's logging surface once, at the entry point, so
    # INFO-level progress is visible to CLI users.
    osh.init_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    # Merge file config with CLI overrides once, then dispatch on the command.
    settings = _settings_from_args(args)
    # Each branch delegates to a `_cmd_*` handler that returns the exit code.
    if args.command == "synth":
        return _cmd_synth(args, settings)
    if args.command == "voices":
        return _cmd_voices(args, settings)
    if args.command == "clone":
        return _cmd_clone(args, settings)
    if args.command == "eval":
        return _cmd_eval(args, settings)
    if args.command == "speak-from":
        return _cmd_speak_from(args, settings)
    if args.command == "route":
        return _cmd_route(args, settings)
    if args.command == "serve":
        return _cmd_serve(args, settings)
    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
