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


# ── 2. The command line ────────────────────────────────────────────────────

# The ten sub-commands the CLI promises. Spelled out here rather than read
# back from the group, because a list derived from the code cannot notice a
# command that quietly stopped being registered in it.
COMMANDS = {
    "clone",
    "eval",
    "health",
    "install-voice",
    "narrate",
    "route",
    "serve",
    "speak-from",
    "synth",
    "voices",
}


def test_the_console_scripts_are_the_cli_and_the_agent_surface() -> None:
    """One command line, plus the launcher for a surface that is not one.

    There used to be a second entry point — `speaker-helper-argparse`, the
    same commands through a different parser. A flag naming the parsing
    library describes the implementation, not the interface, so it is gone;
    this asserts it cannot come back under any suffix.
    """
    assert "speaker-helper" in CONSOLE_SCRIPTS
    # `-mcp` starts the agent tool server: a different surface, not a second
    # way to type the same commands.
    assert "speaker-helper-mcp" in CONSOLE_SCRIPTS
    suffixed = {
        name
        for name in CONSOLE_SCRIPTS
        if name.startswith("speaker-helper-") and name != "speaker-helper-mcp"
    }
    assert not suffixed, f"the CLI has grown an alias again: {sorted(suffixed)}"


def test_the_command_line_offers_every_command_it_promises() -> None:
    """A command nothing registers any more is the failure to catch here."""
    import click

    from speaker_helper.cli import cli

    with click.Context(cli) as ctx:
        registered = set(cli.list_commands(ctx))

    assert registered == COMMANDS, (
        f"missing: {sorted(COMMANDS - registered)}; unannounced: {sorted(registered - COMMANDS)}"
    )


def test_every_command_has_a_handler() -> None:
    """A sub-command the handler table does not know is a KeyError at runtime."""
    import click

    from speaker_helper.cli import _HANDLERS, cli

    with click.Context(cli) as ctx:
        registered = set(cli.list_commands(ctx))
    assert registered <= set(_HANDLERS), f"no handler for {sorted(registered - set(_HANDLERS))}"


# Where a reader copies a command line from.
DOCUMENTED = [
    "README.md",
    "LISEZMOI.md",
    "EXAMPLES.md",
    "EXEMPLES.md",
    "skills/speaker-helper/SKILL.md",
    "skills/speaker-helper/references/surfaces.md",
]


def _documented_command_lines() -> list[tuple[str, int, list[str]]]:
    """Return every ``speaker-helper …`` invocation inside a shell code fence.

    Only fenced blocks count: prose sentences open with the program name too
    ("speaker-helper is the counterpart of …") and they are not command lines.
    Continuations are joined, trailing comments dropped.
    """
    import shlex

    found: list[tuple[str, int, list[str]]] = []
    for name in DOCUMENTED:
        inside = False
        pending = ""
        start = 0
        for lineno, raw in enumerate((ROOT / name).read_text(encoding="utf-8").splitlines(), 1):
            if raw.startswith("```"):
                inside = raw.startswith(("```bash", "```sh"))
                pending = ""
                continue
            if not inside:
                continue
            # A pipeline's `speaker-helper` half is the part under test.
            text = raw.split("|")[-1].strip()
            if pending:
                text = f"{pending} {text}"
            elif not text.startswith("speaker-helper ") or text.startswith("speaker-helper-"):
                continue
            else:
                start = lineno
            if text.endswith("\\"):
                pending = text[:-1].strip()
                continue
            pending = ""
            found.append((name, start, shlex.split(re.sub(r"\s+#.*$", "", text))[1:]))
    return found


def test_every_documented_command_line_is_accepted(tmp_path) -> None:
    """A command line a reader copies has to be one the CLI still accepts.

    This is the check that was missing, and it was missing expensively. Forty
    lines across the two READMEs and the two cookbooks read `speaker-helper
    --port 17600 synth …` — a global option that went away with the
    out-of-process engine in 0.8.0 — so the first thing a reader copied
    answered `No such option '--port'`. Nothing noticed, because nothing ran
    the documentation.

    The handlers are stubbed out: what is under test is whether the *parser*
    accepts the line, not whether an engine is installed on this machine.
    """
    import json

    from click.testing import CliRunner

    from speaker_helper import cli as cli_module

    lines = _documented_command_lines()
    # A floor, so an extractor that silently stops finding anything fails too.
    assert len(lines) > 60, f"only {len(lines)} documented command lines found"

    # `narrate` takes an existing path, so the examples' filenames need to
    # resolve to something; the stub never reads them.
    fixture = tmp_path / "doc.json"
    fixture.write_text(json.dumps([{"text": "Un."}]), encoding="utf-8")

    runner = CliRunner()
    rejected = []
    for name, lineno, argv in lines:
        argv = [
            str(fixture) if arg.endswith(".json") and argv[i - 1] != "--json" else arg
            for i, arg in enumerate(argv)
        ]
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                cli_module, "_HANDLERS", dict.fromkeys(cli_module._HANDLERS, lambda a, s: 0)
            )
            result = runner.invoke(cli_module.cli, argv, input="texte\n")
        if result.exit_code != 0:
            tail = (result.output or "").strip().splitlines()[-1:]
            rejected.append(f"{name}:{lineno} exit={result.exit_code} {argv} {tail}")
    assert not rejected, "documented command lines the CLI rejects:\n" + "\n".join(rejected)


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
