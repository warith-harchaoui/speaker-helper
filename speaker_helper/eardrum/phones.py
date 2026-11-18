"""
Phones: cutting IPA into units, and how far apart two of them sound.

Module summary
--------------
The Ralph Eardrum Loop compares what an engine *said* with what it *should
have said*, both as IPA. A plain string comparison would be useless: the
phoneme recogniser writes ``s a i n m a n`` where Wiktionary writes
``ˈfaɪnmən``, and those are the same name said by a French voice. This module
makes the comparison meaningful:

* :func:`tokenize` cuts IPA into phones, dropping what carries no segment
  (stress marks, length, syllable dots, ties, slashes);
* :func:`phone_distance` says how different two phones sound, from a small
  articulatory feature table (height / backness / rounding / nasality for
  vowels; place / manner / voicing for consonants), so /e/ against /ɛ/ costs
  little and /e/ against /k/ costs everything;
* :func:`align` runs a weighted edit distance and keeps the alignment;
* :func:`word_distance` finds the target word inside a whole carrier sentence
  ("Je vous parle de *Feynman* aujourd'hui.") and scores only that region, so
  the recogniser's noise on the surrounding words does not count against it.

Pure Python, no model, no network: everything here is unit-testable.

Usage example
-------------
>>> tokenize("ˈfaɪn.mən")
['f', 'a', 'ɪ', 'n', 'm', 'ə', 'n']
>>> round(phone_distance("e", "ɛ"), 2)
0.2
>>> word_distance("ʒ v u p a l d ə f a j n m a n".split(),
...     "ʒvupaʁldə", ["faɪnmən"], "").score
0.1

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

#: Marks that carry no segment of their own: primary / secondary stress,
#: length, half-length, syllable dot, linking and tie bars, word separators,
#: transcription brackets, and the hyphens Wiktionary uses between syllables.
_IGNORED = set("ˈˌːˑ.‿͜͡-/[]()|‖ ,;'’") | {"̩", "̯", "͡", "͜"}

#: Combining diacritics that change the phone (nasal vowel: ɑ̃ is not ɑ).
#: Every other combining mark is dropped: the recogniser does not produce them
#: and a reference that has them should not be penalised for it.
_KEPT_DIACRITICS = {"̃"}  # combining tilde

#: Spellings of the same phone that different sources disagree on.
_ALIASES: dict[str, str] = {
    "g": "ɡ",  # ASCII g against IPA script g
    "ɚ": "ə",  # rhotacised schwa → schwa (the r-colour is a separate phone)
    "ɝ": "ɜ",
    "ᵻ": "ɨ",
    "ɫ": "l",  # dark l
    "r": "r",
    "ɑ̃": "ɑ̃",
}

#: Vowels → (height 0 close … 6 open, backness 0 front / 1 central / 2 back,
#: rounded 0/1). Nasality is read from the combining tilde, not stored here.
_VOWELS: dict[str, tuple[int, int, int]] = {
    "i": (0, 0, 0), "y": (0, 0, 1), "ɨ": (0, 1, 0), "ʉ": (0, 1, 1),
    "ɯ": (0, 2, 0), "u": (0, 2, 1),
    "ɪ": (1, 0, 0), "ʏ": (1, 0, 1), "ʊ": (1, 2, 1),
    "e": (2, 0, 0), "ø": (2, 0, 1), "ɘ": (2, 1, 0), "ɵ": (2, 1, 1),
    "ɤ": (2, 2, 0), "o": (2, 2, 1),
    "ə": (3, 1, 0),
    "ɛ": (4, 0, 0), "œ": (4, 0, 1), "ɜ": (4, 1, 0), "ɞ": (4, 1, 1),
    "ʌ": (4, 2, 0), "ɔ": (4, 2, 1),
    "æ": (5, 0, 0), "ɐ": (5, 1, 0),
    "a": (6, 0, 0), "ɶ": (6, 0, 1), "ɑ": (6, 2, 0), "ɒ": (6, 2, 1),
}  # fmt: skip

#: Consonants → (place 0 bilabial … 8 glottal, manner, voiced 0/1). Manner:
#: 0 stop, 1 nasal, 2 fricative, 3 approximant, 4 trill / tap, 5 lateral,
#: 6 affricate-like (only for the rare single-symbol affricates).
_CONSONANTS: dict[str, tuple[int, int, int]] = {
    "p": (0, 0, 0), "b": (0, 0, 1), "m": (0, 1, 1), "ɸ": (0, 2, 0), "β": (0, 2, 1),
    "f": (1, 2, 0), "v": (1, 2, 1), "ɱ": (1, 1, 1), "ʋ": (1, 3, 1),
    "θ": (2, 2, 0), "ð": (2, 2, 1),
    "t": (3, 0, 0), "d": (3, 0, 1), "n": (3, 1, 1), "s": (3, 2, 0), "z": (3, 2, 1),
    "ɹ": (3, 3, 1), "r": (3, 4, 1), "ɾ": (3, 4, 1), "l": (3, 5, 1),
    "ʃ": (4, 2, 0), "ʒ": (4, 2, 1), "ɻ": (4, 3, 1),
    "ʈ": (4, 0, 0), "ɖ": (4, 0, 1), "ɳ": (4, 1, 1),
    "c": (5, 0, 0), "ɟ": (5, 0, 1), "ɲ": (5, 1, 1), "ç": (5, 2, 0), "ʝ": (5, 2, 1),
    "j": (5, 3, 1), "ɥ": (5, 3, 1), "ʎ": (5, 5, 1),
    "k": (6, 0, 0), "ɡ": (6, 0, 1), "ŋ": (6, 1, 1), "x": (6, 2, 0), "ɣ": (6, 2, 1),
    "w": (6, 3, 1), "ʍ": (6, 3, 0), "ɰ": (6, 3, 1),
    "q": (7, 0, 0), "ɢ": (7, 0, 1), "ɴ": (7, 1, 1), "χ": (7, 2, 0), "ʁ": (7, 2, 1),
    "ʀ": (7, 4, 1),
    "ħ": (8, 2, 0), "ʕ": (8, 2, 1), "h": (8, 2, 0), "ɦ": (8, 2, 1), "ʔ": (8, 0, 0),
}  # fmt: skip

#: Every r there is. Languages disagree on which one is "the" r, and so do
#: the references: Wiktionary writes /ʁ/ for French where espeak writes /ʁ/
#: and the recogniser often hears /r/. Hearing one for another is not an
#: error worth correcting by respelling.
_RHOTICS = {"r", "ɾ", "ʁ", "ɹ", "ʀ", "ɻ", "χ"}

#: Glides and the vowel each is a short version of: /j/~/i/, /w/~/u/,
#: /ɥ/~/y/. "Faïnemane" heard as ``f a j n`` or ``f a i n`` is the same.
_GLIDE_VOWEL = {("j", "i"), ("w", "u"), ("ɥ", "y"), ("j", "ɪ"), ("w", "ʊ")}

#: Phones a speaker drops or adds without anyone hearing a mispronunciation:
#: the French mute e, the glottal stop, and /h/ (silent in French). Inserting
#: or deleting one costs half a phone instead of a whole one.
_WEAK = {"ə", "ʔ", "h"}

#: Cost of inserting or deleting an ordinary phone.
INDEL_COST = 1.0


def _canonical(phone: str) -> str:
    """Bring one phone to the spelling this module's tables use.

    Parameters
    ----------
    phone : str
        A phone as :func:`tokenize` cut it (base letter plus kept diacritics).

    Returns
    -------
    str
        The aliased spelling (``"g"`` → ``"ɡ"``), or ``phone`` unchanged.

    Examples
    --------
    >>> _canonical("g")
    'ɡ'
    """
    return _ALIASES.get(phone, phone)


def tokenize(ipa: str) -> list[str]:
    """Cut an IPA string into phones.

    A phone is one base letter plus the combining marks that change it (only
    the nasal tilde is kept). Everything that is not a segment — stress,
    length, syllable boundaries, ties, slashes, spaces — is dropped, so
    ``/ˈfaɪn.mən/`` and ``f a ɪ n m ə n`` tokenise identically. Diphthongs and
    affricates come out as their two halves, on both sides of a comparison
    alike.

    Parameters
    ----------
    ipa : str
        Any IPA transcription: Wiktionary's, espeak-ng's, the recogniser's.

    Returns
    -------
    list of str
        The phones, in order.

    Examples
    --------
    >>> tokenize("/ɑ̃.ʁi/")
    ['ɑ̃', 'ʁ', 'i']
    >>> tokenize("t͡ʃ")
    ['t', 'ʃ']
    """
    # NFD splits precomposed letters (ã) into base + combining mark, so the
    # mark can be judged on its own like every other one.
    text = unicodedata.normalize("NFD", ipa or "")
    phones: list[str] = []
    for char in text:
        if char in _IGNORED or char.isspace():
            continue
        if unicodedata.combining(char):
            # A combining mark modifies the previous phone; keep it only when
            # it changes the phone (nasality), otherwise drop it.
            if char in _KEPT_DIACRITICS and phones:
                phones[-1] += char
            continue
        if unicodedata.category(char).startswith(("P", "S", "N", "Lm")):
            # Punctuation and symbols that slipped through (quotes, ellipses),
            # the recogniser's tone digits (``onɡ5``), and modifier letters —
            # aspiration ʰ, palatalisation ʲ, labialisation ʷ — which refine
            # a phone without making it another one.
            continue
        phones.append(char)
    return [_canonical(unicodedata.normalize("NFC", p)) for p in phones]


def _split_nasal(phone: str) -> tuple[str, bool]:
    """Separate a phone from its nasal tilde.

    Parameters
    ----------
    phone : str
        A tokenised phone.

    Returns
    -------
    tuple of (str, bool)
        The base letter and whether it was nasalised.

    Examples
    --------
    >>> _split_nasal("ɑ̃")
    ('ɑ', True)
    """
    decomposed = unicodedata.normalize("NFD", phone)
    return decomposed.replace("̃", ""), "̃" in decomposed


def phone_distance(a: str, b: str) -> float:
    """How different two phones sound, from 0 (same) to 1 (unrelated).

    Parameters
    ----------
    a, b : str
        Two tokenised phones.

    Returns
    -------
    float
        ``0.0`` for the same phone; a small value for neighbours (/e/–/ɛ/,
        /t/–/d/, any two r's); ``1.0`` for a vowel against a consonant or for
        a symbol the tables do not know that differs from the other.

    Examples
    --------
    >>> phone_distance("a", "a")
    0.0
    >>> round(phone_distance("t", "d"), 2)
    0.2
    >>> phone_distance("ʁ", "r")
    0.1
    >>> phone_distance("a", "k")
    1.0
    """
    if a == b:
        return 0.0
    if a in _RHOTICS and b in _RHOTICS:
        return 0.1
    if (a, b) in _GLIDE_VOWEL or (b, a) in _GLIDE_VOWEL:
        return 0.25
    base_a, nasal_a = _split_nasal(a)
    base_b, nasal_b = _split_nasal(b)
    if base_a in _VOWELS and base_b in _VOWELS:
        ha, ba, ra = _VOWELS[base_a]
        hb, bb, rb = _VOWELS[base_b]
        # Height counts per step (there are seven), backness and rounding
        # weigh a little more per step, nasality the most: "ban" against "bas"
        # is a different word in French, "bas" against "bât" barely is.
        cost = (
            0.1 * abs(ha - hb)
            + 0.15 * abs(ba - bb)
            + 0.15 * abs(ra - rb)
            + 0.35 * (nasal_a != nasal_b)
        )
        return min(0.9, cost)
    if base_a in _CONSONANTS and base_b in _CONSONANTS:
        pa, ma, va = _CONSONANTS[base_a]
        pb, mb, vb = _CONSONANTS[base_b]
        # Manner dominates (a stop for a fricative is a different sound),
        # place counts per step, voicing is the classic near-miss.
        cost = 0.08 * abs(pa - pb) + 0.4 * (ma != mb) + 0.2 * (va != vb)
        return min(0.9, cost)
    return 1.0


def indel_cost(phone: str) -> float:
    """Cost of inserting or deleting ``phone``.

    Parameters
    ----------
    phone : str
        A tokenised phone.

    Returns
    -------
    float
        Half a phone for a mute e, a glottal stop or /h/; one phone otherwise.

    Examples
    --------
    >>> indel_cost("ə"), indel_cost("k")
    (0.5, 1.0)
    """
    return 0.5 if phone in _WEAK else INDEL_COST


@dataclass
class Alignment:
    """A weighted edit-distance alignment between two phone sequences.

    Attributes
    ----------
    cost : float
        Total cost of the alignment.
    pairs : list of tuple
        ``(i, j, cost)`` per operation, in order: ``i`` indexes the heard
        sequence and ``j`` the target one; ``None`` on one side marks an
        insertion (``j is None``) or a deletion (``i is None``).
    """

    cost: float
    pairs: list[tuple[int | None, int | None, float]] = field(default_factory=list)


def align(heard: list[str], target: list[str]) -> Alignment:
    """Align what was heard with what was meant, at the lowest cost.

    Classic Needleman-Wunsch with :func:`phone_distance` as the substitution
    cost and :func:`indel_cost` for gaps.

    Parameters
    ----------
    heard : list of str
        Phones the recogniser produced.
    target : list of str
        Phones that should have been said.

    Returns
    -------
    Alignment
        The total cost and the operations that achieve it.

    Examples
    --------
    >>> align(["a", "b"], ["a", "p"]).cost
    0.2
    """
    n, m = len(heard), len(target)
    # dp[i][j]: cheapest way to turn heard[:i] into target[:j].
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + indel_cost(heard[i - 1])
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + indel_cost(target[j - 1])
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = min(
                dp[i - 1][j - 1] + phone_distance(heard[i - 1], target[j - 1]),
                dp[i - 1][j] + indel_cost(heard[i - 1]),
                dp[i][j - 1] + indel_cost(target[j - 1]),
            )
    # Walk back from the corner to recover which operation produced each cell.
    pairs: list[tuple[int | None, int | None, float]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            sub = phone_distance(heard[i - 1], target[j - 1])
            if abs(dp[i][j] - (dp[i - 1][j - 1] + sub)) < 1e-9:
                pairs.append((i - 1, j - 1, sub))
                i, j = i - 1, j - 1
                continue
        if i > 0 and abs(dp[i][j] - (dp[i - 1][j] + indel_cost(heard[i - 1]))) < 1e-9:
            pairs.append((i - 1, None, indel_cost(heard[i - 1])))
            i -= 1
            continue
        pairs.append((None, j - 1, indel_cost(target[j - 1])))
        j -= 1
    pairs.reverse()
    return Alignment(cost=round(dp[n][m], 6), pairs=pairs)


@dataclass
class WordScore:
    """How close a word, heard inside a carrier sentence, is to its target.

    Attributes
    ----------
    score : float
        Alignment cost on the word's region divided by the target word's
        length: ``0`` is a perfect match, ``≥ 1`` means nothing in common.
    heard : list of str
        The phones the recogniser produced for the word's region.
    heard_indices : list of int
        Their indices in the heard sequence (to cut the audio clip).
    target : list of str
        The target variant this score was measured against.
    """

    score: float
    heard: list[str]
    heard_indices: list[int]
    target: list[str]


def word_distance(
    heard: list[str],
    prefix_ipa: str,
    target_variants: list[str],
    suffix_ipa: str,
) -> WordScore:
    """Score one word heard inside a carrier sentence.

    The whole sentence is aligned (prefix + word + suffix), because the
    recogniser has no idea where the word starts; only the operations that
    touch the word's region are then counted. When the target has several
    accepted pronunciations (Wiktionary often lists two), the best one wins.

    Parameters
    ----------
    heard : list of str
        Phones recognised for the whole carrier sentence.
    prefix_ipa, suffix_ipa : str
        IPA of the carrier around the word (from espeak-ng).
    target_variants : list of str
        Accepted IPA transcriptions of the word itself.

    Returns
    -------
    WordScore
        The best variant's score and the phones heard in the word's region.

    Raises
    ------
    ValueError
        When ``target_variants`` is empty.
    """
    if not target_variants:
        raise ValueError("word_distance needs at least one target pronunciation")
    prefix, suffix = tokenize(prefix_ipa), tokenize(suffix_ipa)
    best: WordScore | None = None
    for variant in target_variants:
        word = tokenize(variant)
        if not word:
            continue
        sequence = prefix + word + suffix
        start, end = len(prefix), len(prefix) + len(word)
        alignment = align(heard, sequence)
        region_cost = 0.0
        region_heard: list[int] = []
        inside = False
        for i, j, cost in alignment.pairs:
            if j is not None:
                inside = start <= j < end
            # An insertion belongs to the region it sits in: after the
            # word's first phone and before its last one.
            if inside or (j is None and _between(alignment.pairs, i, start, end)):
                region_cost += cost
                if i is not None:
                    region_heard.append(i)
        score = WordScore(
            score=round(region_cost / len(word), 4),
            heard=[heard[i] for i in region_heard],
            heard_indices=region_heard,
            target=word,
        )
        if best is None or score.score < best.score:
            best = score
    if best is None:
        raise ValueError("every target pronunciation was empty after tokenisation")
    return best


def _between(
    pairs: list[tuple[int | None, int | None, float]], i: int | None, start: int, end: int
) -> bool:
    """Whether the insertion of heard phone ``i`` falls inside ``[start, end)``.

    Parameters
    ----------
    pairs : list of tuple
        The alignment's operations.
    i : int or None
        Heard index of the insertion being placed.
    start, end : int
        The target region, as indices into the target sequence.

    Returns
    -------
    bool
        ``True`` when the nearest target positions on both sides of the
        insertion are inside the region (an insertion at the edge is
        attributed to the carrier, not the word).
    """
    position = next(k for k, p in enumerate(pairs) if p[0] == i and p[1] is None)
    before = next((p[1] for p in reversed(pairs[:position]) if p[1] is not None), None)
    after = next((p[1] for p in pairs[position + 1 :] if p[1] is not None), None)
    return before is not None and after is not None and start <= before and after < end


def sentence_distances(heard: list[str], word_ipas: list[str]) -> list[float]:
    """Score every word of a sentence in one alignment.

    The listen-all pass hears a whole sentence and needs to know which of its
    words came out far from espeak's reading: the sentence is aligned once
    against the concatenated words, and each word is scored on its own
    region, like :func:`word_distance` does for a single word.

    Parameters
    ----------
    heard : list of str
        Phones recognised for the sentence.
    word_ipas : list of str
        Expected IPA of each word, in order.

    Returns
    -------
    list of float
        One score per word (``0.0`` for a word with no phones, such as a
        stray punctuation token).

    Examples
    --------
    >>> sentence_distances("b ɔ̃ ʒ u ʁ".split(), ["bɔ̃", "ʒuʁ"])
    [0.0, 0.0]
    """
    words = [tokenize(ipa) for ipa in word_ipas]
    sequence: list[str] = []
    owner: list[int] = []
    for k, phones in enumerate(words):
        sequence += phones
        owner += [k] * len(phones)
    costs = [0.0] * len(words)
    if not sequence:
        return costs
    current = owner[0]
    for _i, j, cost in align(heard, sequence).pairs:
        if j is not None:
            current = owner[j]
        # Insertions go to the word the last target phone belonged to.
        costs[current] += cost
    return [round(c / len(w), 4) if w else 0.0 for c, w in zip(costs, words, strict=True)]


def describe_differences(heard: list[str], target: list[str]) -> list[str]:
    """What went wrong, phone by phone, in words a language model can act on.

    A distance says *how far*; a respelling is fixed by knowing *what*: a
    sound said instead of another, a sound too many, a sound missing.

    Parameters
    ----------
    heard : list of str
        Phones heard for the word.
    target : list of str
        Phones it should have had.

    Returns
    -------
    list of str
        One short sentence per difference, in reading order; empty when the
        two match.

    Examples
    --------
    >>> describe_differences(["n", "i", "t", "ʃ", "ɛ", "ʁ"], ["n", "i", "t", "ʃ", "ə"])
    ['/ɛ/ said where /ə/ was wanted', 'extra /ʁ/ at the end']
    """
    notes: list[str] = []
    pairs = align(heard, target).pairs
    for k, (i, j, cost) in enumerate(pairs):
        if cost < 0.15:
            # Near-identical phones (two r's, /e/ for /ɛ/) are not worth a
            # respelling change, and listing them drowns the real problem.
            continue
        if i is not None and j is not None:
            notes.append(f"/{heard[i]}/ said where /{target[j]}/ was wanted")
        elif j is None:
            where = "at the end" if all(p[1] is None for p in pairs[k:]) else "inside"
            if all(p[1] is None for p in pairs[:k]):
                where = "at the start"
            notes.append(f"extra /{heard[i]}/ {where}")  # type: ignore[index]
        else:
            notes.append(f"missing /{target[j]}/")
    return notes
