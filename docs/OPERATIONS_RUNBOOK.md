# Operations Runbook

Operational guide for running and troubleshooting the app in development/CI environments.

## 1) Startup Checklist

1. Install dependencies (`requirements-dev.txt`).
2. Verify LLM key input flow (sidebar Groq key).
3. Confirm storage mode (`APP_STORE_BACKEND`).
4. Run app:

```powershell
streamlit run app.py
```

## 2) Runtime Controls

### Storage

- `APP_STORE_BACKEND=auto|json|mongo`
- `MONGODB_URI` (required for forced mongo)
- optional Mongo collection names (see `README.md`)

### Orchestration

- `USE_GENERIC_ASSET_FLOW`
- `ENABLE_VERIFY_STAGE`
- `ENABLE_POLICY_GATE`
- `POLICY_GATE_MODE`
- `SCHEMA_VALIDATE_ENFORCE`
- `MAX_PARALLEL_TOOLS`
- `ENABLE_PARALLEL_DAG`
- `WORKFLOW_FAIL_POLICY`
- `EXECUTE_RETRY_COUNT`

### Observability / Telemetry

- `OBSERVABILITY_OTEL_ENABLED`
- `OTEL_SERVICE_NAME`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `OTEL_EXPORTER_OTLP_INSECURE`
- `OBSERVABILITY_PAYLOAD_CAPTURE_ENABLED`
- `OBSERVABILITY_PAYLOAD_RETENTION_DAYS`
- `OBSERVABILITY_PAYLOAD_VAULT_DIR`
- `OBSERVABILITY_PAYLOAD_ENCRYPTION_ENABLED`
- `OBSERVABILITY_PAYLOAD_ENCRYPTION_KEY`
- `OBSERVABILITY_PAYLOAD_KEY_FILE`

### Web Sourcing

- `SERPER_API_KEY` (if provider is `serper`)
- UI controls for strict mode, failover, retries, trusted domains, thresholds

## 3) CI/Quality Commands

```powershell
ruff check .
mypy
python -m pytest -q
python scripts/validate_plugin_specs.py
python scripts/simulate_workflow.py --workflow full_asset_suite --dry
python scripts/check_import_cycles.py --package main_app --check-boundaries
```

## 4) Common Failure Cases

### A) `SERPER_API_KEY` missing

- Symptom: web search fails when `serper` selected.
- Action: switch provider to `duckduckgo` or set env key.

### B) Mongo backend startup failure

- Symptom: storage initialization error.
- Action: set `APP_STORE_BACKEND=json` or provide valid `MONGODB_URI`.

### C) Schema/verify/policy stage failures

- Symptom: tool status `error` despite executor return.
- Action: inspect `artifact.provenance` for:
  - `schema_validation`
  - `verification`
  - `policy_gate`

### D) Import boundary warnings/failures

- Action:

```powershell
python scripts/check_import_cycles.py --package main_app --check-boundaries
```

### E) OTel exporter unavailable (`localhost:4317` / `StatusCode.UNAVAILABLE`)

- Symptom: repeated metric export retry logs.
- Cause: OTLP collector is not reachable.
- Action:

```powershell
cd observability
docker compose up -d
docker compose ps
```

Or disable exporter for local-only mode:

```powershell
$env:OBSERVABILITY_OTEL_ENABLED="false"
```

### F) Windows Docker pipe error (`dockerDesktopLinuxEngine` not found)

- Symptom: `open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`.
- Cause: Docker Desktop Linux backend is not running (often WSL not installed/enabled).
- Action:

1. Ensure WSL is installed:

```powershell
wsl --install
```

2. Reboot machine.
3. Start Docker Desktop and wait until engine is healthy.
4. Select Docker context:

```powershell
docker context use desktop-linux
docker version
docker ps
```

5. Retry compose stack startup in `observability/`.

## 5) Operational Diagnostics to Watch

- Stage duration and retries
- Policy/verification issue counts
- Web sourcing accepted count and quality stats
- Cache hit/miss behavior
- Workflow node blocked/failed transitions
- End-to-end trace stitched by `request_id` and `run_id`
- Payload references (`payload_ref`) for deep forensic inspection
