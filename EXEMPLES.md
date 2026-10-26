# speaker-helper — Exemples

Un livre de recettes exécutables pour les usages les plus courants. Il n'y a
aucun moteur à lancer : chaque backend tourne dans le même processus que votre
code. Ce que chaque exemple suppose, c'est une installation
(`pip install -e ".[kokoro,server]"`) et, pour la voix par défaut, les poids sur
le disque.

Récupérez-les une fois, puis vérifiez :

```bash
speaker-helper install-voice
speaker-helper health
# {"engine": "kokoro", "loaded": false, "sample_rate": 24000, "status": "ok",
#  "weights": "/Users/vous/.cache/speaker-helper/kokoro"}
```

---

## 1. Synthèse hors ligne vers un fichier (synchrone)

L'appel le plus simple qui soit : synthétiser une chaîne entière et écrire un
WAV.

```python
from speaker_helper import Speaker, Settings

spk = Speaker(Settings.from_mapping({"backend": "kokoro", "language": "fr"}))
result = spk.save("Bonjour, ceci est speaker-helper.", "hello.wav")
print(f"{result.duration_s:.2f}s audio at {result.sample_rate} Hz, RTF {result.rtf:.2f}")
# 3.31s audio at 24000 Hz, RTF 1.13     <- le premier appel construit la session ONNX
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
speaker-helper --engine kokoro voices

# synthèse hors ligne
speaker-helper synth "Bonjour le monde." -o hello.wav

# depuis l'entrée standard
echo "Texte lu depuis l'entrée standard." | speaker-helper synth -o out.wav

# diffusion continue (rapporte le TTFA et la cadence par segment)
speaker-helper synth "Une. Deux. Trois." -o out.wav --stream

# choisir le meilleur moteur et le meilleur mode pour une condition (voir §10)
speaker-helper --language fr route --condition online_realtime
```

`speaker-helper` est un seul groupe click. Les options globales
(`--backend`, `--engine`, `--language`, …) sont portées par le groupe : elles
précèdent donc la sous-commande.

---

## 6. Serveur d'API REST

```bash
speaker-helper serve --bind-host 0.0.0.0 --bind-port 8080
```

```bash
curl -s localhost:8080/health
# {"status":"ok","backend":"kokoro","engine":{"status":"ok","engine":"kokoro",
#  "loaded":true,"weights":"/Users/vous/.cache/speaker-helper/kokoro",
#  "sample_rate":24000}}
# moteur en panne mais serveur debout -> {"status":"degraded","backend":…,"engine_error":…}

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
    # C'est `backend` qui choisit le moteur ; `engine` n'est qu'une étiquette
    # portée par les résultats.
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

Piloté par la configuration (vaut aussi pour la ligne de commande et le
serveur REST — réglé une fois, cloné partout) :

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
# ligne de commande : cloner la voix de référence fournie et synthétiser avec
speaker-helper --clone synth "Bonjour." -o cloned.wav
# ou cloner depuis votre propre audio (transcription dérivée automatiquement) :
speaker-helper --clone-audio my_voice.wav synth "Bonjour." -o out.wav
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
speaker-helper --engine kokoro eval --json report.json
```

Avec un transcripteur (extra `stt`), vous obtenez en plus un aller-retour
WER/chrF :

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
speaker-helper --language fr route --condition online_realtime
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
        Settings.from_mapping({"backend": "kokoro"}),
        ["fr", "en", "es"],
    )
    print(format_matrix(reports))

asyncio.run(main())
```

```bash
# ligne de commande : une matrice, garde-fou sur chaque langue (sortie 1 si l'une échoue)
speaker-helper --engine kokoro eval --languages fr,en,es --json matrix.json
```

---

## 12. Parole vers parole : revoicer un extrait YouTube

```python
import asyncio
from speaker_helper import Speaker, Settings
from speaker_helper.sources import from_youtube, revoice

async def main() -> None:
    src = from_youtube("https://youtu.be/…")            # extra: youtube
    async with Speaker(Settings.from_mapping({"language": "fr"})) as spk:
        out = await revoice(src, spk)                   # transcrit (vocal-helper) + re-parle
    open("revoiced.wav", "wb").write(out.wav_bytes)

asyncio.run(main())
```

---

## 13. Lexique de prononciation : fixer la prononciation d'un mot, une fois

Copiez `lexicon.yaml.example` vers `lexicon.yaml` à côté de votre
`settings.yaml` (ou pointez `settings.lexicon.path` / `SPEAKER_HELPER_LEXICON`
dessus) et chaque synthèse — Python, CLI, REST, GUI — l'honore
automatiquement :

```yaml
# lexicon.yaml
entries:
  - word: "Grasse"        # phonèmes exacts : déterministe sur kokoro
    language: fr
    ipa: "ɡʁas"
  - word: "GitHub"        # ré-écriture orthographique : marche sur tous les moteurs
    language: fr
    respelling: "guite-heube"
  - word: "RGPD"          # ni l'un ni l'autre -> le LLM local dérive une ré-écriture
    language: fr          #   une seule fois (best-engine-ai-helper + Ollama), puis cache
```

```python
from speaker_helper import Speaker, Settings

Speaker(Settings.load()).save("Le RGPD s'applique à GitHub, même à Grasse.", "out.wav")
# kokoro épisse /ɡʁas/ à son étape de phonémisation ; un moteur sans phonèmes
# (chatterbox, kyutai) prononce les ré-écritures à la place. La ré-écriture
# dérivée pour RGPD atterrit dans lexicon.yaml.llm-cache.yaml — supprimez une
# ligne pour re-dériver, ou déplacez-la dans `respelling:` pour en faire une
# décision humaine.
```

---

## 14. Longs textes : découpés aux frontières du discours

`say()` coupe tout texte plus long que `chunking.max_chars` (500 par défaut)
en groupes de phrases, les synthétise dans l'ordre et concatène — parce que
tout moteur neuronal se dégrade au-delà de sa zone de confort. Le LLM local
place les frontières (il ne fait que *grouper* des phrases découpées
localement : le texte lui-même ne peut pas changer) ; sans Ollama, un
empaquetage glouton s'en charge :

```yaml
# settings.yaml — tout est optionnel, voici les défauts
chunking:
  enabled: true
  llm: true
  max_chars: 500
```

---

## 15. Les règles de langue, de bout en bout

Les défauts appliquent l'étude d'octobre 2026 (`STUDY.md`, branche
`research`), avec **une voix féminine dans chaque langue** :

```python
from speaker_helper import Speaker

# Français -> kyutai (français natif, voix "developpeuse-3", féminine)
spk = Speaker.from_route("offline", language="fr")

# Anglais -> chatterbox, variante Turbo (féminine via la référence bundlée)
spk = Speaker.from_route("offline", language="en")

# Toute autre langue -> chatterbox, variante Multilingual (23 langues)
spk = Speaker.from_route("offline", language="es")

# Le streaming temps réel reste sur les preuves mesurées -> kokoro (RTF ~0,22 CPU)
spk = Speaker.from_route("online_realtime", language="fr")
```

La résolution de langue suit partout une seule règle : **précisée → crue,
non précisée → détectée** (`langdetect`, graine fixée), avec la `language`
configurée en dernier recours.
