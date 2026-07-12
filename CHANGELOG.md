# Changelog

All notable changes to speaker-helper are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project aims to adhere
to [Semantic Versioning](https://semver.org/).

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
