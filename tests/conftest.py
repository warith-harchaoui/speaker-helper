"""
Shared pytest fixtures and helpers for speaker-helper tests.

The ``live_port`` fixture that used to live here probed a REST engine on
:17600 / :17493 and skipped when nothing answered. Both the engine and the
fixture are gone: the default backend runs in this process, so "is the engine
up" is not a question a test can ask a socket. What replaces it is
:func:`needs_kokoro`, which asks the two questions that *can* fail — is the
package installed, and are the weights on disk.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import pytest


@pytest.fixture
def needs_kokoro() -> None:
    """Skip unless Kokoro could really synthesise on this machine.

    Two separate reasons to skip, and the message says which: a missing
    package is a ``pip install`` away, a missing 340 MB of weights is not.
    """
    from speaker_helper.backends.kokoro import model_paths

    try:
        import kokoro_onnx  # noqa: F401
    except ImportError:
        pytest.skip("kokoro-onnx is not installed")
    if model_paths() is None:
        pytest.skip("Kokoro's weights are not on this machine")
