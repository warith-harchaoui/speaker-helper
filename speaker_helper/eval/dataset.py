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

# The built-in datasets live next to this module so they are importable from an
# installed wheel, not just a source checkout. One JSON Lines file per language,
# named ``<lang>_reference.jsonl``.
_DATA_DIR = Path(__file__).parent / "data"
DEFAULT_LANGUAGE = "fr"
DEFAULT_DATASET = _DATA_DIR / f"{DEFAULT_LANGUAGE}_reference.jsonl"


def dataset_path_for_language(language: str) -> Path:
    """Return the bundled dataset path for a language code (e.g. ``"en"``)."""
    return _DATA_DIR / f"{language}_reference.jsonl"


def available_languages() -> list[str]:
    """Return the sorted language codes that ship a built-in dataset."""
    return sorted(p.name.split("_", 1)[0] for p in _DATA_DIR.glob("*_reference.jsonl"))


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
        """Default an empty ``reference`` to ``text`` (frozen-safe)."""
        # A missing reference means "score against the input text itself".
        # The dataclass is frozen, so mutate the field via ``object.__setattr__``.
        if not self.reference:
            object.__setattr__(self, "reference", self.text)


def load_dataset(
    path: str | Path | None = None,
    *,
    language: str | None = None,
) -> list[EvalCase]:
    """Load evaluation cases from a JSON Lines file.

    Parameters
    ----------
    path : str or Path or None
        Explicit dataset file. Takes precedence over ``language``.
    language : str or None
        When ``path`` is ``None``, load the bundled ``<language>_reference.jsonl``
        set. When both are ``None``, the default (French) set is loaded.

    Returns
    -------
    list of EvalCase
        The cases in file order.

    Raises
    ------
    FileNotFoundError
        If the resolved dataset does not exist (the error lists the languages
        that do ship a dataset).
    ValueError
        If a line is not valid JSON or lacks the required ``id``/``text`` keys.
    """
    if path is not None:
        path = Path(path)
    elif language is not None:
        path = dataset_path_for_language(language)
        if not path.is_file():
            raise FileNotFoundError(
                f"no built-in dataset for language {language!r}; "
                f"available: {', '.join(available_languages())}"
            )
    else:
        path = DEFAULT_DATASET
    if not path.is_file():
        raise FileNotFoundError(f"eval dataset not found: {path}")
    cases: list[EvalCase] = []
    # Parse JSON Lines: one case per line. ``lineno`` starts at 1 so errors
    # point at the human line number.
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        # Allow blank lines and ``#`` comments for a readable, annotatable file.
        if not line or line.startswith("#"):
            continue
        # Fail loudly with the offending line number rather than a bare traceback.
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        # ``id`` and ``text`` are the only mandatory keys; the rest have defaults.
        if "id" not in obj or "text" not in obj:
            raise ValueError(f"{path}:{lineno}: each case needs 'id' and 'text'")
        cases.append(
            EvalCase(
                id=str(obj["id"]),
                text=str(obj["text"]),
                language=str(obj.get("language", "fr")),
                reference=str(obj.get("reference", "")),
            )
        )
    return cases
