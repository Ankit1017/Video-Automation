# Agent Asset Service Refactor

This note documents the SOLID-oriented decomposition applied to `AgentDashboardAssetService` while keeping its public API unchanged.

## What Changed

`AgentDashboardAssetService.generate_assets_from_plan(...)` remains the entry point, but key responsibilities are now delegated to focused collaborators:

- `AgentDependencyGraphService`
  - Builds dependency maps from tool execution specs.
  - Resolves expected stage sequences for simulation and diagnostics.

- `AgentToolRunService`
  - Executes one tool run via stage orchestrator.
  - Handles per-run dedup signatures and duplicate skip behavior.

- `AgentRunRecordingService`
  - Emits stage diagnostics, telemetry events, and stage duration metrics.
  - Builds and records run ledger summaries.
  - Centralizes verification/retry/publishability extraction from artifacts.

- `AgentWorkflowExecutionService`
  - Handles ready/running/completed state transitions for DAG scheduling.
  - Encapsulates orchestration-state transition checks and messages.

## Why

This reduces SRP pressure on `AgentDashboardAssetService` and improves extension/testing boundaries without changing existing behavior.

## Compatibility

- No change to user-facing flows.
- No required call-site changes for existing service consumers.
- Existing tests continue to pass with the split.
