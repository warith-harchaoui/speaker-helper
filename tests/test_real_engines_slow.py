"""
Heavy integration tests against the real engines and the real local LLM.

Every test here is marked ``slow`` and therefore **excluded from CI** (the
repository's pytest addopts run ``-m 'not slow'``): CI stays light, these run
on a developer machine that has the weights and the Ollama daemon. Each test
also *skips* — never fails — when its prerequisite is absent, so
``pytest -m slow`` degrades gracefully on a fresh checkout:

* kokoro: needs the ~340 MB ONNX weights already installed.
* kyutai: needs the ~3.4 GB model already in the Hugging Face cache (no test
  is allowed to download it).
* the lexicon LLM tier: needs a running Ollama with the model
  ``best-engine-ai-helper`` resolves.

Run them with::

    pytest -m slow tests/test_real_engines_slow.py
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest
import yaml

from speaker_helper.config import Settings

#: The Hugging Face cache directory a prior download would have populated.
_HF_HUB = Path.home() / ".cache" / "huggingface" / "hub"


def _kokoro_ready() -> bool:
    """Whether the kokoro ONNX weights are already on this machine."""
    try:
        from speaker_helper.backends.kokoro import model_paths

        return model_paths() is not None
    except Exception:  # noqa: BLE001 - any import/setup issue means "not ready"
        return False


def _kyutai_cached() -> bool:
    """Whether the kyutai model is already cached (tests never download it)."""
    if importlib.util.find_spec("moshi") is None:
        return False
    return (_HF_HUB / "models--kyutai--tts-1.6b-en_fr").exists()


def _chatterbox_cached() -> bool:
    """Whether the chatterbox weights are already cached (never downloaded here)."""
    if importlib.util.find_spec("chatterbox") is None:
        return False
    return (_HF_HUB / "models--ResembleAI--chatterbox").exists()


def _ollama_up() -> bool:
    """Whether a local Ollama daemon answers (the LLM tier's prerequisite)."""
    try:
        import ollama

        ollama.list()
        return True
    except Exception:  # noqa: BLE001 - daemon down, client missing, ...
        return False


@pytest.mark.slow
@pytest.mark.skipif(not _kokoro_ready(), reason="kokoro weights not installed")
def test_kokoro_honours_lexicon_ipa_end_to_end(tmp_path: Path) -> None:
    """A lexicon IPA entry flows through phonemisation into real audio."""
    # A pronunciation the French G2P would not produce on its own, so the
    # splice is doing real work (not just reproducing the default phonemes).
    file = tmp_path / "lexicon.yaml"
    file.write_text(
        yaml.safe_dump({"entries": [{"word": "Grasse", "language": "fr", "ipa": "ɡʁas"}]}),
        encoding="utf-8",
    )
    from speaker_helper.backends.kokoro import KokoroEngine

    engine = KokoroEngine(
        Settings.from_mapping(
            {"backend": "kokoro", "language": "fr", "lexicon": {"path": str(file), "llm": False}}
        )
    )
    # The phonemisation step is where the splice happens — assert on it
    # directly (deterministic), then synthesise to prove the phonemes are
    # acceptable to the model.
    phonemes = engine._phonemise("Bienvenue à Grasse.", "fr-fr")
    assert "ɡʁas" in phonemes
    result = asyncio.run(engine.synthesize("Bienvenue à Grasse.", language="fr"))
    assert result.duration_s > 0.5
    assert result.voice_id == "ff_siwis"  # the French female default


@pytest.mark.slow
@pytest.mark.skipif(not _ollama_up(), reason="no local Ollama daemon")
def test_llm_respelling_against_the_real_model() -> None:
    """The real resolved model derives a usable respelling for an initialism."""
    from speaker_helper.lexicon import _llm_respelling

    # An initialism is the easiest derivation class; if the real stack cannot
    # do this one, the tier is effectively down and should be looked at.
    derived = _llm_respelling("RGPD", "fr")
    assert derived, "the local LLM returned nothing usable for 'RGPD'"
    # Letter-by-letter answers come back hyphenated or spaced; either way the
    # answer must differ from the raw initialism (speaking "RGPD" as a word
    # is the failure the lexicon exists to fix).
    assert derived.lower() != "rgpd"


@pytest.mark.slow
@pytest.mark.skipif(not _kyutai_cached(), reason="kyutai weights not in the HF cache")
def test_kyutai_speaks_french_with_the_female_default() -> None:
    """The kyutai backend synthesises French with the documented default voice."""
    from speaker_helper.backends.kyutai import DEFAULT_VOICE_BY_LANG, KyutaiEngine

    engine = KyutaiEngine(
        Settings.from_mapping(
            {"backend": "kyutai", "language": "fr", "lexicon": {"enabled": False}}
        )
    )
    result = asyncio.run(engine.synthesize("Bonjour, ceci est un essai.", language="fr"))
    # Real speech for a short sentence: non-trivial duration, the fixed mimi
    # rate, and the female French default actually used.
    assert result.duration_s > 0.8
    assert result.sample_rate == 24_000
    assert result.voice_id == DEFAULT_VOICE_BY_LANG["fr"]
    asyncio.run(engine.aclose())


@pytest.mark.slow
@pytest.mark.skipif(not _chatterbox_cached(), reason="chatterbox weights not in the HF cache")
def test_chatterbox_short_text_fails_with_a_diagnosis_not_a_torch_error() -> None:
    """A fragment too short for upstream's watchdog must fail legibly.

    `AlignmentStreamAnalyzer` is built ONLY for the multilingual model (see
    `T3.inference`, `if self.hp.is_multilingual`) — the exact variant serving
    French and every non-English language here. Below roughly four tokens it
    has no alignment window and dies in `step()` with "max(): Expected
    reduction dim 1 to have non-zero size", four frames deep in torch.
    Measured boundary (2026-10-28, chatterbox-tts 0.1.7): "Un." and "A."
    fail, "Oui." and "Non." succeed. Upstream exposes no flag to disable it,
    so the backend owes the caller an error that names the cause. This matters
    in production, not in theory: the sentence splitter emits "Un." as its own
    chunk, so any French narration containing a short sentence hits it.
    """
    from speaker_helper.backends.chatterbox import ChatterboxEngine

    engine = ChatterboxEngine(
        Settings.from_mapping(
            {"backend": "chatterbox", "language": "fr", "lexicon": {"enabled": False}}
        )
    )
    # The diagnosis names the engine, the text, and what to do about it.
    with pytest.raises(RuntimeError, match="alignment watchdog"):
        asyncio.run(engine.synthesize("Un.", language="fr"))
    # And the neighbouring length still works, so the guard is not over-broad.
    assert asyncio.run(engine.synthesize("Oui.", language="fr")).duration_s > 0.0
