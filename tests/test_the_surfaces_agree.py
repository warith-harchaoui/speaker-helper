"""
Five surfaces, one engine, and nothing that says otherwise.

The risk is never that a surface is missing — a missing one is obvious the
first time somebody looks for it. The risk is that they quietly stop agreeing:
a command reachable from one front door and not the other, a route the MCP
catalogue never republishes, a skill telling a reader to run something `pip
install` never created, a reference file nothing wrote.

None of that is hypothetical in this suite. Packaging a sibling package turned
up five commands announcing a different name from the one installed, four
exported names that existed nowhere, and a route that would have returned 500
on every call. Each was found by checking rather than by reading.

Nothing here needs a model, a network or an extra.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 — tomllib landed in 3.11
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
CONSOLE_SCRIPTS: dict[str, str] = PYPROJECT["project"]["scripts"]
EXTRAS = set(PYPROJECT["project"].get("optional-dependencies", {}))
SKILL = ROOT / "skills" / "speaker-helper" / "SKILL.md"


# ── 1. Library ─────────────────────────────────────────────────────────────


def test_the_package_exports_an_engine_not_a_version_string() -> None:
    """A library surface that exports no callable is not a library surface."""
    import speaker_helper

    callables = [
        name
        for name in speaker_helper.__all__
        if not name.startswith("__") and callable(getattr(speaker_helper, name))
    ]
    assert len(callables) > 10


def test_the_library_imports_with_no_model_anywhere() -> None:
    """A bare install must import, parse segments and write WebVTT.

    The ONNX runtime and torch arrive with an extra. Importing the package
    must not reach either, or the promise that a caller can build a narration
    plan on any machine is not a promise.

    Run in a subprocess, and that is not fussiness: in-process, ``sys.modules``
    carries whatever *any earlier test* imported, so this passed alone and
    failed in the suite — measuring the session rather than the package.
    """
    import subprocess
    import sys
    import textwrap

    done = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import sys
                from speaker_helper import Segment, cues_to_vtt  # noqa: F401
                leaked = sorted(
                    m for m in sys.modules
                    if m.split(".")[0] in ("onnxruntime", "torch", "kokoro_onnx")
                )
                assert not leaked, leaked
                print("OK")
                """
            ),
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert "OK" in done.stdout


@pytest.mark.parametrize("name", ["Speaker", "Settings", "Segment", "NarrationResult"])
def test_every_advertised_name_exists(name: str) -> None:
    """An export that resolves to nothing is a promise the module cannot keep."""
    import speaker_helper

    assert hasattr(speaker_helper, name)


# ── 2. Both command lines ──────────────────────────────────────────────────


def test_both_front_doors_are_installed() -> None:
    """argparse because it is always there, click because it carries shapes."""
    assert "speaker-helper" in CONSOLE_SCRIPTS
    assert "speaker-helper-argparse" in CONSOLE_SCRIPTS
    assert "speaker-helper-mcp" in CONSOLE_SCRIPTS


def test_the_two_front_doors_offer_the_same_commands() -> None:
    """A command on one and not the other is the failure a twin invites."""
    import click

    from speaker_helper.cli import _build_parser
    from speaker_helper.click_cli import cli

    argparse_commands = set()
    for action in _build_parser()._actions:
        if getattr(action, "choices", None) and isinstance(action.choices, dict):
            argparse_commands |= set(action.choices)

    with click.Context(cli) as ctx:
        click_commands = set(cli.list_commands(ctx))

    assert argparse_commands == click_commands, (
        f"only in argparse: {sorted(argparse_commands - click_commands)}; "
        f"only in click: {sorted(click_commands - argparse_commands)}"
    )


def test_every_command_has_a_handler() -> None:
    """A sub-command the dispatcher does not know is a parse error at runtime."""
    from speaker_helper.cli import _build_parser
    from speaker_helper.click_cli import _HANDLERS

    declared = set()
    for action in _build_parser()._actions:
        if getattr(action, "choices", None) and isinstance(action.choices, dict):
            declared |= set(action.choices)
    assert declared <= set(_HANDLERS), f"no handler for {sorted(declared - set(_HANDLERS))}"


# ── 3 & 4. HTTP and MCP ────────────────────────────────────────────────────


def test_the_api_constructs_and_mounts_its_agent_surface() -> None:
    """Both at once, because the second used to break the first.

    fastapi-mcp 0.4.0 raised a TypeError out of create_app() and a guard that
    only caught ImportError let it through — so an optional surface took down
    every API test. The app must construct either way.
    """
    from speaker_helper.api import create_app
    from speaker_helper.config import Settings

    app = create_app(Settings.from_mapping({"backend": "mock"}))
    paths = {route.path for route in app.routes}
    assert "/synth" in paths and "/narrate" in paths
    # /mcp only when the extra is installed; its absence must not be a failure.
    pytest.importorskip("fastapi_mcp")
    assert "/mcp" in paths


def test_narration_is_reachable_over_http() -> None:
    """The route exists to return cues; returning only audio would be /synth."""
    from fastapi.testclient import TestClient

    from speaker_helper.api import create_app
    from speaker_helper.config import Settings

    client = TestClient(create_app(Settings.from_mapping({"backend": "mock"})))
    answer = client.post("/narrate", json={"segments": [{"text": "Un."}, {"text": "Deux."}]})
    assert answer.status_code == 200
    body = answer.json()
    assert body["vtt"].startswith("WEBVTT")
    assert [cue["index"] for cue in body["cues"]] == [0, 1]
    assert body["audio_wav_base64"]


# ── 5. The skill ───────────────────────────────────────────────────────────


def test_the_skill_ships_where_the_suite_puts_it() -> None:
    """One skill per package, at skills/<package>/SKILL.md."""
    assert SKILL.is_file()


def test_the_skill_points_at_files_that_exist() -> None:
    """A reference nothing wrote is a dead end discovered by the reader."""
    body = SKILL.read_text(encoding="utf-8")
    referenced = set(re.findall(r"`references/([a-z-]+\.md)`", body))
    present = {p.name for p in (SKILL.parent / "references").glob("*.md")}
    assert referenced <= present, f"dangling: {sorted(referenced - present)}"


def test_the_skill_only_tells_the_reader_to_run_real_commands() -> None:
    """``--help`` advertising a command nothing installs is the classic rot."""
    body = SKILL.read_text(encoding="utf-8")
    advertised = set(re.findall(r"\b(speaker-helper(?:-[a-z]+)*)\b", body))
    # Sub-commands are not console scripts; only the bare program names are.
    programs = {name for name in advertised if name in {*CONSOLE_SCRIPTS, "speaker-helper"}}
    unknown = advertised - programs - {"speaker-helper"}
    assert not unknown - set(CONSOLE_SCRIPTS), f"not installed: {sorted(unknown)}"


def test_the_skill_names_extras_pip_can_resolve() -> None:
    """An install line that pip refuses is worse than no install line."""
    body = SKILL.read_text(encoding="utf-8")
    named = set(re.findall(r"speaker-helper\[([a-z,\-]+)\]", body))
    for group in named:
        for extra in group.split(","):
            assert extra in EXTRAS, f"SKILL.md names [{extra}], pyproject does not declare it"


# ── The version says one thing ─────────────────────────────────────────────


def test_every_version_source_agrees() -> None:
    """A wheel that reports a different version than it is.

    Found by installing 0.8.0 into a clean virtualenv and asking it: it
    answered 0.7.6, because the bump had touched pyproject.toml and not the
    package. Nothing in the repository could tell — the two numbers are only
    compared once a wheel exists, and by then it is usually published.

    The consequence is not cosmetic. `--version`, the API's `/health`, and
    whatever a user pastes into a bug report all read the package, while pip,
    the floors in a sibling's extra, and the index read the wheel.
    """
    import speaker_helper

    assert speaker_helper.__version__ == PYPROJECT["project"]["version"]
