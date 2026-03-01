from __future__ import annotations

from main_app.contracts import IntentPayload
from main_app.models import AgentAssetResult, GroqSettings
from main_app.services.agent_dashboard.executor_types import (
    AssetExecutor,
    AssetExecutionRuntimeContext,
    AssetExecutorPlugin,
    AssetExecutorPluginContext,
)
from main_app.services.agent_dashboard.executor_plugins.parsed_asset_result import (
    build_parsed_asset_result,
)


def _build_executor(context: AssetExecutorPluginContext) -> AssetExecutor:
    def _execute(
        payload: IntentPayload,
        settings: GroqSettings,
        runtime_context: AssetExecutionRuntimeContext,
    ) -> AgentAssetResult:
        _ = runtime_context
        topic = str(payload.get("topic", ""))
        result = context.mind_map_service.generate(
            topic=topic,
            max_depth=int(payload.get("max_depth", 4)),
            constraints=str(payload.get("constraints", "")),
            settings=settings,
        )
        return build_parsed_asset_result(
            intent="mindmap",
            payload=payload,
            topic=topic,
            title_prefix="Mind Map",
            parsed_content=result.parsed_map,
            parse_error=result.parse_error,
            raw_text=result.raw_text,
            parse_note=result.parse_note,
            cache_hit=result.cache_hit,
            failure_message="Mind map generation failed.",
        )

    return _execute


PLUGIN = AssetExecutorPlugin(intent="mindmap", build_executor=_build_executor)
