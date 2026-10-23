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
| Speech Synthesis | Offline / local | Streaming | Voice cloning | Multilingual | AI-pipeline ergonomics | Multi-surface | Light install | Commercial licence |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **speaker-helper** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Coqui XTTS | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐ | ⭐ |
| Piper | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Kokoro | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Chatterbox | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| F5-TTS | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐ |
| OpenVoice | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| Hume TADA | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐⭐⭐⭐ |
| IndexTTS 2.5 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| Fish Speech | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐ |
| Bark | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| Tortoise-TTS | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| pyttsx3 | ⭐⭐⭐⭐⭐ | ⭐ | ⭐ | ⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| gTTS | ⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| ElevenLabs (cloud) | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
<!-- TABLE:END -->

## Positioning map

<!-- FIGURE:START -->
2D representation of the table above.

![Positioning map](https://raw.githubusercontent.com/warith-harchaoui/speaker-helper/main/assets/landscape.png)

The map is a 2-D summary of the eight criteria, so read it as a shape, not a scoreboard. `speaker-helper` is at the top-right corner. The axes read **Horizontal: Practicality ↔ Versatility** and **Vertical: Autonomy ↔ Efficiency**.

The map reveals a clear distinction between approaches prioritizing ease of use and those emphasizing broader capabilities. Options clustered on the left side of the map generally excel in straightforward application and deployment, with factors like ease of installation and a simple AI pipeline being key drivers. Conversely, those on the right side demonstrate a greater breadth of functionality, often incorporating features like multilingual support and streaming capabilities, though this sometimes comes at the cost of immediate practicality.

Several options find themselves grouped together in the lower right corner, suggesting a shared focus on versatility and a degree of independence from centralized services. These include Coqui XTTS, Fish Speech, and Hume TADA, all offering a wider range of features but potentially requiring more technical setup. Interestingly, speaker-helper occupies the upper right corner, demonstrating a strong balance of both versatility and efficiency, a position it holds while others, like the options in the lower left, prioritize autonomy over streamlined operation.

The upper left quadrant showcases a different set of strengths, with Piper, Kokoro, pyttsx3, and gTTS all performing well in terms of efficiency and ease of use. While speaker-helper leads overall, these options represent a compelling alternative for users who value a quick and reliable experience above all else. The divergence in positioning highlights that there is no single "best" option; the ideal choice depends heavily on the specific priorities of the user.
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
(`vocal-helper` fills in a missing reference transcript), and **four surfaces**
in lock-step — Python, CLI, REST, and a web GUI.

That is a different centre of gravity from the field:

- The **model projects** — Coqui XTTS, Chatterbox, F5-TTS, OpenVoice, Bark,
  Tortoise, and from 2026 Hume TADA, IndexTTS 2.5 and Fish Speech — are
  excellent *engines*. They clone well and run offline, but each
  is a library or checkpoint: no cross-engine router, no committed eval gate, no
  CLI/REST/GUI trio, and a heavy `torch` install. speaker-helper is happy
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
4. **One core, four surfaces.** The same typed `Speaker` is reachable from
   Python, an argparse *and* a click CLI, a REST API, and a web GUI — no
   drift between them.

**The licence is a routing input, not a footnote.** This is the criterion the
table was missing until 2026-10-23, and it reorders the field: the engines that
clone best are largely the ones you may not ship. XTTS v2 is CPML, F5-TTS
publishes MIT code with CC-BY-NC weights, and Fish Speech's S2 Pro is
non-commercial — all three are excellent and all three are unusable in a
product. What is left for commercial work is narrower than a quality ranking
suggests: Kokoro (Apache-2.0), Piper, OpenVoice v2, Bark (MIT), Tortoise
(Apache-2.0), IndexTTS 2.5 (Apache-2.0), and Chatterbox (MIT, with watermarked
output). Hume TADA sits in between — MIT code over weights under the Llama 3.2
Community License, permissive until you are very large. A router that optimised
quality alone would hand you a licence violation with a justification attached,
which is why `commercial` belongs beside `condition` as a stated constraint.

The honest cost is **install weight** (⭐⭐⭐): a real engine wants `torch`, plus
`ffmpeg` and `libsndfile` for the audio plumbing, and a running Voicebox. That
is the price of being the pipeline layer over real neural engines rather than a
one-file OS shim.

## When to pick what

- **`speaker-helper`** — you want offline, streaming, cloneable TTS wired into an
  AI pipeline: a typed `dict`/`path` API, a router that picks the engine for you,
  an eval gate in CI, and the same thing over CLI / REST / GUI. Especially
  the natural pair for `vocal-helper` (speech→text) — this is the text→speech leg.
- **Coqui XTTS** — you want the widest multilingual cloning coverage as a
  library, **your use is non-commercial** (its weights are CPML, not a
  permissive licence), and you will build your own serving, routing and
  evaluation around it (or let speaker-helper drive it behind the protocol).
- **Chatterbox / F5-TTS / OpenVoice** — cloning fidelity is the priority and you
  can absorb a heavy install and write the glue yourself.
- **Kokoro / Piper** — you need a light, real-time, CPU-friendly voice and do
  *not* need cloning; Kokoro is exactly what speaker-helper routes to for
  real-time conditions.
- **Hume TADA** — you want streaming that cannot hallucinate: text and audio are
  generated in one synchronised stream, which is the point of the design rather
  than a benchmark artefact, at a real-time factor near 0.09 and with a context
  holding minutes of audio instead of seconds. Read the Llama 3.2 terms if you
  are operating at scale.
- **IndexTTS 2.5** — zero-shot cloning with explicit emotion and speed control,
  streaming with synchronised text, and Apache-2.0 weights: the permissive
  option when cloning quality matters and shipping matters equally.
- **Fish Speech** — you are benchmarking against the quality ceiling and the
  work is research or personal; the licence rules out a product.
- **Bark / Tortoise-TTS** — expressive or high-fidelity offline generation where
  latency does not matter (Tortoise is slow, Bark does not truly stream).
- **pyttsx3** — you want a zero-model, fully offline OS voice with no downloads
  and no cloning.
- **gTTS** — a throwaway script where a cloud round-trip and a single stock voice
  are fine and privacy is not a concern.
- **ElevenLabs (cloud)** — top-tier streaming and cloning quality with no local
  setup, and sending text + reference audio to a paid API is acceptable.

## Why there is no `speaker-helper-rs`

Several packages in this suite have a Rust port — `audio-helper-rs`,
`youtube-helper-rs` — and the question of a third keeps coming up. The answer
is no, and the reason is the same one those two give for what they left out.

Their scope rule is: **wrap a system binary, do not reimplement the heavy
part.** `audio-helper-rs` ports probe, convert, chunk and concatenate on top
of `ffmpeg`, and explicitly does not port Demucs source separation or MFCC
similarity, because both need a real ML stack disproportionate to the crate's
promise. `youtube-helper-rs` wraps `yt-dlp` rather than reimplementing it.

Here, the heavy part is the whole part. Synthesis is ONNX inference plus
espeak-ng phonemisation, and there is no `kokoro` binary on the system to
wrap. A Rust port would mean the `ort` crate plus an espeak FFI binding —
reimplementing exactly what those crates decided not to.

And there is no problem it would solve. Kokoro already synthesises at roughly
a fifth of real time on a laptop CPU; the measured operating point through
this package's own façade is a real-time factor of 0.515. The latency that
matters in a conversation is dominated by endpointing and by the language
model's first token, not by the vocoder. A faster vocoder buys nothing a user
can hear.

What a crate *could* usefully own is the half that is not inference: laying a
timeline out, assembling WAV, writing WebVTT. That is a few hundred lines of
arithmetic sitting beside `audio-helper-rs`, and calling it a *speaker* helper
would misname it. If it is ever wanted, it belongs there.

This entry exists so the question is answered once rather than re-litigated.

## Sources and as-of date

Engine ratings and every licence above were checked on **2026-10-23**. Licences
change with releases and a stale licence claim is the one error here that can
cost a user money, so the date is part of the claim.

- [Best open-source TTS models, compared by license](https://www.cartesia.ai/learn/open-source-tts) — Cartesia
- [9 best open source text-to-speech models in 2026](https://www.bland.ai/blog/best-open-source-text-to-speech-model) — Bland
- [Open-sourcing TADA](https://www.hume.ai/blog/opensource-tada) — Hume AI
- [Faster IndexTTS-2: accelerating and streaming autoregressive zero-shot TTS](https://arxiv.org/html/2607.21042v1) — arXiv
- [Deploying open-source TTS on GPU cloud](https://www.spheron.network/blog/deploy-open-source-tts-gpu-cloud-2026/) — Spheron
