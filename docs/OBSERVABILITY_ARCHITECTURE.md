# Observability Architecture

This document defines the end-to-end observability architecture for this repository.

## Goals

- Correlate one user action across UI, web sourcing, LLM calls, orchestration, jobs, and exports.
- Export traces, metrics, and logs to an OpenTelemetry backend.
- Preserve backward compatibility for existing in-app observability views.
- Capture full payload logs through a secure payload vault and reference them from telemetry events.

## Core Components

1. `TelemetryService` (`main_app/services/telemetry_service.py`)
   - Context propagation for `request_id`, `session_id`, `run_id`, `job_id`, `trace_id`, `span_id`.
   - Span lifecycle via `start_span(...)`.
   - Metric emission via `record_metric(...)`.
   - Event emission via `record_event(...)`.
   - Full payload capture via `attach_payload(...)`.

2. `ObservabilityService` (`main_app/services/observability_service.py`)
   - Existing LLM metrics table logic (cache hit, latency, token and cost rollups).
   - Adapter that dual-writes to `TelemetryService`.

3. Payload Vault (`PayloadVault`)
   - Stores full payload envelopes under `.cache/observability_payloads` (default).
   - Encryption at rest enabled by default when `cryptography` is available.
   - Retention and purge policy controlled by env variables.

4. OTel Bridge (`OTelBridge`)
   - Optional OTel exporter integration controlled by `OBSERVABILITY_OTEL_ENABLED`.
   - Exports traces and metrics to OTLP endpoint.

## Runtime Consumption Model

Observability data is consumed through two paths:

1. In-app runtime buffers (always available while app is running)
   - metric families (aggregated)
   - recent metric samples
   - recent events
   - payload lookup by `payload_ref`

2. External OTel backend (optional)
   - traces in Tempo
   - logs in Loki
   - metrics in Prometheus/Grafana

If OTel backend is unavailable, in-app observability remains usable.

## Correlation Envelope

Each telemetry event or metric includes a shared set of IDs:

- `request_id`
- `session_id`
- `run_id`
- `job_id`
- `trace_id`
- `span_id`

Recommended practice:

- start every investigation by fixing one ID (`request_id` first, then `run_id` if present)
- keep the same ID across events, metric samples, payload inspection, and dashboards

## Instrumentation Points

- UI runtime request span: `ui.request`
- Web sourcing:
  - `web_sourcing.run.start`
  - `web_sourcing.run.end`
- Grounding:
  - `grounding.build_sources.start`
  - `grounding.build_sources.end`
- LLM:
  - `llm.call`
  - `llm.call.success`
  - `llm.call.error`
  - `llm.cache.hit`
- Agent orchestration:
  - `agent.run.start`
  - `agent.stage`
  - `agent.run.end`
- Background jobs:
  - `background_job.submit`
  - `background_job.run`
  - `background_job.end`
- Export pipelines:
  - `export.quiz.start/end`
  - `export.report.start/end`
  - `export.video.start/end`

## Signal Semantics

Use these signal types intentionally:

- Events: lifecycle and status transitions, best for debugging sequence.
- Metric samples: precise emitted values with context IDs.
- Metric families: aggregate rollups, best for quick health checks.
- Payload vault: full diagnostic envelope when event attributes are not enough.

## Persistent Diagnostics Stores

Agent orchestration diagnostics are now persisted via storage bundle:

- Run ledger store (JSON/Mongo)
- Stage ledger store (JSON/Mongo)

This improves continuity across app reruns and restarts.

## Local OTel Stack

See `observability/docker-compose.yml` and related config files.

- OTel Collector
- Tempo
- Loki
- Prometheus
- Grafana

Bring up locally:

```powershell
cd observability
docker compose up -d
```

## Efficiency Defaults

For fastest local debugging:

- Use in-app tab first (`request_id` filtered events).
- Only move to Grafana when you need cross-session time windows or multi-user history.
- Keep payload retention bounded (`OBSERVABILITY_PAYLOAD_RETENTION_DAYS`) to reduce local storage growth.
