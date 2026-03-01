from __future__ import annotations

from main_app.contracts import OrchestrationState
from main_app.services.agent_dashboard.orchestration_state_service import OrchestrationStateService


class AgentWorkflowExecutionService:
    def __init__(self, *, orchestration_state_service: OrchestrationStateService) -> None:
        self._orchestration_state_service = orchestration_state_service

    def resolve_ready_tools(
        self,
        *,
        pending: set[str],
        completed: set[str],
        dependencies: dict[str, set[str]],
        tool_states: dict[str, OrchestrationState],
    ) -> list[str]:
        ready = [key for key in pending if all(parent in completed for parent in dependencies.get(key, set()))]
        for key in ready:
            transition = self._orchestration_state_service.transition(
                from_state=tool_states.get(key, "pending"),
                to_state="ready",
            )
            if transition.valid:
                tool_states[key] = "ready"
        return ready

    def mark_running(self, *, tool_key: str, tool_states: dict[str, OrchestrationState]) -> str | None:
        run_transition = self._orchestration_state_service.transition(
            from_state=tool_states.get(tool_key, "ready"),
            to_state="running",
        )
        if run_transition.valid:
            tool_states[tool_key] = "running"
            return None
        return run_transition.message

    def mark_finished(
        self,
        *,
        tool_key: str,
        success: bool,
        tool_states: dict[str, OrchestrationState],
    ) -> str | None:
        finish_transition = self._orchestration_state_service.transition(
            from_state=tool_states.get(tool_key, "running"),
            to_state="completed" if success else "failed",
        )
        if finish_transition.valid:
            tool_states[tool_key] = "completed" if success else "failed"
            return None
        return finish_transition.message

