# Landscape

[🇫🇷 PAYSAGE.md](https://github.com/warith-harchaoui/speaker-helper/blob/main/PAYSAGE.md) · 🇬🇧 English

Related and competing text-to-speech projects in the "local, self-hostable
speech synthesis with voice cloning" space, benchmarked against
`speaker-helper`. Ratings are ⭐ (1) to ⭐⭐⭐⭐⭐ (5), scored on
`speaker-helper`'s intended job — professional TTS that runs **offline over a
local engine**, streams with a low time-to-first-audio, **clones a voice** from
a short reference, and drops into an AI pipeline through a typed
`dict`/`path` API exposed over many surfaces at once. A project optimised for a
very different job (a cloud API, a single OS voice, a research checkpoint) is
not penalised in the abstract — the score just reflects fit to *this* niche.

## At a glance

<!-- TABLE:START -->
| Speech Synthesis | Offline / local | Streaming | Voice cloning | Multilingual | AI-pipeline ergonomics | Multi-surface | Light install |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **speaker-helper** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| Coqui XTTS | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐ |
| Piper | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| Kokoro | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ |
| Chatterbox | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ |
| F5-TTS | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ |
| OpenVoice | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ |
| Bark | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ |
| Tortoise-TTS | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐ | ⭐ |
| pyttsx3 | ⭐⭐⭐⭐⭐ | ⭐ | ⭐ | ⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| gTTS | ⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| ElevenLabs (cloud) | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ |
<!-- TABLE:END -->

## Positioning map

<!-- FIGURE:START -->
2D representation of the table above.

![Positioning map](https://raw.githubusercontent.com/warith-harchaoui/speaker-helper/main/assets/landscape.png)

The map is a 2-D summary of the seven criteria, so read it as a shape, not a scoreboard. `speaker-helper` is at the top-right corner. The axes read **Horizontal — Compact ↔ Versatile** and **Vertical — Self-sufficient ↔ Efficient**.
<!-- FIGURE:END -->

## Positioning

`speaker-helper` is not another TTS model — it is the **toolbox around** the
models. It talks to a concrete engine (Voicebox by default) only through a
`TTSEngine` protocol, so Kokoro, Chatterbox, XTTS-class engines and a
deterministic `mock` all sit behind the same typed `Speaker`. On top of that
neutral core it adds the things a research checkpoint or a bare inference script
never ship: a **router** that turns an operating *condition* (online real-time
vs. offline) into a concrete engine + mode from measured quality↔speed evidence,
a **built-in evaluation gate** (real-time factor, audio anomalies, and a
text→speech→text WER/chrF round-trip), **voice cloning wired to auto-transcription**
(`vocal-helper` fills in a missing reference transcript), and **five surfaces**
in lock-step — Python, CLI, REST, a web GUI, and an MCP server for assistants.

That is a different centre of gravity from the field:

- The **model projects** — Coqui XTTS, Chatterbox, F5-TTS, OpenVoice, Bark,
  Tortoise — are excellent *engines*. They clone well and run offline, but each
  is a library or checkpoint: no cross-engine router, no committed eval gate, no
  CLI/REST/GUI/MCP quartet, and a heavy `torch` install. speaker-helper is happy
  to *drive* several of them behind its protocol rather than compete with any one.
- The **fast, lean engines** — Piper, Kokoro — win on install weight and
  real-time factor (Kokoro synthesises well under real time on CPU, which is why
  it is speaker-helper's default routed choice for `online_realtime`), but they
  do not clone voices and stop at a library/CLI.
- The **OS / cloud shims** — pyttsx3, gTTS, ElevenLabs — trade the local model
  away. pyttsx3 and gTTS are trivially light but give you one OS voice or a cloud
  round-trip with no cloning; ElevenLabs is genuinely best-in-class on streaming
  and cloning quality, but it is a paid SaaS: it scores ⭐ on "offline / local"
  by construction, and your text and reference audio leave the machine.

Where `speaker-helper` uniquely wins for its niche:

1. **Engine-agnostic router.** State a *condition*, get a concrete engine + mode
   justified by numbers — never a vibe. New engines fold in as measured data.
2. **Quality is gated, not guessed.** A committed dataset and versioned
   thresholds fail CI on slow synthesis, audio anomalies, or a broken round-trip.
3. **Cloning that finishes the job.** Point at a recording; a missing transcript
   is derived and over-long references are trimmed and re-aligned automatically.
4. **One core, five surfaces.** The same typed `Speaker` is reachable from
   Python, an argparse *and* a click CLI, a REST API, a web GUI, and MCP — no
   drift between them.

The honest cost is **install weight** (⭐⭐⭐): a real engine wants `torch`, plus
`ffmpeg` and `libsndfile` for the audio plumbing, and a running Voicebox. That
is the price of being the pipeline layer over real neural engines rather than a
one-file OS shim.

## When to pick what

- **`speaker-helper`** — you want offline, streaming, cloneable TTS wired into an
  AI pipeline: a typed `dict`/`path` API, a router that picks the engine for you,
  an eval gate in CI, and the same thing over CLI / REST / GUI / MCP. Especially
  the natural pair for `vocal-helper` (speech→text) — this is the text→speech leg.
- **Coqui XTTS** — you want one strong, permissive multilingual cloning engine as
  a library and will build your own serving, routing, and evaluation around it
  (or let speaker-helper drive it behind the protocol).
- **Chatterbox / F5-TTS / OpenVoice** — cloning fidelity is the priority and you
  can absorb a heavy install and write the glue yourself.
- **Kokoro / Piper** — you need a light, real-time, CPU-friendly voice and do
  *not* need cloning; Kokoro is exactly what speaker-helper routes to for
  real-time conditions.
- **Bark / Tortoise-TTS** — expressive or high-fidelity offline generation where
  latency does not matter (Tortoise is slow, Bark does not truly stream).
- **pyttsx3** — you want a zero-model, fully offline OS voice with no downloads
  and no cloning.
- **gTTS** — a throwaway script where a cloud round-trip and a single stock voice
  are fine and privacy is not a concern.
- **ElevenLabs (cloud)** — top-tier streaming and cloning quality with no local
  setup, and sending text + reference audio to a paid API is acceptable.
