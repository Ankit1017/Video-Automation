from __future__ import annotations

from typing import Any, Callable

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
from main_app.models import AssetHistoryRecord, GroqSettings
from main_app.ui.asset_history.context import AssetHistoryRenderContext


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
    custom_renderers: dict[str, Callable[[AssetHistoryRecord, AssetHistoryRenderContext], None]] | None = None,
) -> None:
    from main_app.ui.asset_history.record_renderer import render_asset_history_tab as _render_impl

    _render_impl(
        asset_history_service=asset_history_service,
        settings=settings,
        llm_service=llm_service,
        cache_count_placeholder=cache_count_placeholder,
        agent_dashboard_service=agent_dashboard_service,
        audio_overview_service=audio_overview_service,
        video_service=video_service,
        quiz_exporter=quiz_exporter,
        report_exporter=report_exporter,
        slide_exporter=slide_exporter,
        video_exporter=video_exporter,
        cartoon_service=cartoon_service,
        cartoon_exporter=cartoon_exporter,
        custom_renderers=custom_renderers,
    )
