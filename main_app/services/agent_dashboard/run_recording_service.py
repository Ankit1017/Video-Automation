from __future__ import annotations

from typing import Callable

from main_app.contracts import AssetRunSummary, OrchestrationState, RunLedgerRecord, StageDiagnostic, StageExecutionRecord
from main_app.models import AgentAssetResult
from main_app.services.agent_dashboard.error_codes import E_RUN_LEDGER_WRITE_FAILED
from main_app.services.agent_dashboard.run_ledger_service import RunLedgerService
from main_app.services.agent_dashboard.stage_ledger_service import StageLedgerService
from main_app.services.agent_dashboard.tool_stage_service import ToolStageResult
from main_app.services.telemetry_service import ObservabilityEvent, TelemetryService


class AgentRunRecordingService:
    def __init__(
        self,
        *,
        run_ledger_service: RunLedgerService,
        stage_ledger_service: StageLedgerService,
        telemetry_service: TelemetryService | None = None,
        on_stage_event: Callable[[StageDiagnostic], None] | None = None,
        on_run_event: Callable[[RunLedgerRecord], None] | None = None,
    ) -> None:
        self._run_ledger_service = run_ledger_service
        self._stage_ledger_service = stage_ledger_service
        self._telemetry_service = telemetry_service
        self._on_stage_event = on_stage_event
        self._on_run_event = on_run_event

    def stage_event_sink(
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
            if self._telemetry_service is not None:
                payload_ref = self._telemetry_service.attach_payload(payload=diagnostic, kind="agent_stage_diagnostic")
                self._telemetry_service.record_metric(
                    name="agent_stage_duration_ms",
                    value=float(diagnostic.get("duration_ms", 0) or 0.0),
                    attrs={
                        "workflow_key": workflow_key,
                        "tool_key": tool_key,
                        "stage_key": str(record.get("stage_key", "")),
                        "status": str(record.get("status", "")),
                    },
                )
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="agent.stage",
                        component="agent_dashboard.stage",
                        status=str(record.get("status", "")) or "unknown",
                        timestamp=str(record.get("ended_at", "")),
                        attributes={
                            "run_id": run_id,
                            "workflow_key": workflow_key,
                            "tool_key": tool_key,
                            "stage_key": str(record.get("stage_key", "")),
                            "attempt": int(record.get("attempt", 1) or 1),
                            "duration_ms": int(record.get("duration_ms", 0) or 0),
                            "error_code": str(record.get("error_code", "")),
                        },
                        payload_ref=payload_ref,
                    )
                )
            if sink is not None:
                sink(diagnostic)

        return _emit

    @staticmethod
    def append_stage_notes(*, notes: list[str], intent: str, stage_results: list[ToolStageResult]) -> None:
        for stage_result in stage_results:
            notes.append(
                f"{intent}: stage `{stage_result.stage_key}` -> {stage_result.status} "
                f"(duration_ms={stage_result.duration_ms}, error_code={stage_result.error_code or 'none'}, attempt={stage_result.attempt})"
            )

    @staticmethod
    def build_run_record(
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

    def record_run(
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

    @staticmethod
    def publishable(asset: AgentAssetResult) -> bool:
        if asset.status != "success":
            return False
        artifact = _as_dict(asset.artifact)
        provenance = _as_dict(artifact.get("provenance"))
        verification = _as_dict(provenance.get("verification"))
        policy_gate = _as_dict(provenance.get("policy_gate"))
        verify_status = " ".join(str(verification.get("status", "passed")).split()).strip().lower()
        policy_status = " ".join(str(policy_gate.get("status", "passed")).split()).strip().lower()
        return verify_status == "passed" and policy_status == "passed"

    @staticmethod
    def verification_status(asset: AgentAssetResult) -> str:
        artifact = _as_dict(asset.artifact)
        provenance = _as_dict(artifact.get("provenance"))
        verification = _as_dict(provenance.get("verification"))
        return " ".join(str(verification.get("status", "unknown")).split()).strip().lower() or "unknown"

    @staticmethod
    def retry_count(asset: AgentAssetResult) -> int:
        artifact = _as_dict(asset.artifact)
        metrics = _as_dict(artifact.get("metrics"))
        return _coerce_int(metrics.get("retry_count"), 0)


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

