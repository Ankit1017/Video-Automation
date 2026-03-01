# Generic Asset Architecture

This document describes the current generic orchestration path used by the Agent Dashboard.

## Goal

Standardize all tool execution through one pipeline so every asset (topic, quiz, slideshow, video, etc.) gets:

- consistent stage execution
- artifact normalization
- schema checks
- verification checks
- policy gating
- stage/run diagnostics

## Core Components

- Tool registry: `main_app/services/agent_dashboard/tool_registry.py`
- Workflow registry: `main_app/services/agent_dashboard/workflow_registry.py`
- Stage orchestrator: `main_app/services/agent_dashboard/tool_stage_service.py`
- Asset orchestration service: `main_app/services/agent_dashboard/asset_service.py`
- Artifact adapter: `main_app/services/agent_dashboard/artifact_adapter.py`

## Runtime Contracts

- `AgentAssetResult` is the executor output shape.
- Output is normalized into artifact envelopes (`artifact.sections`, `artifact.metrics`, `artifact.provenance`).
- Tool plugin spec and workflow plugin spec are validated via `plugin_sdk.py`.

## Stage Sequence

Default stage profile (`default_asset_profile` and `media_asset_profile`):

1. `validate_tool_registration`
2. `validate_stage_requirements`
3. `resolve_dependencies`
4. `execute_tool`
5. `normalize_artifact`
6. `validate_schema`
7. `verify_result`
8. `policy_gate_result`
9. `finalize_result`

## Gate Behavior

### Schema

- Implemented in `schema_validation_service.py`
- Uses `main_app/schemas/assets/*.v1.json`
- Controlled by `SCHEMA_VALIDATE_ENFORCE`

### Verification

- Implemented in `verification_service.py`
- Profiles: text / structured / media
- Controlled by `ENABLE_VERIFY_STAGE`

### Policy

- Implemented in `policy_gate_service.py`
- Profiles: text / structured / media policy gates
- Controlled by `ENABLE_POLICY_GATE` + `POLICY_GATE_MODE`

## Dependency Handling

Dependencies are resolved from tool execution specs:

- `requires_artifacts`
- `produces_artifacts`
- `optional_requires`

Registry defaults are filled automatically by intent.

## Concurrency and Retries

Controlled via `runtime_config.py`:

- `MAX_PARALLEL_TOOLS`
- `ENABLE_PARALLEL_DAG`
- `WORKFLOW_FAIL_POLICY`
- `EXECUTE_RETRY_COUNT`
- `EXECUTE_STAGE_TIMEOUT_MS`
- `VERIFY_STAGE_TIMEOUT_MS`

## Diagnostics

Stage diagnostics are captured via stage ledger (`StageLedgerService`) and surfaced in run diagnostics.

Useful outputs:

- stage durations
- retry counts
- per-stage status/error code
- policy/schema/verify summaries in artifact provenance

## Failure Model

On failures, the orchestrator emits normalized error artifacts rather than raw exceptions.  
This ensures downstream UI and history views remain stable even for partial failures.

## Validation Commands

```powershell
python scripts/validate_plugin_specs.py
python scripts/simulate_workflow.py --workflow full_asset_suite --dry
python -m pytest -q tests/test_tool_stage_service.py tests/test_agent_dashboard_service.py
```
