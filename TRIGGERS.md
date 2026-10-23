# TRIGGERS: speaker-helper

This is the user-facing, exhaustive catalogue of what `speaker-helper` can do
and the natural-language phrasings, commands, functions, and file types that
should invoke it.

`speaker-helper` turns **text into speech**, inside your process. It is the
inverse of `vocal-helper`: text in, audio out. It runs locally by default
(Kokoro, no server), clones a voice from a reference sample (OpenVoice,
Chatterbox), and can narrate a whole document while emitting the **timed track**
that lets a page follow along word by word.

It does **not** transcribe, diarize, translate, or hold a conversation.
Those are `vocal-helper` (speech → text), `md2star` (documents), and
`discussion-helper` (the spoken loop over both).

## The ten operations → how to invoke

| Intent | CLI | Library | API |
|--------|-----|---------|-----|
| Say a sentence to a WAV | `speaker-helper synth "…"` | `create_engine().synthesize(...)` | `POST /synth` |
| Stream a reply as it is written | `speaker-helper synth --stream` | `chunk_for_streaming(...)` | `POST /synth/stream` |
| Narrate a document + timed track | `speaker-helper narrate doc.md` | `NarrationResult`, `cues_to_vtt` | `POST /narrate` |
| Clone a voice from a sample | `speaker-helper clone ref.wav` | `VoiceSample`, `register_backend` | `POST /clone` |
| List the voices an engine offers | `speaker-helper voices` | `voices_for(...)`, `PRESET_VOICES` | `GET /voices` |
| Pick the engine + mode for a situation | `speaker-helper route` | `route(...)`, `RouteRequest` | `POST /route` |
| Check the backend can actually run | `speaker-helper health` | `available_backends()` | `GET /health` |
| Fetch the weights an engine needs | `speaker-helper install-voice` | — | — |
| Re-voice audio from a source | `speaker-helper speak-from URL` | — | — |
| Score the engine against a dataset | `speaker-helper eval` | — | — |

## Phrasings that should invoke `speaker-helper`

**Speaking and reading aloud**
- "read this out loud", "say this", "speak this sentence"
- "text to speech", "TTS", "synthesise speech", "generate a voice-over"
- "narrate this document", "read my article aloud", "turn this post into audio"
- "make an audiobook from this markdown", "voice this script"
- "lis ça à voix haute", "synthèse vocale", "fais-en une voix off"

**Following along / captions from speech you generate**
- "highlight each word as it is spoken", "karaoke timing", "read-along track"
- "give me a WebVTT for the narration", "timed cues for the audio I just made"
- "sous-titres synchronisés avec la narration"

**Voice identity**
- "clone this voice", "use my own voice", "make it sound like this sample"
- "which voices are available?", "list the presets", "pick a French voice"
- "cloner une voix à partir d'un échantillon"

**Engine and placement decisions**
- "which TTS engine should I use on this machine?", "local or cloud?"
- "is a GPU needed for this?", "what runs offline?"
- "quel moteur de synthèse pour cette machine ?"

**Operational**
- "is TTS working here?", "why is there no audio?", "download the voice weights"
- "re-voice this YouTube video / podcast episode in another voice"

## File types and artifacts

| Input | Meaning |
|-------|---------|
| plain text, `.md`, `.txt` | what to say — `narrate` reflows prose and respects headings |
| `.wav` reference clip | the voice to clone |
| a dataset directory | the corpus `eval` scores against |

| Output | Meaning |
|--------|---------|
| `.wav` | the synthesised speech |
| `.vtt` | the timed track, so a page can follow the audio |
| JSON (`Timeline`, `SpeechCue`) | the same timing, for a caller that renders its own |

## Do NOT invoke `speaker-helper` for

| Ask | Use instead |
|-----|-------------|
| "transcribe this audio", "who said what" | `vocal-helper` |
| "hold a spoken conversation with me" | `discussion-helper` |
| "convert this markdown to DOCX/PPTX/PDF" | `md2star` |
| "cut, convert or concatenate audio files" | `audio-helper` |
| "download this video or podcast" | `youtube-helper`, `podcast-helper` |
| "pick a local LLM/VLM for this machine" | `best-engine-ai-helper` |

The boundary is direction of travel: **text → speech is here**, speech → text
is `vocal-helper`, and the loop over both is `discussion-helper`.

## Notes that save a support round-trip

- **Length is latency on a non-streaming client.** `POST /synth` returns when
  the whole utterance exists; `POST /synth/stream` and `chunk_for_streaming`
  exist so a long answer starts playing while the rest is still being made.
- **The backend has to be installed before it can speak.** `health` answers
  whether it can, and `install-voice` fetches the weights. A missing backend
  is reported, not guessed around.
- **Spoken maths is a real step**, not a formatting detail: `speak_math` and
  `resolve_spoken_math` turn `x^2` into words a listener can follow.
- **Nothing is uploaded** by the default path: Kokoro runs in-process, with no
  server and no network.
