# speaker-helper — Exemples

Un livre de recettes exécutables pour les usages les plus courants. Chaque
exemple suppose qu'un moteur Voicebox tourne (en natif sur `:17493` ou via
Docker sur `:17600`) et que speaker-helper est installé
(`pip install -e ".[server]"`).

Posez le port une fois pour les exemples en ligne de commande :

```bash
export SPEAKER_HELPER_VOICEBOX_PORT=17600
```

---

## 1. Synthèse hors ligne vers un fichier (synchrone)

L'appel le plus simple qui soit : synthétiser une chaîne entière et écrire un
WAV.

```python
from speaker_helper import Speaker, Settings

spk = Speaker(Settings.from_mapping({"engine": "kokoro", "language": "fr",
                                     "voicebox": {"port": 17600}}))
result = spk.save("Bonjour, ceci est speaker-helper.", "hello.wav")
print(f"{result.duration_s:.2f}s audio at {result.sample_rate} Hz, RTF {result.rtf:.2f}")
# 3.02s audio at 24000 Hz, RTF 0.43
```

---

## 2. Synthèse hors ligne (asynchrone, dans votre propre boucle)

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

## 3. Diffusion continue, avec le temps jusqu'au premier son

La diffusion découpe le texte en phrases et rend l'audio dès que chacune est
prête : la lecture commence donc avant que le paragraphe entier soit
synthétisé.

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

## 4. Lister les voix disponibles

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

## 5. Ligne de commande

```bash
# lister les voix kokoro françaises
speaker-helper --port 17600 voices --engine kokoro

# synthèse hors ligne
speaker-helper --port 17600 synth "Bonjour le monde." -o hello.wav

# depuis l'entrée standard
echo "Texte lu depuis l'entrée standard." | speaker-helper --port 17600 synth -o out.wav

# diffusion continue (rapporte le TTFA et la cadence par segment)
speaker-helper --port 17600 synth "Une. Deux. Trois." -o out.wav --stream

# choisir le meilleur moteur et le meilleur mode pour une condition (voir §10)
speaker-helper route --condition online_realtime --language fr
```

La commande principale `speaker-helper` est un groupe click ; la façade
argparse reste disponible sous `speaker-helper-argparse`. Les options globales
(`--port`, `--backend`, …) précèdent la sous-commande.

---

## 6. Serveur d'API REST

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
# out.wav écrit ; X-Audio-Duration-S / X-Audio-RTF renvoyés en en-têtes

# le routeur, en point d'entrée :
curl -s -X POST localhost:8080/route \
     -H 'content-type: application/json' \
     -d '{"condition": "online_realtime", "language": "fr"}'
# {"engine":"kokoro","mode":"streaming","confidence":"medium","justification":"…"}
```

Le serveur sert aussi une **interface web minimale** sur
`http://localhost:8080/` (synthèse, diffusion, voix, clonage et routeur).

---

## 7. Choisir une voix et une langue précises

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

## 8. Cloner une voix (en ne donnant que l'audio)

La transcription est facultative : sans elle, elle est dérivée par
`vocal-helper` (installez l'extra `stt`) et un enregistrement trop long est
raccourci par `audio-helper`.

```python
import asyncio
from speaker_helper import Speaker, Settings, VoiceSample

async def main() -> None:
    spk = Speaker(Settings.from_mapping({
        "engine": "chatterbox", "language": "fr", "voicebox": {"port": 17600},
    }))
    async with spk:
        # supply only the recording — transcript auto-derived and aligned:
        voice_id = await spk.clone_voice("my-voice", [VoiceSample("my_voice.wav", "")])
        print(voice_id)  # e.g. a cloned profile id
        result = await spk.say("Je parle maintenant avec la voix clonée.")
        (open("cloned.wav", "wb")).write(result.wav_bytes)

asyncio.run(main())
```

Piloté par la configuration (vaut aussi pour la ligne de commande et le
serveur REST — réglé une fois, cloné partout) :

```python
from speaker_helper import Speaker, Settings

# empty clone block -> the bundled reference voice is used
spk = Speaker(Settings.from_mapping({
    "engine": "chatterbox", "voicebox": {"port": 17600},
    "clone": {"name": "ref-fr-female"},
}))
spk.save("Voix clonée par défaut.", "cloned.wav")   # clones on first synthesis
```

```bash
# ligne de commande : cloner la voix de référence fournie et synthétiser avec
speaker-helper --port 17600 --clone synth "Bonjour." -o cloned.wav
# ou cloner depuis votre propre audio (transcription dérivée automatiquement) :
speaker-helper --port 17600 --clone-audio my_voice.wav synth "Bonjour." -o out.wav
```

---

## 9. Garde-fou qualité par la couche d'évaluation

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
# ligne de commande : code de sortie non nul quand la barre n'est pas tenue
speaker-helper --backend mock eval
speaker-helper --port 17600 --engine kokoro eval --json report.json
```

Avec un transcripteur (extra `stt`), vous obtenez en plus un aller-retour
WER/chrF :

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

## 10. Routage : choisir un moteur et un mode pour une condition

Énoncez la **condition** de fonctionnement et laissez le routeur trancher,
justification à l'appui, sur des mesures qualité↔vitesse :

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
speaker-helper route --condition online_realtime --language fr
speaker-helper route --condition offline --json decision.json
```

Sous le capot, le routeur choisit sur le **front de Pareto** qualité↔RTF ; vous
pouvez utiliser cette primitive directement sur un lot de rapports
d'évaluation :

```python
from speaker_helper.eval import pareto_front

# reports = [await run_eval(spk_kokoro), await run_eval(spk_chatterbox), ...]
best = pareto_front(reports)   # non-dominated: high quality AND low RTF
for r in best:
    print(r.backend, r.mean_rtf, r.quality)
```

---

## 11. Mesurer à travers les langues

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
# ligne de commande : une matrice, garde-fou sur chaque langue (sortie 1 si l'une échoue)
speaker-helper --port 17600 --engine kokoro eval --languages fr,en,es --json matrix.json
```

---

## 12. Parole vers parole : revoicer un extrait YouTube

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
