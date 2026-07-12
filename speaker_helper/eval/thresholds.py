"""
Versioned pass/fail thresholds for the evaluation gate.

Module summary
--------------
"No vibe checks": an evaluation only gates CI if the bar it must clear is
explicit and committed. :class:`Thresholds` holds that bar, with defaults that
encode speaker-helper's operating point — **synthesis faster than real time**
(RTF below 1) and **zero tolerance for audio anomalies**. Fidelity thresholds
(WER/chrF) apply only when a transcriber supplies a round-trip; left ``None``
they are simply not gated.

The defaults live in code; ``thresholds.yaml`` next to this module mirrors them
so the bar can be reviewed and tuned in one obvious place, and
:meth:`Thresholds.load` reads it.

Usage example
-------------
>>> from speaker_helper.eval.thresholds import Thresholds
>>> Thresholds().max_p95_rtf
1.0

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

DEFAULT_THRESHOLDS_FILE = Path(__file__).parent / "thresholds.yaml"


@dataclass(frozen=True)
class Thresholds:
    """The bar an evaluation run must clear to pass.

    Parameters
    ----------
    max_mean_rtf : float
        Maximum allowed mean real-time factor across cases.
    max_p95_rtf : float
        Maximum allowed 95th-percentile RTF (guards tail latency). ``1.0`` means
        even the slow cases stay faster than real time.
    max_anomaly_rate : float
        Maximum allowed fraction of cases with any audio anomaly (``0.0`` = none
        tolerated).
    max_mean_wer : float or None
        Maximum allowed mean word error rate of the re-transcription round-trip.
        ``None`` disables the gate (used when no transcriber is provided).
    min_mean_chrf : float or None
        Minimum allowed mean chrF of the round-trip. ``None`` disables the gate.
    """

    max_mean_rtf: float = 1.0
    max_p95_rtf: float = 1.0
    max_anomaly_rate: float = 0.0
    max_mean_wer: float | None = None
    min_mean_chrf: float | None = None

    @classmethod
    def load(cls, path: str | Path | None = None) -> Thresholds:
        """Load thresholds from a YAML file, falling back to defaults.

        Parameters
        ----------
        path : str or Path or None
            YAML file with a subset of the threshold fields. When ``None``, the
            bundled ``thresholds.yaml`` is used if present; otherwise the
            dataclass defaults apply. Unknown keys are ignored.

        Returns
        -------
        Thresholds
            The populated thresholds.
        """
        if path is None:
            path = DEFAULT_THRESHOLDS_FILE if DEFAULT_THRESHOLDS_FILE.is_file() else None
        if path is None:
            return cls()
        import yaml

        raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})
