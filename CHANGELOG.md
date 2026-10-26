# Changelog

All notable changes to speaker-helper are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project aims to adhere
to [Semantic Versioning](https://semver.org/).

## [0.10.0] - 2026-10-26

### Added
- **A pronunciation lexicon, integrated by default** (`speaker_helper/lexicon.py`,
  `lexicon.yaml.example`). State once how a word is pronounced — IPA, a
  respelling, or nothing at all — and every synthesis honours it. Two tiers,
  because the engines come in two kinds: backends that accept phonemes
  (kokoro, which already phonemised its own input) splice the stated **IPA
  verbatim** at their existing phonemisation step, deterministically; every
  other backend gets the **respelling** tier, a text rewrite applied by
  `Speaker` before the engine sees the text. An entry with neither gets its
  respelling **derived once by the local LLM** — resolved through
  `best-engine-ai-helper` (the suite rule), served by Ollama at temperature 0,
  few-shot prompted — validated structurally, and persisted to a sidecar cache
  so everything after that first derivation is deterministic and offline.
  The feature keys on `settings.lexicon` (`path`, `enabled`, `llm`) and the
  `SPEAKER_HELPER_LEXICON` environment variable, and costs nothing when no
  lexicon file exists.
- **A `kyutai` backend** — Kyutai's `tts-1.6b-en_fr`, the 2026-10 survey's
  French pick (`STUDY.md`, `research` branch): native French from a Paris lab
  where the alternatives render French through English-first pipelines.
  Voices are precomputed embeddings from the `kyutai/tts-voices` bank (the
  speaker encoder is deliberately unreleased — the backend says so instead of
  pretending to clone); the defaults are **female**: `developpeuse-3`
  (unmute's French voice, CC0; measured median F0 240 Hz on this machine) and
  VCTK `p329` for English. Weights (~3.4 GB) download once, then it is
  offline. New `[kyutai]` extra; knobs under `settings.kyutai`.
  Two runtimes behind one knob: `device: auto` (default) selects **Kyutai's
  own MLX implementation on a Mac** — detected with `os-helper`, quantized to
  8 bits like Kyutai's on-device deployments, measured **RTF 0.84** on an
  M2 Max where the torch-CPU fallback measured 7.8 — and torch anywhere else,
  both reading the same cached weights. (The chatterbox Turbo equivalent via
  `mlx-audio` 0.6.1 was evaluated and rejected for now: its loader leaves the
  speaker encoder unweighted, so reference-based cloning — our female-voice
  guarantee — silently breaks; English stays on torch, RTF ~3 on CPU.)
- **Long-text chunking, LLM-assisted** (`speaker_helper/chunking.py`). A long
  `say()` is no longer one engine call — past their comfort zone the neural
  engines audibly degrade — but sentence-group chunks concatenated with a
  breath between them. The local LLM only *places the boundaries* (it groups
  locally-split sentences and its answer must be positive integers summing to
  the sentence count), so the spoken text is structurally guaranteed to be
  the caller's text; any failure falls back to a deterministic greedy packer.
  Knobs under `settings.chunking` (`enabled`, `llm`, `max_chars`).
- **Language-aware quality priors** (`eval/priors.py`): `engine_quality_prior`
  takes an optional language, and a per-language table refines the base —
  kyutai is floored at 0.30 outside fr/en (it would read Spanish with a
  French/English tongue); chatterbox keeps 0.90 in English and drops to 0.78
  in French (6–8% CER, per the survey). Priors are flagged
  `confidence="low"` and only speak where nothing was measured.
- **An A/B bench ran — and its criterion was rejected** (`STUDY.md` §8 bis
  tells the full story). The ~/speak study measured UTMOSv2 naturalness,
  WER/chrF round-trips and RTF for every (engine, language) pair
  (2026-10-26, 10 sentences per language, real operating points on the
  reference M2 Max); UTMOSv2 ranked kokoro first in both languages, the
  numbers were briefly folded into routing, and the project owner then
  **récused the metric as the offline criterion**: it predicts a generic
  anonymous-panel "naturalness" (English-trained), not "réaliste et vivante"
  to a human ear. The offline defaults therefore remain the survey's
  editorial pair — **French → kyutai, English → chatterbox (Turbo)** —
  honestly flagged `quality_source="prior"`, low confidence, until a human
  pairwise-listening protocol produces `measured_human` scores. What the
  bench durably contributed: the automatic **guardrails** (WER floor, anomaly
  gate, female-F0 check), the recorded numbers (`speak/out/ab_voices.json`,
  listening pack in `speak/out/ab_samples/`), and kyutai's better French
  default voice — **CML-TTS 10087 enhanced** replaced `developpeuse-3` after
  a six-voice screening (supported by the ASR round-trip too: French WER
  0.068 → 0.039, tying kokoro).

### Changed
- **The chatterbox backend knows its three variants.** `chatterbox-tts` 0.1.7
  ships base, **Turbo** (the survey's English pick) and **Multilingual**
  (23 languages); `settings.chatterbox["variant"]` pins one, and the default
  `"auto"` serves English with Turbo and everything else with Multilingual —
  per call, so a narration can mix languages. Without a configured reference
  it now clones the bundled female voice (`assets/ref-fr-female.wav`) instead
  of trusting the model's default speaker: the project's contract is **a
  female voice in every language**, and no model card promises that.
- **The router's catalogue names real backends.** Engines used to enter the
  catalogue with the dataclass default `backend="kokoro"` — an offline
  decision for chatterbox would have produced Settings no `create_engine`
  could honour. A `ENGINE_BACKENDS` table maps engine → serving backend, and
  engines with no in-tree backend (qwen3_tts, f5, xtts) keep their priors for
  the eval layer but no longer enter routing decisions.

## [0.9.3] - 2026-10-25

### Changed
- **The MCP launcher was the last argparse parser in the package.** The command
  line moved to click in 0.8.0 and `speaker_helper/mcp.py` did not, so one
  wheel shipped two parsing libraries, two help layouts and two answers to
  `-h`: `speaker-helper -h` printed help, `speaker-helper-mcp -h` answered
  `unrecognized arguments`. It is click now, with
  `help_option_names = ["-h", "--help"]` like every other command in the
  suite.

  Nothing a reader types changed. `--host`, `--port` and `--config` keep their
  spellings and their defaults — they are in the README, the skill's
  `surfaces.md` and the Dockerfile — and `main(argv)` still **returns** an
  exit code rather than exiting, which is what `[project.scripts]` calls.
  click is driven with `standalone_mode=False` for exactly that reason: left
  to itself it exits by raising, and a console script that raises instead of
  returning its code is a different contract.

  Two improvements come with the move. The environment defaults
  (`SPEAKER_HELPER_MCP_HOST`, `SPEAKER_HELPER_MCP_PORT`) are now `envvar=`
  declarations rather than `os.environ.get` calls, so they are read per
  invocation instead of once at import, and they appear in `--help`. And a
  non-numeric `SPEAKER_HELPER_MCP_PORT` used to raise `ValueError` out of
  `int()` while the parser was still being built — before `--help` could
  print — where it now reports `Invalid value for '--port'` and exits 2.

- The README's licence badge pointed at `LICENSE`, a relative target. PyPI has
  no repository to resolve one against, so on the project page it linked to
  `pypi.org/project/speaker-helper/LICENSE` — a 404. README.md is this
  package's long description; it is absolute now. LISEZMOI.md is read on GitHub
  only, where relative targets resolve, so its own links are left alone.

### Added
- `tests/test_the_surfaces_agree.py` now covers the MCP launcher, which no
  test touched at all: that `main` returns `0` for `-h` and `--help` and `2`
  for an unknown flag rather than raising, and that a missing `[mcp]` extra
  returns `2` after naming the extra. Both proven by breaking them —
  `standalone_mode=True` turns the first red.

## [0.9.2] - 2026-10-25

### Fixed
- **`eval` measured the model load and called it slow synthesis.** `run_eval`
  did not warm the engine, so on a cold process the first case paid the ~5 s
  ONNX session build and the gate reported it as real-time factor. Measured on
  an idle M2 Max: `mean_rtf=0.5219 p95_rtf=1.7617 → FAIL` cold against
  `mean_rtf=0.2288 p95_rtf=0.2921 → PASS` warmed. A 6x error on the p95, on an
  engine that was never slow — the kind that reads as a busy laptop.

  Worse, the two entry points disagreed. `run_multilang_eval` warmed each
  language before timing and `run_eval` did not, so **the same engine passed
  under `--languages` and failed under `eval`**. A gate whose verdict depends
  on which door you came through is not a gate.

  The warm-up now lives in `run_eval`, where every caller gets it, and
  `run_multilang_eval` passes its own `warmup` flag through instead of doing it
  itself. `warmup=False` remains for callers who mean to measure cold start.

  This changes what the gate reports for every caller, deliberately: from the
  initialisation cost to the synthesis speed the thresholds were written about.

### Added
- `tests/test_eval.py::test_run_eval_warms_the_engine_before_measuring_anything`
  — asserts the warm-up happens, exactly once, **before** the first synthesis,
  and that it is opt-out. Proven by removing the warm-up and watching it go red.
  The mock cannot reproduce a 5 s model load, so the test asserts the mechanism
  rather than the timing.

### Changed
- `BENCHMARKS.md` and §5.2 of both tech reports carried the defect as current
  behaviour, with the failing numbers. They now carry both measurements and
  date the fix. Both READMEs already said the gate warms up before timing —
  which only becomes true with this release.

## [Unreleased]

## [0.9.1] - 2026-10-25

### Fixed

- **Sixty-one mentions of an engine that is not in the code.** The REST client
  for an out-of-process engine went away in 0.8.0 and the documentation did
  not. It was not stale footnotes: the two READMEs presented that engine as
  **the default** ("talks to a concrete engine (Voicebox by default)") and drew
  it as a node in their architecture diagrams; both cookbooks opened by telling
  the reader to have one running on `:17493` or `:17600`, passed
  `{"voicebox": {"port": 17600}}` into `Settings.from_mapping` and showed a
  `/health` response with a `"voicebox"` key that the endpoint has never
  returned; `TECHNICAL_STACK.md` drew a `VoiceboxClient` node with an `HTTP`
  edge; `LANDSCAPE`/`PAYSAGE` listed "a running Voicebox" as part of the
  install cost; and both example configuration files invited the reader to copy
  a dead `voicebox:` section.

  What the code actually does was established by reading it and then running
  it: `create_engine(settings)` resolves `settings.backend` against a
  module-level registry and returns one of four **in-process** backends —
  `kokoro` (default, kokoro-onnx on ONNX Runtime, 54 voices, 24 kHz),
  `openvoice`, `chatterbox`, `mock`. Nothing speaks HTTP to an engine. The only
  HTTP left is the API speaker-helper *serves*, and the only outbound request
  is `urllib.request` fetching the weights once in `install.py`. Both READMEs,
  both cookbooks, `TECHNICAL_STACK.md`, both technical reports and both
  `LANDSCAPE` twins now say that, and their Mermaid diagrams draw the backends
  inside the process box.

- **The `/health` sample was wrong in both cookbooks.** They showed
  `{"status":"ok","voicebox":{...}}`. The route returns
  `{"status","backend","engine"}` — where `engine` is the backend's own
  document — or `{"status":"degraded","backend","engine_error"}` when the
  backend cannot run. Replaced with the real payload, read off the endpoint.

- **The cloning examples selected nothing.** They passed
  `{"engine": "chatterbox", …}`, but `engine` is only a label carried on
  results; `backend` is what `create_engine` dispatches on. So
  `Settings.from_mapping({"engine": "chatterbox"})` built a `KokoroEngine`,
  and Kokoro refuses to clone. Now `{"backend": "chatterbox"}`, with the
  distinction stated where it is used.

- **`requirements.txt` pinned `httpx>=0.27`; `pyproject.toml` said in a comment
  that `httpx` was gone.** One of the two had to be wrong. Nothing in the
  package imports `httpx` — `install.py` downloads with stdlib
  `urllib.request`, and the only other appearance is `httpx2`, which
  `pyproject` already declares under `[dev]` for starlette's `TestClient`. The
  pin is removed, and `requirements.txt` now mirrors
  `[project.dependencies]` exactly.

  A test compares the two lists, because a surplus requirement installs
  cleanly and so this class of drift cannot be caught by reading. Proven by
  putting `httpx>=0.27` back and watching it go red.

- **Dead environment variables and a dead air-gapping recipe.** Both cookbooks
  told the reader to `export SPEAKER_HELPER_VOICEBOX_PORT`, which
  `_apply_env_overrides` has never read, and both READMEs' "self-hosted
  engines" section told them to point `VOICEBOX_MODELS_DIR` at a bundle with
  `HF_HUB_OFFLINE=1` — a documented override of the *removed* engine, which
  nothing in this package reads. The section now describes what actually makes
  the default engine air-gapped: its two files come from a pinned
  `kokoro-onnx` release into `~/.cache/speaker-helper/kokoro`, nothing is
  fetched during synthesis, and copying that directory is the whole procedure.

### Changed

- **`BENCHMARKS.md` was re-measured rather than relabelled.** Its figures were
  real measurements of an engine this package no longer contains, in two
  configurations (a native MLX build on the Apple GPU, and that same engine's
  CPU build in a container) that cannot be reproduced from this repository.
  Silently re-attributing them to the in-process ONNX engine would have been
  the one unacceptable option.

  So both: the gate was re-run on the same host (Apple M2 Max) against the
  current engine — `speaker-helper eval --languages fr,en,es`, warmed, zero
  anomalies — giving mean RTF **0.223** (fr), **0.237** (en), **0.206** (es),
  four to five times faster than real time on the CPU; and the old figures are
  kept in a dated, explicitly-labelled historical section that says which
  engine they describe and why neither table can be re-run. There is now one
  operating point to report instead of a comparison, which is itself the
  architectural result.

- **`profiles.py` carried the removed engine's timings.** `_MEASURED_KOKORO_MLX`
  seeded the router's operating-point catalogue with RTFs labelled "native MLX,
  M2 Max" — measured against the engine that left in 0.8.0. Renamed to
  `_MEASURED_KOKORO` and refreshed with the re-measurement above, on the same
  host. `measured_quality` is **not** touched: it comes from a separate UTMOSv2
  naturalness sweep, it was not re-run here, and it keeps its own provenance in
  the comment rather than being folded into one sweep that never happened.

- **The `@slow` benchmark was measuring the model load, and the exclusion hid
  it.** `test_run_eval_live_kokoro` asserts `mean_rtf < 1.0` against the real
  engine over three short cases, and it did not warm up — so the one-off ~5 s
  ONNX session build was billed to the first case. On an **idle** M2 Max that
  synthesises at 0.223 warm, it failed at **1.2235**: a six-fold error, which
  is why the number was read as "this machine is busy" rather than as the
  wrong measurement. It was excluded from the default run, from CI and from the
  pre-push gate, so nothing was going to correct that reading.

  One line — `await spk.warmup()` before the timed run — and it passes here.
  Proven both ways on the same machine, minutes apart. The `slow` marker's
  rationale in `pyproject.toml` records the corrected diagnosis, since the
  original one (load average 133) was true but not the whole story.

### Found, not fixed

- **A single-language `eval` still does not warm up, so the CLI can report the
  model load as a verdict.** `run_multilang_eval` warms each language before
  timing; `run_eval` has no such step. Same engine, same dataset, same
  machine: `--languages fr,en,es` gives `p95_rtf=0.261` and PASS, while
  `--engine kokoro eval` gives `p95_rtf=1.7617` and FAIL. Giving `run_eval` a
  warm-up would change what the gate measures for every caller, which is a
  decision rather than a fix, so this release only documents it — in
  `BENCHMARKS.md` §"The model load is not the engine", in §5.2 of both
  technical reports, and in both READMEs.

- **`README` still says the package is "not on PyPI yet" and pins `v0.7.5`.**
  PyPI serves `speaker-helper` up to 0.8.1. Out of scope for a pass about the
  engine, and the right fix is a release rather than an edit.

## [0.9.0] - 2026-10-25

### Changed

- **One command line, built with click.** There were two front doors over the
  same handlers — `speaker-helper` (click) and `speaker-helper-argparse` — and
  a suffix naming the parsing library describes the implementation, not the
  interface. `speaker_helper/click_cli.py` and the click half of the CLI now
  live in `speaker_helper/cli.py`, together with the `_cmd_*` handlers that
  were always shared; the argparse parser and its dispatcher are gone.

  The handlers still take a flag bag and return an exit code, so the command
  logic stays testable without a terminal. The bag is a
  `types.SimpleNamespace` rather than an `argparse.Namespace`: nothing in the
  package needs argparse any more, and a type imported only to be a dumb
  attribute holder reads as a leftover.

  Parity was checked rather than assumed, by listing both surfaces before
  deleting either: the same ten sub-commands (`synth`, `narrate`, `voices`,
  `clone`, `eval`, `speak-from`, `route`, `install-voice`, `health`, `serve`)
  and the same options, with two spelling differences recorded under
  *Migration* below. A test now pins the ten names and refuses any
  re-appearance of a suffixed CLI alias.

### Added

- **`-V` / `--version`.** The CLI could not say what it was. Capital, because
  `-v` is verbosity everywhere in this suite. The number is handed to click
  explicitly: read from the installed distribution metadata it reports
  whatever was last `pip install`ed, which is how an editable checkout comes
  to announce a stale version.

### Fixed

Each of these was found by running the command, and none of them is visible
by reading the source.

- **Every documented CLI invocation was broken.** README, LISEZMOI, EXAMPLES
  and EXEMPLES showed `speaker-helper --port 17600 synth …` on forty lines
  (eleven each in the two READMEs, nine in each cookbook). That global
  `--port` pointed at a Voicebox engine in another process and went away when
  Kokoro moved in-process at 0.8.0; the click door answers `Error: No such
  option '--port'`. So the first line a reader copied could not work, in
  either language.

- **The container's own entry point was broken.** `Dockerfile` ended with
  `CMD ["speaker-helper", "serve", "--host", …]` — the argparse spelling —
  which the installed `speaker-helper` has not accepted since it became the
  click group. `docker run` on the published image exited 2. Same line in
  `SKILL.md` and in the skill's `surfaces.md`.

- **argparse silently dropped two global options.** A sub-parser re-declaring
  an option its parent also declares parses into a fresh namespace and then
  copies *every* key back, defaults included. So `speaker-helper-argparse
  --language en route --condition offline` routed for **fr** (the sub-parser's
  default overwrote `en`), and `--engine kokoro voices` listed the configured
  engine rather than kokoro. Both only worked in the other order. The click
  group has one declaration per option, so the class of bug is gone, not
  merely fixed here.

- **Nothing ran the documentation.** The `--port` rot above survived because
  every check read the source and none ran a documented line. A test now
  extracts all seventy-seven `speaker-helper …` invocations from the shell
  fences of both READMEs, both cookbooks, `SKILL.md` and the skill's
  `surfaces.md`, and asserts the parser accepts each one (handlers stubbed, so
  no engine is involved). Proven by putting one `--port 17600` line back and
  watching it go red.

- **The group's help text rendered its own markup.** click prints a docstring
  verbatim, so ```` ``speaker-helper --backend mock synth "hi"`` ```` reached
  the terminal with the double backticks in it. A test now asserts that
  `--help` carries no reStructuredText scaffolding and no numpydoc
  `Parameters` block.

### Migration

- `speaker-helper-argparse <command>` → **`speaker-helper <command>`**. The
  console script is gone; every sub-command, option and exit code is
  unchanged.

- `serve --host H --port P` → **`serve --bind-host H --bind-port P`**. This is
  the one rename with teeth, and it is deliberately *not* aliased. `--host` /
  `--port` were once global options aiming at a **remote engine**, which is
  how a server came to call itself for `/health`; accepting those spellings on
  `serve` again would make an old command line do something different without
  saying so. click rejects the unknown option and suggests `--bind-host`, so
  the failure is loud and the fix is one word.

- `voices --engine E` → **`--engine E voices`**, and
  `route --condition C --language L` → **`--language L route --condition C`**.
  Global options are declared on the group, so they precede the sub-command —
  the rule the README always stated and its examples contradicted.

- `pip install speaker-helper` is unchanged: `click` was already a core
  dependency rather than an extra, so there is no `[cli]` extra to stop
  asking for. It is now capped `<9`.

### Found, not fixed

The `--port 17600` sweep above only touched command lines. The same dead
Voicebox engine still appears in the Python snippets
(`Settings.from_mapping({"voicebox": {"port": 17600}})`), in `BENCHMARKS.md`,
in `settings.yaml.example`, in `examples/quickstart.py` and as a stale
`httpx>=0.27` in `requirements.txt` — a documentation rot from 0.8.0 that is
wider than one command line and wants its own pass.

*Done in 0.9.1.*

## [0.8.2] - 2026-10-23

### Fixed

- **The graceful-degradation path for a missing MCP surface crashed instead of
  degrading.** `api.py` called `osh.warn(...)` — a function that has never
  existed; it is `osh.warning` — from inside the `except` branch whose entire
  purpose is to say "the MCP surface did not mount, the HTTP API is
  unaffected". So a handled, benign condition became an `AttributeError` at
  application startup, which is the opposite of what the handler was for.

  Nothing caught it because the branch carries `# pragma: no cover`: the
  pragma excused the error path from coverage, and the error path was where
  the error lived. A new test resolves **every** `osh.*` reference in the
  package against the real module at once, rather than trusting call sites one
  at a time — proven by restoring `osh.warn` and watching it fail.

- **The pre-push gate ran no tests at all**, only `ruff`, while CI runs pytest
  across four Python versions with a 70% coverage floor. This was the one
  member of the suite where test-breaking code could be pushed and only caught
  on the server — the inverse of the rule every sibling follows. The gate now
  mirrors the workflow exactly (`-m "not slow"`, `--cov-fail-under=70`), which
  costs fourteen seconds; proven by adding a lint-clean failing test and
  watching the push abort.

### Verified, not changed

`os-helper>=1.7.2` looked anomalous beside siblings pinned at 2.6.0+, but every
`os_helper` API this package uses (`download_file`, `init_logging`,
`temporary_folder`, …) existed at 1.7.2. The floor is honest and stays.

## [0.8.1] - 2026-10-20

Everything here is a consequence of 0.8.0 having been published without a
tag, a release or an entry below — the gaps that shows up as.

### Fixed

- **The 0.8.0 wheel reported itself as 0.7.6.** The bump had touched
  `pyproject.toml` and not `speaker_helper/__init__.py`, and nothing in the
  repository could say so: the two numbers only disagree once the wheel is
  built, by which point it is usually already published. The split matters —
  `--version`, the API's `/health` and whatever a user pastes into a bug
  report read the package, while pip, a neighbouring extra's floor and the
  index read the wheel. A test now holds the two together, verified against a
  deliberate sabotage.

- **`httpx2` was undeclared where the install actually looks.** starlette
  1.9.0 moved its `TestClient` onto `httpx2`; CI resolves the newest starlette
  and every development machine had an older one, so CI failed on a dependency
  no manifest named. The first attempt put it in `requirements-dev.txt`, which
  these repositories' CI never reads — it installs `pip install -e ".[dev,…]"`.
  It is a *test* dependency, so it belongs in the `dev` extra and not in `api`,
  where it would hand a test client to every user of the HTTP surface. Nine
  members of the suite use `TestClient` and none declared it; speaker-helper
  reached the failure first.

- **The `slow` marker was declared and never excluded**, so the default suite
  ran a *performance* assertion against the real engine — `mean_rtf < 1.0`,
  which measures the machine rather than the code. Under a load average of 133
  it reported an RTF of 15.86 against a threshold of 1.0: a red suite saying
  nothing about speaker-helper. Raising the threshold would hide the
  regressions the test exists to catch, so it is now opt-in (`pytest -m slow`),
  which is the call the rest of the suite had already made for its `eval`
  marker. Its description still said "requiring a running Voicebox engine";
  there is no Voicebox since 0.8.0.

- **`.githooks/` was gitignored, in this repository alone.** It sat under a
  line commented "local-only tooling & secrets" and contains no secrets. Two
  hooks existed only on one machine: the pre-push gate, whose very first
  instruction is "enable once per clone" — impossible from a clone that does
  not carry it — and the commit-msg hook that refuses assistant attribution in
  a commit message, which is a project policy rather than a machine
  preference, and applies nowhere if it does not travel.

- **The pre-push hook ran neither `ruff check` nor `ruff format --check`**,
  the only member of the suite not to. Ten files stayed unformatted until an
  unrelated push turned CI red on them. Both passes now name
  `speaker_helper tests`, which is exactly what CI reads: since 0.16 ruff also
  formats fenced code blocks inside Markdown, so a bare `.` would make the gate
  depend on whichever ruff a developer happens to have, rejecting README
  examples that CI — pinned to 0.15.21 and scoped to those two paths — never
  looks at. A local gate that blocks a push CI would accept is worse than none.

### Added

- **Real tests for what the voice says about a formula.** Dropping `slow` from
  the default run took coverage to 67.30 % against a 70 % floor, and the honest
  reading is that `speech_text` was never tested — it was *visited* by a slow,
  unrelated TTS round-trip that lent it coverage by synthesising speech for
  real. Lowering the bar would have hidden the loss; these tests close it
  (`speech_text` 40 % → 87 %, total 67 % → 74 %). They assert the distinction
  the module exists to make: a named operator reads as a sentence — "the
  expected value of theta given m" — not as a transliteration of its symbols.
  Plus the refusal that is easiest to lose: a language with no vocabulary
  raises `SpeechMismatch` rather than serving English operators, because a
  listener would hear "squared" mid-German-sentence with no way to know the
  page said something else. And that no backslash or brace ever reaches the
  voice.

### Changed

- `vocal-helper` in the `stt` extra is capped: `>=2.0.0,<4`. It was
  `>=0.4.4` with no upper bound, the only uncapped suite dependency here, so
  vocal-helper 3.0.0 — which changes two defaults — would have resolved in
  silently. Only `transcribe_pcm` is used, which 3.0.0 leaves untouched, so the
  cap is widened to admit it rather than held at `<3`.

## [0.8.0] - 2026-10-19

Published to PyPI on 2026-10-19 **without a tag, a GitHub release or this
entry**; the wheel also misreported its version (see 0.8.1). Documented
retroactively so the history is not a hole.

### Added

- **Kokoro runs in this process.** speaker-helper was a thin client of a
  separate Voicebox engine listening on a port; it is now an in-process
  engine. Nothing to start, nothing to reach, no port to agree on.

- **Narration**: a document goes in and a timed track comes out, so a page can
  follow along with the voice (`to_vtt()`, speech cues carrying the page's
  words rather than the spoken ones).

- **The five surfaces**, and a container that finally carries its engine:
  library, two CLIs, REST API and web GUI.

- **The 54-voice catalogue reads without the weights.** Listing the voices no
  longer requires downloading a model first, and the tables ship with it.

### Documentation

- `PAYSAGE.md` records why there is no `speaker-helper-rs`.

## [0.7.6] - 2026-08-01

### Changed
- **Default clone reference replaced.** The previous bundled voice was a real
  person's recording that had not consented to being distributed as a
  cloning reference. It is removed (and purged from git history). The new
  default `assets/ref-fr-female.wav` is a French female voice from the
  **CML-TTS** dataset under **CC BY 4.0** (attribution in
  `assets/ref-fr-female.NOTICE.md`). Default clone name is now `ref-fr-female`.

## [0.7.5] - 2026-08-01

### Removed
- **MCP surface dropped.** `fastapi-mcp`'s latest release (0.4.0) is
  incompatible with the latest `mcp` SDK (`Server.__init__()` signature
  mismatch) — `_mount_mcp` crashed `create_app()` in CI, breaking every API
  test (not just the MCP-specific ones), with no available version pairing to
  pin around. Removed `fastapi-mcp` from the `server` extra, `_mount_mcp` and
  the `enable_mcp` flag from `api.py`, and every doc mention. speaker-helper
  now ships **four** surfaces instead of five (library, two CLIs, REST API,
  web GUI).
- **Agent skills dropped from the public repo.** Without an MCP surface, the
  three Claude/OpenCode skills (`skills/`) no longer earn their keep as public
  distribution — moved to the gitignored `.private/skills/` (kept locally as
  reference, never published).

### Added
- **Backend router** (`speaker_helper.router`): choose an engine + mode from
  measured quality↔speed evidence for an operating **condition** —
  `online_realtime` (delay-bounded streaming; speed = real-time factor, the
  engine must run faster than real time, ceiling 0.8 for TTFA/jitter margin;
  maximise quality on the Pareto front among engines that keep up) or `offline`
  (batch; **quality is the only objective**, speed disregarded — pure quality
  argmax). Every `RouteDecision` carries provenance (`measured` vs `prior`), a
  `confidence` flag, and a number-citing `justification`. `Speaker.from_route`,
  `route`, `route_settings`, `default_operating_points`, `RouteRequest`,
  `RouteDecision`, `OperatingPoint` are public. New engines are characterised in
  the `speak` study and folded back as data.
- **Router surfaces**: CLI `speaker-helper route --condition …`, REST
  `POST /route`, and the GUI router panel.
- **Click CLI** (`speaker-helper`, primary): grouped sub-commands over the same
  handlers as the argparse CLI, which stays available as `speaker-helper-argparse`.
- **Minimal web GUI** served at `/` by the API server (`speaker-helper serve`):
  a dependency-free vanilla-JS + Tailwind page for synth (offline + SSE
  streaming), voices, clone, and the router.
- **`RoundTripIdempotenceMetric`** (DeepEval): text→speech→text intelligibility
  as chrF, formalising the round-trip idempotence view of quality.

### Fixed
- **Install was broken**: `requirements-dev.txt` referenced a `requirements.txt`
  that did not exist. Added `requirements.txt` (runtime deps mirroring pyproject).
- Type annotations completed in `cli.py` (`_build_transcriber` return,
  `_cmd_eval_multilang` `thresholds` param).

### Changed
- CI now **gates coverage** (`--cov-fail-under=70`); current fast-suite total ~74%.
- Deeper **os-helper adoption**: file-existence checks use `osh.file_exists`,
  temp directories use `osh.make_temporary_directory` + `osh.join` (replacing
  `Path.is_file` / `tempfile.mkdtemp`); logging was already fully `osh`.
- Coding-standards pass: every source module now clears the 15% in-code comment
  floor (measured excluding docstrings); `click_cli.py` documented.
- Bumped AI-Helpers dependency floors to the current improved releases:
  `os-helper>=1.7.2`, `audio-helper>=1.6.0`, `vocal-helper>=0.4.4`,
  `youtube-helper>=1.3.4`, `podcast-helper>=0.4.0`, `capture-helper>=0.3.0`.

## [0.7.4] - 2026-07-15

### Documentation
- Harmonize README/LISEZMOI to the AI Helpers common structure (single H1, Documentation block, source install pinned to v0.7.4, PyPI-coming-soon note); no code changes.

## [0.7.3] — 2026-07-14

### Documentation
- Finalize suite wording: use plain-language capability names (Speech Synthesis) in the description and README instead of tool-specific acronyms, for consistency across the suite.

## [0.7.2] — 2026-07-14

### Maintenance
- Apply the project coding standards across the package and `tests/`: Numpy-style docstrings on every function/class (including private and nested helpers), full typing, and comment density above the floor. No public API or behavior changes.
- Route library logging through the os-helper logging surface (`osh.info/warning/error`) and adopt os-helper utilities more widely; pin `os-helper>=1.5.0`.
- Refresh the project logo asset.

## [0.7.1] — 2026-07-13

### Maintenance
- Coding-standards pass: genuine in-code narration (`#` block comments) added to
  the logic-bearing modules (metrics, text, config, engine, runner, …),
  explaining the *why* of each non-obvious step — without parrot padding.
- **PEP 8 enforced in CI**: `ruff format --check` now gates alongside
  `ruff check`; the whole tree is `ruff format`-clean.
- Ecosystem dependencies (`os-helper`, `audio-helper`, …) now resolve from
  **PyPI** instead of git pins.
- Move the private working notes under a gitignored `.private/` directory.

## [0.7.0] — 2026-07-13

### Added
- **WER/chrF fidelity gating in CI.** The round-trip *pipeline* and *threshold
  gating* now run in CI via deterministic stub transcribers (a real
  synthesis→STT round-trip needs a live engine the runner lacks). Versioned
  fidelity thresholds (`max_mean_wer: 0.20`, `min_mean_chrf: 0.75`) in
  `thresholds.yaml`. New `speaker-helper eval --transcribe` runs the *real*
  round-trip locally with `vocal-helper` (the `stt` extra), for one language or
  a `--languages` matrix.

## [0.6.0] — 2026-07-13

### Added
- **Technical report** (`docs/tech-report.en.md` + `docs/tech-report.fr.md`,
  bilingual, sharing `docs/refs.bib`): architecture, the producer/consumer
  streaming pipeline, cloning, speech-to-speech sources, the evaluation
  methodology, and the multi-language native-MLX vs CPU measurements.
- **Measured default profiles**: `DEFAULT_PROFILES` now carry reference
  native-MLX operating points (fr/en/es RTF ~0.15–0.19, quality prior),
  obtained with `tune_profiles`; recalibrate per host.

## [0.5.1] — 2026-07-12

### Documentation
- `BENCHMARKS.md`: added real **native MLX (Apple GPU)** multi-language numbers —
  kokoro synthesises **6–8× faster than real time** (fr 0.151, en 0.133, es
  0.141 RTF, all passing), versus CPU-Docker under load (RTF > 1.0). Confirms the
  native-MLX operating point on Apple Silicon.

## [0.5.0] — 2026-07-12

### Added
- **Multi-language measurement.** Bundled `en` and `es` evaluation datasets
  (alongside `fr`), `load_dataset(language=…)`, and `run_multilang_eval()` —
  runs the gate once per language (voice auto-picked per language, warmed up)
  and returns a report per language. CLI: `eval --languages fr,en,es` prints a
  matrix and gates on all. Measured against live kokoro (see `BENCHMARKS.md`).
- **Per-language operating profiles** (`speaker_helper.profiles`):
  `LanguageProfile` bundles a language's hyperparameters — voice, engine, and
  the streaming producer/consumer knobs (`first_chunk_sentences`,
  `stream_concurrency`) — plus its measured RTF/quality. `Speaker.from_profile`,
  `profile_for`, and `tune_profiles` (measure → profile) tie it together.
- Git install instructions (no PyPI yet) and a `BENCHMARKS.md` in the README /
  LISEZMOI.

## [0.4.0] — 2026-07-12

### Added
- **Speech-to-speech sources** (`speaker_helper.sources`): bring audio in and
  re-voice it. `from_youtube` (extra `youtube`), `from_podcast` (extra
  `podcast`), `from_microphone` (extra `mic`), and `revoice()` — transcribe with
  `vocal-helper`, then speak the transcript (cloned voice / new language).
- CLI `speak-from --source youtube|podcast|mic` for one-shot re-voicing.
- **DeepEval integration** (`speaker_helper.eval.deepeval_metrics`, extra
  `eval`): `RealTimeFactorMetric` and `AudioIntegrityMetric` adapt the native
  measurements as DeepEval custom metrics — deterministic and offline.

## [0.3.0] — 2026-07-12

### Added
- **MCP server.** When `fastapi-mcp` is installed (bundled with the `server`
  extra), the REST endpoints are exposed as Model Context Protocol tools at
  `/mcp` — so an assistant can `synth`, `synth_stream`, `clone_voice`,
  `list_voices`, and `health` directly. `create_app(enable_mcp=False)` opts out.
- Stable `operation_id`s on every route, used as the MCP tool names.

### Fixed
- Pinned `os-helper` to `v1.4.1` to match `audio-helper`, resolving a pip
  dependency conflict that broke a clean install.

## [0.2.0] — 2026-07-12

### Added
- **Backend abstraction.** A `TTSEngine` protocol with a backend registry;
  Voicebox is now one backend behind it. A deterministic, serverless
  `MockEngine` ships for tests, CI, and the evaluation layer.
- **Voice cloning, everywhere** (`Speaker.clone_voice`, CLI `clone` + `--clone*`
  flags, REST `POST /clone`). Give only a recording: over-long audio is trimmed
  with `audio-helper` and the transcript is derived with `vocal-helper`. A
  bundled reference voice is the default.
- **AI evaluation layer** (`speaker_helper.eval`): committed French dataset,
  metrics (RTF, audio anomalies, WER, chrF), quality priors + Pareto selection,
  versioned thresholds, and a `speaker-helper eval` command that gates CI via
  its exit code.
- **Streaming HTTP endpoint** `POST /synth/stream` (Server-Sent Events, one
  chunk per sentence with base64 WAV + timing).
- **Robustness**: httpx retries with exponential backoff on transient failures,
  and engine warm-up at server startup.

### Changed
- Adopted the **AI Helpers ecosystem**: logging through `os-helper`, audio
  slicing/concatenation through `audio-helper` (both installed from git). New
  optional `stt` extra pulls `vocal-helper` for transcription.
- `Settings` gains `backend`, `clone`, and `mock`; `Speaker` exposes `engine`
  (with a backward-compatible `client` alias) and `warmup`.
- Health and eval report the active backend rather than assuming Voicebox.

### Guardrails
- A committed `commit-msg` hook (`.githooks/`) refuses any AI-assistant
  attribution in commit messages; authorship stays with human maintainers.

## [0.1.0] — 2026-07-12

### Added
- Initial release: text-to-speech over a local Voicebox engine, the inverse of
  `vocal-helper`.
- `Speaker` façade with **offline** (`say`) and **streaming** (`stream`) modes;
  streaming reports time-to-first-audio and keeps emission in order.
- Typed async `VoiceboxClient`: idempotent preset-profile bootstrap,
  synchronous `POST /generate/stream`, and an automatic async `/generate`
  fallback that triggers the model download on a fresh engine.
- `Settings` (YAML + `${VAR}` expansion + `SPEAKER_HELPER_*` env overrides).
- CLI: `speaker-helper synth | voices | serve`.
- REST API server (`FastAPI` + `uvicorn`) with `/health`, `/voices`, `/synth`.
- Docker image and `docker-compose.yml` for the server.
- Tests (pytest, deterministic units + `@slow` live integration) and CI.
