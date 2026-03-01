# Observability Tab Guide

This guide explains how to use the in-app Observability tab quickly and effectively.

## 1) What the Tab Is Best For

Use it for:

- first-pass debugging during development
- correlation by `request_id` / `run_id` / `job_id`
- inspecting full payloads via `payload_ref`
- verifying instrumentation coverage without leaving Streamlit

## 2) Sections and Their Purpose

### Top Summary Cards

Use for immediate health signal:

- LLM requests/calls/tokens
- cache hit behavior
- latency/cost rollups
- telemetry buffer counters

### Telemetry Metric Families (Aggregated)

Use for high-level metric shape by metric name:

- count, sum, avg, min, max
- last seen value and timestamp
- last correlation IDs and attributes

Best when you want trend-like summary quickly.

### Recent Telemetry Metric Samples (All Emissions)

Use for exact raw emitted metric points:

- one row per emitted metric sample
- includes full context (`request_id`, `run_id`, `trace_id`, etc.)
- includes raw attributes map

Best when validating instrumentation or analyzing one specific run.

### Recent Telemetry Events

Primary timeline view:

- one row per event
- `event_name`, `component`, `status`, `timestamp`
- context IDs and attributes
- `payload_ref` when attached

Best starting point for failure investigations.

### Payload Lookup

For deep details:

- paste `payload_ref` from an event
- inspect full payload envelope and diagnostics

Use this when event attributes are not enough.

### Controls

- `Reset Observability Metrics`: clears runtime in-memory telemetry buffers.
- `Download Metrics JSON`: exports current tab data snapshot.

## 3) Recommended Filter Order

When debugging one issue:

1. filter events by `request_id`
2. narrow with `run_id` if available
3. inspect matching metric samples by same IDs
4. open payload refs for failed/warning events

When debugging a component generally:

1. filter events by component name
2. filter metric families by metric name prefix
3. inspect recent metric samples for outliers

## 4) Correlation IDs Cheat Sheet

- `request_id`: one end-user request path anchor
- `run_id`: one orchestration/tool run anchor
- `job_id`: one async background job anchor
- `trace_id` / `span_id`: distributed tracing anchor

Always keep one ID fixed while switching tab sections.

## 5) High-Value Event Names to Watch

- `web_sourcing.run.start` / `web_sourcing.run.end`
- `grounding.build_sources.start` / `grounding.build_sources.end`
- `llm.call`, `llm.call.success`, `llm.call.error`, `llm.cache.hit`
- `background_job.submit`, `background_job.run`, `background_job.end`
- `export.*` events

## 6) Quick Troubleshooting

### Nothing appears in telemetry sections

- ensure at least one generation flow has been run
- verify telemetry is being emitted by active code path
- confirm you did not reset buffers

### Payload lookup returns not found

- verify `payload_ref` copy is exact
- check `OBSERVABILITY_PAYLOAD_CAPTURE_ENABLED=true`
- check vault location (`OBSERVABILITY_PAYLOAD_VAULT_DIR`)

### OTel exporter errors but tab still works

In-app tab uses local runtime buffers and still works.

- start collector stack for external export, or
- set `OBSERVABILITY_OTEL_ENABLED=false` for local-only mode
