"""
Text segmentation for low-latency streaming synthesis.

Module summary
--------------
In streaming mode the time to first audio (TTFA) is dominated by how much text
the engine must synthesise before it can emit anything. Splitting a paragraph
into sentence-sized units lets speaker-helper synthesise and emit the first
unit quickly while later units are still being produced. This module holds the
deterministic, dependency-free splitter used for that.

Usage example
-------------
>>> from speaker_helper.text import split_sentences
>>> split_sentences("Bonjour. Comment ça va ? Bien !")
['Bonjour.', 'Comment ça va ?', 'Bien !']

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import re

# Sentence terminators for the languages speaker-helper targets. We keep the
# terminator attached to the sentence so the engine still hears the prosodic
# cue. French guillemets and typographic punctuation are intentionally NOT
# treated as boundaries — only end-of-sentence marks are.
_SENTENCE_RE = re.compile(r"[^.!?…。！？]+[.!?…。！？]*", re.UNICODE)


def split_sentences(text: str) -> list[str]:
    """Split text into sentence-sized, non-empty, stripped units.

    Parameters
    ----------
    text : str
        Arbitrary text, possibly multi-sentence and multi-line.

    Returns
    -------
    list[str]
        Sentences in order, each stripped of surrounding whitespace, with
        their terminating punctuation preserved. Text without any terminator
        returns a single-element list (the whole stripped input); empty or
        whitespace-only input returns an empty list.

    Examples
    --------
    >>> split_sentences("Un. Deux. Trois.")
    ['Un.', 'Deux.', 'Trois.']
    >>> split_sentences("no terminator here")
    ['no terminator here']
    >>> split_sentences("   ")
    []
    """
    if not text or not text.strip():
        return []
    pieces = [m.group(0).strip() for m in _SENTENCE_RE.finditer(text)]
    sentences = [p for p in pieces if p]
    # A body with no terminator at all yields nothing above; fall back to the
    # whole stripped text so the caller always gets something to synthesise.
    return sentences or [text.strip()]


def chunk_for_streaming(text: str, first_chunk_sentences: int = 1) -> list[str]:
    """Group sentences into synthesis chunks, keeping the first one small.

    Parameters
    ----------
    text : str
        The text to synthesise.
    first_chunk_sentences : int, optional
        How many sentences to place in the first chunk. Keeping this at ``1``
        (the default) minimises TTFA; larger values reduce per-chunk overhead
        at the cost of a slower first emission.

    Returns
    -------
    list[str]
        Chunks of text to synthesise in order. The first chunk holds
        ``first_chunk_sentences`` sentences; every remaining sentence is its
        own chunk so downstream audio keeps flowing steadily.

    Examples
    --------
    >>> chunk_for_streaming("A. B. C.", first_chunk_sentences=1)
    ['A.', 'B.', 'C.']
    >>> chunk_for_streaming("A. B. C.", first_chunk_sentences=2)
    ['A. B.', 'C.']
    """
    sentences = split_sentences(text)
    if not sentences:
        return []
    n = max(1, first_chunk_sentences)
    first = " ".join(sentences[:n])
    return [first, *sentences[n:]]
