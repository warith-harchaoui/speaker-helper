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
    text = "Bonjour à tous. Comment allez-vous ? Très bien."
    # A first-chunk size of 1 keeps every sentence separate.
    assert chunk_for_streaming(text, first_chunk_sentences=1) == [
        "Bonjour à tous.",
        "Comment allez-vous ?",
        "Très bien.",
    ]
    # A size of 2 fuses the first two sentences, leaving the rest alone.
    assert chunk_for_streaming(text, first_chunk_sentences=2) == [
        "Bonjour à tous. Comment allez-vous ?",
        "Très bien.",
    ]


def test_short_fragments_are_folded_into_a_neighbour() -> None:
    """A fragment too short to synthesise is grouped, never dropped or padded.

    "Un." is its own sentence, so the splitter hands it over as its own chunk —
    and chatterbox's multilingual model (which serves French here) crashes on
    roughly three tokens, inside upstream's own alignment watchdog. Merging is
    the conservative repair: the words and their order are identical, only the
    breath changes.
    """
    # Folded backwards into the preceding chunk, so TTFA is untouched.
    assert chunk_for_streaming("Bonjour à tous. Un. Et voilà.") == [
        "Bonjour à tous. Un.",
        "Et voilà.",
    ]
    # A short FIRST chunk has no predecessor, so it folds forward instead.
    assert chunk_for_streaming("Un. Bonjour à tous.") == ["Un. Bonjour à tous."]
    # Consecutive fragments accumulate rather than each merging separately.
    assert chunk_for_streaming("A. B. C.") == ["A. B. C."]
    # Nothing is invented: a lone fragment has no neighbour and is returned
    # as-is (the backend then refuses it with a diagnosis).
    assert chunk_for_streaming("Un.") == ["Un."]
    # Words and order survive every merge.
    for text in ("Bonjour à tous. Un. Et voilà.", "Un. Bonjour à tous.", "A. B. C."):
        assert " ".join(chunk_for_streaming(text)).split() == text.split()


def test_chunk_empty() -> None:
    """Empty input yields no chunks."""
    # Whitespace-only input produces nothing to stream.
    assert chunk_for_streaming("   ") == []
