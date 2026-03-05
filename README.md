# Hatched Studio

An end-to-end Streamlit application for generating learning and media assets from a topic using LLM workflows, optional web grounding, and orchestration controls.

## What This Repository Does

This project produces multiple asset types from one input topic:

- Detailed explanation
- Mind map
- Flashcards
- Report
- Data table
- Quiz
- Slideshow
- Video payload + rendered media
- Cartoon shorts payload + dual-format renders
- Audio overview
- Agent-driven multi-tool workflow outputs
- In-app Documentation Center (UI + Debug modes)

It supports both:

- Direct tab-based generation in the UI
- Agent Dashboard orchestration with tool/workflow registries, policy gates, schema checks, and verification

## High-Level Architecture

Core entry path:

1. `app.py` -> `main_app.app.runtime.run_streamlit_app()`
2. Runtime builds storage + dependency container
3. Sidebar builds `GroqSettings` + `WebSourcingSettings`
4. Main tabs render feature-specific generation flows

Primary layers:

- `main_app/ui`: Streamlit tabs/components/session state
- `main_app/services`: business logic and asset generation
- `main_app/platform/web_sourcing`: retrieval, crawl, quality, caching, reliability
- `main_app/services/agent_dashboard`: tool/workflow orchestration and governance
- `main_app/infrastructure`: JSON/Mongo storage adapters + Groq client
- `main_app/schemas/assets`: artifact schema contracts

## End-to-End Runtime Flow

### 1) App Bootstrap

- `run_streamlit_app()` sets Streamlit page config
- Loads storage bundle (`json`, `mongo`, or `auto`)
- Initializes session defaults and observability
- Builds dependency container and tab registrations

### 2) User Input and Settings

Sidebar produces:

- `GroqSettings` (API key, model, temperature, max tokens)
- `WebSourcingSettings` (provider, limits, strict mode, retries, failover)
- enabled tab list

### 3) Asset Generation Paths

- Direct tabs call service classes (`TopicExplainerService`, `QuizService`, `SlideShowService`, `VideoAssetService`, etc.)
- Agent Dashboard uses:
  - `AgentToolRegistry`
  - `AgentWorkflowRegistry`
  - `AgentDashboardAssetService` + stage execution service
  - policy + schema + verification gates

### 4) Grounding and Retrieval

`GlobalGroundingService` merges:

- uploaded document sources
- optional web sources from `WebSourcingOrchestrator`

Web sourcing supports provider selection (`duckduckgo`, `serper`), caching, quality scoring, failover, retries, domain filtering, and diagnostics.

### 5) Persistence

Storage is built by `main_app.infrastructure.storage_factory`:

- JSON files under `.cache/` by default
- Optional MongoDB backend
- Auto migration from JSON -> Mongo when Mongo is enabled and empty

### 6) Output and History

- Asset results are normalized into artifact envelopes
- Quiz/report/video exports are available through dedicated exporters
- Asset history and run/state diagnostics are retained for review

## Project Layout

```text
main_app/
  app/                 # runtime entry and dependency wiring
  ui/                  # tabs, components, session/state helpers
  services/            # generation services and orchestration services
  platform/            # web sourcing, contracts, config, errors
  infrastructure/      # storage and external adapters
  schemas/assets/      # artifact schema JSON contracts
  domains/             # domain-first service/parser adapters
tests/                 # unit/integration/smoke tests
scripts/               # validation, simulation, benchmark tooling
docs/                  # architecture and operational documentation
```

## Quick Start

### Prerequisites

- Python 3.12
- Optional: FFmpeg (recommended for some media export paths)
- Groq API key

### Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements-dev.txt
```

### Run

```powershell
streamlit run app.py
```

## Configuration

### Required for LLM Generation

- `GROQ` key is supplied in-app via sidebar field

### Optional Environment Variables

Storage backend:

- `APP_STORE_BACKEND`: `auto` (default), `json`, or `mongo`
- `MONGODB_URI`
- `MONGODB_DB`
- `MONGODB_COLLECTION_CACHE`
- `MONGODB_COLLECTION_ASSET_HISTORY`
- `MONGODB_COLLECTION_QUIZ_HISTORY`
- `MONGODB_COLLECTION_AGENT_SESSIONS`

Web sourcing:

- `SERPER_API_KEY` (required only when using `serper`)

Orchestration/runtime controls:

- `USE_GENERIC_ASSET_FLOW`
- `ENABLE_VERIFY_STAGE`
- `ENABLE_POLICY_GATE`
- `POLICY_GATE_MODE`
- `SCHEMA_VALIDATE_ENFORCE`
- `MAX_PARALLEL_TOOLS`
- `ENABLE_PARALLEL_DAG`
- `WORKFLOW_FAIL_POLICY`

Observability and telemetry:

- `OBSERVABILITY_OTEL_ENABLED` (`true` by default)
- `OTEL_SERVICE_NAME` (default: `hatched-studio-app`)
- `OTEL_EXPORTER_OTLP_ENDPOINT` (default: `http://localhost:4317`)
- `OTEL_EXPORTER_OTLP_INSECURE` (`true` by default for local stack)
- `OBSERVABILITY_PAYLOAD_CAPTURE_ENABLED` (`true` by default)
- `OBSERVABILITY_PAYLOAD_RETENTION_DAYS` (default: `14`)
- `OBSERVABILITY_PAYLOAD_VAULT_DIR` (default: `.cache/observability_payloads`)
- `OBSERVABILITY_PAYLOAD_ENCRYPTION_ENABLED` (`true` by default)
- `OBSERVABILITY_PAYLOAD_ENCRYPTION_KEY` (optional; if unset, local key file is generated)
- `OBSERVABILITY_PAYLOAD_KEY_FILE` (optional key file location)

## Development Commands

### Tests

```powershell
python -m pytest -q
```

### Lint

```powershell
ruff check .
```

### Type Checks

```powershell
mypy
```

### Plugin and Workflow Validation

```powershell
python scripts/validate_plugin_specs.py
python scripts/simulate_workflow.py --workflow full_asset_suite --dry
```

### Web Sourcing Benchmark

```powershell
python scripts/benchmark_web_sourcing.py --fixture tests/fixtures/web_queries.json --warn-only
```

### Local OTel Stack (Tempo/Loki/Prometheus/Grafana)

```powershell
cd observability
docker compose up -d
```

Grafana URL: `http://localhost:3000` (`admin` / `admin`)

## CI

GitHub workflow (`.github/workflows/ci.yml`) runs:

- plugin schema validation
- workflow simulation dry-run
- `ruff`
- `mypy`
- `pytest`
- web sourcing benchmark
- import cycle / boundary checks

## Documentation Map

- [Architecture Boundaries](docs/ARCHITECTURE_BOUNDARIES.md)
- [Generic Asset Architecture](docs/GENERIC_ASSET_ARCHITECTURE.md)
- [Agent Workflows and Tools](docs/AGENT_WORKFLOWS_AND_TOOLS.md)
- [Agent Asset Service Refactor](docs/AGENT_ASSET_SERVICE_REFACTOR.md)
- [Orchestration State Machine](docs/ORCHESTRATION_STATE_MACHINE.md)
- [Policy Gates](docs/POLICY_GATES.md)
- [Schema Contracts](docs/SCHEMA_CONTRACTS.md)
- [Plugin SDK](docs/PLUGIN_SDK.md)
- [Developer Onboarding Fastpath](docs/DEVELOPER_ONBOARDING_FASTPATH.md)
- [Operations Runbook](docs/OPERATIONS_RUNBOOK.md)
- [Operations Runbook v4](docs/OPERATIONS_RUNBOOK_V4.md)
- [UI Documentation Reference](docs/UI_DOCUMENTATION_REFERENCE.md)
- [Debug Documentation Reference](docs/DEBUG_DOCUMENTATION_REFERENCE.md)
- [Observability Architecture](docs/OBSERVABILITY_ARCHITECTURE.md)
- [Observability Tab Guide](docs/OBSERVABILITY_TAB_GUIDE.md)
- [Observability Debug Cookbook](docs/OBSERVABILITY_DEBUG_COOKBOOK.md)
- [Payload Logging Policy](docs/PAYLOAD_LOGGING_POLICY.md)
- [Mypy Debt Tracker](docs/MYPY_DEBT_TRACKER.md)
- [Migration Guide Folder Restructure](docs/MIGRATION_GUIDE_FOLDER_RESTRUCTURE.md)
- [Video Asset E2E Summary](docs/VIDEO_ASSET_CREATION_E2E_SUMMARY.md)
- [Video Avatar Mode Guide](docs/VIDEO_AVATAR_MODE_GUIDE.md)
- [Cartoon Shorts User Guide](docs/CARTOON_SHORTS_USER_GUIDE.md)
- [Cartoon Shorts Architecture](docs/CARTOON_SHORTS_ARCHITECTURE.md)
- [Cartoon Shorts Debug Runbook](docs/CARTOON_SHORTS_DEBUG_RUNBOOK.md)

## Notes

- `.cache/` is ignored and used for runtime cache/state snapshots.
- Python bytecode (`__pycache__`, `*.pyc`) is ignored and should not be committed.
