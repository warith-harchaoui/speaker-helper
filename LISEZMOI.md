# speaker-helper

**Synthèse vocale professionnelle — hors-ligne et en streaming — au-dessus d'un
moteur [Voicebox](https://github.com/jamiepine/voicebox) local.**

speaker-helper est l'inverse de
[`vocal-helper`](https://github.com/warith-harchaoui) : là où vocal-helper
transforme la *parole en texte*, speaker-helper transforme le **texte en
parole**. Il fournit une API Python typée, une CLI et une API REST — utilisable
en local (conda + pip) ou comme serveur Docker.

- **Deux modes.** *Hors-ligne* (tout le texte → un audio) et *streaming*
  (découpage en phrases, faible temps jusqu'au premier son).
- **Temps réel sur CPU.** Le moteur `kokoro` par défaut synthétise plus vite
  que le temps réel (RTF nettement inférieur à 1.0) — sans GPU.
- **Tout inclus.** Bibliothèque, CLI, API REST, Docker.

Voir [`EXAMPLES.md`](EXAMPLES.md) pour un recueil d'exemples exécutables, et
[`README.md`](README.md) pour la version anglaise.

---

## Fonctionnement

```
votre texte ──▶ speaker-helper ──HTTP──▶ moteur Voicebox ──▶ audio WAV
               (API / CLI / serveur)     (kokoro, …)
```

speaker-helper est un **client** d'un moteur Voicebox. Lancez Voicebox une
fois, puis pointez speaker-helper dessus.

---

## Installation

### 1. Dépendance système : libsndfile

`soundfile` (pour mesurer et concaténer l'audio) nécessite la bibliothèque
native `libsndfile`.

- macOS 🍎 : `brew install libsndfile`
  (installez `brew` grâce à [brew.sh](https://brew.sh/))
- Ubuntu 🐧 : `sudo apt install libsndfile1`
- Windows 🪟 : incluse dans le wheel `soundfile` — rien à installer.

### 2. Le paquet (conda + pip, en local)

```bash
conda create -n speaker-helper python=3.11 -y
conda activate speaker-helper
pip install -e ".[server]"     # ajoutez ",dev" pour les outils de test/lint
```

### 3. Un moteur Voicebox

```bash
git clone https://github.com/jamiepine/voicebox && cd voicebox
docker compose up --build            # écoute sur 127.0.0.1:17600
```

Indiquez ensuite à speaker-helper où il se trouve (`--port`, `settings.yaml`,
ou `SPEAKER_HELPER_VOICEBOX_PORT`).

---

## Prise en main rapide

```python
from speaker_helper import Speaker, Settings

spk = Speaker(Settings.from_mapping({
    "engine": "kokoro", "language": "fr", "voicebox": {"port": 17600},
}))
result = spk.save("Bonjour le monde.", "hello.wav")
print(f"{result.duration_s:.2f}s d'audio, RTF {result.rtf:.2f}")
# 2.80s d'audio, RTF 0.43
```

```bash
speaker-helper --port 17600 synth "Bonjour le monde." -o hello.wav
speaker-helper --port 17600 synth "Une. Deux. Trois." -o out.wav --stream
speaker-helper --port 17600 serve --host 0.0.0.0 --port 8080
```

---

## Configuration

Copiez [`settings.yaml.example`](settings.yaml.example) vers `settings.yaml`
(ignoré par git). Chaque clé peut être surchargée par une variable
d'environnement `SPEAKER_HELPER_*` ; les références `${VAR}` dans le YAML sont
remplacées depuis l'environnement au chargement.

---

## Développement

```bash
pip install -e ".[dev,server]"
pytest -q -m "not slow"       # suite rapide et déterministe (sans moteur)
pytest -q                     # inclut les tests live @slow (nécessite Voicebox)
ruff check speaker_helper tests
```

---

## Remerciements

Remerciements chaleureux aux contributrices, contributeurs, relectrices,
relecteurs et utilisateurs qui ont aidé à améliorer ce projet — ainsi qu'aux
auteurs de [Voicebox](https://github.com/jamiepine/voicebox).

## Licence

BSD-3-Clause © Warith HARCHAOUI.
