"""
The Ralph Eardrum Loop: say it, hear it, fix the spelling, say it again.

Module summary
--------------
For each word under test — a lexicon entry, or a word discovered in a
document — the loop:

1. finds the **target** pronunciation (:mod:`.targets`: the lexicon's IPA,
   Wiktionary, Wikipedia, else espeak);
2. has the real engine say the word inside two **carrier sentences** ("Je
   vous parle de … aujourd'hui."), because a word said alone is not said the
   way it is said in a sentence;
3. **hears** each take with a phoneme recogniser (:mod:`.ear`), finds the
   word inside the sentence and scores it against the target
   (:mod:`.phones`); the take's score is the mean over the carriers;
4. when the score is above the threshold, asks the local LLM for **another
   respelling**, showing it the target and every earlier attempt with what
   was heard and how far it was, and goes back to 2 — at most ``max_iter``
   times;
5. keeps the **best** attempt, not the last one, and records it in the
   lexicon's verified sidecar (``lexicon.yaml.eardrum.yaml``) for this
   engine, so every later synthesis uses it.

A hand-written respelling is never replaced: when it fails, the report says
so and proposes the better one, and the human decides. For an engine that
takes phonemes (kokoro), there is nothing to respell — the loop checks that
the target IPA itself comes out right and records it.

Every take is written to disk, and the report (``index.html``) puts each
word's clips side by side: the measure points, the ear decides.

Usage example
-------------
>>> carriers_for("fr")[0]
"Je vous parle de {w} aujourd'hui."

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import datetime as _dt
import io
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import os_helper as osh
import yaml

from speaker_helper.eardrum.ear import Ear, HeardPhone
from speaker_helper.eardrum.phones import align, describe_differences, tokenize, word_distance
from speaker_helper.eardrum.targets import Target, TargetResolver
from speaker_helper.lexicon import (
    _LANGUAGE_NAMES,
    Lexicon,
    LexiconEntry,
    _language_key,
    _validate_respelling,
)

#: Below this score a take counts as said right. Calibrated on chatterbox
#: French takes: "Faïnemane" heard as ``s a i n m a n`` against
#: /fajnman/ scores 0.06, the wrong "fènman" scores 0.39.
DEFAULT_THRESHOLD = 0.25

#: A new respelling must beat the current one by this much to replace it:
#: two takes of the same text differ by a few hundredths on their own.
IMPROVEMENT_MARGIN = 0.05

#: Carrier sentences per language. Neutral, short, the word in the middle,
#: with plain words around it that every engine and espeak read alike.
CARRIERS: dict[str, list[str]] = {
    "fr": ["Je vous parle de {w} aujourd'hui.", "C'est bien {w} qui l'a dit."],
    "en": ["I am talking about {w} today.", "It was {w} who said it."],
    "es": ["Hoy les hablo de {w} otra vez.", "Fue {w} quien lo dijo."],
    "it": ["Oggi vi parlo di {w} di nuovo.", "È stato {w} a dirlo."],
    "de": ["Ich spreche heute über {w} mit euch.", "Es war {w}, der das sagte."],
    "pt": ["Hoje falo de {w} outra vez.", "Foi {w} quem o disse."],
}

#: Padding around a word's clip, so its first and last phones are audible.
CLIP_PAD_S = 0.08


def carriers_for(language: str) -> list[str]:
    """The carrier sentences for ``language`` (English ones as a last resort).

    Parameters
    ----------
    language : str
        ISO-639-1 code.

    Returns
    -------
    list of str
        Templates with a ``{w}`` slot.
    """
    return CARRIERS.get(_language_key(language), CARRIERS["en"])


@dataclass
class Take:
    """One carrier sentence said with one candidate, and what was heard.

    Attributes
    ----------
    carrier : str
        The sentence template.
    score : float
        Distance of the word's region to the target (0 = perfect).
    heard : str
        The phones heard in the word's region, space-separated.
    heard_sentence : str
        Every phone heard in the sentence.
    audio : str
        Path of the whole take, relative to the report directory.
    clip : str
        Path of the word's own clip, relative to the report directory.
    """

    carrier: str
    score: float
    heard: str
    heard_sentence: str
    audio: str = ""
    clip: str = ""


@dataclass
class Attempt:
    """One candidate spelling (or IPA) and its takes.

    Attributes
    ----------
    candidate : str
        The respelling (or IPA) tried.
    kind : str
        ``"respelling"`` or ``"ipa"``.
    origin : str
        Where it came from: ``"written"`` (the word as written),
        ``"current"`` (what the lexicon applies today), ``"llm"``,
        ``"target"`` (the target IPA itself, for phoneme engines).
    score : float
        Mean score over the takes.
    takes : list of Take
        One per carrier sentence.
    """

    candidate: str
    kind: str
    origin: str
    score: float = 1.0
    takes: list[Take] = field(default_factory=list)


@dataclass
class WordResult:
    """Everything the loop did for one word.

    Attributes
    ----------
    word, language, engine : str
        What was tested, in which language, on which backend.
    reasons : list of str
        Why the word was tested (``lexicon``, ``proper``, ``acronym``…).
    source : str
        The lexicon entry's source (``user``, ``builtin``, ``llm``,
        ``eardrum``) or ``"new"`` for a discovered word.
    target : dict or None
        The :class:`~.targets.Target`, as a dict.
    attempts : list of Attempt
        In the order tried.
    best : int
        Index of the best attempt (``-1`` when nothing was tried).
    verdict : str
        ``ok`` (already right), ``fixed`` (a new spelling passes and was
        saved), ``improved`` (better, saved, still above the threshold),
        ``proposal`` (a hand-written spelling fails; a better one is proposed,
        not applied), ``unresolved``, ``no-target``.
    saved : bool
        Whether the verified sidecar was written for this word.
    note : str
        A sentence for the human, in French (the report's language).
    """

    word: str
    language: str
    engine: str
    reasons: list[str] = field(default_factory=list)
    source: str = "new"
    target: dict[str, Any] | None = None
    attempts: list[Attempt] = field(default_factory=list)
    best: int = -1
    verdict: str = "unresolved"
    saved: bool = False
    note: str = ""


@dataclass
class WordJob:
    """A word to put through the loop.

    Attributes
    ----------
    word : str
        The word or phrase.
    language : str
        Language it is spoken in.
    entry : LexiconEntry or None
        The lexicon entry, when there is one.
    reasons : list of str
        Why it is tested.
    """

    word: str
    language: str
    entry: LexiconEntry | None = None
    reasons: list[str] = field(default_factory=list)


def slug(word: str) -> str:
    """A filesystem-safe name for a word.

    Parameters
    ----------
    word : str
        Any word.

    Returns
    -------
    str
        Lowercase ASCII-ish, hyphen-separated.

    Examples
    --------
    >>> slug("Van Gogh"), slug("l'ONU")
    ('van-gogh', 'l-onu')
    """
    cleaned = re.sub(r"[^\w]+", "-", word.casefold(), flags=re.UNICODE).strip("-")
    return cleaned or "word"


# ---------------------------------------------------------------------------
# The LLM proposer
# ---------------------------------------------------------------------------


#: How each sound is usually written, per orthography: a cheat sheet that
#: turns a small model's guesswork into lookups. Measured need: without it,
#: gemma3:12b answered "Nitcherche" for /ˈniːtʃə/ three times in a row.
SPELLING_GUIDE: dict[str, str] = {
    "fr": (
        "/ʃ/ ch · /tʃ/ tch · /dʒ/ dj · /ʒ/ j · /k/ k or qu · /ɡ/ g (gu before e, i) · "
        "/s/ ss between vowels · /z/ z · /ŋ/ ng · /j/ y or ï · /w/ ou · /h/ (silent, "
        "drop it) · /i/ i · /u/ ou · /y/ u · /e/ é · /ɛ/ è · /ə/ e (eu at the end) · "
        "/ø/ eu · /o/ ô · /ɔ/ o · /a/ a · /aɪ/ aï · /eɪ/ èï · /aʊ/ aou · /ɔɪ/ oï · "
        "/ʌ/ eu · /ɪ/ i · /ʊ/ ou · /θ/ ss · /ð/ d · /ɹ/ r · a final consonant that "
        "must be heard gets a final e (Sutton → Seutone), a vowel before n or m "
        "that must not be nasal is followed by ne / me (Feynman → Faïnemane)."
    ),
    "en": (
        "/ʃ/ sh · /tʃ/ ch · /ʒ/ zh · /dʒ/ j · /k/ k · /ɡ/ g · /ŋ/ ng · /j/ y · "
        "/i/ ee · /ɪ/ i · /u/ oo · /ʊ/ u · /y/ ew · /e/ ay · /ɛ/ e · /æ/ a · "
        "/ɑ/ ah · /ɔ/ aw · /o/ oh · /ə/ uh · /aɪ/ eye · /aʊ/ ow · /ʁ/ r · "
        "stress the syllable written in capitals only if needed."
    ),
}


def _prompt(word: str, language: str, target: Target, history: list[Attempt]) -> str:
    """The proposal prompt: target, guide, every attempt and what went wrong.

    Parameters
    ----------
    word : str
        The word.
    language : str
        ISO-639-1 code of the orthography to respell into.
    target : Target
        The pronunciation to reach.
    history : list of Attempt
        Earlier attempts (sorted best first in the prompt).

    Returns
    -------
    str
        The prompt.
    """
    language_name = _LANGUAGE_NAMES.get(language, language)
    goal = tokenize(target.variants[0])
    lines: list[str] = []
    for attempt in sorted(history, key=lambda a: a.score):
        heard = attempt.takes[0].heard if attempt.takes else ""
        issues = describe_differences(tokenize(heard), goal)[:4]
        lines.append(
            f'- "{attempt.candidate}" → heard /{heard}/, distance {attempt.score:.2f}'
            + (f" ({'; '.join(issues)})" if issues else "")
        )
    guide = SPELLING_GUIDE.get(language, "")
    return (
        "You tune a text-to-speech engine that has no phonetic input, by ear. "
        f'The word "{word}" must sound like /{" | ".join(target.variants)}/ '
        f"(IPA, phones: {' '.join(goal)}). Write a phonetic respelling in "
        f"{language_name} orthography: read aloud with ordinary {language_name} "
        "rules, it must produce exactly those phones, no more, no fewer.\n"
        + (f"How {language_name} writes each sound: {guide}\n" if guide else "")
        + "Earlier attempts, best first, with what a phoneme recogniser heard and "
        "what went wrong:\n"
        + "\n".join(lines)
        + "\nStart from the best attempt and change only what went wrong. "
        "Every answer above is forbidden. Answer with the respelling only: one "
        "short line, no explanation, no quotes, no IPA.\n"
        f'Word: "{word}" — new {language_name} respelling:'
    )


def propose_respelling(
    word: str,
    language: str,
    target: Target,
    history: list[Attempt],
) -> str:
    """Ask the local LLM for a respelling not tried yet.

    The model sees the target, a sound-to-spelling guide for the orthography,
    and every earlier attempt with what the ear heard and, phone by phone,
    what went wrong — the information a human would use to adjust a spelling
    by ear. A repeat is answered in the same conversation ("already tried,
    another one"), with a little more temperature each time.

    Parameters
    ----------
    word : str
        The word.
    language : str
        ISO-639-1 code of the orthography to respell into.
    target : Target
        The pronunciation to reach.
    history : list of Attempt
        Earlier attempts, any order.

    Returns
    -------
    str
        A new respelling, or ``""`` when the LLM is unavailable, declines or
        only repeats earlier attempts.
    """
    try:
        import best_engine_ai_helper as be
        import ollama
    except ImportError:
        return ""
    try:
        model = be.text_model()
    except Exception as exc:  # noqa: BLE001 - no env file / no detection yet
        osh.warning("eardrum: best-engine-ai-helper could not resolve a model (%s)", exc)
        return ""
    tried = {a.candidate.casefold() for a in history}
    messages: list[dict[str, str]] = [
        {"role": "user", "content": _prompt(word, language, target, history)}
    ]
    for temperature in (0.4, 0.7, 1.0):
        try:
            reply = ollama.chat(
                model=model,
                messages=messages,
                options={"temperature": temperature, "num_predict": 64},
                think=False,
            )
        except Exception as exc:  # noqa: BLE001 - daemon down, model missing, old client
            osh.warning(
                "eardrum: the local LLM %r did not answer (%s). Pull it (`ollama pull "
                "%s`) or name an installed one with BEST_LLM_TEXT.",
                model,
                exc,
                model,
            )
            return ""
        raw = str(reply["message"]["content"])
        answer = _validate_respelling(raw, word)
        if answer and answer.casefold() not in tried:
            return answer
        # Keep the conversation: telling the model its answer was a repeat
        # works where only raising the temperature did not.
        messages += [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": f'"{answer or raw.strip()}" was already tried or is not a '
                "respelling. Give a different one, one line only:",
            },
        ]
        tried.add((answer or raw).casefold())
    return ""


# ---------------------------------------------------------------------------
# Hearing one candidate
# ---------------------------------------------------------------------------


def _cut(wav_bytes: bytes, start_s: float, end_s: float) -> bytes:
    """Cut ``[start_s, end_s]`` out of a WAV payload.

    Parameters
    ----------
    wav_bytes : bytes
        Encoded audio.
    start_s, end_s : float
        The span, clamped to the audio.

    Returns
    -------
    bytes
        A WAV payload of the span.
    """
    import soundfile as sf

    data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32", always_2d=False)
    a = max(0, int(start_s * sr))
    b = min(len(data), int(end_s * sr))
    out = io.BytesIO()
    sf.write(out, data[a:b], sr, format="WAV")
    return out.getvalue()


def _word_span(heard: list[HeardPhone], indices: list[int]) -> tuple[float, float] | None:
    """Time span of the heard phones at ``indices``, padded.

    Parameters
    ----------
    heard : list of HeardPhone
        Every phone heard in the sentence.
    indices : list of int
        The word region's phones.

    Returns
    -------
    tuple of (float, float) or None
        ``(start, end)`` in seconds, or ``None`` when the region is empty.
    """
    if not indices:
        return None
    first, last = heard[min(indices)], heard[max(indices)]
    return max(0.0, first.start_s - CLIP_PAD_S), last.end_s + CLIP_PAD_S


class Listener:
    """Says a candidate through the real engine and scores what is heard.

    Parameters
    ----------
    speaker : Speaker
        An open :class:`~speaker_helper.speaker.Speaker` (engine loaded once).
    ear : Ear
        The phoneme recogniser.
    espeak : callable
        ``(text, language) -> ipa`` for the carrier sentences.
    out_dir : Path or None
        Where takes are written (``None`` writes nothing — tests).
    """

    def __init__(
        self,
        speaker: Any,
        ear: Ear,
        espeak: Callable[[str, str], str],
        out_dir: Path | None,
    ) -> None:
        """Keep the collaborators; nothing is synthesised yet.

        Parameters
        ----------
        speaker, ear, espeak, out_dir
            See the class docstring.
        """
        self.speaker = speaker
        self.ear = ear
        self.espeak = espeak
        self.out_dir = out_dir

    @property
    def phoneme_input(self) -> bool:
        """Whether the engine takes IPA itself (kokoro) rather than text."""
        return getattr(type(self.speaker.engine), "LEXICON_TIER", "respelling") == "ipa"

    def _use(self, entry: LexiconEntry) -> None:
        """Make ``entry`` the only lexicon entry the engine sees.

        Parameters
        ----------
        entry : LexiconEntry
            The candidate as a lexicon entry.
        """
        trial = Lexicon([entry], llm_enabled=False)
        self.speaker.lexicon = trial
        # A phoneme-input backend reads its own copy of the lexicon (it
        # splices IPA while phonemising), so it must see the candidate too.
        if hasattr(self.speaker.engine, "_lexicon"):
            self.speaker.engine._lexicon = trial

    async def attempt(
        self,
        job: WordJob,
        target: Target,
        candidate: str,
        *,
        kind: str,
        origin: str,
        number: int,
    ) -> Attempt:
        """Say ``candidate`` in every carrier and score the takes.

        Parameters
        ----------
        job : WordJob
            The word.
        target : Target
            What it should sound like.
        candidate : str
            Respelling (or IPA when ``kind == "ipa"``).
        kind : str
            ``"respelling"`` or ``"ipa"``.
        origin : str
            See :class:`Attempt`.
        number : int
            Attempt number, for file names.

        Returns
        -------
        Attempt
            With its takes and mean score.
        """
        language = _language_key(job.language)
        fields = {"ipa": candidate} if kind == "ipa" else {"respelling": candidate}
        self._use(LexiconEntry(word=job.word, language=language, source="trial", **fields))
        result = Attempt(candidate=candidate, kind=kind, origin=origin)
        for k, carrier in enumerate(carriers_for(language)):
            before, _, after = carrier.partition("{w}")
            audio = await self.speaker.say(carrier.replace("{w}", job.word), language=language)
            heard = self.ear.hear(audio.wav_bytes)
            phones = [h.phone for h in heard]
            scored = word_distance(
                phones,
                self.espeak(before.strip(), language),
                target.variants,
                self.espeak(after.strip(), language),
            )
            take = Take(
                carrier=carrier,
                score=scored.score,
                heard=" ".join(scored.heard),
                heard_sentence=" ".join(phones),
            )
            if self.out_dir is not None:
                folder = self.out_dir / "audio" / slug(job.word)
                folder.mkdir(parents=True, exist_ok=True)
                name = f"a{number}-c{k}"
                (folder / f"{name}.wav").write_bytes(audio.wav_bytes)
                take.audio = f"audio/{slug(job.word)}/{name}.wav"
                span = _word_span(heard, scored.heard_indices)
                if span is not None:
                    (folder / f"{name}-word.wav").write_bytes(_cut(audio.wav_bytes, *span))
                    take.clip = f"audio/{slug(job.word)}/{name}-word.wav"
            result.takes.append(take)
        result.score = round(sum(t.score for t in result.takes) / len(result.takes), 4)
        osh.info(
            "eardrum: %s ← %r (%s): %.3f, heard /%s/",
            job.word,
            candidate,
            origin,
            result.score,
            result.takes[0].heard,
        )
        return result


# ---------------------------------------------------------------------------
# The verified sidecar
# ---------------------------------------------------------------------------


def save_verified(path: Path, key: str, record: dict[str, Any]) -> None:
    """Write one verified record into the sidecar (read-modify-write).

    Parameters
    ----------
    path : Path
        ``<lexicon>.eardrum.yaml``.
    key : str
        ``"engine:language:word"`` (word casefolded).
    record : dict
        ``word``, ``respelling`` or ``ipa``, ``score``, ``verified``,
        ``target``, ``target_source``, ``heard``, ``date``.
    """
    existing: dict[str, Any] = {}
    if path.exists():
        existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    existing[key] = record
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Respellings the Ralph Eardrum Loop heard to work, per engine.\n"
        '# Keys are "engine:language:word". Applied automatically on every\n'
        "# synthesis by that engine, except over a hand-written respelling\n"
        "# (the human always wins). Delete an entry to stop using it; copy its\n"
        "# respelling into lexicon.yaml to make it a human decision.\n"
        + yaml.safe_dump(existing, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# One word, start to finish
# ---------------------------------------------------------------------------


async def tune_word(
    job: WordJob,
    listener: Listener,
    resolver: TargetResolver,
    *,
    engine: str,
    max_iter: int = 4,
    threshold: float = DEFAULT_THRESHOLD,
    llm: bool = True,
    verified_path: Path | None = None,
    current: str = "",
    proposer: Callable[[str, str, Target, list[Attempt]], str] = propose_respelling,
) -> WordResult:
    """Run the loop on one word.

    Parameters
    ----------
    job : WordJob
        The word.
    listener : Listener
        Says and hears candidates.
    resolver : TargetResolver
        Finds the target.
    engine : str
        Backend name, for the verified key and the report.
    max_iter : int
        Maximum number of LLM proposals.
    threshold : float
        Score at or below which a take counts as right.
    llm : bool
        Allow LLM proposals (off: measure only).
    verified_path : Path or None
        Where to save a winning spelling (``None``: dry run).
    current : str
        The respelling applied today for this engine (lexicon, verified
        sidecar…); empty when the word is read as written.
    proposer : callable
        Injected for tests; :func:`propose_respelling` in real use.

    Returns
    -------
    WordResult
        Everything tried, the best attempt and the verdict.
    """
    language = _language_key(job.language)
    entry = job.entry
    llm_silent = False
    result = WordResult(
        word=job.word,
        language=language,
        engine=engine,
        reasons=list(job.reasons),
        source=entry.source if entry is not None else "new",
    )
    from speaker_helper.eardrum.espeak import espeak_ipa

    target = resolver.resolve(
        job.word,
        language,
        ipa=entry.ipa if entry is not None else "",
        respelling=current,
        espeak=espeak_ipa,
    )
    if target is None:
        result.verdict = "no-target"
        result.note = (
            "Aucune prononciation trouvée (pas d'IPA dans le lexique, rien sur le "
            "Wiktionnaire ni Wikipédia). Ajoutez un `ipa:` à l'entrée et relancez."
        )
        return result
    if current and len(target.variants) > 1 and not target.weak:
        # Several accepted pronunciations (Wiktionary gives /e.ʃil/ and
        # /ɛs.kil/ for "Eschyle"): the existing respelling says which one
        # was meant ("Esskil", hard ch), so the loop aims at that one.
        target.variants = [chosen_variant(target.variants, espeak_ipa(current, language))]
    result.target = asdict(target)
    human = entry is not None and entry.source == "user" and bool(entry.respelling or entry.ipa)

    if listener.phoneme_input:
        # The engine takes phonemes: the target itself is the candidate.
        for n, variant in enumerate(target.variants):
            attempt = await listener.attempt(
                job, target, variant, kind="ipa", origin="target", number=n
            )
            result.attempts.append(attempt)
            if attempt.score <= threshold:
                break
    else:
        # What is said today, then the word as written (it may need nothing).
        seeds = [(current, "current")] if current else []
        if job.word not in {c for c, _ in seeds}:
            seeds.append((job.word, "written"))
        for n, (candidate, origin) in enumerate(seeds):
            result.attempts.append(
                await listener.attempt(
                    job, target, candidate, kind="respelling", origin=origin, number=n
                )
            )
            # Today's spelling already passes: a take of the word as written
            # would only cost another minute of synthesis to learn nothing
            # the verdict needs.
            if result.attempts[-1].score <= threshold:
                break
        rounds = 0
        while llm and rounds < max_iter and min(a.score for a in result.attempts) > threshold:
            rounds += 1
            candidate = proposer(job.word, language, target, result.attempts)
            if not candidate:
                llm_silent = rounds == 1
                break
            result.attempts.append(
                await listener.attempt(
                    job,
                    target,
                    candidate,
                    kind="respelling",
                    origin="llm",
                    number=len(result.attempts),
                )
            )

    result.best = min(range(len(result.attempts)), key=lambda i: result.attempts[i].score)
    best = result.attempts[result.best]
    baseline = result.attempts[0]
    passes = best.score <= threshold
    better = best.score <= baseline.score - IMPROVEMENT_MARGIN
    if baseline.score <= threshold:
        # A spelling that passes is kept: two takes of the same text differ
        # by a few hundredths, so "slightly better" is noise, and swapping a
        # working spelling for it would only churn the lexicon.
        result.verdict = "ok"
        result.note = "Déjà dit juste ; rien à changer."
        best = baseline
        result.best = 0
    elif human:
        result.verdict = "proposal"
        result.note = (
            f"La graphie écrite à la main obtient {baseline.score:.2f} ; "
            f"« {best.candidate} » obtient {best.score:.2f}. Écoutez les deux et "
            "recopiez vous-même la meilleure dans lexicon.yaml : la boucle ne "
            "remplace jamais une décision humaine."
        )
    elif passes or better:
        result.verdict = "fixed" if passes else "improved"
        result.note = (
            f"« {best.candidate} » obtient {best.score:.2f} "
            f"(contre {baseline.score:.2f} pour « {baseline.candidate} »)."
        )
    else:
        result.verdict = "unresolved"
        result.note = (
            f"Le meilleur essai, « {best.candidate} », obtient encore "
            f"{best.score:.2f}. Écoutez les prises ; une graphie écrite à la main "
            "sera peut-être nécessaire."
        )
    if llm_silent and result.verdict == "unresolved":
        result.note += (
            " Le LLM local n'a rien proposé : son modèle est-il téléchargé ? "
            "(`ollama pull`, ou désignez-en un installé avec BEST_LLM_TEXT)."
        )
    if listener.phoneme_input and result.verdict == "ok" and not (entry and entry.ipa):
        # The engine was never given this IPA before: recording it changes
        # what is said from now on, which is a fix, not a no-op.
        result.verdict = "fixed"
        result.note = f"La cible /{best.candidate}/ sort juste ({best.score:.2f})."
    if target.weak and result.verdict in ("ok", "fixed", "improved"):
        result.note += (
            " La cible est espeak lisant la graphie actuelle : cela prouve que le "
            "moteur la lit comme prévu, pas que la graphie était la bonne."
        )

    if (
        verified_path is not None
        and result.verdict in ("fixed", "improved", "ok")
        and not human
        # The word as written only needs recording when it replaces a
        # spelling (the respelling turned out to hurt on this engine).
        and (best.origin != "written" or bool(current))
    ):
        key = f"{engine.lower()}:{language}:{job.word.casefold()}"
        record: dict[str, Any] = {
            "word": job.word,
            "score": best.score,
            "verified": best.score <= threshold,
            "target": " | ".join(target.variants),
            "target_source": target.source,
            "heard": best.takes[0].heard if best.takes else "",
            "date": _dt.date.today().isoformat(),
        }
        record["ipa" if best.kind == "ipa" else "respelling"] = best.candidate
        save_verified(verified_path, key, record)
        result.saved = True
    return result


def chosen_variant(variants: list[str], intended_ipa: str) -> str:
    """The accepted pronunciation closest to the one a respelling encodes.

    Parameters
    ----------
    variants : list of str
        Accepted IPA transcriptions.
    intended_ipa : str
        espeak's reading of the current respelling.

    Returns
    -------
    str
        The closest variant (the first one on a tie).

    Examples
    --------
    >>> chosen_variant(["e.ʃil", "ɛs.kil"], "ɛskil")
    'ɛs.kil'
    """
    intended = tokenize(intended_ipa)
    return min(variants, key=lambda v: align(intended, tokenize(v)).cost)


def phones_of(ipa: str) -> str:
    """Space-separated phones of an IPA string, as shown in reports.

    Parameters
    ----------
    ipa : str
        Any IPA.

    Returns
    -------
    str
        The tokenised phones joined by spaces.

    Examples
    --------
    >>> phones_of("ˈfaɪn.mən")
    'f a ɪ n m ə n'
    """
    return " ".join(tokenize(ipa))
