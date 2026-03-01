# Architecture Boundaries

This document describes the current import boundary policy enforced by `scripts/check_import_cycles.py`.

## Why This Exists

The codebase has grown into multiple layers (`ui`, `services`, `platform`, `infrastructure`, `domains`, `orchestration`, etc.).  
Boundary checks prevent accidental tight coupling and keep refactors manageable.

## Layer Rules

Current allowed dependency map (from `scripts/check_import_cycles.py`):

- `app` -> `platform`, `orchestration`, `domains`, `ui`, `shared`, `plugins`, `infrastructure`, `services`
- `ui` -> `platform`, `orchestration`, `domains`, `shared`, `services`
- `orchestration` -> `platform`, `shared`, `plugins`, `services`
- `domains` -> `platform`, `shared`, `services`
- `platform` -> `shared`, `services`
- `plugins` -> `platform`, `orchestration`, `shared`, `services`
- `shared` -> `platform`, `services`
- `infrastructure` -> `platform`, `shared`, `services`
- `services` -> `platform`, `shared`, `plugins`, `infrastructure`, `orchestration`, `domains`
- `parsers` -> `platform`, `shared`, `services`
- `mindmap` -> `platform`, `shared`, `services`
- `schemas` -> `platform`, `shared`, `services`

Always-allowed roots:

- `main_app.constants`
- `main_app.contracts`
- `main_app.models`

## What Is Checked

The script validates:

1. Import cycles across discovered modules
2. Layer boundary violations against the allow-list above

## Commands

Warning mode for boundaries:

```powershell
python scripts/check_import_cycles.py --package main_app --check-boundaries
```

Fail on boundaries:

```powershell
python scripts/check_import_cycles.py --package main_app --check-boundaries --enforce-boundaries
```

## CI Behavior

CI currently runs:

```powershell
python scripts/check_import_cycles.py --package main_app --check-boundaries
```

Cycle issues fail CI. Boundary issues are reported and can be moved to strict mode by adding `--enforce-boundaries`.

## Practical Guidance

- Keep UI-specific logic in `main_app/ui`.
- Keep external API/storage adapters in `main_app/infrastructure`.
- Keep cross-cutting reusable logic in `main_app/shared`.
- Add new domain behavior through `services` + `domains` instead of importing deep UI internals.
