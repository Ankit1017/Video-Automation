from __future__ import annotations

from typing import Any, cast

from main_app.contracts import IntentPayload
from main_app.contracts import VideoPayload
from main_app.ui.agent_dashboard.context import AgentAssetRenderContext
from main_app.ui.agent_dashboard.handlers.types import AgentAsset
from main_app.ui.components.interactive_callbacks import (
    build_flashcard_explain_callback,
    build_quiz_callbacks,
    build_video_build_callback,
    build_video_synthesize_callback,
    first_non_empty_topic,
)
from main_app.ui.components import (
    FlashcardsRenderConfig,
    QuizRenderConfig,
    SlideshowRenderConfig,
    VideoRenderConfig,
    render_flashcards_view,
    render_quiz_view,
    render_slideshow_view,
    render_video_view,
)


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_video_payload(value: object) -> VideoPayload:
    if not isinstance(value, dict):
        return {}
    return cast(VideoPayload, value)


def render_flashcards_asset(
    context: AgentAssetRenderContext,
    scope: str,
    payload: IntentPayload,
    content: object,
    asset: AgentAsset,
) -> None:
    del asset
    cards = _dict_list((content or {}).get("cards", []) if isinstance(content, dict) else [])
    topic = first_non_empty_topic(
        payload.get("topic", ""),
        (content or {}).get("topic", "") if isinstance(content, dict) else "",
        fallback="Topic",
    )
    render_flashcards_view(
        topic=topic,
        cards=cards,
        settings=context.settings,
        config=FlashcardsRenderConfig(
            state_index_key=f"agent_dashboard_flashcards_index_{scope}",
            state_show_answer_key=f"agent_dashboard_flashcards_show_answer_{scope}",
            state_explanations_key=f"agent_dashboard_flashcards_explanations_{scope}",
            prev_button_key=f"agent_dashboard_flash_prev_{scope}",
            next_button_key=f"agent_dashboard_flash_next_{scope}",
            see_answer_button_key_format=f"agent_dashboard_flash_show_{scope}" + "_{index}",
            explain_button_key_format=f"agent_dashboard_flash_explain_{scope}" + "_{index}",
            restart_button_key=f"agent_dashboard_flash_restart_{scope}",
            shuffle_button_key=f"agent_dashboard_flash_shuffle_{scope}",
            download_csv_key=f"agent_dashboard_flashcards_download_csv_{scope}",
        ),
        explain_fn=build_flashcard_explain_callback(
            service=context.agent_dashboard_service,
            settings=context.settings,
        ),
        llm_service=context.llm_service,
        cache_count_placeholder=context.cache_count_placeholder,
    )


def render_quiz_asset(
    context: AgentAssetRenderContext,
    scope: str,
    payload: IntentPayload,
    content: object,
    asset: AgentAsset,
) -> None:
    del asset
    questions_raw = _dict_list((content or {}).get("questions", []) if isinstance(content, dict) else [])
    topic = first_non_empty_topic(
        payload.get("topic", ""),
        (content or {}).get("topic", "") if isinstance(content, dict) else "",
        fallback="Topic",
    )
    quiz_callbacks = build_quiz_callbacks(
        service=context.agent_dashboard_service,
        settings=context.settings,
    )
    render_quiz_view(
        topic=topic,
        questions_raw=questions_raw,
        settings=context.settings,
        config=QuizRenderConfig(
            state_key=f"agent_dashboard_quiz_state_{scope}",
            choice_key_format=f"agent_dashboard_quiz_choice_{scope}" + "_{index}",
            hint_button_key_format=f"agent_dashboard_quiz_hint_{scope}" + "_{index}",
            submit_button_key_format=f"agent_dashboard_quiz_submit_{scope}" + "_{index}",
            explain_button_key_format=f"agent_dashboard_quiz_explain_{scope}" + "_{index}",
            prev_button_key_format=f"agent_dashboard_quiz_prev_{scope}" + "_{index}",
            next_button_key_format=f"agent_dashboard_quiz_next_{scope}" + "_{index}",
            template_select_key=f"agent_dashboard_quiz_pdf_template_{scope}",
            download_pdf_key=f"agent_dashboard_quiz_download_pdf_{scope}",
            download_pdf_disabled_key=f"agent_dashboard_quiz_download_pdf_disabled_{scope}",
        ),
        hint_fn=quiz_callbacks.hint_fn,
        feedback_fn=quiz_callbacks.feedback_fn,
        explain_fn=quiz_callbacks.explain_fn,
        quiz_exporter=context.quiz_exporter,
        llm_service=context.llm_service,
        cache_count_placeholder=context.cache_count_placeholder,
    )


def render_slideshow_asset(
    context: AgentAssetRenderContext,
    scope: str,
    payload: IntentPayload,
    content: object,
    asset: AgentAsset,
) -> None:
    del asset
    slides = _dict_list((content or {}).get("slides", []) if isinstance(content, dict) else [])
    topic = str(payload.get("topic", "")).strip() or "Slideshow"
    render_slideshow_view(
        topic=topic,
        slides=slides,
        config=SlideshowRenderConfig(
            state_index_key=f"agent_dashboard_slideshow_index_{scope}",
            jump_key_format=f"agent_dashboard_slideshow_jump_{scope}" + "_{index}",
            prev_button_key_format=f"agent_dashboard_slideshow_prev_{scope}" + "_{index}",
            next_button_key_format=f"agent_dashboard_slideshow_next_{scope}" + "_{index}",
            download_md_key=f"agent_dashboard_slideshow_download_md_{scope}",
            download_json_key=f"agent_dashboard_slideshow_download_json_{scope}",
            download_pptx_key=f"agent_dashboard_slideshow_download_pptx_{scope}",
            download_pptx_disabled_key=f"agent_dashboard_slideshow_download_pptx_disabled_{scope}",
            download_pdf_key=f"agent_dashboard_slideshow_download_pdf_{scope}",
            download_pdf_disabled_key=f"agent_dashboard_slideshow_download_pdf_disabled_{scope}",
            template_select_key=f"agent_dashboard_slideshow_pptx_template_{scope}",
        ),
        slide_exporter=context.slide_exporter,
    )


def render_video_asset(
    context: AgentAssetRenderContext,
    scope: str,
    payload: IntentPayload,
    content: object,
    asset: AgentAsset,
) -> None:
    topic = str(payload.get("topic", "")).strip() or "Video"
    video_payload = _as_video_payload(content)
    render_video_view(
        topic=topic,
        video_payload=video_payload,
        config=VideoRenderConfig(
            slideshow=SlideshowRenderConfig(
                state_index_key=f"agent_dashboard_video_index_{scope}",
                jump_key_format=f"agent_dashboard_video_jump_{scope}" + "_{index}",
                prev_button_key_format=f"agent_dashboard_video_prev_{scope}" + "_{index}",
                next_button_key_format=f"agent_dashboard_video_next_{scope}" + "_{index}",
                download_md_key=f"agent_dashboard_video_slides_md_{scope}",
                download_json_key=f"agent_dashboard_video_slides_json_{scope}",
                download_pptx_key=f"agent_dashboard_video_slides_pptx_{scope}",
                download_pptx_disabled_key=f"agent_dashboard_video_slides_pptx_disabled_{scope}",
                download_pdf_key=f"agent_dashboard_video_slides_pdf_{scope}",
                download_pdf_disabled_key=f"agent_dashboard_video_slides_pdf_disabled_{scope}",
                template_select_key=f"agent_dashboard_video_slides_template_{scope}",
            ),
            language_select_key=f"agent_dashboard_video_language_{scope}",
            slow_checkbox_key=f"agent_dashboard_video_slow_{scope}",
            regenerate_audio_key=f"agent_dashboard_video_regen_audio_{scope}",
            audio_state_bytes_key=f"agent_dashboard_video_audio_bytes_{scope}",
            audio_state_error_key=f"agent_dashboard_video_audio_error_{scope}",
            download_script_md_key=f"agent_dashboard_video_script_md_{scope}",
            download_script_json_key=f"agent_dashboard_video_script_json_{scope}",
            download_audio_key=f"agent_dashboard_video_audio_dl_{scope}",
            download_audio_disabled_key=f"agent_dashboard_video_audio_dl_disabled_{scope}",
            regenerate_video_key=f"agent_dashboard_video_regen_full_video_{scope}",
            video_state_bytes_key=f"agent_dashboard_video_bytes_{scope}",
            video_state_error_key=f"agent_dashboard_video_error_{scope}",
            download_video_key=f"agent_dashboard_video_download_mp4_{scope}",
            download_video_disabled_key=f"agent_dashboard_video_download_mp4_disabled_{scope}",
        ),
        slide_exporter=context.slide_exporter,
        synthesize_audio_fn=build_video_synthesize_callback(context.video_service),
        build_video_fn=build_video_build_callback(context.video_exporter),
        initial_audio_bytes=(
            asset.get("audio_bytes")
            if isinstance(asset.get("audio_bytes"), (bytes, bytearray))
            else None
        ),
        initial_audio_error=str(asset.get("audio_error", "")).strip(),
    )
