"""
Fetching the weights, so the first real run is not also the first download.

Module summary
--------------
``pip install`` gives you the code. It does not give you the ~340 MB Kokoro
reads from, and the gap between those two facts is where a first use goes
wrong: the package imports, the CLI answers ``--help``, and the first sentence
of a long narration is where you find out. :func:`install_engine` closes it
deliberately, before anything is riding on it.

Stdlib only, on purpose. This runs *before* the extras are necessarily in
place — somebody fixing a broken install should not need the broken install to
work.

Two kinds of failure, told apart
--------------------------------
A truncated download is the normal way this breaks: a dropped connection
leaves a short file that *exists*, so a plain "is it there" check calls it
installed and the model fails to load with something about a corrupt graph.
The sizes are therefore pinned and checked, and re-running repairs rather than
trusting the shorter file.

The release is pinned to a tag rather than a floating "latest", so two
machines installing a week apart get the same narrator.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

from speaker_helper.backends.kokoro import CACHE_ROOT as KOKORO_CACHE
from speaker_helper.backends.kokoro import model_paths as kokoro_paths

#: Where the ONNX graph and the voice bank are published.
KOKORO_RELEASE: str = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
)

#: ``(filename, exact size in bytes)``. The size is the whole point — see the
#: module docstring on truncated downloads.
KOKORO_FILES: tuple[tuple[str, int], ...] = (
    ("kokoro-v1.0.onnx", 325_532_387),
    ("voices-v1.0.bin", 28_214_398),
)

#: The Ralph Eardrum Loop's ear: the wav2vec2 espeak-phoneme recogniser, at
#: the revision the loop was calibrated with, file by file with exact sizes —
#: same reasoning as Kokoro's. Read from here at run time, never downloaded
#: then (see :mod:`speaker_helper.eardrum.ear`).
EARDRUM_RELEASE: str = (
    "https://huggingface.co/facebook/wav2vec2-xlsr-53-espeak-cv-ft/resolve/"
    "2c733782da5604684829819a5eb744c193fe9398"
)
EARDRUM_FILES: tuple[tuple[str, int], ...] = (
    ("config.json", 1_856),
    ("preprocessor_config.json", 212),
    ("special_tokens_map.json", 85),
    ("tokenizer_config.json", 412),
    ("vocab.json", 4_637),
    ("pytorch_model.bin", 1_263_535_127),
)

#: Engines whose weights this module can fetch, and what it would take.
INSTALLABLE: dict[str, str] = {
    "kokoro": "~340 MB, two files, from a pinned kokoro-onnx release",
    "eardrum": "~1.26 GB, the phoneme recogniser the Ralph Eardrum Loop listens with",
    "openvoice": "checkpoints published by MyShell; see the project's README",
    "chatterbox": "fetched by the package itself on first use",
}


def _download(url: str, dest: Path) -> None:
    """Download ``url`` to ``dest``, printing a progress line.

    Writes to a ``.part`` file and renames on completion, so an interrupted
    download never leaves something at the final path that looks finished.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    print(f"→ downloading {url}")
    print(f"  into {dest}")
    with urllib.request.urlopen(url) as response:  # noqa: S310 - pinned release URL
        total = int(response.headers.get("Content-Length", "0"))
        read = 0
        with open(partial, "wb") as out:
            while True:
                buffer = response.read(1 << 20)
                if not buffer:
                    break
                out.write(buffer)
                read += len(buffer)
                if total:
                    print(
                        f"  …{100.0 * read / total:5.1f}%  "
                        f"({read / 1e6:.1f} / {total / 1e6:.1f} MB)",
                        end="\r",
                    )
    print()
    partial.replace(dest)


def install_kokoro(*, force: bool = False) -> int:
    """Fetch Kokoro's two files into the cache.

    Parameters
    ----------
    force : bool
        Re-download even when a file of the right size is already there.

    Returns
    -------
    int
        ``0`` when both files are present and the right size afterwards.
    """
    if not force and kokoro_paths() is not None:
        where = kokoro_paths()
        assert where is not None  # narrowing for type checkers
        print(f"✓ Kokoro's weights are already in {where[0].parent}")
        return 0

    KOKORO_CACHE.mkdir(parents=True, exist_ok=True)
    for filename, expected in KOKORO_FILES:
        destination = KOKORO_CACHE / filename
        if not force and destination.is_file() and destination.stat().st_size == expected:
            print(f"✓ {filename} already fetched")
            continue
        _download(f"{KOKORO_RELEASE}/{filename}", destination)
        actual = destination.stat().st_size
        if actual != expected:
            # Said out loud rather than left to fail later as a corrupt graph.
            print(
                f"✗ {filename} is {actual} bytes, expected {expected}. "
                f"The download was cut short; run this again to repair it.",
                file=sys.stderr,
            )
            return 1
    print(f"✓ Kokoro is ready in {KOKORO_CACHE}")
    return 0


def install_eardrum(*, force: bool = False) -> int:
    """Fetch the Ralph Eardrum Loop's phoneme recogniser into the cache.

    Parameters
    ----------
    force : bool
        Re-download even when a file of the right size is already there.

    Returns
    -------
    int
        ``0`` when every file is present and the right size afterwards.
    """
    # Imported here: the ear module is light, but install.py stays importable
    # even if the eardrum package were ever split out.
    from speaker_helper.eardrum.ear import PHONEME_CACHE

    PHONEME_CACHE.mkdir(parents=True, exist_ok=True)
    for filename, expected in EARDRUM_FILES:
        destination = PHONEME_CACHE / filename
        if not force and destination.is_file() and destination.stat().st_size == expected:
            print(f"✓ {filename} already fetched")
            continue
        _download(f"{EARDRUM_RELEASE}/{filename}", destination)
        actual = destination.stat().st_size
        if actual != expected:
            print(
                f"✗ {filename} is {actual} bytes, expected {expected}. "
                f"The download was cut short; run this again to repair it.",
                file=sys.stderr,
            )
            return 1
    print(f"✓ the eardrum's phoneme recogniser is ready in {PHONEME_CACHE}")
    return 0


def install_engine(engine: str, *, force: bool = False) -> int:
    """Fetch what ``engine`` needs, or say why this cannot.

    Only Kokoro is fetched here. The other two are honest refusals rather than
    silent no-ops: Chatterbox downloads its own weights on first use, and
    OpenVoice's checkpoints come with a licence the user has to meet rather
    than a URL this module should quietly pull.
    """
    name = (engine or "kokoro").lower()
    if name == "kokoro":
        return install_kokoro(force=force)
    if name == "eardrum":
        return install_eardrum(force=force)
    if name == "chatterbox":
        print(
            "Chatterbox fetches its own weights the first time it synthesises; "
            "there is nothing to install here. `pip install "
            "'speaker-helper[chatterbox]'` is the whole setup."
        )
        return 0
    if name == "openvoice":
        print(
            "OpenVoice's checkpoints are published by MyShell under their own "
            "terms, so this does not pull them for you. Fetch them, then write "
            f"a config.json pointing at them in {Path.home()}/.cache/"
            "speaker-helper/openvoice/ — `speaker-helper health` will tell you "
            "when it can see them.",
            file=sys.stderr,
        )
        return 1
    print(
        f"unknown engine {engine!r}; this can install: {', '.join(sorted(INSTALLABLE))}",
        file=sys.stderr,
    )
    return 2
