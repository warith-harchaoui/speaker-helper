"""
Curated preset voices, keyed by language and gender.

Module summary
--------------
Auto-picking a voice from the engine's presets (see
resolution by language) is convenient
but blind to gender: it takes the first voice whose language matches. When an
application needs a *specific* male or female voice per language — a two-speaker
dialogue, a role-played call — it should not have to hard-code raw engine ids.

This module names that choice. :data:`PRESET_VOICES` is a small, curated set of
**real kokoro voices** (the ids the ``kokoro`` backend actually serves),
and :func:`voice_for` resolves a ``(language, gender)`` pair to one of them.

Notes on coverage
-----------------
kokoro ships several English voices of each gender and one French voice,
``ff_siwis`` (female). It has **no native French male voice**, so the French male
slot maps to a real male voice id (``bm_george``) that renders French text with a
male timbre. Every id here is a genuine kokoro preset; none is a placeholder.

Usage example
-------------
>>> from speaker_helper.voices import voice_for
>>> voice_for("fr", "female")
'ff_siwis'
>>> voice_for("en", "male")
'am_michael'

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

from speaker_helper.types import Voice

# Curated, real kokoro presets. Two English voices per gender give variety for
# multi-speaker scenes; French has its one native female voice plus a real male
# voice standing in for the gender kokoro does not natively cover.
PRESET_VOICES: tuple[Voice, ...] = (
    # English — female
    Voice(voice_id="af_heart", name="Heart", language="en", gender="female", engine="kokoro"),
    Voice(voice_id="bf_emma", name="Emma", language="en", gender="female", engine="kokoro"),
    # English — male
    Voice(voice_id="am_michael", name="Michael", language="en", gender="male", engine="kokoro"),
    Voice(voice_id="bm_george", name="George", language="en", gender="male", engine="kokoro"),
    # French — female (kokoro's native French voice)
    Voice(voice_id="ff_siwis", name="Siwis", language="fr", gender="female", engine="kokoro"),
    # French — male (no native kokoro French male; a real male voice speaks the
    # French text with a male timbre).
    Voice(voice_id="bm_george", name="George (fr)", language="fr", gender="male", engine="kokoro"),
)


def voices_for(language: str, gender: str = "") -> list[Voice]:
    """Return the curated voices matching ``language`` and, if given, ``gender``.

    Parameters
    ----------
    language : str
        ISO-639-1 language code (e.g. ``"fr"``, ``"en"``).
    gender : str, optional
        ``"male"`` or ``"female"`` to filter; empty returns both genders.

    Returns
    -------
    list of Voice
        Matching voices, in catalogue order (may be empty).
    """
    lang = (language or "").lower()[:2]
    gen = (gender or "").lower()
    return [v for v in PRESET_VOICES if v.language == lang and (not gen or v.gender == gen)]


def voice_for(language: str, gender: str = "", *, index: int = 0) -> str:
    """Resolve a ``(language, gender)`` pair to a concrete kokoro voice id.

    Parameters
    ----------
    language : str
        ISO-639-1 language code.
    gender : str, optional
        ``"male"`` or ``"female"``; empty picks the first voice of the language.
    index : int, optional
        Which matching voice to take when several exist, cycled modulo the count
        (so callers can hand out distinct voices to distinct speakers).

    Returns
    -------
    str
        A real kokoro ``voice_id``. Falls back to the first voice of the language
        (ignoring gender), then to ``ff_siwis``/``am_michael``-style defaults, so
        the result is always a usable id.
    """
    matches = voices_for(language, gender)
    if not matches:
        # No gendered match: relax to any voice of the language, then to English.
        matches = voices_for(language) or voices_for("en")
    if not matches:
        return "af_heart"  # last-resort real kokoro id
    return matches[index % len(matches)].voice_id
