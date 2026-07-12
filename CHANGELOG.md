# Changelog

All notable changes to speaker-helper are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project aims to adhere
to [Semantic Versioning](https://semver.org/).

## [0.4.0] — 2026-07-12

### Added
- **Speech-to-speech sources** (`speaker_helper.sources`): bring audio in and
  re-voice it. `from_youtube` (extra `youtube`), `from_podcast` (extra
  `podcast`), `from_microphone` (extra `mic`), and `revoice()` — transcribe with
  `vocal-helper`, then speak the transcript (cloned voice / new language).
- CLI `speak-from --source youtube|podcast|mic` for one-shot re-voicing.
- **DeepEval integration** (`speaker_helper.eval.deepeval_metrics`, extra
  `eval`): `RealTimeFactorMetric` and `AudioIntegrityMetric` adapt the native
  measurements as DeepEval custom metrics — deterministic and offline.

## [0.3.0] — 2026-07-12

### Added
- **MCP server.** When `fastapi-mcp` is installed (bundled with the `server`
  extra), the REST endpoints are exposed as Model Context Protocol tools at
  `/mcp` — so an assistant can `synth`, `synth_stream`, `clone_voice`,
  `list_voices`, and `health` directly. `create_app(enable_mcp=False)` opts out.
- Stable `operation_id`s on every route, used as the MCP tool names.

### Fixed
- Pinned `os-helper` to `v1.4.1` to match `audio-helper`, resolving a pip
  dependency conflict that broke a clean install.

## [0.2.0] — 2026-07-12

### Added
- **Backend abstraction.** A `TTSEngine` protocol with a backend registry;
  Voicebox is now one backend behind it. A deterministic, serverless
  `MockEngine` ships for tests, CI, and the evaluation layer.
- **Voice cloning, everywhere** (`Speaker.clone_voice`, CLI `clone` + `--clone*`
  flags, REST `POST /clone`). Give only a recording: over-long audio is trimmed
  with `audio-helper` and the transcript is derived with `vocal-helper`. A
  bundled reference (`assets/ref-malo.wav`) is the default.
- **AI evaluation layer** (`speaker_helper.eval`): committed French dataset,
  metrics (RTF, audio anomalies, WER, chrF), quality priors + Pareto selection,
  versioned thresholds, and a `speaker-helper eval` command that gates CI via
  its exit code.
- **Streaming HTTP endpoint** `POST /synth/stream` (Server-Sent Events, one
  chunk per sentence with base64 WAV + timing).
- **Robustness**: httpx retries with exponential backoff on transient failures,
  and engine warm-up at server startup.

### Changed
- Adopted the **AI Helpers ecosystem**: logging through `os-helper`, audio
  slicing/concatenation through `audio-helper` (both installed from git). New
  optional `stt` extra pulls `vocal-helper` for transcription.
- `Settings` gains `backend`, `clone`, and `mock`; `Speaker` exposes `engine`
  (with a backward-compatible `client` alias) and `warmup`.
- Health and eval report the active backend rather than assuming Voicebox.

### Guardrails
- A committed `commit-msg` hook (`.githooks/`) refuses any AI-assistant
  attribution in commit messages; authorship stays with human maintainers.

## [0.1.0] — 2026-07-12

### Added
- Initial release: text-to-speech over a local Voicebox engine, the inverse of
  `vocal-helper`.
- `Speaker` façade with **offline** (`say`) and **streaming** (`stream`) modes;
  streaming reports time-to-first-audio and keeps emission in order.
- Typed async `VoiceboxClient`: idempotent preset-profile bootstrap,
  synchronous `POST /generate/stream`, and an automatic async `/generate`
  fallback that triggers the model download on a fresh engine.
- `Settings` (YAML + `${VAR}` expansion + `SPEAKER_HELPER_*` env overrides).
- CLI: `speaker-helper synth | voices | serve`.
- REST API server (`FastAPI` + `uvicorn`) with `/health`, `/voices`, `/synth`.
- Docker image and `docker-compose.yml` for the server.
- Tests (pytest, deterministic units + `@slow` live integration) and CI.
