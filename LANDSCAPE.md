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
The per-criterion rubric is spelled out under
[How the cells are scored](#how-the-cells-are-scored), together with which
cells rest on measurements of our own and which are a reading of the published
model cards.

## At a glance

<!-- TABLE:START -->
| Speech Synthesis | Offline / local | Streaming | Voice cloning | Multilingual | Pronunciation control | Expressivity control | AI-pipeline ergonomics | Multi-surface | Light install | Commercial licence |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **speaker-helper** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Coqui XTTS | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐ | ⭐ |
| Piper | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Kokoro | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Chatterbox | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| Kyutai TTS | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐⭐⭐⭐ |
| CosyVoice 2/3 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| F5-TTS | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐ |
| OpenVoice | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| Hume TADA | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐⭐⭐⭐ |
| IndexTTS 2.5 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| Fish Speech | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐ |
| Bark | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| Tortoise-TTS | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| pyttsx3 | ⭐⭐⭐⭐⭐ | ⭐ | ⭐ | ⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| gTTS | ⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐ | ⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| ElevenLabs (cloud) | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
<!-- TABLE:END -->

## How the cells are scored

The scale is deliberately coarse and the rubric is written down, so a cell can
be argued with rather than merely disbelieved. Two columns are **new in
0.12.0** — pronunciation and expressivity — because they are what the project's
own brief turns on (a lexicon applied by default; a voice that is "realistic
and lively"), and no previous column captured either.

| Criterion | ⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
|---|---|---|---|
| Offline / local | cloud API only | local but with a hosted step | weights on disk, nothing leaves the machine |
| Streaming | batch only, many times slower than real time | real time under favourable conditions | sustained RTF well under 1 on a commodity CPU |
| Voice cloning | fixed voices only | a published voice bank, or limited timbre transfer | zero-shot from a few seconds you supply |
| Multilingual | English only | ~5–10 languages | 25+ languages in one model or voice set |
| Pronunciation control | nothing but respelling the input text | partial (phoneme or pinyin tags) | a lexicon **plus** verbatim IPA spliced into the phoneme stream |
| Expressivity control | flat, fixed delivery | prosody inherited from the reference clip | an explicit, directable emotion / intensity knob |
| AI-pipeline ergonomics | a research script to vendor | importable, with rough edges | typed `dict`/`path` API built to be called |
| Multi-surface | library only | library + CLI | library + CLI + REST + GUI + MCP |
| Light install | multi-GB, heavy deps | a few GB | small, few dependencies |
| Commercial licence | non-commercial | permissive with real conditions | permissive (MIT / Apache-2.0) |

Provenance, since it differs by cell. **Streaming** is the only column with
measurements of our own on the rows this suite ships — kokoro 0.21–0.24,
kyutai 0.88, chatterbox 2.3 en / 5.6 fr, sustained through `Speaker.stream` on
an M2 Max ([STREAMING.md](STREAMING.md)). Every other cell is a reading of the
published model cards and licences, scored against the rubric above: a
judgement, not a benchmark. **Pocket TTS is deliberately absent**: it is on the
watch list in STREAMING.md §3, but too little is published about it to fill ten
cells honestly, and a fabricated row would be worse than a missing one.

## Positioning map

<!-- FIGURE:START -->
2D representation of the table above.

![Positioning map](https://raw.githubusercontent.com/warith-harchaoui/speaker-helper/main/assets/landscape.png)

The map is a 2-D summary of the ten criteria, so read it as a shape, not a
scoreboard. `speaker-helper` is at the top-right corner. The axes read
**Horizontal: Resourceful ↔ Adaptable** (~34% of the variance) and
**Vertical: Practical ↔ Articulate** (~25%) — together ~60% of the table.

The map reveals a clear distinction between options that prioritize ease of use and those that emphasize flexibility. The horizontal axis separates those that excel at readily available features – like straightforward installation or built-in multilingual support – from those that offer a greater degree of customization and adaptability to varied conditions. Several options, including Tortoise-TTS, F5-TTS, IndexTTS 2.5, Fish Speech, Chatterbox, OpenVoice, Hume TADA, CosyVoice 2/3, Bark, Coqui XTTS, Kyutai TTS, and pyttsx3, cluster on the left, demonstrating a focus on resourceful capabilities. Conversely, speaker-helper, Piper, Kokoro, gTTS, and ElevenLabs (cloud) are positioned on the right, highlighting their adaptability.

The vertical axis differentiates between options that prioritize clear and expressive speech and those that emphasize practicality and simplicity. Those leaning towards articulation, such as speaker-helper, CosyVoice 2/3, ElevenLabs (cloud), IndexTTS 2.5, Hume TADA, Coqui XTTS, Chatterbox, Fish Speech, Kokoro, OpenVoice, Bark, Piper, F5-TTS, and Tortoise-TTS, demonstrate a strength in expressive control and voice cloning. Meanwhile, gTTS and pyttsx3, situated at the bottom, prioritize a more straightforward and functional approach.

Notably, speaker-helper leads in adaptability and articulation, occupying the top-right corner. However, it’s interesting to see how several options – Coqui XTTS, Chatterbox, CosyVoice 2/3, F5-TTS, OpenVoice, Hume TADA, IndexTTS 2.5, and Fish Speech – all gather in the top-left corner, demonstrating a shared emphasis on resourceful capabilities alongside a focus on expressive output.  gTTS and pyttsx3, on the other hand, find themselves in the bottom-left, representing a combination of resourcefulness and practicality, though for different reasons.
<!-- FIGURE:END -->

## Positioning

`speaker-helper` is not another TTS model — it is the **toolbox around** the
models. It reaches a concrete engine only through a `TTSEngine` protocol, so
Kokoro, Chatterbox, OpenVoice and a deterministic `mock` all sit behind the same
typed `Speaker`, and all of them run in the calling process: `settings.backend`
picks one out of a registry, and there is no server to start. On top of that
neutral core it adds the things a research checkpoint or a bare inference script
never ship: a **router** that turns an operating *condition* (online real-time
vs. offline) into a concrete engine + mode from measured quality↔speed evidence,
a **built-in evaluation gate** (real-time factor, audio anomalies, and a
text→speech→text WER/chrF round-trip), **voice cloning wired to auto-transcription**
(`vocal-helper` fills in a missing reference transcript), and **four surfaces**
in lock-step — Python, CLI, REST, and a web GUI.

That is a different centre of gravity from the field:

- The **model projects** — Coqui XTTS, Chatterbox, F5-TTS, OpenVoice, Bark,
  Tortoise, and from 2026 Hume TADA, IndexTTS 2.5, CosyVoice 2/3 and Fish
  Speech — are excellent *engines*. They clone well and run offline, but each
  is a library or checkpoint: no cross-engine router, no committed eval gate, no
  CLI/REST/GUI trio, and a heavy `torch` install. speaker-helper is happy
  to *drive* several of them behind its protocol rather than compete with any one.
- The **fast, lean engines** — Piper, Kokoro — win on install weight and
  real-time factor (Kokoro synthesises well under real time on CPU, which is why
  it is speaker-helper's default routed choice for `online_realtime`), but they
  do not clone voices and stop at a library/CLI.
- The **native-streaming engines** — Kyutai TTS, and Hume TADA alongside it —
  are built to emit audio as they generate rather than after. Kyutai speaks
  native French and English and ships a published voice bank, but it does not
  hand you voice cloning, and its sustained 0.88 RTF measured here lands just
  above our 0.8 anti-underrun ceiling on an M2 Max. speaker-helper drives it
  behind the same protocol as the rest.
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
   Python, one click CLI, a REST API, and a web GUI — no drift between
   them.

**The licence is a routing input, not a footnote.** This is the criterion the
table was missing until 2026-10-23, and it reorders the field: the engines that
clone best are largely the ones you may not ship. XTTS v2 is CPML, F5-TTS
publishes MIT code with CC-BY-NC weights, and Fish Speech's S2 Pro is
non-commercial — all three are excellent and all three are unusable in a
product. What is left for commercial work is narrower than a quality ranking
suggests: Kokoro (Apache-2.0), Piper, OpenVoice v2, Bark (MIT), Tortoise
(Apache-2.0), IndexTTS 2.5 and CosyVoice 2/3 (Apache-2.0), and Chatterbox
(MIT, with watermarked output). Two sit in between, permissive *with a
condition you must actually honour*: Hume TADA (MIT code over Llama 3.2
Community License weights, permissive until you are very large) and Kyutai TTS
(CC-BY-4.0 weights, and CC-BY-4.0 / CC0 voice banks — commercial use is fine,
attribution is not optional). A router that optimised
quality alone would hand you a licence violation with a justification attached,
which is why `commercial` belongs beside `condition` as a stated constraint.

The honest cost is **install weight** (⭐⭐⭐). The default voice is the cheap end
of it — ONNX Runtime, `espeak-ng`, and ~340 MB of weights fetched once — but
`ffmpeg` and `libsndfile` are still required for the audio plumbing, and the
*cloning* half pulls `torch` and `torchaudio` behind the `[openvoice]` /
`[chatterbox]` extras. That is the price of being the pipeline layer over real
neural engines rather than a one-file OS shim.

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
- **Kyutai TTS** — you want French and English spoken by a model that was
  trained on them natively, emitting audio as it generates (delayed-streams,
  ~220 ms announced) rather than after. Accept the trade: a published voice
  bank instead of cloning your own reference, and CC-BY attribution in your
  product.
- **CosyVoice 2/3** — zero-shot cloning from about three seconds, streaming in
  the ~150 ms class, natural-language style instructions, and Apache-2.0: the
  broadest feature set of the permissive cloners, at the price of a heavy
  install.
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

## Ideas worth stealing

Researched rather than guessed: what each neighbour does better, and what this library would have to change to match it. Nothing here is a commitment — it is the reading list the next version starts from.

- **`Piper` — a tier that is always available** — Tiny, fast, CPU-only. A synthesiser that routes across engines needs a floor it can always reach: when no GPU is present and no weights are cached, something still has to speak. Piper is the usual answer to that.

- **`Kokoro` — 82M parameters, Apache-2.0, roughly 30× realtime** — Around 1 GB of VRAM against XTTS v2's ~4 GB, and about ten times faster. It does not clone a voice, which is exactly why it is the right default for narration and the wrong one for a cloned speaker.

- **Licence as a routing criterion, not a footnote** — XTTS v2 is CPML, non-commercial. Chatterbox is MIT and still clones. A router that picks on quality alone can silently hand a commercial caller a model they may not ship. The engine table should carry the licence and let it veto a pick.

- **`Chatterbox` — expressive control, and a caution** — MIT, clones from a short reference, and won 65.3% of blind comparisons against ElevenLabs. Worth noting against this repo's own experience: it is the current French default here and the fidelity gate has been a coin flip since, which is an argument for pinning the gate to the engine rather than to one global threshold.
