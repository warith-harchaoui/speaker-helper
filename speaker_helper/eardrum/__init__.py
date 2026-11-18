"""
The Ralph Eardrum Loop: re-listen to every word, fix how it is spelled for
the engine, until the engine says it right.

Module summary
--------------
The sibling of the Ralph Eyeball Loop (render a figure, look at it, fix the
source): here the engine **says** a word, a phoneme recogniser **hears** it,
the distance to the right pronunciation is measured, and the respelling the
engine is handed is rewritten until the word comes out right. What is checked:

* every entry of the **lexicon** for the language (the default);
* the words of a **document** at risk of being mispronounced and not in the
  lexicon yet — proper nouns, acronyms, brand-shaped words, words espeak reads
  as foreign (:mod:`.discover`);
* optionally (``listen_all``) **every word** of the document: each sentence is
  said with today's lexicon and heard back, and the words that came out far
  from their expected reading join the list;
* or an explicit list of words.

Winning spellings go to ``lexicon.yaml.eardrum.yaml`` (per engine, applied on
every later synthesis, never over a hand-written one); the report with every
take goes to ``.private/eardrum-loop/<date-time>/index.html``.

Submodules: :mod:`.phones` (IPA units and distances), :mod:`.targets` (what
a word should sound like: lexicon, Wiktionary, Wikipedia, espeak),
:mod:`.ear` (the phoneme recogniser), :mod:`.espeak`, :mod:`.discover`,
:mod:`.loop` (one word, start to finish), :mod:`.report`.

Usage example
-------------
>>> from speaker_helper import Settings
>>> from speaker_helper.eardrum import run_eardrum
>>> # report = run_eardrum(Settings.from_mapping({"language": "fr"}),
>>> #                      text="Hier, Feynman parlait de l'ONU.")
>>> # report.html  -> .private/eardrum-loop/20261117-213000/index.html

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import os_helper as osh

from speaker_helper.config import Settings
from speaker_helper.eardrum.discover import _WORD, Discovered, discover
from speaker_helper.eardrum.loop import (
    DEFAULT_THRESHOLD,
    Listener,
    WordJob,
    WordResult,
    tune_word,
)
from speaker_helper.eardrum.targets import TargetResolver
from speaker_helper.lexicon import Lexicon, _language_key, verified_path_for

#: Where reports go, mirroring the Eyeball Loop's ``.private/ralph-loop/``.
DEFAULT_OUT = Path(".private") / "eardrum-loop"

#: In the listen-all pass, a word whose sentence-level score is above this is
#: suspect and joins the loop. Higher than the loop's threshold: the target
#: here is espeak's reading, which is itself wrong on the very words that
#: matter, so only clear departures are worth a closer listen.
LISTEN_ALL_THRESHOLD = 0.45

__all__ = [
    "DEFAULT_THRESHOLD",
    "EardrumReport",
    "WordJob",
    "WordResult",
    "collect_jobs",
    "run_eardrum",
    "run_eardrum_async",
]


@dataclass
class EardrumReport:
    """What a run of the loop produced.

    Attributes
    ----------
    results : list of WordResult
        One per word.
    html : Path or None
        The HTML report (``None`` when nothing was written).
    verified_path : Path or None
        The sidecar the winning spellings went to (``None`` on a dry run).
    meta : dict
        Engine, language, threshold, date.
    """

    results: list[WordResult] = field(default_factory=list)
    html: Path | None = None
    verified_path: Path | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def unresolved(self) -> list[WordResult]:
        """The words still said wrong (``unresolved``, ``proposal``, ``no-target``)."""
        return [r for r in self.results if r.verdict in ("unresolved", "proposal", "no-target")]


def _current_respelling(lexicon: Lexicon | None, word: str, language: str, engine: str) -> str:
    """The respelling the engine is handed today for ``word`` (no LLM call).

    Parameters
    ----------
    lexicon : Lexicon or None
        The project's lexicon.
    word : str
        The word.
    language : str
        Its language.
    engine : str
        The backend.

    Returns
    -------
    str
        The verified respelling for this engine, else the entry's own, else
        ``""`` (the word is read as written).
    """
    if lexicon is None:
        return ""
    entry = lexicon.entry_for(word, language)
    if entry is None:
        return ""
    if not (entry.source == "user" and entry.respelling):
        verified = lexicon.verified_for(word, language, engine)
        if verified.get("respelling"):
            return str(verified["respelling"])
    return "" if entry.source == "eardrum" else entry.respelling


def collect_jobs(
    lexicon: Lexicon | None,
    language: str,
    *,
    text: str | None = None,
    words: list[str] | None = None,
    include_lexicon: bool = True,
    foreign: Any = None,
) -> list[WordJob]:
    """Decide which words the loop will test.

    Parameters
    ----------
    lexicon : Lexicon or None
        The project's lexicon.
    language : str
        Language of the text.
    text : str or None
        A document: its lexicon words and its discovered words are tested.
    words : list of str or None
        Explicit words (tested whatever else is asked).
    include_lexicon : bool
        Without ``text``: test every lexicon entry of the language. With
        ``text``: test the lexicon entries the text contains.
    foreign : callable or None
        espeak-based foreign-word detection, forwarded to
        :func:`~.discover.discover`.

    Returns
    -------
    list of WordJob
        No word twice.
    """
    lang = _language_key(language)
    jobs: dict[str, WordJob] = {}

    def add(word: str, reasons: list[str]) -> None:
        """Queue ``word`` once, merging the reasons it was picked for."""
        entry = lexicon.entry_for(word, lang) if lexicon is not None else None
        key = (entry.word if entry is not None else word).casefold()
        job = jobs.setdefault(
            key, WordJob(word=entry.word if entry else word, language=lang, entry=entry)
        )
        for reason in reasons:
            if reason not in job.reasons:
                job.reasons.append(reason)

    for word in words or []:
        add(word, ["asked"])
    if text is not None:
        if include_lexicon and lexicon is not None:
            for _chunk, entry in lexicon.split(text, lang):
                if entry is not None:
                    add(entry.word, ["lexicon"])
        known = (lambda w: lexicon.entry_for(w, lang) is not None) if lexicon is not None else None
        found: list[Discovered] = discover(text, lang, known=known, foreign=foreign)
        for discovered in found:
            add(discovered.word, discovered.reasons)
    elif include_lexicon and lexicon is not None and not words:
        for bucket in (lexicon._by_lang.get(lang, {}), lexicon._by_lang.get("*", {})):
            for entry in bucket.values():
                add(entry.word, ["lexicon"])
    return list(jobs.values())


def _sentences(text: str) -> list[str]:
    """Cut a text into sentences for the listen-all pass.

    Parameters
    ----------
    text : str
        The document.

    Returns
    -------
    list of str
        Non-empty sentences, whitespace-normalised.

    Examples
    --------
    >>> _sentences("Un. Deux ?\\nTrois")
    ['Un.', 'Deux ?', 'Trois']
    """
    parts = re.split(r"(?<=[.!?…])\s+|\n+", text)
    return [" ".join(p.split()) for p in parts if p.strip()]


async def listen_all(
    speaker: Any,
    ear: Any,
    text: str,
    language: str,
    *,
    threshold: float = LISTEN_ALL_THRESHOLD,
) -> list[tuple[str, float, str]]:
    """Say the whole text with today's lexicon and flag the words heard wrong.

    Parameters
    ----------
    speaker : Speaker
        An open speaker, with the project's lexicon in place.
    ear : Ear
        The phoneme recogniser.
    text : str
        The document.
    language : str
        Its language.
    threshold : float
        Sentence-level score above which a word is flagged.

    Returns
    -------
    list of (word, score, sentence)
        The flagged words, worst first.
    """
    from speaker_helper.eardrum.espeak import espeak_ipa
    from speaker_helper.eardrum.phones import sentence_distances, tokenize

    flagged: dict[str, tuple[str, float, str]] = {}
    for sentence in _sentences(text):
        words = [m.group(0) for m in _WORD.finditer(sentence)]
        if not words:
            continue
        audio = await speaker.say(sentence, language=language)
        heard = [h.phone for h in ear.hear(audio.wav_bytes)]
        # Each word's expected reading is espeak on what the engine was
        # actually handed (the lexicon's respelling when there is one).
        spoken = [speaker._respelled(w, language) for w in words]
        expected = [espeak_ipa(w, language) for w in spoken]
        for word, ipa, score in zip(
            words, expected, sentence_distances(heard, expected), strict=True
        ):
            # Two-phone words are too short to judge: one misheard phone is
            # already half the word.
            if len(tokenize(ipa)) < 3 or score <= threshold:
                continue
            if score > flagged.get(word.casefold(), ("", -1.0, ""))[1]:
                flagged[word.casefold()] = (word, score, sentence)
    return sorted(flagged.values(), key=lambda row: -row[1])


async def run_eardrum_async(
    settings: Settings,
    *,
    text: str | None = None,
    words: list[str] | None = None,
    include_lexicon: bool = True,
    listen_everything: bool = False,
    max_iter: int = 4,
    threshold: float = DEFAULT_THRESHOLD,
    web: bool = True,
    llm: bool = True,
    dry_run: bool = False,
    out_dir: Path | None = None,
    ear: Any = None,
    speaker: Any = None,
    resolver: TargetResolver | None = None,
) -> EardrumReport:
    """Run the Ralph Eardrum Loop; see the module docstring.

    Parameters
    ----------
    settings : Settings
        Engine, language, lexicon location.
    text : str or None
        A document to check (its lexicon words and discovered words).
    words : list of str or None
        Explicit words to check.
    include_lexicon : bool
        Also check lexicon entries (all of them without ``text``).
    listen_everything : bool
        Say the whole ``text`` first and add every word heard far from its
        expected reading.
    max_iter : int
        Maximum LLM proposals per word.
    threshold : float
        Score at or below which a word counts as said right.
    web : bool
        Look targets up on Wiktionary / Wikipedia.
    llm : bool
        Let the local LLM propose respellings.
    dry_run : bool
        Measure and report, but write nothing to the verified sidecar.
    out_dir : Path or None
        Report directory; a dated folder under :data:`DEFAULT_OUT` by default.
    ear, speaker, resolver : optional
        Injected collaborators (tests); built from ``settings`` otherwise.

    Returns
    -------
    EardrumReport
        The results and where the report went.
    """
    from speaker_helper.engine import resolve_auto
    from speaker_helper.lexicon import load_lexicon
    from speaker_helper.speaker import Speaker

    settings = resolve_auto(settings)
    language = _language_key(settings.language or "fr")
    engine = (settings.backend or "auto").lower()
    lexicon = load_lexicon(settings)
    verified_path = None if dry_run else verified_path_for(settings)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out_dir or (DEFAULT_OUT / stamp)
    out.mkdir(parents=True, exist_ok=True)

    try:
        from speaker_helper.eardrum.espeak import foreign_words
    except ImportError:  # pragma: no cover - phonemizer missing
        foreign_words = None  # type: ignore[assignment]
    jobs = collect_jobs(
        lexicon,
        language,
        text=text,
        words=words,
        include_lexicon=include_lexicon,
        foreign=foreign_words,
    )
    if ear is None:
        from speaker_helper.eardrum.ear import PhonemeEar

        ear = PhonemeEar()
    own_speaker = speaker is None
    spk = speaker or Speaker(settings)
    resolver = resolver or TargetResolver(web=web)
    results: list[WordResult] = []
    try:
        if listen_everything and text:
            spk.lexicon = lexicon
            for word, score, sentence in await listen_all(spk, ear, text, language):
                osh.info(
                    "eardrum: heard %r far from its reading (%.2f) in: %s", word, score, sentence
                )
                known = {j.word.casefold(): j for j in jobs}
                if word.casefold() in known:
                    if "heard" not in known[word.casefold()].reasons:
                        known[word.casefold()].reasons.append("heard")
                else:
                    entry = lexicon.entry_for(word, language) if lexicon is not None else None
                    jobs.append(
                        WordJob(word=word, language=language, entry=entry, reasons=["heard"])
                    )
        osh.info("eardrum: %d word(s) to check on %s (%s)", len(jobs), engine, language)
        listener = Listener(spk, ear, _espeak(), out)
        for job in jobs:
            current = _current_respelling(lexicon, job.word, language, engine)
            results.append(
                await tune_word(
                    job,
                    listener,
                    resolver,
                    engine=engine,
                    max_iter=max_iter,
                    threshold=threshold,
                    llm=llm,
                    verified_path=verified_path,
                    current=current,
                )
            )
    finally:
        if own_speaker:
            await spk.aclose()
    meta = {
        "engine": engine,
        "language": language,
        "threshold": threshold,
        "date": _dt.datetime.now().isoformat(timespec="seconds"),
        "saved_to": str(verified_path) if verified_path else None,
    }
    from speaker_helper.eardrum.report import write_report

    html = write_report(out, results, meta)
    return EardrumReport(results=results, html=html, verified_path=verified_path, meta=meta)


def _espeak() -> Any:
    """The carrier-sentence reader (imported late: it needs phonemizer).

    Returns
    -------
    callable
        :func:`speaker_helper.eardrum.espeak.espeak_ipa`.
    """
    from speaker_helper.eardrum.espeak import espeak_ipa

    return espeak_ipa


def run_eardrum(settings: Settings, **kwargs: Any) -> EardrumReport:
    """Synchronous wrapper around :func:`run_eardrum_async`.

    Parameters
    ----------
    settings : Settings
        See :func:`run_eardrum_async`.
    **kwargs
        Forwarded unchanged.

    Returns
    -------
    EardrumReport
        The results and where the report went.
    """
    return asyncio.run(run_eardrum_async(settings, **kwargs))
