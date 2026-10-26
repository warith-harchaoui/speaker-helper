# speaker-helper — Examples

A runnable cookbook of the most common workflows. There is no engine to start:
every backend runs in the same process as your code. What each example assumes
is an install (`pip install -e ".[kokoro,server]"`) and, for the default voice,
the weights on disk.

Fetch them once, and check:

```bash
speaker-helper install-voice
speaker-helper health
# {"engine": "kokoro", "loaded": false, "sample_rate": 24000, "status": "ok",
#  "weights": "/Users/you/.cache/speaker-helper/kokoro"}
```

---

## 1. Offline synthesis to a file (sync)

The simplest possible call — synthesise a whole string and write a WAV:

```python
from speaker_helper import Speaker, Settings

spk = Speaker(Settings.from_mapping({"backend": "kokoro", "language": "fr"}))
result = spk.save("Bonjour, ceci est speaker-helper.", "hello.wav")
print(f"{result.duration_s:.2f}s audio at {result.sample_rate} Hz, RTF {result.rtf:.2f}")
# 3.31s audio at 24000 Hz, RTF 1.13     <- the first call builds the ONNX session
```

---

## 2. Offline synthesis (async, in your own event loop)

```python
import asyncio
from speaker_helper import Speaker, Settings

async def main() -> None:
    async with Speaker(Settings.from_mapping({"engine": "kokoro"})) as spk:
        result = await spk.say("Le temps réel, c'est maintenant.")
        with open("out.wav", "wb") as f:
            f.write(result.wav_bytes)
        print(f"RTF {result.rtf:.2f}")
        # RTF 0.41

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
        # time to first audio: 0.85s
        # chunk 0: 1.62s
        # chunk 1: 1.73s
        # chunk 2: 1.73s

asyncio.run(main())
```

---

## 4. List available voices

```python
import asyncio
from speaker_helper import Speaker, Settings

async def main() -> None:
    async with Speaker(Settings.from_mapping({"engine": "kokoro"})) as spk:
        listing = await spk.voices()
        for v in listing.voices:
            if v.language.startswith("fr"):
                print(v.voice_id, v.name)
        # ff_siwis Siwis

asyncio.run(main())
```

---

## 5. CLI

```bash
# list French kokoro voices
speaker-helper --engine kokoro voices

# offline synthesis
speaker-helper synth "Bonjour le monde." -o hello.wav

# from stdin
echo "Texte lu depuis l'entrée standard." | speaker-helper synth -o out.wav

# streaming (reports TTFA + per-chunk cadence)
speaker-helper synth "Une. Deux. Trois." -o out.wav --stream

# pick the best engine + mode for a condition (see §10)
speaker-helper --language fr route --condition online_realtime
```

`speaker-helper` is one click group. Global options (`--backend`, `--engine`,
`--language`, …) are declared on the group, so they precede the sub-command.

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
# {"engine":"kokoro","voices":[...]}

curl -s -X POST localhost:8080/synth \
     -H 'content-type: application/json' \
     -d '{"text": "Bonjour depuis l'\''API."}' -o out.wav
# out.wav written; X-Audio-Duration-S / X-Audio-RTF returned as headers

# the router, as an endpoint:
curl -s -X POST localhost:8080/route \
     -H 'content-type: application/json' \
     -d '{"condition": "online_realtime", "language": "fr"}'
# {"engine":"kokoro","mode":"streaming","confidence":"medium","justification":"…"}
```

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
spk.save("Voix choisie explicitement.", "voice.wav")
```

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
        print(voice_id)  # e.g. a cloned profile id
        result = await spk.say("Je parle maintenant avec la voix clonée.")
        (open("cloned.wav", "wb")).write(result.wav_bytes)

asyncio.run(main())
```

Config-driven (works in the CLI and REST server too — set once, clone everywhere):

```python
from speaker_helper import Speaker, Settings

# empty clone block -> the bundled reference voice is used
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
from speaker_helper.eval import run_eval, load_dataset

async def main() -> None:
    # the mock backend needs no engine — perfect for CI
    async with Speaker(Settings.from_mapping({"backend": "mock"})) as spk:
        report = await run_eval(spk, load_dataset())
    print(report.passed, report.mean_rtf, report.anomaly_rate)
    # True 0.3 0.0

asyncio.run(main())
```

```bash
# CLI: non-zero exit code when the bar is missed (gates CI)
speaker-helper --backend mock eval
speaker-helper --engine kokoro eval --json report.json
```

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

---

## 10. Routing: pick an engine + mode for a condition

State the operating **condition** and let the router choose, justified by
measured quality↔speed evidence:

```python
from speaker_helper import route, RouteRequest, Speaker

# online real-time: speed = RTF, must run faster than real time; among engines
# that keep up, maximise quality -> streaming with low time-to-first-audio.
d = route(RouteRequest(condition="online_realtime", language="fr"))
print(d.engine, d.mode, d.confidence)       # kokoro streaming medium
print(d.justification)                       # cites the numbers + provenance

# offline: quality is the ONLY objective (speed disregarded).
d2 = route(RouteRequest(condition="offline", language="fr"))

# build a Speaker straight from a routed operating point:
spk = Speaker.from_route("online_realtime", language="fr")
```

```bash
speaker-helper --language fr route --condition online_realtime
speaker-helper route --condition offline --json decision.json
```

Under the hood the router selects on the quality↔RTF **Pareto front**; you can
use that primitive directly on a batch of evaluation reports:

```python
from speaker_helper.eval import pareto_front

# reports = [await run_eval(spk_kokoro), await run_eval(spk_chatterbox), ...]
best = pareto_front(reports)   # non-dominated: high quality AND low RTF
for r in best:
    print(r.backend, r.mean_rtf, r.quality)
```

---

## 11. Measuring across languages

```python
import asyncio
from speaker_helper import Settings
from speaker_helper.eval import run_multilang_eval, format_matrix

async def main() -> None:
    reports = await run_multilang_eval(
        Settings.from_mapping({"backend": "kokoro"}),
        ["fr", "en", "es"],
    )
    print(format_matrix(reports))

asyncio.run(main())
```

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
    open("revoiced.wav", "wb").write(out.wav_bytes)

asyncio.run(main())
```

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

---

## 15. The language rules, end to end

The defaults implement the 2026-10 survey (`STUDY.md`, `research` branch),
with **a female voice in every language**:

```python
from speaker_helper import Speaker

# French -> kyutai (native French, voice "developpeuse-3", female)
spk = Speaker.from_route("offline", language="fr")

# English -> chatterbox, Turbo variant (female via the bundled reference)
spk = Speaker.from_route("offline", language="en")

# Any other language -> chatterbox, Multilingual variant (23 languages)
spk = Speaker.from_route("offline", language="es")

# Real-time streaming stays on measured evidence -> kokoro (RTF ~0.22 on CPU)
spk = Speaker.from_route("online_realtime", language="fr")
```

Language resolution everywhere follows one rule: **stated → believed,
unstated → detected** (`langdetect`, seeded), falling back to the configured
`language`.
