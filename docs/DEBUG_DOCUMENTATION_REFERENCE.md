# Debug Documentation Reference

This guide explains backend execution flow and how to triage failures quickly.

## 1. Correlation IDs You Should Always Capture

- `request_id`: one UI-triggered request lifecycle.
- `run_id`: orchestration run identifier (agent/tool/stage flow).
- `job_id`: background job identifier (async rendering/export).
- `trace_id`: distributed trace identifier.
- `span_id`: specific operation inside a trace.

## 2. End-to-End Backend Flow

## A. UI request lifecycle
- Runtime entry: `main_app/app/runtime.py`
- Tab dispatch: `main_app/ui/tabs/main_tabs.py`
- Starts with request context and telemetry scope.

## B. Grounding and web sourcing
- Merge service: `main_app/services/global_grounding_service.py`
- Web pipeline: `main_app/platform/web_sourcing/orchestrator.py`
- Key reliability signals include retries, failover, and quality acceptance.

## C. LLM generation
- Service: `main_app/services/cached_llm_service.py`
- Track latency, token usage, cache hit rate, and estimated cost.

## D. Agent orchestration
- Entry: `main_app/services/agent_dashboard/dashboard_service.py`
- Stage execution: `tool_stage_service.py`
- Diagnostics persistence: `run_ledger_service.py`, `stage_ledger_service.py`

## E. Background jobs
- Manager: `main_app/services/background_jobs.py`
- Used by slide/video/audio export-heavy flows.

## F. Export pipelines
- Quiz: `quiz_exporter.py`
- Report: `report_exporter.py`
- Slides: `slide_deck_exporter.py`
- Video: `video_exporter.py`
- Avatar video internals:
  - timeline builder: `video_conversation_timeline_service.py`
  - render profile selector: `video_render_profile_service.py`
  - lipsync cues: `video_avatar_lipsync_service.py`
  - avatar overlays: `video_avatar_overlay_service.py`

## G. Observability signal path
- In-app telemetry: `main_app/services/telemetry_service.py`
- Adapter/service: `main_app/services/observability_service.py`
- Local stack: `observability/docker-compose.yml`

## 3. Symptom-Based Playbooks

## Web sourcing quality issues
1. Check provider diagnostics and warning counts.
2. Verify strict mode and quality threshold.
3. Confirm failover provider configuration and credentials.

## LLM latency/cost spikes
1. Filter observability events by `request_id` and `run_id`.
2. Compare model/token settings to baseline.
3. Inspect cache hit ratio changes.

## Agent stage failures
1. Identify failed `tool_key` + `stage_key`.
2. Check run/stage ledgers for dependency or policy errors.
3. Fix upstream artifact dependency and retry.

## Background job failures
1. Query by `job_id` lifecycle events.
2. Check worker availability and input payload validity.
3. Validate output path and write permissions.

## Export failures
1. Inspect exporter-specific error details.
2. Validate source artifact schema and payload completeness.
3. Correlate with prior stage/job failure events.

## Avatar-mode degradation/fallback
1. Filter events for `video.avatar_fallback` and `video.avatar_lipsync.segment`.
2. Check `render_mode_requested` vs `render_mode_used` and `avatar_fallback_used` in payload metadata.
3. Inspect `conversation_timeline` + `audio_segments` for timing monotonicity.
4. If needed, force `classic_slides` temporarily while fixing avatar dependencies.

## OTel export connectivity errors
1. Ensure Docker daemon is running.
2. Start local stack in `observability/`.
3. Validate OTLP endpoint (`localhost:4317` by default).
4. Use fallback in-app telemetry until exporter connectivity is restored.

## 4. Standard Debug Sequence

1. Capture `request_id` from Observability tab.
2. Pivot to `run_id` for orchestration path.
3. If async, pivot to `job_id`.
4. Inspect trace tree (`trace_id` / `span_id`) and event timeline.
5. Use payload references for exact input/output body inspection.

## 5. Related References

- `docs/OBSERVABILITY_ARCHITECTURE.md`
- `docs/OBSERVABILITY_DEBUG_COOKBOOK.md`
- `docs/OPERATIONS_RUNBOOK.md`
- `docs/AGENT_WORKFLOWS_AND_TOOLS.md`
- `docs/ORCHESTRATION_STATE_MACHINE.md`
