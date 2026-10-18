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

import argparse
import os
import sys


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
    parser = argparse.ArgumentParser(
        prog="speaker-helper-mcp",
        description=(
            "Serve speaker-helper's MCP tools over HTTP. Every tool is a route "
            "on the same FastAPI app, with the MCP endpoint mounted beside "
            "them at /mcp."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Defaults come from SPEAKER_HELPER_MCP_HOST and "
            "SPEAKER_HELPER_MCP_PORT when those are set.\n"
            "The host defaults to 127.0.0.1: pass --host 0.0.0.0 to accept "
            "connections from outside this machine."
        ),
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("SPEAKER_HELPER_MCP_HOST", "127.0.0.1"),
        help="Interface to bind (default: %(default)s).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SPEAKER_HELPER_MCP_PORT", "8080")),
        help="Port to bind (default: %(default)s).",
    )
    parser.add_argument(
        "--config", default=None, help="Settings file to load (default: ./settings.yaml)."
    )
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        sys.stderr.write(
            "The MCP surface needs a web server. Install it with:\n"
            "    pip install 'speaker-helper[mcp]'\n"
        )
        return 2

    from speaker_helper.api import create_app
    from speaker_helper.config import Settings

    app = create_app(Settings.load(args.config))
    # One worker: the backend loads its model once per process and keeps it.
    # A second worker does not share that model, it pays for its own copy —
    # which for an ONNX graph is several hundred megabytes of silence.
    uvicorn.run(app, host=args.host, port=args.port, workers=1)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
