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
    build_error_asset_result,
    build_media_asset_result,
)


def _build_executor(context: AssetExecutorPluginContext) -> AssetExecutor:
    def _execute(
        payload: IntentPayload,
        settings: GroqSettings,
        runtime_context: AssetExecutionRuntimeContext,
    ) -> AgentAssetResult:
        _ = runtime_context
        topic = str(payload.get("topic", ""))
        if context.video_service is None:
            return build_error_asset_result(
                intent="video",
                error="Video service is not configured.",
                payload=payload,
            )
        raw_code_mode = " ".join(str(payload.get("code_mode", "auto")).split()).strip().lower()
        code_mode: Literal["auto", "force", "none"] = "auto"
        if raw_code_mode == "force":
            code_mode = "force"
        elif raw_code_mode == "none":
            code_mode = "none"

        result = context.video_service.generate(
            topic=topic,
            constraints=str(payload.get("constraints", "")),
            subtopic_count=int(payload.get("subtopic_count", 5)),
            slides_per_subtopic=int(payload.get("slides_per_subtopic", 2)),
            code_mode=code_mode,
            speaker_count=int(payload.get("speaker_count", 2)),
            conversation_style=str(payload.get("conversation_style", "Educational Discussion")),
            video_template=str(payload.get("video_template", "standard")),
            animation_style=str(payload.get("animation_style", "smooth")),
            representation_mode=str(payload.get("representation_mode", "auto")),
            use_youtube_prompt=bool(payload.get("youtube_prompt", False)),
            settings=settings,
        )
        if result.parse_error or not result.video_payload:
            return build_error_asset_result(
                intent="video",
                error=result.parse_error or "Video generation failed.",
                payload=payload,
                raw_text=result.debug_raw or "",
            )

        audio_bytes, audio_error = context.video_service.synthesize_audio(
            video_payload=result.video_payload,
            language=str(payload.get("language", "en")),
            slow=bool(payload.get("slow_audio", False)),
        )
        return build_media_asset_result(
            intent="video",
            payload=payload,
            topic=topic,
            title_prefix="Video",
            content=result.video_payload,
            cache_hit=result.cache_hits > 0,
            audio_bytes=audio_bytes,
            audio_error=audio_error,
            parse_note=" ".join(result.parse_notes).strip(),
        )

    return _execute


PLUGIN = AssetExecutorPlugin(intent="video", build_executor=_build_executor)
