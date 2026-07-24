# speaker-helper Skills

Portable **Claude / OpenCode Skills** for the [`speaker-helper`](../) local text-to-speech ("speech synthesis") toolbox — the inverse of the `vocal-helper` speech-to-text toolbox. Each skill is a self-contained folder with a `SKILL.md` file (YAML frontmatter + Markdown body) following Anthropic's official Skills standard. Because OpenCode uses the same `SKILL.md` format, these folders are portable across Claude and OpenCode with no changes.

## The three skills

| Skill folder | What it does | Use it when the user says… |
|---|---|---|
| [`speaker-helper-synthesize/`](./speaker-helper-synthesize/SKILL.md) | Text -> speech (WAV) in **offline** (whole text) or **streaming** (sentence chunks, low time-to-first-audio) mode; list preset voices; pick engine / language / voice. | "text to speech", "TTS", "narrate this", "read this aloud", "make a WAV of this", "streaming / low-latency speech", "list voices". |
| [`speaker-helper-clone-voice/`](./speaker-helper-clone-voice/SKILL.md) | Clone a voice from a reference recording, then synthesize (or re-voice YouTube / podcast / mic audio) in that cloned voice. | "clone a voice", "voice cloning", "make it sound like this speaker", "use my voice", "custom voice from a sample", "re-voice this". |
| [`speaker-helper-choose-engine/`](./speaker-helper-choose-engine/SKILL.md) | Backend **router**: pick the best engine + mode from measured quality-vs-speed evidence, for `online_realtime` (RTF<1, faster than real time, then max quality) or `offline` (quality only). | "which TTS engine should I use", "fastest TTS", "best quality TTS", "real-time / low-latency", "speed vs quality tradeoff", "route to the best backend". |

Not covered by these skills (different toolbox): transcription / speech-to-text, subtitles/captions, speaker diarization ("who spoke when"), speaker identification — those belong to `vocal-helper`.

## Installing

A skill is just its folder. Copy the folder(s) you want into one of these locations:

- **Claude — user-wide (all projects):**
  ```bash
  cp -R speaker-helper-synthesize speaker-helper-clone-voice speaker-helper-choose-engine ~/.claude/skills/
  ```
- **Claude — this project only:**
  ```bash
  mkdir -p .claude/skills
  cp -R speaker-helper-synthesize speaker-helper-clone-voice speaker-helper-choose-engine .claude/skills/
  ```
- **OpenCode:** copy the same folders into OpenCode's skills directory (e.g. `~/.config/opencode/skills/` or the project's `.opencode/skills/`). The `SKILL.md` format is identical, so no edits are needed.

After copying, restart the client (or reload skills) so the new skills are discovered. Each skill loads progressively: the frontmatter is always loaded, the `SKILL.md` body loads when the skill is relevant, and any `references/` files load on demand.

## Standard notes

- Every skill folder is **kebab-case** and contains exactly one **`SKILL.md`** (case-sensitive); there is no `README.md` inside a skill folder (this top-level README lives outside them).
- Each `SKILL.md` frontmatter has exactly two fields: `name` (matches the folder, kebab-case) and `description` (< 1024 chars, trigger-rich, with positive and negative triggers).
- Long reference material lives in a skill's `references/` subfolder (see `speaker-helper-choose-engine/references/router-details.md`) and is linked from the `SKILL.md` body.
