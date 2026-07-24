# Paysage

🇫🇷 Français · [🇬🇧 LANDSCAPE.md](https://github.com/warith-harchaoui/speaker-helper/blob/main/LANDSCAPE.md)

Projets de synthèse vocale (text-to-speech) voisins et concurrents dans
l'espace « synthèse vocale locale et auto-hébergeable avec clonage de voix »,
comparés à `speaker-helper`. Les notes vont de ⭐ (1) à ⭐⭐⭐⭐⭐ (5), évaluées
sur la tâche visée par `speaker-helper` — une synthèse vocale professionnelle
qui tourne **hors-ligne sur un moteur local**, streame avec un faible temps
jusqu'au premier son, **clone une voix** depuis une courte référence, et
s'intègre à un pipeline d'IA via une API typée `dict`/`path` exposée sur de
nombreuses surfaces à la fois. Un projet optimisé pour un tout autre usage (une
API cloud, une unique voix système, un checkpoint de recherche) n'est pas
pénalisé dans l'absolu — la note reflète seulement l'adéquation à *ce* créneau.

## En un coup d'œil

| Synthèse vocale | Hors-ligne / local | Streaming | Clonage de voix | Multilingue | Ergonomie pipeline IA | Multi-surface | Installation légère |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **speaker-helper** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| Coqui XTTS | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐ |
| Piper | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| Kokoro | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ |
| Chatterbox | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ |
| F5-TTS | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ |
| OpenVoice | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐ |
| Bark | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ |
| Tortoise-TTS | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐ | ⭐ |
| pyttsx3 | ⭐⭐⭐⭐⭐ | ⭐ | ⭐ | ⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| gTTS | ⭐ | ⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| ElevenLabs (cloud) | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ |

## Carte de positionnement

Représentation 2D du tableau ci-dessus.

![Carte de positionnement](https://raw.githubusercontent.com/warith-harchaoui/speaker-helper/main/assets/paysage.png)

La carte est un résumé en 2D des 7 critères : à lire comme une forme, pas comme un classement. « speaker-helper » se situe dans le coin en haut à droite. Les axes se lisent **Horizontal — Installation ↔ Clonage** et **Vertical — Ligne ↔ Ergonomie**.

## Positionnement

`speaker-helper` n'est pas un énième modèle de TTS — c'est la **boîte à outils
autour** des modèles. Il ne parle à un moteur concret (Voicebox par défaut) qu'à
travers un protocole `TTSEngine`, si bien que Kokoro, Chatterbox, les moteurs de
la classe XTTS et un `mock` déterministe se trouvent tous derrière le même
`Speaker` typé. Sur ce cœur neutre, il ajoute ce qu'un checkpoint de recherche
ou un simple script d'inférence ne livrent jamais : un **routeur** qui transforme
une *condition* de fonctionnement (temps réel en ligne vs. hors-ligne) en un
moteur + mode concrets à partir de preuves qualité↔vitesse mesurées, une
**passerelle d'évaluation intégrée** (facteur temps réel, anomalies audio et un
aller-retour texte→parole→texte WER/chrF), un **clonage de voix couplé à
l'auto-transcription** (`vocal-helper` comble une transcription de référence
manquante), et **cinq surfaces** synchronisées — Python, CLI, REST, une GUI web
et un serveur MCP pour les assistants.

C'est un centre de gravité différent de celui du reste du domaine :

- Les **projets-modèles** — Coqui XTTS, Chatterbox, F5-TTS, OpenVoice, Bark,
  Tortoise — sont d'excellents *moteurs*. Ils clonent bien et tournent
  hors-ligne, mais chacun est une bibliothèque ou un checkpoint : pas de routeur
  inter-moteurs, pas de passerelle d'éval committée, pas de quatuor
  CLI/REST/GUI/MCP, et une installation `torch` lourde. speaker-helper préfère en
  *piloter* plusieurs derrière son protocole plutôt que d'en concurrencer un seul.
- Les **moteurs rapides et légers** — Piper, Kokoro — gagnent sur le poids
  d'installation et le facteur temps réel (Kokoro synthétise bien sous le temps
  réel sur CPU, ce qui en fait le choix routé par défaut de speaker-helper pour
  `online_realtime`), mais ils ne clonent pas les voix et s'arrêtent à une
  bibliothèque/CLI.
- Les **passe-plats OS / cloud** — pyttsx3, gTTS, ElevenLabs — abandonnent le
  modèle local. pyttsx3 et gTTS sont d'une légèreté triviale mais offrent une
  seule voix système ou un aller-retour cloud, sans clonage ; ElevenLabs est
  véritablement au meilleur niveau sur le streaming et la qualité de clonage,
  mais c'est un SaaS payant : il obtient ⭐ sur « hors-ligne / local » par
  construction, et votre texte et votre audio de référence quittent la machine.

Là où `speaker-helper` gagne pour son créneau :

1. **Routeur agnostique du moteur.** Énoncez une *condition*, obtenez un moteur +
   mode concrets justifiés par les chiffres — jamais au feeling. Les nouveaux
   moteurs s'intègrent comme des données mesurées.
2. **La qualité est verrouillée, pas devinée.** Un jeu de données committé et des
   seuils versionnés font échouer la CI en cas de synthèse lente, d'anomalie
   audio ou d'aller-retour cassé.
3. **Un clonage qui va au bout.** Pointez vers un enregistrement ; une
   transcription manquante est produite et les références trop longues sont
   tronquées et ré-alignées automatiquement.
4. **Un cœur, cinq surfaces.** Le même `Speaker` typé est accessible depuis
   Python, une CLI argparse *et* une CLI click, une API REST, une GUI web et MCP
   — sans dérive entre elles.

Le coût honnête est le **poids d'installation** (⭐⭐⭐) : un vrai moteur veut
`torch`, plus `ffmpeg` et `libsndfile` pour la plomberie audio, et un Voicebox en
fonctionnement. C'est le prix à payer pour être la couche pipeline au-dessus de
vrais moteurs neuronaux plutôt qu'un passe-plat OS d'un seul fichier.

## Quand choisir quoi

- **`speaker-helper`** — vous voulez une TTS hors-ligne, en streaming et
  clonable, câblée dans un pipeline d'IA : une API typée `dict`/`path`, un routeur
  qui choisit le moteur pour vous, une passerelle d'éval en CI, et la même chose
  en CLI / REST / GUI / MCP. En particulier le pendant naturel de `vocal-helper`
  (parole→texte) — c'est la jambe texte→parole.
- **Coqui XTTS** — vous voulez un seul moteur de clonage multilingue solide et
  permissif comme bibliothèque, et vous construirez vous-même le service,
  l'aiguillage et l'évaluation autour (ou laissez speaker-helper le piloter
  derrière le protocole).
- **Chatterbox / F5-TTS / OpenVoice** — la fidélité du clonage est la priorité et
  vous pouvez absorber une installation lourde et écrire la glue vous-même.
- **Kokoro / Piper** — vous avez besoin d'une voix légère, temps réel et adaptée
  au CPU, et vous n'avez *pas* besoin de clonage ; Kokoro est exactement ce vers
  quoi speaker-helper aiguille en conditions temps réel.
- **Bark / Tortoise-TTS** — génération hors-ligne expressive ou haute-fidélité
  quand la latence importe peu (Tortoise est lent, Bark ne streame pas vraiment).
- **pyttsx3** — vous voulez une voix système entièrement hors-ligne, sans modèle,
  sans téléchargement et sans clonage.
- **gTTS** — un script jetable où un aller-retour cloud et une voix standard
  unique suffisent et où la confidentialité n'est pas un enjeu.
- **ElevenLabs (cloud)** — qualité de streaming et de clonage au plus haut niveau
  sans installation locale, et envoyer texte + audio de référence à une API
  payante est acceptable.
