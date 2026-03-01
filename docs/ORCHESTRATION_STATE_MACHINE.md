# Orchestration State Machine

The run/node state machine is implemented by `OrchestrationStateService`.

## Node States

- `pending`
- `ready`
- `running`
- `completed`
- `failed`
- `blocked`
- `skipped`

## Allowed Transitions

- `pending` -> `ready`, `blocked`, `skipped`
- `ready` -> `running`, `blocked`, `skipped`
- `running` -> `completed`, `failed`
- `blocked` -> `ready`, `skipped`
- `completed` -> terminal
- `failed` -> terminal
- `skipped` -> terminal

Invalid transition returns error code `E_STATE_TRANSITION_INVALID`.

## Dependency Recalculation

`recalculate_blocked(...)` marks nodes as `blocked` when any declared parent is terminal-failed.

This is used with workflow DAG execution where tool dependencies can block downstream tools.

## Execution Context

Higher-level execution services attach additional diagnostic context:

- stage-level records (`StageLedgerService`)
- run-level records (`RunLedgerService`)
- expected stage path and planned state path per tool

## Related Files

- `main_app/services/agent_dashboard/orchestration_state_service.py`
- `main_app/services/agent_dashboard/asset_service.py`
- `main_app/services/agent_dashboard/stage_ledger_service.py`
- `main_app/services/agent_dashboard/run_ledger_service.py`
