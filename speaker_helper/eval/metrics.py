"""
Dependency-free quality and speed metrics for synthesised speech.

Module summary
--------------
This is speaker-helper's measurement machinery, built around its
:class:`~speaker_helper.types.AudioResult`. It answers two questions for every
utterance — *is it fast?* and *is it good?* — with pure-Python functions that
need no model and no network:

* **Speed.** :func:`percentile` over per-utterance real-time factors (RTF).
* **Signal anomalies.** :func:`detect_anomalies` flags empty audio, aberrant
  duration for the amount of text, clipping, and invalid sample rates — the
  "TTS anomaly rate" gate. It decodes the WAV with ``soundfile`` (imported
  lazily) but computes everything else in the standard library.
* **Fidelity (optional round-trip).** When a transcriber is available the audio
  can be re-transcribed and compared to the reference text with
  :func:`word_error_rate` (WER) and :func:`chrf` (character n-gram F-score).
  Both are implemented here rather than pulled from ``jiwer`` / ``sacrebleu`` so
  the core evaluation has zero heavy dependencies.

Usage example
-------------
>>> from speaker_helper.eval.metrics import word_error_rate, chrf
>>> word_error_rate("le chat dort", "le chat dort")
0.0
>>> round(chrf("bonjour", "bonjour"), 3)
1.0

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import io
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

from speaker_helper.types import AudioResult

# Plausible speaking-rate band (characters of input text per second of audio).
# Human/TTS French speech sits well inside this; audio far outside it for a
# given text is almost certainly a synthesis anomaly (truncation or a runaway
# stretch), independent of any engine. Recalibrate from real runs if needed.
DEFAULT_MIN_CHARS_PER_SEC = 4.0
DEFAULT_MAX_CHARS_PER_SEC = 40.0

# A sample whose absolute value reaches this is treated as clipped.
CLIPPING_THRESHOLD = 0.999


def percentile(values: Sequence[float], p: float) -> float:
    """Return the ``p``-th percentile (0-100) via linear interpolation.

    Parameters
    ----------
    values : sequence of float
        Samples (need not be sorted).
    p : float
        Percentile in ``[0, 100]``.

    Returns
    -------
    float
        The interpolated percentile, or ``0.0`` for an empty input.

    Examples
    --------
    >>> percentile([1, 2, 3, 4], 50)
    2.5
    >>> percentile([], 95)
    0.0
    """
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    rank = (p / 100.0) * (len(s) - 1)
    lo = int(rank)
    frac = rank - lo
    hi = min(lo + 1, len(s) - 1)
    return float(s[lo] + (s[hi] - s[lo]) * frac)


def mean(values: Sequence[float]) -> float:
    """Return the arithmetic mean, or ``0.0`` for an empty input."""
    return (sum(values) / len(values)) if values else 0.0


# ---------------------------------------------------------------------------
# Text normalisation + WER + chrF
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+", re.UNICODE)


def normalize_text(text: str) -> str:
    """Lowercase, strip accents/punctuation, and collapse whitespace.

    A deliberately aggressive normalisation so WER/chrF measure *what was said*,
    not casing, accentuation, or punctuation the TTS/STT pair may drop.

    Parameters
    ----------
    text : str
        Raw text.

    Returns
    -------
    str
        Normalised text (lowercase ASCII words separated by single spaces).

    Examples
    --------
    >>> normalize_text("Où est le Café ?")
    'ou est le cafe'
    """
    # NFKD splits accented characters into a base letter + a combining mark, so
    # dropping the combining marks (below) strips accents while keeping letters.
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    # Punctuation becomes a space (not nothing) so "l'eau" -> "l eau", two tokens.
    no_punct = _PUNCT_RE.sub(" ", stripped)
    # Collapse the runs of spaces the two substitutions above may have produced.
    return _SPACE_RE.sub(" ", no_punct).strip()


def _edit_distance(a: Sequence, b: Sequence) -> int:
    """Levenshtein edit distance between two token sequences (O(len(a)*len(b)))."""
    # Distance to/from an empty sequence is just the other sequence's length.
    if not a:
        return len(b)
    if not b:
        return len(a)
    # Classic two-row dynamic program: ``prev`` is the previous matrix row
    # (distances for the empty prefix of ``a``), rebuilt one row per token of a.
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        # ``cur[0]`` = cost of deleting the first ``i`` tokens of ``a``.
        cur = [i]
        for j, cb in enumerate(b, 1):
            # 0 cost when the tokens match, else 1 (a substitution).
            cost = 0 if ca == cb else 1
            # Cheapest of: insert (prev[j]+1), delete (cur[j-1]+1), sub/keep.
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    # Bottom-right cell: distance between the full sequences.
    return prev[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Word error rate between a reference and a hypothesis transcript.

    Parameters
    ----------
    reference : str
        The ground-truth text (what should have been spoken).
    hypothesis : str
        The transcript of the synthesised audio.

    Returns
    -------
    float
        ``edit_distance(ref_words, hyp_words) / len(ref_words)``. ``0.0`` for an
        exact match; can exceed ``1.0`` when the hypothesis inserts many words.
        Returns ``0.0`` if both are empty and ``1.0`` if only the reference is.

    Examples
    --------
    >>> word_error_rate("le chat dort", "le chien dort")
    0.3333333333333333
    """
    ref = normalize_text(reference).split()
    hyp = normalize_text(hypothesis).split()
    # An empty reference has no words to err on: perfect if the hypothesis is
    # also empty, otherwise treat any spurious output as a full error.
    if not ref:
        return 0.0 if not hyp else 1.0
    # WER = edit distance in *words*, normalised by the reference word count.
    return _edit_distance(ref, hyp) / len(ref)


def _char_ngrams(text: str, n: int) -> Counter:
    """Return a multiset of character ``n``-grams (spaces removed)."""
    # Drop spaces so n-grams span word boundaries (chrF is tokenisation-free).
    s = normalize_text(text).replace(" ", "")
    # A multiset (Counter) of the sliding-window n-grams; empty when too short.
    return Counter(s[i : i + n] for i in range(len(s) - n + 1)) if len(s) >= n else Counter()


def chrf(reference: str, hypothesis: str, *, max_n: int = 6, beta: float = 2.0) -> float:
    """Character n-gram F-score (chrF) between reference and hypothesis.

    A robust, tokenisation-free similarity that credits partial-word overlap —
    well suited to speech round-trips where the transcriber may mis-segment.

    Parameters
    ----------
    reference : str
        Ground-truth text.
    hypothesis : str
        Transcript of the synthesised audio.
    max_n : int
        Highest character n-gram order to average over (1..``max_n``).
    beta : float
        Weight of recall relative to precision (chrF's conventional ``beta=2``).

    Returns
    -------
    float
        Score in ``[0, 1]``; ``1.0`` is identical (after normalisation), ``0.0``
        no shared n-grams. Returns ``1.0`` when both are empty.

    Examples
    --------
    >>> round(chrf("bonjour le monde", "bonjour le monde"), 3)
    1.0
    """
    # Two empty strings are trivially identical; short-circuit before dividing.
    if not normalize_text(reference) and not normalize_text(hypothesis):
        return 1.0
    # Average precision and recall over each n-gram order 1..max_n.
    precisions, recalls = [], []
    for n in range(1, max_n + 1):
        ref_ng, hyp_ng = _char_ngrams(reference, n), _char_ngrams(hypothesis, n)
        # Counter & Counter keeps the min count per shared n-gram (the overlap).
        overlap = sum((ref_ng & hyp_ng).values())
        # max(1, …) guards the division when a side has no n-grams of this order.
        precisions.append(overlap / max(1, sum(hyp_ng.values())))
        recalls.append(overlap / max(1, sum(ref_ng.values())))
    p, r = mean(precisions), mean(recalls)
    # No overlap at any order -> undefined F-score, reported as the worst case.
    if p + r == 0:
        return 0.0
    # F-beta: beta>1 weights recall over precision (chrF convention is beta=2).
    b2 = beta * beta
    return (1 + b2) * p * r / (b2 * p + r)


# ---------------------------------------------------------------------------
# Audio anomaly detection
# ---------------------------------------------------------------------------


def peak_amplitude(wav_bytes: bytes) -> float:
    """Return the peak absolute sample amplitude of a WAV payload (``0.0`` if empty)."""
    import numpy as np
    import soundfile as sf

    data, _ = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=False)
    return float(np.max(np.abs(data))) if len(data) else 0.0


def detect_anomalies(
    result: AudioResult,
    *,
    min_chars_per_sec: float = DEFAULT_MIN_CHARS_PER_SEC,
    max_chars_per_sec: float = DEFAULT_MAX_CHARS_PER_SEC,
    clipping_threshold: float = CLIPPING_THRESHOLD,
) -> list[str]:
    """Return a list of anomaly labels for one synthesised result (empty = clean).

    The checks are engine-agnostic and decidable from the audio alone:

    * ``empty_audio`` — zero or near-zero duration.
    * ``invalid_sample_rate`` — non-positive sample rate.
    * ``duration_too_short`` / ``duration_too_long`` — the characters-per-second
      implied by ``len(text) / duration`` falls outside the plausible band,
      signalling truncation or a runaway stretch.
    * ``clipping`` — a sample reaches full scale.

    Parameters
    ----------
    result : AudioResult
        The synthesised audio and its metadata.
    min_chars_per_sec, max_chars_per_sec : float
        Plausible speaking-rate band (see module constants).
    clipping_threshold : float
        Absolute amplitude at or above which audio is deemed clipped.

    Returns
    -------
    list of str
        Sorted anomaly labels; an empty list means no anomaly was found.
    """
    anomalies: list[str] = []
    if result.duration_s <= 0.05:
        anomalies.append("empty_audio")
        # Rate checks are meaningless without duration; report and return early.
        if result.sample_rate <= 0:
            anomalies.append("invalid_sample_rate")
        return sorted(anomalies)
    if result.sample_rate <= 0:
        anomalies.append("invalid_sample_rate")

    n_chars = len(result.text.strip())
    if n_chars:
        chars_per_sec = n_chars / result.duration_s
        if chars_per_sec > max_chars_per_sec:
            anomalies.append("duration_too_short")
        elif chars_per_sec < min_chars_per_sec:
            anomalies.append("duration_too_long")

    if result.wav_bytes and peak_amplitude(result.wav_bytes) >= clipping_threshold:
        anomalies.append("clipping")

    return sorted(anomalies)
