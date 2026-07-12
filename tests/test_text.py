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
    assert split_sentences("Bonjour. Comment ça va ? Bien !") == [
        "Bonjour.", "Comment ça va ?", "Bien !",
    ]


def test_split_no_terminator_returns_whole() -> None:
    """Text without a terminator returns the whole stripped input."""
    assert split_sentences("no terminator here") == ["no terminator here"]


def test_split_empty_is_empty() -> None:
    """Empty or whitespace-only input returns an empty list."""
    assert split_sentences("") == []
    assert split_sentences("   \n  ") == []


def test_chunk_first_chunk_size() -> None:
    """The first streaming chunk holds the requested number of sentences."""
    assert chunk_for_streaming("A. B. C.", first_chunk_sentences=1) == ["A.", "B.", "C."]
    assert chunk_for_streaming("A. B. C.", first_chunk_sentences=2) == ["A. B.", "C."]


def test_chunk_empty() -> None:
    """Empty input yields no chunks."""
    assert chunk_for_streaming("   ") == []
