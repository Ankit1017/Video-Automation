from __future__ import annotations

import hashlib
import json
from typing import Callable

from main_app.contracts import ArtifactMap, IntentPayload, StageExecutionRecord
from main_app.models import AgentAssetResult, GroqSettings
from main_app.services.agent_dashboard.asset_executor_registry import AgentAssetExecutorRegistry
from main_app.services.agent_dashboard.error_codes import (
    E_DEDUP_SIGNATURE_INVALID,
)
from main_app.services.agent_dashboard.executor_types import AssetExecutionRuntimeContext
from main_app.services.agent_dashboard.runtime_config import execution_dedup_enabled
from main_app.services.agent_dashboard.tool_registry import AgentToolDefinition
from main_app.services.agent_dashboard.tool_stage_service import (
    AgentToolStageOrchestrator,
    ToolStageResult,
)
from main_app.services.intent import IntentRouterService


class AgentToolRunService:
    def __init__(
        self,
        *,
        intent_router: IntentRouterService,
        executor_registry: AgentAssetExecutorRegistry,
        tool_stage_orchestrator: AgentToolStageOrchestrator,
    ) -> None:
        self._intent_router = intent_router
        self._executor_registry = executor_registry
        self._tool_stage_orchestrator = tool_stage_orchestrator

    def run_tool(
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
        run_signature = self.tool_run_signature(
            tool=tool,
            payload=payload,
            available_artifacts=available_artifacts,
        )
        signature_error = ""
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
            executor_registry=self._executor_registry,
            available_artifacts=available_artifacts,
            run_id=run_id,
            queue_wait_ms=queue_wait_ms,
            on_stage_event=on_stage_event,
        )
        if signature_error and asset.status == "success":
            asset.status = "error"
            asset.error = "Dedup signature could not be computed."
        return asset, stage_results

    @staticmethod
    def tool_run_signature(
        *,
        tool: AgentToolDefinition,
        payload: IntentPayload,
        available_artifacts: ArtifactMap,
    ) -> str:
        try:
            payload_blob = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            dependency = tool.execution_spec.get("dependency") if isinstance(tool.execution_spec, dict) else {}
            required_keys = dependency.get("requires_artifacts") if isinstance(dependency, dict) else []
            required_artifacts: dict[str, str] = {}
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
