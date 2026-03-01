from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from main_app.constants import TAB_TITLES
from main_app.services.agent_dashboard import AgentDashboardService
from main_app.services.observability_service import ObservabilityService
from main_app.ui.tabs.documentation_catalog import (
    DOCUMENTATION_MODES,
    UI_DOCUMENTATION_MODE,
    collect_runtime_inventory,
    docs_whitelist_labels,
    filter_records_by_query,
    filter_ui_feature_catalog,
    get_debug_flow_cards,
    get_debug_playbooks,
    get_task_to_tab_matrix,
    get_ui_feature_catalog,
    missing_whitelisted_docs,
    resolve_whitelisted_doc_path,
)


def render_documentation_tab(
    *,
    agent_dashboard_service: AgentDashboardService | None,
    observability_service: ObservabilityService | None,
) -> None:
    _inject_docs_center_styles()
    _ensure_documentation_defaults()

    mode_cols = st.columns([2, 1])
    mode = mode_cols[0].radio(
        "Documentation Mode",
        options=DOCUMENTATION_MODES,
        key="documentation_mode",
        horizontal=True,
    )
    search_query = mode_cols[1].text_input(
        "Search",
        key="documentation_search_query",
        placeholder="feature, flow, metric, doc",
    )

    _render_hero(mode=mode)
    if mode == UI_DOCUMENTATION_MODE:
        _render_ui_documentation_portal(
            search_query=search_query,
            agent_dashboard_service=agent_dashboard_service,
        )
        return

    _render_debug_documentation_portal(
        search_query=search_query,
        agent_dashboard_service=agent_dashboard_service,
        observability_service=observability_service,
    )


def _render_ui_documentation_portal(
    *,
    search_query: str,
    agent_dashboard_service: AgentDashboardService | None,
) -> None:
    sections = [
        "Overview",
        "Quick Start",
        "Feature Guides",
        "Runtime Inventory",
        "Task Matrix",
        "Reference Docs",
    ]
    nav_col, content_col = st.columns([1, 3], gap="large")
    with nav_col:
        st.markdown("### UI Docs")
        section = st.radio(
            "UI sections",
            options=sections,
            key="documentation_ui_section",
            label_visibility="collapsed",
        )
        st.caption("Use Search to narrow features and matrix rows.")
        _render_nav_tips_ui()

    with content_col:
        if section == "Overview":
            _render_ui_overview_page(search_query=search_query)
        elif section == "Quick Start":
            _render_quick_start_page()
        elif section == "Feature Guides":
            _render_ui_feature_guides_page(search_query=search_query)
        elif section == "Runtime Inventory":
            _render_runtime_inventory_page(agent_dashboard_service=agent_dashboard_service)
        elif section == "Task Matrix":
            _render_task_matrix_page(search_query=search_query)
        else:
            _render_reference_docs_page(search_query=search_query)


def _render_debug_documentation_portal(
    *,
    search_query: str,
    agent_dashboard_service: AgentDashboardService | None,
    observability_service: ObservabilityService | None,
) -> None:
    sections = [
        "Overview",
        "System Flow",
        "Correlation IDs",
        "Playbooks",
        "Runtime Matrix",
        "Reference Docs",
    ]
    nav_col, content_col = st.columns([1, 3], gap="large")
    with nav_col:
        st.markdown("### Debug Docs")
        section = st.radio(
            "Debug sections",
            options=sections,
            key="documentation_debug_section",
            label_visibility="collapsed",
        )
        st.caption("Use Search to narrow flow cards and playbooks.")
        _render_nav_tips_debug()

    with content_col:
        if section == "Overview":
            _render_debug_overview_page(search_query=search_query)
        elif section == "System Flow":
            _render_debug_system_flow_page(search_query=search_query)
        elif section == "Correlation IDs":
            _render_correlation_ids_page(observability_service=observability_service)
        elif section == "Playbooks":
            _render_debug_playbooks_page(search_query=search_query)
        elif section == "Runtime Matrix":
            _render_runtime_inventory_page(agent_dashboard_service=agent_dashboard_service)
        else:
            _render_reference_docs_page(search_query=search_query)


def _render_ui_overview_page(*, search_query: str) -> None:
    st.markdown("## UI Documentation")
    st.caption("End-to-end usage guide for tabs, tools, features, and expected outputs.")
    catalog = get_ui_feature_catalog()
    filtered = filter_ui_feature_catalog(catalog=catalog, query=search_query)
    top_cols = st.columns(3)
    top_cols[0].metric("Total Features", str(len(catalog)))
    top_cols[1].metric("Search Matches", str(len(filtered)))
    top_cols[2].metric("Primary Tabs", str(len(TAB_TITLES)))
    with st.container(border=True):
        st.markdown("### What You Get Here")
        st.markdown("- Feature-by-feature usage guidance")
        st.markdown("- Quick start path for first run")
        st.markdown("- Runtime inventory of tools/workflows")
        st.markdown("- Task-to-tab matrix for faster navigation")


def _render_quick_start_page() -> None:
    st.markdown("## Quick Start")
    steps = [
        "Configure model and optional web sourcing in sidebar.",
        "Choose your outcome tab (explanation, quiz, report, slide, video, audio).",
        "Enter focused topic and constraints.",
        "Generate output and review quality.",
        "Export artifact if supported by that tab.",
        "Use Observability + Debug docs when something fails.",
    ]
    for idx, step in enumerate(steps, 1):
        st.markdown(f"{idx}. {step}")


def _render_ui_feature_guides_page(*, search_query: str) -> None:
    st.markdown("## Feature Guides")
    catalog = get_ui_feature_catalog()
    filtered_features = filter_ui_feature_catalog(catalog=catalog, query=search_query)
    if not filtered_features:
        st.warning("No features matched your search.")
        return

    titles = [title for title, _ in filtered_features]
    current = " ".join(str(st.session_state.get("documentation_ui_feature_focus", "")).split()).strip()
    if current not in titles:
        st.session_state.documentation_ui_feature_focus = titles[0]
    selected_title = st.selectbox(
        "Choose feature",
        options=titles,
        key="documentation_ui_feature_focus",
    )
    details = dict(catalog.get(selected_title, {}))
    with st.container(border=True):
        st.markdown(f"### {selected_title}")
        st.markdown(f"**Purpose**: {details.get('purpose', '-')}")
        _render_list_section("Inputs / Controls", details.get("inputs", []))
        _render_list_section("Outputs", details.get("outputs", []))
        _render_list_section("Typical Workflow", details.get("typical_workflow", []))
        _render_list_section("Common Mistakes", details.get("common_mistakes", []))
        _render_list_section("Related Docs", details.get("related_docs", []))


def _render_runtime_inventory_page(*, agent_dashboard_service: AgentDashboardService | None) -> None:
    st.markdown("## Runtime Inventory")
    inventory = collect_runtime_inventory(
        enabled_tab_titles=st.session_state.get("enabled_tab_titles", list(TAB_TITLES)),
        agent_dashboard_service=agent_dashboard_service,
    )
    metric_cols = st.columns(4)
    metric_cols[0].metric("Visible Tabs", str(inventory.get("visible_tab_count", 0)))
    metric_cols[1].metric("Tools", str(inventory.get("tool_count", 0)))
    metric_cols[2].metric("Workflows", str(inventory.get("workflow_count", 0)))
    metric_cols[3].metric("Stage Profiles", str(inventory.get("stage_profile_count", 0)))

    with st.container(border=True):
        visible_tabs = inventory.get("visible_tabs", [])
        if isinstance(visible_tabs, list) and visible_tabs:
            st.markdown("### Active Tabs")
            st.markdown(", ".join(str(item) for item in visible_tabs))

    tools = inventory.get("tools", [])
    workflows = inventory.get("workflows", [])
    stage_sequences = inventory.get("stage_sequences", {})

    if tools:
        st.markdown("### Registered Tools")
        st.dataframe(tools, width="stretch", hide_index=True)
    if workflows:
        st.markdown("### Registered Workflows")
        st.dataframe(workflows, width="stretch", hide_index=True)
    if isinstance(stage_sequences, dict) and stage_sequences:
        st.markdown("### Tool Stage Sequences")
        rows = [{"tool_key": key, "stages": " -> ".join(stages)} for key, stages in stage_sequences.items()]
        st.dataframe(rows, width="stretch", hide_index=True)
    if not tools and not workflows:
        st.info("No runtime inventory detected in this session.")


def _render_task_matrix_page(*, search_query: str) -> None:
    st.markdown("## Task Matrix")
    task_matrix = filter_records_by_query(records=get_task_to_tab_matrix(), query=search_query)
    if task_matrix:
        st.dataframe(task_matrix, width="stretch", hide_index=True)
    else:
        st.info("No task matrix rows matched your search.")


def _render_debug_overview_page(*, search_query: str) -> None:
    st.markdown("## Debug Documentation")
    st.caption("Backend execution flow, correlation IDs, observability usage, and failure triage.")
    cards = filter_records_by_query(records=get_debug_flow_cards(), query=search_query)
    playbooks = filter_records_by_query(records=get_debug_playbooks(), query=search_query)
    metric_cols = st.columns(3)
    metric_cols[0].metric("Flow Cards", str(len(cards)))
    metric_cols[1].metric("Playbooks", str(len(playbooks)))
    metric_cols[2].metric("Whitelisted Docs", str(len(docs_whitelist_labels())))
    with st.container(border=True):
        st.markdown("### Triage Path")
        st.markdown("1. Capture `request_id`.")
        st.markdown("2. Pivot to `run_id` and `job_id` if needed.")
        st.markdown("3. Locate failing flow card.")
        st.markdown("4. Execute playbook checklist.")
        st.markdown("5. Inspect reference docs for deep detail.")


def _render_debug_system_flow_page(*, search_query: str) -> None:
    st.markdown("## System Flow")
    cards = filter_records_by_query(records=get_debug_flow_cards(), query=search_query)
    if not cards:
        st.warning("No system flow cards matched your search.")
        return
    for card in cards:
        with st.container(border=True):
            st.markdown(f"### {card.get('title', 'Flow')}")
            _render_list_section("Trigger Points", card.get("trigger_points", []))
            _render_list_section("Core Paths", card.get("module_paths", []))
            _render_list_section("Key Events", card.get("event_names", []))
            _render_list_section("Key Metrics", card.get("metric_names", []))
            _render_list_section("Primary Failure Modes", card.get("primary_failure_modes", []))
            _render_list_section("First Checks", card.get("first_checks", []))


def _render_correlation_ids_page(*, observability_service: ObservabilityService | None) -> None:
    st.markdown("## Correlation IDs")
    with st.container(border=True):
        st.markdown("### ID Semantics")
        st.markdown("- `request_id`: one UI-triggered request lifecycle")
        st.markdown("- `run_id`: orchestration run across stage execution")
        st.markdown("- `job_id`: async background job")
        st.markdown("- `trace_id`: distributed trace")
        st.markdown("- `span_id`: operation inside trace")
    with st.container(border=True):
        st.markdown("### Debug in 5 Steps")
        st.markdown("1. Start with `request_id` from Observability tab.")
        st.markdown("2. Pivot to `run_id` for stage-level execution.")
        st.markdown("3. If async path is involved, pivot to `job_id`.")
        st.markdown("4. Inspect `trace_id`/`span_id` in Tempo/Grafana.")
        st.markdown("5. Use payload references for exact body inspection.")
    if observability_service is not None:
        ctx = observability_service.telemetry_service.current_context()
        st.caption(
            "Current context: "
            f"request=`{ctx.request_id or '-'}` "
            f"run=`{ctx.run_id or '-'}` "
            f"job=`{ctx.job_id or '-'}` "
            f"trace=`{ctx.trace_id or '-'}` "
            f"span=`{ctx.span_id or '-'}`"
        )


def _render_debug_playbooks_page(*, search_query: str) -> None:
    st.markdown("## Playbooks")
    playbooks = filter_records_by_query(records=get_debug_playbooks(), query=search_query)
    if not playbooks:
        st.warning("No playbooks matched your search.")
        return
    for playbook in playbooks:
        with st.expander(str(playbook.get("symptom", "Playbook")), expanded=False):
            _render_list_section("Checklist", playbook.get("checklist", []))


def _render_reference_docs_page(*, search_query: str) -> None:
    st.markdown("## Reference Docs")
    missing_labels = missing_whitelisted_docs()
    if missing_labels:
        st.warning("Missing docs from whitelist: " + ", ".join(missing_labels))

    labels = docs_whitelist_labels()
    filtered_labels = [label for label in labels if " ".join(str(search_query).split()).strip().lower() in label.lower()] if search_query.strip() else labels
    if not filtered_labels:
        st.warning("No whitelisted docs matched your search.")
        return

    current_doc = " ".join(str(st.session_state.get("documentation_selected_debug_doc", "")).split()).strip()
    if current_doc not in filtered_labels:
        st.session_state.documentation_selected_debug_doc = filtered_labels[0]

    selected_doc = st.selectbox(
        "Choose document",
        options=filtered_labels,
        key="documentation_selected_debug_doc",
    )
    try:
        doc_path = resolve_whitelisted_doc_path(label=selected_doc)
    except ValueError:
        st.error("Selected document is not allowed by whitelist.")
        return
    if not doc_path.exists():
        st.error(f"Document missing: `{doc_path}`")
        return
    markdown_body = _read_markdown_cached(path_str=str(doc_path), mtime_ns=doc_path.stat().st_mtime_ns)
    st.caption(f"Source: `{doc_path}`")
    st.markdown(markdown_body)


def _render_nav_tips_ui() -> None:
    with st.container(border=True):
        st.markdown("**Tips**")
        st.markdown("- Start with `Quick Start` if new.")
        st.markdown("- Use `Feature Guides` for per-tab usage.")
        st.markdown("- Use `Task Matrix` to choose right tab fast.")


def _render_nav_tips_debug() -> None:
    with st.container(border=True):
        st.markdown("**Tips**")
        st.markdown("- Start with `System Flow` for failure mapping.")
        st.markdown("- Use `Correlation IDs` for traceability.")
        st.markdown("- Use `Playbooks` for step-wise triage.")


def _render_list_section(title: str, values: Any) -> None:
    st.markdown(f"**{title}**")
    items = values if isinstance(values, list) else []
    if not items:
        st.markdown("- (none)")
        return
    for item in items:
        st.markdown(f"- {item}")


def _render_hero(*, mode: str) -> None:
    description = (
        "Browse UI feature documentation with runtime inventory."
        if mode == UI_DOCUMENTATION_MODE
        else "Debug backend flows with correlation IDs and playbooks."
    )
    st.markdown(
        (
            '<div class="docs-hero">'
            '<div class="docs-eyebrow">Hatched Studio Docs</div>'
            f'<h3>{mode}</h3>'
            f'<p>{description}</p>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _ensure_documentation_defaults() -> None:
    defaults: dict[str, Any] = {
        "documentation_mode": UI_DOCUMENTATION_MODE,
        "documentation_search_query": "",
        "documentation_ui_section": "Overview",
        "documentation_debug_section": "Overview",
        "documentation_ui_feature_focus": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if st.session_state.get("documentation_mode") not in DOCUMENTATION_MODES:
        st.session_state.documentation_mode = UI_DOCUMENTATION_MODE


def _inject_docs_center_styles() -> None:
    st.markdown(
        """
        <style>
        .docs-hero {
            border: 1px solid #e5e7eb;
            border-radius: 14px;
            padding: 16px 18px;
            margin: 6px 0 18px 0;
            background: linear-gradient(120deg, #f8fafc, #eef2ff);
        }
        .docs-eyebrow {
            font-size: 0.80rem;
            font-weight: 700;
            letter-spacing: .05em;
            text-transform: uppercase;
            color: #2563eb;
            margin-bottom: 6px;
        }
        .docs-hero h3 {
            margin: 0 0 6px 0;
            font-size: 1.35rem;
            color: #0f172a;
        }
        .docs-hero p {
            margin: 0;
            color: #334155;
            font-size: 0.96rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _cache_data(*, show_spinner: bool = False):
    cache_data = getattr(st, "cache_data", None)
    if callable(cache_data):
        return cache_data(show_spinner=show_spinner)

    def _decorator(func):
        return func

    return _decorator


@_cache_data(show_spinner=False)
def _read_markdown_cached(*, path_str: str, mtime_ns: int) -> str:
    _ = mtime_ns
    path = Path(path_str)
    return path.read_text(encoding="utf-8")
