"""
Pronunciation lexicon: per-word overrides applied before synthesis.

Module summary
--------------
Some words a document contains are not words the engine's own
grapheme-to-phoneme stage gets right: proper nouns ("Grasse" the town, not
"grasse" the adjective), acronyms ("ONU"), anglicisms in French text, product
names. This module lets whoever owns the text state, once, how such a word is
pronounced — and applies that statement automatically on every synthesis.

The statement can take two forms, because the engines take two forms:

* **IPA** (``ipa:``) — exact phonemes. Deterministic, but only an engine with
  a phoneme input can honour it. The ``kokoro`` backend does: it already
  phonemises text itself (espeak-ng → IPA) and hands the model phonemes, so a
  lexicon entry is spliced into that stream verbatim
  (see :func:`phonemise_with_lexicon`).
* **Respelling** (``respelling:``) — an orthographic rewrite ("GitHub" →
  "guite-heube") that an engine *without* phoneme access reads correctly.
  Fragile by nature but universal: it works by rewriting the text itself, so
  Chatterbox, Kyutai, and any future end-to-end model benefit.

When an entry states neither, the respelling is **derived once by a local
LLM** — resolved through ``best-engine-ai-helper`` (the suite rule: no
hardcoded model names) and served by Ollama at temperature 0 — then persisted
to a sidecar cache next to the lexicon file. After that first derivation the
whole feature is deterministic and fully offline.

Who applies which tier is decided by the backend's ``LEXICON_TIER`` class
attribute: ``"ipa"`` means "the backend splices phonemes itself, leave the
text alone"; anything else (the default) means
:class:`~speaker_helper.speaker.Speaker` rewrites the text with
:meth:`Lexicon.respell` before calling the engine.

Usage example
-------------
>>> lex = Lexicon.from_mapping({"entries": [
...     {"word": "GitHub", "language": "*", "respelling": "guite-heube"},
... ]})
>>> lex.respell("Va sur GitHub ce soir.", "fr")
'Va sur guite-heube ce soir.'

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import os_helper as osh
import yaml

from speaker_helper.config import Settings

#: The wildcard language: an entry carrying it applies to every language.
#: Useful for brand names that are mangled the same way everywhere.
ANY_LANGUAGE = "*"

#: Sidecar suffix for LLM-derived respellings. A separate file (not a rewrite
#: of the user's lexicon) because the lexicon is hand-edited and commented —
#: regenerating it through a YAML dumper would destroy those comments.
CACHE_SUFFIX = ".llm-cache.yaml"

#: ISO-639-1 → the language name the LLM prompt speaks about. Only languages
#: this package routinely synthesises; anything else falls back to the code
#: itself, which modern instruct models resolve fine.
_LANGUAGE_NAMES: dict[str, str] = {
    "fr": "French",
    "en": "English",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "de": "German",
}


@dataclass
class LexiconEntry:
    """One pronunciation override: a word and how to say it.

    Parameters
    ----------
    word : str
        The written form to match (matched case-insensitively, on word
        boundaries).
    language : str
        ISO-639-1 code the entry applies to, or ``"*"`` for every language.
    ipa : str
        IPA phonemes for the word (no surrounding slashes). Honoured verbatim
        by phoneme-input backends; used as a hint when deriving a respelling.
    respelling : str
        Orthographic rewrite for engines without phoneme access. Empty means
        "derive one with the local LLM on first use".
    source : str
        ``"user"`` for hand-written entries, ``"llm"`` for a derived
        respelling — kept so a cached derivation is distinguishable from a
        human decision.
    """

    word: str
    language: str = ANY_LANGUAGE
    ipa: str = ""
    respelling: str = ""
    source: str = "user"


def _language_key(code: str) -> str:
    """Normalise a language code to the lexicon's key space.

    Parameters
    ----------
    code : str
        Anything a caller says: ``"fr"``, ``"fr-FR"``, ``"*"``, ``""``.

    Returns
    -------
    str
        The bare ISO-639-1 code (``"fr"``), or ``"*"``.

    Examples
    --------
    >>> _language_key("fr-FR")
    'fr'
    >>> _language_key("*")
    '*'
    """
    raw = (code or "").strip().lower()
    if raw in ("", ANY_LANGUAGE):
        return ANY_LANGUAGE
    # Engines spell languages as "fr-fr"; the lexicon keys on the bare code so
    # one entry covers every regional variant.
    return raw.split("-")[0]


class Lexicon:
    """A set of pronunciation overrides, applied by word-boundary matching.

    Parameters
    ----------
    entries : list of LexiconEntry
        The overrides, in file order (later entries win on duplicate words).
    path : Path or None
        Where the lexicon was loaded from — used to place the LLM sidecar
        cache. ``None`` keeps everything in memory (tests, ad-hoc use).
    llm_enabled : bool
        Allow deriving missing respellings with the local LLM. Off means a
        word without a respelling is simply left as written.
    """

    def __init__(
        self,
        entries: list[LexiconEntry],
        *,
        path: Path | None = None,
        llm_enabled: bool = True,
    ) -> None:
        self.path = path
        self.llm_enabled = llm_enabled
        # Entries are indexed by (language, casefolded word): the exact
        # language bucket is consulted first, the "*" bucket second, so a
        # French-specific entry beats a global one for the same word.
        self._by_lang: dict[str, dict[str, LexiconEntry]] = {}
        for entry in entries:
            lang = _language_key(entry.language)
            self._by_lang.setdefault(lang, {})[entry.word.casefold()] = entry
        # Compiled word-matching patterns, one per requested language —
        # built lazily because most texts only ever ask for one language.
        self._patterns: dict[str, re.Pattern[str] | None] = {}
        # Words the LLM was asked about and could not answer, so a broken
        # Ollama setup logs one warning per word instead of one per sentence.
        self._llm_failed: set[str] = set()

    # ----- construction -----------------------------------------------------

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any], *, path: Path | None = None) -> Lexicon:
        """Build a lexicon from a plain mapping (the YAML document shape).

        Parameters
        ----------
        mapping : dict
            ``{"entries": [{word, language, ipa, respelling}, ...],
            "llm": bool}`` — unknown keys are ignored.
        path : Path or None
            Origin file, forwarded for sidecar-cache placement.

        Returns
        -------
        Lexicon
            The populated lexicon.
        """
        entries: list[LexiconEntry] = []
        for raw in mapping.get("entries") or []:
            # Tolerate sparse rows: only `word` is mandatory; everything else
            # has a sensible default. A row without a word is meaningless and
            # dropped with a warning rather than crashing the whole file.
            word = str(raw.get("word") or "").strip()
            if not word:
                osh.warning("lexicon: skipping an entry with no `word`: %r", raw)
                continue
            entries.append(
                LexiconEntry(
                    word=word,
                    language=str(raw.get("language") or ANY_LANGUAGE),
                    ipa=str(raw.get("ipa") or "").strip().strip("/"),
                    respelling=str(raw.get("respelling") or "").strip(),
                    source=str(raw.get("source") or "user"),
                )
            )
        # The file may disable LLM derivation for itself ("llm: false"),
        # e.g. a lexicon shipped to a machine with no Ollama.
        llm_enabled = bool(mapping.get("llm", True))
        lexicon = cls(entries, path=path, llm_enabled=llm_enabled)
        # Fold previously derived respellings back in, so the LLM runs at most
        # once per word across every process that ever used this lexicon.
        lexicon._load_cache()
        return lexicon

    @classmethod
    def load(cls, path: str | Path) -> Lexicon:
        """Load a lexicon from a YAML file.

        Parameters
        ----------
        path : str or Path
            The lexicon file (see ``lexicon.yaml.example`` at the repo root).

        Returns
        -------
        Lexicon
            The populated lexicon.

        Raises
        ------
        FileNotFoundError
            When ``path`` does not exist — a configured-but-missing lexicon is
            a mistake worth hearing about, unlike an unconfigured one.
        """
        file = Path(path)
        text = file.read_text(encoding="utf-8")
        return cls.from_mapping(yaml.safe_load(text) or {}, path=file)

    # ----- lookups ----------------------------------------------------------

    def entry_for(self, word: str, language: str) -> LexiconEntry | None:
        """Return the entry matching ``word`` in ``language``, if any.

        Parameters
        ----------
        word : str
            The written form as found in the text (any casing).
        language : str
            Language of the surrounding text.

        Returns
        -------
        LexiconEntry or None
            The exact-language entry when one exists, else the ``"*"`` entry,
            else ``None``.
        """
        key = word.casefold()
        lang = _language_key(language)
        # Exact language first: a French-specific pronunciation of a word must
        # beat the catch-all one.
        entry = self._by_lang.get(lang, {}).get(key)
        if entry is None and lang != ANY_LANGUAGE:
            entry = self._by_lang.get(ANY_LANGUAGE, {}).get(key)
        return entry

    def _pattern_for(self, language: str) -> re.Pattern[str] | None:
        """The compiled word-boundary pattern for ``language`` (cached).

        Returns ``None`` when no entry applies to the language, so callers can
        take the fast path (no regex pass at all) on lexicon-free languages.
        """
        lang = _language_key(language)
        if lang in self._patterns:
            return self._patterns[lang]
        # The language's own words plus the wildcard bucket, longest first so
        # "Jean-Pierre" wins over "Jean" when both are entries.
        words = set(self._by_lang.get(lang, {})) | set(self._by_lang.get(ANY_LANGUAGE, {}))
        if not words:
            self._patterns[lang] = None
            return None
        alternation = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
        # Lookarounds rather than \b: they behave identically on plain words
        # but keep working when an entry starts or ends with a non-word
        # character (an apostrophe, a digit, a plus sign).
        pattern = re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.IGNORECASE)
        self._patterns[lang] = pattern
        return pattern

    def split(self, text: str, language: str) -> list[tuple[str, LexiconEntry | None]]:
        """Cut ``text`` into plain chunks and lexicon matches, in order.

        This is the primitive the IPA tier builds on: the phonemiser runs on
        the plain chunks, and each matched entry contributes its phonemes.

        Parameters
        ----------
        text : str
            The text to scan.
        language : str
            Language of the text (decides which entries apply).

        Returns
        -------
        list of (str, LexiconEntry or None)
            Pairs in reading order. ``(chunk, None)`` is ordinary text;
            ``(matched_word, entry)`` is a lexicon hit, with the word as it
            appeared in the text.

        Examples
        --------
        >>> lex = Lexicon.from_mapping(
        ...     {"entries": [{"word": "ONU", "language": "fr", "ipa": "oɛny"}]})
        >>> lex.split("Vive l'ONU !", "fr")
        [("Vive l'", None), ('ONU', LexiconEntry(word='ONU', ...)), (' !', None)]
        """
        pattern = self._pattern_for(language)
        if pattern is None:
            # No entry for this language: the whole text is one plain chunk.
            return [(text, None)]
        pieces: list[tuple[str, LexiconEntry | None]] = []
        cursor = 0
        for match in pattern.finditer(text):
            # Everything since the previous match is plain text (may be empty
            # when two lexicon words are adjacent).
            if match.start() > cursor:
                pieces.append((text[cursor : match.start()], None))
            matched = match.group(0)
            entry = self.entry_for(matched, language)
            # The pattern only contains lexicon words, so entry_for cannot
            # miss; the guard keeps the type checker honest.
            pieces.append((matched, entry) if entry else (matched, None))
            cursor = match.end()
        # The tail after the last match (or the whole text when none matched).
        if cursor < len(text):
            pieces.append((text[cursor:], None))
        return pieces

    # ----- the respelling tier ----------------------------------------------

    def respell(self, text: str, language: str) -> str:
        """Rewrite ``text`` so an engine without phoneme input says it right.

        Every lexicon word found in ``text`` is replaced by its respelling —
        the hand-written one when the entry has it, otherwise one derived once
        by the local LLM and cached. A word whose respelling cannot be
        obtained (no LLM available) is left exactly as written.

        Parameters
        ----------
        text : str
            The text about to be synthesised.
        language : str
            Language of the text.

        Returns
        -------
        str
            The rewritten text (identical to ``text`` when nothing matched).
        """
        pieces = self.split(text, language)
        # Fast path: nothing matched, hand the original string back untouched
        # (same object, so callers can cheaply detect "no rewrite happened").
        if all(entry is None for _, entry in pieces):
            return text
        out: list[str] = []
        for chunk, entry in pieces:
            if entry is None:
                out.append(chunk)
                continue
            respelling = self.ensure_respelling(entry, language)
            # No respelling obtainable: say the word as written rather than
            # dropping it — a mispronounced word beats a missing one.
            out.append(respelling or chunk)
        return "".join(out)

    def ensure_respelling(self, entry: LexiconEntry, language: str) -> str:
        """Return the entry's respelling, deriving it with the LLM if needed.

        Parameters
        ----------
        entry : LexiconEntry
            The entry to complete. Mutated in place when a derivation
            succeeds (and persisted to the sidecar cache).
        language : str
            Language of the text being synthesised — used when the entry is a
            wildcard, because a respelling is written *in* a language's
            orthography even when the word applies to all of them.

        Returns
        -------
        str
            The respelling, or ``""`` when none exists and none could be
            derived.
        """
        if entry.respelling:
            return entry.respelling
        if not self.llm_enabled:
            return ""
        # A wildcard entry still needs a concrete orthography to respell
        # into; the text's own language is the only sensible choice.
        lang = _language_key(entry.language)
        target = lang if lang != ANY_LANGUAGE else _language_key(language)
        cache_key = f"{target}:{entry.word.casefold()}"
        # Ask at most once per word per process, even on failure: a broken
        # Ollama must not add one timeout per sentence to every synthesis.
        if cache_key in self._llm_failed:
            return ""
        derived = _llm_respelling(entry.word, target, ipa=entry.ipa)
        if not derived:
            self._llm_failed.add(cache_key)
            osh.warning(
                "lexicon: no respelling for %r (%s) — the local LLM is "
                "unavailable or declined; the word will be spoken as written. "
                "Add a `respelling:` to the lexicon to fix it by hand.",
                entry.word,
                target,
            )
            return ""
        # Record the derivation on the entry (so this process never re-asks)
        # and in the sidecar cache (so no future process ever asks again —
        # after this moment the lexicon is deterministic and offline).
        entry.respelling = derived
        entry.source = "llm"
        self._save_cache_entry(cache_key, derived)
        osh.info("lexicon: derived respelling %r -> %r (%s)", entry.word, derived, target)
        return derived

    # ----- the LLM sidecar cache ---------------------------------------------

    def _cache_path(self) -> Path | None:
        """Where derived respellings persist (``None`` for in-memory lexicons)."""
        if self.path is None:
            return None
        return self.path.with_name(self.path.name + CACHE_SUFFIX)

    def _load_cache(self) -> None:
        """Fold the sidecar cache's derivations into entries lacking one."""
        cache_file = self._cache_path()
        if cache_file is None or not cache_file.exists():
            return
        try:
            cached: dict[str, str] = yaml.safe_load(cache_file.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001 - a corrupt cache must not break synthesis
            osh.warning("lexicon: unreadable cache %s (%s) — ignoring it", cache_file, exc)
            return
        # Apply each cached "lang:word" → respelling to the matching entry,
        # but never over a hand-written respelling: the human wins.
        for key, respelling in cached.items():
            lang, _, word = key.partition(":")
            entry = self._by_lang.get(lang, {}).get(word) or self._by_lang.get(
                ANY_LANGUAGE, {}
            ).get(word)
            if entry is not None and not entry.respelling:
                entry.respelling = str(respelling)
                entry.source = "llm"

    def _save_cache_entry(self, key: str, respelling: str) -> None:
        """Append one derivation to the sidecar cache (best effort).

        A write failure is logged, not raised: the derivation already lives in
        memory, so synthesis proceeds — only the *next* process pays the LLM
        call again.
        """
        cache_file = self._cache_path()
        if cache_file is None:
            return
        try:
            # Read-modify-write the whole (small) mapping: simpler than an
            # append format, and safe because derivations are idempotent.
            existing: dict[str, str] = {}
            if cache_file.exists():
                existing = yaml.safe_load(cache_file.read_text(encoding="utf-8")) or {}
            existing[key] = respelling
            cache_file.write_text(
                "# Respellings derived by the local LLM (temperature 0), one per\n"
                '# "language:word". Delete a line to force a re-derivation; move a\n'
                "# value into lexicon.yaml's `respelling:` to promote it to a human\n"
                "# decision.\n" + yaml.safe_dump(existing, allow_unicode=True, sort_keys=True),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 - the cache is an optimisation, not a contract
            osh.warning("lexicon: could not persist cache %s (%s)", cache_file, exc)


# ---------------------------------------------------------------------------
# The LLM derivation (best-engine-ai-helper + Ollama)
# ---------------------------------------------------------------------------


def _llm_respelling(word: str, language: str, *, ipa: str = "") -> str:
    """Derive a phonetic respelling of ``word`` with the local LLM.

    The model is resolved through ``best-engine-ai-helper`` — the suite rule:
    no package hardcodes a model name — and served by the local Ollama daemon
    at temperature 0, so the derivation is as deterministic as the serving
    stack allows. The result is validated structurally (one short line) before
    being trusted.

    Parameters
    ----------
    word : str
        The word to respell.
    language : str
        ISO-639-1 code of the orthography to respell into.
    ipa : str
        Optional target pronunciation in IPA, given to the model as ground
        truth when the lexicon entry carries one.

    Returns
    -------
    str
        The respelling, or ``""`` when the LLM stack is unavailable or its
        answer fails validation.
    """
    # Both imports stay inside the function: the lexicon must work (IPA tier,
    # hand-written respellings) on machines with no LLM stack at all.
    try:
        import best_engine_ai_helper as be
        import ollama
    except ImportError:
        return ""
    try:
        model = be.text_model()
    except Exception as exc:  # noqa: BLE001 - no env file / no detection yet
        osh.warning("lexicon: best-engine-ai-helper could not resolve a model (%s)", exc)
        return ""
    language_name = _LANGUAGE_NAMES.get(language, language)
    # The hint is phrased as ground truth, not a suggestion: when the lexicon
    # carries IPA, the human already decided the pronunciation and the model's
    # only job is transcribing it into ordinary spelling.
    hint = f" The target pronunciation in IPA is /{ipa}/." if ipa else ""
    # Few-shot on purpose, and no chain-of-thought: measured on this task,
    # local models answer lazily zero-shot ("Worcester" → "Worcester") and
    # burn their whole token budget when thinking is enabled; three examples
    # per language at temperature 0 get a usable answer in about a second.
    prompt = (
        "You configure a text-to-speech engine that has no phonetic input. "
        f'Rewrite the word "{word}" as a phonetic respelling in {language_name} '
        f"orthography: reading the respelling aloud with ordinary "
        f"{language_name} reading rules must produce the correct pronunciation "
        f'of "{word}".{hint}\n'
        "Rules:\n"
        f'- If ordinary {language_name} reading rules already pronounce "{word}" '
        "correctly, answer the word unchanged.\n"
        f"- For initialisms spoken letter by letter, write the {language_name} "
        "letter names joined by hyphens.\n"
        "- Answer with the respelling only: one short line, no explanation, "
        "no quotes, no IPA.\n"
        'Examples in French: "Wi-Fi" -> ouifi ; "FBI" -> èf-bé-i ; '
        '"steak" -> stèque.\n'
        'Examples in English: "cache" -> cash ; "EDF" -> ee-dee-eff ; '
        '"Reims" -> rance.\n'
        f'Word: "{word}" — {language_name} respelling:'
    )
    try:
        reply = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            # temperature 0 + a tight token budget: the answer is a few
            # syllables, and anything longer is already a wrong answer.
            options={"temperature": 0.0, "num_predict": 64},
            think=False,
        )
        answer = str(reply["message"]["content"])
    except TypeError:
        # Older ollama clients have no `think` kwarg; retry without it so the
        # feature does not depend on the client version.
        try:
            reply = ollama.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.0, "num_predict": 64},
            )
            answer = str(reply["message"]["content"])
        except Exception as exc:  # noqa: BLE001 - daemon down, model missing, ...
            osh.warning("lexicon: LLM call failed for %r (%s)", word, exc)
            return ""
    except Exception as exc:  # noqa: BLE001 - daemon down, model missing, ...
        osh.warning("lexicon: LLM call failed for %r (%s)", word, exc)
        return ""
    return _validate_respelling(answer, word)


def _validate_respelling(answer: str, word: str) -> str:
    """Accept an LLM answer only when it is shaped like a respelling.

    Parameters
    ----------
    answer : str
        Raw model output.
    word : str
        The word being respelled (for sanity bounds).

    Returns
    -------
    str
        The cleaned respelling, or ``""`` when the answer looks like prose,
        reasoning, or anything else that must not be spoken aloud.

    Examples
    --------
    >>> _validate_respelling(" au-haine-u \\n", "ONU")
    'au-haine-u'
    >>> _validate_respelling("Sure! Here is the respelling: au-haine-u", "ONU")
    ''
    """
    # Some reasoning models leak a <think> block even when asked not to;
    # strip it before judging the answer's shape.
    cleaned = re.sub(r"(?s)<think>.*?</think>", "", answer)
    cleaned = cleaned.strip().strip("\"'`").strip()
    if not cleaned or "\n" in cleaned:
        return ""
    # A respelling is a few syllables. Longer than ~8 words or ~6× the word is
    # prose pretending to be an answer; refusing it is safer than speaking it.
    if len(cleaned.split()) > 8 or len(cleaned) > max(24, 6 * len(word)):
        return ""
    # Explanatory punctuation is the signature of a chatty answer.
    if any(marker in cleaned for marker in (":", "(", ")", "=")):
        return ""
    return cleaned


# ---------------------------------------------------------------------------
# The IPA tier (used by phoneme-input backends such as kokoro)
# ---------------------------------------------------------------------------


def phonemise_with_lexicon(
    text: str,
    language: str,
    lexicon: Lexicon | None,
    phonemise: Callable[[str], str],
) -> str:
    """Phonemise ``text``, splicing lexicon IPA in place of matched words.

    The deterministic tier: the engine's own phonemiser runs on everything the
    lexicon does not claim, and each claimed word contributes, in order of
    preference, its ``ipa`` verbatim, the phonemisation of its ``respelling``,
    or the phonemisation of the word itself (a no-op override).

    Parameters
    ----------
    text : str
        The text to phonemise.
    language : str
        Language of the text (decides which lexicon entries apply).
    lexicon : Lexicon or None
        The active lexicon; ``None`` degrades to a plain ``phonemise(text)``.
    phonemise : callable
        ``str -> str``, the backend's own phonemiser for this language —
        passed in so this module depends on no backend.

    Returns
    -------
    str
        One phoneme string for the whole text.

    Examples
    --------
    >>> lex = Lexicon.from_mapping(
    ...     {"entries": [{"word": "Grasse", "language": "fr", "ipa": "ɡʁas"}]})
    >>> phonemise_with_lexicon("Grasse", "fr", lex, lambda s: f"<{s}>")
    'ɡʁas'
    """
    if lexicon is None:
        return phonemise(text)
    pieces = lexicon.split(text, language)
    # Fast path: no match means one phonemiser call on the untouched text —
    # the exact behaviour (and cost) the backend had before lexicons existed.
    if all(entry is None for _, entry in pieces):
        return phonemise(text)
    out: list[str] = []
    for chunk, entry in pieces:
        if entry is None:
            # Plain text between matches. Whitespace-only chunks carry no
            # phonemes; punctuation-bearing ones do (the phonemiser preserves
            # punctuation, which the engine renders as pauses).
            if chunk.strip():
                phonemes = phonemise(chunk).strip()
                if phonemes:
                    out.append(phonemes)
            continue
        if entry.ipa:
            # The human stated the phonemes; they go in verbatim.
            out.append(entry.ipa)
        elif entry.respelling:
            # No IPA, but a respelling exists: its phonemisation is still
            # deterministic, because the respelling is a fixed string.
            phonemes = phonemise(entry.respelling).strip()
            out.append(phonemes or chunk)
        else:
            # Entry with neither (awaiting an LLM pass that belongs to the
            # respelling tier): phonemise the word as written.
            phonemes = phonemise(chunk).strip()
            if phonemes:
                out.append(phonemes)
    # Phoneme chunks join on single spaces — espeak separates words the same
    # way, so the result reads like one phonemised sentence.
    return " ".join(part for part in out if part)


# ---------------------------------------------------------------------------
# Loading from settings (the "integrated by default" wiring)
# ---------------------------------------------------------------------------


def load_lexicon(settings: Settings) -> Lexicon | None:
    """Resolve and load the lexicon the settings point at, if any.

    Resolution order for the file path: ``settings.lexicon["path"]``, then the
    ``SPEAKER_HELPER_LEXICON`` environment variable (already folded into
    settings by :class:`~speaker_helper.config.Settings`), then a
    ``lexicon.yaml`` sitting in the current directory — mirroring how
    ``settings.yaml`` itself is found.

    Parameters
    ----------
    settings : Settings
        The configuration whose ``lexicon`` mapping drives this
        (keys: ``path``, ``enabled``, ``llm``).

    Returns
    -------
    Lexicon or None
        The loaded lexicon, or ``None`` when the feature is disabled or no
        file exists (the no-lexicon path costs nothing per synthesis).
    """
    cfg = settings.lexicon or {}
    # `enabled: false` switches the whole feature off regardless of files.
    if not bool(cfg.get("enabled", True)):
        return None
    raw_path = str(cfg.get("path") or "").strip()
    path = Path(raw_path) if raw_path else Path("lexicon.yaml")
    if not path.exists():
        # An explicitly configured path that is missing is a loud mistake; the
        # implicit ./lexicon.yaml simply not existing is the normal quiet case.
        if raw_path:
            osh.warning("lexicon: configured file %s does not exist — no lexicon", path)
        return None
    lexicon = Lexicon.load(path)
    # `llm: false` in settings wins over the file's own `llm:` key, so an
    # operator can forbid LLM calls machine-wide without editing lexicons.
    if not bool(cfg.get("llm", True)):
        lexicon.llm_enabled = False
    osh.info(
        "lexicon: %s loaded (%d entr%s, llm %s)",
        path,
        sum(len(bucket) for bucket in lexicon._by_lang.values()),
        "y" if sum(len(b) for b in lexicon._by_lang.values()) == 1 else "ies",
        "on" if lexicon.llm_enabled else "off",
    )
    return lexicon
