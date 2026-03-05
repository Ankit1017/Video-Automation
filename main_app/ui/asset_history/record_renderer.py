from __future__ import annotations

from typing import Any

import streamlit as st

from main_app.models import AssetHistoryRecord, GroqSettings
from main_app.services.agent_dashboard import AgentDashboardService
from main_app.services.audio_overview_service import AudioOverviewService
from main_app.services.asset_history_service import AssetHistoryService
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.cartoon_exporter import CartoonExporter
from main_app.services.cartoon_shorts_asset_service import CartoonShortsAssetService
from main_app.services.quiz_exporter import QuizExporter
from main_app.services.report_exporter import ReportExporter
from main_app.services.slide_deck_exporter import SlideDeckExporter
from main_app.services.video_asset_service import VideoAssetService
from main_app.services.video_exporter import VideoExporter
from main_app.services.agent_dashboard import ASSET_HISTORY_ORDER
from main_app.ui.asset_history.context import AssetHistoryRenderContext, RendererFn
from main_app.ui.asset_history.renderer_registry import build_record_renderers, render_default_record
from main_app.ui.tabs.audio_overview_tab import AUDIO_OVERVIEW_TAB_CSS
from main_app.ui.tabs.flashcards_tab import FLASHCARDS_CSS
from main_app.ui.tabs.quiz_tab import QUIZ_TAB_CSS
from main_app.ui.tabs.slideshow_tab import SLIDESHOW_TAB_CSS


def render_asset_history_tab(
    *,
    asset_history_service: AssetHistoryService,
    settings: GroqSettings,
    llm_service: CachedLLMService,
    cache_count_placeholder: Any,
    agent_dashboard_service: AgentDashboardService,
    audio_overview_service: AudioOverviewService,
    video_service: VideoAssetService,
    quiz_exporter: QuizExporter,
    report_exporter: ReportExporter,
    slide_exporter: SlideDeckExporter,
    video_exporter: VideoExporter,
    cartoon_service: CartoonShortsAssetService,
    cartoon_exporter: CartoonExporter,
    custom_renderers: dict[str, RendererFn] | None = None,
) -> None:
    context = AssetHistoryRenderContext(
        settings=settings,
        llm_service=llm_service,
        cache_count_placeholder=cache_count_placeholder,
        agent_dashboard_service=agent_dashboard_service,
        audio_overview_service=audio_overview_service,
        quiz_exporter=quiz_exporter,
        report_exporter=report_exporter,
        slide_exporter=slide_exporter,
        video_service=video_service,
        video_exporter=video_exporter,
        cartoon_service=cartoon_service,
        cartoon_exporter=cartoon_exporter,
        custom_renderers=custom_renderers,
    )
    st.markdown(FLASHCARDS_CSS + QUIZ_TAB_CSS + SLIDESHOW_TAB_CSS + AUDIO_OVERVIEW_TAB_CSS, unsafe_allow_html=True)

    st.subheader("Asset History")
    st.caption("Browse previously generated assets. History view keeps the same interactive controls as asset tabs.")

    available_records = asset_history_service.list_records()
    if not available_records:
        st.info("No asset records found yet. Generate any asset once and it will appear here.")
        return

    filter_col, count_col = st.columns([0.7, 0.3])
    with filter_col:
        filter_options = ["all", *ASSET_HISTORY_ORDER]
        selected_asset = st.selectbox(
            "Filter by Asset Type",
            options=filter_options,
            index=0,
            format_func=lambda value: "All Assets" if value == "all" else value.title(),
            key="asset_history_asset_filter",
        )
    with count_col:
        st.markdown("#### Records")
        if selected_asset == "all":
            st.metric("Total", len(available_records))
        else:
            st.metric("Total", len(asset_history_service.list_records(asset_type=selected_asset)))

    records = (
        available_records
        if selected_asset == "all"
        else asset_history_service.list_records(asset_type=selected_asset)
    )
    if not records:
        st.info("No records match this asset filter.")
        return

    record_ids = [record.id for record in records]
    selected_id = st.selectbox(
        "Select Record",
        options=record_ids,
        format_func=lambda value: _record_label(records, value),
        key="asset_history_selected_record_id",
    )
    selected_record = next((record for record in records if record.id == selected_id), None)
    if selected_record is None:
        st.warning("Selected record could not be loaded.")
        return

    st.markdown("---")
    meta_col_1, meta_col_2, meta_col_3, meta_col_4 = st.columns(4)
    meta_col_1.metric("Asset", selected_record.asset_type.title())
    meta_col_2.metric("Status", selected_record.status.title())
    meta_col_3.metric("Model", selected_record.model or "N/A")
    meta_col_4.metric("Cache", "Hit" if selected_record.cache_hit else "Miss")
    st.caption(f"Created at: {selected_record.created_at}")
    if selected_record.topic:
        st.caption(f"Topic: {selected_record.topic}")
    if selected_record.parse_note:
        st.info(selected_record.parse_note)

    if selected_record.status == "error":
        if selected_record.error:
            st.error(selected_record.error)
        if selected_record.raw_text:
            with st.expander("Raw Model Output", expanded=False):
                st.code(selected_record.raw_text)
    else:
        _render_record_content(record=selected_record, context=context)

    with st.expander("Request Payload", expanded=False):
        st.json(selected_record.request_payload)


def _record_label(records: list[AssetHistoryRecord], record_id: str) -> str:
    for record in records:
        if record.id != record_id:
            continue
        topic = record.topic or "No topic"
        return (
            f"{record.created_at} | {record.asset_type} | {topic} | "
            f"{record.status} | {record.id[:8]}"
        )
    return record_id


def _render_record_content(*, record: AssetHistoryRecord, context: AssetHistoryRenderContext) -> None:
    renderers = build_record_renderers(custom_renderers=context.custom_renderers)
    renderer = renderers.get(record.asset_type, render_default_record)
    renderer(record, context)
