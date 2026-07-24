---
name: speaker-helper-choose-engine
description: Uses the speaker-helper backend router to pick the best text-to-speech engine plus mode from measured quality-vs-speed evidence, for a stated condition. Two conditions: online_realtime (delay-bounded streaming, the engine must synthesize faster than real time, so speed is the real-time factor RTF and it must beat 1; among engines that keep up, maximize quality) and offline (batch, quality is the ONLY objective, speed disregarded). Use it when the user asks which TTS engine to use, wants the fastest or lowest-latency speech, wants best-quality offline synthesis, wants a speed-vs-quality tradeoff, or wants to route to the best backend for a language. Trigger phrases include "which TTS engine should I use", "fastest TTS", "best quality TTS", "real-time speech", "low-latency synthesis", "offline high-quality voice", "choose a voice engine", "route to the best backend", "tradeoff speed vs quality", "RTF". NEGATIVE triggers: does not itself transcribe audio or run diarization.
---

# Choose the Best TTS Engine + Mode (speaker-helper router)

The router (`speaker_helper/router.py`) turns measured quality-vs-speed evidence into a concrete, justified choice of **engine + mode + streaming knobs** for a **condition**. It never guesses: every decision is traceable to numbers and carries a `justification` and a `confidence` flag.

The two conditions and their objectives (this is the scientific core — state it to the user):

- **online_realtime** (delay-bounded / streaming): to sustain playback without underrun the engine must synthesize **faster than real time** — `RTF < 1` is the hard feasibility boundary; the router keeps a margin (default ceiling `0.8`) to absorb time-to-first-audio and jitter. Among the engines that keep up, it **maximizes quality**, and only points on the Pareto front can win. Chosen mode is `streaming` with low-latency knobs. If nothing provably keeps up, that is reported, not hidden.
- **offline** (batch): there is **no real-time constraint** (RTF may exceed 1) and **quality is the only objective** — speed is disregarded entirely. The router picks the highest-quality engine outright. Chosen mode is `offline`. RTF appears only as an optional patience budget or an equal-quality tie-break.

Quality means round-trip intelligibility / MOS-style quality (measured chrF where available, otherwise an engine prior). Speed means mean RTF (compute time ÷ audio duration).

## Instructions

1. Establish the **condition** from the user's words:
   - "real-time", "low latency", "streaming", "live", "as it types" -> `online_realtime`.
   - "best quality", "offline", "batch", "render a file", "doesn't need to be fast" -> `offline`.
   Also get the target `language` (e.g. `fr`, `en`, `es`).

2. Get the decision in Python (returns engine, mode, streaming knobs, confidence, and a number-citing justification):
   ```python
   from speaker_helper import route, RouteRequest

   d = route(RouteRequest(condition="online_realtime", language="fr"))
   print(d.engine, d.mode, d.confidence)          # e.g. kokoro streaming ...
   print(d.justification)                          # why this point won, citing RTF + quality
   ```
   For offline: `route(RouteRequest(condition="offline", language="fr"))` -> `mode == "offline"`.

3. Turn the decision straight into a ready-to-use synthesizer with `Speaker.from_route`:
   ```python
   from speaker_helper import Speaker
   spk = Speaker.from_route("online_realtime", language="fr")   # applies the routed engine + mode + knobs
   spk.save("Bonjour.", "out.wav")
   ```
   Use `Speaker.from_route("offline", language="fr")` for the quality-first choice.

4. Serve the router over HTTP for other services / the MCP surface:
   ```bash
   speaker-helper serve --host 0.0.0.0 --port 8080
   # then POST the condition to /route:
   curl -s -X POST localhost:8080/route -H 'content-type: application/json' \
     -d '{"condition":"online_realtime","language":"fr"}'
   ```
   The `/route` endpoint returns the same decision (engine, mode, quality, mean_rtf, confidence, justification) as JSON. The MCP server exposes an equivalent `route` tool.

5. Tune the constraints when the user has requirements (all optional `RouteRequest` fields):
   - `rtf_ceiling` (online only, default `0.8`): the hard RTF bound an engine must beat. Lower it for more headroom.
   - `require_measured_rtf` (online only, default `True`): refuse engines whose RTF was never measured — the router will not claim an untimed engine keeps up. Set `False` only to allow unmeasured engines.
   - `rtf_budget` (offline only): optional patience cap on RTF.
   - `quality_floor` (both): reject candidates below this quality.

6. Feed **measured** evidence for the highest confidence. By default the router uses the built-in per-language operating-point catalogue (kokoro RTF measured on native MLX; other engines carry a quality prior with unknown RTF, so they are excluded from online routing). Passing your own eval reports measures both axes on your host:
   ```python
   from speaker_helper import route, RouteRequest
   # reports = [EvalReport, ...] produced by run_eval / run_multilang_eval
   d = route(RouteRequest(condition="online_realtime", language="fr"), reports=reports)
   ```
   Generate reports with `speaker-helper eval --languages fr,en,es --transcribe` (the round-trip WER/chrF path). See the `references/router-details.md` note for how evidence confidence is rated.

7. Report back: chosen engine + mode, the `mean_rtf` and `quality` of the pick, the `confidence`, and the router's `justification`. If the online condition raised "no engine keeps up", relay that honestly and suggest measuring more engines or relaxing `rtf_ceiling`.

## Examples

**Scenario 1 — "Which TTS engine should I use for a real-time French assistant?"**
- Actions: `route(RouteRequest(condition="online_realtime", language="fr"))`; read `d.engine`, `d.mode` (`streaming`), `d.mean_rtf`, `d.justification`.
- Result: report the engine that maximizes quality while keeping `RTF < 0.8`, note it is streaming for low time-to-first-audio, and quote the justification. Offer `Speaker.from_route("online_realtime", language="fr")` to use it immediately.

**Scenario 2 — "I'm rendering an audiobook offline, I just want the best quality."**
- Actions: `route(RouteRequest(condition="offline", language="en"))`; `mode` is `offline`.
- Result: report the highest-quality engine (speed disregarded) and its quality/confidence; hand back `Speaker.from_route("offline", language="en")`.

**Scenario 3 — "Nothing feels fast enough for streaming — is any engine actually real-time here?"**
- Actions: run the online route; if it raises "no engine meets the online RTF ceiling ... with measured timing", relay that. Suggest `speaker-helper eval --transcribe` to measure more engines on this host, lowering nothing that is untrue, or relaxing `rtf_ceiling` / `require_measured_rtf=False` only with a caveat.
- Result: an honest answer plus a concrete path to a measured decision.

## Troubleshooting

- **Error:** `ValueError: no engine meets the online RTF ceiling ... with measured timing`.
  **Cause:** for `online_realtime`, no engine has a *measured* `mean_rtf` at or below the ceiling — the router refuses to claim an untimed engine keeps up.
  **Solution:** measure more engines with `speaker-helper eval --languages <langs> --transcribe` and pass the reports; or relax `rtf_ceiling`; or set `require_measured_rtf=False` (with a caveat that the pick is then unverified).

- **Error:** `ValueError: unknown condition '...'`.
  **Cause:** `condition` must be exactly `online_realtime` or `offline`.
  **Solution:** use one of those two literals.

- **Symptom:** decision `confidence` is `low`.
  **Cause:** both axes came from priors/estimates, not measurement (the default catalogue).
  **Solution:** pass measured eval `reports` to lift confidence to `medium`/`high`. See `references/router-details.md`.

- **Symptom:** offline picks an engine with unknown RTF.
  **Cause:** offline maximizes quality only; an unmeasured RTF never disqualifies a higher-quality engine.
  **Solution:** that is correct behavior. Set `rtf_budget` only if you actually need a compute cap.

## Triggering tests

Should trigger: "which TTS engine is fastest for real-time French", "best quality offline synthesis engine", "route me to the best backend", "can any engine run faster than real time here", "speed vs quality tradeoff for TTS", "pick a voice engine for low latency".

Should NOT trigger: "transcribe this audio", "who spoke when", "clone this voice" (that is the clone-voice skill), "just synthesize this text with the default engine" (that is the synthesize skill). This skill is specifically about *choosing/justifying* the engine + mode.
