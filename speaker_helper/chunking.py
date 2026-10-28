"""
Long-text chunking: cut a text into synthesis-sized pieces, LLM-assisted.

Module summary
--------------
Every neural TTS engine has a comfort zone, and a long text read in one call
leaves it: Chatterbox audibly degrades past roughly half a minute of speech,
and autoregressive models drift. The fix is old and simple — synthesise
sentence groups and concatenate — and the only interesting question is *where
to cut*. A cut between two sentences of the same thought is audible; a cut at
a paragraph or topic boundary is not.

That placement is what the local LLM contributes here, under one invariant
that makes the feature safe: **the model never touches the text**. Sentences
are split locally (:func:`~speaker_helper.text.split_sentences`,
deterministic); the LLM is only asked *how many consecutive sentences go in
each chunk*, its answer is validated structurally (positive integers, summing
to the sentence count), and anything else — a chatty answer, a wrong sum, no
LLM at all — falls back to a deterministic greedy packer. Chunks always
concatenate back to exactly the sentences the splitter produced.

The model is resolved through ``best-engine-ai-helper`` (the suite rule) and
served by Ollama at temperature 0, like the pronunciation lexicon's
respelling tier (:mod:`speaker_helper.lexicon`).

Usage example
-------------
>>> from speaker_helper.chunking import greedy_group_sizes
>>> greedy_group_sizes(["aa.", "bb.", "cc."], max_chars=7)
[2, 1]

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import json
import re

import os_helper as osh

from speaker_helper.config import Settings
from speaker_helper.text import merge_short_fragments, split_sentences

#: Default per-chunk budget, in characters. ~500 characters is ~30 seconds of
#: speech — inside every backend's comfort zone (Chatterbox degrades past
#: that; Kyutai and Kokoro are comfortable well below it).
DEFAULT_MAX_CHARS: int = 500

#: How much of each sentence the LLM is shown. Grouping needs the shape of
#: the discourse, not every word — and shorter prompts answer faster.
_PREVIEW_CHARS: int = 100


def chunk_long_text(text: str, language: str, settings: Settings) -> list[str]:
    """Cut ``text`` into synthesis-sized chunks at the best boundaries known.

    Short texts pass through untouched (one chunk); long ones are split into
    sentence groups — grouped by the local LLM when available, greedily
    otherwise. Either way the chunks are exactly the local splitter's
    sentences, in order: the LLM chooses boundaries, never words.

    Parameters
    ----------
    text : str
        The text to synthesise (already respelled, when a lexicon applies).
    language : str
        Language of the text — context for the LLM prompt only.
    settings : Settings
        Its ``chunking`` mapping drives this: ``enabled`` (default True),
        ``llm`` (default True), ``max_chars`` (default
        :data:`DEFAULT_MAX_CHARS`).

    Returns
    -------
    list of str
        Chunks in reading order; ``[text]`` when no split is needed (the
        common case, costing one length check).
    """
    cfg = settings.chunking or {}
    max_chars = int(cfg.get("max_chars", DEFAULT_MAX_CHARS))
    # Disabled, or comfortably short: one chunk, zero further work.
    if not bool(cfg.get("enabled", True)) or len(text) <= max_chars:
        return [text]
    sentences = split_sentences(text)
    if len(sentences) <= 1:
        # One giant sentence: there is no boundary to cut at. Hand it over
        # whole — a mid-sentence cut would be worse than a long synthesis.
        return [text]
    # Ask the LLM for boundary placement; fall back to greedy packing on any
    # failure. Both paths return group sizes over the SAME sentence list, so
    # text integrity never depends on which path answered.
    sizes: list[int] | None = None
    if bool(cfg.get("llm", True)):
        sizes = _llm_group_sizes(sentences, language, max_chars)
    if sizes is None:
        sizes = greedy_group_sizes(sentences, max_chars)
    # Materialise the groups back into text chunks. Greedy packing fills each
    # group up to max_chars, so a trailing short sentence can end up alone in
    # the last group (and the LLM may hand back a size-1 group anywhere); fold
    # those into a neighbour for the same reason the streaming path does.
    chunks: list[str] = []
    cursor = 0
    for size in sizes:
        chunks.append(" ".join(sentences[cursor : cursor + size]))
        cursor += size
    chunks = merge_short_fragments(chunks)
    osh.info(
        "chunking: %d chars -> %d chunk(s) of %s sentences",
        len(text),
        len(chunks),
        "/".join(str(s) for s in sizes),
    )
    return chunks


def greedy_group_sizes(sentences: list[str], max_chars: int) -> list[int]:
    """Pack consecutive sentences into groups under ``max_chars`` each.

    The deterministic fallback: no model, no surprise. A single sentence
    longer than the budget forms its own group — splitting inside a sentence
    is never an option.

    Parameters
    ----------
    sentences : list of str
        The sentences, in order.
    max_chars : int
        Character budget per group.

    Returns
    -------
    list of int
        Group sizes, positive, summing to ``len(sentences)``.

    Examples
    --------
    >>> greedy_group_sizes(["aa.", "bb.", "cc."], max_chars=7)
    [2, 1]
    """
    sizes: list[int] = []
    current_n = 0
    current_chars = 0
    for sentence in sentences:
        # +1 for the joining space; the first sentence of a group pays none.
        cost = len(sentence) + (1 if current_n else 0)
        if current_n and current_chars + cost > max_chars:
            # The running group is full: close it, start a new one here.
            sizes.append(current_n)
            current_n, current_chars = 1, len(sentence)
        else:
            current_n += 1
            current_chars += cost
    if current_n:
        sizes.append(current_n)
    return sizes


def _llm_group_sizes(sentences: list[str], language: str, max_chars: int) -> list[int] | None:
    """Ask the local LLM how many consecutive sentences go in each chunk.

    Parameters
    ----------
    sentences : list of str
        The locally-split sentences, in order.
    language : str
        Language of the text (prompt context).
    max_chars : int
        Character budget per chunk, stated to the model as a soft target.

    Returns
    -------
    list of int or None
        Validated group sizes, or ``None`` when the LLM stack is unavailable
        or its answer fails validation (the caller then packs greedily).
    """
    # Imports stay inside: chunking must work (greedy path) with no LLM stack.
    try:
        import best_engine_ai_helper as be
        import ollama
    except ImportError:
        return None
    try:
        model = be.text_model()
    except Exception as exc:  # noqa: BLE001 - no env file / no detection yet
        osh.warning("chunking: best-engine-ai-helper could not resolve a model (%s)", exc)
        return None
    # The model sees numbered sentence *previews* with their lengths — enough
    # to spot topic boundaries, cheap enough to answer in a couple of seconds.
    listing = "\n".join(
        f"{i + 1}. ({len(s)} chars) {s[:_PREVIEW_CHARS]}" for i, s in enumerate(sentences)
    )
    prompt = (
        f"A text-to-speech system must read {len(sentences)} consecutive "
        f"{language} sentences, synthesising them in chunks of at most about "
        f"{max_chars} characters each. Group CONSECUTIVE sentences into chunks, "
        "cutting at natural discourse boundaries (paragraph or topic changes), "
        "never inside a thought.\n"
        f"{listing}\n"
        "Answer with ONLY a JSON array of the chunk sizes (counts of "
        f"consecutive sentences), e.g. [3, 2, 4]. The sizes must sum to "
        f"{len(sentences)}."
    )
    try:
        reply = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            # Deterministic, and the answer is a short array — anything long
            # is already wrong. Thinking stays off: measured on this stack it
            # consumes the whole budget without concluding.
            options={"temperature": 0.0, "num_predict": 128},
            think=False,
        )
        answer = str(reply["message"]["content"])
    except TypeError:
        # Older ollama clients lack the `think` kwarg; retry without it.
        try:
            reply = ollama.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.0, "num_predict": 128},
            )
            answer = str(reply["message"]["content"])
        except Exception as exc:  # noqa: BLE001 - daemon down, model missing, ...
            osh.warning("chunking: LLM call failed (%s) — packing greedily", exc)
            return None
    except Exception as exc:  # noqa: BLE001 - daemon down, model missing, ...
        osh.warning("chunking: LLM call failed (%s) — packing greedily", exc)
        return None
    return _validate_group_sizes(answer, expected_total=len(sentences))


def _validate_group_sizes(answer: str, *, expected_total: int) -> list[int] | None:
    """Accept an LLM answer only when it is a valid consecutive grouping.

    Parameters
    ----------
    answer : str
        Raw model output; the first JSON array found in it is considered.
    expected_total : int
        The sentence count the sizes must sum to.

    Returns
    -------
    list of int or None
        The sizes when they are all positive integers summing to
        ``expected_total``; ``None`` otherwise (the caller packs greedily).

    Examples
    --------
    >>> _validate_group_sizes("[2, 1]", expected_total=3)
    [2, 1]
    >>> _validate_group_sizes("[2, 2]", expected_total=3) is None
    True
    """
    # Reasoning models may leak a think block; ignore it and take the first
    # JSON array anywhere in what remains.
    cleaned = re.sub(r"(?s)<think>.*?</think>", "", answer)
    match = re.search(r"\[[\d,\s]*\]", cleaned)
    if match is None:
        return None
    try:
        sizes = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    # Structural validation — the invariant that makes the LLM safe to trust:
    # positive integers, summing exactly to the sentence count. Anything else
    # would drop or duplicate text, which no chunking is allowed to do.
    if not isinstance(sizes, list) or not sizes:
        return None
    if not all(isinstance(s, int) and s >= 1 for s in sizes):
        return None
    if sum(sizes) != expected_total:
        return None
    return [int(s) for s in sizes]
