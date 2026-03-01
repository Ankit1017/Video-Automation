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
        result = context.report_service.generate(
            topic=topic,
            format_key=str(payload.get("format_key", "briefing_doc")),
            additional_notes=str(payload.get("additional_notes", "")),
            grounding_context=runtime_context.grounding_context,
            source_manifest=list(runtime_context.source_manifest),
            require_citations=bool(runtime_context.require_citations),
            grounding_metadata=dict(runtime_context.diagnostics),
            settings=settings,
        )
        return build_content_asset_result(
            intent="report",
            payload=payload,
            topic=topic,
            title_prefix="Report",
            content=result.content,
            cache_hit=result.cache_hit,
        )

    return _execute


PLUGIN = AssetExecutorPlugin(intent="report", build_executor=_build_executor)
