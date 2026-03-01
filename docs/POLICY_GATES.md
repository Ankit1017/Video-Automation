# Policy Gates

Policy gates run after verification and before finalization in the tool stage pipeline.

## Profiles

Implemented profiles:

- `text_policy_gate`
- `structured_policy_gate`
- `media_policy_gate`

Profile is resolved from `tool.execution_spec.execution_policy.profile`, with safe fallback by intent.

## Runtime Controls

Environment variables:

- `ENABLE_POLICY_GATE` (`true`/`false`)
- `POLICY_GATE_MODE` (`strict` or `warn_only`)

Behavior:

- `strict`: error-severity policy issues fail the stage
- `warn_only`: policy issues are recorded but do not fail execution

## What Is Evaluated

Current checks include:

- text existence and basic marker quality checks for text assets
- presence/shape checks for structured artifacts
- media payload/audio consistency checks for video/audio assets

## Output Shape

Policy result is stored in artifact provenance:

- `artifact.provenance.policy_gate`
  - `status`
  - `profile`
  - `checks_run`
  - `issues`

Issues contain:

- `code`
- `severity`
- `message`
- `path`
- `rule_id`

## Error Codes

Common:

- `E_POLICY_GATE_FAILED`
- `E_POLICY_PROFILE_UNKNOWN`

## Related Files

- `main_app/services/agent_dashboard/policy_gate_service.py`
- `main_app/services/agent_dashboard/tool_stage_service.py`
- `main_app/services/agent_dashboard/runtime_config.py`
