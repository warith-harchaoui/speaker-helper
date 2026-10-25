# Benchmarks — multi-language RTF & quality

Measured with the built-in evaluation gate, one report per language, voice
auto-picked per language and warmed up:

```bash
speaker-helper eval --languages fr,en,es --json report.json
```

Quality is the engine prior (no transcriber in these runs); anomaly rate is the
fraction of clipped / empty / aberrant-duration outputs. The gate's bar is
`mean_rtf < 1.0`, `p95_rtf < 1.0`, `anomaly_rate = 0`.

> **These numbers are hardware-dependent — read the conditions.** The evaluation
> is the source of truth; re-run it on your machine.

These measured RTFs are exactly the evidence the **router** (`speaker-helper
route`) consumes: for the `online_realtime` condition it keeps only engines whose
mean RTF beats real time (with margin) and, among those, maximises quality. The
**quality** column here is the engine *prior* (`quality_source = prior`) because
these runs had no transcriber. Measured quality comes from either the round-trip
**intelligibility** check (`eval --transcribe`, WER/chrF, text→speech→text) or,
for **naturalness**, a MOS predictor (UTMOSv2) measured in the companion study
and folded back as `quality_source = measured_mos`.

## Conditions

| | |
|---|---|
| Measured on | **2026-10-25** |
| Host | Apple M2 Max (12 cores), macOS 26.5.2 |
| Engine | `kokoro` — kokoro-onnx 0.6.1 on onnxruntime 1.26.0, **in-process** |
| Execution provider | `CPUExecutionProvider` (no GPU, no Metal) |
| Python | 3.13.13 |

There is **one** operating point to report, and that is the architectural
change: the engine is a backend inside this process, selected by
`settings.backend`. There is no second process to run it in, no port, and no
GPU path in the ONNX build — so there is nothing left to put in a second
column.

## Kokoro, in-process, warmed up

| lang | cases | mean RTF | p95 RTF | anomaly | quality | verdict |
|------|------:|---------:|--------:|--------:|--------:|---------|
| fr   | 12    | **0.223** | 0.261   | 0.000   | 0.75    | PASS |
| en   | 10    | **0.237** | 0.299   | 0.000   | 0.75    | PASS |
| es   | 10    | **0.206** | 0.230   | 0.000   | 0.75    | PASS |

Four to five times faster than real time in every language, on the CPU, with
zero anomalies. That is comfortably inside the router's `online_realtime`
ceiling of `0.8`, so streaming a conversation is a matter of chunking rather
than of hardware.

## The model load is not the engine

Building the ONNX session costs about **5 seconds** once per process. Timed
against a short utterance it dominates completely:

```
1.19s audio, RTF 4.42      <- first call in the process
1.19s audio, RTF 0.31      <- every call after it
```

This is why `run_eval` warms the engine up before timing anything, and why
`Speaker.warmup()` is public.

Until 0.9.2 it only did so on the `--languages` path. A **single-language**
`eval` measured the load in its first case and reported it as slow synthesis:

```
# speaker-helper --engine kokoro eval   (0.9.1 and earlier, cold, no warm-up)
mean_rtf=0.5219 p95_rtf=1.7617 anomaly_rate=0.0 quality=0.75 (prior)
FAIL: p95 RTF 1.7617 > 1.0

# speaker-helper --engine kokoro eval   (0.9.2, warmed)
mean_rtf=0.2288 p95_rtf=0.2921 anomaly_rate=0.0 quality=0.75 (prior)
PASS
```

Same engine, same dataset, same machine — a 6x error on the p95, and the kind
that reads as a busy laptop rather than a measurement fault. Worse, the two
entry points disagreed: the same engine passed under `--languages` and failed
under `eval`. The warm-up now lives in `run_eval`, so every caller measures the
same thing; pass `warmup=False` when cold start is deliberately what you want.

## Takeaways

- **Nothing to start, and still faster than real time.** The whole operating
  point is `pip install 'speaker-helper[kokoro]'` plus one `install-voice`.
- The evaluation gate measures speed (RTF), integrity (anomalies) and — with a
  transcriber — fidelity (WER/chrF), and exits non-zero when the bar is missed,
  so it gates CI.
- Warm up before you time. The one failing number on this page is a cold start.
- Re-run `speaker-helper eval --languages …` for numbers on *your* host; these
  are a reference point, not a promise.

---

## Historical: the REST engine (removed in 0.8.0)

**The figures below do not describe this code.** They were measured when
speaker-helper was a thin HTTP client of an out-of-process engine ("Voicebox"),
which it drove over REST on a fixed port. That backend was deleted in 0.8.0 when
Kokoro moved in-process; the only trace of it left in the package is a comment
in `config.py` explaining that a `voicebox:` section in a settings file is
dropped rather than refused, so an old configuration still loads.

They are kept here, dated and quarantined, because they are real measurements
and deleting them would erase the reason the architecture changed. They are
**not** re-attributed to the current engine, and neither table can be reproduced
from this repository: there is no MLX build to run and no separate engine to put
in a container.

Measured **2026-07** on Apple M2 Max. Engine: kokoro served by the REST engine.

### Native MLX (Apple GPU / Metal), port 17493

| lang | cases | mean RTF | p95 RTF | anomaly | quality | verdict |
|------|------:|---------:|--------:|--------:|--------:|---------|
| fr   | 12    | 0.151    | 0.201   | 0.000   | 0.75    | PASS |
| en   | 10    | 0.133    | 0.150   | 0.000   | 0.75    | PASS |
| es   | 10    | 0.141    | 0.170   | 0.000   | 0.75    | PASS |

### The same engine's CPU build inside Docker (colima), port 17600

| lang | cases | mean RTF | p95 RTF | anomaly | quality | verdict |
|------|------:|---------:|--------:|--------:|--------:|---------|
| fr   | 12    | 1.341    | 1.723   | 0.000   | 0.75    | FAIL (RTF > 1.0) |
| en   | 10    | 1.131    | 1.470   | 0.000   | 0.75    | FAIL (RTF > 1.0) |
| es   | 10    | 1.287    | 1.678   | 0.000   | 0.75    | FAIL (RTF > 1.0) |

Docker on macOS has no GPU/Metal passthrough, so the container could not use
MPS — hence the ~8× gap. The contrast is worth keeping for one reason: the
in-process ONNX engine measured above runs on the CPU too, and it is **five to
six times faster than that CPU container in French and Spanish** (4.8× in
English) while needing no second process at all. The out-of-process design was paying for itself twice.

---

Author: Warith HARCHAOUI — https://harchaoui.org/warith/ai-helpers
