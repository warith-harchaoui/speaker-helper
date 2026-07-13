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
    args = _build_parser().parse_args(["synth", "hello", "-o", "x.wav"])
    assert args.command == "synth"
    assert args.text == "hello"
    assert str(args.out) == "x.wav"


def test_top_level_overrides_voicebox() -> None:
    """Top-level --host/--port map onto the Voicebox connection."""
    args = _build_parser().parse_args(["--port", "17600", "synth", "hi"])
    settings = _settings_from_args(args)
    assert settings.voicebox.port == 17600


def test_serve_bind_does_not_clobber_voicebox_port(monkeypatch) -> None:
    """`serve --port` binds the server without changing the Voicebox port.

    Regression: the serve bind flags must not collide with the top-level
    Voicebox --host/--port, or the server would call itself for /health.
    """
    monkeypatch.setenv("SPEAKER_HELPER_VOICEBOX_PORT", "17600")
    args = _build_parser().parse_args(["serve", "--host", "0.0.0.0", "--port", "9000"])
    assert args.bind_host == "0.0.0.0"
    assert args.bind_port == 9000
    settings = _settings_from_args(args)
    # The Voicebox port stays what the environment configured, not 9000.
    assert settings.voicebox.port == 17600
