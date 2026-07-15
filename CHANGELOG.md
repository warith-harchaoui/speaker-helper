# Changelog

All notable changes to speaker-helper are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project aims to adhere
to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.7.4] - 2026-07-15

### Documentation
- Harmonize README/LISEZMOI to the AI Helpers common structure (single H1, Documentation block, source install pinned to v0.7.4, PyPI-coming-soon note); no code changes.

## [0.7.3] — 2026-07-14

### Documentation
- Finalize suite wording: use plain-language capability names (Speech Synthesis) in the description and README instead of tool-specific acronyms, for consistency across the suite.

## [0.7.2] — 2026-07-14

### Maintenance
- Apply the project coding standards across the package and `tests/`: Numpy-style docstrings on every function/class (including private and nested helpers), full typing, and comment density above the floor. No public API or behavior changes.
- Route library logging through the os-helper logging surface (`osh.info/warning/error`) and adopt os-helper utilities more widely; pin `os-helper>=1.5.0`.
- Refresh the project logo asset.

## [0.7.1] — 2026-07-13

### Maintenance
- Coding-standards pass: genuine in-code narration (`#` block comments) added to
  the logic-bearing modules (metrics, text, config, engine, runner, …),
  explaining the *why* of each non-obvious step — without parrot padding.
- **PEP 8 enforced in CI**: `ruff format --check` now gates alongside
  `ruff check`; the whole tree is `ruff format`-clean.
- Ecosystem dependencies (`os-helper`, `audio-helper`, …) now resolve from
  **PyPI** instead of git pins.
- Move the private working notes under a gitignored `.private/` directory.

## [0.7.0] — 2026-07-13

### Added
- **WER/chrF fidelity gating in CI.** The round-trip *pipeline* and *threshold
  gating* now run in CI via deterministic stub transcribers (a real
  synthesis→STT round-trip needs a live engine the runner lacks). Versioned
  fidelity thresholds (`max_mean_wer: 0.20`, `min_mean_chrf: 0.75`) in
  `thresholds.yaml`. New `speaker-helper eval --transcribe` runs the *real*
  round-trip locally with `vocal-helper` (the `stt` extra), for one language or
  a `--languages` matrix.

## [0.6.0] — 2026-07-13

### Added
- **Technical report** (`docs/tech-report.en.md` + `docs/tech-report.fr.md`,
  bilingual, sharing `docs/refs.bib`): architecture, the producer/consumer
  streaming pipeline, cloning, speech-to-speech sources, the evaluation
  methodology, and the multi-language native-MLX vs CPU measurements.
- **Measured default profiles**: `DEFAULT_PROFILES` now carry reference
  native-MLX operating points (fr/en/es RTF ~0.15–0.19, quality prior),
  obtained with `tune_profiles`; recalibrate per host.

## [0.5.1] — 2026-07-12

### Documentation
- `BENCHMARKS.md`: added real **native MLX (Apple GPU)** multi-language numbers —
  kokoro synthesises **6–8× faster than real time** (fr 0.151, en 0.133, es
  0.141 RTF, all passing), versus CPU-Docker under load (RTF > 1.0). Confirms the
  native-MLX operating point on Apple Silicon.

## [0.5.0] — 2026-07-12

### Added
- **Multi-language measurement.** Bundled `en` and `es` evaluation datasets
  (alongside `fr`), `load_dataset(language=…)`, and `run_multilang_eval()` —
  runs the gate once per language (voice auto-picked per language, warmed up)
  and returns a report per language. CLI: `eval --languages fr,en,es` prints a
  matrix and gates on all. Measured against live kokoro (see `BENCHMARKS.md`).
- **Per-language operating profiles** (`speaker_helper.profiles`):
  `LanguageProfile` bundles a language's hyperparameters — voice, engine, and
  the streaming producer/consumer knobs (`first_chunk_sentences`,
  `stream_concurrency`) — plus its measured RTF/quality. `Speaker.from_profile`,
  `profile_for`, and `tune_profiles` (measure → profile) tie it together.
- Git install instructions (no PyPI yet) and a `BENCHMARKS.md` in the README /
  LISEZMOI.

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
