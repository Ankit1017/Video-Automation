# Developer Onboarding Fastpath

This is the fastest path to become productive in this repository.

## 1) Environment Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements-dev.txt
```

Run app:

```powershell
streamlit run app.py
```

## 2) Core Navigation

Read these first:

1. `README.md`
2. `main_app/app/runtime.py`
3. `main_app/app/dependency_container.py`
4. `main_app/ui/tabs/main_tabs.py`
5. `main_app/services/agent_dashboard/*` (if touching orchestration)

## 3) Daily Quality Commands

```powershell
ruff check .
mypy
python -m pytest -q
```

## 4) Plugin/Workflow Safety Checks

```powershell
python scripts/validate_plugin_specs.py
python scripts/simulate_workflow.py --workflow full_asset_suite --dry
python scripts/check_import_cycles.py --package main_app --check-boundaries
```

## 5) Web Sourcing Validation

```powershell
python scripts/benchmark_web_sourcing.py --fixture tests/fixtures/web_queries.json --warn-only
```

Use `--enforce` in CI-style gating runs.

## 6) Common Workstreams

### Add a New UI Tab

1. Implement tab renderer under `main_app/ui/tabs`.
2. Register it in `main_app/ui/tabs/main_tabs.py`.
3. Add required services in `main_app/app/dependency_container.py`.
4. Add tests under `tests/`.

### Add a New Agent Tool

1. Add/extend executor plugin under `main_app/services/agent_dashboard/executor_plugins`.
2. Ensure tool is present in `build_default_agent_tool_registry()`.
3. Add schema under `main_app/schemas/assets`.
4. Validate with `scripts/validate_plugin_specs.py`.
5. Add tests for registry + execution + verification.

## 7) Troubleshooting

- `SERPER_API_KEY missing`: switch web provider to `duckduckgo` or set env var.
- Mongo errors: set `APP_STORE_BACKEND=json` to run local without Mongo.
- Import cycles: run `scripts/check_import_cycles.py` and fix nearest boundary break first.
