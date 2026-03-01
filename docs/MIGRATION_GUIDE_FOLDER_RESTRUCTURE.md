# Migration Guide: Folder Restructure

This guide captures the current folder strategy and how to migrate legacy imports safely.

## Current Structure (Authoritative)

- `main_app/app` -> runtime/bootstrap/container wiring
- `main_app/ui` -> tab rendering and interaction state
- `main_app/services` -> core business logic/orchestration
- `main_app/platform` -> contracts/config/errors/web sourcing platform features
- `main_app/infrastructure` -> adapters to external systems (Groq, storage)
- `main_app/domains` -> domain-first wrappers and extracted domain services
- `main_app/shared` -> reusable cross-domain helpers

## Migration Strategy

### 1) Keep Runtime Stable

Do not change `app.py` and `main_app/app/runtime.py` behavior while moving internals.

### 2) Move by Layer, Not by File Name

When relocating modules:

- UI logic -> `ui`
- Orchestration logic -> `services/agent_dashboard`
- External adapters -> `infrastructure`
- Reusable utility -> `shared`

### 3) Preserve Public Import Points

If a move is required, keep compatibility wrappers (re-export imports) until callers are migrated.

### 4) Enforce Boundaries During Migration

Run boundary and cycle checks continuously:

```powershell
python scripts/check_import_cycles.py --package main_app --check-boundaries
```

### 5) Validate Tool/Workflow Contracts

```powershell
python scripts/validate_plugin_specs.py
python scripts/simulate_workflow.py --workflow full_asset_suite --dry
```

### 6) Finish with Test Pass

```powershell
python -m pytest -q
ruff check .
mypy
```

## Anti-Patterns to Avoid

- Moving files and silently changing runtime behavior in same commit.
- Adding UI imports deep inside infrastructure modules.
- Skipping compatibility wrappers during multi-step migrations.
- Introducing new asset types without schema + plugin validation updates.

## Definition of Done

- Import cycles: none.
- Boundary check: clean (or known warnings explicitly documented).
- Plugin/schema checks: pass.
- Full tests: pass.
- Docs updated for new paths.
