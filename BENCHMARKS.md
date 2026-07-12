# Benchmarks — multi-language RTF & quality

Measured with the built-in evaluation gate
(`speaker-helper eval --languages fr,en,es`), one report per language, voice
auto-picked per language and warmed up. Quality is the engine prior (no
transcriber in these runs); anomaly rate is the fraction of clipped / empty /
aberrant-duration outputs.

> **These numbers are hardware-dependent — read the conditions.** The evaluation
> is the source of truth; re-run it on your machine.

Hardware: Apple M2 Max. Engine: **kokoro** (Voicebox).

## Native MLX (Apple GPU / Metal) — `:17493` — recommended

| lang | cases | mean RTF | p95 RTF | anomaly | quality | verdict |
|------|------:|---------:|--------:|--------:|--------:|---------|
| fr   | 12    | **0.151** | 0.201   | 0.000   | 0.75    | PASS |
| en   | 10    | **0.133** | 0.150   | 0.000   | 0.75    | PASS |
| es   | 10    | **0.141** | 0.170   | 0.000   | 0.75    | PASS |

The native Voicebox backend on the **Apple GPU (MPS/Metal)** synthesises **6–8×
faster than real time** in every language, with zero anomalies. This is
speaker-helper's default port (`:17493`) — the intended operating point.

## CPU inside Docker (colima) — `:17600`

| lang | cases | mean RTF | p95 RTF | anomaly | quality | verdict |
|------|------:|---------:|--------:|--------:|--------:|---------|
| fr   | 12    | 1.341    | 1.723   | 0.000   | 0.75    | FAIL (RTF > 1.0) |
| en   | 10    | 1.131    | 1.470   | 0.000   | 0.75    | FAIL (RTF > 1.0) |
| es   | 10    | 1.287    | 1.678   | 0.000   | 0.75    | FAIL (RTF > 1.0) |

CPU synthesis is **borderline and load-sensitive**: on an idle host French
measured mean RTF ≈ 0.32–0.37 (passing), but under CPU contention it climbs
above 1.0 (failing). Docker on macOS has **no GPU/Metal passthrough**, so the
container cannot use MPS — hence the ~8× gap with native MLX above.

## Takeaways

- **On Apple Silicon, run the native MLX Voicebox** (`:17493`) — it is the
  default and gives a comfortable RTF well below 1.0 across languages.
- The evaluation gate correctly flags the CPU-under-load case: quality/integrity
  hold (zero anomalies everywhere), only *speed* misses the bar there.
- speaker-helper is engine- and host-agnostic: point it at whichever engine you
  run (`--port`, `settings.yaml`, or `SPEAKER_HELPER_VOICEBOX_PORT`) and re-run
  `eval --languages …` for numbers on *your* setup.

---

Author: Warith HARCHAOUI — https://harchaoui.org/warith/ai-helpers
