"""
Tests for :mod:`speaker_helper.text` — deterministic sentence segmentation.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

from speaker_helper.text import chunk_for_streaming, split_sentences


def test_split_basic_terminators() -> None:
    """Sentences split on . ! ? and keep their terminator."""
    # Three terminators -> three sentences, each retaining its punctuation.
    assert split_sentences("Bonjour. Comment ça va ? Bien !") == [
        "Bonjour.",
        "Comment ça va ?",
        "Bien !",
    ]


def test_split_no_terminator_returns_whole() -> None:
    """Text without a terminator returns the whole stripped input."""
    # No sentence boundary -> the entire input is a single segment.
    assert split_sentences("no terminator here") == ["no terminator here"]


def test_split_empty_is_empty() -> None:
    """Empty or whitespace-only input returns an empty list."""
    # Both the empty string and pure whitespace collapse to no sentences.
    assert split_sentences("") == []
    assert split_sentences("   \n  ") == []


def test_chunk_first_chunk_size() -> None:
    """The first streaming chunk holds the requested number of sentences."""
    # A first-chunk size of 1 keeps every sentence separate.
    assert chunk_for_streaming("A. B. C.", first_chunk_sentences=1) == ["A.", "B.", "C."]
    # A size of 2 fuses the first two sentences, leaving the rest alone.
    assert chunk_for_streaming("A. B. C.", first_chunk_sentences=2) == ["A. B.", "C."]


def test_chunk_empty() -> None:
    """Empty input yields no chunks."""
    # Whitespace-only input produces nothing to stream.
    assert chunk_for_streaming("   ") == []
