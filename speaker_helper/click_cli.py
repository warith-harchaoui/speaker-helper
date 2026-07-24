"""
Click-based command-line interface for speaker-helper (the primary CLI).

Module summary
--------------
speaker-helper ships two CLI front-ends over the *same* command handlers: the
standard-library :mod:`argparse` one in :mod:`speaker_helper.cli` (dependency-
free, exposed as ``speaker-helper-argparse``) and this `click
<https://click.palletsprojects.com>`_ one (the default ``speaker-helper``
entry point). Click gives nicer help, grouped sub-commands, and composable
options; to avoid two diverging implementations, every command here just builds
the :class:`argparse.Namespace` the shared ``_cmd_*`` handlers already expect and
delegates to them. So the *logic* lives once, in :mod:`speaker_helper.cli`; this
module is only a front-end.

Global options (``--backend``, ``--engine``, ``--language``, the ``--clone*``
family, …) sit on the top-level **group**, so they precede the sub-command —
``speaker-helper --backend mock synth "hi"`` — exactly like the argparse CLI's
"global flags precede the sub-command" behaviour. They are stashed on the click
context and merged into each command's namespace.

Usage example
-------------
.. code-block:: bash

    speaker-helper synth "Bonjour le monde." -o hello.wav --engine kokoro
    speaker-helper route --condition online_realtime --language fr
    speaker-helper --backend mock voices --engine kokoro
    speaker-helper serve --bind-host 0.0.0.0 --bind-port 8080

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import argparse
from pathlib import Path

import click
import os_helper as osh

from speaker_helper import cli as _argcli
from speaker_helper.config import Settings

# Map each command name to its shared handler in speaker_helper.cli, so both CLI
# front-ends run identical logic (this click module only parses arguments).
_HANDLERS = {
    "synth": _argcli._cmd_synth,
    "voices": _argcli._cmd_voices,
    "clone": _argcli._cmd_clone,
    "eval": _argcli._cmd_eval,
    "speak-from": _argcli._cmd_speak_from,
    "route": _argcli._cmd_route,
    "serve": _argcli._cmd_serve,
}


def _run(ctx: click.Context, command: str, **fields: object) -> None:
    """Merge global + command flags, then dispatch to the shared handler.

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
    # Globals (from the group) first, then the command's own fields — one
    # namespace drives both the settings merge and the handler, exactly as the
    # argparse path does, so a handler cannot tell which front-end called it.
    merged = {**(ctx.obj or {}), **fields}
    args = argparse.Namespace(command=command, **merged)
    settings: Settings = _argcli._settings_from_args(args)
    raise SystemExit(_HANDLERS[command](args, settings))


# The global options live on the GROUP (not each command) so they precede the
# sub-command — matching the argparse CLI's "globals before sub-command" order.
@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--config", type=click.Path(path_type=Path), default=None, help="settings.yaml path.")
@click.option("--backend", default=None, help="TTS backend: voicebox (default) or mock.")
@click.option("--host", default=None, help="Voicebox host override.")
@click.option("--port", type=int, default=None, help="Voicebox port override.")
@click.option("--engine", default=None, help="Engine/model id (e.g. kokoro).")
@click.option("--voice", default=None, help="Preset voice id (default: auto).")
@click.option("--language", default=None, help="Target language (e.g. fr).")
@click.option(
    "--clone", is_flag=True, default=False, help="Use a cloned voice (default: ref-malo)."
)
@click.option("--clone-name", default=None, help="Name for the cloned voice profile.")
@click.option("--clone-audio", default=None, help="Reference audio file to clone from.")
@click.option("--clone-text", default=None, help="Transcript of --clone-audio (auto if omitted).")
@click.pass_context
def cli(ctx: click.Context, **globals_: object) -> None:
    """Text-to-speech (offline + streaming) over a local TTS engine.

    Global options above apply to every sub-command and precede it, e.g.
    ``speaker-helper --backend mock synth "hi"``.
    """
    # Configure the ecosystem logging surface once, at the entry point, so
    # INFO-level progress is visible — same as the argparse CLI's main().
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
    # text=None tells the shared handler to read the utterance from stdin;
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


@cli.command(name="voices")
@click.pass_context
def voices_cmd(ctx: click.Context) -> None:
    """List preset voices for an engine (uses the global --engine)."""
    # Named voices_cmd (not voices) to avoid shadowing; registered as "voices".
    # The engine to list comes from the global --engine option.
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

    The API server's bind address uses ``--bind-host`` / ``--bind-port`` so it
    never collides with the global ``--host`` / ``--port`` (which point at the
    upstream Voicebox engine the server talks to).
    """
    # Distinct bind_host/bind_port dests are what let the server bind address and
    # the Voicebox --host/--port coexist in the one shared namespace.
    _run(ctx, "serve", bind_host=bind_host, bind_port=bind_port)


def main() -> None:
    """Console-script entry point: run the click command group."""
    cli()


if __name__ == "__main__":  # pragma: no cover
    main()
