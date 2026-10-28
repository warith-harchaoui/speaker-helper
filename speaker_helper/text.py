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
    # Whitespace-only input has no sentences to speak.
    if not text or not text.strip():
        return []
    # Each regex match is a run of text plus its trailing terminator(s); strip
    # surrounding whitespace so chunks glue back together cleanly.
    pieces = [m.group(0).strip() for m in _SENTENCE_RE.finditer(text)]
    # Drop empties left by back-to-back terminators (e.g. "?!").
    sentences = [p for p in pieces if p]
    # A body with no terminator at all yields nothing above; fall back to the
    # whole stripped text so the caller always gets something to synthesise.
    return sentences or [text.strip()]


#: Chunks shorter than this many characters are folded into a neighbour by
#: :func:`merge_short_fragments`.
#:
#: Why a character count, in a module that knows nothing about engines: the
#: chatterbox multilingual tokenizer is a *grapheme* tokenizer, so its token
#: count tracks characters almost exactly — "Un." is 3 of each, "Oui." is 4 of
#: each. That is the boundary measured on 2026-10-28 (chatterbox-tts 0.1.7):
#: below 4 tokens, upstream's `AlignmentStreamAnalyzer` has no alignment window
#: and dies in `step()` with "max(): Expected reduction dim 1 to have non-zero
#: size". "Un." and "A." fail there; "Oui." and "Non." succeed.
#:
#: The value sits exactly on the measured boundary rather than above it, so the
#: merge changes grouping only where synthesis would otherwise break. If a
#: fragment ever slips through, the chatterbox backend still refuses it with a
#: diagnosis, so a miss is loud rather than silent — which is why no safety
#: margin is baked in here.
MIN_CHUNK_CHARS = 4


def merge_short_fragments(chunks: list[str], min_chars: int = MIN_CHUNK_CHARS) -> list[str]:
    """Fold chunks below ``min_chars`` into a neighbour, leaving words untouched.

    A three-character chunk is a poor synthesis unit for any engine — there is
    not enough context for sensible prosody — and for chatterbox's multilingual
    model it is an outright crash (see :data:`MIN_CHUNK_CHARS`). Merging is the
    conservative repair: the words spoken, and their order, are **identical**;
    only the grouping changes, so a short sentence is said in the breath of its
    neighbour instead of alone.

    A fragment merges into the chunk *before* it when there is one, so the
    first chunk stays small and time-to-first-audio is unaffected. A short
    *first* chunk has no predecessor, so it merges forward into the second.

    Parameters
    ----------
    chunks : list of str
        Chunks in reading order.
    min_chars : int, optional
        Length below which a chunk is folded into a neighbour.

    Returns
    -------
    list of str
        Chunks in the same order, with short fragments absorbed. A lone chunk
        is always returned as-is: with no neighbour there is nothing to merge
        into, and inventing words to pad it would change what is spoken.

    Examples
    --------
    >>> merge_short_fragments(["Bonjour.", "Un.", "Et voilà."])
    ['Bonjour. Un.', 'Et voilà.']
    >>> merge_short_fragments(["Un.", "Bonjour tout le monde."])
    ['Un. Bonjour tout le monde.']
    >>> merge_short_fragments(["A.", "B.", "C."])
    ['A. B. C.']
    >>> merge_short_fragments(["Un."])
    ['Un.']
    """
    if not chunks:
        return []
    merged: list[str] = []
    for chunk in chunks:
        # Too short and something precedes it: fold it into that predecessor.
        if merged and len(chunk) < min_chars:
            merged[-1] = f"{merged[-1]} {chunk}"
        else:
            merged.append(chunk)
    # The first chunk has no predecessor to fold into, so it is handled last,
    # forward into its successor — and only when a successor exists.
    if len(merged) > 1 and len(merged[0]) < min_chars:
        merged[1] = f"{merged[0]} {merged[1]}"
        merged.pop(0)
    return merged


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
        own chunk so downstream audio keeps flowing steadily — except that
        fragments too short to synthesise are folded into a neighbour by
        :func:`merge_short_fragments`, which changes grouping only, never the
        words or their order.

    Examples
    --------
    >>> chunk_for_streaming("Bonjour. Ça va ? Très bien.", first_chunk_sentences=1)
    ['Bonjour.', 'Ça va ?', 'Très bien.']
    >>> chunk_for_streaming("Bonjour. Ça va ? Très bien.", first_chunk_sentences=2)
    ['Bonjour. Ça va ?', 'Très bien.']
    >>> chunk_for_streaming("Bonjour. Un. Et voilà.")  # too short to stand alone
    ['Bonjour. Un.', 'Et voilà.']
    """
    sentences = split_sentences(text)
    if not sentences:
        return []
    # Never emit a zero-sentence first chunk, whatever the caller passed.
    n = max(1, first_chunk_sentences)
    # The first chunk bundles ``n`` sentences (its size sets TTFA); every later
    # sentence is its own chunk so audio keeps flowing at a steady cadence.
    first = " ".join(sentences[:n])
    # Sentence-per-chunk is what makes fragments possible in the first place
    # ("Un." is its own sentence), so the merge belongs right here.
    return merge_short_fragments([first, *sentences[n:]])
