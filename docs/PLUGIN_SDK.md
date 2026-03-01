# Plugin SDK

This repo uses lightweight plugin specs for tools and workflows.

## Tool Plugin Spec

Normalized by `normalize_tool_plugin_spec(...)`:

- `plugin_key` (snake_case key)
- `intent` (normalized intent name)
- `title`
- `description`
- `capabilities` (auto-defaulted by intent if omitted)
- `execution_spec` (stage profile, dependencies, policy profile, verify profile)
- `schema_ref`
  - `intent`
  - `version`
  - `id`

Validation:

- `validate_tool_plugin_spec(...)`
- fix hints available through `plugin_spec_fix_hints(...)`

## Workflow Plugin Spec

Validated by `validate_workflow_plugin_spec(...)`:

- `workflow_key`
- `tool_keys`
- optional `tool_dependencies`

## Defaults by Intent

Capability defaults:

- text assets (`topic`, `report`) -> `generative_asset`, `text`
- media assets (`video`, `audio_overview`) -> `generative_asset`, `media`
- others -> `generative_asset`, `structured`

Execution defaults (from tool registry builder):

- verify profile inferred by intent (text/structured/media)
- policy profile inferred by intent
- dependency keys inferred from artifact adapter defaults when omitted

## Validation Script

Use:

```powershell
python scripts/validate_plugin_specs.py
```

What it checks:

1. Tool plugin spec validity
2. Workflow plugin spec validity
3. Schema file existence for each tool spec

## Recommended Workflow for New Tool

1. Add executor/plugin code.
2. Register tool definition in default tool registry.
3. Add schema JSON under `main_app/schemas/assets`.
4. Run `scripts/validate_plugin_specs.py`.
5. Add tests for registry + execution.

## Related Files

- `main_app/services/agent_dashboard/plugin_sdk.py`
- `main_app/services/agent_dashboard/tool_registry.py`
- `main_app/services/agent_dashboard/workflow_registry.py`
- `scripts/validate_plugin_specs.py`
