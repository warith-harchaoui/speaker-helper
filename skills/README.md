# speaker-helper as an agent skill

`skills/speaker-helper/` packages `speaker-helper` as a **Claude Skill** *and*
an **OpenCode skill** — both ecosystems read the same `SKILL.md` (YAML
frontmatter + Markdown body + progressive-disclosure `references/`).
Installing it lets an agent discover speaker-helper and read text aloud,
narrate a document, or clone a voice on the user's behalf, without the user
opening a terminal.

One skill, not three. An earlier arrangement shipped `synthesize`,
`clone-voice` and `choose-engine` as separate skills; the rest of the AI
Helpers suite packages one skill per package, and three entries competing for
the same prompts made the choice harder rather than finer.

## Layout

```
skills/speaker-helper/
├── SKILL.md                  # name + trigger-rich description + instructions
└── references/
    ├── surfaces.md           # library, two CLIs, REST, MCP, and the container
    └── triggers.md           # when this is the answer, and when it is not
```

## Installing

```bash
# Claude Code / claude.ai
cp -r skills/speaker-helper ~/.claude/skills/

# OpenCode
cp -r skills/speaker-helper ~/.config/opencode/skills/
```

The skill drives the installed commands, so the package has to be installed
too:

```bash
pip install 'speaker-helper[all]'
speaker-helper install-voice --engine kokoro
```
