from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Callable, Iterable

from main_app.contracts import ArtifactMap, IntentPayload, StageExecutionRecord
from main_app.models import AgentAssetResult, GroqSettings
from main_app.services.agent_dashboard.artifact_adapter import (
    build_artifact_envelope,
    legacy_result_to_artifact,
    optional_required_artifacts,
    required_artifacts,
)
from main_app.services.agent_dashboard.asset_executor_registry import AgentAssetExecutorRegistry
from main_app.services.agent_dashboard.executor_types import AssetExecutionRuntimeContext
from main_app.services.agent_dashboard.error_codes import (
    E_ARTIFACT_NORMALIZATION_FAILED,
    E_DEPENDENCY_MISSING,
    E_EXECUTOR_FAILED,
    E_PAYLOAD_MISSING_MANDATORY,
    E_PARSE_FAILED,
    E_STAGE_EXCEPTION,
    E_STAGE_TIMEOUT,
    E_TOOL_NOT_REGISTERED,
    E_VERIFY_FAILED,
    E_POLICY_GATE_FAILED,
    E_SCHEMA_VALIDATION_FAILED,
    map_exception_to_error_code,
)
from main_app.services.agent_dashboard.runtime_config import (
    enable_policy_gate,
    enable_verify_stage,
    execute_retry_count,
    execute_stage_timeout_ms,
    verify_stage_timeout_ms,
)
from main_app.services.agent_dashboard.policy_gate_service import (
    evaluate_policy_gate,
    policy_gate_error_message,
    policy_gate_passed,
)
from main_app.services.agent_dashboard.schema_validation_service import (
    schema_validation_error_message,
    schema_validation_passed,
    validate_artifact,
)
from main_app.services.agent_dashboard.tool_registry import AgentToolDefinition, AgentToolRegistry
from main_app.services.agent_dashboard.verification_service import (
    verification_error_message,
    verification_passed,
    verify_asset_result,
)
from main_app.services.intent import IntentRouterService


RequirementCheck = Callable[["ToolStageContext"], tuple[bool, str]]
StageAction = Callable[["ToolStageContext"], "StageActionResult"]


@dataclass(frozen=True)
class ToolStageRequirement:
    key: str
    description: str
    check: RequirementCheck


@dataclass(frozen=True)
class ToolStageDefinition:
    key: str
    title: str
    description: str
    requirements: tuple[ToolStageRequirement, ...]
    action: StageAction


@dataclass
class StageActionResult:
    ok: bool
    message: str
    error_code: str = ""
    retryable: bool = False
    details: dict[str, object] = field(default_factory=dict)


@dataclass
class ToolStageResult:
    stage_key: str
    status: str
    message: str
    error_code: str = ""
    started_at: str = ""
    ended_at: str = ""
    duration_ms: int = 0
    attempt: int = 1
    requirement_messages: list[str] = field(default_factory=list)


@dataclass
class ToolStageContext:
    tool: AgentToolDefinition
    payload: IntentPayload
    settings: GroqSettings
    intent_router: IntentRouterService
    executor_registry: AgentAssetExecutorRegistry
    runtime_context: AssetExecutionRuntimeContext
    available_artifacts: ArtifactMap
    validated_tool: bool = False
    payload_valid: bool = False
    dependencies_resolved: bool = False
    schema_valid: bool = False
    verified: bool = False
    policy_passed: bool = False
    stage_profile: str = "default_asset_profile"
    run_id: str = ""
    queue_wait_ms: int = 0
    input_artifacts: ArtifactMap = field(default_factory=dict)
    execution_trace: list[dict[str, str]] = field(default_factory=list)
    asset_result: AgentAssetResult | None = None


@dataclass(frozen=True)
class AgentToolStageWorkflow:
    tool_key: str
    stage_keys: tuple[str, ...]


class AgentToolStageCatalog:
    def __init__(self, workflows: Iterable[AgentToolStageWorkflow] | None = None) -> None:
        self._workflows: dict[str, AgentToolStageWorkflow] = {}
        for workflow in workflows or []:
            self.register(workflow)

    def register(self, workflow: AgentToolStageWorkflow) -> None:
        key = " ".join(str(workflow.tool_key).split()).strip().lower().replace(" ", "_")
        stage_keys = tuple(" ".join(str(item).split()).strip().lower() for item in workflow.stage_keys if str(item).strip())
        if not key or not stage_keys:
            return
        self._workflows[key] = AgentToolStageWorkflow(tool_key=key, stage_keys=stage_keys)

    def get(self, tool_key: str) -> AgentToolStageWorkflow | None:
        key = " ".join(str(tool_key).split()).strip().lower().replace(" ", "_")
        return self._workflows.get(key)

    def list_workflows(self) -> list[AgentToolStageWorkflow]:
        return [self._workflows[key] for key in sorted(self._workflows.keys())]


class AgentToolStageOrchestrator:
    _DEFAULT_STAGE_PROFILES: dict[str, tuple[str, ...]] = {
        "default_asset_profile": (
            "validate_tool_registration",
            "validate_stage_requirements",
            "resolve_dependencies",
            "execute_tool",
            "normalize_artifact",
            "validate_schema",
            "verify_result",
            "policy_gate_result",
            "finalize_result",
        ),
        "media_asset_profile": (
            "validate_tool_registration",
            "validate_stage_requirements",
            "resolve_dependencies",
            "execute_tool",
            "normalize_artifact",
            "validate_schema",
            "verify_result",
            "policy_gate_result",
            "finalize_result",
        ),
    }

    def __init__(self, stage_catalog: AgentToolStageCatalog | None = None) -> None:
        self._stage_catalog = stage_catalog or AgentToolStageCatalog()
        self._stage_definitions = self._build_stage_definitions()

    @staticmethod
    def _build_stage_definitions() -> dict[str, ToolStageDefinition]:
        return {
            "validate_tool_registration": ToolStageDefinition(
                key="validate_tool_registration",
                title="Validate Tool Registration",
                description="Ensures tool intent is mapped to a registered executor.",
                requirements=(
                    ToolStageRequirement(
                        key="intent_present",
                        description="Tool intent must be present.",
                        check=lambda context: (
                            bool(" ".join(str(context.tool.intent).split()).strip()),
                            "Tool intent is missing." if not bool(" ".join(str(context.tool.intent).split()).strip()) else "",
                        ),
                    ),
                ),
                action=AgentToolStageOrchestrator._stage_validate_tool_registration,
            ),
            "validate_stage_requirements": ToolStageDefinition(
                key="validate_stage_requirements",
                title="Validate Payload Requirements",
                description="Checks mandatory requirement fields for tool payload.",
                requirements=(
                    ToolStageRequirement(
                        key="payload_is_mapping",
                        description="Tool payload must be a dictionary.",
                        check=lambda context: (
                            isinstance(context.payload, dict),
                            "Tool payload is invalid." if not isinstance(context.payload, dict) else "",
                        ),
                    ),
                    ToolStageRequirement(
                        key="tool_registration_validated",
                        description="Tool registration must be validated before payload checks.",
                        check=lambda context: (
                            bool(context.validated_tool),
                            "Tool registration stage did not pass." if not context.validated_tool else "",
                        ),
                    ),
                ),
                action=AgentToolStageOrchestrator._stage_validate_payload_requirements,
            ),
            "resolve_dependencies": ToolStageDefinition(
                key="resolve_dependencies",
                title="Resolve Dependencies",
                description="Verifies required artifact dependencies for this tool.",
                requirements=(
                    ToolStageRequirement(
                        key="payload_validated",
                        description="Payload requirements must be satisfied.",
                        check=lambda context: (
                            bool(context.payload_valid),
                            "Payload requirements are not satisfied." if not context.payload_valid else "",
                        ),
                    ),
                ),
                action=AgentToolStageOrchestrator._stage_resolve_dependencies,
            ),
            "execute_tool": ToolStageDefinition(
                key="execute_tool",
                title="Execute Tool",
                description="Runs the mapped executor for the tool intent.",
                requirements=(
                    ToolStageRequirement(
                        key="dependencies_resolved",
                        description="Required dependencies must be resolved.",
                        check=lambda context: (
                            bool(context.dependencies_resolved),
                            "Dependencies are not resolved." if not context.dependencies_resolved else "",
                        ),
                    ),
                ),
                action=AgentToolStageOrchestrator._stage_execute_tool,
            ),
            "normalize_artifact": ToolStageDefinition(
                key="normalize_artifact",
                title="Normalize Artifact",
                description="Normalizes output into the generic artifact envelope.",
                requirements=(
                    ToolStageRequirement(
                        key="execution_result_present",
                        description="Tool execution must produce a result before normalization.",
                        check=lambda context: (
                            context.asset_result is not None,
                            "Tool execution did not produce any result." if context.asset_result is None else "",
                        ),
                    ),
                ),
                action=AgentToolStageOrchestrator._stage_normalize_artifact,
            ),
            "validate_schema": ToolStageDefinition(
                key="validate_schema",
                title="Validate Schema",
                description="Validates normalized artifact against intent schema contract.",
                requirements=(
                    ToolStageRequirement(
                        key="artifact_present_for_schema",
                        description="Artifact must be present before schema validation.",
                        check=lambda context: (
                            context.asset_result is not None and isinstance(context.asset_result.artifact, dict),
                            "Artifact is missing for schema validation."
                            if context.asset_result is None or not isinstance(context.asset_result.artifact, dict)
                            else "",
                        ),
                    ),
                ),
                action=AgentToolStageOrchestrator._stage_validate_schema,
            ),
            "verify_result": ToolStageDefinition(
                key="verify_result",
                title="Verify Result",
                description="Runs strict verification checks against normalized asset output.",
                requirements=(
                    ToolStageRequirement(
                        key="artifact_present_for_verify",
                        description="Artifact must be present before verification.",
                        check=lambda context: (
                            context.asset_result is not None and isinstance(context.asset_result.artifact, dict),
                            "Artifact is missing for verification."
                            if context.asset_result is None or not isinstance(context.asset_result.artifact, dict)
                            else "",
                        ),
                    ),
                ),
                action=AgentToolStageOrchestrator._stage_verify_result,
            ),
            "finalize_result": ToolStageDefinition(
                key="finalize_result",
                title="Finalize Result",
                description="Normalizes final output fields for tool result.",
                requirements=(
                    ToolStageRequirement(
                        key="execution_result_present",
                        description="Tool execution must produce a result before finalization.",
                        check=lambda context: (
                            context.asset_result is not None,
                            "Tool execution did not produce any result." if context.asset_result is None else "",
                        ),
                    ),
                    ToolStageRequirement(
                        key="schema_valid_or_warn_mode",
                        description="Schema must validate before verification when enforcement is enabled.",
                        check=lambda context: (
                            bool(context.schema_valid),
                            "Schema validation did not pass for this tool." if not bool(context.schema_valid) else "",
                        ),
                    ),
                    ToolStageRequirement(
                        key="policy_gate_completed_or_disabled",
                        description="Policy gate must pass when policy gate is enabled.",
                        check=lambda context: (
                            (not AgentToolStageOrchestrator._policy_gate_enabled())
                            or bool(context.policy_passed),
                            "Policy gate did not pass for this tool."
                            if AgentToolStageOrchestrator._policy_gate_enabled() and not bool(context.policy_passed)
                            else "",
                        ),
                    ),
                    ToolStageRequirement(
                        key="verification_completed_or_disabled",
                        description="Verification must pass when verification is enabled and required.",
                        check=lambda context: (
                            (not AgentToolStageOrchestrator._verify_stage_enabled())
                            or (not bool(context.tool.execution_spec.get("verify_required", True)))
                            or bool(context.verified),
                            "Verification did not pass for this tool."
                            if AgentToolStageOrchestrator._verify_stage_enabled()
                            and bool(context.tool.execution_spec.get("verify_required", True))
                            and not bool(context.verified)
                            else "",
                        ),
                    ),
                ),
                action=AgentToolStageOrchestrator._stage_finalize_result,
            ),
            "policy_gate_result": ToolStageDefinition(
                key="policy_gate_result",
                title="Policy Gate Result",
                description="Runs governance and quality policy checks against normalized output.",
                requirements=(
                    ToolStageRequirement(
                        key="artifact_present_for_policy",
                        description="Artifact must be present before policy checks.",
                        check=lambda context: (
                            context.asset_result is not None and isinstance(context.asset_result.artifact, dict),
                            "Artifact is missing for policy gate."
                            if context.asset_result is None or not isinstance(context.asset_result.artifact, dict)
                            else "",
                        ),
                    ),
                ),
                action=AgentToolStageOrchestrator._stage_policy_gate_result,
            ),
        }

    def execute_tool(
        self,
        *,
        tool: AgentToolDefinition,
        payload: IntentPayload,
        settings: GroqSettings,
        runtime_context: AssetExecutionRuntimeContext | None = None,
        intent_router: IntentRouterService,
        executor_registry: AgentAssetExecutorRegistry,
        available_artifacts: ArtifactMap | None = None,
        run_id: str = "",
        queue_wait_ms: int = 0,
        on_stage_event: Callable[[StageExecutionRecord], None] | None = None,
    ) -> tuple[AgentAssetResult, list[ToolStageResult]]:
        stage_profile = (
            " ".join(str(tool.execution_spec.get("stage_profile", "default_asset_profile")).split()).strip().lower()
            if isinstance(tool.execution_spec, dict)
            else "default_asset_profile"
        )
        context = ToolStageContext(
            tool=tool,
            payload=payload,
            settings=settings,
            runtime_context=runtime_context or AssetExecutionRuntimeContext(),
            intent_router=intent_router,
            executor_registry=executor_registry,
            available_artifacts=dict(available_artifacts or {}),
            stage_profile=stage_profile or "default_asset_profile",
            run_id=" ".join(str(run_id).split()).strip(),
            queue_wait_ms=max(0, int(queue_wait_ms)),
        )
        stage_results: list[ToolStageResult] = []

        stage_workflow = self._stage_catalog.get(tool.key)
        if stage_workflow is not None:
            sequence = stage_workflow.stage_keys
        else:
            sequence = self._DEFAULT_STAGE_PROFILES.get(context.stage_profile, self._DEFAULT_STAGE_PROFILES["default_asset_profile"])

        for stage_key in sequence:
            stage = self._stage_definitions.get(stage_key)
            if stage is None:
                stage_results.append(
                    ToolStageResult(
                        stage_key=stage_key,
                        status="error",
                        message=f"Unknown stage `{stage_key}`.",
                    )
                )
                return (
                    self._fallback_error_result(
                        tool=tool,
                        payload=payload,
                        message=f"Unknown stage `{stage_key}`.",
                        run_id=context.run_id,
                    ),
                    stage_results,
                )

            requirement_messages: list[str] = []
            failed_requirement = False
            for requirement in stage.requirements:
                ok, message = requirement.check(context)
                if ok:
                    requirement_messages.append(f"{requirement.key}: ok")
                    continue
                failed_requirement = True
                detail = message or f"Requirement `{requirement.key}` failed."
                requirement_messages.append(f"{requirement.key}: {detail}")
            if failed_requirement:
                failure_message = f"Stage `{stage.key}` requirement check failed."
                started_at = _now_iso()
                ended_at = _now_iso()
                stage_results.append(
                    ToolStageResult(
                        stage_key=stage.key,
                        status="error",
                        message=failure_message,
                        error_code=E_STAGE_EXCEPTION,
                        started_at=started_at,
                        ended_at=ended_at,
                        duration_ms=0,
                        requirement_messages=requirement_messages,
                    )
                )
                if on_stage_event is not None:
                    on_stage_event(
                        StageExecutionRecord(
                            run_id=context.run_id,
                            tool_key=context.tool.key,
                            intent=context.tool.intent,
                            stage_key=stage.key,
                            attempt=1,
                            status="error",
                            started_at=started_at,
                            ended_at=ended_at,
                            duration_ms=0,
                            error_code=E_STAGE_EXCEPTION,
                            message=failure_message,
                        )
                    )
                context.execution_trace.append(
                    {
                        "stage": stage.key,
                        "status": "error",
                        "message": failure_message,
                        "error_code": E_STAGE_EXCEPTION,
                        "started_at": started_at,
                        "ended_at": ended_at,
                        "duration_ms": "0",
                        "attempt": "1",
                    }
                )
                if context.asset_result is None:
                    context.asset_result = self._fallback_error_result(
                        tool=tool,
                        payload=payload,
                        message=failure_message + " " + "; ".join(requirement_messages),
                        run_id=context.run_id,
                    )
                return context.asset_result, stage_results

            max_attempts = 1
            if stage.key == "execute_tool":
                max_attempts = max(1, self._execute_max_attempts(context.tool))
            final_action_result: StageActionResult | None = None
            for attempt in range(1, max_attempts + 1):
                started_at = _now_iso()
                started_counter = perf_counter()
                try:
                    action_result = stage.action(context)
                except (AttributeError, KeyError, TypeError, ValueError, RuntimeError, OSError, TimeoutError) as exc:
                    action_result = StageActionResult(
                        ok=False,
                        message=f"Stage `{stage.key}` failed with exception: {exc}",
                        error_code=map_exception_to_error_code(exc),
                        retryable=(stage.key == "execute_tool"),
                        details={"exception": str(exc)},
                    )
                duration_ms = int((perf_counter() - started_counter) * 1000)
                ended_at = _now_iso()
                timeout_ms = self._stage_timeout_ms(stage.key, context.tool)
                if timeout_ms > 0 and duration_ms > timeout_ms:
                    action_result = StageActionResult(
                        ok=False,
                        message=f"Stage `{stage.key}` timed out after {duration_ms}ms (budget {timeout_ms}ms).",
                        error_code=E_STAGE_TIMEOUT,
                        retryable=(stage.key == "execute_tool"),
                        details={"duration_ms": duration_ms, "timeout_ms": timeout_ms},
                    )

                stage_result = ToolStageResult(
                    stage_key=stage.key,
                    status="success" if action_result.ok else "error",
                    message=action_result.message,
                    error_code=action_result.error_code,
                    started_at=started_at,
                    ended_at=ended_at,
                    duration_ms=duration_ms,
                    attempt=attempt,
                    requirement_messages=requirement_messages,
                )
                stage_results.append(stage_result)
                if on_stage_event is not None:
                    on_stage_event(
                        StageExecutionRecord(
                            run_id=context.run_id,
                            tool_key=context.tool.key,
                            intent=context.tool.intent,
                            stage_key=stage.key,
                            attempt=attempt,
                            status=stage_result.status,
                            started_at=started_at,
                            ended_at=ended_at,
                            duration_ms=duration_ms,
                            error_code=action_result.error_code,
                            message=action_result.message,
                        )
                    )
                context.execution_trace.append(
                    {
                        "stage": stage.key,
                        "status": stage_result.status,
                        "message": action_result.message,
                        "error_code": action_result.error_code,
                        "started_at": started_at,
                        "ended_at": ended_at,
                        "duration_ms": str(duration_ms),
                        "attempt": str(attempt),
                    }
                )
                final_action_result = action_result
                if action_result.ok:
                    break
                if not action_result.retryable or attempt >= max_attempts:
                    break

            if final_action_result is None:
                final_action_result = StageActionResult(ok=False, message=f"Stage `{stage.key}` produced no action result.")

            if not final_action_result.ok:
                if context.asset_result is None or context.asset_result.status != "error":
                    context.asset_result = self._error_result(
                        tool=tool,
                        payload=payload,
                        code=(
                            " ".join(str(final_action_result.error_code).split()).strip().upper()
                            or E_STAGE_EXCEPTION
                        ),
                        stage_key=stage.key,
                        message=final_action_result.message or f"Stage `{stage.key}` failed.",
                        details=dict(final_action_result.details),
                        run_id=context.run_id,
                    )
                return context.asset_result, stage_results

        if context.asset_result is None:
            context.asset_result = self._fallback_error_result(
                tool=tool,
                payload=payload,
                message="No result generated by tool stages.",
                run_id=context.run_id,
            )
        return context.asset_result, stage_results

    @staticmethod
    def _stage_validate_tool_registration(context: ToolStageContext) -> StageActionResult:
        intent = " ".join(str(context.tool.intent).split()).strip().lower()
        if not context.executor_registry.has_intent(intent):
            context.asset_result = AgentToolStageOrchestrator._error_result(
                tool=context.tool,
                payload=context.payload,
                code=E_TOOL_NOT_REGISTERED,
                stage_key="validate_tool_registration",
                message="Unsupported intent.",
                details={"intent": intent},
                run_id=context.run_id,
            )
            return StageActionResult(
                ok=False,
                message=f"No executor registered for intent `{intent}`.",
                error_code=E_TOOL_NOT_REGISTERED,
                retryable=False,
            )
        context.validated_tool = True
        return StageActionResult(ok=True, message="Tool registration validated.")

    @staticmethod
    def _stage_validate_payload_requirements(context: ToolStageContext) -> StageActionResult:
        mandatory_missing, _ = context.intent_router.evaluate_requirements(
            intent=context.tool.intent,
            payload=context.payload,
        )
        if mandatory_missing:
            context.asset_result = AgentToolStageOrchestrator._error_result(
                tool=context.tool,
                payload=context.payload,
                code=E_PAYLOAD_MISSING_MANDATORY,
                stage_key="validate_stage_requirements",
                message=f"Mandatory requirements missing: {', '.join(mandatory_missing)}",
                details={"missing_mandatory": mandatory_missing},
                run_id=context.run_id,
            )
            return StageActionResult(
                ok=False,
                message=f"Missing mandatory fields: {', '.join(mandatory_missing)}",
                error_code=E_PAYLOAD_MISSING_MANDATORY,
                retryable=False,
            )
        context.payload_valid = True
        return StageActionResult(ok=True, message="Payload requirements validated.")

    @staticmethod
    def _stage_resolve_dependencies(context: ToolStageContext) -> StageActionResult:
        required = required_artifacts(context.tool.execution_spec)
        optional = optional_required_artifacts(context.tool.execution_spec)
        missing = [key for key in required if key not in context.available_artifacts]
        if missing:
            error_message = "Missing required dependency artifacts: " + ", ".join(missing)
            context.asset_result = AgentToolStageOrchestrator._error_result(
                tool=context.tool,
                payload=context.payload,
                code=E_DEPENDENCY_MISSING,
                stage_key="resolve_dependencies",
                message=error_message,
                details={"missing": missing, "required": required},
                run_id=context.run_id,
            )
            return StageActionResult(
                ok=False,
                message=error_message,
                error_code=E_DEPENDENCY_MISSING,
                retryable=False,
            )

        context.input_artifacts = {
            key: context.available_artifacts[key]
            for key in required + optional
            if key in context.available_artifacts
        }
        context.dependencies_resolved = True
        if not required and not optional:
            return StageActionResult(ok=True, message="No dependency artifacts required.")
        return StageActionResult(ok=True, message="Dependency artifacts resolved.")

    @staticmethod
    def _stage_execute_tool(context: ToolStageContext) -> StageActionResult:
        result = context.executor_registry.execute(
            intent=context.tool.intent,
            payload=context.payload,
            settings=context.settings,
            runtime_context=context.runtime_context,
        )
        context.asset_result = result
        if result.status == "success":
            return StageActionResult(ok=True, message="Tool executor completed successfully.")
        if not result.error:
            result.error = "Tool executor returned an error."
        if result.artifact is None:
            result.artifact = build_artifact_envelope(
                intent=context.tool.intent,
                title=context.tool.title,
                summary=result.error,
                sections=[
                    AgentToolStageOrchestrator._error_section(
                        code=E_EXECUTOR_FAILED,
                        stage_key="execute_tool",
                        message=result.error,
                        details={"intent": context.tool.intent},
                    )
                ],
                metrics={"cache_hit": False},
                provenance={"stage": "execute_tool"},
            )
        provenance = result.artifact.get("provenance", {}) if isinstance(result.artifact, dict) else {}
        error_code = " ".join(str(provenance.get("error_code", E_EXECUTOR_FAILED)).split()).strip().upper()
        return StageActionResult(
            ok=False,
            message=result.error or "Tool executor returned an error.",
            error_code=error_code or E_EXECUTOR_FAILED,
            retryable=error_code not in {E_PARSE_FAILED},
        )

    @staticmethod
    def _stage_normalize_artifact(context: ToolStageContext) -> StageActionResult:
        if context.asset_result is None:
            return StageActionResult(ok=False, message="No execution result to normalize.", error_code=E_ARTIFACT_NORMALIZATION_FAILED)
        try:
            if context.asset_result.artifact is None:
                context.asset_result.artifact = legacy_result_to_artifact(context.asset_result)
        except (TypeError, ValueError, KeyError) as exc:
            message = f"Artifact normalization failed: {exc}"
            context.asset_result = AgentToolStageOrchestrator._error_result(
                tool=context.tool,
                payload=context.payload,
                code=E_ARTIFACT_NORMALIZATION_FAILED,
                stage_key="normalize_artifact",
                message=message,
                details={"exception": str(exc)},
                run_id=context.run_id,
            )
            return StageActionResult(
                ok=False,
                message=message,
                error_code=E_ARTIFACT_NORMALIZATION_FAILED,
                retryable=False,
            )

        artifact = context.asset_result.artifact or {}
        provenance = artifact.get("provenance") if isinstance(artifact.get("provenance"), dict) else {}
        provenance["tool_key"] = context.tool.key
        provenance["intent"] = context.tool.intent
        provenance["stage_profile"] = context.stage_profile
        provenance["trace"] = [dict(item) for item in context.execution_trace]
        artifact["provenance"] = provenance

        metrics = artifact.get("metrics") if isinstance(artifact.get("metrics"), dict) else {}
        metrics.setdefault("cache_hit", bool(context.asset_result.cache_hit))
        stage_durations_ms: dict[str, int] = {}
        attempt_durations_ms: dict[str, list[int]] = {}
        total_duration_ms = 0
        retry_count = 0
        for item in context.execution_trace:
            if not isinstance(item, dict):
                continue
            stage_key = " ".join(str(item.get("stage", "")).split()).strip().lower()
            duration_raw = " ".join(str(item.get("duration_ms", "0")).split()).strip()
            attempt_raw = " ".join(str(item.get("attempt", "1")).split()).strip()
            try:
                duration = int(duration_raw)
            except (TypeError, ValueError):
                duration = 0
            try:
                attempt = int(attempt_raw)
            except (TypeError, ValueError):
                attempt = 1
            if stage_key:
                stage_durations_ms[stage_key] = stage_durations_ms.get(stage_key, 0) + max(0, duration)
                durations = attempt_durations_ms.get(stage_key, [])
                durations.append(max(0, duration))
                attempt_durations_ms[stage_key] = durations
            total_duration_ms += max(0, duration)
            retry_count += max(0, attempt - 1)
        metrics["stage_durations_ms"] = stage_durations_ms
        metrics["attempt_durations_ms"] = attempt_durations_ms
        metrics["total_duration_ms"] = total_duration_ms
        metrics["retry_count"] = retry_count
        metrics["queue_wait_ms"] = max(0, int(context.queue_wait_ms))
        metrics.setdefault("policy_enforced", bool(AgentToolStageOrchestrator._policy_gate_enabled()))
        artifact["metrics"] = metrics
        context.asset_result.artifact = artifact
        return StageActionResult(ok=True, message="Result artifact normalized.")

    @staticmethod
    def _stage_validate_schema(context: ToolStageContext) -> StageActionResult:
        if context.asset_result is None:
            return StageActionResult(ok=False, message="No execution result to schema-validate.", error_code=E_SCHEMA_VALIDATION_FAILED)
        schema_ref = context.tool.schema_ref if isinstance(context.tool.schema_ref, dict) else {}
        summary = validate_artifact(
            intent=context.tool.intent,
            artifact=context.asset_result.artifact if isinstance(context.asset_result.artifact, dict) else None,
            schema_ref=schema_ref,
        )
        artifact = context.asset_result.artifact if isinstance(context.asset_result.artifact, dict) else {}
        provenance = artifact.get("provenance") if isinstance(artifact.get("provenance"), dict) else {}
        provenance["schema_validation"] = summary
        artifact["provenance"] = provenance
        context.asset_result.artifact = artifact
        if schema_validation_passed(summary):
            context.schema_valid = True
            return StageActionResult(ok=True, message="Schema validation passed.")
        context.asset_result.status = "error"
        context.asset_result.error = schema_validation_error_message(summary)
        sections = artifact.get("sections") if isinstance(artifact.get("sections"), list) else []
        sections.append(
            AgentToolStageOrchestrator._error_section(
                code=E_SCHEMA_VALIDATION_FAILED,
                stage_key="validate_schema",
                message=context.asset_result.error,
                details={"schema_validation": summary},
            )
        )
        artifact["sections"] = sections
        context.asset_result.artifact = artifact
        return StageActionResult(ok=False, message=context.asset_result.error, error_code=E_SCHEMA_VALIDATION_FAILED, retryable=False)

    @staticmethod
    def _stage_verify_result(context: ToolStageContext) -> StageActionResult:
        if context.asset_result is None:
            return StageActionResult(ok=False, message="No execution result to verify.", error_code=E_VERIFY_FAILED)
        if not AgentToolStageOrchestrator._verify_stage_enabled():
            context.verified = True
            return StageActionResult(ok=True, message="Verification skipped by configuration.")
        if not bool(context.tool.execution_spec.get("verify_required", True)):
            context.verified = True
            return StageActionResult(ok=True, message="Verification skipped for tool.")

        summary = verify_asset_result(result=context.asset_result, tool=context.tool)
        artifact = context.asset_result.artifact if isinstance(context.asset_result.artifact, dict) else {}
        provenance = artifact.get("provenance") if isinstance(artifact.get("provenance"), dict) else {}
        provenance["verification"] = summary
        artifact["provenance"] = provenance
        metrics = artifact.get("metrics") if isinstance(artifact.get("metrics"), dict) else {}
        issues = summary.get("issues", [])
        metrics["verification_issue_count"] = len(issues) if isinstance(issues, list) else 0
        artifact["metrics"] = metrics
        context.asset_result.artifact = artifact

        if verification_passed(summary):
            context.verified = True
            return StageActionResult(ok=True, message="Verification passed.")

        message = verification_error_message(summary)
        context.asset_result.status = "error"
        context.asset_result.error = message
        sections = artifact.get("sections") if isinstance(artifact.get("sections"), list) else []
        sections.append(
            AgentToolStageOrchestrator._error_section(
                code=E_VERIFY_FAILED,
                stage_key="verify_result",
                message=message,
                details={"verification": summary},
            )
        )
        artifact["sections"] = sections
        context.asset_result.artifact = artifact
        return StageActionResult(ok=False, message=message, error_code=E_VERIFY_FAILED, retryable=False)

    @staticmethod
    def _stage_policy_gate_result(context: ToolStageContext) -> StageActionResult:
        if context.asset_result is None:
            return StageActionResult(ok=False, message="No execution result to policy-check.", error_code=E_POLICY_GATE_FAILED)
        if not AgentToolStageOrchestrator._policy_gate_enabled():
            context.policy_passed = True
            artifact = context.asset_result.artifact if isinstance(context.asset_result.artifact, dict) else {}
            metrics = artifact.get("metrics") if isinstance(artifact.get("metrics"), dict) else {}
            metrics["policy_enforced"] = False
            artifact["metrics"] = metrics
            context.asset_result.artifact = artifact
            return StageActionResult(ok=True, message="Policy gate skipped by configuration.")
        summary = evaluate_policy_gate(result=context.asset_result, tool=context.tool)
        artifact = context.asset_result.artifact if isinstance(context.asset_result.artifact, dict) else {}
        provenance = artifact.get("provenance") if isinstance(artifact.get("provenance"), dict) else {}
        provenance["policy_gate"] = summary
        artifact["provenance"] = provenance
        metrics = artifact.get("metrics") if isinstance(artifact.get("metrics"), dict) else {}
        metrics["policy_enforced"] = True
        artifact["metrics"] = metrics
        context.asset_result.artifact = artifact
        if policy_gate_passed(summary):
            context.policy_passed = True
            return StageActionResult(ok=True, message="Policy gate passed.")
        message = policy_gate_error_message(summary)
        context.asset_result.status = "error"
        context.asset_result.error = message
        sections = artifact.get("sections") if isinstance(artifact.get("sections"), list) else []
        sections.append(
            AgentToolStageOrchestrator._error_section(
                code=E_POLICY_GATE_FAILED,
                stage_key="policy_gate_result",
                message=message,
                details={"policy_gate": summary},
            )
        )
        artifact["sections"] = sections
        context.asset_result.artifact = artifact
        return StageActionResult(ok=False, message=message, error_code=E_POLICY_GATE_FAILED, retryable=False)

    @staticmethod
    def _stage_finalize_result(context: ToolStageContext) -> StageActionResult:
        if context.asset_result is None:
            return StageActionResult(ok=False, message="No execution result to finalize.", error_code=E_STAGE_EXCEPTION)
        if not context.asset_result.intent:
            context.asset_result.intent = context.tool.intent
        if not context.asset_result.payload:
            context.asset_result.payload = context.payload
        if context.asset_result.artifact is None:
            context.asset_result.artifact = legacy_result_to_artifact(context.asset_result)
        artifact = context.asset_result.artifact if isinstance(context.asset_result.artifact, dict) else {}
        provenance = artifact.get("provenance") if isinstance(artifact.get("provenance"), dict) else {}
        if "verification" not in provenance and AgentToolStageOrchestrator._verify_stage_enabled():
            provenance["verification"] = {
                "status": "passed" if context.verified else "failed",
                "issues": [],
                "checks_run": [],
            }
        if "policy_gate" not in provenance and AgentToolStageOrchestrator._policy_gate_enabled():
            provenance["policy_gate"] = {
                "status": "passed" if context.policy_passed else "failed",
                "issues": [],
                "checks_run": [],
            }
        artifact["provenance"] = provenance
        context.asset_result.artifact = artifact
        return StageActionResult(ok=True, message="Result finalized.")

    @staticmethod
    def _fallback_error_result(
        *,
        tool: AgentToolDefinition,
        payload: IntentPayload,
        message: str,
        run_id: str = "",
    ) -> AgentAssetResult:
        return AgentToolStageOrchestrator._error_result(
            tool=tool,
            payload=payload,
            code=E_EXECUTOR_FAILED,
            stage_key="fallback",
            message=message,
            details={},
            run_id=run_id,
        )

    @staticmethod
    def _error_section(
        *,
        code: str,
        stage_key: str,
        message: str,
        details: dict[str, object],
        run_id: str = "",
        tool_key: str = "",
    ) -> dict[str, object]:
        data_details = dict(details)
        normalized_run_id = " ".join(str(run_id).split()).strip()
        normalized_tool_key = " ".join(str(tool_key).split()).strip()
        if normalized_run_id:
            data_details["run_id"] = normalized_run_id
        if normalized_tool_key:
            data_details["tool_key"] = normalized_tool_key
        return {
            "kind": "meta",
            "key": "error",
            "title": "Error",
            "data": {
                "code": code,
                "stage": stage_key,
                "message": message,
                "details": data_details,
            },
            "optional": False,
        }

    @staticmethod
    def _error_result(
        *,
        tool: AgentToolDefinition,
        payload: IntentPayload,
        code: str,
        stage_key: str,
        message: str,
        details: dict[str, object],
        run_id: str = "",
    ) -> AgentAssetResult:
        return AgentAssetResult(
            intent=tool.intent,
            status="error",
            error=message,
            payload=payload,
            artifact=build_artifact_envelope(
                intent=tool.intent,
                title=tool.title,
                summary=message,
                sections=[
                    AgentToolStageOrchestrator._error_section(
                        code=code,
                        stage_key=stage_key,
                        message=message,
                        details=details,
                        run_id=run_id,
                        tool_key=tool.key,
                    )
                ],
                metrics={"cache_hit": False},
                provenance={"stage": stage_key},
            ),
        )

    @staticmethod
    def _verify_stage_enabled() -> bool:
        return enable_verify_stage()

    @staticmethod
    def _policy_gate_enabled() -> bool:
        return enable_policy_gate()

    @staticmethod
    def _stage_timeout_ms(stage_key: str, tool: AgentToolDefinition | None = None) -> int:
        normalized = " ".join(str(stage_key).split()).strip().lower()
        if normalized == "execute_tool":
            if tool is not None and isinstance(tool.execution_spec, dict):
                execution_policy = tool.execution_spec.get("execution_policy")
                if isinstance(execution_policy, dict) and execution_policy.get("timeout_ms") is not None:
                    try:
                        timeout = int(execution_policy.get("timeout_ms"))
                        return max(0, timeout)
                    except (TypeError, ValueError):
                        return execute_stage_timeout_ms()
            return execute_stage_timeout_ms()
        if normalized == "verify_result":
            return verify_stage_timeout_ms()
        return 0

    @staticmethod
    def _execute_max_attempts(tool: AgentToolDefinition) -> int:
        spec = tool.execution_spec if isinstance(tool.execution_spec, dict) else {}
        execution_policy = spec.get("execution_policy") if isinstance(spec.get("execution_policy"), dict) else {}
        max_retries_raw = execution_policy.get("max_retries", execute_retry_count())
        try:
            max_retries = int(max_retries_raw)
        except (TypeError, ValueError):
            max_retries = execute_retry_count()
        return max(1, max(0, max_retries) + 1)

    @classmethod
    def default_stage_sequence(cls, stage_profile: str = "default_asset_profile") -> tuple[str, ...]:
        normalized_profile = " ".join(str(stage_profile).split()).strip().lower()
        return cls._DEFAULT_STAGE_PROFILES.get(normalized_profile, cls._DEFAULT_STAGE_PROFILES["default_asset_profile"])


def build_default_tool_stage_catalog(*, tool_registry: AgentToolRegistry) -> AgentToolStageCatalog:
    catalog = AgentToolStageCatalog()
    for tool in tool_registry.list_tools():
        stage_profile = (
            " ".join(str(tool.execution_spec.get("stage_profile", "default_asset_profile")).split()).strip().lower()
            if isinstance(tool.execution_spec, dict)
            else "default_asset_profile"
        )
        catalog.register(
            AgentToolStageWorkflow(
                tool_key=tool.key,
                stage_keys=AgentToolStageOrchestrator.default_stage_sequence(stage_profile),
            )
        )
    return catalog


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
