from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from main_app.models import GroqSettings, WebSourcingSettings
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.global_grounding_service import GlobalGroundingService
from main_app.services.report_exporter import ReportExporter
from main_app.services.report_service import ReportService
from main_app.services.source_grounding_service import SourceGroundingService
from main_app.ui.components import (
    ReportRenderConfig,
    render_report_view,
    render_source_grounding_controls,
)

REPORT_TAB_CSS = """
<style>
    .report-section-title {
        margin: 2px 0 10px 0;
        font-size: 1.02rem;
        font-weight: 700;
        color: #343a40;
    }
    .report-format-card {
        border: 1px solid #e1e5ea;
        border-radius: 14px;
        background: #f8fafc;
        padding: 12px;
        min-height: 112px;
        margin-bottom: 6px;
    }
    .report-format-card.active {
        border-color: #7c8da6;
        background: #eef4ff;
        box-shadow: inset 0 0 0 1px rgba(124, 141, 166, 0.35);
    }
    .report-format-name {
        margin: 0 0 6px 0;
        font-size: 1rem;
        font-weight: 700;
        color: #22262c;
    }
    .report-format-desc {
        margin: 0;
        color: #505866;
        font-size: 0.92rem;
        line-height: 1.35;
    }
    .report-meta {
        color: #4b5563;
        font-weight: 600;
        margin-top: 2px;
        margin-bottom: 2px;
    }
</style>
"""


def render_report_tab(
    *,
    report_service: ReportService,
    report_exporter: ReportExporter,
    llm_service: CachedLLMService,
    settings: GroqSettings,
    web_sourcing_settings: WebSourcingSettings,
    cache_count_placeholder: Any,
    source_grounding_service: SourceGroundingService,
    global_grounding_service: GlobalGroundingService,
) -> None:
    st.markdown(REPORT_TAB_CSS, unsafe_allow_html=True)
    st.subheader("Create Report")

    formats = report_service.list_formats()
    format_key_by_title = {fmt.title: fmt.key for fmt in formats}
    format_title_by_key = {fmt.key: fmt.title for fmt in formats}

    if st.session_state.report_selected_format not in format_title_by_key:
        st.session_state.report_selected_format = formats[0].key

    with st.container(border=True):
        st.markdown('<div class="report-section-title">Report Setup</div>', unsafe_allow_html=True)
        topic = st.text_input(
            "Report Topic",
            placeholder="e.g. Transitioning to Agentic AI Systems",
            key="report_topic_input",
        )
        additional_notes = st.text_area(
            "Additional Notes (Optional)",
            placeholder="e.g. Keep it practical for engineering teams and decision makers.",
            height=90,
            key="report_additional_notes",
        )
        grounding = render_source_grounding_controls(
            key_prefix="report",
            source_grounding_service=source_grounding_service,
            global_grounding_service=global_grounding_service,
            web_settings=web_sourcing_settings,
            topic=topic,
            constraints=additional_notes,
        )

    with st.container(border=True):
        st.markdown('<div class="report-section-title">Choose Format</div>', unsafe_allow_html=True)

        selected_title = st.radio(
            "Format",
            options=[fmt.title for fmt in formats],
            index=[fmt.key for fmt in formats].index(st.session_state.report_selected_format),
            horizontal=True,
            label_visibility="collapsed",
            key="report_format_radio",
        )
        st.session_state.report_selected_format = format_key_by_title[selected_title]

        format_cols = st.columns(len(formats), gap="small")
        for idx, report_format in enumerate(formats):
            is_active = report_format.key == st.session_state.report_selected_format
            active_class = " active" if is_active else ""
            with format_cols[idx]:
                st.markdown(
                    (
                        f'<div class="report-format-card{active_class}">'
                        f'<p class="report-format-name">{escape(report_format.title)}</p>'
                        f'<p class="report-format-desc">{escape(report_format.description)}</p>'
                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )

    generate_col, _ = st.columns([0.28, 0.72])
    with generate_col:
        generate_report = st.button(
            "Generate Report",
            type="primary",
            key="generate_report",
            width="stretch",
        )

    if generate_report:
        if not settings.has_api_key():
            st.error("Please enter your Groq API key in the sidebar.")
            st.stop()
        if not settings.has_model():
            st.error("Please select or enter a valid model.")
            st.stop()
        if not topic or not topic.strip():
            st.error("Please enter a topic.")
            st.stop()
        if grounding.enabled and not grounding.grounding_context:
            strict_warning = next(
                (item for item in grounding.warnings if "Strict mode is enabled" in str(item)),
                "",
            )
            st.error(strict_warning or "Source-grounded mode is enabled but no valid source text was loaded.")
            st.stop()

        try:
            with st.spinner("Generating report..."):
                generation_result = report_service.generate(
                    topic=topic,
                    format_key=st.session_state.report_selected_format,
                    additional_notes=additional_notes,
                    grounding_context=grounding.grounding_context,
                    source_manifest=grounding.source_manifest,
                    require_citations=grounding.require_citations,
                    grounding_metadata=grounding.diagnostics,
                    settings=settings,
                )

            st.session_state.report_last_topic = topic.strip()
            st.session_state.report_last_format_title = format_title_by_key[
                st.session_state.report_selected_format
            ]
            st.session_state.report_last_content = generation_result.content

            if generation_result.cache_hit:
                st.info("Report served from cache. No API call made.")
            else:
                cache_count_placeholder.caption(f"Cached responses: {llm_service.count}")
            st.success("Report generated successfully.")
            if grounding.enabled and grounding.require_citations:
                st.caption("Source-grounded mode enabled. Verify citation markers like [S1], [S2] in the report.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Request failed: {exc}")

    if st.session_state.report_last_content:
        st.markdown("---")
        st.subheader("Generated Report")
        st.markdown(
            f'<div class="report-meta">Topic: {escape(st.session_state.report_last_topic)}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="report-meta">Format: {escape(st.session_state.report_last_format_title)}</div>',
            unsafe_allow_html=True,
        )
        render_report_view(
            topic=str(st.session_state.report_last_topic),
            format_title=str(st.session_state.report_last_format_title),
            markdown_content=str(st.session_state.report_last_content),
            config=ReportRenderConfig(
                template_select_key="report_export_template",
                download_md_key="download_report_markdown",
                download_pdf_key="download_report_pdf",
                download_pdf_disabled_key="download_report_pdf_disabled",
            ),
            report_exporter=report_exporter,
        )
