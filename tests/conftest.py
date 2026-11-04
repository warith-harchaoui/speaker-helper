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

import os

import pytest

#: A timing is only evidence when the machine has cores to spare: above one
#: runnable process per two cores, the engine competes for CPU and the RTF
#: measures the neighbours as much as the engine.
LOADED_FRACTION_OF_CORES: float = 0.5


def skip_timing_if_loaded(measured: str) -> None:
    """Skip a speed assertion the machine cannot honestly answer right now.

    Call it *after* the measurement and right before asserting on speed, so
    every other check in the test has already run. Load is read over the last
    minute, which covers a measurement of a few seconds. The skip message
    carries the load and the core count, so a skipped run says why instead of
    looking like a pass.

    Parameters
    ----------
    measured : str
        What was measured, for the message (e.g. ``"kokoro mean RTF 1.52"``).
    """
    try:
        load_1min = os.getloadavg()[0]
    except OSError:  # pragma: no cover - platform without a load average
        return
    cores = os.cpu_count() or 1
    if load_1min > cores * LOADED_FRACTION_OF_CORES:
        pytest.skip(
            f"machine loaded (1-min load {load_1min:.1f} on {cores} cores): "
            f"{measured} measures the neighbours too; re-run on an idle machine"
        )


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
