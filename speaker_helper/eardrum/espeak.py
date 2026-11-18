"""
espeak-ng as the loop's reading of plain text.

Module summary
--------------
Two jobs need a deterministic grapheme-to-phoneme reading:

* the **carrier sentence** around a word ("Je vous parle de … aujourd'hui.")
  is ordinary text, and its IPA tells the aligner where the word sits;
* **foreign-word detection**: espeak-ng wraps a word it reads in another
  language in switch markers (``(en)tˈeɪlwɪnd(fr)``), which is exactly the
  kind of word a French engine is likely to mangle.

The library is found the way :func:`speaker_helper.backends.kokoro.espeak_config`
finds it — a system install first, the ``espeakng-loader`` wheel last — but
without importing kokoro-onnx, which the eardrum extra does not need.

Usage example
-------------
>>> espeak_language("fr"), espeak_language("en-GB"), espeak_language("es")
('fr-fr', 'en-gb', 'es')

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

#: espeak-ng's switch marker, as in ``(en)`` or ``(fr)``.
SWITCH_MARKER = re.compile(r"\((?:[a-z]{2,3}(?:-[a-z]{2,4})?)\)")

#: ISO-639-1 → espeak-ng voice, for the codes espeak does not take as-is.
_ESPEAK_VOICE = {"fr": "fr-fr", "en": "en-us", "pt": "pt-br"}


def espeak_language(code: str) -> str:
    """The espeak-ng voice for an ISO-639-1 (or regional) language code.

    Parameters
    ----------
    code : str
        ``"fr"``, ``"en-GB"``, ``"es"``…

    Returns
    -------
    str
        A voice espeak-ng accepts.
    """
    raw = (code or "en").strip().lower()
    if "-" in raw:
        return raw
    return _ESPEAK_VOICE.get(raw, raw)


@functools.lru_cache(maxsize=1)
def _configure() -> None:
    """Point phonemizer at a working espeak-ng library, once per process.

    Raises
    ------
    ImportError
        When ``phonemizer`` is not installed.
    """
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    for prefix in (Path("/opt/homebrew"), Path("/usr/local"), Path("/usr")):
        for name in ("libespeak-ng.dylib", "libespeak-ng.so", "libespeak-ng.so.1"):
            library = prefix / "lib" / name
            data = prefix / "share" / "espeak-ng-data"
            if library.is_file() and (data / "phontab").is_file():
                EspeakWrapper.set_library(str(library))
                EspeakWrapper.set_data_path(str(data))
                return
    try:  # pragma: no cover - only on machines without a system espeak-ng
        import espeakng_loader

        EspeakWrapper.set_library(espeakng_loader.get_library_path())
        EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
    except ImportError:
        # Leave phonemizer to its own discovery; it raises a clear error.
        pass


@functools.lru_cache(maxsize=8)
def _backend(language: str, keep_flags: bool):  # type: ignore[no-untyped-def]
    """A cached phonemizer backend for one language and switch policy.

    Parameters
    ----------
    language : str
        espeak-ng voice.
    keep_flags : bool
        Keep ``(en)…(fr)`` switch markers in the output.

    Returns
    -------
    phonemizer.backend.EspeakBackend
        The backend.
    """
    _configure()
    from phonemizer.backend import EspeakBackend

    return EspeakBackend(
        language,
        with_stress=True,
        language_switch="keep-flags" if keep_flags else "remove-flags",
    )


def espeak_ipa(text: str, language: str) -> str:
    """espeak-ng's IPA reading of ``text``, switch markers removed.

    Parameters
    ----------
    text : str
        Plain text.
    language : str
        ISO-639-1 code of the text.

    Returns
    -------
    str
        The IPA (empty for empty text).
    """
    if not text.strip():
        return ""
    out = _backend(espeak_language(language), False).phonemize([text], strip=True)[0]
    return SWITCH_MARKER.sub("", out).strip()


def foreign_words(words: list[str], language: str) -> set[str]:
    """The words espeak-ng reads as belonging to another language.

    Parameters
    ----------
    words : list of str
        Candidate words, phonemised in one batch.
    language : str
        ISO-639-1 code of the text.

    Returns
    -------
    set of str
        The subset espeak wrapped in a language switch.

    Notes
    -----
    Returns an empty set when espeak-ng is unavailable: detection then rests
    on the other rules (capitals, acronyms, mixed case), never on a crash.
    """
    if not words:
        return set()
    try:
        outputs = _backend(espeak_language(language), True).phonemize(list(words), strip=True)
    except Exception:  # noqa: BLE001 - detection is an aid, not a requirement
        return set()
    return {word for word, out in zip(words, outputs, strict=False) if SWITCH_MARKER.search(out)}
