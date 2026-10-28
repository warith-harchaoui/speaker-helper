# speaker-helper — Examples

[🇫🇷 EXEMPLES.md](https://github.com/warith-harchaoui/speaker-helper/blob/main/EXEMPLES.md) · 🇬🇧 English

A runnable cookbook of the most common workflows. There is no engine to start:
every backend runs in the same process as your code, so each example below is a
script you can paste as it is.

---

## Table of Contents

- [Setup](#setup)
- [1. Offline synthesis to a file (sync)](#1-offline-synthesis-to-a-file-sync)
- [2. Offline synthesis (async, in your own event loop)](#2-offline-synthesis-async-in-your-own-event-loop)
- [3. Streaming with time-to-first-audio](#3-streaming-with-time-to-first-audio)
- [4. List available voices](#4-list-available-voices)
- [5. Reading a document aloud, with cues a page can follow](#5-reading-a-document-aloud-with-cues-a-page-can-follow)
- [6. REST API server](#6-rest-api-server)
- [7. Choosing a specific voice and language](#7-choosing-a-specific-voice-and-language)
- [8. Cloning a voice (give only the audio)](#8-cloning-a-voice-give-only-the-audio)
- [9. Gating quality with the evaluation layer](#9-gating-quality-with-the-evaluation-layer)
- [10. Routing: pick an engine + mode for a condition](#10-routing-pick-an-engine--mode-for-a-condition)
- [11. Measuring across languages](#11-measuring-across-languages)
- [12. Speech-to-speech: re-voice a YouTube clip](#12-speech-to-speech-re-voice-a-youtube-clip)
- [13. Pronunciation lexicon: fix how a word is said, once](#13-pronunciation-lexicon-fix-how-a-word-is-said-once)
- [14. Long texts: chunked at discourse boundaries](#14-long-texts-chunked-at-discourse-boundaries)
- [15. The language rules, end to end](#15-the-language-rules-end-to-end)
- [Command line](#command-line)
- [Troubleshooting](#troubleshooting)

---

## Setup

One install, one download, one check. The `kokoro` extra brings the default
engine; `server` brings the REST API and the web GUI used in §6.

```bash
pip install "speaker-helper[kokoro,server]"   # from a clone: pip install -e ".[kokoro,server]"
speaker-helper install-voice                  # fetch the default engine's weights, once
speaker-helper health
# {
#   "engine": "kokoro",
#   "loaded": false,
#   "sample_rate": 24000,
#   "status": "ok",
#   "weights": "/Users/you/.cache/speaker-helper/kokoro"
# }
```

`health` exits non-zero when the backend could not synthesise, so it works as a
gate in a script and not only as something to read. `"weights"` is wherever
`install-voice` put the 340 MB — it is reported rather than assumed.

Every Python example from here on assumes these two bindings, and nothing else:

```python
import asyncio                                 # §2-§5, §8, §9, §11 and §12 are async
from speaker_helper import Speaker, Settings   # the façade, and its configuration
```

A section that needs more (`VoiceSample`, `route`, the `eval` layer) imports it
in place. `Settings.from_mapping({...})` is used throughout so each snippet is
self-contained; `Settings.load()` reads `./settings.yaml` and the
`SPEAKER_HELPER_*` environment variables instead.

**About the numbers in the comments.** Every output line below was produced by
running the snippet above it. Durations are the engine's own answer and
reproduce exactly; the **real-time factors do not** — an RTF depends on the
host, on whether the ONNX session has already been built in this process, and
on what else the machine is doing. Read the shape of the line, not the digits,
and see [BENCHMARKS.md](BENCHMARKS.md) for the reference-host figures (kokoro,
mean RTF 0.223 in French on an idle M2 Max).

---

## 1. Offline synthesis to a file (sync)

The simplest possible call — synthesise a whole string and write a WAV:

```python
from speaker_helper import Speaker, Settings

spk = Speaker(Settings.from_mapping({"backend": "kokoro", "language": "fr"}))
for _ in range(2):
    result = spk.save("Bonjour, ceci est speaker-helper.", "hello.wav")
    print(f"{result.duration_s:.2f}s audio at {result.sample_rate} Hz, RTF {result.rtf:.2f}")
# 2.45s audio at 24000 Hz, RTF 0.84    <- this call also built the ONNX session
# 2.45s audio at 24000 Hz, RTF 0.77    <- every call after it
```

The first synthesis loads the model, so its real-time factor measures the
*load* and not the engine. `await spk.warmup()` moves that cost to where you
want it — which is why the evaluation gate warms up before it times anything.

---

## 2. Offline synthesis (async, in your own event loop)

Entering the async context warms the engine up, so the measurement below is of
synthesis rather than of start-up:

```python
import asyncio
from speaker_helper import Speaker, Settings

async def main() -> None:
    async with Speaker(Settings.from_mapping({"engine": "kokoro"})) as spk:
        result = await spk.say("Le temps réel, c'est maintenant.")
        with open("out.wav", "wb") as f:
            f.write(result.wav_bytes)
        print(f"{result.duration_s:.2f}s audio, RTF {result.rtf:.2f}")
        # 1.47s audio, RTF 0.94

asyncio.run(main())
```

---

## 3. Streaming with time-to-first-audio

Streaming splits the text into sentences and yields audio as each is ready, so
you can start playing before the whole paragraph is synthesised:

```python
import asyncio
from speaker_helper import Speaker, Settings

async def main() -> None:
    text = "Premier segment. Deuxième segment. Et voici le troisième."
    async with Speaker(Settings.from_mapping({"engine": "kokoro"})) as spk:
        async for chunk in spk.stream(text):
            if chunk.ttfa_s is not None:
                print(f"time to first audio: {chunk.ttfa_s:.2f}s")
            print(f"chunk {chunk.seq}: {chunk.audio.duration_s:.2f}s")
        # time to first audio: 1.83s
        # chunk 0: 1.07s
        # chunk 1: 1.15s
        # chunk 2: 1.43s

asyncio.run(main())
```

`ttfa_s` is set on the first chunk only (`seq == 0`) and is `None` afterwards —
it is one measurement about the stream, not a per-chunk field.

---

## 4. List available voices

Listing does not need the weights: without them the answer comes from the
engine's built-in catalogue, because "fetch 340 MB, then ask again" is a poor
reply to "which voices are there".

```python
import asyncio
from speaker_helper import Speaker, Settings

async def main() -> None:
    async with Speaker(Settings.from_mapping({"engine": "kokoro"})) as spk:
        listing = await spk.voices()
        print(len(listing.voices), "voices")
        for v in listing.voices:
            if v.language.startswith("fr"):
                print(v.voice_id, v.language, v.gender)
        # 54 voices
        # ff_siwis fr female

asyncio.run(main())
```

kokoro reports a voice's id as its name, so `v.name == v.voice_id` here; the
curated presets in `speaker_helper.voices` carry the human-readable ones:

```python
from speaker_helper import voice_for, voices_for

print(voice_for("fr"))                              # ff_siwis
print([(v.voice_id, v.name) for v in voices_for("fr")])
# [('ff_siwis', 'Siwis'), ('bm_george', 'George (fr)')]
```

---

## 5. Reading a document aloud, with cues a page can follow

`narrate()` differs from `stream()` in its bookkeeping, not its engine. A
document has structure — pauses its headings ask for, blocks whose spoken form
differs from their printed form — and a caller that wants to *follow* the
reading needs to know which stretch of audio speaks which block:

```python
import asyncio
from speaker_helper import Speaker, Settings, cues_to_vtt

async def main() -> None:
    segments = [
        {"text": "Ce que la synthèse vocale change", "pause_after_ms": 400},
        {"text": "Le texte devient du son : la page sait quand.", "pace": "slow"},
    ]
    async with Speaker(Settings.from_mapping({"backend": "mock", "language": "fr"})) as spk:
        narration = await spk.narrate(segments)
    print(f"{narration.duration_s:.2f}s, {len(narration.cues)} cues")
    # 6.06s, 2 cues
    for cue in narration.cues:
        print(cue.index, f"{cue.start_seconds:.2f}-{cue.end_seconds:.2f}", cue.text)
    # 0 0.00-2.13 Ce que la synthèse vocale change
    # 1 2.53-6.06 Le texte devient du son : la page sait quand.
    print(cues_to_vtt(narration.cues).splitlines()[0])   # WEBVTT

asyncio.run(main())
```

A segment may be a `Segment`, a dict, or a bare string. The dict keys are
`text` plus the optional `say` (what the voice reads where the page shows
something else), `pause_before_ms`, `pause_after_ms`, `pace` and `emotion`. The
run above uses the `mock` backend because the cue arithmetic is the point and
`mock` makes it deterministic; swap in `kokoro` for real audio.

---

## 6. REST API server

```bash
speaker-helper serve --bind-host 0.0.0.0 --bind-port 8080
```

```bash
curl -s localhost:8080/health
# {"status":"ok","backend":"kokoro","engine":{"status":"ok","engine":"kokoro",
#  "loaded":true,"weights":"/Users/you/.cache/speaker-helper/kokoro",
#  "sample_rate":24000}}
# engine down but server up -> {"status":"degraded","backend":…,"engine_error":…}

curl -s "localhost:8080/voices?engine=kokoro"
# {"engine":"kokoro","voices":[{"voice_id":"af_alloy","name":"af_alloy",
#  "language":"en","gender":"female","engine":"kokoro"}, … 54 in all]}

curl -s -D - -X POST localhost:8080/synth \
     -H 'content-type: application/json' \
     -d '{"text": "Bonjour depuis l'\''API."}' -o out.wav
# HTTP/1.1 200 OK
# x-audio-duration-s: 1.408
# x-audio-rtf: 1.822
# content-type: audio/wav

# the router, as an endpoint:
curl -s -X POST localhost:8080/route \
     -H 'content-type: application/json' \
     -d '{"condition": "online_realtime", "language": "fr"}'
# {"condition":"online_realtime","engine":"kokoro","backend":"kokoro",
#  "mode":"streaming","quality":0.466,"mean_rtf":0.223,
#  "quality_source":"public_elo","rtf_source":"measured","confidence":"high",
#  "justification":"…","candidates_considered":3,"pareto_size":1}
```

`POST /narrate` answers §5 over HTTP — JSON rather than `audio/wav`, because the
cues are the reason that route exists and the audio rides along base64-encoded.
`POST /synth/stream` is §3 as Server-Sent Events, one JSON chunk per sentence.
The server also serves a **minimal web GUI** at `http://localhost:8080/`
(synth, streaming, voices, clone, and the router).

---

## 7. Choosing a specific voice and language

```python
from speaker_helper import Speaker, Settings

spk = Speaker(Settings.from_mapping({
    "engine": "kokoro",
    "voice_id": "ff_siwis",   # explicit French voice
    "language": "fr",
}))
result = spk.save("Voix choisie explicitement.", "voice.wav")
print(result.voice_id, f"{result.duration_s:.2f}s")
# ff_siwis 1.54s
```

A voice *is* a language in kokoro — the id's first letter says which — so a
`language` that disagrees with `voice_id` produces an accent nobody asked for.
Leave `voice_id` empty to let the language pick the voice.

---

## 8. Cloning a voice (give only the audio)

The transcript is optional: without one, it is derived with `vocal-helper`
(install the `stt` extra) and over-long audio is trimmed with `audio-helper`.

```python
import asyncio
from speaker_helper import Speaker, Settings, VoiceSample

async def main() -> None:
    # `backend` picks the engine; `engine` is only a label carried on results.
    spk = Speaker(Settings.from_mapping({
        "backend": "chatterbox", "language": "fr",
    }))
    async with spk:
        # supply only the recording — transcript auto-derived and aligned:
        voice_id = await spk.clone_voice("my-voice", [VoiceSample("my_voice.wav", "")])
        print(voice_id)  # the cloned profile id, to reuse later
        result = await spk.say("Je parle maintenant avec la voix clonée.")
        with open("cloned.wav", "wb") as f:
            f.write(result.wav_bytes)

asyncio.run(main())
```

`VoiceSample` takes the audio first (`bytes` or a path) and its transcript
second; an empty transcript is the "derive it for me" signal.

Config-driven (works in the CLI and REST server too — set once, clone everywhere):

```python
from speaker_helper import Speaker, Settings

# an empty clone block -> the bundled reference voice is used
spk = Speaker(Settings.from_mapping({
    "backend": "chatterbox",
    "clone": {"name": "ref-fr-female"},
}))
spk.save("Voix clonée par défaut.", "cloned.wav")   # clones on first synthesis
```

```bash
# CLI: clone the bundled reference and synthesise with it
speaker-helper --clone synth "Bonjour." -o cloned.wav
# or clone from your own audio (transcript auto-derived):
speaker-helper --clone-audio my_voice.wav synth "Bonjour." -o out.wav
```

---

## 9. Gating quality with the evaluation layer

```python
import asyncio
from speaker_helper import Speaker, Settings
from speaker_helper.eval import load_dataset, run_eval

async def main() -> None:
    # the mock backend needs no weights — perfect for CI
    async with Speaker(Settings.from_mapping({"backend": "mock"})) as spk:
        report = await run_eval(spk, load_dataset())
    print(report.passed, report.mean_rtf, report.anomaly_rate)
    # True 0.3 0.0

asyncio.run(main())
```

```bash
# CLI: non-zero exit code when the bar is missed (gates CI)
speaker-helper --backend mock eval
# backend=mock engine=kokoro cases=12
# mean_rtf=0.3 p95_rtf=0.3 anomaly_rate=0.0 quality=1.0 (prior)
# PASS
speaker-helper --engine kokoro eval --json report.json
```

`run_eval` warms the engine up before it times anything, so the first case does
not pay for the model load. Pass `warmup=False` only to measure cold start
deliberately.

With a transcriber (from the `stt` extra) you also get a WER/chrF round-trip:

```python
import asyncio
from speaker_helper import Speaker, Settings
from speaker_helper.eval import run_eval
from speaker_helper.transcription import VocalHelperTranscriber

async def main() -> None:
    async with Speaker(Settings.from_mapping({"language": "fr"})) as spk:
        report = await run_eval(spk, transcriber=VocalHelperTranscriber("fr"))
    print(report.mean_wer, report.mean_chrf)

asyncio.run(main())
```

Without a transcriber `mean_wer` and `mean_chrf` stay `None` and their
thresholds are not gated — the report says so rather than scoring a blank.

---

## 10. Routing: pick an engine + mode for a condition

State the operating **condition** and let the router choose, justified by
measured quality↔speed evidence:

```python
from speaker_helper import RouteRequest, Speaker, route

# online real-time: RTF is a hard feasibility bound — the engine must run
# faster than real time (ceiling 0.8). Among those that keep up, maximise
# quality -> streaming with low time-to-first-audio.
d = route(RouteRequest(condition="online_realtime", language="fr"))
print(d.engine, d.mode, d.confidence, d.quality_source)
# kokoro streaming high public_elo

# offline: quality is the ONLY objective (speed disregarded).
d2 = route(RouteRequest(condition="offline", language="fr"))
print(d2.engine, d2.mode, d2.confidence, d2.quality_source)
# chatterbox offline low prior  <- 'low': offline confidence rates the QUALITY evidence alone

# French is settled by the owner's ratification, not by the argmax -- and the
# router says so rather than quietly rewriting the quality numbers.
print(d2.owner_ratified)                            # True
print(d2.justification)
# offline: engine fixed by the owner's ratified choice for 'fr' (as of
# 2026-10-28) -- 'chatterbox' (quality=0.780 [prior]). This OVERRIDES the
# quality argmax over 3 candidate(s), which was 'kyutai' (quality=0.920
# [prior]): a decision, not a measurement. Pass respect_ratification=False
# for the unarbitrated ranking. mode=offline (whole-text synthesis; speed is
# not an objective and no RTF enters this decision).

# Switch the arbitration off to see the unarbitrated ranking:
print(route(RouteRequest(condition="offline", language="fr",
                         respect_ratification=False)).engine)   # kyutai

# build a Speaker straight from a routed operating point:
spk = Speaker.from_route("online_realtime", language="fr")
```

The two conditions rank quality on **different criteria**, and every decision
says which through `quality_source`:

- `online_realtime` uses the public arena Elo (`public_elo`) — human pairwise
  votes. An engine on no public arena scores `0.0` with `no_public_elo`: a
  documented data gap, never a flattering prior in disguise.
- `offline` uses the owner-ratified per-language priors (`prior`), or kokoro's
  measured UTMOSv2 score where one exists (`measured_mos`).

`confidence` is `high` when both axes are evidenced, `medium` when one is,
`low` when the decision rests on priors alone.

Under the hood the online condition selects on the quality↔RTF **Pareto
front**; you can use that primitive directly on a batch of evaluation reports:

```python
from speaker_helper.eval import pareto_front

# reports = [await run_eval(spk_kokoro), await run_eval(spk_chatterbox), ...]
best = pareto_front(reports)   # non-dominated: high quality AND low RTF
for r in best:
    print(r.backend, r.mean_rtf, r.quality)
```

Offline deliberately runs **no** Pareto gate (it reports `pareto_size=0`):
dropping a higher-quality engine because nobody timed it would contradict an
objective that does not care about speed.

---

## 11. Measuring across languages

```python
import asyncio
from speaker_helper import Settings
from speaker_helper.eval import format_matrix, run_multilang_eval

async def main() -> None:
    reports = await run_multilang_eval(
        Settings.from_mapping({"backend": "kokoro"}),
        ["fr", "en", "es"],
    )
    print(format_matrix(reports))
    # lang   cases  mean_rtf  p95_rtf  anomaly  quality  verdict
    # ----------------------------------------------------------
    # fr        12     0.242    0.293    0.000    0.750  PASS
    # en        10     0.235    0.268    0.000    0.750  PASS
    # es        10     0.221    0.264    0.000    0.750  PASS

asyncio.run(main())
```

Each language needs a bundled dataset — `available_languages()` says which have
one. These are exactly the numbers the router's online feasibility gate
consumes.

```bash
# CLI: one matrix, gates on every language (exit 1 if any fails)
speaker-helper --engine kokoro eval --languages fr,en,es --json matrix.json
```

---

## 12. Speech-to-speech: re-voice a YouTube clip

```python
import asyncio
from speaker_helper import Speaker, Settings
from speaker_helper.sources import from_youtube, revoice

async def main() -> None:
    src = from_youtube("https://youtu.be/…")            # extra: youtube
    async with Speaker(Settings.from_mapping({"language": "fr"})) as spk:
        out = await revoice(src, spk)                   # transcribe (vocal-helper) + re-speak
    with open("revoiced.wav", "wb") as f:
        f.write(out.wav_bytes)

asyncio.run(main())
```

`from_podcast(feed_url)` and `from_microphone(seconds=…)` are the other two
sources, and `revoice` also accepts a plain file path. Give it a `language`
different from the source's and the same call becomes a dub.

---

## 13. Pronunciation lexicon: fix how a word is said, once

Copy `lexicon.yaml.example` to `lexicon.yaml` next to your `settings.yaml`
(or point `settings.lexicon.path` / `SPEAKER_HELPER_LEXICON` at it) and every
synthesis — Python, CLI, REST, GUI — honours it automatically:

```yaml
# lexicon.yaml
entries:
  - word: "Grasse"        # exact phonemes: deterministic on kokoro
    language: fr
    ipa: "ɡʁas"
  - word: "GitHub"        # orthographic rewrite: works on every engine
    language: fr
    respelling: "guite-heube"
  - word: "RGPD"          # neither -> the local LLM derives a respelling once
    language: fr          #   (best-engine-ai-helper + Ollama), then it is cached
```

```python
from speaker_helper import Speaker, Settings

Speaker(Settings.load()).save("Le RGPD s'applique à GitHub, même à Grasse.", "out.wav")
# kokoro splices /ɡʁas/ at its phonemisation step; a phoneme-less engine
# (chatterbox, kyutai) speaks the respellings instead. The derived RGPD
# respelling lands in lexicon.yaml.llm-cache.yaml — delete a line there to
# re-derive, or move it into `respelling:` to make it a human decision.
```

Matching is case-insensitive and on word boundaries, so `ONU` matches in
`l'ONU !` and not inside `monument`. Set `lexicon: {llm: false}` in
`settings.yaml` on a machine without Ollama: entries that carry an `ipa` or a
`respelling` keep working, and the rest are left alone.

---

## 14. Long texts: chunked at discourse boundaries

`say()` cuts anything longer than `chunking.max_chars` (default 500) into
sentence-group chunks, synthesises them in order and concatenates — because
every neural engine audibly degrades past its comfort zone. The local LLM
places the boundaries (it only ever *groups* locally-split sentences, so the
text itself cannot change); without Ollama a greedy packer does it:

```yaml
# settings.yaml — all optional, these are the defaults
chunking:
  enabled: true
  llm: true
  max_chars: 500
```

The splitter is importable on its own when you want the boundaries without the
audio:

```python
from speaker_helper import chunk_for_streaming, split_sentences

text = "Premier segment. Deuxième segment. Et voici le troisième."
print(split_sentences(text))
# ['Premier segment.', 'Deuxième segment.', 'Et voici le troisième.']
print(chunk_for_streaming(text, first_chunk_sentences=1))
# ['Premier segment.', 'Deuxième segment.', 'Et voici le troisième.']
```

---

## 15. The language rules, end to end

The offline defaults are the **owner's editorial choice** from the 2026-10
survey ([`STUDY.md`](STUDY.md)) — French re-decided on 2026-10-28 (§8 ter) —
honestly flagged as such (`quality_source="prior"`, and `owner_ratified=True`
where a choice overrode the ranking): automatic naturalness predictors were
evaluated and **rejected as the offline criterion** — they score a generic anonymous-panel
"naturalness", not "realistic and lively" to a human ear (see `STUDY.md`
§8 bis). Automatic metrics remain as guardrails (WER floor, anomaly gate,
female-F0 check), never as the ranking; a human pairwise-listening protocol is
the planned replacement. Every default voice is **female** in every engine:

```python
from speaker_helper import Speaker

# French -> chatterbox, by the owner's ratification of 2026-10-28 (the
# Multilingual model -- the best documented chatterbox that speaks French;
# Turbo and base are English-only). An arbitration, flagged as one.
spk = Speaker.from_route("offline", language="fr")
print(spk.route.engine, spk.route.owner_ratified)   # chatterbox True

# English -> chatterbox (its backend auto-picks the lively Turbo model)
spk = Speaker.from_route("offline", language="en")
print(spk.route.engine)                             # chatterbox

# Any other language -> chatterbox's 23-language Multilingual model.
# rtf_source is "not_considered" and mean_rtf is None on EVERY offline
# decision, however well-timed the engine: offline does not rank on speed, so
# it reports no speed. Quoting one would invite you to read it as a reason.
spk = Speaker.from_route("offline", language="es")
print(spk.route.engine, spk.route.rtf_source)       # chatterbox not_considered
print(spk.route.mean_rtf)                           # None

# Real-time streaming runs on measured evidence -> kokoro (RTF 0.223 in French)
spk = Speaker.from_route("online_realtime", language="fr")
print(spk.route.engine, spk.route.confidence)       # kokoro high
```

Prefer kokoro's polished-narrator steadiness? It stays one setting away
(`backend: kokoro`), and the companion study keeps a listening pack so the
defaults can be re-decided by ear.

Language resolution everywhere follows one rule: **stated → believed,
unstated → detected** (`langdetect`, seeded), falling back to the configured
`language`.

---

## Command line

`speaker-helper` is one [click](https://click.palletsprojects.com) group. The
global options (`--backend`, `--engine`, `--language`, `--clone`, …) are
declared on the group, so they **precede** the sub-command; `-h` and `-V` both
answer.

```bash
speaker-helper --help
# Commands:
#   clone          Register a cloned voice from reference audio and print...
#   eval           Evaluate the engine against a dataset and gate on...
#   health         Report whether the configured backend can run; exit...
#   install-voice  Download the weights an engine needs, before anything...
#   narrate        Read a document aloud, and write the timed track that...
#   route          Choose the best engine + mode for a condition (online...
#   serve          Run the REST API server.
#   speak-from     Re-voice audio from a source (youtube / podcast /...
#   synth          Synthesise TEXT (or stdin) to a WAV file.
#   voices         List preset voices for an engine (uses the global...
```

Synthesis, offline and streaming (§1, §3):

```bash
speaker-helper synth "Bonjour le monde." -o hello.wav
# wrote hello.wav (1.19s audio, RTF 1.51)

echo "Texte lu depuis l'entrée standard." | speaker-helper synth -o out.wav

speaker-helper synth "Une. Deux. Trois." -o out.wav --stream
# chunk 0: 0.55s audio (RTF 3.39)
# chunk 1: 0.53s audio (RTF 0.40)
# chunk 2: 0.58s audio (RTF 0.36)
# streamed 1.66s audio to out.wav (TTFA 2.97s)
```

Voices and weights (§4):

```bash
speaker-helper --engine kokoro voices
# ff_siwis	fr	female	ff_siwis
# …54 lines: voice_id, language, gender, name

speaker-helper install-voice
# ✓ Kokoro's weights are already in /Users/you/.cache/speaker-helper/kokoro
```

Narration with its timed track (§5) — two files, not one, because the `.vtt`
beside the WAV is what lets a page highlight the block being read:

```bash
cat > segments.json <<'JSON'
[
  {"text": "Ce que la synthèse vocale change", "pause_after_ms": 400},
  {"text": "Le texte devient du son : la page sait quand.", "pace": "slow"}
]
JSON
speaker-helper --backend mock narrate segments.json -o narration.wav
# narration.wav	6.06s	2 cues	rtf 0.00
# -> narration.wav + narration.vtt
```

Routing (§10) and the quality gate (§9):

```bash
speaker-helper --language fr route --condition online_realtime
# condition=online_realtime engine=kokoro mode=streaming
# quality=0.466 (public_elo) mean_rtf=0.223 (measured) confidence=high
# online_realtime: require mean_rtf <= 0.8 (RTF<1 is the real-time feasibility
# boundary; margin absorbs TTFA + jitter). 1/3 candidates keep up; on the
# 1-point Pareto front, chose 'kokoro' …

speaker-helper route --condition offline --json decision.json
speaker-helper --backend mock eval                               # exit 1 if the bar is missed
speaker-helper --engine kokoro eval --languages fr,en,es --json matrix.json
```

Cloning (§8), re-voicing (§12) and the server (§6):

```bash
speaker-helper --clone synth "Bonjour." -o cloned.wav
speaker-helper --clone-audio my_voice.wav synth "Bonjour." -o out.wav
speaker-helper speak-from --source youtube --url "https://youtu.be/…" -o revoiced.wav
speaker-helper serve --bind-host 0.0.0.0 --bind-port 8080
```

---

## Troubleshooting

**`health` says `"the weights are not on this machine"`.** Run
`speaker-helper install-voice`. The default engine needs about 340 MB that no
`pip install` fetches, and the fix is printed in the `"fix"` field of the
health report itself.

**`health` says `"kokoro-onnx is not installed"`.** The engine lives behind an
extra: `pip install "speaker-helper[kokoro]"`.

**The first call looks slow (RTF above 1).** It built the ONNX session, which
costs about five seconds once per process. `await spk.warmup()` — or entering
the `async with` block, which calls it for you — moves that cost off your first
real request.

**`route --condition online_realtime` exits 2 with "no engine meets the online
RTF ceiling".** The online condition refuses engines whose RTF was never
measured, rather than claiming they keep up. Raise `--rtf-ceiling`, or pass
`require_measured_rtf=False` to `RouteRequest` and accept that the decision is
then a guess.

**Cloning raises on a missing transcript.** Deriving one needs the `stt` extra
(`pip install "speaker-helper[stt]"`), which pulls `vocal-helper`. Supply
`VoiceSample(path, "what is actually said")` to skip it entirely.

**A word is mispronounced.** That is §13, and it is a one-line fix in
`lexicon.yaml` rather than a reason to change engine.
