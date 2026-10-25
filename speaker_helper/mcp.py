"""
The MCP surface: the same routes, republished as agent tools.

Module summary
--------------
There is no second implementation here, and that is the design. The HTTP API
in :mod:`speaker_helper.api` already describes every operation — its
parameters, its types, its ``operation_id`` — and ``fastapi-mcp`` turns that
description into a tool catalogue. An agent calling ``narrate`` and a shell
calling ``POST /narrate`` reach the same function, so the two surfaces cannot
drift into disagreeing about what this package does.

What this module adds is a way to *start* it: a console script that serves the
app with the MCP endpoint mounted, and whose defaults name this package's own
environment variables rather than a neighbour's.

The parsing is `click <https://click.palletsprojects.com>`_, like
:mod:`speaker_helper.cli` and every other command line in the suite. It used
to be ``argparse`` — the last one left in this package after the CLI moved —
which meant two parsing libraries in one wheel, two help layouts, and two
answers to ``-h``.

Why it came back
----------------
This surface was removed in 0.7.5. ``fastapi-mcp`` 0.4.0 called the ``mcp``
SDK with an argument count that release no longer accepted, and the mount was
guarded by ``except ImportError`` alone — so a ``TypeError`` escaped
``create_app()`` and broke every API test, not only the MCP ones. Both halves
are fixed: the pairing is pinned in the ``mcp`` extra, and the mount in
:func:`speaker_helper.api._mount_mcp` now catches more than ``ImportError``,
because an optional surface must never be able to take the HTTP API down.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import sys

import click

#: The command name the console script installs. Passed to click explicitly as
#: ``prog_name``: left to itself click reads ``sys.argv[0]``, which prints
#: ``mcp.py`` under ``python -m`` and the test runner's name under pytest.
_PROG = "speaker-helper-mcp"


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog=(
        # `\b` stops click reflowing the block under it into one paragraph.
        # The second half is a warning about the bind address, not a
        # continuation of the sentence about environment variables.
        "\b\n"
        "Defaults come from SPEAKER_HELPER_MCP_HOST and SPEAKER_HELPER_MCP_PORT\n"
        "when those are set.\n"
        "The host defaults to 127.0.0.1: pass --host 0.0.0.0 to accept\n"
        "connections from outside this machine."
    ),
)
# `envvar=` rather than a default computed from `os.environ`: an option's
# default is evaluated when this module is imported, so reading the environment
# there would freeze whatever the shell held at import time. click consults the
# variable per invocation, and an explicit flag still wins over it.
@click.option(
    "--host",
    default="127.0.0.1",
    envvar="SPEAKER_HELPER_MCP_HOST",
    show_default=True,
    help="Interface to bind.",
)
@click.option(
    "--port",
    type=int,
    default=8080,
    envvar="SPEAKER_HELPER_MCP_PORT",
    show_default=True,
    help="Port to bind.",
)
@click.option("--config", default=None, help="Settings file to load (default: ./settings.yaml).")
def cli(host: str, port: int, config: str | None) -> int:
    """Serve speaker-helper's MCP tools over HTTP.

    Every tool is a route on the same FastAPI app, with the MCP endpoint
    mounted beside them at /mcp.

    \f

    Everything above the form feed is what ``--help`` prints: click renders
    the whole docstring, so the numpydoc sections below would otherwise land
    in a user's terminal, double backticks and all.

    Parameters
    ----------
    host : str
        Interface to bind; ``SPEAKER_HELPER_MCP_HOST`` when unset.
    port : int
        Port to bind; ``SPEAKER_HELPER_MCP_PORT`` when unset.
    config : str or None
        Settings file to load; ``./settings.yaml`` when unset.

    Returns
    -------
    int
        A process exit code, handed back by :func:`main` rather than raised:
        ``standalone_mode=False`` is what lets this value travel.
    """
    try:
        import uvicorn
    except ImportError:
        click.echo(
            "The MCP surface needs a web server. Install it with:\n"
            "    pip install 'speaker-helper[mcp]'",
            err=True,
        )
        return 2

    from speaker_helper.api import create_app
    from speaker_helper.config import Settings

    app = create_app(Settings.load(config))
    # One worker: the backend loads its model once per process and keeps it.
    # A second worker does not share that model, it pays for its own copy —
    # which for an ONNX graph is several hundred megabytes of silence.
    uvicorn.run(app, host=host, port=port, workers=1)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Serve the API with its MCP endpoint mounted.

    Parameters
    ----------
    argv : list of str or None
        Argument vector without ``argv[0]``; reads ``sys.argv`` when ``None``.

    Returns
    -------
    int
        A process exit code. Non-zero when the extra is missing, with the
        install line rather than a traceback about a module the reader has
        never imported.
    """
    # `standalone_mode=False` is the whole point: it stops click calling
    # `sys.exit` itself, so the exit code comes back here and this function
    # keeps returning an `int`. A console script that raises instead of
    # returning its code is a regression, and `[project.scripts]` points
    # straight at this name.
    try:
        code = cli.main(
            args=argv if argv is not None else sys.argv[1:],
            prog_name=_PROG,
            standalone_mode=False,
        )
    except click.ClickException as exc:
        # A bad flag lands here as a UsageError: show the usage line and give
        # back its exit code (2), which is what argparse did before.
        exc.show()
        return exc.exit_code
    except click.exceptions.Exit as exc:  # -h / --help
        return int(exc.exit_code)
    except SystemExit as exc:  # pragma: no cover - defensive
        return int(exc.code or 0)
    return int(code or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
