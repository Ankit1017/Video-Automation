from __future__ import annotations

from typing import Any, cast

import streamlit as st

from main_app.contracts import VideoPayload
from main_app.contracts import CartoonPayload
from main_app.models import AssetHistoryRecord
from main_app.ui.asset_history.context import AssetHistoryRenderContext
from main_app.ui.components.interactive_callbacks import (
    build_cartoon_build_callback,
    build_flashcard_explain_callback,
    build_quiz_callbacks,
    build_video_build_callback,
    build_video_synthesize_callback,
    first_non_empty_topic,
)
from main_app.ui.components import (
    CartoonRenderConfig,
    FlashcardsRenderConfig,
    QuizRenderConfig,
    SlideshowRenderConfig,
    VideoRenderConfig,
    render_flashcards_view,
    render_cartoon_view,
    render_quiz_view,
    render_slideshow_view,
    render_video_view,
)


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _video_payload(value: object) -> VideoPayload | None:
    if not isinstance(value, dict):
        return None
    return cast(VideoPayload, {str(key): item for key, item in value.items()})


def _cartoon_payload(value: object) -> CartoonPayload | None:
    if not isinstance(value, dict):
        return None
    return cast(CartoonPayload, {str(key): item for key, item in value.items()})


def render_flashcards_record(record: AssetHistoryRecord, context: AssetHistoryRenderContext) -> None:
    payload = record.result_payload if isinstance(record.result_payload, dict) else {}
    cards = _dict_list(payload.get("cards", []))
    if not cards:
        st.json(record.result_payload)
        return
    topic = first_non_empty_topic(record.topic, payload.get("topic", ""), fallback="Topic")
    scope = f"asset_history_flashcards_{record.id}"

    render_flashcards_view(
        topic=topic,
        cards=cards,
        settings=context.settings,
        config=FlashcardsRenderConfig(
            state_index_key=f"{scope}_index",
            state_show_answer_key=f"{scope}_show_answer",
            state_explanations_key=f"{scope}_explanations",
            prev_button_key=f"{scope}_prev",
            next_button_key=f"{scope}_next",
            see_answer_button_key_format=f"{scope}_see_{{index}}",
            explain_button_key_format=f"{scope}_explain_{{index}}",
            restart_button_key=f"{scope}_restart",
            shuffle_button_key=f"{scope}_shuffle",
            download_csv_key=f"{scope}_download_csv",
        ),
        explain_fn=build_flashcard_explain_callback(
            service=context.agent_dashboard_service,
            settings=context.settings,
        ),
        llm_service=context.llm_service,
        cache_count_placeholder=context.cache_count_placeholder,
        title="Agent Flashcards",
        subtitle=f"Based on {len(cards)} saved cards",
    )


def render_quiz_record(record: AssetHistoryRecord, context: AssetHistoryRenderContext) -> None:
    payload = record.result_payload if isinstance(record.result_payload, dict) else {}
    questions = _dict_list(payload.get("questions", []))
    if not questions:
        st.json(record.result_payload)
        return
    topic = first_non_empty_topic(record.topic, payload.get("topic", ""), fallback="Topic")
    scope = f"asset_history_quiz_{record.id}"
    quiz_callbacks = build_quiz_callbacks(
        service=context.agent_dashboard_service,
        settings=context.settings,
    )
    render_quiz_view(
        topic=topic,
        questions_raw=questions,
        settings=context.settings,
        config=QuizRenderConfig(
            state_key=f"{scope}_state",
            choice_key_format=f"{scope}_choice_{{index}}",
            hint_button_key_format=f"{scope}_hint_{{index}}",
            submit_button_key_format=f"{scope}_submit_{{index}}",
            explain_button_key_format=f"{scope}_explain_{{index}}",
            prev_button_key_format=f"{scope}_prev_{{index}}",
            next_button_key_format=f"{scope}_next_{{index}}",
            template_select_key=f"{scope}_pdf_template",
            download_pdf_key=f"{scope}_download_pdf",
            download_pdf_disabled_key=f"{scope}_download_pdf_disabled",
        ),
        hint_fn=quiz_callbacks.hint_fn,
        feedback_fn=quiz_callbacks.feedback_fn,
        explain_fn=quiz_callbacks.explain_fn,
        quiz_exporter=context.quiz_exporter,
        llm_service=context.llm_service,
        cache_count_placeholder=context.cache_count_placeholder,
    )


def render_slideshow_record(record: AssetHistoryRecord, context: AssetHistoryRenderContext) -> None:
    payload = record.result_payload if isinstance(record.result_payload, dict) else {}
    slides = _dict_list(payload.get("slides", []))
    if not slides:
        st.json(record.result_payload)
        return
    topic = record.topic or str(record.request_payload.get("topic", "")).strip() or "Slideshow"
    scope = f"asset_history_slideshow_{record.id}"
    render_slideshow_view(
        topic=topic,
        slides=slides,
        config=SlideshowRenderConfig(
            state_index_key=f"{scope}_index",
            jump_key_format=f"{scope}_jump_{{index}}",
            prev_button_key_format=f"{scope}_prev_{{index}}",
            next_button_key_format=f"{scope}_next_{{index}}",
            download_md_key=f"{scope}_download_md",
            download_json_key=f"{scope}_download_json",
            download_pptx_key=f"{scope}_download_pptx",
            download_pptx_disabled_key=f"{scope}_download_pptx_disabled",
            download_pdf_key=f"{scope}_download_pdf",
            download_pdf_disabled_key=f"{scope}_download_pdf_disabled",
            template_select_key=f"{scope}_download_pptx_template",
        ),
        slide_exporter=context.slide_exporter,
    )


def render_video_record(record: AssetHistoryRecord, context: AssetHistoryRenderContext) -> None:
    payload = record.result_payload if isinstance(record.result_payload, dict) else {}
    video_payload = _video_payload(payload)
    if not video_payload:
        st.json(record.result_payload)
        return

    topic = first_non_empty_topic(record.topic, video_payload.get("topic", ""), fallback="Video")
    scope = f"asset_history_video_{record.id}"
    render_video_view(
        topic=topic,
        video_payload=video_payload,
        config=VideoRenderConfig(
            slideshow=SlideshowRenderConfig(
                state_index_key=f"{scope}_index",
                jump_key_format=f"{scope}_jump_{{index}}",
                prev_button_key_format=f"{scope}_prev_{{index}}",
                next_button_key_format=f"{scope}_next_{{index}}",
                download_md_key=f"{scope}_slides_md",
                download_json_key=f"{scope}_slides_json",
                download_pptx_key=f"{scope}_slides_pptx",
                download_pptx_disabled_key=f"{scope}_slides_pptx_disabled",
                download_pdf_key=f"{scope}_slides_pdf",
                download_pdf_disabled_key=f"{scope}_slides_pdf_disabled",
                template_select_key=f"{scope}_slides_template",
            ),
            language_select_key=f"{scope}_language",
            slow_checkbox_key=f"{scope}_slow",
            regenerate_audio_key=f"{scope}_regen_audio",
            audio_state_bytes_key=f"{scope}_audio_bytes",
            audio_state_error_key=f"{scope}_audio_error",
            download_script_md_key=f"{scope}_script_md",
            download_script_json_key=f"{scope}_script_json",
            download_audio_key=f"{scope}_audio_dl",
            download_audio_disabled_key=f"{scope}_audio_dl_disabled",
            regenerate_video_key=f"{scope}_regen_video",
            video_state_bytes_key=f"{scope}_video_bytes",
            video_state_error_key=f"{scope}_video_error",
            download_video_key=f"{scope}_video_download",
            download_video_disabled_key=f"{scope}_video_download_disabled",
        ),
        slide_exporter=context.slide_exporter,
        synthesize_audio_fn=build_video_synthesize_callback(context.video_service),
        build_video_fn=build_video_build_callback(context.video_exporter),
    )


def render_cartoon_record(record: AssetHistoryRecord, context: AssetHistoryRenderContext) -> None:
    payload = record.result_payload if isinstance(record.result_payload, dict) else {}
    cartoon_payload = _cartoon_payload(payload)
    if not cartoon_payload:
        st.json(record.result_payload)
        return

    topic = first_non_empty_topic(record.topic, cartoon_payload.get("topic", ""), fallback="Cartoon Shorts")
    scope = f"asset_history_cartoon_{record.id}"
    render_cartoon_view(
        topic=topic,
        cartoon_payload=cartoon_payload,
        config=CartoonRenderConfig(
            build_button_key=f"{scope}_build",
            outputs_state_key=f"{scope}_outputs",
            output_error_state_key=f"{scope}_output_error",
            download_script_key=f"{scope}_script",
            download_project_key=f"{scope}_project",
            download_shorts_key=f"{scope}_shorts",
            download_widescreen_key=f"{scope}_widescreen",
        ),
        build_cartoon_fn=build_cartoon_build_callback(context.cartoon_exporter),
    )
