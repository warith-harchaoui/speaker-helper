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
Helpers [@aihelpers] : il exécute un moteur de synthèse vocale **dans le
processus appelant** — le modèle Kokoro [@kokoro] via ONNX Runtime par défaut —
derrière une petite API Python typée, une CLI, une API REST et une GUI web
minimale. Deux partis pris traversent tout le système. D'abord, **le moteur est
un détail d'implémentation** : chaque composant parle au protocole `TTSEngine`
et `create_engine(settings)` résout `settings.backend` dans un registre, si bien
que le moteur concret est interchangeable et qu'un backend `mock` déterministe
rend le paquet (et son évaluation) exécutable en CI sans aucun modèle. Ensuite, **la qualité se mesure, elle ne se décrète pas** : un jeu
de données committé, des seuils versionnés et des métriques propres à l'audio
(facteur temps réel, anomalies de signal et, avec un transcripteur, un
aller-retour WER / chrF [@popovic2015chrf]) verrouillent le projet comme des
tests unitaires verrouillent du code ordinaire. Ces mêmes preuves mesurées
alimentent un **routeur de backends** qui transforme une *condition* de
fonctionnement (temps réel en ligne ou hors-ligne) en moteur et mode concrets
avec une justification chiffrée et toute la pile peut tourner avec
des **modèles de moteurs et de métriques auto-hébergés** : rien n'est alors
récupéré depuis Hugging Face à l'exécution. Nous décrivons l'architecture, le
pipeline de streaming producteur/consommateur, le clonage de voix, les sources
speech-to-speech, la couche d'évaluation et le routeur, puis nous rapportons des
mesures multilingues : sur Apple Silicon, le backend natif MLX [@mlx] synthétise
Kokoro **6 à 8× plus vite que le temps réel** en français, anglais et espagnol,
tandis que le même moteur sur CPU-dans-Docker est à la limite et sensible à la
charge.

# 1. Objectifs et non-objectifs

## 1.1 Objectifs

- **Une boîte à outils opérationnelle, prête à l'emploi**, pas une étude : une
  bibliothèque, une CLI, une API REST et une GUI web minimale qu'un
  développeur seul ou une petite équipe peut adopter sans contexte privé.
- **Indépendance vis-à-vis du moteur.** Rien au-dessus de la frontière backend
  ne doit dépendre d'un moteur concret. Ajouter ou remplacer un backend reste un
  changement local.
- **Deux modes de synthèse.** *Hors-ligne* (tout le texte → un audio, optimise
  le débit) et *streaming* (découpé en phrases, optimise le temps jusqu'au
  premier son).
- **Clonage de voix trivial** : pointez vers un enregistrement, la
  transcription est produite automatiquement si elle manque.
- **Une passerelle d'évaluation de premier plan** : vitesse et intégrité du
  signal toujours, fidélité quand un transcripteur est disponible ; branchée à
  la CI via un code de sortie.
- **Local-first et sans coût à l'inférence** : pas d'API hébergée, pas
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
  `sample_rate`, `duration_s`, `compute_s` et un `rtf` dérivé), `StreamChunk`,
  `VoiceList`, `VoiceSample`.
- **Frontière moteur** (`engine.py`) : le protocole `TTSEngine` —
  `synthesize`, `list_voices`, `health`, `clone_voice`, `aclose` — plus un
  registre de backends. Quatre backends sont livrés, tous dans le processus :
  `KokoroEngine` (`backends/kokoro.py`, le défaut), `OpenVoiceEngine` et
  `ChatterboxEngine` (clonage) et `MockEngine` (déterministe, sans modèle).
- **Façade** (`speaker.py`) : `Speaker` — `say`, `stream`, `clone_voice`,
  `warmup`, `from_profile`.
- **Interfaces** : CLI (`cli.py`), API REST (`api.py`, [@fastapi]).
- **Évaluation** (`eval/`) : jeux de données, métriques, seuils, runner, priors,
  pont DeepEval [@deepeval], pilote multilingue.
- **Colle écosystème** : journalisation via `os-helper`, découpe et concaténation
  audio via `audio-helper`, transcription via Vocal Helper [@aihelpers].

## 2.1 Format d'échange

L'audio traverse la frontière moteur sous forme d'une charge WAV `bytes` en
mémoire, plus les métadonnées nécessaires pour l'enregistrer, le streamer ou le
*mesurer*. Le facteur temps réel (RTF), quantité centrale de l'étude, vaut
`compute_s / duration_s` : sous `1.0`, la synthèse est plus rapide que le temps réel. Il
est dérivé de l'`AudioResult`, jamais deviné.

# 3. Conception par composant

## 3.1 La frontière moteur

`create_engine(settings)` aiguille selon `settings.backend` dans un registre de
niveau module et `register_backend` permet à un tiers d'y ajouter le sien à
l'exécution. Chaque fabrique enregistrée est paresseuse : le paquet reste donc
importable sur une machine sans runtime ONNX ni poids, rien ne touche à un
modèle avant la première synthèse.

Le backend `kokoro` cache trois détails pénibles de l'exécution d'un modèle dans
le processus : les poids sont cherchés dans deux caches et leur absence est
rapportée par `health()` comme une *raison accompagnée d'un remède* plutôt que
comme une exception à la première phrase ; la voix **est** la langue (la
première lettre du nom l'encode), si bien qu'une voix non renseignée est résolue
depuis la langue détectée au lieu de retomber sur une voix qui phonémiserait le
texte comme s'il était anglais ; et `espeak-ng` est résolu depuis
l'installation système d'abord, parce que la copie embarquée dans la roue
`espeakng-loader` quitte le processus depuis le C quand elle ne trouve pas ses
données. Le clonage, il le refuse franchement en nommant `openvoice` et
`chatterbox` — la réponse utile à une demande qu'il ne peut pas servir.

Un cinquième backend était livré jusqu'à 0.8.0 : un client REST vers un moteur
hors processus sur un port fixe [@voicebox], avec bootstrap idempotent de
profil, repli sync/async et retries à backoff exponentiel sur les échecs
transitoires. Il a été retiré quand le défaut est passé dans le processus, et
avec lui la dépendance HTTP, les erreurs de connexion et le port. Le backend
`mock` rend un signal sinusoïdal déterministe dont la durée suit la
longueur d'entrée et dont le `compute_s` reproduit un RTF configuré : assez pour
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
  avant la fin de lecture du précédent, le TTFA reste minimal sans affamer la
  lecture.

Concrètement, Kokoro synthétisant bien en deçà du temps réel, le pipeline strict
(`stream_concurrency = 1`) atteint le premier son en ≈ 0,8 s, contre ≈ 2,7 s
quand un premier lot plus grand est synthétisé avant toute émission. D'où le
défaut faible latence : granularité producteur plus fine et consommateur strict.
Ces boutons, avec le choix de voix et de moteur, forment le *profil de
fonctionnement* par langue du §5.3.

## 3.3 Clonage de voix

Le clonage est uniforme entre la bibliothèque, la CLI et l'API REST. L'appelant
fournit un ou plusieurs enregistrements de référence ; l'audio trop long est
tronqué à la limite du moteur avec `audio-helper` et une transcription
manquante est produite avec Vocal Helper puis mise en cache dans un fichier
voisin. Une référence prête à l'emploi est livrée par défaut : `--clone` seul
produit donc une voix clonée. Le clonage passe par le protocole
`TTSEngine`, donc un backend incapable de cloner échoue explicitement plutôt que
silencieusement.

## 3.4 Sources speech-to-speech

`sources.py` boucle la chaîne speech-to-speech : `from_youtube` [@ytdlp],
`from_podcast` et `from_microphone` font entrer de l'audio et `revoice` le
transcrit (Vocal Helper) puis reparle la transcription via un `Speaker`, dans
une voix clonée ou une autre langue. Tous les imports tiers sont paresseux et
derrière des extras optionnels : le cœur reste léger.

# 4. Méthodologie d'évaluation

Le contrat du projet interdit les « vibe checks » : tout ce qui est IA doit
franchir une barre committée. L'évaluation cible le `Speaker` agnostique du
moteur, si bien que la même passerelle évalue le backend `mock` en CI ou un vrai
moteur en local ; seul `backend` change.

## 4.1 Métriques

Toutes les métriques sont en Python pur et sans dépendance au cœur :

- **Vitesse.** RTF par énoncé, résumé par la moyenne et le 95e percentile.
- **Anomalies de signal.** `detect_anomalies` signale, à partir du seul audio,
  `empty_audio`, `invalid_sample_rate`, `clipping` (un échantillon à pleine
  échelle) et `duration_too_short` / `duration_too_long` (caractères par seconde
  hors d'une bande plausible, signe d'une troncature ou d'un étirement aberrant). C'est le *taux*
  d'anomalie qui est verrouillé.
- **Aller-retour de fidélité (optionnel).** Quand un transcripteur est injecté,
  l'audio est re-transcrit et comparé au texte de référence par le **taux
  d'erreur de mots** (une distance de Levenshtein sur les tokens
  [@levenshtein1966]) et le **chrF** (F-score de n-grammes de caractères
  [@popovic2015chrf]) ; les deux sont implémentés dans le paquet pour éviter une
  dépendance lourde.

## 4.2 Seuils, priors et sélection de Pareto

La barre pass/fail vit dans un `thresholds.yaml` committé : RTF `< 1.0` (moyenne
et p95), taux d'anomalie nul toléré et, seulement si un transcripteur tourne,
des seuils WER/chrF. Un axe qualité est *toujours* rapporté : chrF mesuré quand
disponible, sinon un **prior** par moteur dans `[0, 1]` ; la sélection
vitesse↔qualité fonctionne donc sans transcripteur. `pareto_front` extrait les points
non dominés sur le plan qualité↔RTF [@deb2001multiobjective], la réponse
opérationnelle à « quel réglage livrer ? ».

## 4.3 Un pont DeepEval

Comme les mesures sont propres à l'audio, nous ne forçons pas un framework
texte-seul à mesurer de l'audio ; nous *adaptons* plutôt les mesures en
métriques DeepEval [@deepeval] sur mesure (`RealTimeFactorMetric`,
`AudioIntegrityMetric` et `RoundTripIdempotenceMetric`, le contrôle chrF
texte→parole→texte). Elles sont déterministes et hors-ligne — pas de LLM, de clé
ni de réseau — et les équipes qui standardisent sur DeepEval retrouvent ainsi
les mêmes chiffres dans leur outillage existant.

## 4.4 Aiguillage des backends

La couche d'évaluation *mesure* la qualité et la vitesse ; le **routeur**
(`speaker_helper.router` : `route`, `RouteRequest`, `RouteDecision`,
`Speaker.from_route`) *agit* sur ces preuves. L'appelant énonce une **condition**
de fonctionnement et le routeur renvoie un moteur et un mode concrets, justifiés par
les chiffres plutôt que devinés :

- **`online_realtime`** — streaming à délai borné. La vitesse est le **facteur
  temps réel (RTF)** et définit une frontière de faisabilité dure : un moteur
  n'est admissible que s'il synthétise *plus vite que le temps réel* (`RTF < 1`),
  avec une marge pour le temps jusqu'au premier son et la gigue (plafond `0.8`).
  Parmi les moteurs qui tiennent le rythme, le routeur **maximise la qualité**
  sur le front de Pareto qualité↔RTF [@deb2001multiobjective] et sélectionne le
  streaming avec des réglages à faible TTFA.
- **`offline`** — par lots. Aucune contrainte temps réel, donc **seule la
  qualité compte** : le moteur de plus haute qualité l'emporte et
  la vitesse est ignorée.

La qualité est l'**intelligibilité** en aller-retour (texte→parole→texte
WER/chrF) quand un moteur a été mesuré, sinon un prior hérité par moteur ; chaque
`RouteDecision` indique lequel via `quality_source` (mesuré ou prior), porte un
flag de `confidence` et une `justification` chiffrée. Les nouveaux
moteurs sont caractérisés dans l'étude compagne et réinjectés ici comme données :
le routeur s'améliore à mesure que les preuves grandissent, sans
aucun changement de code.

## 4.5 Moteurs auto-hébergés (sans Hugging Face)

Le moteur par défaut n'atteint jamais Hugging Face. Ses deux fichiers — un
graphe ONNX d'environ 325 Mo et une banque de voix d'environ 28 Mo — viennent
d'une release `kokoro-onnx` épinglée puis vivent dans
`~/.cache/speaker-helper/kokoro` ; `install.py` épingle leurs tailles exactes en
octets, si bien qu'un téléchargement coupé est réparé au lieu d'être pris pour
une installation et que deux machines installant à une semaine d'écart
obtiennent le même narrateur. Rien n'est récupéré pendant la synthèse : mettre
le moteur en environnement clos revient donc à posséder ce répertoire, qu'il
suffit de recopier pour que `health()` rapporte `status: ok` sans réseau. Seuls
les backends de clonage vont encore chercher leurs propres checkpoints et
`install_engine` dit lesquels il ne tirera pas à votre place.

# 5. Mesures

Mesuré le 2026-10-25. Matériel : Apple M2 Max, macOS 26.5.2. Moteur : Kokoro
[@kokoro] via `kokoro-onnx` 0.6.1 sur onnxruntime 1.26.0, dans le processus, sur
le `CPUExecutionProvider` (sans GPU). Jeux de données : 10 à 12 énoncés de
référence committés par langue, voix choisie automatiquement par langue et
préchauffée. La qualité est le prior du moteur (pas de transcripteur ici) ; le
taux d'anomalie est nul dans toutes les mesures ci-dessous.

## 5.1 Kokoro dans le processus, préchauffé

| langue | cas | RTF moyen | RTF p95 | verdict |
| ------ | --: | --------: | ------: | ------- |
| fr     | 12  | **0.223** | 0.261   | PASS    |
| en     | 10  | **0.237** | 0.299   | PASS    |
| es     | 10  | **0.206** | 0.230   | PASS    |

Quatre à cinq fois plus vite que le temps réel dans chaque langue, sur CPU, avec
zéro anomalie — confortablement sous le plafond `online_realtime` de `0.8` du
routeur. Il y a un seul point de fonctionnement à rapporter plutôt qu'une
comparaison, et c'est précisément le résultat architectural : le moteur est un
backend de ce processus, il n'y a donc ni second processus, ni port, ni chemin
GPU dans le build ONNX à lui opposer.

## 5.2 Le chargement du modèle n'est pas le moteur

Construire la session ONNX coûte environ 5 s, une fois par processus. Face à un
énoncé de 1,19 s, cela domine complètement : le premier appel mesure un RTF de
**4,42**, tous les suivants **0,31**. Un `eval` mono-langue ne préchauffe pas :
sur un processus froid, son premier cas porte ce chargement et la passerelle
rapporte `mean_rtf=0.5219 p95_rtf=1.7617 → FAIL` — même moteur, même jeu de
données, même machine qu'au §5.1, à quelques minutes d'intervalle. C'est pour
cela que `run_multilang_eval` préchauffe chaque langue avant de chronométrer et
que `Speaker.warmup()` est public : un banc d'essai qui inclut une
initialisation unique mesure l'initialisation.

## 5.3 Profils de fonctionnement par langue

`LanguageProfile` regroupe la voix et le moteur d'une langue et ses boutons
producteur/consommateur avec un **point de fonctionnement mesuré**.
`tune_profiles` mesure un ensemble de langues et réinjecte le RTF et la qualité de
chaque rapport dans son profil. Les défauts livrés portent les RTF du §5.1 ;
leur `measured_quality` vient d'une campagne de naturalité UTMOSv2 distincte,
menée dans l'étude compagne, et reste assortie de sa propre provenance plutôt
que fondue dans la même exécution. Un autre hôte recalibre les deux en un appel.

## 5.4 Historique : le moteur qui a été retiré

Jusqu'à 0.8.0, les mesures de cette page décrivaient un moteur REST hors
processus [@voicebox] piloté en HTTP : un build MLX sur le GPU Apple atteignait
un RTF moyen de 0,151 / 0,133 / 0,141 (fr / en / es), tandis que le build CPU du
même moteur dans Docker mesurait 1,341 / 1,131 / 1,287 et manquait la barre,
macOS n'offrant aucun passthrough GPU/Metal vers le conteneur. Ces chiffres sont
conservés, datés et étiquetés, dans `BENCHMARKS.md` ; ils ne sont **pas**
réattribués au moteur mesuré ci-dessus et ni l'un ni l'autre n'est reproductible
depuis ce dépôt. La comparaison reste instructive sur un point : le moteur ONNX
du §5.1 tourne lui aussi sur CPU et il est quatre à six fois plus rapide que ce
conteneur CPU, sans avoir besoin d'un second processus.

# 6. Interfaces

Le même cœur est exposé au travers de cinq surfaces :

- **CLI** : un seul groupe [click](https://click.palletsprojects.com) dont les
  options globales précèdent la sous-commande. Sous-commandes : `synth`,
  `narrate`, `voices`, `clone`, `route`, `eval` (avec `--languages` pour une
  matrice), `speak-from` (speech-to-speech), `install-voice`, `health`,
  `serve`.
- **REST** : `GET /health`, `GET /voices`, `POST /synth`, `POST /synth/stream`
  (Server-Sent Events, un morceau JSON par phrase [@sse]), `POST /clone` et
  `POST /route` (le routeur de backends).
- **GUI web** : une page vanilla-JS + Tailwind minimale et sans dépendance,
  servie à `/`, pour la synthèse, le streaming, les voix, le clonage et le
  routeur.

# 7. Limites et travaux futurs

- Les chiffres de RTF dépendent du matériel et de la charge ; c'est
  l'évaluation, pas une table statique, qui fait foi : relancez-la sur votre
  hôte.
- La fidélité a deux moitiés. Le *pipeline* WER/chrF et le *gating par seuils*
  tournent en CI avec des transcripteurs stubs déterministes (un vrai
  aller-retour synthèse→STT exige un moteur vivant que le runner hébergé n'a
  pas) ; le *vrai* aller-retour tourne en local via
  `speaker-helper eval --transcribe` (l'extra `stt`).
- La référence de clonage livrée est dans l'arbre source ; son empaquetage dans
  le wheel reste à faire.
- Prévu : des matrices de Pareto multi-moteurs mesurées par langue et des
  chaînes speech-to-speech plus riches sur les paquets sources.

# Références
