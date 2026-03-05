from __future__ import annotations

import base64
import json
from typing import Any, cast

import streamlit as st

from main_app.contracts import CartoonPayload, CartoonTimeline, DialogueAudioSegment, JSONValue
from main_app.models import GroqSettings
from main_app.services.background_jobs import BackgroundJobContext, BackgroundJobManager
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.cartoon_audio_service import CartoonAudioService
from main_app.services.cartoon_exporter import CartoonExporter
from main_app.services.cartoon_shorts_asset_service import CartoonShortsAssetService
from main_app.services.video_avatar_lipsync_service import VideoAvatarLipsyncService
from main_app.ui.components import CartoonRenderConfig, render_background_job_panel, render_cartoon_view


_SHORT_TYPES = [
    "educational_explainer",
    "debate_discussion",
    "story_sketch",
    "news_brief",
    "product_pitch",
    "case_study",
]
_OUTPUT_MODES = ["dual", "shorts_9_16", "widescreen_16_9"]
_LANGUAGES = ["en", "hi"]
_TIMELINE_SCHEMA_OPTIONS = ["v2", "v1"]
_QUALITY_TIERS = ["auto", "light", "balanced", "high"]
_RENDER_STYLES = ["scene", "character_showcase"]
_BACKGROUND_STYLES = ["auto", "scene", "chroma_green"]


def render_cartoon_shorts_tab(
    *,
    cartoon_service: CartoonShortsAssetService,
    cartoon_audio_service: CartoonAudioService,
    cartoon_exporter: CartoonExporter,
    llm_service: CachedLLMService,
    settings: GroqSettings,
    cache_count_placeholder: Any,
    job_manager: BackgroundJobManager,
) -> None:
    st.subheader("Cartoon Shorts Studio")
    st.caption(
        "Create multi-character cartoon shorts from a simple idea or manual timeline editor, then export dual MP4 outputs."
    )

    setup_col, control_col = st.columns([0.7, 0.3], gap="large")
    with setup_col:
        topic = st.text_input("Topic", placeholder="e.g. How RAG works in production", key="cartoon_topic_input")
        idea = st.text_area(
            "Idea / Hook",
            placeholder="e.g. Two bots debate why naive retrieval fails and how reranking fixes it.",
            height=96,
            key="cartoon_idea_input",
        )
        st.radio(
            "Timeline Source",
            options=["idea", "manual"],
            index=0,
            horizontal=True,
            key="cartoon_timeline_mode",
            format_func=lambda value: "Idea to Script" if value == "idea" else "Manual Timeline JSON",
        )
        if str(st.session_state.get("cartoon_timeline_mode", "idea")).strip().lower() == "manual":
            st.text_area(
                "Manual Timeline JSON",
                height=220,
                key="cartoon_manual_timeline_json",
                placeholder='{"scenes":[{"scene_index":1,"title":"Intro","turns":[{"speaker_id":"ava","speaker_name":"Ava","text":"Hello"}]}]}',
            )

    with control_col:
        st.markdown("#### Render Controls")
        st.selectbox("Short Type", options=_SHORT_TYPES, index=0, key="cartoon_short_type")
        st.slider("Scenes", min_value=2, max_value=10, value=4, step=1, key="cartoon_scene_count")
        st.slider("Characters", min_value=2, max_value=4, value=2, step=1, key="cartoon_speaker_count")
        st.selectbox("Output Mode", options=_OUTPUT_MODES, index=0, key="cartoon_output_mode")
        st.selectbox("Timeline Schema Version", options=_TIMELINE_SCHEMA_OPTIONS, index=0, key="cartoon_timeline_schema_version")
        st.selectbox("Quality Tier", options=_QUALITY_TIERS, index=0, key="cartoon_quality_tier")
        st.selectbox("Render Style", options=_RENDER_STYLES, index=0, key="cartoon_render_style")
        st.selectbox("Background Style", options=_BACKGROUND_STYLES, index=0, key="cartoon_background_style")
        st.selectbox("Language", options=_LANGUAGES, index=0, key="cartoon_language")
        st.checkbox("Use Hinglish Script", value=False, key="cartoon_hinglish_script")
        st.checkbox("Cinematic Story Mode", value=True, key="cartoon_cinematic_story_mode")
        generate = st.button("Generate Cartoon Shorts Asset", type="primary", key="cartoon_generate_btn", width="stretch")

    if generate:
        if not settings.has_api_key():
            st.error("Please enter your Groq API key in the sidebar.")
            st.stop()
        if not settings.has_model():
            st.error("Please select or enter a valid model.")
            st.stop()
        topic_clean = " ".join(str(topic).split()).strip()
        if not topic_clean:
            st.error("Please enter a topic.")
            st.stop()

        idea_clean = " ".join(str(idea).split()).strip()
        short_type = str(st.session_state.get("cartoon_short_type", _SHORT_TYPES[0])).strip().lower()
        scene_count = int(st.session_state.get("cartoon_scene_count", 4))
        speaker_count = int(st.session_state.get("cartoon_speaker_count", 2))
        output_mode = str(st.session_state.get("cartoon_output_mode", "dual")).strip().lower()
        timeline_schema_version = str(st.session_state.get("cartoon_timeline_schema_version", "v2")).strip().lower()
        quality_tier = str(st.session_state.get("cartoon_quality_tier", "auto")).strip().lower()
        render_style = str(st.session_state.get("cartoon_render_style", "scene")).strip().lower()
        background_style = str(st.session_state.get("cartoon_background_style", "auto")).strip().lower()
        language = str(st.session_state.get("cartoon_language", "en")).strip().lower()
        hinglish_script = bool(st.session_state.get("cartoon_hinglish_script", False))
        cinematic_story_mode = bool(st.session_state.get("cartoon_cinematic_story_mode", True))
        timeline_mode = str(st.session_state.get("cartoon_timeline_mode", "idea")).strip().lower()
        manual_json = str(st.session_state.get("cartoon_manual_timeline_json", "") or "")

        manual_timeline = _parse_manual_timeline(manual_json) if timeline_mode == "manual" else None
        if timeline_mode == "manual" and manual_timeline is None:
            st.error("Manual timeline JSON is invalid. Please correct it.")
            st.stop()

        def _worker(context: BackgroundJobContext) -> dict[str, Any]:
            context.update_progress(progress=0.08, message="Script Generation")
            result = cartoon_service.generate(
                topic=topic_clean,
                idea=idea_clean,
                short_type=short_type,
                scene_count=scene_count,
                speaker_count=speaker_count,
                output_mode=output_mode,
                language=language,
                use_hinglish_script=hinglish_script,
                manual_timeline=manual_timeline,
                timeline_schema_version=timeline_schema_version,
                quality_tier=quality_tier,
                render_style=render_style,
                background_style=background_style,
                settings=settings,
            )
            context.raise_if_cancelled()
            payload = result.cartoon_payload if isinstance(result.cartoon_payload, dict) else {}

            audio_bytes: bytes | None = None
            audio_error: str | None = None
            outputs: dict[str, bytes] = {}
            export_error: str | None = None

            if not result.parse_error and payload:
                context.update_progress(progress=0.34, message="Voice Synthesis")
                audio_bytes, audio_error, segments = cartoon_audio_service.synthesize_timeline_audio(
                    topic=topic_clean,
                    title=str(payload.get("title", "")),
                    timeline=cast(CartoonTimeline, payload.get("timeline", {})),
                    character_roster=cast(list[dict[str, object]], payload.get("character_roster", [])),
                    language=language,
                    slow=False,
                )
                lipsync_service = VideoAvatarLipsyncService()
                metadata = payload.get("metadata", {})
                metadata_map: dict[str, JSONValue] = {}
                if isinstance(metadata, dict):
                    metadata_map.update(cast(dict[str, JSONValue], metadata))
                metadata_map["audio_b64"] = (
                    base64.b64encode(audio_bytes).decode("utf-8")
                    if isinstance(audio_bytes, (bytes, bytearray))
                    else ""
                )
                metadata_map["cinematic_story_mode"] = cinematic_story_mode
                metadata_map["audio_error"] = audio_error or ""
                metadata_map["audio_segments"] = _segments_json(segments, lipsync_service=lipsync_service)
                metadata_map["audio_timing_source"] = "timeline_audio_segments"
                metadata_map["mouth_cue_source"] = "heuristic_or_rhubarb"
                metadata_map["render_style"] = render_style
                metadata_map["background_style"] = background_style
                payload["metadata"] = metadata_map
                context.raise_if_cancelled()

                context.update_progress(progress=0.62, message="Render 9:16")
                if output_mode in {"dual", "shorts_9_16"}:
                    outputs_9x16, error_9x16 = cartoon_exporter.build_cartoon_mp4s(
                        topic=topic_clean,
                        cartoon_payload=payload,
                        output_mode="shorts_9_16",
                    )
                    outputs.update(outputs_9x16)
                    if error_9x16:
                        export_error = error_9x16
                context.raise_if_cancelled()
                context.update_progress(progress=0.82, message="Render 16:9")
                if output_mode in {"dual", "widescreen_16_9"}:
                    outputs_16x9, error_16x9 = cartoon_exporter.build_cartoon_mp4s(
                        topic=topic_clean,
                        cartoon_payload=payload,
                        output_mode="widescreen_16_9",
                    )
                    outputs.update(outputs_16x9)
                    if error_16x9 and not export_error:
                        export_error = error_16x9

            context.raise_if_cancelled()
            context.update_progress(progress=1.0, message="Packaging")
            return {
                "topic": topic_clean,
                "idea": idea_clean,
                "result": result,
                "outputs": outputs,
                "audio_error": audio_error or "",
                "export_error": export_error or "",
                "language": language,
                "short_type": short_type,
                "scene_count": scene_count,
                "speaker_count": speaker_count,
                "output_mode": output_mode,
                "timeline_schema_version": timeline_schema_version,
                "quality_tier": quality_tier,
                "render_style": render_style,
                "background_style": background_style,
                "hinglish_script": hinglish_script,
                "cinematic_story_mode": cinematic_story_mode,
                "timeline_mode": timeline_mode,
            }

        job_id = job_manager.submit(
            label=f"Cartoon Shorts: {topic_clean}",
            worker=_worker,
            metadata={
                "asset": "cartoon_shorts",
                "topic": topic_clean,
                "short_type": short_type,
                "output_mode": output_mode,
                "timeline_schema_version": timeline_schema_version,
                "quality_tier": quality_tier,
                "render_style": render_style,
                "background_style": background_style,
            },
        )
        st.session_state.cartoon_background_job_id = job_id
        st.session_state.cartoon_background_job_applied_id = ""
        st.info("Cartoon shorts request queued in background.")
        st.rerun()

    active_job_id = str(st.session_state.get("cartoon_background_job_id", "")).strip()
    if active_job_id:
        replacement = render_background_job_panel(
            manager=job_manager,
            job_id=active_job_id,
            title="Cartoon Shorts Generation Job",
            key_prefix="cartoon_background_job",
        )
        if replacement != active_job_id:
            st.session_state.cartoon_background_job_id = replacement
            st.session_state.cartoon_background_job_applied_id = ""
            st.rerun()

    _apply_cartoon_job_result(
        job_manager=job_manager,
        llm_service=llm_service,
        cache_count_placeholder=cache_count_placeholder,
    )

    payload = st.session_state.get("cartoon_payload")
    if not isinstance(payload, dict) or not payload:
        return
    render_cartoon_view(
        topic=str(st.session_state.get("cartoon_topic", payload.get("topic", "Cartoon Shorts"))),
        cartoon_payload=cast(CartoonPayload, payload),
        config=CartoonRenderConfig(
            build_button_key="cartoon_build_outputs_btn",
            outputs_state_key="cartoon_outputs",
            output_error_state_key="cartoon_output_error",
            download_script_key="cartoon_download_script_md",
            download_project_key="cartoon_download_project_json",
            download_shorts_key="cartoon_download_shorts_mp4",
            download_widescreen_key="cartoon_download_widescreen_mp4",
        ),
        build_cartoon_fn=lambda topic_name, cartoon_data: cartoon_exporter.build_cartoon_mp4s(
            topic=topic_name,
            cartoon_payload=cartoon_data,
            output_mode=str(cartoon_data.get("output_mode", "dual")),
        ),
        initial_outputs=cast(dict[str, bytes] | None, st.session_state.get("cartoon_outputs")),
        initial_error=str(st.session_state.get("cartoon_output_error", "")),
    )


def _apply_cartoon_job_result(
    *,
    job_manager: BackgroundJobManager,
    llm_service: CachedLLMService,
    cache_count_placeholder: Any,
) -> None:
    job_id = str(st.session_state.get("cartoon_background_job_id", "")).strip()
    if not job_id:
        return
    snapshot = job_manager.get_snapshot(job_id)
    if snapshot is None or not snapshot.is_terminal:
        return
    applied_id = str(st.session_state.get("cartoon_background_job_applied_id", "")).strip()
    if applied_id == job_id:
        return
    st.session_state.cartoon_background_job_applied_id = job_id

    if snapshot.status == "cancelled":
        st.warning("Cartoon shorts generation was cancelled.")
        return
    if snapshot.status == "failed":
        st.error(f"Cartoon shorts generation failed: {snapshot.error or 'Unknown error'}")
        return

    payload = snapshot.result
    if not isinstance(payload, dict):
        st.error("Cartoon shorts background job returned unexpected payload.")
        return
    result = payload.get("result")
    if result is None:
        st.error("Cartoon shorts background job did not return generation result.")
        return

    parse_notes = list(getattr(result, "parse_notes", []))
    parse_error = str(getattr(result, "parse_error", "") or "").strip()
    debug_raw = str(getattr(result, "debug_raw", "") or "").strip()
    cartoon_payload = getattr(result, "cartoon_payload", None)
    total_calls = int(getattr(result, "total_calls", 0) or 0)
    cache_hits = int(getattr(result, "cache_hits", 0) or 0)

    for note in parse_notes:
        st.info(str(note))

    if parse_error or not isinstance(cartoon_payload, dict):
        st.error(parse_error or "Cartoon shorts generation failed.")
        if debug_raw:
            st.caption("Debug raw response:")
            st.code(debug_raw)
        return

    st.session_state.cartoon_topic = str(payload.get("topic", ""))
    st.session_state.cartoon_payload = cartoon_payload
    st.session_state.cartoon_outputs = dict(payload.get("outputs", {})) if isinstance(payload.get("outputs"), dict) else {}
    st.session_state.cartoon_output_error = str(payload.get("export_error", "") or "")
    st.session_state.cartoon_audio_error = str(payload.get("audio_error", "") or "")
    st.success(
        f"Generated cartoon asset via {total_calls} LLM calls ({cache_hits} served from cache)."
    )
    if st.session_state.cartoon_audio_error:
        st.warning(st.session_state.cartoon_audio_error)
    if st.session_state.cartoon_output_error:
        st.warning(st.session_state.cartoon_output_error)
    cache_count_placeholder.caption(f"Cached responses: {llm_service.count}")


def _parse_manual_timeline(raw_json: str) -> CartoonTimeline | None:
    text = str(raw_json or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return cast(CartoonTimeline, parsed)


def _segments_json(
    segments: list[DialogueAudioSegment],
    *,
    lipsync_service: VideoAvatarLipsyncService | None = None,
) -> list[JSONValue]:
    output: list[JSONValue] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        mouth_cues: list[JSONValue] = []
        if lipsync_service is not None:
            cues, _ = lipsync_service.build_mouth_cues(segment=segment)
            for cue in cues:
                if not isinstance(cue, dict):
                    continue
                mouth_cues.append(
                    cast(
                        JSONValue,
                        {
                            "start_ms": int(cue.get("start_ms", 0) or 0),
                            "end_ms": int(cue.get("end_ms", 0) or 0),
                            "mouth": str(cue.get("mouth", "X") or "X"),
                        },
                    )
                )
        output.append(
            cast(
                JSONValue,
                {
                    "segment_ref": str(segment.get("segment_ref", "")),
                    "speaker": str(segment.get("speaker", "")),
                    "start_ms": int(segment.get("start_ms", 0) or 0),
                    "end_ms": int(segment.get("end_ms", 0) or 0),
                    "duration_ms": int(segment.get("duration_ms", 0) or 0),
                    "text": str(segment.get("text", "")),
                    "cache_hit": bool(segment.get("cache_hit", False)),
                    "mouth_cues": mouth_cues,
                },
            )
        )
    return output
