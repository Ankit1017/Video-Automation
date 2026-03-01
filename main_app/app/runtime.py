from __future__ import annotations

import streamlit as st
from uuid import uuid4

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
    RUN_LEDGER_FILE,
    STAGE_LEDGER_FILE,
)
from main_app.infrastructure.groq_client import GroqChatCompletionClient
from main_app.infrastructure.storage_factory import build_storage_bundle
from main_app.services.background_jobs import BackgroundJobManager
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.observability_service import ObservabilityService, clear_request_id, ensure_request_id
from main_app.services.telemetry_service import TelemetryService
from main_app.ui.sidebar import render_sidebar
from main_app.ui.state import initialize_session_state
from main_app.ui.tabs.main_tabs import render_main_tabs


def run_streamlit_app() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout=PAGE_LAYOUT)
    clear_request_id()
    request_id = ensure_request_id()
    if "telemetry_service" not in st.session_state:
        st.session_state.telemetry_service = TelemetryService()
    telemetry_service: TelemetryService = st.session_state.telemetry_service

    storage_bundle = build_storage_bundle(
        cache_file=CACHE_FILE,
        asset_history_file=ASSET_HISTORY_FILE,
        quiz_history_file=QUIZ_HISTORY_FILE,
        agent_dashboard_sessions_file=AGENT_DASHBOARD_SESSIONS_FILE,
        run_ledger_file=RUN_LEDGER_FILE,
        stage_ledger_file=STAGE_LEDGER_FILE,
        telemetry_service=telemetry_service,
    )
    cache_store = storage_bundle.cache_store
    initialize_session_state(cache_store)

    if "telemetry_session_id" not in st.session_state:
        st.session_state.telemetry_session_id = f"sess_{uuid4().hex[:12]}"
    telemetry_session_id = " ".join(str(st.session_state.get("telemetry_session_id", "")).split()).strip()

    if "observability_service" not in st.session_state:
        st.session_state.observability_service = ObservabilityService(telemetry_service=telemetry_service)
    observability_service: ObservabilityService = st.session_state.observability_service

    with telemetry_service.context_scope(request_id=request_id, session_id=telemetry_session_id):
        with telemetry_service.start_span(
            name="ui.request",
            component="ui.runtime",
            attrs={"app_title": APP_TITLE},
        ):
            llm_service = CachedLLMService(
                chat_client=GroqChatCompletionClient(),
                cache_store=cache_store,
                cache_data=st.session_state.llm_cache,
                observability_service=observability_service,
            )
            container = build_app_container(
                llm_service=llm_service,
                storage_bundle=storage_bundle,
                telemetry_service=telemetry_service,
            )

            st.title(APP_TITLE)
            st.write(APP_DESCRIPTION)
            sidebar_result = render_sidebar()

            if "background_job_manager" not in st.session_state:
                st.session_state.background_job_manager = BackgroundJobManager(
                    max_workers=2,
                    telemetry_service=telemetry_service,
                )
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
