# TRIGGERS: speaker-helper

This is the exhaustive catalogue of what `speaker-helper` can do and the
natural-language phrasings, commands, functions, and file types that should
invoke it. It exists twice, identical: `TRIGGERS.md` at the repo root for
users and `skills/speaker-helper/references/triggers.md` for agents. The
`description:` in the skill's `SKILL.md` is what a host model actually sees
and is capped at 1024 characters; this file carries the full list.

`speaker-helper` turns **text into speech**, inside your process. It is the
inverse of `vocal-helper`: text in, audio out. It runs locally, with no
server, and picks its engine from the **mode** (`backend: auto`, the default):
offline → Chatterbox (Turbo for English, Multilingual for every other
language), streaming → Kokoro. Other engines are one `--backend` away: Kyutai
(native French), Audio8 (realism-tuned cloner, Apple Silicon), Qwen3-TTS (the
closest clone, Apple Silicon), OpenVoice, and ElevenLabs for the paid cloud
cells (named explicitly, never by default). It clones a voice from a reference
sample, speaks with a **female voice** in every language unless told
otherwise, applies the **pronunciation lexicon** on every call, and can
narrate a whole document while emitting the **timed track** that lets a page
follow along block by block.

It does **not** transcribe, diarize, translate, or hold a conversation.
Those are `vocal-helper` (speech → text), `md2star` (documents), and
`discussion-helper` (the spoken loop over both).

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

## The operations → how to invoke

Global options (`--backend`, `--engine`, `--voice`, `--language`,
`--voice-sample`, the `--clone` family) belong to the group, so they come
before the sub-command.

| Intent | CLI | Library | API |
|--------|-----|---------|-----|
| Say a sentence to a WAV | `speaker-helper synth "…" -o out.wav` | `Speaker.say(...)`, `create_engine().synthesize(...)` | `POST /synth` |
| Stream a reply as it is written | `speaker-helper synth --stream "…"` | `Speaker.stream(...)`, `chunk_for_streaming(...)` | `POST /synth/stream` |
| Narrate a document + timed track | `speaker-helper narrate segments.json -o post.wav` | `Speaker.narrate(...)`, `NarrationResult`, `cues_to_vtt` | `POST /narrate` |
| Clone a voice from a sample | `speaker-helper --clone-audio ref.wav clone` | `Speaker.clone_voice()`, `VoiceSample` | `POST /clone` |
| List the voices an engine offers | `speaker-helper voices` | `voices_for(...)`, `PRESET_VOICES` | `GET /voices` |
| Pick the engine + mode for a situation | `speaker-helper route --condition offline` | `route(...)`, `RouteRequest` | `POST /route` |
| Check the backend can actually run | `speaker-helper health` | `available_backends()` | `GET /health` |
| Fetch the weights an engine needs | `speaker-helper install-voice --engine kokoro` | — | — |
| Re-voice audio from a source | `speaker-helper speak-from --source youtube --url URL` | — | — |
| Score the engine against a dataset | `speaker-helper eval --dataset cases.jsonl` | — | — |
| Serve the HTTP API | `speaker-helper serve` | — | — |
| Serve the MCP tools | `speaker-helper-mcp` | — | `/mcp` |

## Phrasings that should invoke `speaker-helper`

**Speaking and reading aloud**
- "read this out loud", "read this aloud", "read it to me", "say this",
  "say this out loud", "speak this sentence", "speak this text"
- "text to speech", "TTS", "synthesise speech", "synthesize speech",
  "generate audio from text", "make a WAV from this text"
- "generate a voice-over", "voiceover", "voice this script"
- "narrate this", "narrate this document", "narrate this post", "narrate this
  article", "read my article aloud", "turn this post into audio"
- "make an audiobook from this markdown", "audiobook", "podcast my blog"
- "lis ça à voix haute", "synthèse vocale", "fais-en une voix off"

**Following along / a timed track for speech you generate**
- "highlight each word as it is spoken", "highlight the sentence being read",
  "karaoke timing", "read-along", "read-along track", "follow the text while
  it plays"
- "give me a WebVTT for the narration", "WebVTT for the audio", "timed track
  for the narration", "timed cues for the audio I just made"
- "sous-titres synchronisés avec la narration"

**Voice identity**
- "clone this voice", "use my own voice", "make it sound like me", "make it
  sound like this sample", "sound like this recording", "voice sample"
- "a female voice", "une voix féminine et vivante", "a female voice that
  sounds alive"
- "which voice", "which voices are available?", "list the voices", "list the
  presets", "pick a voice", "pick a French voice", "a French voice", "change
  the voice", "this voice is flat"
- "cloner une voix à partir d'un échantillon"

**Engine and placement decisions**
- "which TTS engine should I use on this machine?", "which engine for
  French", "local or cloud?"
- "offline or streaming?", "offline TTS", "the most lifelike local voice", "a
  voice that sounds alive"
- "use ElevenLabs", "cloud TTS", "paid voice for production"
- "is a GPU needed for this?", "what runs offline?"
- "quel moteur de synthèse pour cette machine ?"

**Latency**
- "low-latency speech", "streaming speech", "real-time voice"
- "start talking before it finishes", "time to first audio"

**Pronunciation**
- "pronunciation lexicon", "pronounce this name correctly"
- "read the dates and amounts correctly", "numbers read wrong"

**Operational**
- "is TTS working here?", "why is there no audio?", "download the voice weights"
- "re-voice this YouTube video / podcast episode / microphone take in another
  voice"

**The names**
- `speaker-helper`, `speaker-helper-mcp`, `import speaker_helper`,
  `Speaker(...)`
- the engines: `chatterbox`, `kokoro`, `kyutai`, `audio8` /
  `Audio8-TTS-Realistic`, `qwen3tts` / `Qwen3-TTS`, `openvoice`,
  `elevenlabs` / `ElevenLabs`

## File types and artifacts

| Input | Meaning |
|-------|---------|
| plain text, as an argument or on stdin | what `synth` says |
| a JSON list of blocks (`text`, optionally `say`, `pause_before_ms`, `pause_after_ms`, `pace`, `emotion`), or of plain strings | what `narrate` reads, one block at a time; the page that holds the document does the splitting |
| `.wav` reference clip (+ `<stem>.txt` transcript) | the voice to clone (`--clone-audio`, `--clone-text`, `--voice-sample`) — Audio8 needs the transcript, vocal-helper derives it when missing |
| `lexicon.yaml` | how to pronounce names, acronyms, jargon — applied on every call (`./lexicon.yaml`, or `SPEAKER_HELPER_LEXICON`) |
| a JSONL dataset | the cases `eval` scores against |

| Output | Meaning |
|--------|---------|
| `.wav` (or `.mp3` / `.m4a`, by the `-o` extension) | the synthesised speech |
| `.vtt` | the timed track, written beside the `narrate` audio, so a page can follow it |
| JSON (`Timeline`, `SpeechCue`) | the same timing, for a caller that renders its own (`POST /narrate`) |

## Do NOT invoke `speaker-helper` for

| The ask, or the thing in front of you | Use instead |
|-----|-------------|
| "transcribe this", "speech to text", "what did they say" — a recording somebody needs as text | `vocal-helper` |
| "who spoke when", "how many speakers", "label the speakers", diarization | `vocal-helper` |
| "subtitles for this video", "caption this recording" — captions **of a recording** | `vocal-helper` |
| "hold a spoken conversation with me" | `discussion-helper` |
| "convert this markdown to DOCX/PPTX/PDF" | `md2star` |
| "convert this mp3 to wav", "cut this audio", "normalise the volume", "concatenate audio files" | `audio-helper` |
| a live microphone or camera as a stream of frames | `capture-helper` |
| "download this video or podcast" | `youtube-helper`, `podcast-helper` |
| "pick a local LLM/VLM for this machine" | `best-engine-ai-helper` |

The boundary is direction of travel: **text → speech is here**, speech → text
is `vocal-helper`, and the loop over both is `discussion-helper`. The dividing
line that catches most mistakes: **captions of a recording** are
`vocal-helper`'s job; **a timed track for speech this package just
synthesised** is this one's, because only the synthesiser knows where each
block landed.

## Notes that save a support round-trip

- **Length is latency on a non-streaming client.** `POST /synth` returns when
  the whole utterance exists; `POST /synth/stream` and `chunk_for_streaming`
  exist so a long answer starts playing while the rest is still being made.
- **The backend has to be installed before it can speak.** `health` answers
  whether it can, and `install-voice` fetches the weights. A missing backend
  is reported, not guessed around.
- **Spoken maths is a real step**, not a formatting detail: `speak_math` and
  `resolve_spoken_math` (`narrate --read-math LANG`) turn `x^2` into words a
  listener can follow.
- **The default engine depends on the mode.** `backend: auto` resolves offline
  to Chatterbox and streaming to Kokoro; `speaker-helper route --condition
  offline` (or `online_realtime`) prints the decision with its numbers. A backend named explicitly is honoured as-is.
- **A streaming request is the streaming cell**, whatever `mode` the settings
  name: `synth --stream` and `POST /synth/stream` use kokoro under `auto`.
- **Offline is judged on quality, not speed.** RTF only matters when
  streaming; Chatterbox and Audio8 are slower than real time and that is fine
  for a file.
- **Digits are said as words** (French, English) before any engine reads them:
  `le 14/11 à 9h30, 3 200 €` reaches the engine as "le quatorze novembre à
  neuf heures trente, trois mille deux cents euros". Cues keep the digits;
  `numbers_to_words: false` turns it off.
- **A missing `lexicon.yaml` is not an error**: the lexicon is on by default
  and simply inert when there is no file.
- **Nothing is uploaded** unless you name `--backend elevenlabs`: every other
  engine runs on this machine, and only the first use downloads weights.
  ElevenLabs needs `ELEVENLABS_API_KEY`; `health` says so without spending a
  request.
