from __future__ import annotations

from typing import Any

from main_app.app.dependency_container import AppContainer
from main_app.services.background_jobs import BackgroundJobManager
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.observability_service import ObservabilityService
from main_app.services.pptx_export_service import PptxExportService
from main_app.models import WebSourcingSettings
from main_app.ui.tabs.main_tabs import build_main_tab_registrations


def build_main_registrations(
    *,
    container: AppContainer,
    llm_service: CachedLLMService,
    observability_service: ObservabilityService | None,
    settings: Any,
    web_sourcing_settings: WebSourcingSettings,
    cache_count_placeholder: Any,
    cache_location: str,
    job_manager: BackgroundJobManager,
) -> list[Any]:
    return build_main_tab_registrations(
        explainer_service=container.explainer_service,
        mind_map_service=container.mind_map_service,
        flashcards_service=container.flashcards_service,
        report_service=container.report_service,
        data_table_service=container.data_table_service,
        quiz_service=container.quiz_service,
        slideshow_service=container.slideshow_service,
        video_service=container.video_service,
        audio_overview_service=container.audio_overview_service,
        intent_router_service=container.intent_router_service,
        agent_dashboard_service=container.agent_dashboard_service,
        asset_history_service=container.asset_history_service,
        llm_service=llm_service,
        observability_service=observability_service,
        settings=settings,
        web_sourcing_settings=web_sourcing_settings,
        cache_count_placeholder=cache_count_placeholder,
        cache_location=cache_location,
        agent_dashboard_session_store=container.agent_dashboard_session_store,
        quiz_exporter=container.quiz_export_service,
        report_exporter=container.report_export_service,
        slide_exporter=PptxExportService(),
        video_exporter=container.video_export_service,
        job_manager=job_manager,
        source_grounding_service=container.source_grounding_service,
        global_grounding_service=container.global_grounding_service,
    )
