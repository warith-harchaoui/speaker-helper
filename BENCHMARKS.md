# Benchmarks — multi-language RTF & quality

Measured with the built-in evaluation gate
(`speaker-helper eval --languages fr,en,es`), one report per language, voice
auto-picked per language. Quality is the engine prior (no transcriber in this
run); anomaly rate is the fraction of clipped / empty / aberrant-duration
outputs.

> **These numbers are hardware- and load-dependent — read the conditions.** The
> evaluation is the source of truth; re-run it on your machine.

## Engine: kokoro (Voicebox)

### CPU-Docker (colima), machine under load — warm

| lang | cases | mean RTF | p95 RTF | anomaly | quality | verdict |
|------|------:|---------:|--------:|--------:|--------:|---------|
| fr   | 12    | 1.341    | 1.723   | 0.000   | 0.75    | FAIL (RTF > 1.0) |
| en   | 10    | 1.131    | 1.470   | 0.000   | 0.75    | FAIL (RTF > 1.0) |
| es   | 10    | 1.046    | 1.207   | 0.000   | 0.75    | FAIL (RTF > 1.0) |

Conditions: Apple M2 Max, kokoro on **CPU inside a Docker VM** (colima on
`:17600`), host load average ≈ 5–8 (concurrent builds). Zero audio anomalies in
every language — quality/integrity hold; only speed misses the bar.

### Same CPU-Docker engine, host idle (reference)

Earlier, on the *same* CPU-Docker engine with the host idle, French measured
**mean RTF ≈ 0.32–0.37** (faster than real time). CPU synthesis is therefore
**borderline and load-sensitive**: it clears the RTF < 1.0 bar when the machine
is free and misses it under contention.

## Reading the result

The gate is doing its job: it flags that, under CPU contention, kokoro is *not*
reliably faster than real time. Two ways to get comfortably below 1.0:

1. **Use the GPU (recommended on Apple Silicon).** Docker on macOS has **no
   GPU/Metal passthrough**, so the CPU-Docker container cannot use MPS. Run the
   **native MLX Voicebox** instead (its default port `:17493` is also
   speaker-helper's default) — it uses the Apple GPU and is markedly faster.
2. **Give the CPU headroom** — measure on an unloaded host.

speaker-helper is engine- and host-agnostic: point it at whichever engine you
run (`--port`, `settings.yaml`, or `SPEAKER_HELPER_VOICEBOX_PORT`) and re-run
`eval --languages …` to get numbers for *your* setup.

---

Author: Warith HARCHAOUI — https://harchaoui.org/warith/ai-helpers
