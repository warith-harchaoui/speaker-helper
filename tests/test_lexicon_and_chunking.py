"""
Tests for the pronunciation lexicon, long-text chunking, and language routing.

Three features landed together and are tested together because they share one
contract — "integrated by default, deterministic once derived":

* **Lexicon** (:mod:`speaker_helper.lexicon`) — per-word pronunciation
  overrides: IPA spliced by phoneme backends, respellings for the others,
  missing respellings derived once by the local LLM (mocked here) and cached.
* **Chunking** (:mod:`speaker_helper.chunking`) — long texts cut at sentence
  groups; the LLM only places boundaries and its answer is structurally
  validated, so text integrity never depends on it.
* **Routing** (:mod:`speaker_helper.router`) — offline English goes to
  chatterbox (Turbo) and other languages to its multilingual model; offline
  French goes to chatterbox too, but by the owner's 2026-10-28 ratification
  rather than by the quality argmax, and the router must declare the override
  instead of hiding it. Every proposed engine maps to a backend that can
  serve it.

Every LLM call is monkeypatched: CI has no Ollama, and these tests must stay
deterministic either way.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

import speaker_helper.chunking as chunking_mod
import speaker_helper.lexicon as lexicon_mod
from speaker_helper.chunking import (
    _validate_group_sizes,
    chunk_long_text,
    greedy_group_sizes,
)
from speaker_helper.config import Settings
from speaker_helper.engine import available_backends
from speaker_helper.eval.priors import engine_quality_prior
from speaker_helper.lexicon import (
    Lexicon,
    _validate_respelling,
    load_lexicon,
    phonemise_with_lexicon,
)
from speaker_helper.router import ENGINE_BACKENDS, RouteRequest, default_operating_points, route
from speaker_helper.speaker import Speaker

# ---------------------------------------------------------------------------
# Lexicon: matching
# ---------------------------------------------------------------------------


def _lexicon() -> Lexicon:
    """A small in-memory lexicon exercising every entry shape."""
    return Lexicon.from_mapping(
        {
            "entries": [
                # IPA-only entry (the deterministic tier's input).
                {"word": "Grasse", "language": "fr", "ipa": "ɡʁas"},
                # Hand-written respelling (the universal tier's input).
                {"word": "GitHub", "language": "fr", "respelling": "guite-heube"},
                # Wildcard entry: applies to every language.
                {"word": "SQL", "language": "*", "respelling": "ess-kyou-elle"},
                # Neither: would need the (mocked) LLM.
                {"word": "RGPD", "language": "fr"},
            ]
        }
    )


def test_matching_is_case_insensitive_and_bounded() -> None:
    """Words match on boundaries whatever their casing, never inside words."""
    lex = _lexicon()
    out = lex.respell("github GITHUB sousgithub regithub", "fr")
    # Both standalone spellings are replaced; the embedded ones are not.
    assert out == "guite-heube guite-heube sousgithub regithub"


def test_exact_language_beats_wildcard_and_wrong_language_is_inert() -> None:
    """A French-only entry does nothing in English; wildcards work everywhere."""
    lex = _lexicon()
    # GitHub's entry is French-only: English text keeps the word as written.
    assert lex.respell("Open GitHub now.", "en") == "Open GitHub now."
    # SQL is a wildcard: it is respelled in both languages.
    assert "ess-kyou-elle" in lex.respell("la base SQL", "fr")
    assert "ess-kyou-elle" in lex.respell("the SQL table", "en")


def test_split_preserves_every_character_in_order() -> None:
    """split() is a partition of the text — nothing lost, nothing reordered."""
    lex = _lexicon()
    text = "Vive l'ONU, GitHub et Grasse !"
    pieces = lex.split(text, "fr")
    # Concatenating the pieces must reproduce the input exactly: the IPA tier
    # relies on this to never drop or duplicate a character.
    assert "".join(chunk for chunk, _ in pieces) == text


# ---------------------------------------------------------------------------
# Lexicon: the respelling tier and its (mocked) LLM derivation
# ---------------------------------------------------------------------------


def test_missing_respelling_is_derived_once_and_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The LLM runs at most once per word; its answer persists to the sidecar."""
    # A lexicon file whose RGPD entry has neither ipa nor respelling.
    file = tmp_path / "lexicon.yaml"
    file.write_text(
        yaml.safe_dump({"entries": [{"word": "RGPD", "language": "fr"}]}),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_llm(word: str, language: str, *, ipa: str = "") -> str:
        calls.append(word)
        return "èr-jé-pé-dé"

    monkeypatch.setattr(lexicon_mod, "_llm_respelling", fake_llm)
    lex = Lexicon.load(file)
    # Two uses, one derivation: the entry remembers its answer.
    assert lex.respell("le RGPD", "fr") == "le èr-jé-pé-dé"
    assert lex.respell("encore le RGPD", "fr") == "encore le èr-jé-pé-dé"
    assert calls == ["RGPD"]
    # The sidecar cache now holds the derivation, so a *fresh* lexicon needs
    # no LLM at all — this is the "deterministic and offline after the first
    # derivation" promise.
    monkeypatch.setattr(lexicon_mod, "_llm_respelling", lambda *a, **k: pytest.fail("re-asked"))
    fresh = Lexicon.load(file)
    assert fresh.respell("le RGPD", "fr") == "le èr-jé-pé-dé"
    cache = yaml.safe_load((tmp_path / "lexicon.yaml.llm-cache.yaml").read_text())
    assert cache == {"fr:rgpd": "èr-jé-pé-dé"}


def test_llm_failure_leaves_the_word_and_asks_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No LLM → the word is spoken as written, and not re-asked per sentence."""
    calls: list[str] = []

    def failing_llm(word: str, language: str, *, ipa: str = "") -> str:
        calls.append(word)
        return ""

    monkeypatch.setattr(lexicon_mod, "_llm_respelling", failing_llm)
    lex = Lexicon.from_mapping({"entries": [{"word": "RGPD", "language": "fr"}]})
    assert lex.respell("le RGPD", "fr") == "le RGPD"
    assert lex.respell("le RGPD encore", "fr") == "le RGPD encore"
    # One failure is remembered; synthesis does not pay one timeout per call.
    assert calls == ["RGPD"]


def test_validate_respelling_rejects_prose() -> None:
    """Only answers shaped like a respelling are trusted."""
    # Clean answers pass, with quotes/whitespace stripped.
    assert _validate_respelling(" au-haine-u \n", "ONU") == "au-haine-u"
    # Chatty answers, multi-line answers, and explanations are refused.
    assert _validate_respelling("Sure! Here it is: au-haine-u", "ONU") == ""
    assert _validate_respelling("a\nb", "ONU") == ""
    assert _validate_respelling("<think>hmm</think>onu", "ONU") == "onu"
    assert _validate_respelling("", "ONU") == ""


# ---------------------------------------------------------------------------
# Lexicon: the IPA tier
# ---------------------------------------------------------------------------


def test_phonemise_with_lexicon_splices_ipa_verbatim() -> None:
    """Matched words contribute their stated phonemes; the rest is phonemised."""
    lex = _lexicon()
    # A fake phonemiser that wraps chunks, so the splice points are visible.
    out = phonemise_with_lexicon("Bienvenue à Grasse.", "fr-fr", lex, lambda s: f"[{s.strip()}]")
    assert "ɡʁas" in out
    assert "[Bienvenue à]" in out
    # No match → the single-call fast path returns the plain phonemisation.
    assert phonemise_with_lexicon("Rien ici.", "fr-fr", lex, lambda s: f"[{s}]") == "[Rien ici.]"
    # No lexicon at all degrades to the same thing.
    assert phonemise_with_lexicon("Rien.", "fr-fr", None, lambda s: f"[{s}]") == "[Rien.]"


def test_respelling_only_entries_reach_the_ipa_tier_through_phonemisation() -> None:
    """An entry with only a respelling is phonemised from that respelling."""
    lex = _lexicon()
    out = phonemise_with_lexicon("Va sur GitHub.", "fr-fr", lex, lambda s: f"[{s.strip()}]")
    # The phonemiser received the respelling, not the original word.
    assert "[guite-heube]" in out


# ---------------------------------------------------------------------------
# Lexicon: loading from settings (the integrated-by-default wiring)
# ---------------------------------------------------------------------------


def test_load_lexicon_resolution_and_switches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Path resolution and the enabled/llm switches behave as documented."""
    file = tmp_path / "lex.yaml"
    file.write_text(
        yaml.safe_dump({"llm": True, "entries": [{"word": "SQL", "respelling": "x"}]}),
        encoding="utf-8",
    )
    # An explicit path loads, and the settings-level llm switch wins over the
    # file's own `llm: true`.
    s = Settings.from_mapping({"lexicon": {"path": str(file), "llm": False}})
    lex = load_lexicon(s)
    assert lex is not None and lex.llm_enabled is False
    # enabled: false turns the whole feature off regardless of the file.
    disabled = Settings.from_mapping({"lexicon": {"path": str(file), "enabled": False}})
    assert load_lexicon(disabled) is None
    # No configured path and no ./lexicon.yaml → the BUILT-IN per-language
    # entries still apply (that is the point of shipping them); opting out
    # of them as well is what yields no lexicon at all.
    monkeypatch.chdir(tmp_path)
    builtin_only = load_lexicon(Settings.from_mapping({}))
    assert builtin_only is not None
    assert "Vane Gogue" in builtin_only.respell("Van Gogh peint.", "fr")
    assert load_lexicon(Settings.from_mapping({"lexicon": {"builtin": False}})) is None
    # The environment override points every process at one shared lexicon.
    monkeypatch.setenv("SPEAKER_HELPER_LEXICON", str(file))
    assert load_lexicon(Settings.from_mapping({})) is not None


def test_speaker_applies_the_respelling_tier_only_where_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mock (no phonemes) gets respelled text; an IPA-tier engine does not."""
    file = tmp_path / "lexicon.yaml"
    file.write_text(
        yaml.safe_dump(
            {"entries": [{"word": "GitHub", "language": "*", "respelling": "guite-heube"}]}
        ),
        encoding="utf-8",
    )
    base = {
        "backend": "mock",
        "language": "fr",
        "lexicon": {"path": str(file)},
        "chunking": {"enabled": False},
    }
    # The mock engine has no LEXICON_TIER attribute → the respelling tier
    # applies, and the result's echoed text proves it reached the engine.
    spk = Speaker(Settings.from_mapping(base))
    result = asyncio.run(spk.say("Va sur GitHub.", language="fr"))
    assert result.text == "Va sur guite-heube."

    # An engine declaring the IPA tier must receive the text untouched (it
    # splices phonemes itself at its own phonemisation step).
    class _IpaTierEngine:
        """Minimal engine stub declaring the IPA lexicon tier."""

        LEXICON_TIER = "ipa"

        def __init__(self) -> None:
            self.saw: list[str] = []

        async def synthesize(self, text: str, *, language=None, voice=None, speed=1.0):
            self.saw.append(text)
            # Reuse the mock engine for a real AudioResult shape.
            from speaker_helper.engine import MockEngine

            return await MockEngine(Settings.from_mapping({"backend": "mock"})).synthesize(
                text, language=language
            )

        async def list_voices(self, engine=None):  # pragma: no cover - unused
            raise NotImplementedError

        async def health(self):  # pragma: no cover - unused
            return {"status": "ok"}

        async def clone_voice(self, name, samples, *, language=None):  # pragma: no cover
            raise NotImplementedError

        async def aclose(self) -> None:
            return None

    stub = _IpaTierEngine()
    spk2 = Speaker(Settings.from_mapping(base), engine=stub)
    asyncio.run(spk2.say("Va sur GitHub.", language="fr"))
    assert stub.saw == ["Va sur GitHub."]


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def test_greedy_packing_respects_the_budget_without_losing_sentences() -> None:
    """Greedy sizes are positive, sum to the input, and respect max_chars."""
    sentences = ["aaaa.", "bbbb.", "cccc.", "d" * 300 + "."]
    sizes = greedy_group_sizes(sentences, max_chars=12)
    assert sum(sizes) == len(sentences)
    assert all(s >= 1 for s in sizes)
    # The oversized sentence still forms its own group (never split inside).
    assert sizes[-1] == 1


def test_group_size_validation_is_strict() -> None:
    """Only a positive-integer array summing to the sentence count passes."""
    assert _validate_group_sizes("[2, 1]", expected_total=3) == [2, 1]
    # Prose around the array is tolerated; a wrong sum, zero, float or
    # missing array is not.
    assert _validate_group_sizes("chunks: [1, 1, 1] done", expected_total=3) == [1, 1, 1]
    assert _validate_group_sizes("[2, 2]", expected_total=3) is None
    assert _validate_group_sizes("[0, 3]", expected_total=3) is None
    assert _validate_group_sizes("no array here", expected_total=3) is None


def test_chunk_long_text_llm_answer_used_when_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid LLM grouping is honoured; an invalid one falls back greedily."""
    text = "Un. Deux. Trois. Quatre."
    settings = Settings.from_mapping({"chunking": {"max_chars": 10}})
    # Valid answer → exactly the LLM's boundaries.
    monkeypatch.setattr(chunking_mod, "_llm_group_sizes", lambda s, lang, m: [3, 1])
    assert chunk_long_text(text, "fr", settings) == ["Un. Deux. Trois.", "Quatre."]
    # Invalid answer (None) → greedy fallback, text still fully preserved.
    monkeypatch.setattr(chunking_mod, "_llm_group_sizes", lambda s, lang, m: None)
    chunks = chunk_long_text(text, "fr", settings)
    assert " ".join(chunks) == text
    # Short texts never split, whatever the knobs say.
    assert chunk_long_text("Court.", "fr", settings) == ["Court."]


def test_chunked_say_merges_into_one_result() -> None:
    """A long say() returns one AudioResult whose text is the caller's text."""
    settings = Settings.from_mapping(
        {
            "backend": "mock",
            "language": "fr",
            "lexicon": {"enabled": False},
            "chunking": {"llm": False, "max_chars": 80},
        }
    )
    spk = Speaker(settings)
    text = " ".join(f"La phrase {i} occupe l'espace nécessaire au découpage." for i in range(6))
    result = asyncio.run(spk.say(text))
    # One merged result: the caller's text, a duration spanning every chunk
    # (the mock speaks ~15 chars/s, so well beyond any single chunk), and the
    # backend's sample rate.
    assert result.text == text
    assert result.duration_s > 10.0
    assert result.sample_rate == 24_000


# ---------------------------------------------------------------------------
# Language routing: fr → chatterbox (ratified), en → chatterbox (Turbo),
# others → chatterbox (Multilingual)
# ---------------------------------------------------------------------------


def test_offline_routing_follows_the_owner_priors() -> None:
    """Offline routing encodes the owner's editorial choice, flagged as prior.

    The A/B bench's UTMOSv2 numbers were deliberately NOT folded into routing:
    the owner rejected that metric as the offline criterion (it scores a
    generic anonymous-panel naturalness, not "réaliste et vivante" to a human
    ear — see STUDY.md §8 bis). Until human listening data lands, the
    language-aware priors ARE the decision, and the router must say so
    (``quality_source="prior"``) rather than dress them up.
    """
    # English: chatterbox (its backend auto-picks the Turbo variant).
    en = route(RouteRequest(condition="offline", language="en"))
    assert (en.engine, en.backend) == ("chatterbox", "chatterbox")
    assert en.quality_source == "prior"
    assert en.owner_ratified is False  # it won the argmax on its own
    # Any other language: chatterbox too (the multilingual variant serves it);
    # kyutai must NOT win — it would read Spanish with a French/English tongue.
    es = route(RouteRequest(condition="offline", language="es"))
    assert (es.engine, es.backend) == ("chatterbox", "chatterbox")
    assert es.quality_source == "prior"


def test_offline_french_follows_the_owner_ratification() -> None:
    """French offline is the owner's arbitration — and says so.

    Ratified 2026-10-28: **fr → chatterbox** (the Multilingual model, the best
    documented chatterbox that speaks French; Turbo and base are English-only).
    This is a DECISION, so the router must (a) follow it, (b) flag it as an
    arbitration rather than a measurement, and (c) leave the evidence it
    overrode intact and visible — kyutai's 0.92 French prior still stands in
    the tables, and still wins when the ratification is switched off.
    """
    fr = route(RouteRequest(condition="offline", language="fr"))
    assert (fr.engine, fr.backend) == ("chatterbox", "chatterbox")
    assert fr.owner_ratified is True
    # The override is declared in the justification, naming what it set aside.
    assert "OVERRIDES" in fr.justification
    assert "kyutai" in fr.justification
    # The quality axis is NOT rewritten to justify the choice: the decision
    # carries chatterbox's own documented French prior, lower than kyutai's.
    assert fr.quality == engine_quality_prior("chatterbox", "fr")
    assert fr.quality < engine_quality_prior("kyutai", "fr")
    # Switch the arbitration off and the unarbitrated argmax reappears.
    raw = route(RouteRequest(condition="offline", language="fr", respect_ratification=False))
    assert raw.engine == "kyutai"
    assert raw.owner_ratified is False
    # A region subtag or an upper-cased code is still French: the lookup
    # normalises the tag, rather than falling through to the argmax in silence.
    for tag in ("fr-FR", "FR", "fr-ca"):
        tagged = route(RouteRequest(condition="offline", language=tag))
        assert (tagged.engine, tagged.owner_ratified) == ("chatterbox", True), tag
    # The caller's own vetoes come first: a floor of 0.85 drops chatterbox
    # (0.78 in French) before the arbitration is consulted, and the router
    # then reports honestly that it overrode nothing.
    floored = route(RouteRequest(condition="offline", language="fr", quality_floor=0.85))
    assert (floored.engine, floored.owner_ratified) == ("kyutai", False)
    assert "OVERRIDES" not in floored.justification


def test_language_aware_priors() -> None:
    """Per-language priors refine the base, with a wildcard floor for kyutai."""
    assert engine_quality_prior("kyutai", "fr") == 0.92
    assert engine_quality_prior("kyutai", "en") == 0.85
    # Outside fr/en the wildcard floor applies (kyutai does not speak es).
    assert engine_quality_prior("kyutai", "es") == 0.30
    # Without a language, the base prior stands.
    assert engine_quality_prior("kyutai") == 0.88
    assert engine_quality_prior("chatterbox", "fr") == 0.78


def test_catalogue_engines_all_have_a_registered_backend() -> None:
    """Every engine the catalogue proposes can actually be constructed."""
    registered = set(available_backends())
    for point in default_operating_points("fr"):
        # The decision's backend must name something create_engine knows —
        # this is the regression test for the old backend="kokoro" default
        # silently mislabelling non-kokoro engines.
        assert point.backend in registered
        assert ENGINE_BACKENDS.get(point.engine) == point.backend


# ---------------------------------------------------------------------------
# Kyutai backend (no weights needed for these)
# ---------------------------------------------------------------------------


def test_kyutai_backend_contract_without_weights() -> None:
    """The parts of the kyutai backend that must not require a download."""
    from speaker_helper.backends.kyutai import DEFAULT_VOICE_BY_LANG, KyutaiEngine

    engine = KyutaiEngine(Settings.from_mapping({"backend": "kyutai", "language": "fr"}))
    # Empty text is refused before any model would load.
    with pytest.raises(ValueError, match="empty"):
        asyncio.run(engine.synthesize("   "))
    # Cloning is a policy refusal that names the alternatives.
    with pytest.raises(NotImplementedError, match="chatterbox"):
        asyncio.run(engine.clone_voice("x", []))
    # The curated voices are the female defaults, one per supported language.
    voices = asyncio.run(engine.list_voices())
    assert {v.language for v in voices.voices} == {"fr", "en"}
    assert all(v.gender == "female" for v in voices.voices)
    assert voices.voices[0].voice_id == DEFAULT_VOICE_BY_LANG["fr"]


# ---------------------------------------------------------------------------
# Streaming (online) routing: the public-Elo criterion
# ---------------------------------------------------------------------------


def test_online_routing_ranks_quality_by_public_elo() -> None:
    """Online quality is the public arena Elo; absence of Elo is a ranked gap.

    The owner ratified two different quality criteria per condition
    (STREAMING.md): editorial priors offline, public arena Elo online. The
    online catalogue must therefore carry ``public_elo`` provenance for
    arena-ranked engines, and rank an engine absent from every public arena
    (``no_public_elo``, quality 0.0) below every ranked one — never let a
    flattering prior sneak into the Elo race.
    """
    from speaker_helper.eval.priors import PUBLIC_ELO, elo_to_unit

    pts = {p.engine: p for p in default_operating_points("fr", condition="online_realtime")}
    # Arena-ranked engines carry their Elo, linearly mapped, flagged as such.
    assert pts["kokoro"].quality_source == "public_elo"
    assert pts["kokoro"].quality == elo_to_unit(PUBLIC_ELO["kokoro"])
    assert pts["chatterbox"].quality_source == "public_elo"
    # kyutai is on no public arena (as of 2026-10-26): documented gap, not a prior.
    assert pts["kyutai"].quality_source == "no_public_elo"
    assert pts["kyutai"].quality == 0.0
    # The offline catalogue is untouched by the Elo criterion.
    off = {p.engine: p for p in default_operating_points("fr", condition="offline")}
    assert off["kyutai"].quality_source == "prior"
    assert off["kyutai"].quality > 0.5


def test_online_decision_is_elo_ranked_and_rtf_gated() -> None:
    """The online decision cites public Elo and only among engines that keep up."""
    d = route(RouteRequest(condition="online_realtime", language="fr"))
    # kokoro: the only engine with BOTH a public Elo and a measured real-time
    # RTF on the reference host — the one candidate evidenced on both axes.
    assert d.engine == "kokoro"
    assert d.quality_source == "public_elo"
    assert d.rtf_source == "measured"
    assert d.mode == "streaming"


# ── Built-in per-language lexicons ──────────────────────────────────────────


def test_builtin_lexicons_load_and_apply() -> None:
    """The packaged per-language files apply without any user lexicon.

    "Van Gogh" in French and "Gide" in English are the canonical cases: both
    are mangled by the default G2P, both are stated once in the shipped
    ``lexicons/<code>.yaml``, and both must come out respelled on a machine
    with no ``lexicon.yaml`` at all.
    """
    entries = lexicon_mod.builtin_entries()
    assert entries, "the packaged lexicons are empty"
    assert all(e.source == "builtin" for e in entries)
    lex = lexicon_mod.Lexicon(entries)
    assert "Vane Gogue" in lex.respell("Van Gogh peint.", "fr")
    assert "Stanislasse" in lex.respell("Stanislas, 2021", "fr")
    assert "Zheed" in lex.respell("Gide wrote plays.", "en")
    # et la langue borne l'entree : Gide en francais reste Gide
    assert lex.respell("Gide écrit.", "fr") == "Gide écrit."


def test_user_lexicon_wins_over_builtin(tmp_path: Path) -> None:
    """A user entry on a built-in word replaces it, the rest survives."""
    user = tmp_path / "lexicon.yaml"
    entree = {"word": "Van Gogh", "language": "fr", "respelling": "Vinnecent"}
    user.write_text(yaml.safe_dump({"entries": [entree]}), encoding="utf-8")
    settings = Settings.from_mapping({"lexicon": {"path": str(user)}})
    lex = lexicon_mod.load_lexicon(settings)
    assert lex is not None
    assert "Vinnecent" in lex.respell("Van Gogh peint.", "fr")
    assert "Stanislasse" in lex.respell("Stanislas, 2021", "fr")


def test_builtin_optout(tmp_path: Path) -> None:
    """``lexicon.builtin: false`` leaves only the user file, or nothing."""
    settings = Settings.from_mapping({"lexicon": {"builtin": False}})
    assert lexicon_mod.load_lexicon(settings) is None
