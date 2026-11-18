"""
The Ralph Eardrum Loop hears a word, scores it, and fixes its spelling.

Every promise the loop makes is checked here without a model, a network or
espeak: the phone distances that tell a right reading from a wrong one, the
web parsers that find the target, the client that never hammers a server,
the discovery of words the lexicon does not have yet, the verdicts, the
human-always-wins rule, and the sidecar every later synthesis reads.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import asyncio
import io
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from speaker_helper.eardrum import collect_jobs
from speaker_helper.eardrum.discover import discover
from speaker_helper.eardrum.ear import HeardPhone, collapse_ctc
from speaker_helper.eardrum.loop import (
    Attempt,
    Listener,
    Take,
    WordJob,
    chosen_variant,
    save_verified,
    slug,
    tune_word,
)
from speaker_helper.eardrum.phones import (
    align,
    phone_distance,
    sentence_distances,
    tokenize,
    word_distance,
)
from speaker_helper.eardrum.report import render_html, render_markdown
from speaker_helper.eardrum.targets import (
    PoliteClient,
    Target,
    TargetResolver,
    pick_for_word,
    wikipedia_lead_ipas,
    wiktionary_ipas,
)
from speaker_helper.lexicon import Lexicon, LexiconEntry, phonemise_with_lexicon

# ── 1. Phones: a right reading is near, a wrong one is far ──────────────────


def test_tokenize_drops_everything_that_is_not_a_segment() -> None:
    """Stress, length, dots, slashes, tone digits, aspiration: all gone."""
    assert tokenize("/ˈfaɪn.mən/") == ["f", "a", "ɪ", "n", "m", "ə", "n"]
    assert tokenize("onɡ5") == ["o", "n", "ɡ"]
    assert tokenize("tʰaː") == ["t", "a"]


def test_nasal_vowels_stay_nasal() -> None:
    """ɑ̃ is not ɑ: "banc" is not "bas"."""
    assert tokenize("bɑ̃") == ["b", "ɑ̃"]
    assert phone_distance("ɑ̃", "ɑ") >= 0.3


def test_neighbours_cost_little_and_strangers_cost_everything() -> None:
    """The feature table orders confusions the way an ear does."""
    assert phone_distance("e", "ɛ") < phone_distance("e", "u") < 1.0
    assert phone_distance("t", "d") < phone_distance("t", "s") < 1.0
    assert phone_distance("a", "k") == 1.0
    assert phone_distance("ʁ", "ɹ") == pytest.approx(0.1)


def test_alignment_is_an_edit_distance() -> None:
    """Identical sequences cost nothing; a dropped phone costs one."""
    assert align(list("abc"), list("abc")).cost == 0
    assert align(list("ac"), list("abc")).cost == 1.0
    # A mute e dropped is half a mistake, not a whole one.
    assert align(["l", "a"], ["l", "ə", "a"]).cost == 0.5


def test_the_word_is_found_inside_its_carrier_and_judged_alone() -> None:
    """Measured on chatterbox French: right ≈ 0.06–0.10, wrong ≈ 0.39."""
    prefix, suffix = "ʒəvupaʁldə", "oʒuʁdɥi"
    right = "ʒ y v uː p a d ə s a i n m a n u ʒ uː d".split()
    wrong = "ʒ y v uː p a d ə f ɛ n m ɑ̃ u ʒ uː d".split()
    good = word_distance(right, prefix, ["faɪnmən"], suffix)
    bad = word_distance(wrong, prefix, ["faɪnmən"], suffix)
    assert good.score < 0.25 < bad.score
    assert good.heard == ["s", "a", "i", "n", "m", "a", "n"]


def test_the_best_of_several_accepted_pronunciations_wins() -> None:
    """Wiktionary lists variants; matching any one of them is right."""
    heard = "ɛ s k i l".split()
    assert word_distance(heard, "", ["e.ʃil", "ɛs.kil"], "").score == 0


def test_word_distance_refuses_an_empty_target() -> None:
    """No target, no judgement."""
    with pytest.raises(ValueError):
        word_distance(["a"], "", [], "")


def test_every_word_of_a_sentence_gets_its_own_score() -> None:
    """The listen-all pass blames the word that went wrong, not its neighbours."""
    heard = "l a m e z ɔ̃ k i ʁ i t".split()
    scores = sentence_distances(heard, ["la", "mɛzɔ̃", "ki", "ʁi"])
    assert scores[0] == 0 and scores[2] == 0
    assert scores[1] < 0.25


# ── 2. The ear's decoding ───────────────────────────────────────────────────


def test_ctc_collapse_merges_repeats_and_keeps_spans() -> None:
    """Greedy CTC: one token per run, blanks dropped, frames kept for clips."""
    assert collapse_ctc([0, 3, 3, 0, 3, 4, 4], blank=0) == [(3, 1, 3), (3, 4, 5), (4, 5, 7)]


# ── 3. Targets: where the right pronunciation comes from ────────────────────


def test_french_wiktionary_gives_every_variant_with_its_language() -> None:
    """``{{pron|…|…|fr}}``: transcriptions first, language last."""
    text = "{{pron|e.ʃil|ɛs.kil|fr}} … {{pron||fr}} {{pron|ˈfaɪn.mən|lang=en}}"
    assert wiktionary_ipas(text, "fr") == [("e.ʃil", "fr"), ("ɛs.kil", "fr"), ("ˈfaɪn.mən", "en")]


def test_english_wiktionary_skips_labels() -> None:
    """``{{IPA|en|/…/|a=UK}}``: language first, labels ignored."""
    text = "{{IPA|en|/ˈfaɪnmən/|a=US}} {{IPA|en|/kæʃ/|UK}}"
    assert wiktionary_ipas(text, "en") == [("ˈfaɪnmən", "en"), ("kæʃ", "en")]


def test_wikipedia_ipac_pieces_are_joined() -> None:
    """``{{IPAc-en|ˈ|f|aɪ|…}}`` is one transcription cut into phonemes."""
    lead = "'''Richard Feynman''' ({{IPAc-en|ˈ|f|aɪ|n|m|ə|n}}; 1918–1988)"
    assert wikipedia_lead_ipas(lead, "en") == [("ˈfaɪnmən", "en")]
    assert wikipedia_lead_ipas("{{API|ɡʁas}}", "fr") == [("ɡʁas", "fr")]


def test_only_the_words_own_part_of_a_full_name_is_kept() -> None:
    """A lead transcribes the title; the target is the word's chunk, or nothing."""
    assert pick_for_word("ˈrɪtʃərd ˈfaɪnmən", "Feynman", "Richard Feynman") == "ˈfaɪnmən"
    assert pick_for_word("vɑ̃ ɡɔɡ", "Van Gogh", "Vincent van Gogh") == "vɑ̃ ɡɔɡ"
    assert pick_for_word("vɛ̃sɑ̃ vɑ̃ ɡɔɡ", "Van Gogh", "Vincent van Gogh") == "vɑ̃ ɡɔɡ"
    # Two chunks for a three-word title, asked for the first name: ambiguous.
    assert pick_for_word("vɑ̃ ɡɔɡ", "Vincent", "Vincent van Gogh") == ""


class _FakeResponse:
    """A urlopen() answer carrying a JSON body."""

    def __init__(self, body: bytes) -> None:
        """Keep the body."""
        self.body = body

    def read(self) -> bytes:
        """The body."""
        return self.body

    def __enter__(self) -> _FakeResponse:
        """Context-manager entry."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Context-manager exit."""


def _http_error(code: int, retry_after: str = "") -> urllib.error.HTTPError:
    """An HTTPError with an optional Retry-After header."""
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("https://x", code, "refused", headers, io.BytesIO())  # type: ignore[arg-type]


def test_the_client_backs_off_with_jitter_and_honours_retry_after(monkeypatch) -> None:
    """A 429 is waited out (Retry-After as a floor), then the request succeeds."""
    answers = [_http_error(429, "7"), _FakeResponse(b'{"ok": 1}')]

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        """Pop the next scripted answer, checking the User-Agent is honest."""
        assert "speaker-helper-eardrum" in request.get_header("User-agent")
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    slept: list[float] = []
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = PoliteClient(sleep=slept.append)
    assert client.get_json("https://fr.wiktionary.org/w/api.php", {}) == {"ok": 1}
    # At least one pause is the Retry-After floor.
    assert any(s >= 7 for s in slept)


def test_the_client_stops_asking_a_host_that_keeps_refusing(monkeypatch) -> None:
    """After every attempt is refused, the host is left alone for the run."""
    calls: list[str] = []

    def refuse(request, timeout):  # type: ignore[no-untyped-def]
        """Always 503."""
        calls.append(request.full_url)
        raise _http_error(503)

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    client = PoliteClient(sleep=lambda s: None, attempts=3)
    assert client.get_json("https://en.wikipedia.org/w/api.php", {}) is None
    assert len(calls) == 3
    assert client.get_json("https://en.wikipedia.org/w/api.php", {"x": 1}) is None
    assert len(calls) == 3  # no fourth request


def test_the_humans_ipa_beats_every_other_source(tmp_path) -> None:
    """An entry's own ``ipa:`` is final: no lookup happens at all."""
    resolver = TargetResolver(tmp_path / "t.yaml", client=_NoNetwork())
    target = resolver.resolve("Grasse", "fr", ipa="ɡʁas")
    assert target == Target(variants=["ɡʁas"], language="fr", source="lexicon")


class _NoNetwork(PoliteClient):
    """A client that fails the test if it is ever used."""

    def get_json(self, url, params):  # type: ignore[no-untyped-def]
        """Refuse to be called."""
        raise AssertionError(f"unexpected request to {url}")


def test_a_looked_up_word_is_never_looked_up_again(tmp_path, monkeypatch) -> None:
    """The cache answers the second time, even with the network gone."""
    pages = {
        ("fr.wiktionary.org", "Eschyle"): ("{{pron|e.ʃil|ɛs.kil|fr}}", "Eschyle"),
    }

    def fake_wikitext(client, host, page):  # type: ignore[no-untyped-def]
        """Serve the scripted pages; anything else does not exist."""
        return pages.get((host, page), ("", ""))

    monkeypatch.setattr("speaker_helper.eardrum.targets._wikitext", fake_wikitext)
    cache = tmp_path / "targets.yaml"
    first = TargetResolver(cache).resolve("Eschyle", "fr")
    assert first is not None and first.source == "wiktionary"
    assert first.variants == ["e.ʃil", "ɛs.kil"]
    second = TargetResolver(cache, client=_NoNetwork()).resolve("Eschyle", "fr")
    assert second == first


def test_without_any_source_the_target_is_espeak_and_says_it_is_weak(tmp_path) -> None:
    """espeak reading the respelling proves consistency only, and is flagged."""
    resolver = TargetResolver(tmp_path / "t.yaml", web=False)
    target = resolver.resolve("Sutton", "fr", respelling="Seutone", espeak=lambda t, lang: "søtɔn")
    assert target is not None and target.weak and target.source == "espeak"
    assert resolver.resolve("Sutton", "fr") is None


def test_optional_sounds_give_two_accepted_readings(tmp_path, monkeypatch) -> None:
    """``k(j)uː``: with or without the /j/, both are right (Kubernetes)."""
    monkeypatch.setattr(
        "speaker_helper.eardrum.targets._wikitext",
        lambda c, h, p: (
            ("{{IPA|en|/k(j)uːbəˈnɛtɪs/}}", p) if h == "en.wiktionary.org" else ("", "")
        ),
    )
    target = TargetResolver(tmp_path / "t.yaml").resolve("Kubernetes", "fr")
    assert target is not None
    assert target.variants == ["kjuːbəˈnɛtɪs", "kuːbəˈnɛtɪs"]


def test_a_dotted_answer_is_not_a_respelling() -> None:
    """Syllable dots from the LLM never reach the engine; a final dot is trimmed."""
    from speaker_helper.lexicon import _validate_respelling

    assert _validate_respelling("Ours.tœ.rcheur.", "Worcestershire") == ""
    assert _validate_respelling("Nitche.", "Nietzsche") == "Nitche"


def test_the_respelling_says_which_variant_was_meant() -> None:
    """ "Esskil" picks /ɛs.kil/ over /e.ʃil/ — the hard ch the lexicon wants."""
    assert chosen_variant(["e.ʃil", "ɛs.kil"], "ɛskil") == "ɛs.kil"


# ── 4. Discovery: the words not in the lexicon yet ──────────────────────────


def test_discovery_finds_names_acronyms_and_brands_but_not_sentence_openers() -> None:
    """The capital that opens a sentence proves nothing; the others do."""
    found = discover("Hier, Feynman parlait de l'ONU sur GitHub. Le chat dort.", "fr")
    assert [(d.word, d.reasons) for d in found] == [
        ("Feynman", ["proper"]),
        ("ONU", ["acronym"]),
        ("GitHub", ["mixed"]),
    ]


def test_a_name_in_several_words_is_one_phrase_unless_said_apart() -> None:
    """ "Van Gogh" stays whole; "Richard Feynman" gives way to "Feynman"."""
    found = {
        d.word: d for d in discover("Il cite Van Gogh. Il cite Richard Feynman et Feynman.", "fr")
    }
    assert "Van Gogh" in found
    assert "Richard Feynman" not in found
    assert found["Feynman"].count == 2


def test_words_the_lexicon_knows_are_left_to_the_lexicon() -> None:
    """Discovery only lists what nobody wrote down yet."""
    found = discover("Il cite Feynman et Sutton.", "fr", known=lambda w: w == "Sutton")
    assert [d.word for d in found] == ["Feynman"]


def test_espeak_decides_which_plain_words_are_foreign() -> None:
    """A lowercase English word in French text is caught by espeak's switch."""
    found = discover("On garde le template ici.", "fr", foreign=lambda ws, lang: {"template"})
    assert [(d.word, d.reasons) for d in found] == [("template", ["foreign"])]


# ── 5. Which words a run checks ─────────────────────────────────────────────


def _lexicon() -> Lexicon:
    """A small lexicon: one hand-written entry, one packaged one."""
    return Lexicon(
        [
            LexiconEntry(word="Sutton", language="fr", respelling="Seutone", source="user"),
            LexiconEntry(word="Eschyle", language="fr", respelling="Esskil", source="builtin"),
        ]
    )


def test_without_a_text_every_lexicon_entry_is_checked() -> None:
    """The default run audits the whole lexicon of the language."""
    jobs = collect_jobs(_lexicon(), "fr")
    assert sorted(j.word for j in jobs) == ["Eschyle", "Sutton"]


def test_with_a_text_its_lexicon_words_and_its_new_words_are_checked() -> None:
    """Lexicon words found in the text, plus discovered ones; nothing twice."""
    jobs = collect_jobs(_lexicon(), "fr", text="Sutton a lu Feynman. Feynman aussi.")
    assert [(j.word, j.reasons) for j in jobs] == [
        ("Sutton", ["lexicon"]),
        ("Feynman", ["proper"]),
    ]


# ── 6. One word through the loop ────────────────────────────────────────────


class _ScriptedListener(Listener):
    """A listener whose engine-and-ear is a table: candidate → score."""

    def __init__(self, scores: dict[str, float], *, phoneme_input: bool = False) -> None:
        """Keep the table; nothing is synthesised."""
        self.scores = scores
        self._phoneme_input = phoneme_input
        self.said: list[str] = []

    @property
    def phoneme_input(self) -> bool:
        """Whether the scripted engine takes IPA."""
        return self._phoneme_input

    async def attempt(self, job, target, candidate, *, kind, origin, number):  # type: ignore[no-untyped-def]
        """Score ``candidate`` from the table (unknown candidates are far)."""
        self.said.append(candidate)
        score = self.scores.get(candidate, 0.9)
        take = Take(carrier="{w}", score=score, heard=candidate.lower(), heard_sentence="")
        return Attempt(candidate=candidate, kind=kind, origin=origin, score=score, takes=[take])


def _resolver(tmp_path: Path, variants: list[str]) -> TargetResolver:
    """A resolver with a pre-filled cache, so no request is ever made."""
    cache = tmp_path / "targets.yaml"
    cache.write_text(
        yaml.safe_dump(
            {
                f"fr:{w}": [[v, "fr", "wiktionary", "https://x"] for v in variants]
                for w in ("feynman", "sutton", "eschyle", "goodhart", "krug")
            }
        ),
        encoding="utf-8",
    )
    return TargetResolver(cache, client=_NoNetwork())


def _tune(job, listener, resolver, **kwargs):  # type: ignore[no-untyped-def]
    """Run :func:`tune_word` synchronously with espeak stubbed out."""
    import speaker_helper.eardrum.espeak as espeak

    original = espeak.espeak_ipa
    espeak.espeak_ipa = lambda text, language: text.lower()
    try:
        return asyncio.run(tune_word(job, listener, resolver, engine="chatterbox", **kwargs))
    finally:
        espeak.espeak_ipa = original


def test_a_word_already_said_right_is_left_alone(tmp_path) -> None:
    """No LLM call, no sidecar write when the word as written passes."""
    listener = _ScriptedListener({"Feynman": 0.1})
    result = _tune(
        WordJob("Feynman", "fr"),
        listener,
        _resolver(tmp_path, ["fajnman"]),
        proposer=lambda *a: pytest.fail("the LLM must not be asked"),
        verified_path=tmp_path / "v.yaml",
    )
    assert result.verdict == "ok" and not result.saved
    assert not (tmp_path / "v.yaml").exists()


def test_a_spelling_that_already_passes_costs_one_take(tmp_path) -> None:
    """Today's respelling passes: the word as written is not even tried."""
    listener = _ScriptedListener({"Faïnemane": 0.08})
    result = _tune(
        WordJob("Feynman", "fr"),
        listener,
        _resolver(tmp_path, ["fajnman"]),
        current="Faïnemane",
        proposer=lambda *a: pytest.fail("the LLM must not be asked"),
    )
    assert listener.said == ["Faïnemane"]
    assert result.verdict == "ok"


def test_a_passing_spelling_is_never_swapped_for_a_slightly_better_one(tmp_path) -> None:
    """Measured on Goodhart: 0.14 for the respelling, 0.08 as written — noise."""
    listener = _ScriptedListener({"Goudharte": 0.14, "Goodhart": 0.08})
    sidecar = tmp_path / "v.yaml"
    result = _tune(
        WordJob("Goodhart", "fr"),
        listener,
        _resolver(tmp_path, ["ɡudaʁt"]),
        current="Goudharte",
        verified_path=sidecar,
    )
    assert result.verdict == "ok"
    assert result.attempts[result.best].candidate == "Goudharte"


def test_a_respelling_that_hurts_gives_way_to_the_word_as_written(tmp_path) -> None:
    """When only the plain word passes, the engine is told to say it as written."""
    listener = _ScriptedListener({"Kroug": 0.5, "Krug": 0.05})
    sidecar = tmp_path / "v.yaml"
    entry = LexiconEntry("Krug", "fr", respelling="Kroug", source="builtin")
    result = _tune(
        WordJob("Krug", "fr", entry=entry),
        listener,
        _resolver(tmp_path, ["kʁuɡ"]),
        current="Kroug",
        verified_path=sidecar,
    )
    assert result.verdict == "fixed" and result.saved
    assert yaml.safe_load(sidecar.read_text())["chatterbox:fr:krug"]["respelling"] == "Krug"


def test_the_llm_is_shown_the_history_and_the_best_attempt_is_kept(tmp_path) -> None:
    """Proposals continue until one passes; the winner is saved for the engine."""
    seen: list[list[str]] = []

    def proposer(word, language, target, history):  # type: ignore[no-untyped-def]
        """Propose a worse spelling first, then the right one."""
        seen.append([a.candidate for a in history])
        return ["Fènemane", "Faïnemane"][len(seen) - 1]

    listener = _ScriptedListener({"Feynman": 0.4, "Fènemane": 0.5, "Faïnemane": 0.08})
    sidecar = tmp_path / "lexicon.yaml.eardrum.yaml"
    result = _tune(
        WordJob("Feynman", "fr"),
        listener,
        _resolver(tmp_path, ["fajnman"]),
        proposer=proposer,
        verified_path=sidecar,
    )
    assert seen == [["Feynman"], ["Feynman", "Fènemane"]]
    assert result.verdict == "fixed" and result.saved
    assert result.attempts[result.best].candidate == "Faïnemane"
    record = yaml.safe_load(sidecar.read_text(encoding="utf-8"))["chatterbox:fr:feynman"]
    assert record["respelling"] == "Faïnemane" and record["verified"] is True


def test_the_loop_stops_after_max_iter(tmp_path) -> None:
    """A word that never passes costs at most ``max_iter`` proposals."""
    count = iter(range(100))
    listener = _ScriptedListener({})
    result = _tune(
        WordJob("Feynman", "fr"),
        listener,
        _resolver(tmp_path, ["fajnman"]),
        proposer=lambda *a: f"essai{next(count)}",
        max_iter=3,
    )
    assert len(result.attempts) == 1 + 3
    assert result.verdict == "unresolved"


def test_a_silent_llm_is_reported_not_hidden(tmp_path) -> None:
    """No proposal at all: the note says where to look (the model, Ollama)."""
    result = _tune(
        WordJob("Feynman", "fr"),
        _ScriptedListener({}),
        _resolver(tmp_path, ["fajnman"]),
        proposer=lambda *a: "",
    )
    assert result.verdict == "unresolved" and "BEST_LLM_TEXT" in result.note


def test_the_proposal_prompt_says_what_went_wrong() -> None:
    """The model is told which phones were wrong, extra or missing."""
    from speaker_helper.eardrum.loop import _prompt

    history = [
        Attempt("Nitcherche", "respelling", "llm", 0.3, [Take("", 0.3, "n i t ʃ ɛ ʁ ʃ", "")])
    ]
    prompt = _prompt("Nietzsche", "fr", Target(["ˈniːtʃə"], "de", "wiktionary"), history)
    assert "extra /ʁ/" in prompt and "/ɛ/ said where /ə/ was wanted" in prompt
    assert "/tʃ/ tch" in prompt  # the French spelling guide


def test_a_hand_written_spelling_is_never_overwritten(tmp_path) -> None:
    """The human loses the score and keeps the decision: a proposal, no write."""
    entry = LexiconEntry(word="Sutton", language="fr", respelling="Seutone", source="user")
    listener = _ScriptedListener({"Seutone": 0.6, "Seuttone": 0.1})
    sidecar = tmp_path / "v.yaml"
    result = _tune(
        WordJob("Sutton", "fr", entry=entry),
        listener,
        _resolver(tmp_path, ["sʌtən"]),
        current="Seutone",
        proposer=lambda *a: "Seuttone",
        verified_path=sidecar,
    )
    assert result.verdict == "proposal" and not result.saved
    assert "Seuttone" in result.note
    assert not sidecar.exists()


def test_a_phoneme_engine_is_checked_with_the_target_itself(tmp_path) -> None:
    """kokoro takes IPA: nothing to respell, the target is tried and recorded."""
    listener = _ScriptedListener({"fajnman": 0.05}, phoneme_input=True)
    sidecar = tmp_path / "v.yaml"
    result = _tune(
        WordJob("Feynman", "fr"),
        listener,
        _resolver(tmp_path, ["fajnman"]),
        verified_path=sidecar,
        proposer=lambda *a: pytest.fail("no respelling for a phoneme engine"),
    )
    assert result.verdict == "fixed"
    assert listener.said == ["fajnman"]
    assert yaml.safe_load(sidecar.read_text())["chatterbox:fr:feynman"]["ipa"] == "fajnman"


def test_no_target_means_no_judgement(tmp_path) -> None:
    """A word with no IPA anywhere is reported, not guessed at."""
    resolver = TargetResolver(tmp_path / "t.yaml", web=False)
    result = _tune(WordJob("Zorglub", "fr"), _ScriptedListener({}), resolver)
    assert result.verdict == "no-target" and "ipa:" in result.note


def test_the_listener_says_the_candidate_and_cuts_the_words_clip(tmp_path) -> None:
    """Real Listener: the candidate reaches the engine; the take is written."""
    import numpy as np
    import soundfile as sf

    spoken: list[str] = []

    class Engine:
        """A respelling-tier engine."""

        LEXICON_TIER = "respelling"

    class Speaker:
        """Applies its lexicon like the real Speaker, returns a second of silence."""

        engine = Engine()
        lexicon: Lexicon | None = None

        async def say(self, text, language=None):  # type: ignore[no-untyped-def]
            """Record what the engine would be handed."""
            spoken.append(self.lexicon.respell(text, language) if self.lexicon else text)
            buffer = io.BytesIO()
            sf.write(buffer, np.zeros(16000, dtype="float32"), 16000, format="WAV")
            return SimpleNamespace(wav_bytes=buffer.getvalue())

    class Ear:
        """Hears the word part of the last sentence, one phone per letter."""

        def hear(self, wav_bytes):  # type: ignore[no-untyped-def]
            """Pretend the respelling's letters are its phones."""
            return [HeardPhone(c, i * 0.05, i * 0.05 + 0.05) for i, c in enumerate("fajnman")]

    listener = Listener(Speaker(), Ear(), lambda text, lang: "", tmp_path)
    target = Target(variants=["fajnman"], language="fr", source="wiktionary")
    attempt = asyncio.run(
        listener.attempt(
            WordJob("Feynman", "fr"), target, "Faïnemane", kind="respelling", origin="llm", number=2
        )
    )
    assert spoken[0] == "Je vous parle de Faïnemane aujourd'hui."
    assert attempt.score == 0
    assert (tmp_path / attempt.takes[0].clip).is_file()
    assert attempt.takes[0].audio == "audio/feynman/a2-c0.wav"


# ── 7. The sidecar every later synthesis reads ──────────────────────────────


def test_a_verified_spelling_applies_to_its_engine_only(tmp_path) -> None:
    """What chatterbox reads right, kyutai may not: the key carries the engine."""
    sidecar = tmp_path / "lexicon.yaml.eardrum.yaml"
    save_verified(sidecar, "chatterbox:fr:feynman", {"word": "Feynman", "respelling": "Faïnemane"})
    lexicon = Lexicon([])
    lexicon.load_verified(sidecar)
    text = "Feynman a raison."
    assert lexicon.respell(text, "fr", engine="chatterbox") == "Faïnemane a raison."
    # Another engine: the word is said as written, and no LLM is asked about
    # a word nobody listed.
    lexicon.llm_enabled = True
    assert lexicon.respell(text, "fr", engine="kyutai") == text


def test_the_human_still_wins_over_a_verified_spelling(tmp_path) -> None:
    """A hand-written respelling is applied even when the sidecar disagrees."""
    sidecar = tmp_path / "v.yaml"
    save_verified(sidecar, "chatterbox:fr:sutton", {"respelling": "Seuttone"})
    lexicon = Lexicon([LexiconEntry("Sutton", "fr", respelling="Seutone", source="user")])
    lexicon.load_verified(sidecar)
    assert lexicon.respell("Sutton", "fr", engine="chatterbox") == "Seutone"


def test_a_packaged_spelling_gives_way_to_a_verified_one(tmp_path) -> None:
    """Built-in respellings were measured with espeak, not with the engine."""
    sidecar = tmp_path / "v.yaml"
    save_verified(sidecar, "chatterbox:fr:eschyle", {"respelling": "Ès-kile"})
    lexicon = Lexicon([LexiconEntry("Eschyle", "fr", respelling="Esskil", source="builtin")])
    lexicon.load_verified(sidecar)
    assert lexicon.respell("Eschyle", "fr", engine="chatterbox") == "Ès-kile"
    assert lexicon.respell("Eschyle", "fr", engine="kyutai") == "Esskil"


def test_a_phoneme_engine_uses_verified_ipa(tmp_path) -> None:
    """kokoro splices the IPA the loop heard it say right."""
    sidecar = tmp_path / "v.yaml"
    save_verified(sidecar, "kokoro:fr:feynman", {"ipa": "fajnman"})
    lexicon = Lexicon([])
    lexicon.load_verified(sidecar)
    out = phonemise_with_lexicon("Feynman", "fr", lexicon, lambda s: f"<{s}>", engine="kokoro")
    assert out == "fajnman"


def test_the_sidecar_is_found_even_without_a_lexicon_file(tmp_path, monkeypatch) -> None:
    """A project with no lexicon.yaml still keeps what the loop heard."""
    from speaker_helper import Settings
    from speaker_helper.lexicon import load_lexicon, verified_path_for

    monkeypatch.chdir(tmp_path)
    settings = Settings.from_mapping({"lexicon": {"builtin": False}})
    save_verified(verified_path_for(settings), "chatterbox:fr:feynman", {"respelling": "Faïnemane"})
    lexicon = load_lexicon(settings)
    assert lexicon is not None
    assert lexicon.respell("Feynman", "fr", engine="chatterbox") == "Faïnemane"


# ── 8. Report and command line ──────────────────────────────────────────────


def test_the_report_escapes_and_shows_every_word() -> None:
    """HTML and Markdown both name each word, verdict and best spelling."""
    from speaker_helper.eardrum.loop import WordResult

    result = WordResult(
        word="<Feynman>",
        language="fr",
        engine="chatterbox",
        target={"variants": ["fajnman"], "source": "wikipedia", "url": "https://x", "weak": False},
        attempts=[
            Attempt("Faïnemane", "respelling", "llm", 0.08, [Take("{w}", 0.08, "f a j n", "")])
        ],
        best=0,
        verdict="fixed",
        saved=True,
    )
    meta = {"engine": "chatterbox", "language": "fr", "threshold": 0.25, "date": "2026-11-17"}
    page = render_html([result], meta)
    assert "&lt;Feynman&gt;" in page and "<Feynman>" not in page
    assert "corrigé" in page and "Faïnemane" in page
    assert "| <Feynman> | corrigé ✓ |" in render_markdown([result], meta)


def test_slugs_are_safe_folder_names() -> None:
    """Clips live in one folder per word."""
    assert slug("Van Gogh") == "van-gogh" and slug("???") == "word"


def test_the_command_reports_and_exits_on_what_is_left(monkeypatch, tmp_path) -> None:
    """Exit 0 when every word is right, 1 when some are not, 2 on misuse."""
    from click.testing import CliRunner

    from speaker_helper.cli import cli
    from speaker_helper.eardrum import EardrumReport
    from speaker_helper.eardrum.loop import WordResult

    verdicts = {"value": "fixed"}

    def fake_run(settings, **kwargs):  # type: ignore[no-untyped-def]
        """Return one word with the scripted verdict."""
        result = WordResult("Feynman", "fr", "chatterbox", verdict=verdicts["value"])
        return EardrumReport(results=[result], html=tmp_path / "index.html")

    monkeypatch.setattr("speaker_helper.eardrum.run_eardrum", fake_run)
    runner = CliRunner()
    assert runner.invoke(cli, ["eardrum", "--words", "Feynman"]).exit_code == 0
    verdicts["value"] = "unresolved"
    assert runner.invoke(cli, ["eardrum", "--words", "Feynman"]).exit_code == 1
    assert runner.invoke(cli, ["eardrum", "--listen-all"]).exit_code == 2


def test_the_ear_can_be_installed_with_pinned_sizes() -> None:
    """``install-voice --engine eardrum`` knows every file and its exact size."""
    from speaker_helper.install import EARDRUM_FILES, INSTALLABLE

    assert "eardrum" in INSTALLABLE
    assert dict(EARDRUM_FILES)["pytorch_model.bin"] == 1_263_535_127
