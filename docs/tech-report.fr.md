---
title: "Speaker Helper — Rapport technique"
subtitle: "Synthèse vocale agnostique du moteur : streaming producteur/consommateur, clonage de voix et une passerelle d'évaluation mesurée"
author: Warith HARCHAOUI
date: Été 2026
bibliography: refs.bib
lang: fr
---

# Résumé

Speaker Helper transforme du texte en parole sur votre propre machine. C'est le
pendant « sortie » de Vocal Helper (parole → texte) dans l'écosystème AI
Helpers [@aihelpers], et il enveloppe un moteur de synthèse vocale *local* —
Voicebox [@voicebox] exécutant le modèle Kokoro [@kokoro] par défaut — derrière
une petite API Python typée, une CLI, une API REST et un serveur Model Context
Protocol [@mcp]. Deux partis pris traversent tout le système. D'abord, **le
moteur est un détail d'implémentation** : chaque composant parle à un protocole
`TTSEngine`, si bien que Voicebox n'est qu'un backend parmi d'autres et qu'un
backend `mock` déterministe rend le paquet (et son évaluation) exécutable en CI
sans serveur. Ensuite, **la qualité se mesure, elle ne se décrète pas** : un jeu
de données committé, des seuils versionnés et des métriques propres à l'audio
(facteur temps réel, anomalies de signal et — avec un transcripteur — un
aller-retour WER / chrF [@popovic2015chrf]) verrouillent le projet comme des
tests unitaires verrouillent du code ordinaire. Nous décrivons l'architecture,
le pipeline de streaming producteur/consommateur, le clonage de voix, les
sources speech-to-speech et la couche d'évaluation, puis nous rapportons des
mesures multilingues : sur Apple Silicon, le backend natif MLX [@mlx] synthétise
Kokoro **6 à 8× plus vite que le temps réel** en français, anglais et espagnol,
alors que le même moteur sur CPU-dans-Docker est à la limite et sensible à la
charge.

# 1. Objectifs et non-objectifs

## 1.1 Objectifs

- **Une boîte à outils opérationnelle, prête à l'emploi**, pas une étude : une
  bibliothèque, une CLI, une API REST et un serveur MCP qu'un développeur seul
  ou une petite équipe peut adopter sans contexte privé.
- **Indépendance vis-à-vis du moteur.** Rien au-dessus de la frontière backend
  ne doit dépendre d'un moteur concret. Ajouter ou remplacer un backend est un
  changement local.
- **Deux modes de synthèse.** *Hors-ligne* (tout le texte → un audio, optimise
  le débit) et *streaming* (découpé en phrases, optimise le temps jusqu'au
  premier son).
- **Clonage de voix trivial** — pointez vers un enregistrement ; la
  transcription est produite automatiquement si elle manque.
- **Une passerelle d'évaluation de premier plan** — vitesse et intégrité du
  signal toujours, fidélité quand un transcripteur est disponible ; branchée à
  la CI via un code de sortie.
- **Local-first et sans coût à l'inférence** — pas d'API hébergée, pas
  d'exfiltration de données.

## 1.2 Non-objectifs

- Nous n'entraînons ni ne livrons de modèle TTS ; nous orchestrons un moteur
  local.
- Nous ne réimplémentons pas la reconnaissance vocale : la transcription est
  déléguée à Vocal Helper (whisper.cpp [@whispercpp; @radford2023whisper]).
- Nous ne cherchons pas un Pareto formel indépendant du moteur ; nous rapportons
  une image *opérationnelle* qualité↔vitesse mesurée sur le moteur livré.

# 2. Vue d'ensemble du système

Le paquet est une pile fine et typée au-dessus d'un moteur en fonctionnement :

```
votre texte ──▶ Speaker (hors-ligne · streaming · clone) ──TTSEngine──▶ moteur ──▶ WAV
                       │
                       └───────────── mesuré par la couche d'évaluation
```

- **Types** (`types.py`) : `Voice`, `AudioResult` (porte `wav_bytes`,
  `sample_rate`, `duration_s`, `compute_s`, et un `rtf` dérivé), `StreamChunk`,
  `VoiceList`, `VoiceSample`.
- **Frontière moteur** (`engine.py`) : le protocole `TTSEngine` —
  `synthesize`, `list_voices`, `health`, `clone_voice`, `aclose` — plus un
  registre de backends. Deux backends sont livrés : `VoiceboxClient` (réel) et
  `MockEngine` (déterministe, sans serveur).
- **Façade** (`speaker.py`) : `Speaker` — `say`, `stream`, `clone_voice`,
  `warmup`, `from_profile`.
- **Interfaces** : CLI (`cli.py`), API REST + MCP (`api.py`, [@fastapi; @fastapimcp]).
- **Évaluation** (`eval/`) : jeux de données, métriques, seuils, runner, priors,
  pont DeepEval [@deepeval], pilote multilingue.
- **Colle écosystème** : journalisation via `os-helper`, découpe/concaténation
  audio via `audio-helper`, transcription via Vocal Helper [@aihelpers].

## 2.1 Format d'échange

L'audio traverse la frontière moteur sous forme d'une charge WAV `bytes` en
mémoire, plus les métadonnées nécessaires pour l'enregistrer, le streamer ou le
*mesurer*. Le facteur temps réel (RTF), quantité centrale de l'étude, vaut
`compute_s / duration_s` : sous `1.0`, c'est plus rapide que le temps réel. Il
est dérivé de l'`AudioResult`, jamais deviné.

# 3. Conception par composant

## 3.1 La frontière moteur

`create_engine(settings)` aiguille selon `settings.backend`. Le backend
`voicebox` cache trois détails pénibles de l'API REST Voicebox : le bootstrap
idempotent d'un *profil* (voix preset ou clonée), un chemin synchrone
`POST /generate/stream` avec repli transparent vers le chemin asynchrone
`/generate` qui déclenche le téléchargement du modèle au premier appel, et des
retries avec backoff exponentiel sur les échecs transitoires (transport / 5xx).
Le backend `mock` rend un signal sinusoïdal déterministe dont la durée suit la
longueur d'entrée et dont le `compute_s` reproduit un RTF configuré — assez pour
exercer chaque chemin de code, y compris les détections d'anomalies de
l'évaluation, sans serveur.

## 3.2 Hors-ligne et streaming : un pipeline producteur/consommateur

`Speaker.say` synthétise tout le texte en un appel. `Speaker.stream` est un
pipeline **producteur/consommateur** borné : un *producteur* découpe le texte en
morceaux de taille phrase (`text.py`) et des *consommateurs* les synthétisent
sous un sémaphore de taille `stream_concurrency`, tandis que l'émission reste
strictement dans l'ordre du texte. Deux hyperparamètres arbitrent entre le temps
jusqu'au premier son (TTFA) et le débit :

- `first_chunk_sentences` (granularité producteur) — `1` rend le premier
  morceau aussi petit que possible, donc le premier son est émis au plus tôt.
- `stream_concurrency` (parallélisme consommateur) — le défaut `1` est un
  pipeline strict : comme un moteur rapide synthétise chaque morceau suivant
  avant la fin de lecture du précédent, le TTFA est minimal sans affamer la
  lecture.

Concrètement, Kokoro synthétisant bien en deçà du temps réel, le pipeline strict
(`stream_concurrency = 1`) atteint le premier son en ≈ 0,8 s, contre ≈ 2,7 s
quand un premier lot plus grand est synthétisé avant toute émission — d'où le
défaut faible latence : granularité producteur plus fine et consommateur strict.
Ces boutons, avec le choix de voix et de moteur, forment le *profil de
fonctionnement* par langue du §5.3.

## 3.3 Clonage de voix

Le clonage est uniforme entre la bibliothèque, la CLI et l'API REST. L'appelant
fournit un ou plusieurs enregistrements de référence ; l'audio trop long est
tronqué à la limite du moteur avec `audio-helper`, et une transcription
manquante est produite avec Vocal Helper puis mise en cache dans un fichier
voisin. Une référence prête à l'emploi est livrée par défaut, si bien que
`--clone` seul produit une voix clonée. Le clonage est exposé sur le protocole
`TTSEngine`, donc un backend incapable de cloner échoue explicitement plutôt que
silencieusement.

## 3.4 Sources speech-to-speech

`sources.py` boucle la chaîne speech-to-speech : `from_youtube` [@ytdlp],
`from_podcast` et `from_microphone` font entrer de l'audio, et `revoice` le
transcrit (Vocal Helper) puis reparle la transcription via un `Speaker` — dans
une voix clonée ou une autre langue. Tous les imports tiers sont paresseux et
derrière des extras optionnels, si bien que le cœur reste léger.

# 4. Méthodologie d'évaluation

Le contrat du projet interdit les « vibe checks » : tout ce qui est IA doit
franchir une barre committée. L'évaluation cible le `Speaker` agnostique du
moteur, si bien que la même passerelle évalue le backend `mock` en CI ou un vrai
moteur en local — seul `backend` change.

## 4.1 Métriques

Toutes les métriques sont en Python pur et sans dépendance au cœur :

- **Vitesse.** RTF par énoncé, résumé par la moyenne et le 95e percentile.
- **Anomalies de signal.** `detect_anomalies` signale, à partir du seul audio,
  `empty_audio`, `invalid_sample_rate`, `clipping` (un échantillon à pleine
  échelle) et `duration_too_short` / `duration_too_long` (caractères par seconde
  hors d'une bande plausible — troncature ou étirement aberrant). C'est le *taux*
  d'anomalie qui est verrouillé.
- **Aller-retour de fidélité (optionnel).** Quand un transcripteur est injecté,
  l'audio est re-transcrit et comparé au texte de référence par le **taux
  d'erreur de mots** (une distance de Levenshtein sur les tokens
  [@levenshtein1966]) et le **chrF** (F-score de n-grammes de caractères
  [@popovic2015chrf]) ; les deux sont implémentés dans le paquet pour éviter une
  dépendance lourde.

## 4.2 Seuils, priors et sélection de Pareto

La barre pass/fail vit dans un `thresholds.yaml` committé : RTF `< 1.0` (moyenne
et p95), taux d'anomalie nul toléré, et — seulement si un transcripteur tourne —
des seuils WER/chrF. Un axe qualité est *toujours* rapporté : chrF mesuré quand
disponible, sinon un **prior** par moteur dans `[0, 1]`, si bien que la sélection
vitesse↔qualité fonctionne sans transcripteur. `pareto_front` extrait les points
non dominés sur le plan qualité↔RTF [@deb2001multiobjective] — la réponse
opérationnelle à « quel réglage livrer ? ».

## 4.3 Un pont DeepEval

Comme les mesures sont propres à l'audio, nous ne forçons pas un framework
texte-seul à mesurer de l'audio ; nous *adaptons* plutôt les mesures en
métriques DeepEval [@deepeval] sur mesure (`RealTimeFactorMetric`,
`AudioIntegrityMetric`). Elles sont déterministes et hors-ligne — pas de LLM, de
clé ni de réseau — si bien que les équipes qui standardisent sur DeepEval
obtiennent les mêmes chiffres dans leur outillage existant.

# 5. Mesures

Matériel : Apple M2 Max. Moteur : Kokoro [@kokoro] sur Voicebox [@voicebox].
Jeux de données : 10 à 12 énoncés de référence committés par langue, voix
choisie automatiquement par langue et préchauffée. La qualité est le prior du
moteur (pas de transcripteur ici) ; le taux d'anomalie est nul dans toutes les
mesures ci-dessous.

## 5.1 Natif MLX (GPU Apple / Metal) — le point de fonctionnement recommandé

| langue | cas | RTF moyen | RTF p95 | verdict |
| ------ | --: | --------: | ------: | ------- |
| fr     | 12  | **0.151** | 0.201   | PASS    |
| en     | 10  | **0.133** | 0.150   | PASS    |
| es     | 10  | **0.141** | 0.170   | PASS    |

Le backend natif sur le GPU Apple synthétise **6 à 8× plus vite que le temps
réel** dans chaque langue. C'est le port par défaut de Speaker Helper (`:17493`).

## 5.2 CPU dans Docker — pour contraste

| langue | cas | RTF moyen | RTF p95 | verdict          |
| ------ | --: | --------: | ------: | ---------------- |
| fr     | 12  | 1.341     | 1.723   | FAIL (RTF > 1.0) |
| en     | 10  | 1.131     | 1.470   | FAIL (RTF > 1.0) |
| es     | 10  | 1.287     | 1.678   | FAIL (RTF > 1.0) |

La synthèse CPU est à la limite et sensible à la charge : à vide, le français
mesure ≈ 0,32–0,37 (réussite), mais sous contention il grimpe au-dessus de 1,0.
Docker sur macOS n'a **pas de passthrough GPU/Metal**, ce qui explique l'écart
d'environ ×8 avec le §5.1. Point crucial : *la qualité et l'intégrité tiennent
dans les deux régimes* (zéro anomalie partout) ; seule la vitesse manque la
barre sur CPU chargé — exactement ce que la passerelle doit détecter.

## 5.3 Profils de fonctionnement par langue

`LanguageProfile` regroupe la voix/moteur d'une langue et ses boutons
producteur/consommateur avec un **point de fonctionnement mesuré**.
`tune_profiles` mesure un ensemble de langues et réinjecte le RTF/qualité de
chaque rapport dans son profil. Les défauts livrés portent les chiffres de
référence du §5.1 (M2 Max, natif MLX) ; un autre hôte les recalibre en un appel.

# 6. Interfaces

- **CLI** : `synth`, `voices`, `clone`, `eval` (avec `--languages` pour une
  matrice), `speak-from` (speech-to-speech), `serve`.
- **REST** : `GET /health`, `GET /voices`, `POST /synth`, `POST /synth/stream`
  (Server-Sent Events, un morceau JSON par phrase [@sse]), `POST /clone`.
- **MCP** [@mcp] : quand `fastapi-mcp` [@fastapimcp] est présent, les mêmes
  endpoints sont montés à `/mcp` comme outils qu'un assistant peut appeler
  directement.

# 7. Limites et travaux futurs

- Les chiffres de RTF dépendent du matériel et de la charge ; c'est
  l'évaluation, pas une table statique, qui fait foi — relancez-la sur votre
  hôte.
- La fidélité a deux moitiés. Le *pipeline* WER/chrF et le *gating par seuils*
  tournent en CI avec des transcripteurs stubs déterministes (un vrai
  aller-retour synthèse→STT exige un moteur vivant que le runner hébergé n'a
  pas) ; le *vrai* aller-retour tourne en local via
  `speaker-helper eval --transcribe` (l'extra `stt`).
- La référence de clonage livrée est dans l'arbre source ; son empaquetage dans
  le wheel reste à faire.
- Prévu : des matrices de Pareto multi-moteurs mesurées par langue, et des
  chaînes speech-to-speech plus riches sur les paquets sources.

# Références
