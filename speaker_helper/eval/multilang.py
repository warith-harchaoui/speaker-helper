"""
Multi-language measurement: run the evaluation across several languages.

Module summary
--------------
A single engine (kokoro speaks many languages) does not perform identically in
every language. This module runs the evaluation gate once per language — each
with its own bundled dataset and a voice auto-picked for that language — and
returns one :class:`~speaker_helper.eval.runner.EvalReport` per language. That
is the raw material for a language × (speed, quality) matrix: the product-side
counterpart of choosing an operating point per language.

Because it drives the engine-agnostic :class:`~speaker_helper.speaker.Speaker`,
the same call measures the deterministic ``mock`` backend (for tests) or a real
engine (for real numbers) — only ``settings.backend`` differs.

Usage example
-------------
>>> import asyncio
>>> from speaker_helper import Settings
>>> from speaker_helper.eval import run_multilang_eval
>>> reports = asyncio.run(run_multilang_eval(
...     Settings.from_mapping({"backend": "mock"}), ["fr", "en", "es"]))
>>> sorted(reports)
['en', 'es', 'fr']

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import dataclasses

import os_helper as osh

from speaker_helper.config import Settings
from speaker_helper.eval.dataset import load_dataset
from speaker_helper.eval.runner import EvalReport, Transcriber, run_eval
from speaker_helper.eval.thresholds import Thresholds
from speaker_helper.speaker import Speaker


async def run_multilang_eval(
    base_settings: Settings,
    languages: list[str],
    *,
    thresholds: Thresholds | None = None,
    transcriber: Transcriber | None = None,
    warmup: bool = True,
) -> dict[str, EvalReport]:
    """Evaluate an engine across several languages, one report per language.

    Parameters
    ----------
    base_settings : Settings
        Base configuration (backend, engine, connection). Its ``language`` and
        ``voice_id`` are overridden per language so the engine auto-picks a
        voice matching each language.
    languages : list of str
        ISO-639-1 codes to measure; each must have a bundled dataset (see
        :func:`~speaker_helper.eval.dataset.available_languages`).
    thresholds : Thresholds or None
        Pass/fail bar applied to every language; defaults to the bundled bar.
    transcriber : Transcriber or None
        Optional STT enabling the WER/chrF round-trip in each language.
    warmup : bool
        When ``True`` (default), warm each language's voice before measuring so
        the numbers reflect steady state rather than a one-off cold model/voice
        load. Set ``False`` to include cold-start cost.

    Returns
    -------
    dict
        Mapping ``language -> EvalReport`` in the requested order.
    """
    thresholds = thresholds or Thresholds.load()
    reports: dict[str, EvalReport] = {}
    for lang in languages:
        # Fresh language + auto voice pick (empty voice_id) so the engine
        # bootstraps a profile for this language rather than reusing another.
        settings = dataclasses.replace(base_settings, language=lang, voice_id="")
        cases = load_dataset(language=lang)
        osh.info("measuring language %s (%d cases)", lang, len(cases))
        async with Speaker(settings) as spk:
            if warmup:
                await spk.warmup()
            reports[lang] = await run_eval(
                spk, cases, thresholds=thresholds, transcriber=transcriber
            )
    return reports


def format_matrix(reports: dict[str, EvalReport]) -> str:
    """Render a per-language report mapping as a compact text matrix.

    Parameters
    ----------
    reports : dict
        Mapping ``language -> EvalReport`` (e.g. from :func:`run_multilang_eval`).

    Returns
    -------
    str
        A fixed-width table with one row per language and a PASS/FAIL verdict.
    """
    # Fixed-width header, then an underline sized to it for a clean table.
    header = (
        f"{'lang':<6}{'cases':>6}{'mean_rtf':>10}{'p95_rtf':>9}"
        f"{'anomaly':>9}{'quality':>9}  verdict"
    )
    lines = [header, "-" * len(header)]
    # One row per language; a failing run spells out its reasons inline.
    for lang, r in reports.items():
        verdict = "PASS" if r.passed else "FAIL: " + "; ".join(r.failures)
        lines.append(
            f"{lang:<6}{r.n_cases:>6}{r.mean_rtf:>10.3f}{r.p95_rtf:>9.3f}"
            f"{r.anomaly_rate:>9.3f}{r.quality:>9.3f}  {verdict}"
        )
    return "\n".join(lines)
