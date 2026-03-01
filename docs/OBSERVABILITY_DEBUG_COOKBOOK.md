# Observability Debug Cookbook

Practical workflows for using observability quickly and consistently during day-to-day development.

## 1) Pick Your Operating Mode

### Mode A: In-app observability only (no Docker required)

Use this when you want fast local debugging from the Streamlit Observability tab.

```powershell
$env:OBSERVABILITY_OTEL_ENABLED="false"
streamlit run app.py
```

You still get:

- full in-app telemetry events
- metric samples and aggregates
- payload references and payload lookup

### Mode B: Full OTel stack (Grafana/Tempo/Loki/Prometheus)

Use this when you want cross-session dashboards and external trace/log/metric exploration.

```powershell
cd observability
docker compose up -d
docker compose ps
```

Then run the app with OTel enabled:

```powershell
$env:OBSERVABILITY_OTEL_ENABLED="true"
streamlit run app.py
```

## 2) Daily Fast Debug Workflow (Recommended)

1. Reproduce the issue once.
2. Open the **Observability** tab immediately.
3. Copy `request_id` (and `run_id` if present).
4. In **Recent Telemetry Events**, filter by `request_id`.
5. In **Recent Telemetry Metric Samples**, filter by the same `request_id`.
6. If an event has `payload_ref`, open **Payload Lookup** and inspect the full envelope.
7. If using Grafana, search by the same `request_id` to correlate across traces/logs/metrics.

This flow avoids guessing and keeps every investigation anchored to one correlation ID.

## 3) How to Read the Observability Tab Efficiently

Use sections in this order:

1. **Top cards**
   - sanity check throughput and recent activity
2. **Recent Telemetry Events**
   - primary timeline of what happened
3. **Recent Telemetry Metric Samples**
   - precise emitted values with context IDs
4. **Telemetry Metric Families (Aggregated)**
   - trend/volume view by metric name
5. **Payload Lookup**
   - deep forensic details

Avoid starting with aggregated metrics when debugging a single failure. Start with events first.

## 4) End-to-End Trace Path You Should See

For one user-triggered run, expected sequence is:

- `ui.request` (root)
- `grounding.build_sources.*` and/or `web_sourcing.run.*`
- `llm.call*`
- `agent.run.*` and `agent.stage` (agent path)
- `background_job.*` (if async)
- `export.*` (if quiz/report/video export)

Missing segments usually indicate instrumentation gaps or early failure before stage handoff.

## 5) Issue Playbooks

### A) Web sourcing quality or result count is poor

Check event + payload fields:

- `provider`, `provider_requested`
- `search_count`, `fetched_count`, `accepted_count`
- `warning_count`
- `failover_used`, `failover_reason`
- `provider_attempts`
- `quality_stats`

If `accepted_count` is low, inspect `quality_stats` and `warnings` first before changing provider.

### B) LLM latency/cost spike

Check:

- metrics: `llm_latency_ms`, `llm_tokens_total`, `llm_calls_total`
- events: `llm.call`, `llm.call.success`, `llm.call.error`, `llm.cache.hit`
- attributes: `model`, `task`, `cache_hit`, `estimated_cost_usd`

Validate pricing env vars:

- `LLM_INPUT_COST_PER_1M_USD`
- `LLM_OUTPUT_COST_PER_1M_USD`
- `LLM_MODEL_COST_OVERRIDES_JSON`

### C) Agent run fails at a stage

1. Filter events by `run_id`.
2. Locate failing `agent.stage` / `agent.run.end`.
3. Use `payload_ref` from the failing event.
4. Cross-check run/stage ledger persistence for the same `run_id`.

### D) Background job stuck or failed

Look for:

- `background_job.submit`
- `background_job.run`
- `background_job.end`

Correlate by `job_id` and then by `request_id`.

### E) Export failures (quiz/report/video)

Check corresponding `export.*` events and metric samples for:

- duration
- status
- output size (when available)
- payload diagnostics

## 6) Payload Inspection Workflow

1. Copy `payload_ref` from an event row.
2. Paste into **Payload Lookup**.
3. Review:
   - `context` envelope (`request_id`, `run_id`, `job_id`, `trace_id`)
   - diagnostic fields specific to failing component
4. If not found in UI, check files under:
   - `.cache/observability_payloads`

## 7) Grafana Usage Pattern (If OTel Stack Is Running)

1. Open Grafana `http://localhost:3000`.
2. In Explore:
   - traces: filter by `request_id` or `run_id`
   - logs: search for correlation IDs in structured JSON lines
   - metrics: inspect relevant metric names (`llm_*`, `web_sourcing_*`, `grounding_*`, `background_job_*`, `export_*`)
3. Keep one ID constant while switching between traces/logs/metrics.

## 8) Common Setup Failures

### `localhost:4317 StatusCode.UNAVAILABLE`

No collector is listening on OTLP endpoint.

Fix:

- start stack in `observability/` via Docker Compose, or
- set `OBSERVABILITY_OTEL_ENABLED=false`

### Windows pipe errors (`dockerDesktopLinuxEngine` not found)

Docker Desktop engine is not ready or WSL backend missing.

Fix summary:

- ensure WSL is installed and enabled
- start Docker Desktop and wait for engine healthy
- use `docker context use desktop-linux`

See `docs/OPERATIONS_RUNBOOK.md` for full Windows recovery steps.
