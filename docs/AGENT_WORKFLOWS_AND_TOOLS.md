# Agent Dashboard Workflows and Tools

This file documents the current tool/workflow model used by the Agent Dashboard.

## Tool Inventory (Current)

Default tool intents:

- `topic`
- `mindmap`
- `flashcards`
- `data table`
- `quiz`
- `slideshow`
- `video`
- `audio_overview`
- `report`

Each tool is registered through `build_default_agent_tool_registry()` and includes:

- `plugin_key`
- `intent`
- `execution_spec`
- `schema_ref`
- capability tags

## Workflow Inventory (Current)

Defined in `build_default_agent_workflow_registry()`:

- `core_learning_assets`
  - `topic`, `mindmap`, `flashcards`, `quiz`, `slideshow`
- `media_production_assets`
  - `slideshow`, `video`, `audio_overview`, `report`
  - explicit dependency: `video` depends on `slideshow`
- `full_asset_suite`
  - all tools in catalog order

Generated at runtime:

- `plan_selected_assets`
  - built from active plan intent set
  - dependencies inferred from required/produced artifact keys

## How Plan -> Execution Works

1. Plan produces selected intents + payloads.
2. Tool registry resolves tool specs for intents.
3. Workflow registry builds/loads workflow.
4. DAG order is resolved (explicit + inferred dependencies).
5. Each tool executes through the stage orchestrator.
6. Results are normalized and validated (schema/verify/policy).
7. Final artifacts are persisted and surfaced in UI/history.

## Stage-Level Execution

Per tool stage sequence:

1. validate registration
2. validate payload requirements
3. resolve dependencies
4. execute tool
5. normalize artifact
6. validate schema
7. verify
8. policy gate
9. finalize

See `docs/GENERIC_ASSET_ARCHITECTURE.md` for details.

## Dependency Model

Tool execution specs contain:

- `dependency.requires_artifacts`
- `dependency.produces_artifacts`
- `dependency.optional_requires`

These drive:

- DAG ordering
- runtime dependency blocking/unblocking
- artifact handoff between tools

## Governance Hooks

Integrated gates:

- Schema validation (`schema_validation_service.py`)
- Verification (`verification_service.py`)
- Policy gate (`policy_gate_service.py`)

Gate outcomes are attached to artifact provenance and used to decide final stage success/failure.

## Runtime Controls

Key env controls:

- `MAX_PARALLEL_TOOLS`
- `ENABLE_PARALLEL_DAG`
- `WORKFLOW_FAIL_POLICY`
- `ENABLE_VERIFY_STAGE`
- `ENABLE_POLICY_GATE`
- `POLICY_GATE_MODE`
- `SCHEMA_VALIDATE_ENFORCE`

## Common Developer Tasks

### Add New Tool

1. Add executor implementation/plugin.
2. Add tool definition to default tool registry.
3. Add schema JSON (`main_app/schemas/assets`).
4. Add tests + run plugin validation script.

### Add New Workflow

1. Register workflow in workflow registry.
2. Define `tool_keys` and optional `tool_dependencies`.
3. Dry run simulation script and add tests.

## Validation Commands

```powershell
python scripts/validate_plugin_specs.py
python scripts/simulate_workflow.py --workflow full_asset_suite --dry
python -m pytest -q tests/test_tool_registry.py tests/test_workflow_registry.py tests/test_tool_stage_service.py
```
