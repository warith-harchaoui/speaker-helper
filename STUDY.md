# Recherche — deux voix féminines (FR + EN) réalistes et vivantes, offline, avec lexique de prononciation

**Date de la recherche : 2026-10-26.** Les classements, licences et versions citées ont
été vérifiés ce jour-là ; tout ici est périssable, la date fait partie de chaque
affirmation. Quatre volets de recherche web indépendants (open source anglais,
français, propriétaire offline, benchmarks + contrôle phonétique), sources
primaires privilégiées (API live du TTS Arena, cartes de modèles, code source
inspecté).

---

## 1. La question posée, et la grille de lecture

Quatre modes d'exploitation, croisement de deux axes :

| | **Local gratuit (open source)** | **Cloud payant (propriétaire)** |
|---|---|---|
| **Offline (différé)** | ← **la présente recherche** → **chatterbox pour TOUTES les langues** : en → Turbo, tout le reste → Multilingual (ratifié ; le fr révisé le 2026-10-28, §8 ter). **C'est aussi le défaut du produit** depuis le 2026-10-28, pas seulement la réponse du routeur (§8 quater) | **indécis : ElevenLabs ou NaturalReaders** (à trancher plus tard ; aucune clef API, aucun backend écrit) |
| **Streaming (temps réel)** | → **[STREAMING.md](STREAMING.md)** → **kokoro pour le moment** (Elo public × RTF ; fr/en mesurés) | **indécis : ElevenLabs ou NaturalReaders** (Cartesia Sonic en challenger d'arène) |

Deux cases hors-diagonale existent aussi, documentées en §7 pour mémoire : le
**propriétaire local** (SDK Acapela, Picovoice Orca… — et les voix intégrées
d'Apple, **écartées : jugées mauvaises à l'écoute par le propriétaire**,
quoi qu'en disent leurs fiches) et les offres on-prem/on-device des grands du
cloud (quasi toutes verrouillées enterprise en 2026).

**Critères durs pour la case visée :**

1. Une voix **féminine française** et une voix **féminine anglaise**, réalistes
   et **vivantes** (prosodie expressive, pas une voix de narrateur plate).
2. **Offline intégral** : poids locaux, aucun réseau à l'exécution. Machine
   cible : Apple M2 Max, 96 Go unifiés, ~30 Go de disque libre.
3. **Lexique de prononciation** : pouvoir forcer la prononciation de certains
   mots, par exemple en notation phonétique (IPA ou équivalent).
4. **Licence** permettant d'expédier (speaker-helper est un produit ; cf.
   LANDSCAPE.md : la licence est une entrée du routeur, pas une note de bas de
   page).

## 2. Le verdict en une phrase

**Aucun moteur open source ne combine aujourd'hui (2026-10-26) vivacité de
pointe, contrôle phonétique déterministe et licence permissive** — les moteurs
les plus vivants (Chatterbox, Kyutai, Qwen3-TTS) n'exposent aucun accès aux
phonèmes, et les moteurs contrôlables (Kokoro, Piper) sont les moins
expressifs. La recommandation (§8) est donc une **paire de moteurs par rôle**,
avec le lexique porté par speaker-helper et non par le moteur — ce que
l'architecture actuelle (`say`/`text`, phonémisation espeak en amont de Kokoro,
`is_phonemes=True`) permet déjà presque gratuitement.

## 3. Où en sont les classements (instantané du 2026-10-26)

- **TTS Arena V2** (TTS-AGI, Hugging Face, API live, 43 modèles) : tout le
  top 10 est propriétaire (Audio8-TTS 1726, Gradium 1610, Aurora 1560…).
  Les meilleures options locales sont **Chatterbox (Elo 1469 ± 20)** et
  **Kokoro v1.0 (1466 ± 24)** — égalité statistique, ~60 Elo sous le milieu de
  tableau fermé. <https://huggingface.co/spaces/TTS-AGI/TTS-Arena-V2>
- **Artificial Analysis, arène open-weights** : 1. Fish Drama 3 Preview (1249,
  licence à plafond de revenus), 2. Breeze TTS 2 (1233, **non commercial**),
  3. Ming-3.0-tts (1192, MIT, sorti le 2026-10-20), … 7. Kokoro (1066),
  12. Chatterbox (1027). Sur le top 6, seuls Ming (MIT) et Step-Audio-EditX
  (Apache, mais CUDA-seulement et phonèmes chinois uniquement) sont
  exploitables commercialement.
  <https://artificialanalysis.ai/text-to-speech/leaderboard/provider-voice/open-weights>
- Artificial Analysis a ouvert des **arènes multilingues (9 langues dont le
  français)** vers octobre 2026 : Cartesia Sonic 3.6 est n°1 dans 7 langues
  sur 9 ; **aucun modèle ouvert ne mène aucune langue**.
- **TTSDS2** (seul benchmark distributionnel multilingue couvrant le français,
  ICLR 2026) : site et espace HF **injoignables le 2026-10-26** (DNS/erreur
  runtime) — pas de classement français par système ce jour. Alternative :
  calculer `ttsds` (PyPI v2.1.1) localement dans ~/speak.
  <https://arxiv.org/abs/2506.19441>
- **UTMOS communautaire** (tts-bench, UTMOS-2022 — *pas* UTMOSv2, corrélation
  de rang seulement) : Chatterbox 4,42 / WER 0,061 · Qwen3-TTS-0.6B 4,27 ·
  Kokoro 4,18 / WER 0,054 · Piper 3,88 · XTTS-v2 3,94.
  <https://5uck1ess.github.io/tts-bench/scores.html>
- **EmergentTTS-Eval** (NeurIPS 2025) : tous les modèles ouverts échouent sur
  la « prononciation complexe » (nombres, URL) ; Orpheus anglicise les mots
  étrangers ; Sesame CSM insère des interjections aléatoires.
  <https://arxiv.org/abs/2505.23009>

Lecture honnête : en offline open source, le plafond de réalisme reste sous
ElevenLabs/Cartesia ; la question n'est pas « qui égale le cloud » mais « quel
compromis vivacité / contrôle / licence on choisit ».

## 4. Le critère qui départage tout : le lexique de prononciation

C'est le critère le plus discriminant de toute la recherche. Trois familles
seulement offrent un override **déterministe** par mot, entièrement offline :

| Mécanisme documenté | Moteur | Syntaxe | Langues |
|---|---|---|---|
| Lien markdown inline + lexiques éditables (misaki G2P) | **Kokoro** | `[Worcester](/wˈʊstər/)` ; lexiques gold/silver extensibles ; entrée phonèmes brute | EN natif ; **FR via espeak** (voir ci-dessous) |
| Blocs phonèmes bruts + dictionnaires espeak compilés | **Piper** | `[[ f ɔ̃ ]]` ; `espeak-ng --compile=fr` | **FR + EN uniformément** |
| Entrée = chaîne IPA (on possède l'étage G2P) | **StyleTTS2** | IPA directe | EN seulement |
| « Pronunciation inpainting » entraîné | **CosyVoice 3** | `mot[K AH0 M]` (CMU/ARPAbet), pinyin | **EN + ZH, pas le FR** |
| Balise inline | **IndexTTS-2.5** | `<minute\|M IH1 N AH0 T>` | EN/ZH/JA, pas de FR (et licence Bilibili sur autorisation écrite) |
| IPA pipe-delimited + dictionnaires G2P | **NVIDIA Magpie 357M** | IPA | 12 langues (couverture FR à vérifier) |
| Phonémiseur espeak en façade | **NeuTTS Air** | chaîne phonémisée acceptée en entrée | selon espeak |

**Impossible** (texte brut → BPE, aucun étage phonémique) : Chatterbox (toutes
variantes — demandes ouvertes [#115](https://github.com/resemble-ai/chatterbox/issues/115),
#550), F5-TTS ([#241](https://github.com/SWivid/F5-TTS/issues/241)), Orpheus,
Dia, Sesame CSM, **Qwen3-TTS**, VibeVoice, Higgs, Maya1, **Kyutai (1.6B et
Pocket)**, Hume TADA, Fish/OpenAudio (balises ARPAbet **EN seulement**),
Ming-3.0 (rien de documenté). Seul recours : la **réécriture orthographique**
(« ONU » → « au-haine-u ») — fragile, dépendante de la voix, invérifiable.
Deux papiers 2026 confirment qu'il n'existe **aucun correctif d'inférence**
pour ces modèles ; les corrections passent par du fine-tuning
(<https://arxiv.org/html/2610.24164>).

**SSML est mort en open source** : aucun moteur moderne ne parse `<phoneme>`.
Le lexique doit donc vivre dans **notre couche de prétraitement** — c'est le
motif vers lequel tout l'écosystème a convergé.

### Pourquoi speaker-helper est déjà aux trois quarts du chemin

Deux points d'ancrage existent **déjà** dans le code :

1. **Niveau texte** : `Segment.text` / `Segment.say` (narration.py,
   speech_text.py) — « les overrides de prononciation appartiennent à qui
   assemble les segments ». Un lexique par réécriture (`say`) fonctionne avec
   *n'importe quel* moteur, y compris Chatterbox/Kyutai. Fiabilité moyenne.
2. **Niveau phonèmes** : le backend Kokoro phonémise lui-même
   (phonemizer + espeak-ng → IPA, suppression des marqueurs de switch,
   `is_phonemes=True` — backends/kokoro.py). Y greffer une substitution
   `mot → IPA` **avant** synthèse donne un lexique déterministe FR + EN pour un
   diff minime. C'est exactement le chemin « DIY » que la recherche identifie
   comme la seule voie française déterministe (l'override inline de misaki ne
   couvre pas le français, qui passe par le fallback espeak).

## 5. Candidats — voix féminine anglaise

| Moteur | Licence (poids) | Vivacité | Lexique | Mac (M2 Max) | Taille | Voix féminines |
|---|---|---|---|---|---|---|
| **Chatterbox-Turbo** | MIT (watermark PerTh par défaut) | ★★★★★ | ✗ (réécriture) | MLX RTF 0,87 (torch-MPS : 2,63) | ~4 Go | clonage ~10 s + défaut |
| **Kokoro af_heart / af_bella** | Apache-2.0 | ★★★ (narratrice soignée) | ★★★★★ natif | >10× temps réel (MLX/CoreML/CPU) | 330 Mo | 15 voix notées (af_heart = A) |
| **CosyVoice 3 0.5B-2512** | Apache-2.0 | ★★★★ (instruct + `[laughter]`) | ★★★★ (CMU inpainting EN) | CPU RTF 0,3–0,5 ; pas de MPS ; pas de MLX officiel | 2–3 Go | clonage 3–10 s (pas de preset) |
| **Qwen3-TTS 1.7B CustomVoice** | Apache-2.0 | ★★★★★ (réputation 2026) | ✗ | mlx-audio de 1re classe | 4,5 Go | Vivian, Serena, Chelsie |
| **IndexTTS-2.5** | autorisation écrite Bilibili | ★★★★★ (vecteur émotion 8D) | ★★★★ (ARPAbet inline) | MPS ok, pas de MLX | 4,7 Go | clonage |
| Magpie 357M (outsider) | NVIDIA Open (commercial ok) | ★★ | ★★★★★ (IPA + dicos) | port MLX communautaire | 0,3–0,6 Go | Aria, Sofia |
| NeuTTS Air (outsider) | Apache-2.0 (watermark) | ★★★ | ★★★★ (entrée phonémisée) | GGUF/llama.cpp, 2–4× TR | 0,5–1 Go | clonage 3 s |

Notes qui pèsent :

- **Chatterbox-Turbo** est le choix « vivant » expédiable : préféré à 65,3 %
  face à ElevenLabs Turbo v2.5 en éval aveugle (Podonos, *commanditée par
  Resemble*), meilleure entrée open du TTS Arena, backend **déjà présent** dans
  speaker-helper et dans le bundle speaker-engines. Son absence totale d'accès
  phonémique est son seul vrai défaut — rédhibitoire seul, acceptable adossé à
  un moteur de garantie (§8).
- **Kokoro** est le seul moteur qui satisfait *tous* les critères durs sans
  réserve (licence, taille, vitesse, lexique) — au prix de la vivacité : pas de
  balises d'émotion, prosodie régulière.
- **CosyVoice 3** est le meilleur compromis mono-moteur EN (expressif *et*
  contrôlable *et* Apache) ; il demande un clip de référence féminin licencié
  et tourne CPU (quand même plus vite que temps réel). Son inpainting ne
  couvre pas le français.
- **Ming-3.0-tts** (MIT, n°1 open en « Controlled Voice », déjà dans
  mlx-audio) est *le modèle à surveiller* : s'il documente un accès phonémique,
  il passe en tête de liste.

## 6. Candidats — voix féminine française

C'est le côté le plus contraint : la qualité française des modèles ouverts est
le maillon faible documenté partout.

| Moteur | Licence (poids) | Français | Vivacité | Lexique | Mac |
|---|---|---|---|---|---|
| **Kyutai TTS 1.6B en_fr** | CC-BY-4.0 (code MIT) | **natif** (labo parisien) : WER FR 3,29 %, prosodie/hésitations saluées | ★★★★ | ✗ | **MLX officiel** (~4 Go) |
| **Chatterbox Multilingual v3** | MIT (watermark) | CER FR 6–8 % (vs <0,2 % sur ses meilleures langues) ; prise en main indépendante ~9/10 — *jamais le modèle de base EN, accent allemand* | ★★★★★ | ✗ | MPS/MLX |
| **Kokoro ff_siwis** | Apache-2.0 | **une seule voix**, <11 h de corpus, grade officiel **B-** ; « légèrement robotique » | ★★ | ★★★★ (via chemin espeak déjà en place) | excellent |
| **Piper fr (siwis, upmc)** | GPL-3.0 (piper1-gpl ; l'original MIT est archivé, oct. 2025) | fiable mais **plate**, « pas expressive » | ★ | ★★★★★ | CPU trivial |
| **Qwen3-TTS** | Apache-2.0 | rapport technique flatteur (WER 2,6–2,9 auto-déclaré) mais retours terrain mitigés : accent québécois, voix « déprimées » | ★★★★ | ✗ | mlx-audio |
| **Pocket TTS (Kyutai)** | CC-BY-4.0 (code MIT) | FR natif, voix Estelle (défaut spectral connu >2 kHz, issue #372) | ★★ | ✗ | 6× TR sur 2 cœurs |
| CosyVoice 3 | Apache-2.0 | 9 langues dont FR, mais preuves françaises rares et inpainting **sans** FR | ★★★ | ✗ (pour le FR) | CPU |

**Juridiquement morts pour un produit** (constat convergent avec LANDSCAPE.md) :
XTTS-v2 (CPML, et Coqui ayant fermé, personne ne vend plus de licence),
Fish/OpenAudio S1-mini (CC-BY-NC-SA), les finetunes français de F5
(CC-BY-NC), MMS-TTS-fra (CC-BY-NC). **Sans français** : IndexTTS-2.5, Dia,
Sesame CSM. **Écosystème académique français** (Lina-Speech/IRCAM, LinTO,
Le Voice Lab) : rien d'expédiable aujourd'hui.

Le trio de tête français est donc : **Kyutai 1.6B** (le plus naturellement
français, banque de voix féminines CC-BY/CC0, clonage volontairement bridé à
des embeddings précalculés), **Chatterbox Multilingual v3** (le plus vivant,
n'importe quelle voix féminine FR par clonage 10 s, mais CER français moyen)
— et **Kokoro ff_siwis** comme garantie de prononciation, pas comme voix
vitrine.

## 7. Les autres cases de la matrice (pour plus tard)

> **Pré-choix ratifié (2026-10-26)** : pour les deux cases « cloud payant »
> (offline et streaming), le fournisseur pressenti est **ElevenLabs** —
> cohérent avec les arènes (ses modèles v3/v4 tiennent le haut des
> classements humains) et avec le constat du LANDSCAPE (« genuinely
> best-in-class on streaming and cloning quality »). Rien n'est implémenté :
> pas de clef API à ce jour, le backend `elevenlabs` reste à écrire le jour
> où la case s'ouvre. Challenger à re-regarder à ce moment-là : Cartesia
> Sonic (n°1 des arènes multilingues, dont le français, fin 2026).

Résumé du volet propriétaire offline — utile le jour où la case « cloud
payant » ou « propriétaire local » s'ouvre :

- **Verrouillé enterprise** (hors de portée d'une petite équipe en 2026) :
  Azure Embedded Speech (le meilleur sur le papier — SDK macOS arm64 natif,
  fr-FR-Denise + en-US-Jenny, SSML `<phoneme>` IPA complet — mais accès
  réservé aux clients gérés par Microsoft) ; Cartesia on-prem/on-device (ironie :
  kernels Metal Apple, beta privée) ; ElevenLabs on-prem/on-device (annoncé
  avril 2026, liste d'attente) ; Camb.ai, Cerence.
- **Réellement accessible** (sur le papier) :
  **Picovoice Orca** (self-serve, macOS arm64, FR + EN, prononciations ARPAbet,
  réalisme moyen) ; SDK **Acapela** (meilleur catalogue féminin FR — Claire,
  Manon, Margaux — et excellent outillage lexique/SAMPA ; devis, build Apple
  Silicon à confirmer) ; **CereProc/Capacity** (macOS, historiquement
  indie-friendly, continuité post-rachat à vérifier). Les **voix intégrées
  d'Apple** (Ava/Zoe, Audrey/Aurélie), que la presse spécialisée décrivait
  comme « bonnes », sont **écartées : le propriétaire les a écoutées et les
  juge mauvaises** — rappel utile que les fiches et revues ne remplacent pas
  une oreille, exactement la leçon du §8 bis.
- **Morts** : Play.ht/PlayAI (fermé déc. 2025), Nuance Vocalizer (retiré
  2025-2026), Supertonic (archivé sept. 2026).

## 8. Recommandation

### L'architecture avant les moteurs

Le lexique vit dans speaker-helper, à deux étages, et devient une **capacité de
la boîte à outils** plutôt qu'une propriété d'un moteur :

1. **Lexique niveau `say`** (réécriture orthographique) — s'applique à tous les
   moteurs, y compris les non-contrôlables ; fiabilité moyenne, à documenter
   comme telle.
2. **Lexique niveau IPA** — greffé sur la phonémisation espeak existante du
   backend Kokoro (`is_phonemes=True`) : déterministe, FR + EN, diff minime.

Le routeur gagne une entrée de plus : un segment contenant des mots du lexique
*critiques* peut être routé vers le moteur à garantie phonétique — cohérent
avec la philosophie « condition → moteur justifié par des nombres ».

### La paire recommandée (case « local gratuit offline »)

- **Anglais, voix féminine : Chatterbox-Turbo** (MIT ; clonage d'une référence
  féminine licenciée ou voix par défaut). Le plus vivant des expédiables,
  backend déjà écrit, MLX plus vite que temps réel. Lexique : étage `say`
  uniquement.
- **Français, voix féminine : Kyutai TTS 1.6B en_fr** (poids CC-BY-4.0, MLX
  officiel). Le seul candidat dont le français est *natif* et documenté comme
  tel ; banque de voix féminines CC-BY/CC0. Nouveau backend à écrire.
  Lexique : étage `say` uniquement.
- **Garantie de prononciation (déjà en place) : Kokoro** (af_heart EN /
  ff_siwis FR) — le filet déterministe pour les segments à vocabulaire
  critique, et le défaut temps réel actuel du routeur.

**Variante conservatrice** si le lexique déterministe prime partout : Kokoro
seul pour les deux langues (af_heart grade A ; ff_siwis grade B-, c'est le
compromis), zéro nouveau backend.

**Challenger à mettre dans le même A/B** : Chatterbox Multilingual v3 en
français (réutilise le backend existant ; si son CER 6–8 % s'avère acceptable
sur notre banc, il fait l'économie d'un backend Kyutai).

### Plan de validation (dans ~/speak, pas ici)

Conformément au partage des rôles (toolbox ↔ expériences) :

1. Banc FR : Kyutai 1.6B vs Chatterbox Multilingual v3 vs Kokoro ff_siwis —
   UTMOSv2 (naturalité), WER/chrF aller-retour (intelligibilité, avec des cas
   pièges français : homographes hétérophones, sigles, anglicismes),
   speaker-sim le cas échéant.
2. Banc EN : Chatterbox-Turbo vs Kokoro af_heart vs CosyVoice 3 (si un clip de
   référence propre est disponible) — mêmes métriques.
3. Banc lexique : taux de respect de prononciations imposées (lexique IPA via
   Kokoro vs réécriture `say` via Chatterbox/Kyutai) sur une liste de mots
   difficiles — c'est la métrique qui n'existe pas encore et que ce critère
   impose de créer.
4. Replier les nombres dans le catalogue du routeur
   (`quality_source="measured_mos"`), ajouter la dimension `lexicon_support`
   aux capacités d'engine.

### Incertitudes assumées

- TTSDS2 injoignable le jour de la recherche : pas de classement FR neutre par
  système ; à recontrôler ou à calculer localement.
- Les chiffres UTMOS publics sont en UTMOS-2022, pas UTMOSv2 : comparables en
  rang, pas en valeur, avec notre banc.
- Le RTF MLX de Kokoro sur M2 Max (13–17×) est interpolé M1 Max/M4 Max, pas
  mesuré ; nos propres mesures (BENCHMARKS.md : RTF 0,22 CPU/ONNX) restent la
  référence.
- La vivacité « ~9/10 » du français de Chatterbox Multilingual vient d'une
  prise en main indépendante unique (archy.net) ; le banc FR tranchera.
- Piper : le projet actif est GPL-3.0 et cherche des mainteneurs — risque de
  gouvernance s'il devait devenir un backend.

## 8 bis. Addendum — le banc a parlé (2026-10-26, soir)

Le plan de validation du §8 a été exécuté le jour même (`~/speak`,
`scripts/exp_ab_voices.py` : UTMOSv2 + aller-retour WER/chrF via vocal-helper
+ RTF, 10 phrases par langue — les 5 déclaratives historiques plus 5 phrases
expressives — moteurs à leur point de fonctionnement réel sur M2 Max :
kyutai en MLX quantifié 8 bits, chatterbox Turbo/Multilingual en torch CPU,
kokoro en ONNX CPU). **Les mesures contredisent la recommandation du §8** :

| scénario | MOS (UTMOSv2) | qualité [0,1] | WER | chrF | RTF |
|---|---:|---:|---:|---:|---:|
| **fr** kokoro `ff_siwis` | **2,87** | **0,468** | **0,039** | **0,970** | 0,23 |
| fr chatterbox (mtl) | 2,66 | 0,414 | 0,111 | 0,953 | 5,80 |
| fr kyutai (cml-10087) | 2,39 | 0,348 | **0,039** | **0,970** | 1,03 |
| **en** kokoro `af_heart` | **3,67** | **0,666** | **0,051** | 0,956 | 0,24 |
| en chatterbox (turbo) | 2,85 | 0,462 | 0,103 | 0,930 | 2,34 |
| en kyutai (p329) | 2,75 | 0,438 | 0,051 | 0,956 | 1,06 |

Enseignements, dans l'ordre où ils ont surpris :

1. **Kokoro gagne la condition offline dans les deux langues, sur les deux
   axes.** Sa régularité de narratrice, que le §5 comptait comme une
   faiblesse de vivacité, est ce que le prédicteur MOS récompense — et le
   diagnostic par phrase a réfuté l'excuse toute prête : les phrases
   expressives ne sont *pas* systématiquement pénalisées (kokoro y score
   même plus haut que sur les plates).
2. **La voix kyutai par défaut était le mauvais cheval.** Un crible de six
   voix féminines de la banque a montré +0,9 MOS entre `developpeuse-3`
   (don vocal CC0) et la meilleure voix CML-TTS « enhanced » (10087) — la
   voix pèse plus que la quantization (q8 ≥ bf16 en MOS mesuré). Le défaut
   du backend est maintenant cml-10087 ; kyutai devient alors co-leader
   d'intelligibilité française (WER 0,039) mais son MOS global reste sous
   kokoro, plombé par ses rendus expressifs.
3. **Chatterbox paie son WER** (0,10–0,11 dans les deux langues) : le prix
   des libertés expressives que le §5/§6 saluaient.
4. **Réserve épistémique, maintenue au premier plan** : UTMOSv2 est entraîné
   sur des panels MOS anglophones ; ses valeurs absolues en français sont une
   extrapolation, et il est plausible qu'il sous-cote le *caractère* des
   moteurs LLM. Un **pack d'écoute** (`~/speak/out/ab_samples/`, les 6
   scénarios × plat/vivant + les variantes kyutai) attend l'arbitrage à
   l'oreille qui pourrait renverser ce verdict — par de nouveaux nombres,
   pas par décret.

Conséquence appliquée (version 0.10.0, branche `research`) : les mesures sont
repliées dans `profiles.MEASURED_QUALITY`/`MEASURED_RTF`, la condition
offline route fr et en vers **kokoro** avec `quality_source="measured_mos"`
et `confidence="high"`, kyutai (MLX, RTF ~1) et chatterbox restent à un
réglage de distance, et le lexique de prononciation couvre les trois moteurs.
La paire du §8 reste la bonne réponse à « la voix la plus vivante » ; elle
n'est plus la bonne réponse par défaut à « la meilleure qualité mesurée ».

### Post-scriptum (2026-10-26, plus tard dans la soirée) — le critère est récusé

Le propriétaire du projet a tranché après lecture : **UTMOSv2 n'est pas le
bon critère, et ce n'est pas un critère que la machine peut porter**. Le
prédicteur note une « naturalité » générique jugée par des panels anonymes
anglophones ; le cahier des charges est « réaliste et **vivante**, agréable à
écouter », un jugement perceptif qui appartient à l'oreille du propriétaire.
Le RTF, de son côté, n'a rien à faire dans l'exposé d'une décision offline.

Conséquence appliquée (révision du repli ci-dessus) : les tables
`MEASURED_QUALITY`/`MEASURED_RTF` sont **retirées du routage** (les nombres
restent consignés ici et dans `~/speak/out/ab_voices.json`) ; les défauts
offline redeviennent le choix éditorial du §8 — **fr → kyutai, en →
chatterbox-Turbo** — affiché honnêtement comme prior de confiance basse.
(Le volet français de cette paire a été révisé depuis : voir §8 ter.) Les
métriques automatiques ne servent plus qu'en garde-fous : plancher
d'intelligibilité (WER/chrF), détection d'anomalies, contrôle F0 du genre.
Le remplaçant prévu du critère est un protocole d'écoute humaine par paires
(à la MUSHRA/Blizzard), dont les scores entreront comme
`quality_source="measured_human"`. Deux acquis du banc survivent au
critère récusé : la voix française kyutai par défaut (cml-10087, soutenue
aussi par le WER 0,039) et les garde-fous chiffrés.

**Décision ratifiée par le propriétaire (2026-10-26)** : la configuration
offline est arrêtée à **fr → kyutai, en → chatterbox (Turbo), es et autres
langues → chatterbox (Multilingual)** — appuyée, au-delà du choix éditorial,
par la littérature à jugement humain (arènes de préférences, retours publiés
sur le français d'unmute, test aveugle Turbo vs ElevenLabs) plutôt que par
les prédicteurs automatiques.

## 8 ter. Révision du français (ratifiée 2026-10-28)

**Décision du propriétaire : en offline local gratuit, le français passe à
chatterbox, pas à kyutai.** Le moteur retenu est le **meilleur chatterbox à
qualité documentée qui parle effectivement français**, c'est-à-dire le modèle
**Multilingual** (23 langues, prior de base 0,90) — Turbo et base sont
anglophones uniquement et n'étaient donc pas candidats pour cette langue.
Aucun réglage n'est nécessaire : `variant="auto"` résout déjà toute langue
non-anglaise vers Multilingual (`backends/chatterbox.py::_variant_for`).

Ce qui change, et ce qui ne change pas :

| | Avant (2026-10-26) | Après (2026-10-28) |
|---|---|---|
| Moteur offline fr | kyutai (`tts-1.6b-en_fr`) | **chatterbox Multilingual** |
| Moteur offline en | chatterbox Turbo | chatterbox Turbo (inchangé) |
| Moteur offline es/autres | chatterbox Multilingual | inchangé |
| Moteur streaming fr/en | kokoro | inchangé (Elo public × RTF) |
| Prior qualité fr | kyutai 0,92 · chatterbox 0,78 | **inchangés** |

La dernière ligne est le point important. **L'arbitrage ne réécrit pas la
preuve qu'il écarte.** Les priors par langue d'`eval/priors.py` continuent de
dire ce qu'ils disaient — kyutai 0,92 contre chatterbox 0,78 en français, avec
sa note de CER 6–8 % — et c'est le routeur qui porte la décision, dans une
table séparée (`router.OFFLINE_RATIFIED_ENGINE`, datée par
`OFFLINE_RATIFIED_AS_OF`). Conséquences vérifiables :

- la décision sort avec `owner_ratified=True` et une justification qui
  **nomme ce qu'elle écrase** (« OVERRIDES the quality argmax … which was
  'kyutai' (quality=0.920) ») ;
- `respect_ratification=False` restitue le classement non arbitré, donc
  kyutai — l'étude garde accès au argmax brut ;
- un `quality_floor` et un `rtf_budget` gardent leur droit de veto : ils sont
  appliqués **avant** l'arbitrage.

### Le RTF sort complètement de la case offline (2026-10-28)

Rappel du propriétaire, le même jour : **« pour le offline, on s'en fout du
RTF ; pour le streaming, oui, c'est important. »** La règle existait depuis le
§8 bis (« le RTF n'a rien à faire dans l'exposé d'une décision offline ») mais
n'était tenue que par convention — et elle avait dérivé : la justification
offline citait encore le `mean_rtf` du gagnant, et pire, la note de
`confidence` d'une décision offline montait à `medium` *parce que* le RTF était
mesuré, hissant un simple prior au rang de demi-preuve sur l'axe qui ne décide
de rien.

Elle est désormais **structurelle**, ce qui veut dire qu'elle ne peut plus
dériver :

- le RTF **ne classe pas** et **ne départage plus les ex æquo** (l'égalité de
  qualité se tranche dans l'ordre du catalogue, de façon déterministe) ;
- une `RouteDecision` hors ligne porte `mean_rtf=None` et
  `rtf_source="not_considered"` — le nombre n'est pas là, il ne peut donc fuir
  ni dans une justification, ni dans un log, ni dans un tableau de bord en aval ;
- la CLI n'imprime plus de couple `mean_rtf=…` sur un verdict offline ;
- seule exception, assumée : un **budget de patience** que l'appelant fixe
  lui-même (`rtf_budget`, désactivé par défaut), nommé dans la justification
  comme *sa* contrainte, jamais comme une propriété du gagnant.

Trois tests verrouillent la règle
(`test_offline_decisions_carry_no_rtf_at_all`,
`test_decisions_report_provenance_and_no_confidence_grade`,
`test_offline_ties_break_without_consulting_speed`). Le streaming, lui, ne
bouge pas d'un iota : sa frontière de faisabilité `RTF < 1` reste le cœur du
critère.

### La note de « confidence » est supprimée (2026-10-28)

Verdict du propriétaire, dans la foulée : **« tes critères de *confidence* sont
bidons : abandonne-les. »** Il a raison, et le bug de RTF ci-dessus en était le
symptôme, pas la cause. L'échelle `high` / `medium` / `low` était une invention
de ce module : trois barreaux arbitraires posés par-dessus des faits, agrégeant
deux axes de nature différente en une seule note, qui se lisait comme une mesure
alors qu'elle n'était qu'un jugement de notre part. Une fois cet emballage
accepté, rien n'empêchait un chronomètre de faire monter un prior d'un cran.

`RouteDecision.confidence` **n'existe plus** — ni dans l'objet, ni dans le JSON
de l'API, ni sur la ligne de la CLI, ni dans le badge de la GUI (qui colore
désormais la **provenance** : mesurée en vert, prior en ambre, plus le badge
`owner-ratified` quand l'arbitrage a joué).

Ce qui reste est strictement factuel, et c'est tout ce dont un lecteur a
besoin : **`quality_source`** (`measured_chrf`, `measured_mos`, `public_elo`,
`prior`, `no_public_elo`) et **`rtf_source`** (`measured`, `estimate`,
`unknown`, `not_considered`). D'où vient chaque nombre, dit en clair. La
conclusion appartient à celui qui lit, pas à une note que nous aurions fabriquée
pour lui.

C'est le même statut épistémique que la paire qu'elle remplace : le jugement
d'une oreille, pas une mesure, et en attente du même remplaçant — le protocole
d'écoute humaine par paires (§8 bis), dont les scores arriveront en
`quality_source="measured_human"` et trancheront le cas français sur preuve
plutôt que par arbitrage. Le trou de données reste entier : aucune arène
publique ne classe les moteurs ouverts en français (STREAMING.md §1).

## 8 quater. Le défaut du produit suit la matrice (2026-10-28)

Jusqu'ici la matrice ne vivait que dans le **routeur**. Un appelant qui la
demandait (`route`, `Speaker.from_route`) obtenait la bonne réponse ; un appelant
qui ne demandait rien — un `Speaker()` nu, un `speaker-helper synth` — prenait le
backend configuré, dont le défaut était `kokoro`. « Le français hors ligne va à
chatterbox » était donc vrai du routeur et **faux du chemin par défaut**.

Rappel du propriétaire : en local gratuit hors ligne, c'est **chatterbox pour
toutes les langues**, avec **Turbo pour l'anglais** ; en local gratuit streaming,
**kokoro pour le moment** ; le cloud payant attendra (ElevenLabs ou
NaturalReaders, pas tranché). Priorité donnée explicitement au hors-ligne.

`settings.backend` vaut désormais **`"auto"`** par défaut, résolu depuis `mode`
— et résolu **à travers le routeur**, pas par une copie en dur de la matrice qui
pourrait diverger : la ratification française, les priors par langue et la
justification imprimée suivent gratuitement. Un backend nommé explicitement
reste respecté tel quel. Points de détail qui comptent :

- l'**exception anglaise** est portée par le backend lui-même
  (`variant="auto"` → Turbo si `en`, Multilingual sinon), donc deux modèles
  différents derrière un seul nom de backend. Le chargement le dit maintenant
  dans les logs, sans quoi rien ne distinguait les deux cellules ;
- `Speaker` stocke les réglages **résolus**, pas le sentinelle : `settings.engine`
  est ce que les rapports d'éval utilisent comme étiquette, et laisser `"auto"`
  aurait attribué de l'audio chatterbox à la mauvaise ligne ;
- la condition online refuse une langue que personne n'a chronométrée plutôt que
  d'affirmer qu'un moteur tient la cadence. C'est juste pour une *question* de
  routage, mais ça ne doit pas laisser `synth --stream` sans moteur : le repli
  est kokoro, le défaut streaming énoncé par le propriétaire, et il est
  **journalisé** — un repli muet est la façon dont un défaut cesse de
  correspondre à sa documentation.

Le coût redouté (« charger 6 Go sur un simple `synth` ») n'existe pas à la
construction : les backends sont instanciés paresseusement et ne chargent leurs
poids qu'à la première synthèse. La CI reste donc légère.

## 9. Sources principales

- TTS Arena V2 (API live) — <https://huggingface.co/spaces/TTS-AGI/TTS-Arena-V2>
- Artificial Analysis, arènes TTS — <https://artificialanalysis.ai/text-to-speech/leaderboard>
- TTSDS2 (ICLR 2026) — <https://arxiv.org/abs/2506.19441>
- EmergentTTS-Eval (NeurIPS 2025) — <https://arxiv.org/abs/2505.23009>
- Kyutai TTS — <https://kyutai.org/tts/> · <https://huggingface.co/kyutai/tts-1.6b-en_fr>
- Chatterbox (Resemble) — <https://github.com/resemble-ai/chatterbox> ·
  <https://www.resemble.ai/resources/chatterbox-multilingual-v3-tts-with-embedded-watermarking-for-25-languages>
- Kokoro / misaki — <https://huggingface.co/hexgrad/Kokoro-82M> · <https://github.com/hexgrad/misaki>
- CosyVoice 3 — <https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512>
- Qwen3-TTS — <https://github.com/QwenLM/Qwen3-TTS>
- mlx-audio — <https://github.com/Blaizzy/mlx-audio>
- Piper (successeur GPL) — <https://github.com/OHF-Voice/piper1-gpl>
- IndexTTS — <https://github.com/index-tts/index-tts>
- Magpie 357M — <https://huggingface.co/nvidia/magpie_tts_multilingual_357m>
- Apple AVSpeech IPA — <https://developer.apple.com/documentation/avfaudio/avspeechsynthesisipanotationattribute>
- Azure Embedded Speech (accès restreint) — <https://learn.microsoft.com/en-us/azure/ai-services/speech-service/embedded-speech>
- Acapela — <https://www.acapela-group.com/voices/repertoire/french-text-to-speech-voices/>
- Picovoice Orca — <https://github.com/Picovoice/orca>
- Blizzard 2023 (référentiel qualité FR) — <https://www.sciencedirect.com/science/article/pii/S088523082400130X>
