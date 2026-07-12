"""
Logging surface for speaker-helper.

Module summary
--------------
A single place to obtain a configured :class:`logging.Logger`. Library code
must never call bare :func:`print`; it logs through ``get_logger(__name__)``
so downstream applications control verbosity from one place (a ``LOG_LEVEL``
environment variable, or their own logging configuration).

Usage example
-------------
>>> from speaker_helper.logging_utils import get_logger
>>> log = get_logger(__name__)
>>> log.info("synthesising %d characters", 42)

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import logging
import os

_CONFIGURED: bool = False


def get_logger(name: str) -> logging.Logger:
    """Return a module logger, configuring the root handler once.

    Parameters
    ----------
    name : str
        Logger name, conventionally ``__name__`` of the calling module.

    Returns
    -------
    logging.Logger
        A logger whose effective level follows the ``LOG_LEVEL`` environment
        variable (default ``INFO``). Handlers are attached to the package root
        exactly once so importing the library never duplicates log lines.

    Examples
    --------
    >>> logger = get_logger("speaker_helper.demo")
    >>> logger.name
    'speaker_helper.demo'
    """
    global _CONFIGURED
    if not _CONFIGURED:
        level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
        # Configure only the package root so we never hijack the caller's
        # root logger configuration (they may have their own handlers).
        root = logging.getLogger("speaker_helper")
        if not root.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
            )
            root.addHandler(handler)
        root.setLevel(level)
        _CONFIGURED = True
    return logging.getLogger(name)
