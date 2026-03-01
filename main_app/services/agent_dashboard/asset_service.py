from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from time import perf_counter
from typing import Callable, ContextManager, Iterator
from uuid import uuid4

from main_app.contracts import (
    ArtifactMap,
    AssetRunSummary,
    IntentPayload,
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
from main_app.services.agent_dashboard.dependency_graph_service import AgentDependencyGraphService
from main_app.services.agent_dashboard.executor_types import AssetExecutionRuntimeContext
from main_app.services.agent_dashboard.error_codes import (
    E_PARALLEL_SCHEDULER_FAILURE,
    E_SIMULATION_INVALID_PLAN,
    E_STATE_TRANSITION_INVALID,
    E_WORKFLOW_CYCLE,
)
from main_app.services.agent_dashboard.orchestration_state_service import OrchestrationStateService
from main_app.services.agent_dashboard.run_ledger_service import RunLedgerService
from main_app.services.agent_dashboard.run_recording_service import AgentRunRecordingService
from main_app.services.agent_dashboard.stage_ledger_service import StageLedgerService
from main_app.services.agent_dashboard.runtime_config import (
    enable_parallel_dag,
    max_parallel_tools,
    use_generic_asset_flow,
    workflow_fail_policy,
)
from main_app.services.agent_dashboard.tool_run_service import AgentToolRunService
from main_app.services.agent_dashboard.workflow_execution_service import AgentWorkflowExecutionService
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
from main_app.services.observability_service import ensure_request_id
from main_app.services.telemetry_service import ObservabilityEvent, TelemetryService
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
        telemetry_service: TelemetryService | None = None,
        dependency_graph_service: AgentDependencyGraphService | None = None,
        tool_run_service: AgentToolRunService | None = None,
        run_recording_service: AgentRunRecordingService | None = None,
        workflow_execution_service: AgentWorkflowExecutionService | None = None,
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
        self._telemetry_service = telemetry_service
        self._dependency_graph_service = dependency_graph_service or AgentDependencyGraphService()
        self._tool_run_service = tool_run_service or AgentToolRunService(
            intent_router=self._intent_router,
            executor_registry=self._asset_executor_registry,
            tool_stage_orchestrator=self._tool_stage_orchestrator,
        )
        self._run_recording_service = run_recording_service or AgentRunRecordingService(
            run_ledger_service=self._run_ledger_service,
            stage_ledger_service=self._stage_ledger_service,
            telemetry_service=self._telemetry_service,
            on_stage_event=self._on_stage_event,
            on_run_event=self._on_run_event,
        )
        self._workflow_execution_service = workflow_execution_service or AgentWorkflowExecutionService(
            orchestration_state_service=self._orchestration_state_service
        )

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
        request_id = ensure_request_id()
        notes: list[str] = [f"run_id={run_id_value}"]
        assets: list[AgentAssetResult] = []
        run_summaries: list[AssetRunSummary] = []

        if self._telemetry_service is not None:
            self._telemetry_service.record_event(
                ObservabilityEvent(
                    event_name="agent.run.start",
                    component="agent_dashboard.asset_service",
                    status="started",
                    timestamp=_now_iso(),
                    attributes={"run_id": run_id_value, "request_id": request_id},
                )
            )

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

        context_scope: ContextManager[object] = (
            self._telemetry_service.context_scope(request_id=request_id, run_id=run_id_value)
            if self._telemetry_service is not None
            else _null_context()
        )
        with context_scope:
            while pending:
                ready = self._workflow_execution_service.resolve_ready_tools(
                    pending=pending,
                    completed=completed,
                    dependencies=dependencies,
                    tool_states=tool_states,
                )
                ready.sort(key=lambda key: (order_index.get(key, 9999), key))
                if not ready:
                    notes.append(f"[{E_PARALLEL_SCHEDULER_FAILURE}] No schedulable tools remain.")
                    break

                if not parallel_enabled:
                    selected = ready[:1]
                else:
                    selected = ready[:parallel_limit]

                for key in selected:
                    transition_error = self._workflow_execution_service.mark_running(tool_key=key, tool_states=tool_states)
                    if transition_error:
                        notes.append(f"[{E_STATE_TRANSITION_INVALID}] {transition_error}")

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
                    transition_error = self._workflow_execution_service.mark_finished(
                        tool_key=key,
                        success=(asset.status == "success"),
                        tool_states=tool_states,
                    )
                    if transition_error:
                        notes.append(f"[{E_STATE_TRANSITION_INVALID}] {transition_error}")
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
        if self._telemetry_service is not None:
            payload_ref = self._telemetry_service.attach_payload(payload=run_record, kind="agent_run_record")
            self._telemetry_service.record_metric(
                name="agent_runs_total",
                value=1.0,
                attrs={
                    "workflow_key": plan_workflow.key,
                    "status": run_record.get("status", "unknown"),
                },
            )
            self._telemetry_service.record_event(
                ObservabilityEvent(
                    event_name="agent.run.end",
                    component="agent_dashboard.asset_service",
                    status=str(run_record.get("status", "unknown")),
                    timestamp=_now_iso(),
                    attributes={
                        "run_id": run_id_value,
                        "workflow_key": plan_workflow.key,
                        "request_id": request_id,
                        "summary_count": len(run_summaries),
                    },
                    payload_ref=payload_ref,
                )
            )
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
        payload: IntentPayload,
        settings: GroqSettings,
        runtime_context: AssetExecutionRuntimeContext | None,
        available_artifacts: ArtifactMap,
        run_id: str,
        queue_wait_ms: int,
        on_stage_event: Callable[[StageExecutionRecord], None] | None,
        executed_signatures: set[str],
    ) -> tuple[AgentAssetResult, list[ToolStageResult]]:
        return self._tool_run_service.run_tool(
            tool=tool,
            payload=payload,
            settings=settings,
            runtime_context=runtime_context,
            available_artifacts=available_artifacts,
            run_id=run_id,
            queue_wait_ms=queue_wait_ms,
            on_stage_event=on_stage_event,
            executed_signatures=executed_signatures,
        )

    def _stage_event_sink(
        self,
        *,
        workflow_key: str,
        run_id: str,
        tool_states: dict[str, OrchestrationState],
        on_stage_event: Callable[[StageDiagnostic], None] | None,
    ) -> Callable[[StageExecutionRecord], None]:
        return self._run_recording_service.stage_event_sink(
            workflow_key=workflow_key,
            run_id=run_id,
            tool_states=tool_states,
            on_stage_event=on_stage_event,
        )

    @staticmethod
    def _append_stage_notes(*, notes: list[str], intent: str, stage_results: list[ToolStageResult]) -> None:
        AgentRunRecordingService.append_stage_notes(notes=notes, intent=intent, stage_results=stage_results)

    def _dependency_map(self, *, tools: list[AgentToolDefinition]) -> dict[str, set[str]]:
        return self._dependency_graph_service.build_dependency_map(tools=tools)

    @staticmethod
    def _publishable(asset: AgentAssetResult) -> bool:
        return AgentRunRecordingService.publishable(asset)

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
        return AgentRunRecordingService.build_run_record(
            run_id=run_id,
            workflow_key=workflow_key,
            planner_mode=planner_mode,
            started_at=started_at,
            ended_at=ended_at,
            summaries=summaries,
        )

    def _record_run(
        self,
        *,
        run_record: RunLedgerRecord,
        notes: list[str],
        on_run_event: Callable[[RunLedgerRecord], None] | None,
    ) -> None:
        self._run_recording_service.record_run(run_record=run_record, notes=notes, on_run_event=on_run_event)

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
        return AgentRunRecordingService.verification_status(asset)

    @staticmethod
    def _retry_count(asset: AgentAssetResult) -> int:
        return AgentRunRecordingService.retry_count(asset)

    @staticmethod
    def _workflow_fail_fast() -> bool:
        return workflow_fail_policy() == "fail_fast"

    @staticmethod
    def _tool_run_signature(*, tool: AgentToolDefinition, payload: IntentPayload, available_artifacts: ArtifactMap) -> str:
        return AgentToolRunService.tool_run_signature(
            tool=tool,
            payload=payload,
            available_artifacts=available_artifacts,
        )

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
        return self._dependency_graph_service.expected_stages_for_tool(tool, stage_catalog=self._tool_stage_catalog)


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


def _as_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _coerce_int(value: object, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        if isinstance(value, (int, float, str)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return default


@contextmanager
def _null_context() -> Iterator[None]:
    yield
