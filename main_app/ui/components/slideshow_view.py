from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
import re
from typing import Any

import streamlit as st

from main_app.shared.slideshow.representation_normalizer import normalize_slide_representation
from main_app.services.slide_deck_exporter import SlideDeckExporter


@dataclass(frozen=True)
class SlideshowRenderConfig:
    state_index_key: str
    jump_key_format: str
    prev_button_key_format: str
    next_button_key_format: str
    download_md_key: str
    download_json_key: str
    download_pptx_key: str
    download_pptx_disabled_key: str
    download_pdf_key: str
    download_pdf_disabled_key: str
    template_select_key: str


def render_slideshow_view(
    *,
    topic: str,
    slides: list[dict[str, Any]],
    config: SlideshowRenderConfig,
    slide_exporter: SlideDeckExporter,
) -> None:
    if not slides:
        st.warning("No slides available.")
        return

    total = len(slides)
    if config.state_index_key not in st.session_state:
        st.session_state[config.state_index_key] = 0

    current_idx = int(st.session_state[config.state_index_key])
    if current_idx < 0 or current_idx >= total:
        current_idx = 0
        st.session_state[config.state_index_key] = 0

    raw_slide = slides[current_idx] if isinstance(slides[current_idx], dict) else {}
    slide, _ = normalize_slide_representation(raw_slide)
    top_col_1, top_col_2 = st.columns([0.64, 0.36], vertical_alignment="bottom")
    with top_col_1:
        st.caption(f"Slide {current_idx + 1} / {total}")
    with top_col_2:
        jump_target = st.selectbox(
            "Jump to slide",
            options=list(range(total)),
            index=current_idx,
            format_func=lambda idx: f"{idx + 1}. {slides[idx].get('title', 'Untitled')}",
            key=config.jump_key_format.format(index=current_idx),
        )
        if jump_target != current_idx:
            st.session_state[config.state_index_key] = jump_target
            st.rerun()

    representation_html = _render_representation_html(slide)
    slide_html = (
        '<div class="ss-wrap">'
        f'<div class="ss-meta">Section: {escape(str(slide.get("section", "General")))}</div>'
        f'<h2 class="ss-title">{escape(str(slide.get("title", "Untitled")))}</h2>'
        f"{representation_html}"
        "</div>"
    )
    st.markdown(slide_html, unsafe_allow_html=True)

    code_snippet = str(slide.get("code_snippet", "")).strip()
    if code_snippet:
        code_language = str(slide.get("code_language", "")).strip() or "text"
        st.code(code_snippet, language=code_language)

    notes = str(slide.get("speaker_notes", "")).strip()
    if notes:
        with st.expander("Speaker Notes", expanded=False):
            st.write(notes)

    nav_col_1, _, nav_col_3 = st.columns([0.2, 0.6, 0.2])
    with nav_col_1:
        if st.button(
            "Previous",
            key=config.prev_button_key_format.format(index=current_idx),
            width="stretch",
            disabled=current_idx == 0,
        ):
            st.session_state[config.state_index_key] = max(0, current_idx - 1)
            st.rerun()
    with nav_col_3:
        if st.button(
            "Next",
            key=config.next_button_key_format.format(index=current_idx),
            width="stretch",
            disabled=current_idx >= total - 1,
        ):
            st.session_state[config.state_index_key] = min(total - 1, current_idx + 1)
            st.rerun()

    st.markdown("---")
    template_options = slide_exporter.list_templates()
    if not template_options:
        template_options = [
            {
                "key": "default",
                "title": "Default",
                "description": "Default presentation style.",
            }
        ]

    template_keys = [str(item.get("key", "")).strip() for item in template_options if str(item.get("key", "")).strip()]
    if not template_keys:
        template_keys = ["default"]
        template_options = [
            {
                "key": "default",
                "title": "Default",
                "description": "Default presentation style.",
            }
        ]

    template_by_key = {str(item.get("key", "")).strip(): item for item in template_options}
    stored_template = st.session_state.get(config.template_select_key)
    default_template = template_keys[0]
    if stored_template not in template_keys and config.template_select_key in st.session_state:
        del st.session_state[config.template_select_key]
    selected_template = str(st.session_state.get(config.template_select_key, default_template))
    selected_index = template_keys.index(selected_template) if selected_template in template_keys else 0

    template_col, dl_col_1, dl_col_2, dl_col_3, dl_col_4 = st.columns([1.35, 1.0, 1.0, 1.0, 1.0])
    with template_col:
        selected_template = st.selectbox(
            "PPT Template",
            options=template_keys,
            index=selected_index,
            format_func=lambda key: str(template_by_key.get(key, {}).get("title", key)),
            key=config.template_select_key,
        )
        template_description = str(template_by_key.get(selected_template, {}).get("description", "")).strip()
        if template_description:
            st.caption(template_description)

    markdown_payload = _slides_to_markdown(topic, slides)
    json_payload = {"topic": topic, "slides": slides}
    safe_topic = re.sub(r"[^a-zA-Z0-9_-]+", "_", topic.strip())[:60].strip("_") or "slideshow"
    pptx_bytes, pptx_error = slide_exporter.build_pptx(
        topic=topic,
        slides=slides,
        template_key=selected_template,
    )
    pdf_bytes, pdf_error = slide_exporter.build_pdf(
        topic=topic,
        slides=slides,
        template_key=selected_template,
    )

    with dl_col_1:
        st.download_button(
            "Download Slides (Markdown)",
            data=markdown_payload,
            file_name=f"{safe_topic}.md",
            mime="text/markdown",
            key=config.download_md_key,
            width="stretch",
        )
    with dl_col_2:
        st.download_button(
            "Download Slides (JSON)",
            data=json.dumps(json_payload, ensure_ascii=False, indent=2),
            file_name=f"{safe_topic}.json",
            mime="application/json",
            key=config.download_json_key,
            width="stretch",
        )
    with dl_col_3:
        if pptx_bytes is not None:
            st.download_button(
                "Download Slides (PPTX)",
                data=pptx_bytes,
                file_name=f"{safe_topic}.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                key=config.download_pptx_key,
                width="stretch",
            )
        else:
            st.button(
                "Download Slides (PPTX)",
                disabled=True,
                width="stretch",
                key=config.download_pptx_disabled_key,
            )
            if pptx_error:
                st.caption(pptx_error)
    with dl_col_4:
        if pdf_bytes is not None:
            st.download_button(
                "Download Slides (PDF)",
                data=pdf_bytes,
                file_name=f"{safe_topic}.pdf",
                mime="application/pdf",
                key=config.download_pdf_key,
                width="stretch",
            )
        else:
            st.button(
                "Download Slides (PDF)",
                disabled=True,
                width="stretch",
                key=config.download_pdf_disabled_key,
            )
            if pdf_error:
                st.caption(pdf_error)


def _slides_to_markdown(topic: str, slides: list[dict[str, Any]]) -> str:
    lines = [f"# {topic}", ""]
    for idx, raw_slide in enumerate(slides, start=1):
        normalized_slide, _ = normalize_slide_representation(raw_slide if isinstance(raw_slide, dict) else {})
        lines.append(f"## Slide {idx}: {normalized_slide.get('title', 'Untitled')}")
        lines.append(f"Section: {normalized_slide.get('section', 'General')}")
        lines.append(f"Representation: {normalized_slide.get('representation', 'bullet')}")
        lines.append("")
        for bullet in normalized_slide.get("bullets", []):
            lines.append(f"- {bullet}")
        code_snippet = str(normalized_slide.get("code_snippet", "")).strip()
        if code_snippet:
            code_language = str(normalized_slide.get("code_language", "")).strip() or "text"
            lines.append("")
            lines.append(f"```{code_language}")
            lines.append(code_snippet)
            lines.append("```")
        notes = str(normalized_slide.get("speaker_notes", "")).strip()
        if notes:
            lines.append("")
            lines.append(f"Notes: {notes}")
        lines.append("")
    return "\n".join(lines)


def _render_representation_html(slide: dict[str, Any]) -> str:
    representation = " ".join(str(slide.get("representation", "bullet")).split()).strip().lower()
    layout_payload = slide.get("layout_payload", {})
    payload = layout_payload if isinstance(layout_payload, dict) else {}

    if representation == "two_column":
        left_title = escape(str(payload.get("left_title", "Left")))
        right_title = escape(str(payload.get("right_title", "Right")))
        left_items = _render_list_html(payload.get("left_items", []), css_class="ss-col-list")
        right_items = _render_list_html(payload.get("right_items", []), css_class="ss-col-list")
        return (
            '<div class="ss-two-col">'
            f'<div class="ss-col"><h4 class="ss-col-title">{left_title}</h4>{left_items}</div>'
            f'<div class="ss-col"><h4 class="ss-col-title">{right_title}</h4>{right_items}</div>'
            "</div>"
        )

    if representation == "comparison":
        left_title = escape(str(payload.get("left_title", "Option A")))
        right_title = escape(str(payload.get("right_title", "Option B")))
        left_items = _render_list_html(payload.get("left_points", []), css_class="ss-col-list")
        right_items = _render_list_html(payload.get("right_points", []), css_class="ss-col-list")
        return (
            '<div class="ss-two-col ss-compare">'
            f'<div class="ss-col"><h4 class="ss-col-title">{left_title}</h4>{left_items}</div>'
            f'<div class="ss-col"><h4 class="ss-col-title">{right_title}</h4>{right_items}</div>'
            "</div>"
        )

    if representation == "timeline":
        events = payload.get("events", [])
        if not isinstance(events, list):
            events = []
        timeline_blocks: list[str] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            label = escape(str(event.get("label", "")))
            detail = escape(str(event.get("detail", "")))
            if not label and not detail:
                continue
            timeline_blocks.append(
                '<div class="ss-timeline-item">'
                f'<div class="ss-timeline-label">{label or "Milestone"}</div>'
                f'<div class="ss-timeline-detail">{detail}</div>'
                "</div>"
            )
        if not timeline_blocks:
            return _render_list_html(slide.get("bullets", []), css_class="ss-bullets")
        return '<div class="ss-timeline">' + "".join(timeline_blocks) + "</div>"

    if representation == "process_flow":
        steps = payload.get("steps", [])
        if not isinstance(steps, list):
            steps = []
        flow_blocks: list[str] = []
        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                continue
            title = escape(str(step.get("title", f"Step {idx}")))
            detail = escape(str(step.get("detail", "")))
            flow_blocks.append(
                '<div class="ss-flow-step">'
                f'<div class="ss-flow-index">{idx}</div>'
                f'<div class="ss-flow-title">{title}</div>'
                f'<div class="ss-flow-detail">{detail}</div>'
                "</div>"
            )
        if not flow_blocks:
            return _render_list_html(slide.get("bullets", []), css_class="ss-bullets")
        return '<div class="ss-flow">' + "".join(flow_blocks) + "</div>"

    if representation == "metric_cards":
        cards = payload.get("cards", [])
        if not isinstance(cards, list):
            cards = []
        metric_blocks: list[str] = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            label = escape(str(card.get("label", "")))
            value = escape(str(card.get("value", "")))
            context = escape(str(card.get("context", "")))
            metric_blocks.append(
                '<div class="ss-metric-card">'
                f'<div class="ss-metric-label">{label}</div>'
                f'<div class="ss-metric-value">{value}</div>'
                f'<div class="ss-metric-context">{context}</div>'
                "</div>"
            )
        if not metric_blocks:
            return _render_list_html(slide.get("bullets", []), css_class="ss-bullets")
        return '<div class="ss-metric-grid">' + "".join(metric_blocks) + "</div>"

    return _render_list_html(slide.get("bullets", []), css_class="ss-bullets")


def _render_list_html(items: Any, *, css_class: str) -> str:
    if not isinstance(items, list):
        items = []
    rendered = "".join(f"<li>{escape(str(item))}</li>" for item in items if str(item).strip())
    if not rendered:
        rendered = "<li>Key concept summary for this slide.</li>"
    return f'<ul class="{css_class}">{rendered}</ul>'
