from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, cast

from main_app.contracts import ArtifactSchemaRef, ToolExecutionPolicy, ToolExecutionSpec, ToolPluginSpec
from main_app.services.agent_dashboard.plugin_sdk import (
    normalize_tool_plugin_spec,
    validate_tool_plugin_spec,
)
from main_app.services.agent_dashboard.artifact_adapter import (
    default_optional_required_artifact_keys_by_intent,
    default_produced_artifact_keys_by_intent,
    default_required_artifact_keys_by_intent,
)
from main_app.services.agent_dashboard.intent_catalog import ASSET_INTENTS, ASSET_TAB_TITLE_BY_INTENT, normalize_intent


def _as_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _as_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _as_object_list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return list(value)


@dataclass(frozen=True)
class AgentToolDefinition:
    key: str
    intent: str
    title: str
    description: str
    execution_spec: ToolExecutionSpec = field(default_factory=lambda: cast(ToolExecutionSpec, {}))
    capabilities: list[str] = field(default_factory=list)
    schema_ref: ArtifactSchemaRef = field(default_factory=lambda: cast(ArtifactSchemaRef, {}))


class AgentToolRegistry:
    def __init__(self, tools: Iterable[AgentToolDefinition] | None = None) -> None:
        self._tools_by_key: dict[str, AgentToolDefinition] = {}
        self._tool_key_by_intent: dict[str, str] = {}
        self._plugin_specs_by_key: dict[str, ToolPluginSpec] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: AgentToolDefinition) -> None:
        plugin_spec: ToolPluginSpec = {
            "plugin_key": tool.key,
            "intent": tool.intent,
            "title": tool.title,
            "description": tool.description,
            "capabilities": [str(item).strip() for item in tool.capabilities if str(item).strip()],
            "execution_spec": tool.execution_spec if isinstance(tool.execution_spec, dict) else {},
            "schema_ref": tool.schema_ref if isinstance(tool.schema_ref, dict) else {},
        }
        self.register_plugin_spec(plugin_spec)

    def register_plugin_spec(self, plugin_spec: ToolPluginSpec) -> None:
        normalized_plugin_spec = normalize_tool_plugin_spec(plugin_spec)
        validation = validate_tool_plugin_spec(normalized_plugin_spec)
        if not validation.ok:
            return
        key_raw = str(normalized_plugin_spec.get("plugin_key", ""))
        intent_raw = str(normalized_plugin_spec.get("intent", ""))
        intent = normalize_intent(intent_raw)
        key = normalize_intent(key_raw).replace(" ", "_")
        if not key or not intent:
            return
        execution_spec = _as_dict(normalized_plugin_spec.get("execution_spec"))
        capabilities = _as_string_list(normalized_plugin_spec.get("capabilities"))
        schema_ref = _as_dict(normalized_plugin_spec.get("schema_ref"))
        normalized_tool = AgentToolDefinition(
            key=key,
            intent=intent,
            title=" ".join(str(normalized_plugin_spec.get("title", intent.title())).split()).strip() or intent.title(),
            description=" ".join(str(normalized_plugin_spec.get("description", "")).split()).strip(),
            execution_spec=self._normalize_execution_spec(
                execution_spec=cast(ToolExecutionSpec | dict[str, object], execution_spec),
                normalized_key=key,
                normalized_intent=intent,
            ),
            capabilities=capabilities,
            schema_ref=self._normalize_schema_ref(intent=intent, schema_ref=schema_ref),
        )
        self._tools_by_key[key] = normalized_tool
        self._tool_key_by_intent[intent] = key
        self._plugin_specs_by_key[key] = {
            "plugin_key": key,
            "intent": intent,
            "capabilities": list(normalized_tool.capabilities),
            "execution_spec": normalized_tool.execution_spec,
            "schema_ref": normalized_tool.schema_ref,
        }

    def list_tools(self) -> list[AgentToolDefinition]:
        ordered_keys = [self._tool_key_by_intent[intent] for intent in ASSET_INTENTS if intent in self._tool_key_by_intent]
        ordered_keys.extend(sorted(key for key in self._tools_by_key if key not in set(ordered_keys)))
        return [self._tools_by_key[key] for key in ordered_keys]

    def list_plugin_specs(self) -> list[ToolPluginSpec]:
        return [self._plugin_specs_by_key[key] for key in sorted(self._plugin_specs_by_key.keys())]

    def get_by_key(self, key: str) -> AgentToolDefinition | None:
        normalized = normalize_intent(key).replace(" ", "_")
        return self._tools_by_key.get(normalized)

    def get_by_intent(self, intent: str) -> AgentToolDefinition | None:
        normalized_intent = normalize_intent(intent)
        tool_key = self._tool_key_by_intent.get(normalized_intent)
        if not tool_key:
            return None
        return self._tools_by_key.get(tool_key)

    def resolve_tools_for_intents(
        self,
        intents: list[str] | tuple[str, ...],
    ) -> tuple[list[AgentToolDefinition], list[str]]:
        resolved: list[AgentToolDefinition] = []
        unresolved: list[str] = []
        seen_intents: set[str] = set()

        for raw_intent in intents:
            intent = normalize_intent(raw_intent)
            if not intent or intent in seen_intents:
                continue
            seen_intents.add(intent)
            tool = self.get_by_intent(intent)
            if tool is None:
                unresolved.append(intent)
                continue
            resolved.append(tool)
        return resolved, unresolved

    @staticmethod
    def _normalize_execution_spec(
        *,
        execution_spec: ToolExecutionSpec | dict[str, object],
        normalized_key: str,
        normalized_intent: str,
    ) -> ToolExecutionSpec:
        execution_spec_map = _as_dict(execution_spec)
        dependency = _as_dict(execution_spec_map.get("dependency"))
        required = _as_string_list(dependency.get("requires_artifacts"))
        produced = _as_string_list(dependency.get("produces_artifacts"))
        optional_requires = _as_string_list(dependency.get("optional_requires"))
        if not required:
            required = default_required_artifact_keys_by_intent(normalized_intent)
        if not produced:
            produced = default_produced_artifact_keys_by_intent(normalized_intent)
        if not optional_requires:
            optional_requires = default_optional_required_artifact_keys_by_intent(normalized_intent)
        return {
            "intent": " ".join(str(execution_spec_map.get("intent", normalized_intent)).split()).strip().lower(),
            "tool_key": " ".join(str(execution_spec_map.get("tool_key", normalized_key)).split()).strip().lower().replace(" ", "_"),
            "stage_profile": " ".join(str(execution_spec_map.get("stage_profile", "default_asset_profile")).split()).strip().lower(),
            "requirements_schema_key": " ".join(
                str(execution_spec_map.get("requirements_schema_key", normalized_intent)).split()
            ).strip().lower(),
            "verify_profile": " ".join(
                str(execution_spec_map.get("verify_profile", _default_verify_profile_by_intent(normalized_intent))).split()
            ).strip().lower(),
            "verify_required": bool(execution_spec_map.get("verify_required", True)),
            "execution_policy": _normalize_execution_policy(
                execution_policy=execution_spec_map.get("execution_policy"),
                intent=normalized_intent,
            ),
            "dependency": {
                "requires_artifacts": required,
                "produces_artifacts": produced,
                "optional_requires": optional_requires,
            },
        }

    @staticmethod
    def _normalize_schema_ref(*, intent: str, schema_ref: dict[str, object]) -> ArtifactSchemaRef:
        version = " ".join(str(schema_ref.get("version", "v1")).split()).strip().lower() or "v1"
        schema_id = " ".join(str(schema_ref.get("id", f"{intent}.{version}")).split()).strip() or f"{intent}.{version}"
        schema_intent = " ".join(str(schema_ref.get("intent", intent)).split()).strip().lower() or intent
        return {
            "intent": schema_intent,
            "version": version,
            "id": schema_id,
        }


def build_default_agent_tool_registry(
    extra_tools: Iterable[AgentToolDefinition] | None = None,
) -> AgentToolRegistry:
    default_descriptions = {
        "topic": "Generates detailed topic explanation content.",
        "mindmap": "Builds a hierarchical visual concept map.",
        "flashcards": "Creates study flashcards with concise Q/A pairs.",
        "data table": "Generates structured comparison/analysis tables.",
        "quiz": "Builds quiz questions with answer keys.",
        "slideshow": "Creates presentation slides with optional code.",
        "video": "Generates narrated video payload and multi-voice script.",
        "cartoon_shorts": "Generates cartoon short videos with multi-character dialogue and scene timeline.",
        "audio_overview": "Creates podcast-style multi-speaker audio scripts.",
        "report": "Generates long-form report documents.",
    }
    tools: list[AgentToolDefinition] = []
    for intent in ASSET_INTENTS:
        tools.append(
            AgentToolDefinition(
                key=intent.replace(" ", "_"),
                intent=intent,
                title=ASSET_TAB_TITLE_BY_INTENT.get(intent, intent.title()),
                description=default_descriptions.get(intent, f"{intent.title()} generation tool."),
                capabilities=["generative_asset"],
                schema_ref={
                    "intent": normalize_intent(intent),
                    "version": "v1",
                    "id": f"{normalize_intent(intent).replace(' ', '_')}.v1",
                },
                execution_spec={
                    "intent": intent,
                    "tool_key": intent.replace(" ", "_"),
                    "stage_profile": "media_asset_profile" if intent in {"video", "cartoon_shorts", "audio_overview"} else "default_asset_profile",
                    "requirements_schema_key": intent,
                    "verify_profile": _default_verify_profile_by_intent(intent),
                    "verify_required": True,
                    "execution_policy": _default_execution_policy_by_intent(intent),
                    "dependency": {
                        "requires_artifacts": default_required_artifact_keys_by_intent(intent),
                        "produces_artifacts": default_produced_artifact_keys_by_intent(intent),
                        "optional_requires": default_optional_required_artifact_keys_by_intent(intent),
                    },
                },
            )
        )
    registry = AgentToolRegistry(tools=tools)
    for tool in extra_tools or []:
        registry.register(tool)
    return registry


def _default_verify_profile_by_intent(intent: str) -> str:
    normalized = normalize_intent(intent)
    if normalized in {"topic", "report"}:
        return "text_asset_verify"
    if normalized in {"video", "cartoon_shorts", "audio_overview"}:
        return "media_asset_verify"
    return "structured_asset_verify"


def _normalize_execution_policy(*, execution_policy: object, intent: str) -> ToolExecutionPolicy:
    default = _default_execution_policy_by_intent(intent)
    execution_policy_map = _as_dict(execution_policy)
    if not execution_policy_map:
        return default
    retry_backoff = _as_object_list(execution_policy_map.get("retry_backoff_ms"))
    default_retry_backoff = _as_object_list(default.get("retry_backoff_ms", []))
    return {
        "timeout_ms": _int_or_none(execution_policy_map.get("timeout_ms"), default.get("timeout_ms")),
        "max_retries": max(
            0,
            min(5, _int_or_default(execution_policy_map.get("max_retries"), _int_or_default(default.get("max_retries"), 1))),
        ),
        "retry_backoff_ms": [
            max(0, min(120000, _int_or_default(item, 0)))
            for item in (retry_backoff if retry_backoff else default_retry_backoff)
        ],
        "fail_policy": (
            "fail_fast"
            if " ".join(str(execution_policy_map.get("fail_policy", default.get("fail_policy", "continue"))).split()).strip().lower()
            in {"fail_fast", "failfast"}
            else "continue"
        ),
        "concurrency_group": (
            " ".join(str(execution_policy_map.get("concurrency_group", default.get("concurrency_group") or "")).split()).strip()
            or None
        ),
        "profile": (
            " ".join(str(execution_policy_map.get("profile", default.get("profile", ""))).split()).strip().lower()
            or str(default.get("profile", "structured_policy_gate"))
        ),
    }


def _default_execution_policy_by_intent(intent: str) -> ToolExecutionPolicy:
    normalized = normalize_intent(intent)
    profile = "structured_policy_gate"
    if normalized in {"topic", "report"}:
        profile = "text_policy_gate"
    elif normalized in {"video", "cartoon_shorts", "audio_overview"}:
        profile = "media_policy_gate"
    return {
        "timeout_ms": None,
        "max_retries": 1,
        "retry_backoff_ms": [0],
        "fail_policy": "continue",
        "concurrency_group": None,
        "profile": profile,
    }


def _int_or_none(value: object, default: object) -> int | None:
    parsed = _coerce_int(value)
    if parsed is not None:
        return parsed
    return _coerce_int(default)


def _int_or_default(value: object, default: int) -> int:
    parsed = _coerce_int(value)
    return parsed if parsed is not None else default


def _coerce_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float, str)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return None
