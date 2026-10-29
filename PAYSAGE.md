# Paysage

🇫🇷 Français · [🇬🇧 LANDSCAPE.md](https://github.com/warith-harchaoui/speaker-helper/blob/main/LANDSCAPE.md)

Projets de synthèse vocale (text-to-speech) voisins et concurrents dans
l'espace « synthèse vocale locale et auto-hébergeable avec clonage de voix »,
comparés à `speaker-helper`. Les notes vont de ⭐ (1) à ⭐⭐⭐⭐⭐ (5), évaluées
sur la tâche visée par `speaker-helper` : une synthèse vocale professionnelle
qui tourne **hors-ligne sur un moteur local**, streame avec un faible temps
jusqu'au premier son, **clone une voix** depuis une courte référence et
s'intègre à un pipeline d'IA via une API typée `dict`/`path` exposée sur
plusieurs surfaces à la fois. Un projet optimisé pour un tout autre usage (une
API cloud, une seule voix système, un checkpoint de recherche) n'est pas
pénalisé dans l'absolu : la note reflète seulement l'adéquation à *ce* créneau.
La grille critère par critère est explicitée dans
[Comment les cases sont notées](#comment-les-cases-sont-notées), avec le détail
des cases qui reposent sur nos propres mesures et de celles qui sont une
lecture des fiches de modèle publiées.

## En un coup d'œil

<!-- TABLE:START -->
| Synthèse vocale | Hors-ligne / local | Streaming | Clonage de voix | Multilingue | Maîtrise de la prononciation | Maîtrise de l'expressivité | Ergonomie pipeline IA | Multi-surface | Installation légère | Licence commerciale |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **speaker-helper** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Coqui XTTS | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐ | ⭐ |
| Piper | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Kokoro | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Chatterbox | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| Kyutai TTS | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐⭐⭐⭐ |
| CosyVoice 2/3 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| F5-TTS | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐ |
| OpenVoice | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| Hume TADA | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐⭐⭐⭐ |
| IndexTTS 2.5 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| Fish Speech | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐ |
| Bark | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| Tortoise-TTS | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| pyttsx3 | ⭐⭐⭐⭐⭐ | ⭐ | ⭐ | ⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| gTTS | ⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐ | ⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| ElevenLabs (cloud) | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
<!-- TABLE:END -->

## Comment les cases sont notées

L'échelle est volontairement grossière et la grille est écrite noir sur blanc,
pour qu'une case puisse être *discutée* plutôt que simplement mise en doute.
Deux colonnes sont **nouvelles en 0.12.0** — prononciation et expressivité —
parce que c'est là-dessus que se joue le cahier des charges du projet (un
lexique appliqué d'office ; une voix « réaliste et vivante ») et qu'aucune
colonne existante ne les captait.

| Critère | ⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
|---|---|---|---|
| Hors-ligne / local | API cloud uniquement | local mais avec une étape hébergée | poids sur disque, rien ne sort de la machine |
| Streaming | par lots seulement, bien plus lent que le temps réel | temps réel dans des conditions favorables | RTF soutenu nettement sous 1 sur un CPU ordinaire |
| Clonage de voix | voix figées uniquement | une banque de voix publiée ou un transfert de timbre limité | zero-shot depuis quelques secondes que vous fournissez |
| Multilingue | anglais seulement | ~5 à 10 langues | 25+ langues dans un seul modèle ou jeu de voix |
| Maîtrise de la prononciation | rien d'autre que ré-écrire le texte d'entrée | partielle (balises de phonèmes ou pinyin) | un lexique **plus** l'IPA inséré tel quel dans le flux de phonèmes |
| Maîtrise de l'expressivité | débit plat et figé | prosodie héritée de l'extrait de référence | un bouton d'émotion / d'intensité explicite et dirigeable |
| Ergonomie pipeline IA | un script de recherche à recopier | importable, avec des aspérités | API typée `dict`/`path` faite pour être appelée |
| Multi-surface | bibliothèque seule | bibliothèque + CLI | bibliothèque + CLI + REST + GUI + MCP |
| Installation légère | plusieurs Go, dépendances lourdes | quelques Go | petit, peu de dépendances |
| Licence commerciale | non commerciale | permissive avec de vraies conditions | permissive (MIT / Apache-2.0) |

La provenance, puisqu'elle change d'une case à l'autre. **Streaming** est la
seule colonne où nous avons nos propres mesures, sur les lignes que cette suite
embarque — kokoro 0,21–0,24, kyutai 0,88, chatterbox 2,3 en / 5,6 fr, en RTF
soutenu à travers `Speaker.stream` sur un M2 Max ([STREAMING.md](STREAMING.md)).
Toutes les autres cases sont une lecture des fiches de modèle et des licences
publiées, notée selon la grille ci-dessus : un jugement, pas un banc d'essai.
**Pocket TTS est délibérément absent** : il est sur la liste de veille de
STREAMING.md §3, mais trop peu de choses sont publiées à son sujet pour remplir
dix cases honnêtement ; une ligne inventée vaudrait moins qu'une ligne
manquante.

## Carte de positionnement

<!-- FIGURE:START -->
Représentation 2D du tableau ci-dessus.

![Carte de positionnement](https://raw.githubusercontent.com/warith-harchaoui/speaker-helper/main/assets/paysage.png)

La carte est un résumé en 2D des 10 critères : à lire comme une forme, pas
comme un classement. « speaker-helper » se situe dans le coin en haut à
droite. Les axes se lisent **Horizontal : Authenticité ↔ Efficacité** (~34 %
de la variance) et **Vertical : Simplicité ↔ Polyvalence** (~25 %) — soit
~60 % du tableau à eux deux.

L'axe horizontal distingue principalement les solutions qui misent sur une production rapide et efficace de la parole, comme speaker-helper, Piper et Kokoro, de celles qui privilégient une reproduction plus authentique, même au prix d'un processus plus lent. L'installation facile, la maîtrise de la prononciation et l'ergonomie des pipelines d'IA sont des facteurs clés qui orientent les options vers l'efficacité, tandis que le clonage de voix et la maîtrise de l'expressivité, au contraire, les rapprochent de l'authenticité. On observe que speaker-helper, bien qu'étant le leader, n'est pas le plus authentique, mais excelle dans sa capacité à produire de la parole rapidement et efficacement.

L'axe vertical oppose, quant à lui, les solutions simples et directes à celles qui offrent une grande variété de fonctionnalités et d'options de personnalisation. La maîtrise de l'expressivité et le clonage de voix sont des éléments qui contribuent à la polyvalence, tandis que l'installation légère et une ergonomie soignée favorisent la simplicité. Plusieurs options, comme Coqui XTTS, Chatterbox, CosyVoice 2/3, F5-TTS, OpenVoice, Hume TADA, IndexTTS 2.5, Fish Speech, Bark et Tortoise-TTS, se regroupent dans le coin supérieur gauche, car elles cherchent toutes à reproduire une parole authentique, mais avec une grande flexibilité et des possibilités de personnalisation.

Enfin, on remarque que plusieurs solutions se positionnent dans le coin supérieur droit, comme speaker-helper, Piper, Kokoro et ElevenLabs (cloud), car elles offrent un bon compromis entre efficacité et polyvalence. À l'opposé, gTTS et pyttsx3 se trouvent dans le coin inférieur droit, privilégiant la simplicité et l'efficacité, mais au détriment de l'authenticité et de la personnalisation. Kyutai TTS se distingue en se positionnant dans le coin inférieur gauche, où l'authenticité est primordiale, mais la simplicité est également recherchée.
<!-- FIGURE:END -->

## Positionnement

`speaker-helper` n'est pas un énième modèle de TTS : c'est la **boîte à outils
autour** des modèles. Il n'atteint un moteur concret qu'à travers le protocole
`TTSEngine`, si bien que Kokoro, Chatterbox, OpenVoice et un `mock` déterministe
se trouvent tous derrière le même `Speaker` typé — et tournent tous dans le
processus appelant : `settings.backend` en choisit un dans un registre et il n'y
a aucun serveur à lancer. Sur ce cœur neutre, il ajoute ce qu'un checkpoint de recherche
ou un simple script d'inférence ne livrent jamais : un **routeur** qui transforme
une *condition* de fonctionnement (temps réel en ligne ou hors-ligne) en
moteur et mode concrets à partir de preuves qualité↔vitesse mesurées, une
**passerelle d'évaluation intégrée** (facteur temps réel, anomalies audio et un
aller-retour texte→parole→texte WER/chrF), un **clonage de voix couplé à
l'auto-transcription** (`vocal-helper` comble une transcription de référence
manquante) et **quatre surfaces** synchronisées : Python, CLI, REST et une GUI web.

C'est un centre de gravité différent de celui du reste du domaine :

- Les **projets-modèles** — Coqui XTTS, Chatterbox, F5-TTS, OpenVoice, Bark,
  Tortoise, puis depuis 2026 Hume TADA, IndexTTS 2.5, CosyVoice 2/3 avec Fish
  Speech — sont d'excellents *moteurs*. Ils clonent bien et tournent
  hors-ligne, mais chacun est une bibliothèque ou un checkpoint : pas de routeur
  inter-moteurs, pas de passerelle d'éval committée, pas de trio
  CLI/REST/GUI et une installation `torch` lourde. speaker-helper préfère en
  *piloter* plusieurs derrière son protocole plutôt que d'en concurrencer un seul.
- Les **moteurs rapides et légers** — Piper, Kokoro — gagnent sur le poids
  d'installation et le facteur temps réel (Kokoro synthétise bien sous le temps
  réel sur CPU, ce qui en fait le choix routé par défaut de speaker-helper pour
  `online_realtime`), mais ils ne clonent pas les voix et s'arrêtent à une
  bibliothèque ou une CLI.
- Les **moteurs à streaming natif** — Kyutai TTS, Hume TADA à ses côtés —
  sont faits pour émettre le son pendant la génération, pas après. Kyutai parle
  un français et un anglais natifs et livre une banque de voix publiée, mais il
  ne vous donne pas le clonage ; son RTF soutenu de 0,88 mesuré ici tombe
  juste au-dessus de notre plafond anti-underrun de 0,8 sur un M2 Max.
  speaker-helper le pilote derrière le même protocole que les autres.
- Les **passe-plats OS / cloud** — pyttsx3, gTTS, ElevenLabs — abandonnent le
  modèle local. pyttsx3 et gTTS sont d'une légèreté triviale mais offrent une
  seule voix système ou un aller-retour cloud, sans clonage ; ElevenLabs est
  au meilleur niveau sur le streaming et la qualité de clonage,
  mais c'est un SaaS payant : il obtient ⭐ sur « hors-ligne / local » par
  construction et votre texte comme votre audio de référence quittent la machine.

Là où `speaker-helper` gagne pour son créneau :

1. **Routeur agnostique du moteur.** Énoncez une *condition*, obtenez un moteur
   et un mode concrets justifiés par les chiffres, jamais au feeling. Les nouveaux
   moteurs s'intègrent comme des données mesurées.
2. **La qualité est verrouillée, pas devinée.** Un jeu de données committé et des
   seuils versionnés font échouer la CI en cas de synthèse lente, d'anomalie
   audio ou d'aller-retour cassé.
3. **Un clonage qui va au bout.** Pointez vers un enregistrement : une
   transcription manquante est produite et les références trop longues sont
   tronquées et ré-alignées automatiquement.
4. **Un cœur, quatre surfaces.** Le même `Speaker` typé est accessible depuis
   Python, une seule CLI click, une API REST et une GUI web, sans dérive
   entre elles.

**La licence est une entrée de routage, pas une note de bas de page.** C'est le
critère qui manquait au tableau jusqu'au 2026-10-23 ; il rebat les cartes :
les moteurs qui clonent le mieux sont largement ceux que vous n'avez pas le
droit de livrer. XTTS v2 est sous CPML, F5-TTS publie du code MIT avec des
poids CC-BY-NC, le S2 Pro de Fish Speech est non commercial — trois moteurs
excellents, trois moteurs inutilisables dans un produit. Ce qui reste pour un
travail commercial est plus étroit qu'un classement par qualité ne le laisse
croire : Kokoro (Apache-2.0), Piper, OpenVoice v2, Bark (MIT), Tortoise
(Apache-2.0), IndexTTS 2.5 et CosyVoice 2/3 (Apache-2.0), puis Chatterbox
(MIT, avec sortie tatouée). Deux moteurs tiennent le milieu, permissifs *avec
une condition qu'il faut vraiment honorer* : Hume TADA (code MIT sur des poids
sous Llama 3.2 Community License, permissifs jusqu'à ce que vous soyez très
gros) et Kyutai TTS (poids en CC-BY-4.0, banques de voix en CC-BY-4.0 / CC0 —
l'usage commercial est permis, l'attribution n'est pas optionnelle). Un routeur
qui n'optimiserait que la qualité vous tendrait une violation de licence avec
une justification jointe : voilà pourquoi `commercial` se place à côté de
`condition`, comme une contrainte énoncée.

Le coût honnête est le **poids d'installation** (⭐⭐⭐). La voix par défaut en
est l'extrémité la moins chère — ONNX Runtime, `espeak-ng` et ~340 Mo de poids
récupérés une fois — mais `ffmpeg` et `libsndfile` restent nécessaires pour la
plomberie audio et la moitié *clonage* tire `torch` et `torchaudio` derrière les
extras `[openvoice]` et `[chatterbox]`. C'est le prix à payer pour être la
couche pipeline par-dessus de vrais moteurs neuronaux plutôt qu'un passe-plat OS
d'un seul fichier.

## Quand choisir quoi

- **`speaker-helper`** — vous voulez une TTS hors-ligne, en streaming et
  clonable, câblée dans un pipeline d'IA : une API typée `dict`/`path`, un routeur
  qui choisit le moteur pour vous, une passerelle d'éval en CI et la même chose
  en CLI / REST / GUI. C'est le pendant naturel de `vocal-helper`
  (parole→texte) : la jambe texte→parole.
- **Coqui XTTS** — vous voulez la plus large couverture multilingue en clonage
  comme bibliothèque, **votre usage n'est pas commercial** (ses poids sont sous
  CPML, pas sous une licence permissive) et vous construirez vous-même le
  service, l'aiguillage puis l'évaluation autour (ou vous laissez
  speaker-helper le piloter derrière le protocole).
- **Chatterbox / F5-TTS / OpenVoice** — la fidélité du clonage prime et
  vous pouvez absorber une installation lourde et écrire la glue vous-même.
- **Kokoro / Piper** — vous avez besoin d'une voix légère, temps réel et adaptée
  au CPU et vous n'avez *pas* besoin de clonage ; Kokoro est exactement ce vers
  quoi speaker-helper aiguille en conditions temps réel.
- **Hume TADA** — vous voulez un flux qui ne peut pas halluciner : le texte avec
  l'audio sont générés dans un seul flux synchronisé, ce qui relève de la
  conception plutôt que d'un artefact de mesure, à un facteur temps réel voisin
  de 0,09 et avec un contexte qui tient des minutes d'audio au lieu de
  secondes. Lisez les termes Llama 3.2 si vous opérez à grande échelle.
- **IndexTTS 2.5** — clonage zéro-coup avec contrôle explicite de l'émotion puis
  de la vitesse, flux à texte synchronisé, poids en Apache-2.0 : l'option
  permissive quand la qualité du clonage compte autant que le droit de livrer.
- **Kyutai TTS** — vous voulez un français et un anglais parlés par un modèle
  entraîné nativement dessus, qui émet le son pendant qu'il génère
  (delayed-streams, ~220 ms annoncés) plutôt qu'après. Acceptez le marché : une
  banque de voix publiée au lieu du clonage de votre propre référence, et
  l'attribution CC-BY dans votre produit.
- **CosyVoice 2/3** — clonage zero-shot à partir de trois secondes environ,
  streaming de la classe ~150 ms, consignes de style en langue naturelle et
  licence Apache-2.0 : le jeu de fonctionnalités le plus large parmi les
  cloneurs permissifs, au prix d'une installation lourde.
- **Fish Speech** — vous vous mesurez au plafond de qualité et le travail est de
  la recherche ou du personnel ; la licence exclut un produit.
- **Bark / Tortoise-TTS** — génération hors-ligne expressive ou haute-fidélité
  quand la latence importe peu (Tortoise est lent, Bark ne streame pas vraiment).
- **pyttsx3** — vous voulez une voix système entièrement hors-ligne, sans modèle,
  sans téléchargement ni clonage.
- **gTTS** — un script jetable où un aller-retour cloud et une seule voix standard
  suffisent et où la confidentialité n'est pas un enjeu.
- **ElevenLabs (cloud)** — qualité de streaming et de clonage au plus haut niveau
  sans installation locale et envoyer texte et audio de référence à une API
  payante ne pose pas de problème.

## Pourquoi il n'y a pas de `speaker-helper-rs`

Plusieurs paquets de cette suite ont un portage Rust — `audio-helper-rs`,
`youtube-helper-rs` — et la question d'un troisième revient régulièrement. La
réponse est non, pour la raison même que ces deux-là donnent à ce qu'ils ont
laissé de côté.

Leur règle de périmètre : **envelopper un binaire système, ne pas
réimplémenter la partie lourde.** `audio-helper-rs` porte le sondage, la
conversion, le découpage et la concaténation par-dessus `ffmpeg` et ne porte
explicitement ni la séparation de sources Demucs ni la similarité MFCC, parce
que les deux demandent une vraie pile d'apprentissage, disproportionnée à la
promesse du crate. `youtube-helper-rs` enveloppe `yt-dlp` au lieu de le
réécrire.

Ici, la partie lourde est la seule partie. La synthèse, c'est de l'inférence
ONNX plus la phonémisation espeak-ng et il n'existe aucun binaire `kokoro` à
envelopper. Un portage voudrait dire le crate `ort` plus une liaison FFI vers
espeak — réimplémenter précisément ce que ces crates ont décidé de ne pas
faire.

Et il n'y a aucun problème que ça résoudrait. Kokoro synthétise déjà à environ
un cinquième du temps réel sur un processeur portable ; le point de
fonctionnement mesuré à travers la façade de ce paquet est un facteur
temps-réel de 0,515. La latence qui compte dans une conversation est dominée
par la détection de fin de tour et par le premier jeton du modèle de langue,
pas par le vocodeur. Un vocodeur plus rapide n'achète rien qu'une oreille
perçoive.

Ce qu'un crate pourrait utilement posséder, c'est la moitié qui n'est pas de
l'inférence : disposer une timeline, assembler du WAV, écrire du WebVTT. Cela
fait quelques centaines de lignes d'arithmétique, à leur place à côté
d'`audio-helper-rs` — et les appeler un helper de *voix* serait les mal
nommer. Si cela se révèle souhaitable un jour, c'est là que ça va.

Cette entrée existe pour que la question soit tranchée une fois plutôt que
rouverte.

## Sources et date de relevé

Les notes des moteurs ainsi que chaque licence ci-dessus ont été vérifiées le
**2026-10-23**. Les licences changent au fil des versions ; une affirmation
de licence périmée est la seule erreur d'ici qui puisse coûter de l'argent à
quelqu'un : la date fait partie de l'affirmation.

- [Best open-source TTS models, compared by license](https://www.cartesia.ai/learn/open-source-tts) — Cartesia
- [9 best open source text-to-speech models in 2026](https://www.bland.ai/blog/best-open-source-text-to-speech-model) — Bland
- [Open-sourcing TADA](https://www.hume.ai/blog/opensource-tada) — Hume AI
- [Faster IndexTTS-2: accelerating and streaming autoregressive zero-shot TTS](https://arxiv.org/html/2607.21042v1) — arXiv
- [Deploying open-source TTS on GPU cloud](https://www.spheron.network/blog/deploy-open-source-tts-gpu-cloud-2026/) — Spheron

## Idées à reprendre

Étudié plutôt que deviné : ce que chaque voisin fait mieux, puis ce que cette bibliothèque devrait changer pour l'égaler. Rien ici n'est un engagement : c'est la liste de lecture dont part la version suivante.

- **`Piper` — un étage toujours disponible** — Minuscule, rapide, uniquement processeur. Un synthétiseur qui route entre moteurs a besoin d'un plancher qu'il atteint toujours : sans GPU ni poids en cache, il faut bien que quelque chose parle. Piper est la réponse habituelle.

- **`Kokoro` — 82 M de paramètres, Apache-2.0, environ 30× le temps réel** — Autour d'1 Go de VRAM contre près de 4 Go pour XTTS v2, puis à peu près dix fois plus rapide. Il ne clone pas de voix, ce qui en fait précisément le bon défaut pour la narration puis le mauvais pour un locuteur cloné.

- **La licence comme critère de routage, non comme note de bas de page** — XTTS v2 est en CPML, non commercial. Chatterbox est en MIT puis clone quand même. Un routeur qui choisit sur la seule qualité peut remettre en silence à un appelant commercial un modèle qu'il n'a pas le droit de livrer. La table des moteurs devrait porter la licence puis la laisser opposer son veto.

- **`Chatterbox` — le contrôle expressif, avec une mise en garde** — MIT, clone depuis une courte référence, puis a gagné 65,3 % des comparaisons à l'aveugle face à ElevenLabs. À noter au regard de l'expérience de ce dépôt : c'est le défaut français actuel ici et le gate de fidélité tient du pile ou face depuis, ce qui plaide pour attacher le seuil au moteur plutôt qu'à un unique seuil global.
