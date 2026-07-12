"""
Evaluation datasets: reference utterances the engine must speak well.

Module summary
--------------
An evaluation is only reproducible if the inputs are versioned alongside the
code. This module defines :class:`EvalCase` (one reference utterance) and loads
JSON Lines datasets — the built-in French set ``data/fr_reference.jsonl`` ships
in the package, and callers may point at their own file.

Each line is a JSON object with ``id``, ``language``, ``text`` and, optionally,
a ``reference`` transcript to score a re-transcription round-trip against
(defaulting to ``text`` itself).

Usage example
-------------
>>> from speaker_helper.eval.dataset import load_dataset
>>> cases = load_dataset()          # the built-in French set
>>> cases[0].language
'fr'

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# The built-in dataset lives next to this module so it is importable from an
# installed wheel, not just a source checkout.
_DATA_DIR = Path(__file__).parent / "data"
DEFAULT_DATASET = _DATA_DIR / "fr_reference.jsonl"


@dataclass(frozen=True)
class EvalCase:
    """One reference utterance to synthesise and score.

    Parameters
    ----------
    id : str
        Stable identifier (used in reports and to diff runs).
    text : str
        The text to synthesise.
    language : str
        ISO-639-1 language code to synthesise in.
    reference : str
        Ground-truth transcript to compare a re-transcription against. Defaults
        to ``text`` when a dataset line omits it.
    """

    id: str
    text: str
    language: str = "fr"
    reference: str = ""

    def __post_init__(self) -> None:
        # A missing reference means "score against the input text itself".
        if not self.reference:
            object.__setattr__(self, "reference", self.text)


def load_dataset(path: str | Path | None = None) -> list[EvalCase]:
    """Load evaluation cases from a JSON Lines file.

    Parameters
    ----------
    path : str or Path or None
        Dataset file. When ``None``, the built-in French set is loaded.

    Returns
    -------
    list of EvalCase
        The cases in file order.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If a line is not valid JSON or lacks the required ``id``/``text`` keys.
    """
    path = Path(path) if path is not None else DEFAULT_DATASET
    if not path.is_file():
        raise FileNotFoundError(f"eval dataset not found: {path}")
    cases: list[EvalCase] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        if "id" not in obj or "text" not in obj:
            raise ValueError(f"{path}:{lineno}: each case needs 'id' and 'text'")
        cases.append(EvalCase(
            id=str(obj["id"]),
            text=str(obj["text"]),
            language=str(obj.get("language", "fr")),
            reference=str(obj.get("reference", "")),
        ))
    return cases
