"""
Command-line interface for speaker-helper.

Module summary
--------------
Exposes the library as a terminal tool with three sub-commands:

* ``synth`` — synthesise text (or stdin) to a ``.wav`` file, offline or
  streaming, printing the measured duration and real-time factor.
* ``voices`` — list the preset voices of an engine.
* ``serve`` — run the REST API server (see :mod:`speaker_helper.api`).

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

from speaker_helper.config import Settings
from speaker_helper.logging_utils import get_logger
from speaker_helper.speaker import Speaker

log = get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser and its sub-commands."""
    parser = argparse.ArgumentParser(
        prog="speaker-helper",
        description="Text-to-speech (offline + streaming) over a local Voicebox engine.",
    )
    parser.add_argument("--config", type=Path, default=None,
                        help="Path to settings.yaml (default: ./settings.yaml if present).")
    parser.add_argument("--host", default=None, help="Voicebox host override.")
    parser.add_argument("--port", type=int, default=None, help="Voicebox port override.")
    parser.add_argument("--engine", default=None, help="Voicebox engine (e.g. kokoro).")
    parser.add_argument("--voice", default=None, help="Preset voice id (default: auto).")
    parser.add_argument("--language", default=None, help="Target language (e.g. fr).")

    sub = parser.add_subparsers(dest="command", required=True)

    p_synth = sub.add_parser("synth", help="Synthesise text to a WAV file.")
    p_synth.add_argument("text", nargs="?", default=None,
                         help="Text to speak; omit to read from stdin.")
    p_synth.add_argument("-o", "--out", type=Path, default=Path("out.wav"),
                         help="Output WAV path (default: out.wav).")
    p_synth.add_argument("--stream", action="store_true",
                         help="Streaming mode: report time-to-first-audio and cadence.")

    p_voices = sub.add_parser("voices", help="List preset voices for an engine.")
    p_voices.add_argument("--engine", default=None, help="Engine id (default: configured).")

    # Distinct dests so the server's *bind* address never collides with the
    # top-level *Voicebox* --host/--port in the shared argparse namespace.
    p_serve = sub.add_parser("serve", help="Run the REST API server.")
    p_serve.add_argument("--host", dest="bind_host", default="127.0.0.1", help="Bind host.")
    p_serve.add_argument("--port", dest="bind_port", type=int, default=8080, help="Bind port.")

    return parser


def _settings_from_args(args: argparse.Namespace) -> Settings:
    """Load settings from ``--config`` and apply CLI overrides."""
    settings = Settings.load(args.config)
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
    return settings


def _cmd_synth(args: argparse.Namespace, settings: Settings) -> int:
    """Handle the ``synth`` sub-command; return a process exit code."""
    text = args.text if args.text is not None else sys.stdin.read()
    if not text or not text.strip():
        log.error("no text provided (argument or stdin)")
        return 2

    async def run() -> int:
        async with Speaker(settings) as spk:
            if args.stream:
                first_ttfa: float | None = None
                total_audio = 0.0
                buffers: list[bytes] = []
                async for chunk in spk.stream(text):
                    if chunk.ttfa_s is not None:
                        first_ttfa = chunk.ttfa_s
                    total_audio += chunk.audio.duration_s
                    buffers.append(chunk.audio.wav_bytes)
                    log.info("chunk %d: %.2fs audio (RTF %.2f)",
                             chunk.seq, chunk.audio.duration_s, chunk.audio.rtf)
                _concat_wavs(buffers, args.out)
                log.info("streamed %.2fs audio to %s (TTFA %.2fs)",
                         total_audio, args.out, first_ttfa or 0.0)
            else:
                result = await spk.say(text)
                Path(args.out).write_bytes(result.wav_bytes)
                log.info("wrote %s (%.2fs audio, RTF %.2f)",
                         args.out, result.duration_s, result.rtf)
        return 0

    return asyncio.run(run())


def _cmd_voices(args: argparse.Namespace, settings: Settings) -> int:
    """Handle the ``voices`` sub-command; return a process exit code."""
    async def run() -> int:
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


def _concat_wavs(buffers: list[bytes], out: Path) -> None:
    """Concatenate WAV payloads into one file (re-encoding via soundfile)."""
    import io

    import numpy as np
    import soundfile as sf

    frames: list = []
    sr = 24000
    for buf in buffers:
        data, sr = sf.read(io.BytesIO(buf), dtype="float32", always_2d=False)
        frames.append(data)
    audio = np.concatenate(frames) if frames else np.zeros(0, dtype="float32")
    sf.write(str(out), audio, sr)


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
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = _settings_from_args(args)
    if args.command == "synth":
        return _cmd_synth(args, settings)
    if args.command == "voices":
        return _cmd_voices(args, settings)
    if args.command == "serve":
        return _cmd_serve(args, settings)
    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
