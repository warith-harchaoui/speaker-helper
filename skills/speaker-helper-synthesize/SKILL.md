---
name: speaker-helper-synthesize
description: Turns written text into spoken audio (a WAV file) with the local speaker-helper text-to-speech toolbox, in offline mode (whole text at once) or streaming mode (sentence chunks, low time-to-first-audio). Use it when the user wants to convert text to speech, synthesize speech, narrate or read text aloud, generate a voice recording or WAV/audio file from a string, produce an audiobook/voiceover clip, or get low-latency streaming speech. Trigger phrases include "text to speech", "TTS", "synthesize speech", "read this aloud", "narrate this", "speak this text", "say this out loud", "generate a WAV from text", "make an audio/mp3 of this", "voiceover", "streaming speech", "low-latency audio", "list voices for an engine". Also handles picking a preset voice, choosing a language (fr/en/es), and choosing an engine (e.g. kokoro). NEGATIVE triggers (do NOT use this skill): transcribing audio, speech-to-text, subtitles/captions, or "what did they say" — that is the inverse vocal-helper toolbox, not speaker-helper.
---

# Synthesize Speech with speaker-helper

Convert text into a spoken WAV file using the local `speaker-helper` toolbox. Two modes: **offline** (synthesize the whole text at once — simplest, best for files) and **streaming** (synthesize sentence by sentence for low time-to-first-audio — best for interactive/real-time playback).

This skill is for text -> speech only. If the user wants speech -> text (transcription/captions), stop and route them to the `vocal-helper` toolbox instead.

## Instructions

1. Confirm the toolbox is installed and reachable:
   ```bash
   speaker-helper --help
   ```
   If the command is not found, see Troubleshooting.

2. Pick the mode from the user's need:
   - Default / "just make a WAV of this file/paragraph" -> **offline**.
   - "as fast as possible to first sound", "real-time", "low latency", "streaming" -> add `--stream`.
   If they only say "which engine is fastest/best", use the `speaker-helper-choose-engine` skill first, then come back here.

3. Synthesize to a WAV file (offline):
   ```bash
   speaker-helper synth "Bonjour, ceci est un test." -o out.wav --language fr
   ```
   Expected: an `out.wav` file is written and the command prints the output path (and typically duration / real-time factor).

4. Streaming synthesis (low time-to-first-audio) — same command plus `--stream`:
   ```bash
   speaker-helper synth "This is a long paragraph split into sentences." -o out.wav --stream --language en
   ```
   Streaming chunks text by sentence so the first audio is produced early; the final `out.wav` still contains the full utterance.

5. For long text, pipe it in on stdin instead of quoting it as an argument:
   ```bash
   cat article.txt | speaker-helper synth -o article.wav --language en
   ```

6. Choose an engine and/or a preset voice when the user asks for a specific one:
   ```bash
   # See which preset voices an engine offers
   speaker-helper voices --engine kokoro

   # Then synthesize with a specific engine + voice + language
   speaker-helper synth "Hola, esto es una prueba." -o out.wav --engine kokoro --language es --voice VOICE_ID
   ```
   Use the exact `--voice` id printed by `voices`. Do not invent voice ids.

7. Python library path (when the caller wants code, not a shell command):
   ```python
   from speaker_helper import Speaker, Settings

   spk = Speaker(Settings.from_mapping({"engine": "kokoro", "language": "fr"}))
   spk.save("Bonjour.", "out.wav")            # offline: writes out.wav
   ```
   For streaming in code, use `Speaker.stream(...)` (async) which yields audio chunks as they are produced. `save(...)` is the simple offline call.

8. Report back the output path, the mode used, the engine/voice/language, and (if printed) the duration or real-time factor.

Note on formats: the toolbox synthesizes **WAV**. If the user explicitly asks for MP3, produce the WAV first and mention that a separate transcode step (e.g. `ffmpeg -i out.wav out.mp3`) is needed — speaker-helper's native output is WAV.

## Examples

**Scenario 1 — "Read this sentence aloud and save it as a French audio file."**
- Actions: run `speaker-helper synth "Bonjour, comment ça va ?" -o bonjour.wav --language fr`.
- Result: `bonjour.wav` is written; report the path and that it used offline mode in French.

**Scenario 2 — "I need low-latency streaming TTS for a long English paragraph, first sound ASAP."**
- Actions: put the paragraph in `para.txt`, then `cat para.txt | speaker-helper synth -o para.wav --stream --language en`.
- Result: streaming mode produces the first sentence's audio quickly; `para.wav` holds the full narration. Report the path, that streaming (`--stream`) was used, and why (low time-to-first-audio).

**Scenario 3 — "Which voices does kokoro have, and make one say hello in Spanish?"**
- Actions: `speaker-helper voices --engine kokoro` to list ids, then `speaker-helper synth "Hola." -o hola.wav --engine kokoro --language es --voice <id from the list>`.
- Result: report the chosen voice id and the written `hola.wav`.

## Troubleshooting

- **Error:** `speaker-helper: command not found`.
  **Cause:** the toolbox is not installed or not on PATH.
  **Solution:** install the package (e.g. `pip install speaker-helper` in the project's environment) or run via `python -m speaker_helper.cli ...`. Confirm with `speaker-helper --help`.

- **Error:** `--voice` id is rejected / unknown voice.
  **Cause:** the voice id does not belong to the selected engine.
  **Solution:** run `speaker-helper voices --engine <engine>` and copy an id verbatim; voice ids are engine-specific. Do not guess ids.

- **Error / surprise:** user asked for MP3 but got a `.wav`.
  **Cause:** speaker-helper synthesizes WAV natively.
  **Solution:** synthesize the WAV, then transcode with `ffmpeg -i out.wav out.mp3`. Mention this to the user.

- **Symptom:** streaming feels no faster / underruns.
  **Cause:** the chosen engine cannot synthesize faster than real time (RTF >= 1) on this host, so streaming cannot keep up.
  **Solution:** use the `speaker-helper-choose-engine` skill to route to an engine with measured RTF < 1 for the `online_realtime` condition, or fall back to offline mode for a file.

- **Confusion:** the request is actually transcription (audio -> text), not synthesis.
  **Cause:** speaker-helper only does text -> speech.
  **Solution:** do NOT use this skill; direct the user to the `vocal-helper` (speech-to-text) toolbox.

## Triggering tests

Should trigger: "turn this text into speech", "make a WAV that reads this paragraph", "narrate this in French", "give me low-latency streaming TTS", "what voices does kokoro have", "generate audio of this sentence".

Should NOT trigger: "transcribe this recording", "what did the speaker say", "generate subtitles/captions for this video", "identify who is speaking" (diarization). Those belong to vocal-helper or the choose-engine/clone-voice skills, not here.
