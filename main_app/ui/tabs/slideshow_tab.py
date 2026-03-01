from __future__ import annotations

from typing import Any

import streamlit as st

from main_app.models import GroqSettings, WebSourcingSettings
from main_app.services.background_jobs import BackgroundJobContext, BackgroundJobManager
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.global_grounding_service import GlobalGroundingService
from main_app.services.slide_deck_exporter import SlideDeckExporter
from main_app.services.slideshow_service import SlideShowService
from main_app.services.source_grounding_service import SourceGroundingService
from main_app.ui.components import (
    SlideshowRenderConfig,
    render_background_job_panel,
    render_slideshow_view,
    render_source_grounding_controls,
)
from main_app.ui.error_handling import UI_HANDLED_EXCEPTIONS, report_ui_error

SLIDESHOW_TAB_CSS = """
<style>
    .ss-wrap {
        border: 1px solid #e5e7eb;
        border-radius: 16px;
        background: linear-gradient(150deg, #f8fafc 0%, #eef2ff 100%);
        padding: 18px;
        margin-top: 8px;
    }
    .ss-meta {
        color: #4b5563;
        font-size: 0.92rem;
        margin-bottom: 8px;
        font-weight: 600;
    }
    .ss-title {
        color: #0f172a;
        font-size: 1.85rem;
        line-height: 1.25;
        font-weight: 750;
        margin: 0 0 12px 0;
    }
    .ss-bullets {
        margin: 0;
        padding-left: 1.2rem;
        color: #1f2937;
        font-size: 1.05rem;
        line-height: 1.5;
    }
    .ss-bullets li {
        margin-bottom: 6px;
    }
    .ss-two-col {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
        margin-top: 6px;
    }
    .ss-col {
        border: 1px solid #dbe4f1;
        border-radius: 12px;
        padding: 10px 12px;
        background: #ffffffc9;
    }
    .ss-col-title {
        margin: 0 0 8px 0;
        font-size: 1rem;
        color: #0f172a;
    }
    .ss-col-list {
        margin: 0;
        padding-left: 1rem;
        color: #1f2937;
    }
    .ss-timeline {
        display: grid;
        gap: 8px;
    }
    .ss-timeline-item {
        border-left: 4px solid #3b82f6;
        padding: 6px 0 6px 10px;
        background: #ffffffb3;
        border-radius: 6px;
    }
    .ss-timeline-label {
        font-weight: 700;
        color: #0f172a;
    }
    .ss-timeline-detail {
        color: #1f2937;
    }
    .ss-flow {
        display: grid;
        gap: 10px;
    }
    .ss-flow-step {
        border: 1px solid #dbe4f1;
        border-radius: 12px;
        padding: 10px 12px;
        background: #ffffffd4;
    }
    .ss-flow-index {
        display: inline-block;
        min-width: 24px;
        height: 24px;
        line-height: 24px;
        text-align: center;
        border-radius: 999px;
        background: #1d4ed8;
        color: white;
        font-size: 0.85rem;
        font-weight: 700;
        margin-bottom: 4px;
    }
    .ss-flow-title {
        font-weight: 700;
        color: #0f172a;
    }
    .ss-flow-detail {
        color: #1f2937;
    }
    .ss-metric-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
    }
    .ss-metric-card {
        border: 1px solid #dbe4f1;
        border-radius: 12px;
        padding: 10px 12px;
        background: #ffffffd4;
    }
    .ss-metric-label {
        color: #334155;
        font-size: 0.9rem;
        margin-bottom: 4px;
    }
    .ss-metric-value {
        color: #0f172a;
        font-weight: 800;
        font-size: 1.3rem;
        line-height: 1.2;
    }
    .ss-metric-context {
        color: #334155;
        font-size: 0.85rem;
        margin-top: 3px;
    }
</style>
"""


def render_slideshow_tab(
    *,
    slideshow_service: SlideShowService,
    llm_service: CachedLLMService,
    settings: GroqSettings,
    web_sourcing_settings: WebSourcingSettings,
    cache_count_placeholder: Any,
    slide_exporter: SlideDeckExporter,
    job_manager: BackgroundJobManager,
    source_grounding_service: SourceGroundingService,
    global_grounding_service: GlobalGroundingService,
) -> None:
    st.markdown(SLIDESHOW_TAB_CSS, unsafe_allow_html=True)
    st.subheader("Slide Show Builder")

    setup_col, control_col = st.columns([0.72, 0.28], gap="large")
    with setup_col:
        topic = st.text_input(
            "Presentation Topic",
            placeholder="e.g. Building Agentic AI Systems in Production",
            key="slideshow_topic_input",
        )
        constraints = st.text_area(
            "Optional Slide Constraints",
            placeholder="e.g. Emphasize architecture, monitoring, and failure modes.",
            height=90,
            key="slideshow_constraints",
        )
        grounding = render_source_grounding_controls(
            key_prefix="slideshow",
            source_grounding_service=source_grounding_service,
            global_grounding_service=global_grounding_service,
            web_settings=web_sourcing_settings,
            topic=topic,
            constraints=constraints,
        )

    with control_col:
        st.markdown("#### Deck Controls")
        subtopic_count = st.slider(
            "Subtopics",
            min_value=2,
            max_value=10,
            value=5,
            step=1,
            key="slideshow_subtopic_count",
        )
        slides_per_subtopic = st.slider(
            "Slides per Subtopic",
            min_value=1,
            max_value=3,
            value=2,
            step=1,
            key="slideshow_slides_per_subtopic",
        )
        code_mode = st.radio(
            "Code Support",
            options=["auto", "force", "none"],
            format_func=lambda value: {
                "auto": "Auto (intent-based)",
                "force": "Force some code slides",
                "none": "No code slides",
            }[value],
            index=0,
            horizontal=False,
            key="slideshow_code_mode",
        )
        st.selectbox(
            "Representation Mode",
            options=["auto", "classic", "visual"],
            index=0,
            key="slideshow_representation_mode",
            format_func=lambda value: {
                "auto": "Auto (Balanced Mix)",
                "classic": "Classic (Bullet-first)",
                "visual": "Visual (Diagram-style)",
            }[value],
        )
        generate_deck = st.button(
            "Generate Slide Show",
            type="primary",
            key="generate_slideshow",
            width="stretch",
        )

    if generate_deck:
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

        topic_clean = topic.strip()
        constraints_clean = constraints.strip()
        representation_mode = str(st.session_state.slideshow_representation_mode or "auto").strip().lower() or "auto"
        grounding_context = grounding.grounding_context
        source_manifest = grounding.source_manifest
        require_citations = grounding.require_citations

        def _worker(context: BackgroundJobContext) -> dict[str, Any]:
            context.update_progress(progress=0.1, message="Building slide deck...")
            result = slideshow_service.generate(
                topic=topic_clean,
                constraints=constraints_clean,
                subtopic_count=subtopic_count,
                slides_per_subtopic=slides_per_subtopic,
                code_mode=code_mode,
                representation_mode=representation_mode,
                grounding_context=grounding_context,
                source_manifest=source_manifest,
                require_citations=require_citations,
                grounding_metadata=grounding.diagnostics,
                settings=settings,
            )
            context.raise_if_cancelled()
            context.update_progress(progress=1.0, message="Slide deck generation completed.")
            return {
                "topic": topic_clean,
                "constraints": constraints_clean,
                "code_mode": code_mode,
                "representation_mode": representation_mode,
                "grounded_mode": bool(grounding_context.strip()),
                "require_citations": bool(require_citations),
                "result": result,
            }

        job_id = job_manager.submit(
            label=f"Slide Show: {topic_clean}",
            worker=_worker,
            metadata={"asset": "slideshow", "topic": topic_clean},
        )
        st.session_state.slideshow_background_job_id = job_id
        st.session_state.slideshow_background_job_applied_id = ""
        st.info("Slide show request queued in background.")
        st.rerun()

    active_job_id = str(st.session_state.get("slideshow_background_job_id", "")).strip()
    if active_job_id:
        replacement_job_id = render_background_job_panel(
            manager=job_manager,
            job_id=active_job_id,
            title="Slide Show Generation Job",
            key_prefix="slideshow_background_job",
        )
        if replacement_job_id != active_job_id:
            st.session_state.slideshow_background_job_id = replacement_job_id
            st.session_state.slideshow_background_job_applied_id = ""
            st.rerun()

    _apply_slideshow_job_result(
        job_manager=job_manager,
        llm_service=llm_service,
        cache_count_placeholder=cache_count_placeholder,
    )

    if not st.session_state.slideshow_slides:
        return

    slides: list[dict[str, Any]] = st.session_state.slideshow_slides
    render_slideshow_view(
        topic=str(st.session_state.slideshow_topic),
        slides=slides,
        config=SlideshowRenderConfig(
            state_index_key="slideshow_index",
            jump_key_format="slideshow_jump_to_{index}",
            prev_button_key_format="slideshow_prev_{index}",
            next_button_key_format="slideshow_next_{index}",
            download_md_key="download_slides_markdown",
            download_json_key="download_slides_json",
            download_pptx_key="download_slides_pptx",
            download_pptx_disabled_key="download_slides_pptx_disabled",
            download_pdf_key="download_slides_pdf",
            download_pdf_disabled_key="download_slides_pdf_disabled",
            template_select_key="download_slides_pptx_template",
        ),
        slide_exporter=slide_exporter,
    )


def _apply_slideshow_job_result(
    *,
    job_manager: BackgroundJobManager,
    llm_service: CachedLLMService,
    cache_count_placeholder: Any,
) -> None:
    job_id = str(st.session_state.get("slideshow_background_job_id", "")).strip()
    if not job_id:
        return
    snapshot = job_manager.get_snapshot(job_id)
    if snapshot is None or not snapshot.is_terminal:
        return

    applied_id = str(st.session_state.get("slideshow_background_job_applied_id", "")).strip()
    if applied_id == job_id:
        return

    st.session_state.slideshow_background_job_applied_id = job_id

    if snapshot.status == "cancelled":
        st.warning("Slide show generation was cancelled.")
        return
    if snapshot.status == "failed":
        st.error(f"Slide show generation failed: {snapshot.error or 'Unknown error'}")
        return

    payload = snapshot.result
    if not isinstance(payload, dict):
        st.error("Slide show background job returned unexpected payload.")
        return

    result = payload.get("result")
    if result is None:
        st.error("Slide show background job did not return generation result.")
        return

    try:
        parse_notes = list(getattr(result, "parse_notes", []))
        parse_error = str(getattr(result, "parse_error", "") or "").strip()
        debug_raw = str(getattr(result, "debug_raw", "") or "").strip()
        slides = getattr(result, "slides", None)
        total_calls = int(getattr(result, "total_calls", 0) or 0)
        cache_hits = int(getattr(result, "cache_hits", 0) or 0)
    except UI_HANDLED_EXCEPTIONS as exc:
        report_ui_error(action="slideshow_apply_job_result", exc=exc)
        return

    for note in parse_notes:
        st.info(str(note))

    if parse_error or not isinstance(slides, list):
        st.error(parse_error or "Slide show generation failed.")
        if debug_raw:
            st.caption("Debug raw response:")
            st.code(debug_raw)
        return

    topic = " ".join(str(payload.get("topic", "")).split()).strip()
    constraints = " ".join(str(payload.get("constraints", "")).split()).strip()
    code_mode = " ".join(str(payload.get("code_mode", "")).split()).strip()
    representation_mode = " ".join(str(payload.get("representation_mode", "auto")).split()).strip().lower() or "auto"
    grounded_mode = bool(payload.get("grounded_mode", False))
    require_citations = bool(payload.get("require_citations", False))

    st.session_state.slideshow_topic = topic
    st.session_state.slideshow_slides = slides
    st.session_state.slideshow_index = 0
    st.session_state.slideshow_last_constraints = constraints
    st.session_state.slideshow_outline = [
        slide.get("section", "")
        for slide in slides
        if isinstance(slide, dict) and slide.get("section") not in {"Introduction", "Conclusion"}
    ]
    st.session_state.slideshow_last_code_mode = code_mode
    st.session_state.slideshow_last_representation_mode = representation_mode

    st.success(
        f"Generated {len(slides)} slides via {total_calls} LLM calls "
        f"({cache_hits} served from cache)."
    )
    if grounded_mode and require_citations:
        st.caption("Source-grounded mode enabled. Slides should include citation markers like [S1], [S2].")
    cache_count_placeholder.caption(f"Cached responses: {llm_service.count}")
