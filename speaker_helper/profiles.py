"""
Per-language operating profiles: hyperparameters plus a measured operating point.

Module summary
--------------
A single engine speaks many languages, but the *best settings* differ per
language — which voice, and how to run the streaming producer/consumer (how
small to make the first chunk for low time-to-first-audio, how many chunks to
synthesise in parallel). A :class:`LanguageProfile` bundles those knobs for one
language, together with the **quality** and **RTF** measured for it, so the
operating point is chosen from data rather than guessed.

Streaming in speaker-helper is a producer/consumer pipeline: a *producer* splits
the text into sentence-sized chunks and *consumers* synthesise them under a
bounded concurrency while emission stays in order (see
:meth:`~speaker_helper.speaker.Speaker.stream`). ``first_chunk_sentences``
(producer granularity) and ``stream_concurrency`` (consumer parallelism) are the
two hyperparameters that trade time-to-first-audio against throughput; they live
here, per language.

:func:`~speaker_helper.eval.multilang.run_multilang_eval` measures each language;
:meth:`LanguageProfile.with_measurement` records that result back onto the
profile, and :func:`tune_profiles` builds measured profiles for a set of
languages in one call.

Usage example
-------------
>>> from speaker_helper.profiles import profile_for
>>> profile_for("en").engine
'kokoro'
>>> profile_for("en").first_chunk_sentences
1

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from speaker_helper.config import Settings


@dataclass(frozen=True)
class LanguageProfile:
    """Hyperparameters and a measured operating point for one language.

    Parameters
    ----------
    language : str
        ISO-639-1 code this profile targets.
    engine : str
        Engine/model id to use for this language.
    voice_id : str
        Preset voice id; empty means "auto-pick a voice for the language".
    normalize : bool
        Ask the engine to loudness-normalise the output.
    first_chunk_sentences : int
        Streaming *producer* granularity — sentences in the first emitted chunk.
        ``1`` minimises time-to-first-audio.
    stream_concurrency : int
        Streaming *consumer* parallelism — chunks synthesised at once. ``1`` is
        a strict pipeline (lowest first-audio latency).
    measured_rtf : float or None
        Mean real-time factor measured for this language, or ``None`` if untuned.
    measured_quality : float or None
        Quality score in ``[0, 1]`` measured for this language, or ``None``.
    """

    language: str
    engine: str = "kokoro"
    voice_id: str = ""
    normalize: bool = True
    first_chunk_sentences: int = 1
    stream_concurrency: int = 1
    measured_rtf: float | None = None
    measured_quality: float | None = None

    def apply(self, settings: Settings | None = None) -> Settings:
        """Return ``settings`` (or fresh defaults) with this profile applied.

        Parameters
        ----------
        settings : Settings or None
            Base configuration to derive from; ``None`` uses defaults.

        Returns
        -------
        Settings
            A copy carrying this profile's language, engine, voice, and
            producer granularity. ``stream_concurrency`` is a :class:`Speaker`
            argument, not a :class:`Settings` field, so pass it separately (see
            :meth:`~speaker_helper.speaker.Speaker.from_profile`).
        """
        base = settings if settings is not None else Settings()
        return dataclasses.replace(
            base,
            language=self.language,
            engine=self.engine,
            voice_id=self.voice_id,
            normalize=self.normalize,
            first_chunk_sentences=self.first_chunk_sentences,
        )

    def with_measurement(self, report: object) -> LanguageProfile:
        """Return a copy with ``measured_rtf``/``measured_quality`` from a report.

        Parameters
        ----------
        report : EvalReport
            A report for this language (duck-typed: needs ``mean_rtf`` and
            ``quality``).

        Returns
        -------
        LanguageProfile
            A copy carrying the measured operating point.
        """
        return dataclasses.replace(
            self,
            measured_rtf=getattr(report, "mean_rtf", None),
            measured_quality=getattr(report, "quality", None),
        )


# Sensible defaults per language. Voice is left to auto-pick (empty) so the
# engine chooses one matching the language; the streaming knobs favour low
# time-to-first-audio. Recalibrate the measured fields from real runs.
DEFAULT_PROFILES: dict[str, LanguageProfile] = {
    lang: LanguageProfile(language=lang)
    for lang in ("fr", "en", "es", "it", "pt", "de")
}


def profile_for(language: str) -> LanguageProfile:
    """Return the profile for ``language`` (a default profile if none is defined)."""
    return DEFAULT_PROFILES.get(language, LanguageProfile(language=language))


async def tune_profiles(
    base_settings: Settings,
    languages: list[str],
    **eval_kwargs: object,
) -> dict[str, LanguageProfile]:
    """Measure a set of languages and return profiles carrying the results.

    A thin convenience over
    :func:`~speaker_helper.eval.multilang.run_multilang_eval`: it runs the
    evaluation per language and folds each report's RTF/quality into the
    corresponding :class:`LanguageProfile`.

    Parameters
    ----------
    base_settings : Settings
        Base configuration (backend, engine, connection).
    languages : list of str
        Language codes to measure and profile.
    **eval_kwargs
        Forwarded to :func:`run_multilang_eval` (e.g. ``thresholds``,
        ``transcriber``, ``warmup``).

    Returns
    -------
    dict
        Mapping ``language -> LanguageProfile`` with measured RTF/quality.
    """
    from speaker_helper.eval.multilang import run_multilang_eval

    reports = await run_multilang_eval(base_settings, languages, **eval_kwargs)  # type: ignore[arg-type]
    return {
        lang: profile_for(lang).with_measurement(report)
        for lang, report in reports.items()
    }
