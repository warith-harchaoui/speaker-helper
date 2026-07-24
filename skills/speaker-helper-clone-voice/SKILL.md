---
name: speaker-helper-clone-voice
description: Clones a voice from a short reference recording with the local speaker-helper toolbox, then synthesizes new text in that cloned voice. Use it when the user wants a custom voice built from an audio sample, wants generated speech to sound like a specific person or reference clip, or wants to re-voice/dub audio in a cloned voice. Trigger phrases include "clone a voice", "voice cloning", "clone my voice", "make it sound like this speaker/recording", "custom voice from a sample", "use my voice for TTS", "revoice this in a cloned voice", "copy this person's voice", "voice from a reference WAV". Also covers speech-to-speech re-voicing where a source (YouTube, podcast, microphone) is re-synthesized in a cloned voice. NEGATIVE triggers (do NOT use this skill): speaker diarization ("who spoke when"), speaker identification/recognition ("who is this speaker"), or plain transcription — those are the vocal-helper toolbox, not speaker-helper.
---

# Clone a Voice with speaker-helper

Register a cloned voice from a reference recording, then synthesize any text in that voice. Optionally re-voice existing audio (YouTube / podcast / microphone) into the cloned voice.

This is voice *cloning* (making TTS sound like a reference speaker). It is NOT diarization ("who spoke when") or speaker identification ("who is this") — those live in the `vocal-helper` toolbox.

## Instructions

1. Gather the inputs:
   - A **reference audio** file of the target speaker (a clean WAV of a few seconds of speech works best): `--clone-audio ref.wav`.
   - Optionally the **transcript** of that reference clip: `--clone-text "exact words spoken in ref.wav"`. Some engines clone better with the transcript.
   - Optionally a friendly **name** for the clone: `--clone-name "alice"`.

2. Register the cloned voice and get its id:
   ```bash
   speaker-helper clone --clone-audio ref.wav --clone-name alice --clone-text "Hello, this is a short reference."
   ```
   Expected: the command registers the clone and prints a voice id. Keep that id — you pass it back to `synth` as `--voice`.

3. Synthesize new text in the cloned voice, passing the id from step 2:
   ```bash
   speaker-helper synth "This new sentence is spoken in the cloned voice." -o cloned.wav --voice <CLONE_VOICE_ID> --language en
   ```
   Add `--stream` for low-latency streaming if the user wants it, and set `--language` to match the text.

4. Speech-to-speech / re-voicing — take an existing source and re-render it in a voice. `speak-from` pulls audio from a source and re-voices it:
   ```bash
   speaker-helper speak-from --source youtube --url "https://youtu.be/..." -o revoiced.wav
   speaker-helper speak-from --source podcast --url "https://.../episode.mp3" -o revoiced.wav
   speaker-helper speak-from --source mic -o revoiced.wav
   ```
   To re-voice into a *cloned* voice, clone it first (steps 2) and combine with the cloned voice as the active voice.

5. Python library path (code, not shell):
   ```python
   from speaker_helper import Speaker, Settings

   spk = Speaker(Settings.from_mapping({"engine": "kokoro", "language": "en"}))
   # clone_voice(...) is async and returns the registered voice id/handle
   # voice_id = await spk.clone_voice(clone_audio="ref.wav", clone_name="alice", clone_text="...")
   spk.save("Now speaking in the cloned voice.", "cloned.wav")
   ```
   `Speaker.clone_voice(...)` registers the reference; `save(...)` / `stream(...)` then synthesize using the active/cloned voice.

6. Report back: the clone's name and voice id, the reference used, and the path of any synthesized WAV.

Quality notes to relay to the user: use a clean, single-speaker reference with minimal background noise; a few seconds of clear speech is usually enough; providing the transcript (`--clone-text`) can improve fidelity. Cloning quality depends on the engine — mention that engine choice matters and the `speaker-helper-choose-engine` skill can pick one.

## Examples

**Scenario 1 — "Clone my voice from this recording and have it say a new line."**
- Actions: `speaker-helper clone --clone-audio my_voice.wav --clone-name me --clone-text "<what I said in my_voice.wav>"` to get a voice id, then `speaker-helper synth "Here is a brand new sentence." -o me_new.wav --voice <id> --language en`.
- Result: report the clone id and the written `me_new.wav`, spoken in the cloned voice.

**Scenario 2 — "Re-voice this YouTube clip so it sounds like a reference speaker."**
- Actions: clone the reference (`speaker-helper clone --clone-audio ref.wav --clone-name host`), then `speaker-helper speak-from --source youtube --url "<url>" -o revoiced.wav` with that clone as the active voice.
- Result: `revoiced.wav` carries the source content re-spoken in the cloned voice; report the path and the clone used.

## Troubleshooting

- **Error:** clone command runs but synthesized voice sounds generic / not like the reference.
  **Cause:** noisy, multi-speaker, or too-short reference audio, or a missing transcript.
  **Solution:** supply a clean single-speaker WAV of a few seconds and pass `--clone-text` with the exact spoken words. Try a different `--engine` (see `speaker-helper-choose-engine`).

- **Error:** `--voice <id>` not recognized during `synth`.
  **Cause:** the id from `clone` was not carried over, or a different engine is now selected.
  **Solution:** re-run `clone` to reprint the id and use the same `--engine` for both clone and synth. Voice ids are engine-specific.

- **Error:** `speak-from --source youtube/podcast` fails to fetch.
  **Cause:** the URL is unreachable, or the network/download dependency is missing.
  **Solution:** verify the `--url`, check connectivity, and confirm the download backend is installed. For a local file, try `--source mic` or synthesize from a transcript instead.

- **Confusion:** request is really "who is speaking" / "label the speakers".
  **Cause:** that is diarization / speaker identification, not voice cloning.
  **Solution:** do NOT use this skill; direct the user to the `vocal-helper` toolbox.

## Triggering tests

Should trigger: "clone this speaker's voice", "make TTS sound like this WAV", "use my voice for narration", "custom voice from a 5-second sample", "re-voice this podcast in a cloned voice".

Should NOT trigger: "who spoke when in this recording" (diarization), "identify/recognize this speaker", "transcribe this audio". Those are vocal-helper tasks, not this skill.
