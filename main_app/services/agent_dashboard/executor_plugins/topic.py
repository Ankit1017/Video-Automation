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
    build_content_asset_result,
)


def _build_executor(context: AssetExecutorPluginContext) -> AssetExecutor:
    def _execute(
        payload: IntentPayload,
        settings: GroqSettings,
        runtime_context: AssetExecutionRuntimeContext,
    ) -> AgentAssetResult:
        topic = str(payload.get("topic", ""))
        content, cache_hit = context.explainer_service.generate(
            topic=topic,
            additional_instructions=str(payload.get("additional_instructions", "")),
            grounding_context=runtime_context.grounding_context,
            source_manifest=list(runtime_context.source_manifest),
            require_citations=bool(runtime_context.require_citations),
            grounding_metadata=dict(runtime_context.diagnostics),
            settings=settings,
        )
        return build_content_asset_result(
            intent="topic",
            payload=payload,
            topic=topic,
            title_prefix="Detailed Description",
            content=content,
            cache_hit=cache_hit,
        )

    return _execute


PLUGIN = AssetExecutorPlugin(intent="topic", build_executor=_build_executor)
