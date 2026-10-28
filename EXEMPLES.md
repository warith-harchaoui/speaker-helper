# speaker-helper — Exemples

🇫🇷 Français · [🇬🇧 EXAMPLES.md](https://github.com/warith-harchaoui/speaker-helper/blob/main/EXAMPLES.md)

Un livre de recettes exécutables pour les usages les plus courants. Il n'y a
aucun moteur à lancer : chaque backend tourne dans le même processus que votre
code. Chaque exemple ci-dessous est donc un script que vous pouvez coller tel
quel.

---

## Table des matières

- [Mise en place](#mise-en-place)
- [1. Synthèse hors ligne vers un fichier (synchrone)](#1-synthèse-hors-ligne-vers-un-fichier-synchrone)
- [2. Synthèse hors ligne (asynchrone, dans votre propre boucle)](#2-synthèse-hors-ligne-asynchrone-dans-votre-propre-boucle)
- [3. Diffusion continue, avec le temps jusqu'au premier son](#3-diffusion-continue-avec-le-temps-jusquau-premier-son)
- [4. Lister les voix disponibles](#4-lister-les-voix-disponibles)
- [5. Lire un document à voix haute, avec les repères que suit une page](#5-lire-un-document-à-voix-haute-avec-les-repères-que-suit-une-page)
- [6. Serveur d'API REST](#6-serveur-dapi-rest)
- [7. Choisir une voix et une langue précises](#7-choisir-une-voix-et-une-langue-précises)
- [8. Cloner une voix (en ne donnant que l'audio)](#8-cloner-une-voix-en-ne-donnant-que-laudio)
- [9. Garde-fou qualité par la couche d'évaluation](#9-garde-fou-qualité-par-la-couche-dévaluation)
- [10. Routage : choisir un moteur et un mode pour une condition](#10-routage--choisir-un-moteur-et-un-mode-pour-une-condition)
- [11. Mesurer à travers les langues](#11-mesurer-à-travers-les-langues)
- [12. Parole vers parole : revoicer un extrait YouTube](#12-parole-vers-parole--revoicer-un-extrait-youtube)
- [13. Lexique de prononciation : fixer la prononciation d'un mot, une fois](#13-lexique-de-prononciation--fixer-la-prononciation-dun-mot-une-fois)
- [14. Longs textes : découpés aux frontières du discours](#14-longs-textes--découpés-aux-frontières-du-discours)
- [15. Les règles de langue, de bout en bout](#15-les-règles-de-langue-de-bout-en-bout)
- [Ligne de commande](#ligne-de-commande)
- [Dépannage](#dépannage)

---

## Mise en place

Une installation, un téléchargement, une vérification. L'extra `kokoro`
apporte le moteur par défaut ; `server` apporte l'API REST ainsi que
l'interface web du §6.

```bash
pip install "speaker-helper[kokoro,server]"   # depuis un clone : pip install -e ".[kokoro,server]"
speaker-helper install-voice                  # récupère les poids du moteur par défaut, une fois
speaker-helper health
# {
#   "engine": "kokoro",
#   "loaded": false,
#   "sample_rate": 24000,
#   "status": "ok",
#   "weights": "/Users/vous/.cache/speaker-helper/kokoro"
# }
```

`health` sort avec un code non nul quand le backend ne peut pas synthétiser :
c'est donc un garde-fou dans un script, pas seulement quelque chose à lire.
`"weights"` indique là où `install-voice` a déposé les 340 Mo — l'emplacement
est rapporté plutôt que supposé.

Tous les exemples Python qui suivent supposent ces deux liaisons, rien de plus :

```python
import asyncio                                 # §2-§5, §8, §9, §11 puis §12 sont asynchrones
from speaker_helper import Speaker, Settings   # la façade ainsi que sa configuration
```

Une section qui a besoin d'autre chose (`VoiceSample`, `route`, la couche
`eval`) l'importe sur place. `Settings.from_mapping({...})` est utilisé partout
pour que chaque extrait se tienne tout seul ; `Settings.load()` lit plutôt
`./settings.yaml` ainsi que les variables d'environnement `SPEAKER_HELPER_*`.

**À propos des nombres en commentaire.** Chaque ligne de sortie ci-dessous a
été produite en exécutant l'extrait qui la précède. Les durées sont la réponse
du moteur lui-même : elles se reproduisent à l'identique. Les **facteurs temps
réel, non** — un RTF dépend de la machine, de l'état de la session ONNX dans le
processus courant ainsi que de ce que fait la machine par ailleurs. Lisez la
forme de la ligne plutôt que ses chiffres ; voyez
[BENCHMARKS.md](BENCHMARKS.md) pour les mesures de la machine de référence
(kokoro, RTF moyen 0,223 en français sur un M2 Max au repos).

---

## 1. Synthèse hors ligne vers un fichier (synchrone)

L'appel le plus simple qui soit : synthétiser une chaîne entière et écrire un
WAV.

```python
from speaker_helper import Speaker, Settings

spk = Speaker(Settings.from_mapping({"backend": "kokoro", "language": "fr"}))
for _ in range(2):
    result = spk.save("Bonjour, ceci est speaker-helper.", "hello.wav")
    print(f"{result.duration_s:.2f}s audio at {result.sample_rate} Hz, RTF {result.rtf:.2f}")
# 2.45s audio at 24000 Hz, RTF 0.84    <- cet appel a aussi construit la session ONNX
# 2.45s audio at 24000 Hz, RTF 0.77    <- tous les appels suivants
```

La première synthèse charge le modèle : son facteur temps réel mesure donc le
*chargement*, pas le moteur. `await spk.warmup()` déplace ce coût là où vous le
voulez — c'est pour cela que le garde-fou d'évaluation préchauffe avant de
chronométrer quoi que ce soit.

---

## 2. Synthèse hors ligne (asynchrone, dans votre propre boucle)

Entrer dans le contexte asynchrone préchauffe le moteur : la mesure ci-dessous
porte donc sur la synthèse plutôt que sur le démarrage.

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
        # time to first audio: 1.83s
        # chunk 0: 1.07s
        # chunk 1: 1.15s
        # chunk 2: 1.43s

asyncio.run(main())
```

`ttfa_s` n'est renseigné que sur le premier segment (`seq == 0`) puis vaut
`None` : c'est une mesure sur le flux, pas un champ par segment.

---

## 4. Lister les voix disponibles

Lister ne demande pas les poids : sans eux la réponse vient du catalogue
embarqué du moteur, parce que « téléchargez 340 Mo puis redemandez » répond mal
à « quelles voix existe-t-il ? ».

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

kokoro donne pour nom de voix son identifiant : `v.name == v.voice_id` ici. Les
présélections de `speaker_helper.voices` portent les noms lisibles :

```python
from speaker_helper import voice_for, voices_for

print(voice_for("fr"))                              # ff_siwis
print([(v.voice_id, v.name) for v in voices_for("fr")])
# [('ff_siwis', 'Siwis'), ('bm_george', 'George (fr)')]
```

---

## 5. Lire un document à voix haute, avec les repères que suit une page

`narrate()` diffère de `stream()` par sa comptabilité, pas par son moteur. Un
document a une structure — les pauses que réclament ses titres, les blocs dont
la forme parlée diffère de la forme imprimée — et qui veut *suivre* la lecture
doit savoir quelle tranche d'audio dit quel bloc :

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

Un segment peut être un `Segment`, un dictionnaire ou une simple chaîne. Les
clés du dictionnaire sont `text`, plus les facultatives `say` (ce que la voix
lit là où la page montre autre chose), `pause_before_ms`, `pause_after_ms`,
`pace` ainsi que `emotion`. L'exécution ci-dessus passe par le backend `mock`
parce que l'arithmétique des repères est le sujet et que `mock` la rend
déterministe ; mettez `kokoro` à la place pour du vrai son.

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
# {"engine":"kokoro","voices":[{"voice_id":"af_alloy","name":"af_alloy",
#  "language":"en","gender":"female","engine":"kokoro"}, … 54 au total]}

curl -s -D - -X POST localhost:8080/synth \
     -H 'content-type: application/json' \
     -d '{"text": "Bonjour depuis l'\''API."}' -o out.wav
# HTTP/1.1 200 OK
# x-audio-duration-s: 1.408
# x-audio-rtf: 1.822
# content-type: audio/wav

# le routeur, en point d'entrée :
curl -s -X POST localhost:8080/route \
     -H 'content-type: application/json' \
     -d '{"condition": "online_realtime", "language": "fr"}'
# {"condition":"online_realtime","engine":"kokoro","backend":"kokoro",
#  "mode":"streaming","quality":0.466,"mean_rtf":0.223,
#  "quality_source":"public_elo","rtf_source":"measured","confidence":"high",
#  "justification":"…","candidates_considered":3,"pareto_size":1}
```

`POST /narrate` répond au §5 sur HTTP — en JSON plutôt qu'en `audio/wav`, parce
que les repères sont la raison d'être de cette route : l'audio voyage avec eux,
encodé en base64. `POST /synth/stream` est le §3 en Server-Sent Events, un
objet JSON par phrase. Le serveur sert aussi une **interface web minimale** sur
`http://localhost:8080/` (synthèse, diffusion, voix, clonage ainsi que le
routeur).

---

## 7. Choisir une voix et une langue précises

```python
from speaker_helper import Speaker, Settings

spk = Speaker(Settings.from_mapping({
    "engine": "kokoro",
    "voice_id": "ff_siwis",   # voix française explicite
    "language": "fr",
}))
result = spk.save("Voix choisie explicitement.", "voice.wav")
print(result.voice_id, f"{result.duration_s:.2f}s")
# ff_siwis 1.54s
```

Chez kokoro une voix *est* une langue — la première lettre de l'identifiant dit
laquelle — donc une `language` en désaccord avec `voice_id` produit un accent
que personne n'a demandé. Laissez `voice_id` vide pour que la langue choisisse
la voix.

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
        # ne fournir que l'enregistrement : transcription dérivée puis alignée
        voice_id = await spk.clone_voice("my-voice", [VoiceSample("my_voice.wav", "")])
        print(voice_id)  # l'identifiant du profil cloné, à réutiliser ensuite
        result = await spk.say("Je parle maintenant avec la voix clonée.")
        with open("cloned.wav", "wb") as f:
            f.write(result.wav_bytes)

asyncio.run(main())
```

`VoiceSample` prend l'audio d'abord (`bytes` ou un chemin) puis sa
transcription ; une transcription vide est le signal « dérive-la pour moi ».

Piloté par la configuration (vaut aussi pour la ligne de commande et le
serveur REST — réglé une fois, cloné partout) :

```python
from speaker_helper import Speaker, Settings

# un bloc clone vide -> la voix de référence fournie est utilisée
spk = Speaker(Settings.from_mapping({
    "backend": "chatterbox",
    "clone": {"name": "ref-fr-female"},
}))
spk.save("Voix clonée par défaut.", "cloned.wav")   # clone à la première synthèse
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
from speaker_helper.eval import load_dataset, run_eval

async def main() -> None:
    # le backend mock n'a besoin d'aucun poids : parfait pour la CI
    async with Speaker(Settings.from_mapping({"backend": "mock"})) as spk:
        report = await run_eval(spk, load_dataset())
    print(report.passed, report.mean_rtf, report.anomaly_rate)
    # True 0.3 0.0

asyncio.run(main())
```

```bash
# ligne de commande : code de sortie non nul quand la barre n'est pas tenue
speaker-helper --backend mock eval
# backend=mock engine=kokoro cases=12
# mean_rtf=0.3 p95_rtf=0.3 anomaly_rate=0.0 quality=1.0 (prior)
# PASS
speaker-helper --engine kokoro eval --json report.json
```

`run_eval` préchauffe le moteur avant de chronométrer : le premier cas ne paie
donc pas le chargement du modèle. Ne passez `warmup=False` que pour mesurer
délibérément un démarrage à froid.

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

Sans transcripteur, `mean_wer` ainsi que `mean_chrf` restent à `None` et leurs
seuils ne sont pas évalués : le rapport le dit plutôt que de noter du vide.

---

## 10. Routage : choisir un moteur et un mode pour une condition

Énoncez la **condition** de fonctionnement et laissez le routeur trancher,
justification à l'appui, sur des mesures qualité↔vitesse :

```python
from speaker_helper import RouteRequest, Speaker, route

# temps réel en ligne : le RTF est une borne de faisabilité dure — le moteur
# doit tourner plus vite que le temps réel (plafond 0,8). Parmi ceux qui
# tiennent la cadence, on maximise la qualité -> diffusion continue à faible
# temps jusqu'au premier son.
d = route(RouteRequest(condition="online_realtime", language="fr"))
print(d.engine, d.mode, d.confidence, d.quality_source)
# kokoro streaming high public_elo

# hors ligne : la qualité est le SEUL objectif (la vitesse est ignorée).
d2 = route(RouteRequest(condition="offline", language="fr"))
print(d2.engine, d2.mode, d2.confidence, d2.quality_source)
# chatterbox offline low prior  <- 'low': offline confidence rates the QUALITY evidence alone

# Le français est tranché par l'arbitrage du propriétaire, pas par l'argmax --
# et le routeur le dit, au lieu de retoucher discrètement les scores.
print(d2.owner_ratified)                            # True
print(d2.justification)
# offline: engine fixed by the owner's ratified choice for 'fr' (as of
# 2026-10-28) -- 'chatterbox' (quality=0.780 [prior]). This OVERRIDES the
# quality argmax over 3 candidate(s), which was 'kyutai' (quality=0.920
# [prior]): a decision, not a measurement. Pass respect_ratification=False
# for the unarbitrated ranking. mode=offline (whole-text synthesis; speed is
# not an objective and no RTF enters this decision).

# Couper l'arbitrage pour voir le classement non arbitré :
print(route(RouteRequest(condition="offline", language="fr",
                         respect_ratification=False)).engine)   # kyutai

# construire un Speaker directement depuis un point de fonctionnement routé :
spk = Speaker.from_route("online_realtime", language="fr")
```

Les deux conditions classent la qualité sur des **critères différents**, et
chaque décision dit lequel via `quality_source` :

- `online_realtime` s'appuie sur l'Elo d'arène publique (`public_elo`), des
  votes humains par paires. Un moteur absent de toute arène publique obtient
  `0.0` avec la provenance `no_public_elo` : un trou de données assumé, jamais
  un prior flatteur déguisé.
- `offline` s'appuie sur les priors par langue ratifiés par le propriétaire
  (`prior`) — ou bien sur le score UTMOSv2 mesuré de kokoro là où il existe
  (`measured_mos`).

`confidence` vaut `high` quand les deux axes sont mesurés, `medium` quand un
seul l'est, `low` quand la décision ne repose que sur des priors.

Sous le capot, la condition en ligne choisit sur le **front de Pareto**
qualité↔RTF ; vous pouvez utiliser cette primitive directement sur un lot de
rapports d'évaluation :

```python
from speaker_helper.eval import pareto_front

# reports = [await run_eval(spk_kokoro), await run_eval(spk_chatterbox), ...]
best = pareto_front(reports)   # non dominés : haute qualité ET RTF bas
for r in best:
    print(r.backend, r.mean_rtf, r.quality)
```

Le mode hors ligne, lui, n'applique **aucun** filtre de Pareto (il rapporte
`pareto_size=0`) : écarter un moteur de meilleure qualité parce que personne ne
l'a chronométré contredirait un objectif qui se moque de la vitesse.

---

## 11. Mesurer à travers les langues

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

Chaque langue a besoin d'un jeu de données embarqué — `available_languages()`
dit lesquelles en ont un. Ces nombres sont exactement ceux que consomme le
filtre de faisabilité en ligne du routeur.

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
    with open("revoiced.wav", "wb") as f:
        f.write(out.wav_bytes)

asyncio.run(main())
```

`from_podcast(feed_url)` ainsi que `from_microphone(seconds=…)` sont les deux
autres sources ; `revoice` accepte aussi un simple chemin de fichier.
Donnez-lui une `language` différente de celle de la source : le même appel
devient un doublage.

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
# dérivée pour RGPD atterrit dans lexicon.yaml.llm-cache.yaml — supprimez-y une
# ligne pour re-dériver ; déplacez-la dans `respelling:` pour en faire une
# décision humaine.
```

La reconnaissance ignore la casse et s'arrête aux frontières de mot : `ONU`
correspond dans `l'ONU !` mais pas à l'intérieur de `monument`. Mettez
`lexicon: {llm: false}` dans `settings.yaml` sur une machine sans Ollama — les
entrées qui portent un `ipa` ou un `respelling` continuent de fonctionner ; les
autres sont laissées telles quelles.

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

Le découpeur s'importe seul quand vous voulez les frontières sans l'audio :

```python
from speaker_helper import chunk_for_streaming, split_sentences

text = "Premier segment. Deuxième segment. Et voici le troisième."
print(split_sentences(text))
# ['Premier segment.', 'Deuxième segment.', 'Et voici le troisième.']
print(chunk_for_streaming(text, first_chunk_sentences=1))
# ['Premier segment.', 'Deuxième segment.', 'Et voici le troisième.']
```

---

## 15. Les règles de langue, de bout en bout

Les défauts hors ligne sont le **choix éditorial du propriétaire** issu de
l'étude d'octobre 2026 ([`STUDY.md`](STUDY.md)) — le français re-tranché le
2026-10-28 (§8 ter) — affiché honnêtement comme tel (`quality_source="prior"`,
et `owner_ratified=True` là où un arbitrage a primé sur le classement) : les
prédicteurs automatiques de naturalité ont été évalués puis **récusés comme
critère hors ligne** — ils notent une
« naturalité » générique de panel anonyme, pas « réaliste et vivante » à
l'oreille humaine (voir `STUDY.md` §8 bis). Les métriques automatiques restent
des garde-fous (plancher WER, détection d'anomalies, contrôle F0 féminin),
jamais le classement ; un protocole d'écoute humaine par paires est le
remplaçant prévu. Chaque voix par défaut est **féminine**, dans chaque moteur :

```python
from speaker_helper import Speaker

# Français -> chatterbox, par l'arbitrage du propriétaire du 2026-10-28 (le
# modèle Multilingual -- le meilleur chatterbox documenté qui parle français ;
# Turbo et base sont anglophones uniquement). Un arbitrage, signalé comme tel.
spk = Speaker.from_route("offline", language="fr")
print(spk.route.engine, spk.route.owner_ratified)   # chatterbox True

# Anglais -> chatterbox (son backend choisit tout seul le modèle Turbo, vivant)
spk = Speaker.from_route("offline", language="en")
print(spk.route.engine)                             # chatterbox

# Toute autre langue -> le modèle Multilingual de chatterbox (23 langues)
spk = Speaker.from_route("offline", language="es")
# rtf_source vaut "not_considered" et mean_rtf vaut None sur TOUTE décision
# hors ligne, aussi bien chronométré soit le moteur : le hors-ligne ne classe
# pas sur la vitesse, donc il n'en rapporte aucune. En citer une inviterait à
# la lire comme une raison.
print(spk.route.engine, spk.route.rtf_source)       # chatterbox not_considered
print(spk.route.mean_rtf)                           # None

# Le streaming temps réel roule sur du mesuré -> kokoro (RTF 0,223 en français)
spk = Speaker.from_route("online_realtime", language="fr")
print(spk.route.engine, spk.route.confidence)       # kokoro high
```

Vous préférez la régularité de narratrice de kokoro ? Elle reste à un réglage
de distance (`backend: kokoro`) ; l'étude compagnonne conserve par ailleurs un
pack d'écoute pour que les défauts se re-décident à l'oreille.

La résolution de langue suit partout une seule règle : **précisée → crue,
non précisée → détectée** (`langdetect`, graine fixée), avec la `language`
configurée en dernier recours.

---

## Ligne de commande

`speaker-helper` est un seul groupe [click](https://click.palletsprojects.com).
Les options globales (`--backend`, `--engine`, `--language`, `--clone`, …) sont
portées par le groupe : elles **précèdent** donc la sous-commande. `-h` ainsi
que `-V` répondent tous les deux.

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

Synthèse, hors ligne puis en diffusion continue (§1, §3) :

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

Voix puis poids (§4) :

```bash
speaker-helper --engine kokoro voices
# ff_siwis	fr	female	ff_siwis
# …54 lignes : voice_id, langue, genre, nom

speaker-helper install-voice
# ✓ Kokoro's weights are already in /Users/vous/.cache/speaker-helper/kokoro
```

Narration avec sa piste minutée (§5) — deux fichiers plutôt qu'un, parce que le
`.vtt` posé à côté du WAV est ce qui permet à une page de surligner le bloc en
cours de lecture :

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

Routage (§10) puis garde-fou qualité (§9) :

```bash
speaker-helper --language fr route --condition online_realtime
# condition=online_realtime engine=kokoro mode=streaming
# quality=0.466 (public_elo) mean_rtf=0.223 (measured) confidence=high
# online_realtime: require mean_rtf <= 0.8 (RTF<1 is the real-time feasibility
# boundary; margin absorbs TTFA + jitter). 1/3 candidates keep up; on the
# 1-point Pareto front, chose 'kokoro' …

speaker-helper route --condition offline --json decision.json
speaker-helper --backend mock eval                               # sortie 1 si la barre n'est pas tenue
speaker-helper --engine kokoro eval --languages fr,en,es --json matrix.json
```

Clonage (§8), re-voicing (§12) puis serveur (§6) :

```bash
speaker-helper --clone synth "Bonjour." -o cloned.wav
speaker-helper --clone-audio my_voice.wav synth "Bonjour." -o out.wav
speaker-helper speak-from --source youtube --url "https://youtu.be/…" -o revoiced.wav
speaker-helper serve --bind-host 0.0.0.0 --bind-port 8080
```

---

## Dépannage

**`health` répond `"the weights are not on this machine"`.** Lancez
`speaker-helper install-voice`. Le moteur par défaut réclame environ 340 Mo
qu'aucun `pip install` ne récupère ; le remède est imprimé dans le champ
`"fix"` du rapport de santé lui-même.

**`health` répond `"kokoro-onnx is not installed"`.** Le moteur vit derrière un
extra : `pip install "speaker-helper[kokoro]"`.

**Le premier appel paraît lent (RTF supérieur à 1).** Il a construit la session
ONNX, ce qui coûte environ cinq secondes une fois par processus.
`await spk.warmup()` — ou l'entrée dans le bloc `async with`, qui l'appelle
pour vous — sort ce coût de votre première vraie requête.

**`route --condition online_realtime` sort en 2 avec « no engine meets the
online RTF ceiling ».** La condition en ligne refuse les moteurs dont le RTF
n'a jamais été mesuré plutôt que de prétendre qu'ils tiennent la cadence.
Relevez `--rtf-ceiling` — ou passez `require_measured_rtf=False` à
`RouteRequest` en acceptant que la décision devienne alors un pari.

**Le clonage échoue sur une transcription manquante.** En dériver une réclame
l'extra `stt` (`pip install "speaker-helper[stt]"`), qui tire `vocal-helper`.
Fournissez `VoiceSample(chemin, "ce qui est réellement dit")` pour s'en passer
complètement.

**Un mot est mal prononcé.** C'est le §13 : une ligne dans `lexicon.yaml`,
plutôt qu'une raison de changer de moteur.
