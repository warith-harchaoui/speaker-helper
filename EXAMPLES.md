# speaker-helper — Examples

A runnable cookbook of the most common workflows. Every example assumes a
Voicebox engine is running (native on `:17493`, or Docker on `:17600`) and that
you have installed speaker-helper (`pip install -e ".[server]"`).

Set the port once for the shell examples:

```bash
export SPEAKER_HELPER_VOICEBOX_PORT=17600
```

---

## 1. Offline synthesis to a file (sync)

The simplest possible call — synthesise a whole string and write a WAV:

```python
from speaker_helper import Speaker, Settings

spk = Speaker(Settings.from_mapping({"engine": "kokoro", "language": "fr",
                                     "voicebox": {"port": 17600}}))
result = spk.save("Bonjour, ceci est speaker-helper.", "hello.wav")
print(f"{result.duration_s:.2f}s audio at {result.sample_rate} Hz, RTF {result.rtf:.2f}")
# 3.02s audio at 24000 Hz, RTF 0.43
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
speaker-helper --port 17600 voices --engine kokoro

# offline synthesis
speaker-helper --port 17600 synth "Bonjour le monde." -o hello.wav

# from stdin
echo "Texte lu depuis l'entrée standard." | speaker-helper --port 17600 synth -o out.wav

# streaming (reports TTFA + per-chunk cadence)
speaker-helper --port 17600 synth "Une. Deux. Trois." -o out.wav --stream
```

---

## 6. REST API server

```bash
speaker-helper --port 17600 serve --host 0.0.0.0 --port 8080
```

```bash
curl -s localhost:8080/health
# {"status":"ok","voicebox":{"status":"healthy",...}}

curl -s "localhost:8080/voices?engine=kokoro"
# {"engine":"kokoro","voices":[...]}

curl -s -X POST localhost:8080/synth \
     -H 'content-type: application/json' \
     -d '{"text": "Bonjour depuis l'\''API."}' -o out.wav
# out.wav written; X-Audio-Duration-S / X-Audio-RTF returned as headers
```

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
    spk = Speaker(Settings.from_mapping({
        "engine": "chatterbox", "language": "fr", "voicebox": {"port": 17600},
    }))
    async with spk:
        # supply only the recording — transcript auto-derived and aligned:
        voice_id = await spk.clone_voice("malo", [VoiceSample("my_voice.wav", "")])
        print(voice_id)  # e.g. a cloned profile id
        result = await spk.say("Je parle maintenant avec la voix clonée.")
        (open("cloned.wav", "wb")).write(result.wav_bytes)

asyncio.run(main())
```

Config-driven (works in the CLI and REST server too — set once, clone everywhere):

```python
from speaker_helper import Speaker, Settings

# empty clone block -> the bundled ref-malo reference is used
spk = Speaker(Settings.from_mapping({
    "engine": "chatterbox", "voicebox": {"port": 17600},
    "clone": {"name": "ref-malo"},
}))
spk.save("Voix clonée par défaut.", "malo.wav")   # clones on first synthesis
```

```bash
# CLI: clone the bundled ref-malo and synthesise with it
speaker-helper --port 17600 --clone synth "Bonjour." -o cloned.wav
# or clone from your own audio (transcript auto-derived):
speaker-helper --port 17600 --clone-audio my_voice.wav synth "Bonjour." -o out.wav
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
speaker-helper --port 17600 --engine kokoro eval --json report.json
```

With a transcriber (from the `stt` extra) you also get a WER/chrF round-trip:

```python
import asyncio
from speaker_helper import Speaker, Settings
from speaker_helper.eval import run_eval
from speaker_helper.transcription import VocalHelperTranscriber

async def main() -> None:
    async with Speaker(Settings.from_mapping({"voicebox": {"port": 17600}})) as spk:
        report = await run_eval(spk, transcriber=VocalHelperTranscriber("fr"))
    print(report.mean_wer, report.mean_chrf)

asyncio.run(main())
```

---

## 10. Picking an engine on the quality↔speed frontier

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
        Settings.from_mapping({"engine": "kokoro", "voicebox": {"port": 17600}}),
        ["fr", "en", "es"],
    )
    print(format_matrix(reports))

asyncio.run(main())
```

```bash
# CLI: one matrix, gates on every language (exit 1 if any fails)
speaker-helper --port 17600 --engine kokoro eval --languages fr,en,es --json matrix.json
```

---

## 12. Speech-to-speech: re-voice a YouTube clip

```python
import asyncio
from speaker_helper import Speaker, Settings
from speaker_helper.sources import from_youtube, revoice

async def main() -> None:
    src = from_youtube("https://youtu.be/…")            # extra: youtube
    async with Speaker(Settings.from_mapping({"voicebox": {"port": 17600}})) as spk:
        out = await revoice(src, spk)                   # transcribe (vocal-helper) + re-speak
    open("revoiced.wav", "wb").write(out.wav_bytes)

asyncio.run(main())
```
