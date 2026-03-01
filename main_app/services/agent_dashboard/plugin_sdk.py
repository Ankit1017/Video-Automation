from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from main_app.contracts import ToolPluginSpec, WorkflowPluginSpec
from main_app.services.agent_dashboard.error_codes import (
    E_PLUGIN_SPEC_HINT_AVAILABLE,
    E_PLUGIN_SPEC_INVALID,
)


class BaseToolPlugin(Protocol):
    def spec(self) -> ToolPluginSpec:
        ...

    def health_check(self) -> tuple[bool, str]:
        ...


class BaseWorkflowPlugin(Protocol):
    def spec(self) -> WorkflowPluginSpec:
        ...

    def health_check(self) -> tuple[bool, str]:
        ...


class BaseRendererPlugin(Protocol):
    def key(self) -> str:
        ...

    def health_check(self) -> tuple[bool, str]:
        ...


@dataclass(frozen=True)
class PluginValidationResult:
    ok: bool
    error_code: str
    message: str
    fix_hints: list[str] | None = None


def _as_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def default_capabilities_for_intent(intent: str) -> list[str]:
    normalized = " ".join(str(intent).split()).strip().lower()
    if normalized in {"video", "audio_overview"}:
        return ["generative_asset", "media"]
    if normalized in {"topic", "report"}:
        return ["generative_asset", "text"]
    return ["generative_asset", "structured"]


def normalize_tool_plugin_spec(spec: ToolPluginSpec) -> ToolPluginSpec:
    raw = _as_dict(spec)
    plugin_key = " ".join(str(raw.get("plugin_key", raw.get("intent", ""))).split()).strip().lower().replace(" ", "_")
    intent = " ".join(str(raw.get("intent", raw.get("plugin_key", ""))).split()).strip().lower()
    title = " ".join(str(raw.get("title", intent.title())).split()).strip() or intent.title()
    description = " ".join(str(raw.get("description", f"{title} plugin.")).split()).strip()
    capabilities_raw = raw.get("capabilities")
    capabilities = (
        [str(item).strip() for item in capabilities_raw if str(item).strip()]
        if isinstance(capabilities_raw, list)
        else []
    )
    if not capabilities:
        capabilities = default_capabilities_for_intent(intent)
    schema_ref_raw = _as_dict(raw.get("schema_ref"))
    version = " ".join(str(schema_ref_raw.get("version", "v1")).split()).strip().lower() or "v1"
    schema_id = " ".join(str(schema_ref_raw.get("id", f"{intent.replace(' ', '_')}.{version}")).split()).strip()
    execution_spec_raw = _as_dict(raw.get("execution_spec"))
    return {
        "plugin_key": plugin_key,
        "intent": intent,
        "title": title,
        "description": description,
        "capabilities": capabilities,
        "execution_spec": cast(Any, execution_spec_raw),
        "schema_ref": {
            "intent": " ".join(str(schema_ref_raw.get("intent", intent)).split()).strip().lower() or intent,
            "version": version,
            "id": schema_id,
        },
    }


def plugin_spec_fix_hints(spec: ToolPluginSpec) -> list[str]:
    hints: list[str] = []
    raw = _as_dict(spec)
    plugin_key = " ".join(str(raw.get("plugin_key", "")).split()).strip()
    intent = " ".join(str(raw.get("intent", "")).split()).strip()
    if not plugin_key:
        hints.append("Set `plugin_key` to a stable snake_case identifier (for example `my_tool`).")
    if not intent:
        hints.append("Set `intent` to the runtime intent name (for example `topic`).")
    if not isinstance(raw.get("execution_spec"), dict):
        hints.append("Add `execution_spec` with stage profile, dependency, and requirement schema key.")
    schema_ref = _as_dict(raw.get("schema_ref"))
    if not schema_ref:
        hints.append("Add `schema_ref` with `intent`, `version`, and `id` fields.")
    else:
        if not str(schema_ref.get("id", "")).strip():
            hints.append("Set `schema_ref.id` (for example `topic.v1`).")
    return hints


def validate_tool_plugin_spec(spec: ToolPluginSpec) -> PluginValidationResult:
    normalized = normalize_tool_plugin_spec(spec)
    plugin_key = " ".join(str(normalized.get("plugin_key", "")).split()).strip()
    intent = " ".join(str(normalized.get("intent", "")).split()).strip()
    execution_spec = normalized.get("execution_spec")
    hints = plugin_spec_fix_hints(spec)
    if not plugin_key:
        return PluginValidationResult(False, E_PLUGIN_SPEC_INVALID, "Missing plugin_key in tool plugin spec.", hints)
    if not intent:
        return PluginValidationResult(False, E_PLUGIN_SPEC_INVALID, "Missing intent in tool plugin spec.", hints)
    if not isinstance(execution_spec, dict):
        return PluginValidationResult(False, E_PLUGIN_SPEC_INVALID, "Missing execution_spec in tool plugin spec.", hints)
    if hints:
        return PluginValidationResult(True, E_PLUGIN_SPEC_HINT_AVAILABLE, "Tool plugin spec validated with fix hints.", hints)
    return PluginValidationResult(True, "", "", [])


def validate_workflow_plugin_spec(spec: WorkflowPluginSpec) -> PluginValidationResult:
    workflow_key = " ".join(str(spec.get("workflow_key", "")).split()).strip()
    tool_keys = spec.get("tool_keys")
    if not workflow_key:
        return PluginValidationResult(False, E_PLUGIN_SPEC_INVALID, "Missing workflow_key in workflow plugin spec.")
    if not isinstance(tool_keys, list) or not tool_keys:
        return PluginValidationResult(False, E_PLUGIN_SPEC_INVALID, "Workflow plugin must declare tool_keys.")
    return PluginValidationResult(True, "", "")
