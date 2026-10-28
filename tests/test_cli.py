"""
Tests for the command line (:mod:`speaker_helper.cli`).

The CLI is one click group over the ``_cmd_*`` handlers: the group parses, the
handlers do the work and return an exit code. So there are two things to check
and they are different — that a flag *reaches* the handler (including the
global options, which precede the sub-command), and that a command run for
real produces what it promises.

These drive the group through click's ``CliRunner`` against the deterministic
mock backend, so nothing here needs an engine, a model or a network.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from speaker_helper import __version__
from speaker_helper.cli import cli
from speaker_helper.config import Settings


@pytest.fixture
def captured(monkeypatch) -> list[tuple[SimpleNamespace, Settings]]:
    """Replace every command handler with one that records and succeeds.

    What a flag *becomes* is not visible in a command's output: ``--voice``
    changes which voice reads, and the mock backend prints neither. Swapping
    the handler table for a recorder is how the flag-to-settings path gets
    asserted on instead of assumed.
    """
    seen: list[tuple[SimpleNamespace, Settings]] = []

    def recorder(args: SimpleNamespace, settings: Settings) -> int:
        seen.append((args, settings))
        return 0

    from speaker_helper import cli as cli_module

    monkeypatch.setattr(
        cli_module, "_HANDLERS", dict.fromkeys(cli_module._HANDLERS, recorder), raising=True
    )
    return seen


def test_route_offline_prints_decision() -> None:
    """`route --condition offline` prints a quality-only decision.

    ``--language`` is a *global* option, so it precedes the sub-command:
    ``--language en route ...``. English is used here because French is
    settled by the owner's ratification rather than by the argmax (see
    :func:`test_route_offline_french_announces_the_ratification`).
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["--language", "en", "route", "--condition", "offline"])
    assert result.exit_code == 0
    # Offline picks the highest-quality engine and says so in the justification.
    assert "condition=offline" in result.output
    assert "quality is the ONLY objective" in result.output
    # Nothing was arbitrated here, so the flag must stay off the summary line.
    assert "owner_ratified" not in result.output


def test_route_offline_french_announces_the_ratification() -> None:
    """French offline prints the arbitration instead of pretending to an argmax.

    The engine did not win on the numbers — the owner chose it — so the CLI
    has to say so on the headline line, and the justification has to name the
    candidate that was set aside.
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["--language", "fr", "route", "--condition", "offline"])
    assert result.exit_code == 0
    assert "engine=chatterbox" in result.output
    assert "owner_ratified=True" in result.output
    assert "OVERRIDES the quality argmax" in result.output
    assert "kyutai" in result.output


def test_global_option_after_subcommand_is_rejected() -> None:
    """A global option placed AFTER the sub-command is a usage error."""
    runner = CliRunner()
    # The rule is "globals precede the sub-command", so `route --language fr`
    # (global after command) must fail rather than be quietly ignored.
    result = runner.invoke(cli, ["route", "--condition", "offline", "--language", "fr"])
    assert result.exit_code == 2


def test_route_online_prints_streaming_decision() -> None:
    """`route --condition online_realtime` prints a streaming decision."""
    runner = CliRunner()
    result = runner.invoke(cli, ["route", "--condition", "online_realtime"])
    assert result.exit_code == 0
    assert "mode=streaming" in result.output


def test_global_backend_before_subcommand() -> None:
    """A global option (--backend) must be accepted BEFORE the sub-command."""
    runner = CliRunner()
    # `--backend mock voices`, not `voices --backend mock`: this exercises the
    # group-level global options reaching a sub-command handler.
    result = runner.invoke(cli, ["--backend", "mock", "voices"])
    assert result.exit_code == 0
    # The mock backend advertises its two fixed voices.
    assert "mock-fr" in result.output
    assert "mock-en" in result.output


def test_synth_writes_wav(tmp_path) -> None:
    """`synth` on the mock backend writes a RIFF WAV to the output path.

    Positional text and ``-o`` together: the two halves of the invocation
    everybody types first.
    """
    out = tmp_path / "out.wav"
    runner = CliRunner()
    result = runner.invoke(cli, ["--backend", "mock", "synth", "Bonjour.", "-o", str(out)])
    assert result.exit_code == 0
    assert out.is_file()
    # The mock renders a real (decodable) WAV, so the RIFF magic must be present.
    assert out.read_bytes()[:4] == b"RIFF"


def test_route_bad_condition_is_usage_error() -> None:
    """An invalid --condition is rejected by click (exit code 2)."""
    runner = CliRunner()
    result = runner.invoke(cli, ["route", "--condition", "turbo"])
    # click validates the Choice and fails before the handler runs.
    assert result.exit_code == 2


def test_the_voice_flag_reaches_the_settings(captured) -> None:
    """``--voice`` names the voice that reads, through the global option."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--voice", "ff_siwis", "voices"])
    assert result.exit_code == 0
    _args, settings = captured[-1]
    assert settings.voice == "ff_siwis"


def test_serve_bind_is_the_servers_own_socket(captured) -> None:
    """``serve --bind-host/--bind-port`` binds this server, and nothing else.

    The long spelling exists because a global ``--host``/``--port`` once aimed
    at a *different* server — the engine's, back when it was a separate
    process. Two pairs one word apart on the same line is how a server ends up
    calling itself for /health, and that cannot recur while the two spellings
    cannot be confused.
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", "--bind-host", "0.0.0.0", "--bind-port", "9000"])
    assert result.exit_code == 0
    args, settings = captured[-1]
    assert args.bind_host == "0.0.0.0"
    assert args.bind_port == 9000
    # Nothing about the bind address touches which engine speaks.
    assert settings.backend == "kokoro"


def test_serve_refuses_the_old_host_spelling() -> None:
    """``serve --host`` must fail loudly, not be re-read as something else.

    The removed argparse front-end spelled the bind address ``--host``/
    ``--port``. Accepting those spellings here would be worse than rejecting
    them: a global ``--host`` used to mean the *remote engine*, so an alias
    would silently change what an old command line does. click rejects the
    unknown option and suggests ``--bind-host``.
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", "--host", "0.0.0.0"])
    assert result.exit_code == 2
    assert "--bind-host" in result.output


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_answers_to_both_spellings(flag: str) -> None:
    """``-h`` is the first thing a user tries; it must not be a usage error."""
    runner = CliRunner()
    result = runner.invoke(cli, [flag])
    assert result.exit_code == 0
    assert "Commands:" in result.output


@pytest.mark.parametrize("flag", ["-V", "--version"])
def test_version_answers_with_the_package_version(flag: str) -> None:
    """``-V`` reports the version of *this* checkout, not of the last wheel.

    Capital because ``-v`` means verbose everywhere in this suite, and the
    number is handed to click explicitly: read from the installed distribution
    metadata it would report whatever was last pip-installed, which is how an
    editable checkout comes to announce a stale version.
    """
    runner = CliRunner()
    result = runner.invoke(cli, [flag])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_the_group_help_carries_no_docstring_scaffolding() -> None:
    """Help text is read by users; reStructuredText markup is not help.

    click renders a docstring verbatim, so double-backtick markup reaches the
    terminal as literal backticks, and a numpydoc ``Parameters`` block reaches
    it as one reflowed paragraph.
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert "``" not in result.output
    assert "Parameters" not in result.output
    assert "----------" not in result.output
