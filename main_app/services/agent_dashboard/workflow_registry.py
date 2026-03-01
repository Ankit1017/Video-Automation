from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from main_app.contracts import WorkflowPluginSpec
from main_app.services.agent_dashboard.intent_catalog import ASSET_INTENTS, normalize_intent
from main_app.services.agent_dashboard.plugin_sdk import validate_workflow_plugin_spec
from main_app.services.agent_dashboard.tool_registry import AgentToolDefinition, AgentToolRegistry


@dataclass(frozen=True)
class AgentWorkflowDefinition:
    key: str
    title: str
    description: str
    tool_keys: list[str]
    tool_dependencies: dict[str, list[str]] = field(default_factory=dict)


class AgentWorkflowRegistry:
    PLAN_SELECTED_WORKFLOW_KEY = "plan_selected_assets"

    def __init__(self, workflows: Iterable[AgentWorkflowDefinition] | None = None) -> None:
        self._workflows: dict[str, AgentWorkflowDefinition] = {}
        self._workflow_plugin_specs: dict[str, WorkflowPluginSpec] = {}
        for workflow in workflows or []:
            self.register(workflow)

    def register(self, workflow: AgentWorkflowDefinition) -> None:
        self.register_plugin_spec(
            {
                "workflow_key": workflow.key,
                "tool_keys": list(workflow.tool_keys),
                "tool_dependencies": dict(workflow.tool_dependencies),
                "title": workflow.title,
                "description": workflow.description,
            }
        )

    def register_plugin_spec(self, workflow_spec: WorkflowPluginSpec) -> None:
        validation = validate_workflow_plugin_spec(workflow_spec)
        if not validation.ok:
            return
        workflow_key_raw = str(workflow_spec.get("workflow_key", ""))
        title_raw = str(workflow_spec.get("title", workflow_key_raw))
        description_raw = str(workflow_spec.get("description", ""))
        raw_tool_keys_value = workflow_spec.get("tool_keys")
        tool_keys_raw = raw_tool_keys_value if isinstance(raw_tool_keys_value, list) else []
        dependencies_raw = (
            workflow_spec.get("tool_dependencies")
            if isinstance(workflow_spec.get("tool_dependencies"), dict)
            else {}
        )
        key = normalize_intent(workflow_key_raw).replace(" ", "_")
        if not key:
            return
        tool_keys = [normalize_intent(item).replace(" ", "_") for item in tool_keys_raw if normalize_intent(item)]
        raw_dependencies = dependencies_raw if isinstance(dependencies_raw, dict) else {}
        normalized_dependencies: dict[str, list[str]] = {}
        for child_key, parents in raw_dependencies.items():
            child = normalize_intent(child_key).replace(" ", "_")
            if not child:
                continue
            parent_keys = [
                normalize_intent(parent).replace(" ", "_")
                for parent in (parents if isinstance(parents, list) else [])
                if normalize_intent(parent)
            ]
            if parent_keys:
                normalized_dependencies[child] = parent_keys
        self._workflows[key] = AgentWorkflowDefinition(
            key=key,
            title=" ".join(str(title_raw).split()).strip() or key,
            description=" ".join(str(description_raw).split()).strip(),
            tool_keys=tool_keys,
            tool_dependencies=normalized_dependencies,
        )
        self._workflow_plugin_specs[key] = {
            "workflow_key": key,
            "tool_keys": list(tool_keys),
            "tool_dependencies": dict(normalized_dependencies),
        }

    def list_workflows(self) -> list[AgentWorkflowDefinition]:
        ordered = sorted(self._workflows.values(), key=lambda item: item.key)
        return list(ordered)

    def list_workflow_plugin_specs(self) -> list[WorkflowPluginSpec]:
        return [self._workflow_plugin_specs[key] for key in sorted(self._workflow_plugin_specs.keys())]

    def get(self, key: str) -> AgentWorkflowDefinition | None:
        normalized = normalize_intent(key).replace(" ", "_")
        return self._workflows.get(normalized)

    def build_plan_selected_workflow(self, *, tools: list[AgentToolDefinition]) -> AgentWorkflowDefinition:
        dependencies: dict[str, list[str]] = {}
        for tool in tools:
            dependency = tool.execution_spec.get("dependency", {}) if isinstance(tool.execution_spec, dict) else {}
            required_artifacts = dependency.get("requires_artifacts", []) if isinstance(dependency.get("requires_artifacts"), list) else []
            if not required_artifacts:
                continue
            parents: list[str] = []
            for candidate in tools:
                if candidate.key == tool.key:
                    continue
                produced = candidate.execution_spec.get("dependency", {}).get("produces_artifacts", []) if isinstance(candidate.execution_spec, dict) else []
                if not isinstance(produced, list):
                    continue
                if any(str(item).strip() in {str(prod).strip() for prod in produced} for item in required_artifacts):
                    parents.append(candidate.key)
            if parents:
                dependencies[tool.key] = parents
        return AgentWorkflowDefinition(
            key=self.PLAN_SELECTED_WORKFLOW_KEY,
            title="Plan Selected Assets",
            description="Runs the exact set of tools selected by the active agent plan in declared order.",
            tool_keys=[tool.key for tool in tools],
            tool_dependencies=dependencies,
        )

    def resolve_workflow_tools(
        self,
        *,
        workflow: AgentWorkflowDefinition,
        tool_registry: AgentToolRegistry,
    ) -> list[AgentToolDefinition]:
        tools: list[AgentToolDefinition] = []
        for tool_key in workflow.tool_keys:
            tool = tool_registry.get_by_key(tool_key)
            if tool is None:
                continue
            tools.append(tool)
        return tools

    def resolve_workflow_tools_dag(
        self,
        *,
        workflow: AgentWorkflowDefinition,
        tool_registry: AgentToolRegistry,
    ) -> tuple[list[AgentToolDefinition], list[str]]:
        tools_by_key: dict[str, AgentToolDefinition] = {}
        for tool_key in workflow.tool_keys:
            tool = tool_registry.get_by_key(tool_key)
            if tool is not None:
                tools_by_key[tool.key] = tool
        if not tools_by_key:
            return [], []

        dependencies: dict[str, list[str]] = {}
        for key, tool in tools_by_key.items():
            explicit_parents = workflow.tool_dependencies.get(key, [])
            parents = [parent for parent in explicit_parents if parent in tools_by_key]
            if not parents:
                required = (
                    tool.execution_spec.get("dependency", {}).get("requires_artifacts", [])
                    if isinstance(tool.execution_spec, dict)
                    else []
                )
                if not isinstance(required, list):
                    required = []
                for candidate_key, candidate_tool in tools_by_key.items():
                    if candidate_key == key:
                        continue
                    produced = (
                        candidate_tool.execution_spec.get("dependency", {}).get("produces_artifacts", [])
                        if isinstance(candidate_tool.execution_spec, dict)
                        else []
                    )
                    produced_set = {str(item).strip() for item in produced if str(item).strip()} if isinstance(produced, list) else set()
                    if any(str(req).strip() in produced_set for req in required if str(req).strip()):
                        parents.append(candidate_key)
            if parents:
                dependencies[key] = sorted(set(parents))

        in_degree = {key: 0 for key in tools_by_key}
        adjacency: dict[str, list[str]] = {key: [] for key in tools_by_key}
        for child, parents in dependencies.items():
            for parent in parents:
                if parent not in tools_by_key or child not in tools_by_key:
                    continue
                adjacency[parent].append(child)
                in_degree[child] = in_degree.get(child, 0) + 1

        order_index = {key: idx for idx, key in enumerate(workflow.tool_keys)}
        queue = sorted([key for key, degree in in_degree.items() if degree == 0], key=lambda key: order_index.get(key, 9999))
        sorted_keys: list[str] = []
        while queue:
            node = queue.pop(0)
            sorted_keys.append(node)
            for child in sorted(adjacency.get(node, []), key=lambda key: order_index.get(key, 9999)):
                in_degree[child] = max(0, in_degree[child] - 1)
                if in_degree[child] == 0:
                    queue.append(child)
            queue = sorted(set(queue), key=lambda key: order_index.get(key, 9999))

        notes: list[str] = []
        if len(sorted_keys) != len(tools_by_key):
            cyclic = [key for key in tools_by_key if key not in set(sorted_keys)]
            notes.append("Workflow dependency cycle detected: " + ", ".join(cyclic))
            for key in workflow.tool_keys:
                if key in tools_by_key and key not in sorted_keys:
                    sorted_keys.append(key)

        return [tools_by_key[key] for key in sorted_keys if key in tools_by_key], notes


def build_default_agent_workflow_registry() -> AgentWorkflowRegistry:
    registry = AgentWorkflowRegistry()
    registry.register(
        AgentWorkflowDefinition(
            key="core_learning_assets",
            title="Core Learning Assets",
            description="Generates a compact learning set: topic explanation, mind map, flashcards, quiz, and slideshow.",
            tool_keys=["topic", "mindmap", "flashcards", "quiz", "slideshow"],
            tool_dependencies={},
        )
    )
    registry.register(
        AgentWorkflowDefinition(
            key="media_production_assets",
            title="Media Production Assets",
            description="Generates presentation and media outputs: slideshow, video, audio overview, and report.",
            tool_keys=["slideshow", "video", "audio_overview", "report"],
            tool_dependencies={"video": ["slideshow"]},
        )
    )
    registry.register(
        AgentWorkflowDefinition(
            key="full_asset_suite",
            title="Full Asset Suite",
            description="Runs all currently supported asset tools in catalog order.",
            tool_keys=[intent.replace(" ", "_") for intent in ASSET_INTENTS],
            tool_dependencies={},
        )
    )
    return registry
