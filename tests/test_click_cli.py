"""
Tests for the click CLI front-end (:mod:`speaker_helper.click_cli`).

The click CLI is only a parser: it must build the same namespace the argparse
handlers expect and route global options (which precede the sub-command) into
each command. These tests drive it through click's ``CliRunner`` against the
deterministic mock backend, so no TTS server is needed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("click")
from click.testing import CliRunner  # noqa: E402

from speaker_helper.click_cli import cli  # noqa: E402


def test_route_offline_prints_decision() -> None:
    """`route --condition offline` prints a quality-only decision.

    ``--language`` is a *global* option, so it precedes the sub-command
    (``--language fr route ...``) — the argparse-parity contract.
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["--language", "fr", "route", "--condition", "offline"])
    assert result.exit_code == 0
    # Offline picks the highest-quality engine and says so in the justification.
    assert "condition=offline" in result.output
    assert "quality is the ONLY objective" in result.output


def test_global_option_after_subcommand_is_rejected() -> None:
    """A global option placed AFTER the sub-command is a usage error."""
    runner = CliRunner()
    # This documents the parity rule: globals precede the sub-command, so
    # `route --language fr` (global after command) must fail.
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
    # This is the argparse-parity contract: `--backend mock voices`, not
    # `voices --backend mock`. It exercises the group-level global options.
    result = runner.invoke(cli, ["--backend", "mock", "voices"])
    assert result.exit_code == 0
    # The mock backend advertises its two fixed voices.
    assert "mock-fr" in result.output
    assert "mock-en" in result.output


def test_synth_writes_wav(tmp_path) -> None:
    """`synth` on the mock backend writes a RIFF WAV to the output path."""
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
