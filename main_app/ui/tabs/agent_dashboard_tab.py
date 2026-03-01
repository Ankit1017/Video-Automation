from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from main_app.infrastructure.agent_dashboard_session_store import AgentDashboardSessionRepository
from main_app.models import GroqSettings, WebSourcingSettings
from main_app.services.agent_dashboard import AgentDashboardService
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.global_grounding_service import GlobalGroundingService
from main_app.services.intent import IntentRouterService
from main_app.services.quiz_exporter import QuizExporter
from main_app.services.report_exporter import ReportExporter
from main_app.services.slide_deck_exporter import SlideDeckExporter
from main_app.services.source_grounding_service import SourceGroundingService
from main_app.services.video_asset_service import VideoAssetService
from main_app.services.video_exporter import VideoExporter
from main_app.ui.agent_dashboard import (
    AgentAssetRenderContext,
    AgentAssetRenderer,
    AgentDashboardChatFlowController,
    AgentDashboardSessionManager,
    apply_agent_dashboard_styles,
)
from main_app.ui.agent_dashboard.render_handlers import AgentAssetRenderHandler


def render_agent_dashboard_tab(
    *,
    agent_dashboard_service: AgentDashboardService,
    llm_service: CachedLLMService,
    settings: GroqSettings,
    web_sourcing_settings: WebSourcingSettings,
    cache_count_placeholder: Any,
    session_store: AgentDashboardSessionRepository,
    quiz_exporter: QuizExporter,
    report_exporter: ReportExporter,
    slide_exporter: SlideDeckExporter,
    video_service: VideoAssetService,
    video_exporter: VideoExporter,
    source_grounding_service: SourceGroundingService,
    global_grounding_service: GlobalGroundingService,
    asset_render_handlers: dict[str, AgentAssetRenderHandler] | None = None,
) -> None:
    session_manager = AgentDashboardSessionManager(session_store)
    session_manager.bootstrap_session()
    controller = AgentDashboardChatFlowController(
        settings=settings,
        llm_service=llm_service,
        cache_count_placeholder=cache_count_placeholder,
        agent_dashboard_service=agent_dashboard_service,
        session_manager=session_manager,
        web_sourcing_settings=web_sourcing_settings,
        source_grounding_service=source_grounding_service,
        global_grounding_service=global_grounding_service,
    )
    renderer = AgentAssetRenderer(
        AgentAssetRenderContext(
            settings=settings,
            llm_service=llm_service,
            cache_count_placeholder=cache_count_placeholder,
            agent_dashboard_service=agent_dashboard_service,
            quiz_exporter=quiz_exporter,
            report_exporter=report_exporter,
            slide_exporter=slide_exporter,
            video_service=video_service,
            video_exporter=video_exporter,
        ),
        render_handlers=asset_render_handlers,
    )

    apply_agent_dashboard_styles()
    st.markdown(
        (
            '<div class="ad-title-wrap">'
            '<div class="ad-title">Agent Dashboard Chat</div>'
            '<div class="ad-subtitle">'
            "Session-based conversation. Message intent is detected per turn, requirements are prepared, "
            "missing mandatory fields are requested, and assets are generated directly in this chat."
            "</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    planner_modes = ["Local First (No LLM if possible)", "Detect and Prepare Using LLM"]
    if st.session_state.agent_dashboard_planner_mode not in planner_modes:
        st.session_state.agent_dashboard_planner_mode = planner_modes[0]
    if bool(st.session_state.agent_dashboard_force_sync_planner_selector):
        st.session_state.agent_dashboard_planner_mode_selector = st.session_state.agent_dashboard_planner_mode
        st.session_state.agent_dashboard_force_sync_planner_selector = False
    elif st.session_state.agent_dashboard_planner_mode_selector not in planner_modes:
        st.session_state.agent_dashboard_planner_mode_selector = st.session_state.agent_dashboard_planner_mode

    top_col_1, top_col_2 = st.columns([0.72, 0.28], vertical_alignment="bottom")
    with top_col_1:
        planner_mode_label = st.radio(
            "Planner Mode",
            options=planner_modes,
            index=planner_modes.index(st.session_state.agent_dashboard_planner_mode_selector),
            horizontal=True,
            key="agent_dashboard_planner_mode_selector",
        )
        st.session_state.agent_dashboard_planner_mode = planner_mode_label
    with top_col_2:
        if st.button("Start New Session", key="agent_dashboard_new_session", width="stretch"):
            session_manager.persist_current_session()
            session_manager.start_fresh_session()
            st.rerun()

    saved_sessions = session_manager.list_saved_sessions()
    saved_ids = [str(item.get("id", "")).strip() for item in saved_sessions if str(item.get("id", "")).strip()]
    if saved_ids:
        if st.session_state.agent_dashboard_selected_saved_session_id not in saved_ids:
            st.session_state.agent_dashboard_selected_saved_session_id = saved_ids[0]
        if bool(st.session_state.agent_dashboard_force_sync_saved_selector):
            st.session_state.agent_dashboard_saved_session_selector = st.session_state.agent_dashboard_selected_saved_session_id
            st.session_state.agent_dashboard_force_sync_saved_selector = False
        elif st.session_state.agent_dashboard_saved_session_selector not in saved_ids:
            st.session_state.agent_dashboard_saved_session_selector = st.session_state.agent_dashboard_selected_saved_session_id

        saved_col_1, saved_col_2, saved_col_3 = st.columns([0.62, 0.19, 0.19], vertical_alignment="bottom")
        with saved_col_1:
            st.selectbox(
                "Saved Chat Sessions",
                options=saved_ids,
                format_func=lambda session_id: session_manager.saved_session_label(saved_sessions, session_id),
                key="agent_dashboard_saved_session_selector",
            )
            st.session_state.agent_dashboard_selected_saved_session_id = str(st.session_state.agent_dashboard_saved_session_selector).strip()
        with saved_col_2:
            if st.button("Load Selected", key="agent_dashboard_load_saved", width="stretch"):
                selected_id = str(st.session_state.agent_dashboard_selected_saved_session_id).strip()
                selected_session = session_manager.get_session(selected_id)
                if selected_session:
                    session_manager.restore_session_from_store_record(selected_session)
                    session_manager.persist_current_session()
                    st.rerun()
                st.warning("Could not load the selected session.")
        with saved_col_3:
            if st.button("Delete Selected", key="agent_dashboard_delete_saved", width="stretch"):
                selected_id = str(st.session_state.agent_dashboard_selected_saved_session_id).strip()
                current_id = str(st.session_state.agent_dashboard_session_id).strip()
                session_manager.delete_session(selected_id)
                refreshed = session_manager.list_saved_sessions()
                refreshed_ids = [str(item.get("id", "")).strip() for item in refreshed if str(item.get("id", "")).strip()]
                if selected_id == current_id:
                    session_manager.start_fresh_session()
                st.session_state.agent_dashboard_selected_saved_session_id = refreshed_ids[0] if refreshed_ids else ""
                st.session_state.agent_dashboard_force_sync_saved_selector = True
                st.rerun()
    else:
        st.session_state.agent_dashboard_selected_saved_session_id = ""
        st.session_state.agent_dashboard_saved_session_selector = ""
        st.caption("No saved chat sessions yet.")

    history: list[dict[str, Any]] = st.session_state.agent_dashboard_history
    pending_plan = st.session_state.agent_dashboard_pending_plan
    active_topic = " ".join(str(st.session_state.agent_dashboard_active_topic).split()).strip()
    recent_topics = st.session_state.agent_dashboard_recent_topics or []

    if active_topic:
        st.caption(f"Active session topic: {active_topic}")
    if recent_topics:
        st.caption("Recent topics: " + ", ".join(str(item) for item in recent_topics[:5]))

    if pending_plan:
        st.warning(
            "Pending mandatory requirement: please provide topic in your next message to continue generation."
        )

    for item_idx, item in enumerate(history):
        role = str(item.get("role", "assistant"))
        with st.chat_message(role):
            text = str(item.get("text", "")).strip()
            if text:
                bubble_role_class = "ad-msg-bubble-user" if role == "user" else "ad-msg-bubble-assistant"
                row_role_class = "ad-msg-row-user" if role == "user" else "ad-msg-row-assistant"
                st.markdown(
                    (
                        f'<div class="ad-msg-row {row_role_class}">'
                        f'<div class="ad-msg-bubble {bubble_role_class}">{escape(text)}</div>'
                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )
            intents = item.get("intents") or []
            if intents:
                st.markdown(
                    "".join(f'<span class="ad-chip">{escape(str(intent))}</span>' for intent in intents),
                    unsafe_allow_html=True,
                )
            notes = item.get("notes") or []
            if notes:
                joined_notes = "\n".join(f"- {str(note).strip()}" for note in notes if str(note).strip())
                if joined_notes:
                    st.markdown(f'<div class="ad-notes">{escape(joined_notes)}</div>', unsafe_allow_html=True)
            next_asks = item.get("next_asks") or []
            next_intents = item.get("next_intents") or []
            if next_asks:
                asks_html = "".join(
                    f'<p class="ad-next-item">- {escape(str(suggestion).strip())}</p>'
                    for suggestion in next_asks
                    if str(suggestion).strip()
                )
                intents_html = "".join(
                    f'<span class="ad-next-intent">{escape(str(intent))}</span>'
                    for intent in next_intents
                    if str(intent).strip()
                )
                st.markdown(
                    (
                        '<div class="ad-next-wrap">'
                        '<p class="ad-next-title">What you can ask next</p>'
                        f"{asks_html}"
                        f"{intents_html}"
                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )
            payloads = item.get("payloads")
            if payloads:
                with st.expander("Resolved Requirement Payloads", expanded=False):
                    st.json(payloads)
            assets = item.get("assets") or []
            if assets:
                renderer.render_assets_in_chat(assets=assets, item_idx=item_idx)

    prompt = st.chat_input("Chat with agent... e.g. Create quiz, slideshow, and narrated video for Segment Tree.")
    if not prompt:
        return

    planner_mode = (
        IntentRouterService.MODE_LOCAL_FIRST
        if planner_mode_label == "Local First (No LLM if possible)"
        else IntentRouterService.MODE_LLM_DRIVEN
    )
    controller.process_prompt(
        prompt=prompt,
        active_topic=active_topic,
        planner_mode=planner_mode,
        pending_plan=pending_plan,
    )
    st.rerun()
