# Operations Runbook v4

Focused operational profile for teams using full orchestration + web sourcing diagnostics.

## Core Signals

Track these first:

- workflow node state distribution (`completed/failed/blocked/skipped`)
- stage retry counts + timeout incidents
- policy/schema/verify gate failure rate
- web sourcing accepted source count and fallback/failover usage
- cache hit ratio (LLM + web caches)

## Triage Order

1. **Configuration sanity**
   - storage mode, API keys, gate flags
2. **Workflow-level health**
   - which tools failed or blocked
3. **Stage diagnostics**
   - exact failing stage and error code
4. **Artifact provenance**
   - schema/verification/policy summaries
5. **Provider diagnostics**
   - web provider attempts, circuit state, retries

## Recommended Runtime Flags (Stable Defaults)

- `USE_GENERIC_ASSET_FLOW=true`
- `ENABLE_VERIFY_STAGE=true`
- `ENABLE_POLICY_GATE=true`
- `POLICY_GATE_MODE=strict`
- `SCHEMA_VALIDATE_ENFORCE=true`
- `ENABLE_PARALLEL_DAG=true`
- `MAX_PARALLEL_TOOLS=2`
- `WORKFLOW_FAIL_POLICY=continue`

## Common Error Code Buckets

- `E_SCHEMA_VALIDATION_FAILED`
- `E_VERIFY_FAILED`
- `E_POLICY_GATE_FAILED`
- `E_STAGE_TIMEOUT`
- `E_DEPENDENCY_MISSING`
- `E_EXECUTOR_FAILED`
- `E_STATE_TRANSITION_INVALID`

## Fast Recovery Playbook

1. Re-run in dry simulation (`scripts/simulate_workflow.py`) if issue is orchestration shape-related.
2. Run plugin/schema validation script for registry/schema drift.
3. Temporarily switch to `warn_only` policy mode only for triage, not as long-term fix.
4. Fix root cause in schema/tool output, then restore strict settings.
