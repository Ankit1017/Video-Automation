from __future__ import annotations

from main_app.contracts import IntentPayload
from main_app.models import AgentAssetResult, GroqSettings
from main_app.services.agent_dashboard.executor_types import (
    AssetExecutor,
    AssetExecutorPlugin,
    AssetExecutorPluginContext,
)
from main_app.services.agent_dashboard.executor_plugins.parsed_asset_result import (
    build_error_asset_result,
    build_media_asset_result,
)


def _build_executor(context: AssetExecutorPluginContext) -> AssetExecutor:
    def _execute(payload: IntentPayload, settings: GroqSettings) -> AgentAssetResult:
        topic = str(payload.get("topic", ""))
        result = context.audio_overview_service.generate(
            topic=topic,
            speaker_count=int(payload.get("speaker_count", 2)),
            turn_count=int(payload.get("turn_count", 12)),
            conversation_style=str(payload.get("conversation_style", "Educational Discussion")),
            constraints=str(payload.get("constraints", "")),
            use_youtube_prompt=bool(payload.get("youtube_prompt", False)),
            use_hinglish_script=bool(payload.get("hinglish_script", False)),
            settings=settings,
        )
        if result.parse_error or not result.parsed_overview:
            return build_error_asset_result(
                intent="audio_overview",
                error=result.parse_error or "Audio overview generation failed.",
                payload=payload,
                raw_text=result.raw_text,
            )

        audio_bytes, audio_error = context.audio_overview_service.synthesize_mp3(
            overview_payload=result.parsed_overview,
            language=str(payload.get("language", "en")),
            slow=bool(payload.get("slow_audio", False)),
        )
        return build_media_asset_result(
            intent="audio_overview",
            payload=payload,
            topic=topic,
            title_prefix="Audio Overview",
            content=result.parsed_overview,
            cache_hit=result.cache_hit,
            audio_bytes=audio_bytes,
            audio_error=audio_error,
            parse_note=result.parse_note,
        )

    return _execute


PLUGIN = AssetExecutorPlugin(intent="audio_overview", build_executor=_build_executor)
