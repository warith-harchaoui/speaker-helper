"""
Shared pytest fixtures and helpers for speaker-helper tests.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import pytest


def voicebox_port() -> int | None:
    """Return the first reachable Voicebox port, or ``None`` if unreachable.

    Returns
    -------
    int or None
        ``17600`` (docker-compose) or ``17493`` (native) if either answers
        ``/health``; otherwise ``None`` so live tests can skip cleanly.
    """
    import httpx

    for port in (17600, 17493):
        try:
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0).raise_for_status()
            return port
        except Exception:
            continue
    return None


@pytest.fixture
def live_port() -> int:
    """Provide a reachable Voicebox port or skip the test."""
    port = voicebox_port()
    if port is None:
        pytest.skip("Voicebox not reachable on :17600 or :17493")
    return port
