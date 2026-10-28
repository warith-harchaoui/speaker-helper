# Étude — la case « gratuit local + streaming » : Elo public × RTF

**Date : 2026-10-26.** Volet streaming de la matrice des modes d'exploitation
(le volet offline est dans [STUDY.md](STUDY.md), §1) : {offline, streaming} ×
{local gratuit, cloud payant}. Même contrainte transverse : **voix féminine
dans chaque langue**, lexique de prononciation appliqué d'office.

## 1. Les critères — ratifiés, et pourquoi ceux-là

Le propriétaire a fixé les deux axes de cette case, après la récusation des
prédicteurs MOS automatiques (STUDY.md §8 bis) :

- **Qualité = Elo public** : les arènes de préférences humaines (votes par
  paires agrégés en Elo) sont la seule « littérature » qui mesure réellement
  « naturelle et agréable » à des oreilles humaines, à grande échelle, hors de
  notre contrôle. Référence : **TTS Arena V2** (communautaire, relevé via son
  API le 2026-10-26) ; l'arène open-weights d'Artificial Analysis sert de
  second regard. La date fait partie de l'affirmation (l'Elo bouge à chaque
  vote) : table dans `eval/priors.py` (`PUBLIC_ELO`, `PUBLIC_ELO_AS_OF`).
- **Performance = RTF** (+ TTFA) : mesurés sur la machine de référence
  (M2 Max), à travers le vrai chemin de production
  (`Speaker.stream` : découpage en phrases, pipeline borné, émission
  ordonnée) — pas une boucle synthétique. Le streaming impose `RTF < 1`
  (frontière de faisabilité) avec marge (plafond routeur : 0,8).

Deux réserves affichées d'emblée :

1. **Le trou de données français.** TTS Arena V2 est anglophone ; les arènes
   multilingues d'Artificial Analysis (dont le français) ne classent que des
   modèles fermés. **Aucun Elo public ne couvre les moteurs ouverts en
   français** au 2026-10-26 : pour le fr, l'axe qualité est un proxy anglais,
   assumé et documenté.
2. **Un moteur absent des arènes n'a pas de preuve sous ce critère.** Il est
   marqué `no_public_elo` (qualité 0 dans le catalogue online) — une lacune
   documentée, pas un zéro de qualité, et surtout pas un prior flatteur en
   douce : c'est le mélange priors/mesures qui a déjà failli fausser la case
   offline.

## 2. L'Elo public au 2026-10-26

**TTS Arena V2** (43 modèles ; tout le top 10 est propriétaire — Audio8-TTS
1726, Gradium 1610, Aurora 1560…). Meilleures entrées locales/ouvertes :

| Moteur | Elo | Note |
|---|---:|---|
| **Chatterbox** | **1469 ± 20** | meilleure entrée open ; égalité statistique avec kokoro |
| **Kokoro v1.0** | **1466 ± 24** | la seule entrée `open:true` du haut de tableau |
| Tontaube V1 | 1423 | |
| Fluxions Vui | 1420 | |
| Veena | 1353 | |
| kyutai, pocket-tts, Hume TADA, CosyVoice… | — | **absents de toute arène publique** |

Second regard, arène open-weights d'Artificial Analysis (échelle différente,
ordre seul comparable) : Fish Drama 3 1249 (licence plafonnée, 35 Md params),
Breeze 2 1233 (non commercial), Ming-3.0 1192 (MIT, CUDA-centré), …
Kokoro 1066, Chatterbox 1027. Les deux arènes racontent la même chose :
**en local ouvert, chatterbox et kokoro sont le haut du panier, au coude à
coude.**

## 3. Le paysage des moteurs *streamables* (littérature)

Ce que l'architecture promet, avant mesure :

- **kokoro** — pas de streaming natif, mais RTF si bas que le découpage en
  phrases suffit (c'est le choix historique du routeur).
- **kyutai tts-1.6b** — streaming **natif** (delayed-streams modeling, son
  ADN ; latence ~220 ms annoncée, tourne « sur iPhone » en q8 d'après Kyutai).
- **chatterbox Turbo/Multilingual** — génération autorégressive chunkée ;
  port MLX revendiqué sous temps réel, mais rejeté ici (encodeur de locuteur
  non chargé → la garantie « voix féminine par référence » casse,
  cf. CHANGELOG 0.10.0).
- Hors arène (donc hors critère qualité, en veille) : **Hume TADA** (RTF 0,09
  annoncé, streaming sans hallucination, MLX officiel, licence Llama 3.2),
  **Pocket TTS** (100M, ~6× temps réel sur 2 cœurs, fr natif),
  **CosyVoice 2/3** (streaming 150 ms annoncé). Si l'un d'eux apparaît dans
  une arène publique, il entre dans la course par la grande porte.

## 4. Les mesures (M2 Max, 2026-10-26, `~/speak/scripts/exp_streaming_voices.py`)

Paragraphe de 8 phrases par langue, moteurs chauds, via `Speaker.stream` ;
« RTF soutenu » = calcul total / audio total (le critère d'anti-décrochage),
p95 = la queue que la moyenne cache. Résultats (`~/speak/out/streaming_voices.json`) :

| scénario | TTFA | RTF soutenu | p95 chunk | audio | charge modèle |
|---|---:|---:|---:|---:|---:|
| **kokoro fr** (`ff_siwis`) | **0,95 s** | **0,245** | 0,248 | 28,4 s | 1,6 s |
| **kokoro en** (`af_heart`) | **0,72 s** | **0,241** | 0,251 | 27,1 s | 1,4 s |
| kyutai q8 fr (MLX) | 3,79 s | 0,880 | 0,928 | 33,9 s | 10,2 s |
| kyutai q4 fr (MLX) | 4,00 s | 0,892 | 0,925 | 35,3 s | 2,5 s |
| kyutai q8 en (MLX) | 3,33 s | 0,945 | 1,014 | 34,8 s | 2,5 s |
| chatterbox turbo en (torch) | 6,92 s | 2,289 | 2,497 | 29,5 s | 106,8 s |
| chatterbox mtl fr (torch) | 30,9 s | 5,599 | 5,868 | 40,7 s | 31,8 s |

Enseignements :

1. **Seul kokoro tient le temps réel** sur cette machine — et largement
   (0,24, soit 4× la marge), avec un premier son sous la seconde.
2. **kyutai est le « presque »** : 0,88 soutenu en français, au-dessus du
   plafond 0,8 (la marge anti-décrochage), sous 1,0. Et la quantization 4 bits
   **n'apporte rien** (0,892) : le goulot est la mémoire, pas le calcul — la
   piste q4 est fermée, les pistes restantes sont un chip plus rapide ou un
   plafond assoupli à 1,0 (au prix du risque de décrochage).
3. **chatterbox est disqualifié par le RTF** (2,3 en, 5,6 fr) malgré son Elo
   de tête — la faisabilité prime : un Elo magnifique ne se diffuse pas en
   retard.
4. Incident de mesure consigné : le multilingual **plante sur les entrées
   quasi vides** (« Un. » → `max(): Expected reduction dim 1…`) — corrigé
   dans le banc (échauffement sur vraie phrase) ; à garder en tête côté
   backend si un appelant envoie un texte d'un mot.

## 5. Verdict de la case — et son inscription dans le routeur

**Condition `online_realtime` : fr et en → kokoro** (voix féminines
`ff_siwis` / `af_heart`), parce qu'il est **à la fois** dans l'égalité de
tête de l'Elo public (1466 ± 24 vs 1469 ± 20 pour chatterbox) **et** le seul
à tenir le RTF. Ce n'est pas un choix par défaut : c'est l'intersection des
deux critères ratifiés.

Inscription (version 0.11.0, branche `research`) :

- `eval/priors.py` : `PUBLIC_ELO` (+ date) et `elo_to_unit` (mapping linéaire
  transparent — seul l'ordre compte, la justification imprimée reste traçable
  au nombre public).
- Le catalogue du routeur est **conscient de la condition** : online, la
  qualité = Elo public (`quality_source="public_elo"` ; absent des arènes →
  `no_public_elo`, classé derrière tout moteur classé) ; offline, rien ne
  change ici — la décision ratifiée (STUDY.md §8 bis, français révisé au
  §8 ter) reste la décision.
- `profiles.MEASURED_RTF` : les RTF soutenus mesurés ci-dessus (axe
  performance, jamais récusé) alimentent la porte de faisabilité online.
- Décisions vérifiées : `online fr/en → kokoro` (`public_elo`, confiance
  haute — Elo public + RTF mesuré) ; `offline` → chatterbox partout
  (fr → chatterbox-multilingual **par arbitrage du propriétaire**, ratifié
  2026-10-28 et signalé `owner_ratified=True` ; en → chatterbox-turbo,
  autres → chatterbox-multilingual, tous deux par argmax de qualité).
  **La case streaming n'est pas touchée** par cette révision : son critère
  est l'Elo public croisé au RTF, et kokoro y reste le seul moteur à la fois
  classé en arène et sous le plafond anti-underrun de 0,8.

## 6. Ce qui ferait bouger le verdict

- **Un Elo public pour kyutai** (ou TADA, ou pocket-tts) : la table
  `PUBLIC_ELO` est faite pour être re-relevée ; un moteur classé et
  temps-réel-faisable rebattrait les cartes en une ligne.
- **Une arène française ouverte** : combler LE trou de données ; d'ici là,
  l'écoute humaine par paires du propriétaire (protocole prévu, STUDY.md
  §8 bis) reste l'arbitre français légitime.
- **Du matériel plus rapide** : kyutai passe sous 0,8 avec ~15 % de débit en
  plus — un M4/M5 Max l'amènerait vraisemblablement dans la zone, et le
  streaming natif DSM ferait alors mieux que notre TTFA par phrases.
- **Le port MLX chatterbox réparé en amont** (encodeur de locuteur chargé) :
  RTF annoncé 0,33 sur cette machine — à re-tester à chaque release de
  `mlx-audio`.

## 7. Sources

- TTS Arena V2 (API live) — <https://huggingface.co/spaces/TTS-AGI/TTS-Arena-V2>
- Artificial Analysis, arènes TTS — <https://artificialanalysis.ai/text-to-speech/leaderboard>
- Kyutai delayed-streams (streaming natif, on-device) — <https://kyutai.org/tts/>
- Hume TADA — <https://github.com/HumeAI/tada>
- Pocket TTS — <https://github.com/kyutai-labs/pocket-tts>
- Mesures locales — `~/speak/out/streaming_voices.json` (script
  `~/speak/scripts/exp_streaming_voices.py`)
