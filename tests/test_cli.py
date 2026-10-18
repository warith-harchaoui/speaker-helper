"""
Tests for :mod:`speaker_helper.cli` — argument parsing and settings mapping.

Author
------
Warith HARCHAOUI — https://linkedin.com/in/warith-harchaoui
"""

from __future__ import annotations

from speaker_helper.cli import _build_parser, _settings_from_args


def test_synth_parses_text_and_output() -> None:
    """The synth sub-command captures positional text and output path."""
    # Act: parse a synth invocation with positional text and -o output.
    args = _build_parser().parse_args(["synth", "hello", "-o", "x.wav"])
    # Assert: command, text, and output path are captured as given.
    assert args.command == "synth"
    assert args.text == "hello"
    assert str(args.out) == "x.wav"


def test_the_voice_flag_reaches_the_settings() -> None:
    """``--voice`` names the voice that reads, wherever it sits on the line."""
    args = _build_parser().parse_args(["--voice", "ff_siwis", "synth", "hi"])
    settings = _settings_from_args(args)
    assert settings.voice == "ff_siwis"


def test_serve_bind_is_the_servers_own_socket(monkeypatch) -> None:
    """``serve --host/--port`` binds this server and configures nothing else.

    These flags used to need separate dests because a top-level --host/--port
    pointed at a *different* server — the engine's. With the engine in this
    process there is only one socket in this program, and the regression that
    made the server call itself for /health cannot recur.
    """
    args = _build_parser().parse_args(["serve", "--host", "0.0.0.0", "--port", "9000"])
    assert args.bind_host == "0.0.0.0"
    assert args.bind_port == 9000
    settings = _settings_from_args(args)
    assert settings.backend == "kokoro"
