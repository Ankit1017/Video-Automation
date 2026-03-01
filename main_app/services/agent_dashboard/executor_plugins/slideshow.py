from __future__ import annotations

from typing import Literal

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
    build_error_asset_result,
)


def _build_executor(context: AssetExecutorPluginContext) -> AssetExecutor:
    def _execute(
        payload: IntentPayload,
        settings: GroqSettings,
        runtime_context: AssetExecutionRuntimeContext,
    ) -> AgentAssetResult:
        topic = str(payload.get("topic", ""))
        raw_code_mode = " ".join(str(payload.get("code_mode", "auto")).split()).strip().lower()
        code_mode: Literal["auto", "force", "none"] = "auto"
        if raw_code_mode == "force":
            code_mode = "force"
        elif raw_code_mode == "none":
            code_mode = "none"
        result = context.slideshow_service.generate(
            topic=topic,
            constraints=str(payload.get("constraints", "")),
            subtopic_count=int(payload.get("subtopic_count", 5)),
            slides_per_subtopic=int(payload.get("slides_per_subtopic", 2)),
            code_mode=code_mode,
            representation_mode=str(payload.get("representation_mode", "auto")),
            grounding_context=runtime_context.grounding_context,
            source_manifest=list(runtime_context.source_manifest),
            require_citations=bool(runtime_context.require_citations),
            grounding_metadata=dict(runtime_context.diagnostics),
            settings=settings,
        )
        if result.parse_error or not result.slides:
            return build_error_asset_result(
                intent="slideshow",
                error=result.parse_error or "Slideshow generation failed.",
                payload=payload,
                raw_text=result.debug_raw or "",
            )
        return build_content_asset_result(
            intent="slideshow",
            payload=payload,
            topic=topic,
            title_prefix="Slide Show",
            content={"slides": result.slides},
            cache_hit=result.cache_hits > 0,
            parse_note=" ".join(result.parse_notes).strip(),
        )

    return _execute


PLUGIN = AssetExecutorPlugin(intent="slideshow", build_executor=_build_executor)
