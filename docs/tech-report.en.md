---
title: "Speaker Helper — Technical Report"
subtitle: "Engine-agnostic text-to-speech: producer/consumer streaming, voice cloning, and a measured evaluation gate"
author: Warith HARCHAOUI
date: Summer 2026
bibliography: refs.bib
lang: en
---

# Abstract

Speaker Helper turns text into speech on your own machine. It is the output
counterpart of Vocal Helper (speech → text) in the AI Helpers ecosystem
[@aihelpers], and it wraps a *local* text-to-speech engine — Voicebox
[@voicebox] running the Kokoro model [@kokoro] by default — behind a small,
typed Python API, a CLI, a REST API, and a minimal web GUI. Two design
commitments run through the whole system. First, **the
engine is an implementation detail**: every component speaks to a `TTSEngine`
protocol, so Voicebox is one backend among others and a deterministic `mock`
backend makes the package (and its evaluation) runnable in CI without a server.
Second, **quality is measured, not asserted**: a committed dataset, versioned
thresholds, and audio-specific metrics (real-time factor, signal anomalies,
and — with a transcriber — a word-error / chrF round-trip [@popovic2015chrf])
gate the project the way unit tests gate ordinary code. That same measured
evidence feeds a **backend router** that turns an operating *condition*
(online-real-time or offline) into a concrete engine + mode with a
number-citing justification, and the whole stack can run with **self-hosted
engine and metric models** so nothing is fetched from Hugging Face at runtime.
We describe the architecture, the streaming producer/consumer pipeline, voice
cloning, speech-to-speech sources, the evaluation layer, and the router, and we
report multi-language
measurements: on Apple silicon the native MLX backend [@mlx] synthesises Kokoro
**6–8× faster than real time** across French, English and Spanish, whereas the
same engine on CPU-in-Docker is borderline and load-sensitive.

# 1. Goals & non-goals

## 1.1 Goals

- **A ready-to-use, operational toolbox**, not a study: a library, a CLI
  (argparse + click), a REST API, and a minimal web GUI that a solo developer
  or a small team can adopt without private context.
- **Engine independence.** Nothing above the backend boundary may depend on a
  concrete engine. Adding or swapping a backend is a local change.
- **Two synthesis modes.** *Offline* (whole text → one audio, optimising
  throughput) and *streaming* (sentence-split, optimising time-to-first-audio).
- **Voice cloning made trivial** — point at a recording; the transcript is
  derived automatically when absent.
- **A first-class evaluation gate** — speed and signal integrity always, fidelity
  when a transcriber is available; wired to CI via an exit code.
- **Local-first and cost-free at inference** — no hosted API, no data exfiltration.

## 1.2 Non-goals

- We do not train or ship a TTS model; we orchestrate a local engine.
- We do not re-implement speech-to-text: transcription is delegated to
  Vocal Helper (whisper.cpp [@whispercpp; @radford2023whisper]).
- We do not chase a formal, engine-independent Pareto sweep; we report an
  *operational* quality↔speed picture measured on the shipped engine.

# 2. System overview

The package is a thin, typed stack over a running engine:

```
your text ──▶ Speaker (offline · streaming · clone) ──TTSEngine──▶ engine ──▶ WAV
                     │
                     └───────────── measured by the evaluation layer
```

- **Types** (`types.py`): `Voice`, `AudioResult` (carries `wav_bytes`,
  `sample_rate`, `duration_s`, `compute_s`, and a derived `rtf`), `StreamChunk`,
  `VoiceList`, `VoiceSample`.
- **Engine boundary** (`engine.py`): the `TTSEngine` protocol —
  `synthesize`, `list_voices`, `health`, `clone_voice`, `aclose` — plus a
  backend registry. Two backends ship: `VoiceboxClient` (real) and `MockEngine`
  (deterministic, serverless).
- **Façade** (`speaker.py`): `Speaker` — `say`, `stream`, `clone_voice`,
  `warmup`, `from_profile`.
- **Interfaces**: CLI (`cli.py`), REST API (`api.py`, [@fastapi]).
- **Evaluation** (`eval/`): datasets, metrics, thresholds, runner, priors,
  DeepEval binding [@deepeval], multi-language driver.
- **Ecosystem glue**: logging via `os-helper`, audio slicing/concatenation via
  `audio-helper`, transcription via Vocal Helper [@aihelpers].

## 2.1 Wire format

Audio crosses the engine boundary as an in-memory WAV `bytes` payload plus the
metadata a caller needs to save, stream, or *measure* it. Real-time factor
(RTF), the study's central quantity, is `compute_s / duration_s`: below `1.0`
means faster than real time. It is derived from the `AudioResult`, never guessed.

# 3. Per-component design

## 3.1 The engine boundary

`create_engine(settings)` dispatches on `settings.backend`. The `voicebox`
backend hides three awkward details of the Voicebox REST API: idempotent
*profile* bootstrap (a preset or a cloned voice), a synchronous
`POST /generate/stream` path with a transparent fallback to the async
`/generate` path that triggers a first-time model download, and retries with
exponential backoff on transient (transport / 5xx) failures. The `mock` backend
renders a deterministic sine tone whose duration tracks the input length and
whose `compute_s` reproduces a configured RTF — enough to exercise every code
path, including the evaluation's anomaly checks, without a server.

## 3.2 Offline and streaming: a producer/consumer pipeline

`Speaker.say` synthesises the whole text in one call. `Speaker.stream` is a
bounded **producer/consumer** pipeline: a *producer* splits the text into
sentence-sized chunks (`text.py`) and *consumers* synthesise them under a
semaphore of size `stream_concurrency`, while emission stays strictly in text
order. Two hyperparameters trade time-to-first-audio (TTFA) against throughput:

- `first_chunk_sentences` (producer granularity) — `1` makes the first chunk as
  small as possible, so the first audio is emitted soonest.
- `stream_concurrency` (consumer parallelism) — the default `1` is a strict
  pipeline: because a fast engine synthesises each later chunk before the
  previous one finishes playing, TTFA is minimised without starving playback.

Concretely, with Kokoro synthesising well below real time, the strict pipeline
(`stream_concurrency = 1`) reaches first audio in ≈ 0.8 s, versus ≈ 2.7 s when a
larger first batch is synthesised before anything is emitted — so a smaller
producer granularity and a strict consumer are the low-latency default. These
knobs, together with the voice and engine choice, are the per-language
*operating profile* of §5.3.

## 3.3 Voice cloning

Cloning is uniform across the library, CLI, and REST API. The caller supplies
one or more reference recordings; over-long audio is trimmed to the engine's
limit with `audio-helper`, and a missing transcript is derived with
Vocal Helper and cached in a sidecar. A ready-to-use reference ships as the
default, so `--clone` alone produces a cloned voice. Cloning is exposed on the
`TTSEngine` protocol, so a backend that cannot clone fails explicitly rather
than silently.

## 3.4 Speech-to-speech sources

`sources.py` closes the speech-to-speech loop: `from_youtube` [@ytdlp],
`from_podcast`, and `from_microphone` bring audio in, and `revoice` transcribes
it (Vocal Helper) and speaks the transcript back through a `Speaker` — in a
cloned voice or another language. All third-party imports are lazy and gated
behind optional extras, so the core stays light.

# 4. Evaluation methodology

The project's contract forbids "vibe checks": anything AI must clear a committed
bar. The evaluation targets the engine-agnostic `Speaker`, so the identical gate
grades the `mock` backend in CI or a real engine locally — only `backend`
differs.

## 4.1 Metrics

All metrics are pure-Python and dependency-free at the core:

- **Speed.** Per-utterance RTF, summarised by mean and 95th percentile.
- **Signal anomalies.** `detect_anomalies` flags, from the audio alone,
  `empty_audio`, `invalid_sample_rate`, `clipping` (a sample at full scale),
  and `duration_too_short` / `duration_too_long` (characters-per-second outside
  a plausible band — truncation or a runaway stretch). The anomaly *rate* is the
  gated quantity.
- **Fidelity round-trip (optional).** When a transcriber is injected, the audio
  is re-transcribed and compared to the reference text with **word error rate**
  (a Levenshtein token distance [@levenshtein1966]) and **chrF** (character
  n-gram F-score [@popovic2015chrf]); both are implemented in-tree to avoid a
  heavy dependency.

## 4.2 Thresholds, priors, and Pareto selection

The pass/fail bar lives in a committed `thresholds.yaml`: RTF `< 1.0` (mean and
p95), zero tolerated anomaly rate, and — only when a transcriber runs — WER/chrF
gates. A quality axis is *always* reported: measured chrF when available, else a
per-engine **prior** in `[0, 1]`, so speed↔quality selection works without a
transcriber. `pareto_front` extracts the non-dominated engines/languages on the
quality↔RTF plane [@deb2001multiobjective] — the operational answer to "which
setting should I ship?".

## 4.3 A DeepEval binding

Because the measurements are audio-specific, we do not force a text-only
framework to measure audio; instead we *adapt* the measurements as DeepEval
[@deepeval] custom metrics (`RealTimeFactorMetric`, `AudioIntegrityMetric`, and
`RoundTripIdempotenceMetric` — the text→speech→text chrF check). They are
deterministic and offline — no LLM, key, or network — so teams that standardise
on DeepEval get the same numbers inside their existing harness.

## 4.4 Backend routing

The evaluation layer *measures* quality and speed; the **router**
(`speaker_helper.router`: `route`, `RouteRequest`, `RouteDecision`,
`Speaker.from_route`) *acts* on that evidence. The caller states an operating
**condition** and the router returns a concrete engine + mode, justified by the
numbers rather than guessed:

- **`online_realtime`** — delay-bounded streaming. Speed is the **real-time
  factor (RTF)** and defines a hard feasibility boundary: an engine is admissible
  only if it synthesises *faster than real time* (`RTF < 1`), with a margin for
  time-to-first-audio and jitter (ceiling `0.8`). Among the engines that keep up,
  the router **maximises quality** on the quality↔RTF Pareto front [@deb2001multiobjective]
  and selects streaming with low-TTFA knobs.
- **`offline`** — batch. There is no real-time constraint, so **quality is the
  only objective**: the highest-quality engine wins and speed is disregarded.

Quality is round-trip **intelligibility** (text→speech→text WER/chrF) when an
engine has been measured, else an inherited per-engine prior; every
`RouteDecision` records which via `quality_source` (measured vs prior), carries a
`confidence` flag, and a number-citing `justification`. New engines are
characterised in the companion study and folded back here as data, so the router
improves as the evidence grows without any code change.

## 4.5 Self-hosted engines (no Hugging Face)

By default the engine server downloads model weights from Hugging Face on first
use. For a production or air-gapped host, an optional `speaker-engines` bundle
(hosted at `https://harchaoui.org/warith/speaker-engines/`) serves every TTS engine —
**and the evaluation metric models** — from a single self-hosted archive. The
consumer downloads and unzips it, then points the runtime at it with
`VOICEBOX_MODELS_DIR=$HOME/speaker-engines/tts` and `HF_HUB_OFFLINE=1`, so
nothing is fetched from Hugging Face at runtime.

# 5. Measurements

Hardware: Apple M2 Max. Engine: Kokoro [@kokoro] on Voicebox [@voicebox].
Datasets: 10–12 committed reference utterances per language, voice auto-picked
per language and warmed up. Quality is the engine prior (no transcriber here);
anomaly rate is zero in every run below.

## 5.1 Native MLX (Apple GPU / Metal) — the recommended operating point

| language | cases | mean RTF | p95 RTF | verdict |
| -------- | ----: | -------: | ------: | ------- |
| fr       | 12    | **0.151**| 0.201   | PASS    |
| en       | 10    | **0.133**| 0.150   | PASS    |
| es       | 10    | **0.141**| 0.170   | PASS    |

The native backend on the Apple GPU synthesises **6–8× faster than real time**
in every language. This is Speaker Helper's default port (`:17493`).

## 5.2 CPU inside Docker — for contrast

| language | cases | mean RTF | p95 RTF | verdict          |
| -------- | ----: | -------: | ------: | ---------------- |
| fr       | 12    | 1.341    | 1.723   | FAIL (RTF > 1.0) |
| en       | 10    | 1.131    | 1.470   | FAIL (RTF > 1.0) |
| es       | 10    | 1.287    | 1.678   | FAIL (RTF > 1.0) |

CPU synthesis is borderline and load-sensitive: on an idle host French measured
≈ 0.32–0.37 (passing), but under contention it climbs above 1.0. Docker on macOS
has **no GPU/Metal passthrough**, which explains the ~8× gap with §5.1. Crucially,
*quality and integrity hold in both regimes* (zero anomalies everywhere); only
speed misses the bar on loaded CPU — exactly what the gate is meant to catch.

## 5.3 Per-language operating profiles

`LanguageProfile` bundles a language's voice/engine and its producer/consumer
knobs together with a **measured operating point**. `tune_profiles` measures a
set of languages and folds each report's RTF/quality back into its profile. The
shipped defaults carry the §5.1 reference numbers (M2 Max, native MLX); a
different host recalibrates them with one call.

# 6. Interfaces

The same core is exposed over five surfaces:

- **CLI**: a primary [click](https://click.palletsprojects.com) group with global
  options preceding the sub-command, and the standard-library argparse front-end
  kept as `speaker-helper-argparse`. Sub-commands: `synth`, `voices`, `clone`,
  `route`, `eval` (with `--languages` for a matrix), `speak-from`
  (speech-to-speech), `serve`.
- **REST**: `GET /health`, `GET /voices`, `POST /synth`, `POST /synth/stream`
  (Server-Sent Events, one JSON chunk per sentence [@sse]), `POST /clone`, and
  `POST /route` (the backend router).
- **Web GUI**: a minimal, dependency-free vanilla-JS + Tailwind page served at
  `/` for synth, streaming, voices, cloning, and the router.

# 7. Limitations & future work

- The RTF numbers are hardware- and load-dependent; the evaluation, not a static
  table, is the source of truth — re-run it on your host.
- Fidelity has two halves. The WER/chrF *pipeline and threshold gating* run in
  CI with deterministic stub transcribers (a real synthesis→STT round-trip needs
  a live engine the hosted runner lacks); the *real* round-trip runs locally via
  `speaker-helper eval --transcribe` (the `stt` extra).
- The bundled clone reference ships in the source tree; packaging it into the
  wheel is pending.
- Planned: measured multi-engine Pareto matrices per language, and richer
  speech-to-speech pipelines over the source packages.

# References
