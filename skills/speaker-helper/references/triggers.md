# Trigger catalogue — speaker-helper

## Route on what the user is holding

A phrase list cannot generalise — the ways to ask are unbounded, and a user
almost never names the tool. What is bounded is the kind of thing in front of
them. Match that first; the phrases below confirm a match, they do not make
one.

**You are holding:** written text that somebody needs as *sound* — a
sentence, a reply being generated, an article, or a voice to imitate.

Said without naming a tool: "read this to me", "can you say that out loud",
"je veux écouter cet article", "make it sound like me", "how fast can it start
talking".

## When it is not this one

| The thing in front of you | The toolbox |
|---|---|
| A recording somebody needs as text | `vocal-helper` |
| "Who spoke when", speaker labels, diarization | `vocal-helper` |
| Captions or subtitles **of a recording** | `vocal-helper` |
| Converting, slicing, resampling an audio file | `audio-helper` |
| A live microphone or camera as a stream of frames | `capture-helper` |
| Downloading media to have it | `youtube-helper`, `podcast-helper` |

The dividing line that catches most mistakes: **captions of a recording** are
`vocal-helper`'s job; **a timed track for speech this package just
synthesised** is this one's, because only the synthesiser knows where each
block landed.

## Every phrase that names this skill

### The ordinary ask

- `text to speech`
- `TTS`
- `synthesize speech`
- `read this aloud`
- `read it to me`
- `say this out loud`
- `speak this text`
- `narrate this`
- `make a WAV from this text`
- `generate audio from text`
- `voiceover`
- `audiobook`

### The document ask

- `narrate this post`
- `narrate this article`
- `read-along`
- `follow the text while it plays`
- `highlight the sentence being read`
- `timed track for the narration`
- `WebVTT for the audio`
- `podcast my blog`

### The voice ask

- `which voice`
- `list the voices`
- `pick a voice`
- `this voice is flat`
- `change the voice`
- `a French voice`
- `clone this voice`
- `sound like this recording`
- `voice sample`
- `make it sound like me`

### The latency ask

- `low-latency speech`
- `streaming speech`
- `start talking before it finishes`
- `time to first audio`
- `real-time voice`

### The names

- `speaker-helper`
- `speaker-helper-mcp`
- `import speaker_helper`
- `Speaker(...)`
- `kokoro`
- `openvoice`
- `chatterbox`

## Negative triggers — do **not** fire on these

- `transcribe this` / `speech to text` / `what did they say`
- `subtitles for this video` / `caption this recording`
- `who spoke when` / `how many speakers` / `label the speakers`
- `convert this mp3 to wav` / `cut this audio` / `normalise the volume`
- `download this video`
