from __future__ import annotations

import streamlit as st

from main_app.app.bootstrap import build_main_registrations
from main_app.app.dependency_container import build_app_container
from main_app.constants import (
    AGENT_DASHBOARD_SESSIONS_FILE,
    APP_DESCRIPTION,
    APP_TITLE,
    ASSET_HISTORY_FILE,
    CACHE_FILE,
    PAGE_LAYOUT,
    PAGE_TITLE,
    QUIZ_HISTORY_FILE,
)
from main_app.infrastructure.groq_client import GroqChatCompletionClient
from main_app.infrastructure.storage_factory import build_storage_bundle
from main_app.services.background_jobs import BackgroundJobManager
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.observability_service import ObservabilityService, clear_request_id
from main_app.ui.sidebar import render_sidebar
from main_app.ui.state import initialize_session_state
from main_app.ui.tabs.main_tabs import render_main_tabs


def run_streamlit_app() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout=PAGE_LAYOUT)
    clear_request_id()

    storage_bundle = build_storage_bundle(
        cache_file=CACHE_FILE,
        asset_history_file=ASSET_HISTORY_FILE,
        quiz_history_file=QUIZ_HISTORY_FILE,
        agent_dashboard_sessions_file=AGENT_DASHBOARD_SESSIONS_FILE,
    )
    cache_store = storage_bundle.cache_store
    initialize_session_state(cache_store)

    if "observability_service" not in st.session_state:
        st.session_state.observability_service = ObservabilityService()
    observability_service: ObservabilityService = st.session_state.observability_service

    llm_service = CachedLLMService(
        chat_client=GroqChatCompletionClient(),
        cache_store=cache_store,
        cache_data=st.session_state.llm_cache,
        observability_service=observability_service,
    )
    container = build_app_container(llm_service=llm_service, storage_bundle=storage_bundle)

    st.title(APP_TITLE)
    st.write(APP_DESCRIPTION)
    sidebar_result = render_sidebar()

    if "background_job_manager" not in st.session_state:
        st.session_state.background_job_manager = BackgroundJobManager(max_workers=2)
    job_manager: BackgroundJobManager = st.session_state.background_job_manager

    registrations = build_main_registrations(
        container=container,
        llm_service=llm_service,
        observability_service=observability_service,
        settings=sidebar_result.settings,
        web_sourcing_settings=sidebar_result.web_sourcing_settings,
        cache_count_placeholder=sidebar_result.cache_count_placeholder,
        cache_location=storage_bundle.cache_label,
        job_manager=job_manager,
    )
    render_main_tabs(registrations, enabled_tab_titles=sidebar_result.enabled_tab_titles)
