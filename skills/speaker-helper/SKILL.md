---
name: speaker-helper
description: >-
  Turn text into speech, locally and in-process — one sentence, a streamed
  reply, or a whole document read aloud with a WebVTT track saying where each
  block is spoken so a page can follow along. Kokoro by default (82M through
  ONNX, Apache-2.0 code *and* weights, 54 voices, no server to start, faster
  than real time on CPU); OpenVoice and Chatterbox clone a voice from a short
  recording. Picks the voice from the language the text is actually written
  in, speaks LaTeX as words rather than spelling it out, and reports the dials
  a backend does not have instead of pretending. Use when the user says "read
  this aloud", "text to speech", "TTS", "narrate this post / article /
  document", "make a voiceover", "say this out loud", "which voice", "clone
  this voice", "sound like this recording", "audiobook", "low-latency speech",
  or names `speaker-helper`, `speaker-helper-mcp`, `import speaker_helper`. Do
  NOT use for speech → text, captions of a recording, or "who spoke when" —
  that is the inverse toolbox, `vocal-helper`. The exhaustive trigger
  catalogue is in `references/triggers.md`.
license: BSD-3-Clause
metadata:
  author: Warith HARCHAOUI
  package: speaker-helper
  suite: ai-helpers
  homepage: https://deraison.ai/ai-helpers
---

# speaker-helper — the voice, running in your process

`speaker-helper` is the inverse of `vocal-helper`: text in, speech out. It
answers three different questions, and knowing which one is being asked is
most of using it well.

| The question | The call | What comes back |
|---|---|---|
| "What does this sentence sound like?" | `synth` / `Speaker.say` | one WAV |
| "Start talking before I finish writing" | `synth --stream` / `Speaker.stream` | chunks, first one small |
| "Read me this document, and let the page follow" | `narrate` / `Speaker.narrate` | one WAV **and** its cues |

The third is the one a plain text-to-speech call cannot give you, and the one
most people actually want for an article.

## Before anything: is it installed?

```bash
speaker-helper health          # exits non-zero and says what is missing
speaker-helper install-voice --engine kokoro    # ~340 MB, once
```

Two separate failures, and the message says which: the package being
importable tells you nothing about whether the weights were ever fetched.
`health` asks both without loading the model.

On Linux and macOS you also need `espeak-ng` (`apt install espeak-ng`,
`brew install espeak-ng`). The wheel carries a copy, but it was built on a CI
runner and looks for its data in that machine's home directory; when it fails
it does so from C, with `exit(1)` and no traceback.

## Reading a sentence

```bash
speaker-helper synth "Bonjour tout le monde." -o hello.wav
speaker-helper synth --stream "A longer reply, read as it arrives."
speaker-helper voices            # what this engine can read with
```

Leave the voice unset and the language of the text picks it. That is not a
convenience: the detected language is what the phonemiser works from, so
French read as English is not French in an American accent — it is an
American spelling the words out.

## Reading a document

```bash
speaker-helper narrate post.json -o post.wav --read-math fr
# writes post.wav and post.vtt
```

`post.json` is a list of blocks:

```json
[
  {"text": "Premier paragraphe.", "pause_after_ms": 300},
  {"text": "Une formule \\(E = mc^2\\) ici.", "pace": "slow"},
  {"text": "Conclusion.", "pause_before_ms": 500}
]
```

Three things to understand about this shape, because each exists for a reason
that bit somebody:

- **`say` is not `text`.** `text` is what the page shows and what the cue
  carries; `say` is what the engine is handed. `--read-math` fills `say` for
  you from the notation. The cue keeps the page's words, which is what lets a
  read-along highlight the right ones.
- **A block that is only punctuation still takes its turn.** A French page
  closing a quotation on its own line gives a block that is a single `»`. It
  becomes a short silence rather than being dropped, because the page still
  shows it and dropping it would shift every later highlight by one.
- **The cues are free.** The offsets were already computed to lay the audio
  out. A narration without them can be played; only one with them can be
  followed.

## Cloning a voice

```bash
speaker-helper --backend chatterbox --voice-sample ref.wav \
  synth "This should sound like the reference."
```

Kokoro refuses a voice sample rather than ignoring it, and names these two.
Six to sixty seconds of clean speech is plenty — the reference supplies
timbre, it does not teach the model to talk.

## The other surfaces

```bash
speaker-helper serve --bind-host 0.0.0.0 --bind-port 8080   # REST + the GUI at /
speaker-helper-mcp                                 # the same routes as agent tools
docker compose up -d                               # the whole thing, engine included
```

`POST /narrate` returns the audio base64-encoded *with* its cues, because the
cues are the reason that route exists; a caller who only wants sound has
`/synth`.

## Reading further

- `references/surfaces.md` — library, both CLIs, REST, MCP, the container
- `references/triggers.md` — when this skill is the answer, and when it is not
