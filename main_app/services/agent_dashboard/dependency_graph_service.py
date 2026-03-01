from __future__ import annotations

from collections import defaultdict

from main_app.services.agent_dashboard.tool_registry import AgentToolDefinition
from main_app.services.agent_dashboard.tool_stage_service import (
    AgentToolStageCatalog,
    AgentToolStageOrchestrator,
)


class AgentDependencyGraphService:
    def build_dependency_map(self, *, tools: list[AgentToolDefinition]) -> dict[str, set[str]]:
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

    def expected_stages_for_tool(
        self,
        tool: AgentToolDefinition,
        *,
        stage_catalog: AgentToolStageCatalog,
    ) -> list[str]:
        workflow = stage_catalog.get(tool.key)
        if workflow is not None:
            return list(workflow.stage_keys)
        stage_profile = (
            " ".join(str(tool.execution_spec.get("stage_profile", "default_asset_profile")).split()).strip().lower()
            if isinstance(tool.execution_spec, dict)
            else "default_asset_profile"
        )
        return list(AgentToolStageOrchestrator.default_stage_sequence(stage_profile))

