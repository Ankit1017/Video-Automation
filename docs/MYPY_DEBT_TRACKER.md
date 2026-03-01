# Mypy Debt Tracker

Tracks static-type debt burn-down for `main_app`.

## Baseline

- Date: 2026-03-01
- Command: `python -m mypy main_app`
- Result: `304 errors in 56 files`

## Ratchet Policy

1. `scripts/mypy_targets.txt` must stay green in CI at all times.
2. New or heavily-edited modules should be added to the target list once clean.
3. Full `mypy main_app` is the final gate for completion.

## Current Ratchet Targets

- `main_app/services/telemetry_service.py`
- `main_app/services/report_export/markdown_renderer.py`
- `main_app/ui/tabs/additional_settings_tab.py`
- `main_app/services/cached_llm_service.py`

## Batch Progress

## PR-1 (CI unblock)
- Status: complete
- Notes:
  - fixed test collection regression in `documentation_tab.py`
  - fixed lint blocker in `asset_service.py`
  - cleaned import hygiene in `cached_llm_service.py`

## PR-2 (mypy governance)
- Status: complete
- Notes:
  - added `scripts/mypy_targets.txt`
  - added `scripts/run_mypy_targets.py`
  - added CI step for ratchet targets

## PR-3 (Batch A)
- Status: complete
- Notes:
  - fixed tracer nullability guard in `telemetry_service.py`
  - fixed regex match narrowing in `markdown_renderer.py`
  - validated target batch with mypy

## Remaining
- Batch B: complete
- Batch C: complete
- Batch D: complete

## Final Status

- Date: 2026-03-01
- Command: `python -m mypy main_app`
- Result: `0 errors in 276 files`

## Validation Snapshot

- `python -m ruff check .` -> pass
- `python -m mypy main_app` -> pass
- `python -m pytest -q` -> `229 passed`
