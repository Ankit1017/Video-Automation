from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from time import perf_counter
from typing import Callable
from uuid import uuid4

from main_app.contracts import (
    ArtifactMap,
    AssetRunSummary,
    OrchestrationState,
    RunLedgerRecord,
    SimulationNodeResult,
    SimulationReport,
    StageDiagnostic,
    StageExecutionRecord,
)
from main_app.models import AgentAssetResult, AgentPlan, GroqSettings
from main_app.services.agent_dashboard.artifact_adapter import collect_produced_artifacts
from main_app.services.agent_dashboard.asset_executor_registry import AgentAssetExecutorRegistry
from main_app.services.agent_dashboard.executor_types import AssetExecutionRuntimeContext
from main_app.services.agent_dashboard.error_codes import (
    E_DEDUP_SIGNATURE_INVALID,
    E_PARALLEL_SCHEDULER_FAILURE,
    E_RUN_LEDGER_WRITE_FAILED,
    E_SIMULATION_INVALID_PLAN,
    E_STATE_TRANSITION_INVALID,
    E_WORKFLOW_CYCLE,
)
from main_app.services.agent_dashboard.orchestration_state_service import OrchestrationStateService
from main_app.services.agent_dashboard.run_ledger_service import RunLedgerService
from main_app.services.agent_dashboard.stage_ledger_service import StageLedgerService
from main_app.services.agent_dashboard.runtime_config import (
    enable_parallel_dag,
    execution_dedup_enabled,
    max_parallel_tools,
    use_generic_asset_flow,
    workflow_fail_policy,
)
from main_app.services.agent_dashboard.tool_registry import (
    AgentToolDefinition,
    AgentToolRegistry,
    build_default_agent_tool_registry,
)
from main_app.services.agent_dashboard.tool_stage_service import (
    AgentToolStageCatalog,
    AgentToolStageOrchestrator,
    ToolStageResult,
    build_default_tool_stage_catalog,
)
from main_app.services.agent_dashboard.workflow_registry import (
    AgentWorkflowDefinition,
    AgentWorkflowRegistry,
    build_default_agent_workflow_registry,
)
from main_app.services.flashcards_service import FlashcardsService
from main_app.services.intent import IntentRouterService
from main_app.services.mind_map_service import MindMapService
from main_app.services.quiz_service import QuizService


class AgentDashboardAssetService:
    def __init__(
        self,
        *,
        intent_router: IntentRouterService,
        asset_executor_registry: AgentAssetExecutorRegistry,
        mind_map_service: MindMapService,
        flashcards_service: FlashcardsService,
        quiz_service: QuizService,
        tool_registry: AgentToolRegistry | None = None,
        workflow_registry: AgentWorkflowRegistry | None = None,
        tool_stage_catalog: AgentToolStageCatalog | None = None,
        tool_stage_orchestrator: AgentToolStageOrchestrator | None = None,
        run_ledger_service: RunLedgerService | None = None,
        stage_ledger_service: StageLedgerService | None = None,
        orchestration_state_service: OrchestrationStateService | None = None,
        on_stage_event: Callable[[StageDiagnostic], None] | None = None,
        on_run_event: Callable[[RunLedgerRecord], None] | None = None,
    ) -> None:
        self._intent_router = intent_router
        self._asset_executor_registry = asset_executor_registry
        self._mind_map_service = mind_map_service
        self._flashcards_service = flashcards_service
        self._quiz_service = quiz_service
        self._tool_registry = tool_registry or build_default_agent_tool_registry()
        self._workflow_registry = workflow_registry or build_default_agent_workflow_registry()
        self._tool_stage_catalog = tool_stage_catalog or build_default_tool_stage_catalog(tool_registry=self._tool_registry)
        self._tool_stage_orchestrator = tool_stage_orchestrator or AgentToolStageOrchestrator(
            stage_catalog=self._tool_stage_catalog
        )
        self._run_ledger_service = run_ledger_service or RunLedgerService()
        self._stage_ledger_service = stage_ledger_service or StageLedgerService()
        self._orchestration_state_service = orchestration_state_service or OrchestrationStateService()
        self._on_stage_event = on_stage_event
        self._on_run_event = on_run_event

    def generate_assets_from_plan(
        self,
        *,
        plan: AgentPlan,
        settings: GroqSettings,
        runtime_context: AssetExecutionRuntimeContext | None = None,
        run_id: str | None = None,
        on_stage_event: Callable[[StageDiagnostic], None] | None = None,
        on_run_event: Callable[[RunLedgerRecord], None] | None = None,
        resume_from_run_id: str | None = None,
        resume_from_tool_key: str | None = None,
    ) -> tuple[list[AgentAssetResult], list[str]]:
        if not self._use_generic_asset_flow():
            return self._generate_assets_from_plan_linear(
                plan=plan,
                settings=settings,
                runtime_context=runtime_context,
                run_id=run_id,
                on_stage_event=on_stage_event,
                on_run_event=on_run_event,
                resume_from_run_id=resume_from_run_id,
                resume_from_tool_key=resume_from_tool_key,
            )
        return self._generate_assets_from_plan_dag(
            plan=plan,
            settings=settings,
            runtime_context=runtime_context,
            run_id=run_id,
            on_stage_event=on_stage_event,
            on_run_event=on_run_event,
            resume_from_run_id=resume_from_run_id,
            resume_from_tool_key=resume_from_tool_key,
        )

    def simulate_plan_execution(
        self,
        plan: AgentPlan,
        *,
        run_id: str | None = None,
    ) -> SimulationReport:
        run_id_value = " ".join(str(run_id or "").split()).strip() or uuid4().hex[:16]
        notes: list[str] = []
        intents = list(plan.intents)
        resolved_tools, unresolved_intents = self._tool_registry.resolve_tools_for_intents(intents)
        workflow = self._workflow_registry.build_plan_selected_workflow(tools=resolved_tools)
        workflow_tools, dag_notes = self._workflow_registry.resolve_workflow_tools_dag(
            workflow=workflow,
            tool_registry=self._tool_registry,
        )
        notes.extend(dag_notes)
        if unresolved_intents:
            notes.append(
                f"[{E_SIMULATION_INVALID_PLAN}] Unsupported intents in plan: "
                + ", ".join(unresolved_intents)
            )

        dependencies = self._dependency_map(tools=workflow_tools)
        order_index = {tool.key: idx for idx, tool in enumerate(workflow_tools)}
        completed: set[str] = set()
        failed: set[str] = set()
        pending = {tool.key for tool in workflow_tools}
        state_paths: dict[str, list[str]] = {tool.key: ["pending"] for tool in workflow_tools}

        nodes_by_key: dict[str, SimulationNodeResult] = {
            tool.key: {
                "tool_key": tool.key,
                "intent": tool.intent,
                "planned_state_path": ["pending"],
                "blocked_by": [],
                "expected_stages": self._expected_stages_for_tool(tool),
            }
            for tool in workflow_tools
        }

        while pending:
            ready = [key for key in pending if all(parent in completed for parent in dependencies.get(key, set()))]
            if not ready:
                for key in sorted(pending, key=lambda item: order_index.get(item, 9999)):
                    blockers = sorted(parent for parent in dependencies.get(key, set()) if parent in failed or parent in pending)
                    path = state_paths[key]
                    if path[-1] != "blocked":
                        path.append("blocked")
                    nodes_by_key[key]["planned_state_path"] = list(path)
                    nodes_by_key[key]["blocked_by"] = blockers
                break
            ready.sort(key=lambda item: (order_index.get(item, 9999), item))
            for key in ready:
                pending.discard(key)
                path = state_paths[key]
                if path[-1] != "ready":
                    path.append("ready")
                path.append("running")
                path.append("completed")
                nodes_by_key[key]["planned_state_path"] = list(path)
                completed.add(key)

        nodes: list[SimulationNodeResult] = [
            nodes_by_key[tool.key]
            for tool in sorted(workflow_tools, key=lambda item: order_index.get(item.key, 9999))
            if tool.key in nodes_by_key
        ]
        return {
            "workflow_key": workflow.key,
            "run_id": run_id_value,
            "nodes": nodes,
            "notes": notes,
        }

    def _generate_assets_from_plan_dag(
        self,
        *,
        plan: AgentPlan,
        settings: GroqSettings,
        runtime_context: AssetExecutionRuntimeContext | None,
        run_id: str | None,
        on_stage_event: Callable[[StageDiagnostic], None] | None,
        on_run_event: Callable[[RunLedgerRecord], None] | None,
        resume_from_run_id: str | None,
        resume_from_tool_key: str | None,
    ) -> tuple[list[AgentAssetResult], list[str]]:
        started_at = _now_iso()
        resume_run_id = " ".join(str(resume_from_run_id or "").split()).strip()
        run_id_value = " ".join(str(run_id or "").split()).strip() or resume_run_id or uuid4().hex[:16]
        notes: list[str] = [f"run_id={run_id_value}"]
        assets: list[AgentAssetResult] = []
        run_summaries: list[AssetRunSummary] = []

        intents = list(plan.intents)
        payloads = dict(plan.payloads)
        resolved_tools, unresolved_intents = self._tool_registry.resolve_tools_for_intents(intents)
        plan_workflow = self._workflow_registry.build_plan_selected_workflow(tools=resolved_tools)
        workflow_tools, dag_notes = self._workflow_registry.resolve_workflow_tools_dag(
            workflow=plan_workflow,
            tool_registry=self._tool_registry,
        )
        for note in dag_notes:
            notes.append(f"[{E_WORKFLOW_CYCLE}] {note}")

        for unresolved_intent in unresolved_intents:
            assets.append(
                AgentAssetResult(
                    intent=unresolved_intent,
                    status="error",
                    error="Unsupported intent.",
                    payload=payloads.get(unresolved_intent, {}),
                )
            )

        if workflow_tools:
            notes.append(
                f"Workflow `{plan_workflow.key}` executed with DAG tools: "
                + ", ".join(tool.intent for tool in workflow_tools)
            )

        order_index = {tool.key: idx for idx, tool in enumerate(workflow_tools)}
        key_to_tool = {tool.key: tool for tool in workflow_tools}
        dependencies = self._dependency_map(tools=workflow_tools)
        pending = {tool.key for tool in workflow_tools}
        completed = self._resume_completed_tool_keys(
            run_id=resume_run_id,
            workflow_tools=workflow_tools,
            resume_from_tool_key=resume_from_tool_key,
        )
        for done_key in sorted(completed, key=lambda key: order_index.get(key, 9999)):
            if done_key in pending:
                pending.remove(done_key)
                notes.append(f"{key_to_tool[done_key].intent}: resumed as already completed in prior run state.")
        tool_states: dict[str, OrchestrationState] = {tool.key: "pending" for tool in workflow_tools}
        for done_key in completed:
            tool_states[done_key] = "completed"

        available_artifacts: ArtifactMap = {}
        executed_signatures: set[str] = set()
        results_by_key: dict[str, tuple[AgentAssetResult, list[ToolStageResult]]] = {}
        queue_started_at = perf_counter()
        stop_due_to_fail_fast = False

        stage_event_sink = self._stage_event_sink(
            workflow_key=plan_workflow.key,
            run_id=run_id_value,
            tool_states=tool_states,
            on_stage_event=on_stage_event,
        )

        parallel_enabled = enable_parallel_dag() and max_parallel_tools() > 1
        parallel_limit = max_parallel_tools()

        while pending:
            ready = [
                key
                for key in pending
                if all(parent in completed for parent in dependencies.get(key, []))
            ]
            for key in ready:
                transition = self._orchestration_state_service.transition(
                    from_state=tool_states.get(key, "pending"),
                    to_state="ready",
                )
                if transition.valid:
                    tool_states[key] = "ready"
            ready.sort(key=lambda key: (order_index.get(key, 9999), key))
            if not ready:
                notes.append(f"[{E_PARALLEL_SCHEDULER_FAILURE}] No schedulable tools remain.")
                break

            if not parallel_enabled:
                selected = ready[:1]
            else:
                selected = ready[:parallel_limit]

            for key in selected:
                run_transition = self._orchestration_state_service.transition(
                    from_state=tool_states.get(key, "ready"),
                    to_state="running",
                )
                if run_transition.valid:
                    tool_states[key] = "running"
                else:
                    notes.append(f"[{E_STATE_TRANSITION_INVALID}] {run_transition.message}")

            batch_results: dict[str, tuple[AgentAssetResult, list[ToolStageResult]]] = {}
            if len(selected) == 1:
                tool = key_to_tool[selected[0]]
                queue_wait_ms = int((perf_counter() - queue_started_at) * 1000)
                batch_results[tool.key] = self._run_tool(
                    tool=tool,
                    payload=payloads.get(tool.intent, {}),
                    settings=settings,
                    runtime_context=runtime_context,
                    available_artifacts=available_artifacts,
                    run_id=run_id_value,
                    queue_wait_ms=queue_wait_ms,
                    on_stage_event=stage_event_sink,
                    executed_signatures=executed_signatures,
                )
            else:
                with ThreadPoolExecutor(max_workers=len(selected)) as executor:
                    futures = {}
                    for key in selected:
                        tool = key_to_tool[key]
                        queue_wait_ms = int((perf_counter() - queue_started_at) * 1000)
                        futures[key] = executor.submit(
                            self._run_tool,
                            tool=tool,
                            payload=payloads.get(tool.intent, {}),
                            settings=settings,
                            runtime_context=runtime_context,
                            available_artifacts=dict(available_artifacts),
                            run_id=run_id_value,
                            queue_wait_ms=queue_wait_ms,
                            on_stage_event=stage_event_sink,
                            executed_signatures=executed_signatures,
                        )
                    for key, future in futures.items():
                        batch_results[key] = future.result()

            for key in selected:
                pending.discard(key)
                completed.add(key)
                tool = key_to_tool[key]
                asset, stage_results = batch_results[key]
                finish_transition = self._orchestration_state_service.transition(
                    from_state=tool_states.get(key, "running"),
                    to_state="completed" if asset.status == "success" else "failed",
                )
                if finish_transition.valid:
                    tool_states[key] = "completed" if asset.status == "success" else "failed"
                else:
                    notes.append(f"[{E_STATE_TRANSITION_INVALID}] {finish_transition.message}")
                results_by_key[key] = (asset, stage_results)
                assets.append(asset)
                self._append_stage_notes(notes=notes, intent=tool.intent, stage_results=stage_results)

                if asset.status == "success" and self._publishable(asset):
                    produced = collect_produced_artifacts(result=asset, execution_spec=tool.execution_spec)
                    for artifact_key, artifact_value in produced.items():
                        available_artifacts[artifact_key] = artifact_value
                elif asset.status == "success":
                    notes.append(f"{tool.intent}: dependency artifacts suppressed due to verify/policy failure.")

                summary: AssetRunSummary = {
                    "run_id": run_id_value,
                    "workflow_key": plan_workflow.key,
                    "tool_key": tool.key,
                    "intent": tool.intent,
                    "status": asset.status,
                    "verification_status": self._verification_status(asset),
                    "retry_count": self._retry_count(asset),
                }
                run_summaries.append(summary)
                if self._workflow_fail_fast() and asset.status == "error":
                    stop_due_to_fail_fast = True
                    notes.append(f"Workflow fail-fast triggered at tool `{tool.key}`.")
            if stop_due_to_fail_fast:
                break

        success_count = sum(1 for asset in assets if asset.status == "success")
        if assets:
            notes.append(f"Generated {success_count}/{len(assets)} assets in chat.")

        ended_at = _now_iso()
        run_record = self._build_run_record(
            run_id=run_id_value,
            workflow_key=plan_workflow.key,
            planner_mode=plan.planner_mode,
            started_at=started_at,
            ended_at=ended_at,
            summaries=run_summaries,
        )
        self._record_run(run_record=run_record, notes=notes, on_run_event=on_run_event)
        notes.append(f"run_summary_count={len(run_summaries)}")
        return assets, notes

    def _generate_assets_from_plan_linear(
        self,
        *,
        plan: AgentPlan,
        settings: GroqSettings,
        runtime_context: AssetExecutionRuntimeContext | None,
        run_id: str | None,
        on_stage_event: Callable[[StageDiagnostic], None] | None,
        on_run_event: Callable[[RunLedgerRecord], None] | None,
        resume_from_run_id: str | None,
        resume_from_tool_key: str | None,
    ) -> tuple[list[AgentAssetResult], list[str]]:
        del resume_from_run_id, resume_from_tool_key
        run_id_value = " ".join(str(run_id or "").split()).strip() or uuid4().hex[:16]
        notes: list[str] = [f"run_id={run_id_value}"]
        assets: list[AgentAssetResult] = []
        run_summaries: list[AssetRunSummary] = []
        started_at = _now_iso()

        intents = list(plan.intents)
        payloads = dict(plan.payloads)
        resolved_tools, unresolved_intents = self._tool_registry.resolve_tools_for_intents(intents)
        plan_workflow = self._workflow_registry.build_plan_selected_workflow(tools=resolved_tools)
        workflow_tools = self._workflow_registry.resolve_workflow_tools(
            workflow=plan_workflow,
            tool_registry=self._tool_registry,
        )

        for unresolved_intent in unresolved_intents:
            assets.append(
                AgentAssetResult(
                    intent=unresolved_intent,
                    status="error",
                    error="Unsupported intent.",
                    payload=payloads.get(unresolved_intent, {}),
                )
            )

        stage_event_sink = self._stage_event_sink(
            workflow_key=plan_workflow.key,
            run_id=run_id_value,
            tool_states={tool.key: "running" for tool in workflow_tools},
            on_stage_event=on_stage_event,
        )

        available_artifacts: ArtifactMap = {}
        executed_signatures: set[str] = set()
        for tool in workflow_tools:
            asset, stage_results = self._run_tool(
                tool=tool,
                payload=payloads.get(tool.intent, {}),
                settings=settings,
                runtime_context=runtime_context,
                available_artifacts=available_artifacts,
                run_id=run_id_value,
                queue_wait_ms=0,
                on_stage_event=stage_event_sink,
                executed_signatures=executed_signatures,
            )
            assets.append(asset)
            self._append_stage_notes(notes=notes, intent=tool.intent, stage_results=stage_results)
            if asset.status == "success" and self._publishable(asset):
                for artifact_key, artifact_value in collect_produced_artifacts(result=asset, execution_spec=tool.execution_spec).items():
                    available_artifacts[artifact_key] = artifact_value
            summary: AssetRunSummary = {
                "run_id": run_id_value,
                "workflow_key": plan_workflow.key,
                "tool_key": tool.key,
                "intent": tool.intent,
                "status": asset.status,
                "verification_status": self._verification_status(asset),
                "retry_count": self._retry_count(asset),
            }
            run_summaries.append(summary)

        success_count = sum(1 for asset in assets if asset.status == "success")
        if assets:
            notes.append(f"Generated {success_count}/{len(assets)} assets in chat.")
        run_record = self._build_run_record(
            run_id=run_id_value,
            workflow_key=plan_workflow.key,
            planner_mode=plan.planner_mode,
            started_at=started_at,
            ended_at=_now_iso(),
            summaries=run_summaries,
        )
        self._record_run(run_record=run_record, notes=notes, on_run_event=on_run_event)
        return assets, notes

    def _run_tool(
        self,
        *,
        tool: AgentToolDefinition,
        payload: dict[str, object],
        settings: GroqSettings,
        runtime_context: AssetExecutionRuntimeContext | None,
        available_artifacts: ArtifactMap,
        run_id: str,
        queue_wait_ms: int,
        on_stage_event: Callable[[StageExecutionRecord], None] | None,
        executed_signatures: set[str],
    ) -> tuple[AgentAssetResult, list[ToolStageResult]]:
        signature_error = ""
        run_signature = self._tool_run_signature(
            tool=tool,
            payload=payload,
            available_artifacts=available_artifacts,
        )
        if not run_signature:
            signature_error = E_DEDUP_SIGNATURE_INVALID
        if execution_dedup_enabled() and run_signature and run_signature in executed_signatures:
            return (
                AgentAssetResult(
                    intent=tool.intent,
                    status="error",
                    payload=payload,
                    error="Skipped duplicate execution in same run.",
                ),
                [],
            )
        if run_signature:
            executed_signatures.add(run_signature)

        asset, stage_results = self._tool_stage_orchestrator.execute_tool(
            tool=tool,
            payload=payload,
            settings=settings,
            runtime_context=runtime_context or AssetExecutionRuntimeContext(),
            intent_router=self._intent_router,
            executor_registry=self._asset_executor_registry,
            available_artifacts=available_artifacts,
            run_id=run_id,
            queue_wait_ms=queue_wait_ms,
            on_stage_event=on_stage_event,
        )
        if signature_error and asset.status == "success":
            asset.status = "error"
            asset.error = "Dedup signature could not be computed."
        return asset, stage_results

    def _stage_event_sink(
        self,
        *,
        workflow_key: str,
        run_id: str,
        tool_states: dict[str, OrchestrationState],
        on_stage_event: Callable[[StageDiagnostic], None] | None,
    ) -> Callable[[StageExecutionRecord], None]:
        sink = on_stage_event or self._on_stage_event

        def _emit(record: StageExecutionRecord) -> None:
            tool_key = str(record.get("tool_key", ""))
            current_state = tool_states.get(tool_key, "running")
            diagnostic: StageDiagnostic = {
                "run_id": run_id,
                "workflow_key": workflow_key,
                "tool_key": tool_key,
                "intent": str(record.get("intent", "")),
                "stage_key": str(record.get("stage_key", "")),
                "attempt": int(record.get("attempt", 1)),
                "status": str(record.get("status", "")),
                "error_code": str(record.get("error_code", "")),
                "message": str(record.get("message", "")),
                "duration_ms": int(record.get("duration_ms", 0)),
                "started_at": str(record.get("started_at", "")),
                "ended_at": str(record.get("ended_at", "")),
                "from_state": current_state,
                "to_state": current_state,
                "transition_valid": True,
            }
            self._stage_ledger_service.record_stage(diagnostic)
            if sink is not None:
                sink(diagnostic)

        return _emit

    @staticmethod
    def _append_stage_notes(*, notes: list[str], intent: str, stage_results: list[ToolStageResult]) -> None:
        for stage_result in stage_results:
            notes.append(
                f"{intent}: stage `{stage_result.stage_key}` -> {stage_result.status} "
                f"(duration_ms={stage_result.duration_ms}, error_code={stage_result.error_code or 'none'}, attempt={stage_result.attempt})"
            )

    @staticmethod
    def _dependency_map(*, tools: list[AgentToolDefinition]) -> dict[str, set[str]]:
        produced_by: dict[str, set[str]] = defaultdict(set)
        for tool in tools:
            dependency = tool.execution_spec.get("dependency") if isinstance(tool.execution_spec, dict) else {}
            produces = dependency.get("produces_artifacts") if isinstance(dependency, dict) else []
            for key in (produces if isinstance(produces, list) else []):
                normalized = " ".join(str(key).split()).strip()
                if normalized:
                    produced_by[normalized].add(tool.key)

        deps: dict[str, set[str]] = {tool.key: set() for tool in tools}
        for tool in tools:
            dependency = tool.execution_spec.get("dependency") if isinstance(tool.execution_spec, dict) else {}
            requires = dependency.get("requires_artifacts") if isinstance(dependency, dict) else []
            for key in (requires if isinstance(requires, list) else []):
                normalized = " ".join(str(key).split()).strip()
                for parent in produced_by.get(normalized, set()):
                    if parent != tool.key:
                        deps[tool.key].add(parent)
        return deps

    @staticmethod
    def _publishable(asset: AgentAssetResult) -> bool:
        if asset.status != "success":
            return False
        artifact = asset.artifact if isinstance(asset.artifact, dict) else {}
        provenance = artifact.get("provenance") if isinstance(artifact.get("provenance"), dict) else {}
        verification = provenance.get("verification") if isinstance(provenance.get("verification"), dict) else {}
        policy_gate = provenance.get("policy_gate") if isinstance(provenance.get("policy_gate"), dict) else {}
        verify_status = " ".join(str(verification.get("status", "passed")).split()).strip().lower()
        policy_status = " ".join(str(policy_gate.get("status", "passed")).split()).strip().lower()
        return verify_status == "passed" and policy_status == "passed"

    @staticmethod
    def _build_run_record(
        *,
        run_id: str,
        workflow_key: str,
        planner_mode: str,
        started_at: str,
        ended_at: str,
        summaries: list[AssetRunSummary],
    ) -> RunLedgerRecord:
        status = "success"
        error_counts: dict[str, int] = {}
        for summary in summaries:
            if " ".join(str(summary.get("status", "")).split()).strip().lower() == "error":
                status = "error"
            intent = " ".join(str(summary.get("intent", "")).split()).strip().lower() or "unknown"
            if " ".join(str(summary.get("status", "")).split()).strip().lower() == "error":
                error_counts[intent] = error_counts.get(intent, 0) + 1
        return {
            "run_id": run_id,
            "workflow_key": workflow_key,
            "planner_mode": planner_mode,
            "status": status,
            "started_at": started_at,
            "ended_at": ended_at,
            "tool_summaries": summaries,
            "error_counts": error_counts,
        }

    def _record_run(
        self,
        *,
        run_record: RunLedgerRecord,
        notes: list[str],
        on_run_event: Callable[[RunLedgerRecord], None] | None,
    ) -> None:
        try:
            self._run_ledger_service.record_run(run_record)
            sink = on_run_event or self._on_run_event
            if sink is not None:
                sink(run_record)
        except (TypeError, ValueError, OSError, RuntimeError, PermissionError) as exc:
            notes.append(f"[{E_RUN_LEDGER_WRITE_FAILED}] run ledger persistence failed: {exc}")

    def explain_mindmap_node(
        self,
        *,
        root_topic: str,
        node_path: str,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        return self._mind_map_service.explain_node(
            root_topic=root_topic,
            node_path=node_path,
            settings=settings,
        )

    def explain_flashcard(
        self,
        *,
        topic: str,
        question: str,
        short_answer: str,
        card_index: int,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        return self._flashcards_service.explain_card(
            topic=topic,
            question=question,
            short_answer=short_answer,
            card_index=card_index,
            settings=settings,
        )

    def get_quiz_hint(
        self,
        *,
        topic: str,
        question: str,
        options: list[str],
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        return self._quiz_service.get_hint(
            topic=topic,
            question=question,
            options=options,
            settings=settings,
        )

    def get_quiz_attempt_feedback(
        self,
        *,
        topic: str,
        question: str,
        options: list[str],
        correct_index: int,
        selected_index: int,
        settings: GroqSettings,
    ) -> tuple[dict[str, str], bool]:
        return self._quiz_service.get_attempt_feedback(
            topic=topic,
            question=question,
            options=options,
            correct_index=correct_index,
            selected_index=selected_index,
            settings=settings,
        )

    def explain_quiz_attempt(
        self,
        *,
        topic: str,
        question: str,
        options: list[str],
        correct_index: int,
        selected_index: int,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        return self._quiz_service.explain_attempt(
            topic=topic,
            question=question,
            options=options,
            correct_index=correct_index,
            selected_index=selected_index,
            settings=settings,
        )

    def extract_primary_topic_from_assets(self, assets: list[AgentAssetResult]) -> str:
        for asset in assets:
            if asset.status != "success":
                continue
            payload = asset.payload or {}
            topic = " ".join(str(payload.get("topic", "")).split()).strip()
            if self._intent_router.is_valid_topic(topic):
                return topic
        return ""

    def list_registered_tools(self) -> list[AgentToolDefinition]:
        return self._tool_registry.list_tools()

    def list_registered_workflows(self) -> list[AgentWorkflowDefinition]:
        workflows = self._workflow_registry.list_workflows()
        tools = self._tool_registry.list_tools()
        workflows.append(self._workflow_registry.build_plan_selected_workflow(tools=tools))
        return workflows

    def list_tool_stage_sequences(self) -> dict[str, list[str]]:
        sequences: dict[str, list[str]] = {}
        for workflow in self._tool_stage_catalog.list_workflows():
            sequences[workflow.tool_key] = list(workflow.stage_keys)
        return sequences

    @staticmethod
    def _use_generic_asset_flow() -> bool:
        return use_generic_asset_flow()

    @staticmethod
    def _verification_status(asset: AgentAssetResult) -> str:
        artifact = asset.artifact if isinstance(asset.artifact, dict) else {}
        provenance = artifact.get("provenance") if isinstance(artifact.get("provenance"), dict) else {}
        verification = provenance.get("verification") if isinstance(provenance.get("verification"), dict) else {}
        return " ".join(str(verification.get("status", "unknown")).split()).strip().lower() or "unknown"

    @staticmethod
    def _retry_count(asset: AgentAssetResult) -> int:
        artifact = asset.artifact if isinstance(asset.artifact, dict) else {}
        metrics = artifact.get("metrics") if isinstance(artifact.get("metrics"), dict) else {}
        try:
            return int(metrics.get("retry_count", 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _workflow_fail_fast() -> bool:
        return workflow_fail_policy() == "fail_fast"

    @staticmethod
    def _tool_run_signature(*, tool: AgentToolDefinition, payload: dict[str, object], available_artifacts: ArtifactMap) -> str:
        try:
            payload_blob = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            dependency = tool.execution_spec.get("dependency") if isinstance(tool.execution_spec, dict) else {}
            required_keys = dependency.get("requires_artifacts") if isinstance(dependency, dict) else []
            required_artifacts = {}
            for key in (required_keys if isinstance(required_keys, list) else []):
                normalized_key = " ".join(str(key).split()).strip()
                if not normalized_key:
                    continue
                if normalized_key in available_artifacts:
                    required_artifacts[normalized_key] = _checksum(available_artifacts[normalized_key])
            artifacts_blob = json.dumps(required_artifacts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            raw = f"{tool.key}|{payload_blob}|{artifacts_blob}"
            return hashlib.sha256(raw.encode("utf-8")).hexdigest()
        except (TypeError, ValueError):
            return ""

    def _resume_completed_tool_keys(
        self,
        *,
        run_id: str,
        workflow_tools: list[AgentToolDefinition],
        resume_from_tool_key: str | None,
    ) -> set[str]:
        normalized_run_id = " ".join(str(run_id).split()).strip()
        if not normalized_run_id:
            return set()
        diagnostics = self._stage_ledger_service.list_by_run(run_id=normalized_run_id)
        completed: set[str] = set()
        for item in diagnostics:
            if not isinstance(item, dict):
                continue
            stage_key = " ".join(str(item.get("stage_key", "")).split()).strip().lower()
            status = " ".join(str(item.get("status", "")).split()).strip().lower()
            tool_key = " ".join(str(item.get("tool_key", "")).split()).strip().lower().replace(" ", "_")
            if stage_key == "finalize_result" and status == "success" and tool_key:
                completed.add(tool_key)
        if not completed:
            return set()
        resume_key = " ".join(str(resume_from_tool_key or "").split()).strip().lower().replace(" ", "_")
        if not resume_key:
            return completed
        order_index = {tool.key: idx for idx, tool in enumerate(workflow_tools)}
        resume_idx = order_index.get(resume_key)
        if resume_idx is None:
            return completed
        return {key for key in completed if order_index.get(key, 999999) < resume_idx}

    def _expected_stages_for_tool(self, tool: AgentToolDefinition) -> list[str]:
        workflow = self._tool_stage_catalog.get(tool.key)
        if workflow is not None:
            return list(workflow.stage_keys)
        stage_profile = (
            " ".join(str(tool.execution_spec.get("stage_profile", "default_asset_profile")).split()).strip().lower()
            if isinstance(tool.execution_spec, dict)
            else "default_asset_profile"
        )
        return list(AgentToolStageOrchestrator.default_stage_sequence(stage_profile))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted((_json_safe(item) for item in value), key=lambda item: str(item))
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _checksum(value: object) -> str:
    blob = json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
