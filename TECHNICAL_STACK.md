# Technical Stack — speaker-helper

How speaker-helper is put together, what each layer does, and where it sits in
the **AI Helpers** ecosystem.

---

## Architecture

```mermaid
flowchart TB
    subgraph clients["Entry points (4 surfaces)"]
        lib["Python API<br/>Speaker · route"]:::core
        cli["CLI (click)<br/>synth · narrate · voices · clone · eval · route · serve · health · install-voice · speak-from"]:::core
        api["REST API + MCP<br/>/synth · /synth/stream · /narrate · /clone · /voices · /route · /health · /mcp"]:::core
        gui["Web GUI<br/>served at /"]:::core
    end

    speaker["Speaker façade<br/>offline · streaming · clone · warmup"]:::core
    router["router<br/>condition → engine + mode"]:::core
    text["text splitter<br/>sentence chunks → low TTFA"]:::util

    subgraph engines["TTSEngine protocol — backends, all in this process"]
        kokoro["KokoroEngine (streaming default)<br/>ONNX Runtime · 54 voices"]:::engine
        cloning["ChatterboxEngine (offline default) · OpenVoiceEngine<br/>Audio8Engine · Qwen3TTSEngine<br/>cloning"]:::engine
        kyutai["KyutaiEngine<br/>native FR+EN · voice bank"]:::engine
        cloud["ElevenLabsEngine<br/>cloud · paid · only when named"]:::engine
        mock["MockEngine<br/>deterministic · no model"]:::engine
    end

    subgraph evallayer["Evaluation gate"]
        metrics["metrics<br/>RTF · anomalies · WER · chrF"]:::eval
        priors["priors + Pareto<br/>quality↔RTF"]:::eval
        thresholds["versioned thresholds<br/>CI gating"]:::eval
    end

    subgraph ecosystem["AI Helpers ecosystem"]
        osh["os-helper<br/>logging · temp files"]:::eco
        ah["audio-helper<br/>slice · concatenate"]:::eco
        vh["vocal-helper (stt)<br/>transcription"]:::eco
    end

    weights[("weights cache<br/>~/.cache/speaker-helper/kokoro")]:::ext
    espeak["espeak-ng<br/>phonemisation"]:::ext

    lib --> speaker
    cli --> speaker
    api --> speaker
    gui --> api
    speaker --> text
    router -.->|picks engine + mode| speaker
    speaker -- "TTSEngine" --> kokoro
    speaker -- "TTSEngine" --> cloning
    speaker -- "TTSEngine" --> kyutai
    speaker -- "TTSEngine" --> cloud
    speaker -- "TTSEngine" --> mock
    weights -.->|loaded once| kokoro
    espeak -.->|phonemes| kokoro
    speaker -.->|measured by| metrics
    metrics --> priors --> thresholds
    priors -.->|evidence| router
    speaker -.->|logging| osh
    speaker -.->|clone trim/concat| ah
    speaker -.->|clone transcript| vh

    classDef core fill:#CCE4FF,stroke:#007AFF,color:#000000
    classDef util fill:#FFF5CC,stroke:#FFCC00,color:#000000
    classDef engine fill:#EFDCF8,stroke:#AF52DE,color:#000000
    classDef eval fill:#D4F5D9,stroke:#28CD41,color:#000000
    classDef eco fill:#FFD5DD,stroke:#FF2D55,color:#000000
    classDef ext fill:#FFEACC,stroke:#FF9500,color:#000000
```

---

## Layers

| Layer | Module | Responsibility |
|------|--------|----------------|
| Types | `types.py` | `Voice`, `AudioResult` (+`rtf`), `StreamChunk`, `VoiceList`, `VoiceSample` |
| Config | `config.py` | YAML + `${VAR}` + `SPEAKER_HELPER_*` overrides; `backend`, `clone`, `mock` |
| Engine | `engine.py` | `TTSEngine` protocol, backend registry, `MockEngine` |
| Backends | `backends/` | `kokoro.py` (streaming default, ONNX in-process), `chatterbox.py` (offline default), `openvoice.py`, `kyutai.py`, `audio8.py` (`audio8` and `qwen3tts`, MLX), `elevenlabs.py` (cloud, paid) |
| Install | `install.py` | fetches Kokoro's ~340 MB from a pinned release, size-checked |
| Façade | `speaker.py` | `Speaker` — `say` / `stream` / `clone_voice` / `warmup` / `from_profile` / `from_route` |
| Router | `router.py` | condition (`online_realtime` / `offline`) → engine + mode from measured quality↔speed evidence, minus the languages the owner has arbitrated himself (`OFFLINE_RATIFIED_ENGINE`, flagged `owner_ratified`) |
| Profiles | `profiles.py` | per-language hyperparameters (producer/consumer) + measured RTF/quality |
| Text | `text.py` | sentence splitting for low time-to-first-audio |
| Chunking | `chunking.py` | long texts cut at discourse boundaries, LLM-assisted |
| Lexicon | `lexicon.py` | per-word pronunciation overrides (IPA or respelling) applied before synthesis |
| Spoken numbers | `spoken_numbers.py` | dates, times, amounts and numbers said as words (French, English) |
| Speech text | `speech_text.py` | notation (math) turned into the words the voice says |
| Narration | `narration.py` | a document read aloud, with the timed cues (WebVTT) a page can follow |
| Voices | `voices.py` | curated preset voices by language and gender |
| CLI | `cli.py` | `synth`, `narrate`, `voices`, `clone`, `eval`, `speak-from`, `route`, `serve`, `health`, `install-voice` — one click group over the shared `_cmd_*` handlers |
| API | `api.py` | FastAPI — offline, SSE streaming, `/narrate`, cloning upload, `/route`, GUI at `/` |
| MCP | `mcp.py` | `speaker-helper-mcp`: the same routes as agent tools, mounted at `/mcp` |
| GUI | `gui/` | minimal vanilla-JS + Tailwind single page (synth / stream / voices / clone / route) |
| Cloning | `cloning.py` | clone defaults (ref-fr-female), trim + transcript preparation |
| Transcription | `transcription.py` | `vocal-helper` adapter (clone transcript + eval round-trip) |
| Sources | `sources.py` | speech-to-speech in: youtube / podcast / microphone → `revoice` |
| Evaluation | `eval/` | dataset, metrics, priors/Pareto, thresholds, runner, DeepEval metrics (incl. round-trip idempotence) |

---

## Design choices

- **Backend-agnostic core, and no second process.** Everything talks to the
  `TTSEngine` protocol, never to a concrete engine: `create_engine(settings)`
  looks `settings.backend` up in a module-level registry. Eight backends are
  registered — `kokoro` (the streaming default), `chatterbox` (the offline
  default), `openvoice`, `kyutai`, `audio8`, `qwen3tts`, `elevenlabs` and
  `mock` — and every local one synthesises in the calling process;
  `elevenlabs`, the paid cloud, runs only when named. The package shipped
  another once, a REST client for a desktop application on a fixed port; it was
  removed when the default moved in-process, because an engine you have to
  install, launch and keep alive is not a second option but a second way to
  fail. `register_backend` adds your own with one call.
- **Low time-to-first-audio.** Streaming splits text into sentence chunks and
  pipelines synthesis (`stream_concurrency=1` by default) so the first chunk is
  emitted as early as possible while later chunks are produced ahead of playback.
- **Evaluation, not vibe checks.** A committed dataset + versioned thresholds
  gate speed (RTF), signal integrity (anomalies), and — with a transcriber —
  fidelity (WER/chrF). The gate returns a non-zero exit code for CI. Quality is
  round-trip **intelligibility** (text→speech→text); naturalness (MOS) and
  speaker-similarity are measured in the companion study and fed back as data.
- **Routing, justified by measurement.** The evaluation layer measures; the
  `router` acts. A **condition** — `online_realtime` (speed = RTF, must beat real
  time; maximise quality on the Pareto front among engines that keep up) or
  `offline` (quality only) — maps to a concrete engine + mode, with provenance
  (`quality_source`, `rtf_source`) and a number-citing justification — no
  derived confidence grade.
- **Nothing fetched at synthesis time.** The streaming default's weights come
  from a pinned `kokoro-onnx` GitHub release and then live in
  `~/.cache/speaker-helper/kokoro`; `install.py` checks the exact byte sizes so
  a truncated download is repaired rather than mistaken for an install. Copy
  that directory and the engine runs air-gapped. The other local backends,
  chatterbox the offline default among them, still fetch their own checkpoints.
- **Cloning made trivial.** Supply a recording; the transcript is derived with
  `vocal-helper` and over-long audio is trimmed with `audio-helper`, so a custom
  voice works from the library, CLI, and REST API alike.
- **Ecosystem-native.** Logging goes through `os-helper`; audio slicing and
  concatenation through `audio-helper` — the same building blocks as the other
  `*-helper` projects.

---

## Ecosystem

speaker-helper is the **text → speech** node of the AI Helpers graph, the
inverse of `vocal-helper` (speech → text). Since v0.4.0 it also closes the
**speech-to-speech** loop: `speaker_helper.sources` pulls audio from
`youtube-helper`, `podcast-helper`, or `capture-helper` (live microphone),
transcribes it with `vocal-helper`, and re-voices it.

```mermaid
flowchart LR
    yt["youtube-helper"]:::eco --> vh
    pod["podcast-helper"]:::eco --> vh
    cap["capture-helper"]:::eco --> vh
    vh["vocal-helper<br/>speech → text"]:::eco --> sh["speaker-helper<br/>text → speech"]:::core
    sh --> out["spoken audio"]:::ext

    classDef eco fill:#FFD5DD,stroke:#FF2D55,color:#000000
    classDef core fill:#CCE4FF,stroke:#007AFF,color:#000000
    classDef ext fill:#FFEACC,stroke:#FF9500,color:#000000
```

---

Author: Warith HARCHAOUI — https://harchaoui.org/warith/ai-helpers
