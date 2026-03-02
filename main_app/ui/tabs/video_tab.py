from __future__ import annotations

from typing import Any, Literal, cast

import streamlit as st

from main_app.contracts import VideoPayload
from main_app.models import GroqSettings
from main_app.services.background_jobs import BackgroundJobContext, BackgroundJobManager
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.slide_deck_exporter import SlideDeckExporter
from main_app.services.video_asset_service import VideoAssetService
from main_app.services.video_exporter import VideoExporter
from main_app.ui.components import (
    SlideshowRenderConfig,
    VideoRenderConfig,
    render_background_job_panel,
    render_video_view,
)
from main_app.ui.error_handling import UI_HANDLED_EXCEPTIONS, report_ui_error


_VIDEO_DEFAULT_CODE_MODE: Literal["auto", "force", "none"] = "auto"
_VIDEO_DEFAULT_REPRESENTATION_MODE = "visual"
_VIDEO_DEFAULT_SPEAKER_COUNT = 2
_VIDEO_DEFAULT_CONVERSATION_STYLE = "Educational Discussion"
_VIDEO_DEFAULT_TEMPLATE = "youtube"
_VIDEO_DEFAULT_USE_YOUTUBE_PROMPT = True
_VIDEO_DEFAULT_USE_HINGLISH_SCRIPT = False
_VIDEO_DEFAULT_SLOW_AUDIO = False
_VIDEO_DEFAULT_ANIMATION_STYLE = "none"
_VIDEO_DEFAULT_RENDER_MODE: Literal["avatar_conversation", "classic_slides"] = "avatar_conversation"
_VIDEO_DEFAULT_AVATAR_ENABLE_SUBTITLES = True
_VIDEO_DEFAULT_AVATAR_STYLE_PACK = "default"
_VIDEO_DEFAULT_AVATAR_ALLOW_FALLBACK = True


def _resolve_initial_playback_language(*, selected_language: str, use_hinglish_script: bool) -> str:
    if use_hinglish_script:
        return "hi"
    return " ".join(str(selected_language).split()).strip() or "en"


VIDEO_TAB_CSS = """
<style>
    .video-title {
        font-size: 1.9rem;
        font-weight: 760;
        color: #0f172a;
        margin: 2px 0 2px 0;
    }
    .video-subtitle {
        color: #475569;
        margin: 0 0 12px 0;
    }
</style>
"""


def render_video_tab(
    *,
    video_service: VideoAssetService,
    llm_service: CachedLLMService,
    settings: GroqSettings,
    cache_count_placeholder: Any,
    slide_exporter: SlideDeckExporter,
    video_exporter: VideoExporter,
    job_manager: BackgroundJobManager,
) -> None:
    st.markdown(VIDEO_TAB_CSS, unsafe_allow_html=True)
    st.markdown('<div class="video-title">Video Builder</div>', unsafe_allow_html=True)
    st.markdown(
        (
            '<div class="video-subtitle">'
            "Generate a slide deck first, then create per-slide narration scripts and synthesize "
            "a single multi-voice audio track aligned to the deck."
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    setup_col, control_col = st.columns([0.72, 0.28], gap="large")
    with setup_col:
        topic = st.text_input(
            "Video Topic",
            placeholder="e.g. CDC Pipeline: from source DB to near-real-time analytics",
            key="video_topic_input",
        )
        constraints = st.text_area(
            "Optional Video Constraints",
            placeholder="e.g. Keep practical, include architecture trade-offs and one code walkthrough.",
            height=90,
            key="video_constraints",
        )

    with control_col:
        st.markdown("#### Video Controls")
        st.caption("YouTube style defaults are applied automatically for simpler generation.")
        subtopic_count = st.slider(
            "Subtopics",
            min_value=2,
            max_value=10,
            value=5,
            step=1,
            key="video_subtopic_count",
        )
        slides_per_subtopic = st.slider(
            "Slides per Subtopic",
            min_value=1,
            max_value=3,
            value=2,
            step=1,
            key="video_slides_per_subtopic",
        )
        st.selectbox(
            "Last Audio Language",
            options=["en", "hi", "es", "fr", "de", "ja"],
            index=0,
            key="video_language",
        )
        st.selectbox(
            "Animation Style",
            options=["youtube_dynamic", "smooth", "none"],
            index=2,
            key="video_animation_style",
            format_func=lambda value: {
                "none": "None (Static Slides)",
                "smooth": "Smooth (Ken Burns + Fade)",
                "youtube_dynamic": "YouTube Dynamic (Reveals + Fast Motion)",
            }[value],
        )
        with st.expander("Advanced Avatar Settings", expanded=False):
            st.selectbox(
                "Render Mode",
                options=["avatar_conversation", "classic_slides"],
                index=0,
                key="video_render_mode",
                format_func=lambda value: {
                    "avatar_conversation": "Avatar Conversation (Default)",
                    "classic_slides": "Classic Slides",
                }.get(value, value),
            )
            st.checkbox(
                "Enable subtitles",
                value=_VIDEO_DEFAULT_AVATAR_ENABLE_SUBTITLES,
                key="video_avatar_enable_subtitles",
            )
            st.selectbox(
                "Avatar style pack",
                options=["default", "compact"],
                index=0,
                key="video_avatar_style_pack",
                format_func=lambda value: value.title(),
            )
            st.checkbox(
                "Auto fallback to classic on avatar failure",
                value=_VIDEO_DEFAULT_AVATAR_ALLOW_FALLBACK,
                key="video_avatar_allow_fallback",
            )
        generate_video = st.button(
            "Generate Video Asset",
            key="video_generate_btn",
            type="primary",
            width="stretch",
        )

    if generate_video:
        if not settings.has_api_key():
            st.error("Please enter your Groq API key in the sidebar.")
            st.stop()
        if not settings.has_model():
            st.error("Please select or enter a valid model.")
            st.stop()
        if not topic or not topic.strip():
            st.error("Please enter a topic.")
            st.stop()

        topic_clean = topic.strip()
        constraints_clean = constraints.strip()
        selected_playback_language = str(st.session_state.video_language)
        playback_slow = _VIDEO_DEFAULT_SLOW_AUDIO
        video_template = _VIDEO_DEFAULT_TEMPLATE
        animation_style = str(st.session_state.video_animation_style or _VIDEO_DEFAULT_ANIMATION_STYLE).strip().lower() or _VIDEO_DEFAULT_ANIMATION_STYLE
        representation_mode = _VIDEO_DEFAULT_REPRESENTATION_MODE
        use_youtube_prompt = _VIDEO_DEFAULT_USE_YOUTUBE_PROMPT
        use_hinglish_script = _VIDEO_DEFAULT_USE_HINGLISH_SCRIPT
        render_mode = str(st.session_state.video_render_mode or _VIDEO_DEFAULT_RENDER_MODE).strip().lower() or _VIDEO_DEFAULT_RENDER_MODE
        avatar_enable_subtitles = bool(st.session_state.video_avatar_enable_subtitles)
        avatar_style_pack = str(st.session_state.video_avatar_style_pack or _VIDEO_DEFAULT_AVATAR_STYLE_PACK).strip().lower() or _VIDEO_DEFAULT_AVATAR_STYLE_PACK
        avatar_allow_fallback = bool(st.session_state.video_avatar_allow_fallback)
        code_mode = _VIDEO_DEFAULT_CODE_MODE
        speaker_count = _VIDEO_DEFAULT_SPEAKER_COUNT
        conversation_style = _VIDEO_DEFAULT_CONVERSATION_STYLE
        playback_language = _resolve_initial_playback_language(
            selected_language=selected_playback_language,
            use_hinglish_script=use_hinglish_script,
        )

        def _worker(context: BackgroundJobContext) -> dict[str, Any]:
            context.update_progress(progress=0.1, message="Building slideshow and narration scripts...")
            result = video_service.generate(
                topic=topic_clean,
                constraints=constraints_clean,
                subtopic_count=subtopic_count,
                slides_per_subtopic=slides_per_subtopic,
                code_mode=code_mode,
                speaker_count=speaker_count,
                conversation_style=conversation_style,
                video_template=video_template,
                animation_style=animation_style,
                representation_mode=representation_mode,
                render_mode=cast(Literal["avatar_conversation", "classic_slides"], render_mode),
                avatar_enable_subtitles=avatar_enable_subtitles,
                avatar_style_pack=avatar_style_pack,
                avatar_allow_fallback=avatar_allow_fallback,
                use_youtube_prompt=use_youtube_prompt,
                use_hinglish_script=use_hinglish_script,
                settings=settings,
            )
            context.raise_if_cancelled()

            audio_bytes: bytes | None = None
            audio_error = ""
            video_bytes: bytes | None = None
            video_error = ""

            if not result.parse_error and result.video_payload:
                context.update_progress(progress=0.65, message="Synthesizing multi-voice narration...")
                audio_bytes, synth_error = video_service.synthesize_audio(
                    video_payload=result.video_payload,
                    language=playback_language,
                    slow=playback_slow,
                )
                audio_error = synth_error or ""
                context.raise_if_cancelled()

                if audio_bytes:
                    context.update_progress(progress=0.85, message="Rendering full video from slides + audio...")
                    video_bytes, render_error = video_exporter.build_video_mp4(
                        topic=topic_clean,
                        video_payload=result.video_payload,
                        audio_bytes=audio_bytes,
                        template_key=video_template,
                        animation_style=animation_style,
                        render_mode=render_mode,
                        allow_fallback=avatar_allow_fallback,
                    )
                    video_error = render_error or ""

            context.raise_if_cancelled()
            context.update_progress(progress=1.0, message="Video asset generation completed.")
            return {
                "topic": topic_clean,
                "constraints": constraints_clean,
                "language": playback_language,
                "slow_audio": playback_slow,
                "result": result,
                "audio_bytes": audio_bytes,
                "audio_error": audio_error,
                "video_bytes": video_bytes,
                "video_error": video_error,
                "video_template": video_template,
                "animation_style": animation_style,
                "representation_mode": representation_mode,
                "render_mode": render_mode,
                "avatar_enable_subtitles": avatar_enable_subtitles,
                "avatar_style_pack": avatar_style_pack,
                "avatar_allow_fallback": avatar_allow_fallback,
                "youtube_prompt": use_youtube_prompt,
                "use_hinglish_script": use_hinglish_script,
            }

        job_id = job_manager.submit(
            label=f"Video Asset: {topic_clean}",
            worker=_worker,
            metadata={"asset": "video", "topic": topic_clean},
        )
        st.session_state.video_background_job_id = job_id
        st.session_state.video_background_job_applied_id = ""
        st.info("Video asset request queued in background.")
        st.rerun()

    active_job_id = str(st.session_state.get("video_background_job_id", "")).strip()
    if active_job_id:
        replacement_job_id = render_background_job_panel(
            manager=job_manager,
            job_id=active_job_id,
            title="Video Generation Job",
            key_prefix="video_background_job",
        )
        if replacement_job_id != active_job_id:
            st.session_state.video_background_job_id = replacement_job_id
            st.session_state.video_background_job_applied_id = ""
            st.rerun()

    _apply_video_job_result(
        job_manager=job_manager,
        llm_service=llm_service,
        cache_count_placeholder=cache_count_placeholder,
    )

    payload = st.session_state.video_payload
    if not isinstance(payload, dict) or not payload:
        return

    if "video_playback_language" not in st.session_state:
        st.session_state.video_playback_language = str(st.session_state.video_language)
    if "video_playback_slow_audio" not in st.session_state:
        st.session_state.video_playback_slow_audio = bool(st.session_state.video_slow_audio)
    if "video_full_video_bytes" not in st.session_state:
        st.session_state.video_full_video_bytes = None
    if "video_full_video_error" not in st.session_state:
        st.session_state.video_full_video_error = ""

    render_video_view(
        topic=str(st.session_state.video_topic or payload.get("topic", "Video")).strip(),
        video_payload=cast(VideoPayload, payload),
        config=VideoRenderConfig(
            slideshow=SlideshowRenderConfig(
                state_index_key="video_slideshow_index",
                jump_key_format="video_slideshow_jump_{index}",
                prev_button_key_format="video_slideshow_prev_{index}",
                next_button_key_format="video_slideshow_next_{index}",
                download_md_key="video_slideshow_download_md",
                download_json_key="video_slideshow_download_json",
                download_pptx_key="video_slideshow_download_pptx",
                download_pptx_disabled_key="video_slideshow_download_pptx_disabled",
                download_pdf_key="video_slideshow_download_pdf",
                download_pdf_disabled_key="video_slideshow_download_pdf_disabled",
                template_select_key="video_slideshow_template_key",
            ),
            language_select_key="video_playback_language",
            slow_checkbox_key="video_playback_slow_audio",
            regenerate_audio_key="video_regenerate_audio_btn",
            audio_state_bytes_key="video_audio_bytes",
            audio_state_error_key="video_audio_error",
            download_script_md_key="video_download_script_md",
            download_script_json_key="video_download_script_json",
            download_audio_key="video_download_audio_mp3",
            download_audio_disabled_key="video_download_audio_mp3_disabled",
            regenerate_video_key="video_regenerate_full_video_btn",
            video_state_bytes_key="video_full_video_bytes",
            video_state_error_key="video_full_video_error",
            download_video_key="video_download_video_mp4",
            download_video_disabled_key="video_download_video_mp4_disabled",
        ),
        slide_exporter=slide_exporter,
        synthesize_audio_fn=lambda payload_data, language, slow: video_service.synthesize_audio(
            video_payload=payload_data,
            language=language,
            slow=slow,
        ),
        build_video_fn=lambda topic_name, payload_data, audio_data: video_exporter.build_video_mp4(
            topic=topic_name,
            video_payload=payload_data,
            audio_bytes=audio_data,
            template_key=str(payload_data.get("video_template", "standard")),
            animation_style=str(payload_data.get("animation_style", "smooth")),
            render_mode=str(payload_data.get("render_mode", "avatar_conversation")),
            allow_fallback=bool(
                cast(dict[str, Any], payload_data.get("metadata", {})).get("avatar_allow_fallback", True)
                if isinstance(payload_data.get("metadata", {}), dict)
                else True
            ),
        ),
        initial_audio_bytes=st.session_state.video_audio_bytes,
        initial_audio_error=st.session_state.video_audio_error,
        initial_video_bytes=st.session_state.video_full_video_bytes,
        initial_video_error=st.session_state.video_full_video_error,
    )


def _apply_video_job_result(
    *,
    job_manager: BackgroundJobManager,
    llm_service: CachedLLMService,
    cache_count_placeholder: Any,
) -> None:
    job_id = str(st.session_state.get("video_background_job_id", "")).strip()
    if not job_id:
        return
    snapshot = job_manager.get_snapshot(job_id)
    if snapshot is None or not snapshot.is_terminal:
        return

    applied_id = str(st.session_state.get("video_background_job_applied_id", "")).strip()
    if applied_id == job_id:
        return
    st.session_state.video_background_job_applied_id = job_id

    if snapshot.status == "cancelled":
        st.warning("Video generation was cancelled.")
        return
    if snapshot.status == "failed":
        st.error(f"Video generation failed: {snapshot.error or 'Unknown error'}")
        return

    payload = snapshot.result
    if not isinstance(payload, dict):
        st.error("Video background job returned unexpected payload.")
        return

    result = payload.get("result")
    if result is None:
        st.error("Video background job did not return generation result.")
        return

    try:
        parse_notes = list(getattr(result, "parse_notes", []))
        parse_error = str(getattr(result, "parse_error", "") or "").strip()
        debug_raw = str(getattr(result, "debug_raw", "") or "").strip()
        video_payload = getattr(result, "video_payload", None)
        total_calls = int(getattr(result, "total_calls", 0) or 0)
        cache_hits = int(getattr(result, "cache_hits", 0) or 0)
    except UI_HANDLED_EXCEPTIONS as exc:
        report_ui_error(action="video_apply_job_result", exc=exc)
        return

    for note in parse_notes:
        st.info(str(note))

    if parse_error or not isinstance(video_payload, dict):
        st.error(parse_error or "Video asset generation failed.")
        if debug_raw:
            st.caption("Debug raw response:")
            st.code(debug_raw)
        return

    topic = " ".join(str(payload.get("topic", "")).split()).strip()
    constraints = " ".join(str(payload.get("constraints", "")).split()).strip()
    language = " ".join(str(payload.get("language", "en")).split()).strip() or "en"
    slow_audio = bool(payload.get("slow_audio", False))
    video_template = " ".join(str(payload.get("video_template", "standard")).split()).strip().lower() or "standard"
    animation_style = " ".join(str(payload.get("animation_style", "smooth")).split()).strip().lower() or "smooth"
    representation_mode = " ".join(str(payload.get("representation_mode", "auto")).split()).strip().lower() or "auto"
    render_mode = " ".join(str(payload.get("render_mode", "avatar_conversation")).split()).strip().lower() or "avatar_conversation"
    avatar_enable_subtitles = bool(payload.get("avatar_enable_subtitles", True))
    avatar_style_pack = " ".join(str(payload.get("avatar_style_pack", "default")).split()).strip().lower() or "default"
    avatar_allow_fallback = bool(payload.get("avatar_allow_fallback", True))
    youtube_prompt = bool(payload.get("youtube_prompt", False))
    use_hinglish_script = bool(payload.get("use_hinglish_script", False))
    audio_bytes = payload.get("audio_bytes")
    audio_error = " ".join(str(payload.get("audio_error", "")).split()).strip()
    video_bytes = payload.get("video_bytes")
    video_error = " ".join(str(payload.get("video_error", "")).split()).strip()

    st.session_state.video_topic = topic
    st.session_state.video_payload = video_payload
    st.session_state.video_audio_bytes = audio_bytes if isinstance(audio_bytes, (bytes, bytearray)) else None
    st.session_state.video_audio_error = audio_error
    st.session_state.video_full_video_bytes = video_bytes if isinstance(video_bytes, (bytes, bytearray)) else None
    st.session_state.video_full_video_error = video_error
    st.session_state.video_last_constraints = constraints
    st.session_state.video_slideshow_index = 0
    st.session_state.video_playback_language = language
    st.session_state.video_playback_slow_audio = slow_audio
    # Avoid mutating widget-backed keys
    # (`video_template`, `video_use_youtube_prompt`, `video_use_hinglish_script`)
    # after those widgets are instantiated in this render pass.
    st.session_state.video_last_template = video_template
    st.session_state.video_last_animation_style = animation_style
    st.session_state.video_last_representation_mode = representation_mode
    st.session_state.video_last_render_mode = render_mode
    st.session_state.video_last_avatar_enable_subtitles = avatar_enable_subtitles
    st.session_state.video_last_avatar_style_pack = avatar_style_pack
    st.session_state.video_last_avatar_allow_fallback = avatar_allow_fallback
    st.session_state.video_last_youtube_prompt = youtube_prompt
    st.session_state.video_last_use_hinglish_script = use_hinglish_script

    slide_count = len(video_payload.get("slides", [])) if isinstance(video_payload.get("slides"), list) else 0
    st.success(
        f"Generated narrated deck with {slide_count} slides "
        f"via {total_calls} LLM calls ({cache_hits} served from cache)."
    )
    if audio_error:
        st.warning(audio_error)
    if video_error:
        st.warning(video_error)
    cache_count_placeholder.caption(f"Cached responses: {llm_service.count}")
