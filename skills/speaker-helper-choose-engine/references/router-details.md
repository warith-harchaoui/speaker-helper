# Router details (speaker-helper)

Reference material for the `speaker-helper-choose-engine` skill. Source of truth: `speaker_helper/router.py`.

## Where the evidence comes from (in order of confidence)

1. **Measured reports** — pass a list of `EvalReport` objects (from `run_eval` / `run_multilang_eval` / `tune_profiles`, i.e. the `speaker-helper eval` path) to `route(..., reports=reports)`. Both axes (RTF and quality) are then measured on *your* host -> highest confidence.
2. **The built-in operating-point catalogue** (`default_operating_points(language)`) — seeded from per-language profiles (kokoro RTF measured on native MLX) plus engine quality priors. RTF is known only where it was measured; other engines carry a quality prior with an *unknown* RTF and are therefore excluded from online routing by default (the router will not claim an engine keeps up if it was never timed).

## Confidence flag

`RouteDecision.confidence` is derived from the two provenance flags on the chosen point:

- `high` — both quality and RTF measured (`quality_source == "measured_chrf"` and `rtf_source == "measured"`).
- `medium` — exactly one axis measured.
- `low` — both from priors/estimates (the default catalogue with no reports passed).

## Objectives, restated

- **online_realtime**: feasibility gate `mean_rtf <= rtf_ceiling` (default `0.8`; `RTF < 1` is the hard real-time boundary). Only measured-RTF engines survive when `require_measured_rtf=True`. Among survivors, pick the highest quality; only Pareto-front points can win; ties break toward the faster engine. Mode `streaming`, `first_chunk_sentences=1`, `stream_concurrency=1` for minimal time-to-first-audio.
- **offline**: pure quality argmax over the whole pool; RTF disregarded except as an optional `rtf_budget` patience cap and an equal-quality speed tie-break. Mode `offline` (whole-text synthesis). No Pareto gate (that would let an unmeasured RTF drop a higher-quality engine).

## Key `RouteRequest` fields

- `condition`: `"online_realtime"` or `"offline"` (required).
- `language`: ISO-639-1, default `"fr"`.
- `rtf_ceiling`: online hard bound, default `0.8`.
- `rtf_budget`: offline optional patience cap (`None` = no cap).
- `quality_floor`: reject candidates below this quality, both conditions.
- `require_measured_rtf`: online, default `True` — refuse untimed engines.

## Consuming the decision

- `RouteDecision.apply(settings)` -> a `Settings` copy carrying the routed backend/engine/mode/first-chunk granularity. `stream_concurrency` is a `Speaker` argument, read it off the decision separately.
- `Speaker.from_route(condition, language=...)` -> a ready `Speaker` with the decision applied.
- `route_settings(condition, language=...)` -> `(Settings, RouteDecision)`.
- `RouteDecision.to_dict()` -> JSON for API / MCP / CLI. The `/route` endpoint and the MCP `route` tool return this.
