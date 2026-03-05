from __future__ import annotations

import json
from typing import cast

from main_app.contracts import CartoonTimeline, IntentPayload
from main_app.models import AgentAssetResult, GroqSettings
from main_app.services.agent_dashboard.executor_types import (
    AssetExecutionRuntimeContext,
    AssetExecutor,
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
        if context.cartoon_service is None:
            return build_error_asset_result(
                intent="cartoon_shorts",
                payload=payload,
                error="Cartoon shorts service is not configured.",
            )
        topic = str(payload.get("topic", "")).strip()
        manual_timeline = _manual_timeline_from_payload(payload)
        result = context.cartoon_service.generate(
            topic=topic,
            idea=str(payload.get("idea", "")),
            short_type=str(payload.get("short_type", "educational_explainer")),
            scene_count=_int_safe(payload.get("scene_count"), default=4),
            speaker_count=_int_safe(payload.get("speaker_count"), default=2),
            output_mode=str(payload.get("output_mode", "dual")),
            language=str(payload.get("language", "en")),
            use_hinglish_script=bool(payload.get("hinglish_script", False)),
            manual_timeline=manual_timeline,
            settings=settings,
        )
        if result.parse_error or not isinstance(result.cartoon_payload, dict):
            return build_error_asset_result(
                intent="cartoon_shorts",
                payload=payload,
                error=result.parse_error or "Cartoon shorts generation failed.",
                raw_text=result.debug_raw or "",
            )
        return build_media_asset_result(
            intent="cartoon_shorts",
            payload=payload,
            topic=topic,
            title_prefix="Cartoon Shorts",
            content=result.cartoon_payload,
            cache_hit=result.cache_hits > 0,
            audio_bytes=None,
            audio_error=None,
            parse_note=" ".join(result.parse_notes).strip(),
        )

    return _execute


def _manual_timeline_from_payload(payload: IntentPayload) -> CartoonTimeline | None:
    raw = payload.get("manual_timeline_json")
    if isinstance(raw, dict):
        return cast(CartoonTimeline, raw)
    if not isinstance(raw, str):
        return None
    text = " ".join(raw.split()).strip()
    if not text:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return cast(CartoonTimeline, parsed)


def _int_safe(value: object, *, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return default


PLUGIN = AssetExecutorPlugin(intent="cartoon_shorts", build_executor=_build_executor)
