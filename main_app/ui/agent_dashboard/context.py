from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from main_app.models import GroqSettings
from main_app.services.agent_dashboard import AgentDashboardService
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.quiz_exporter import QuizExporter
from main_app.services.report_exporter import ReportExporter
from main_app.services.slide_deck_exporter import SlideDeckExporter
from main_app.services.cartoon_exporter import CartoonExporter
from main_app.services.cartoon_shorts_asset_service import CartoonShortsAssetService
from main_app.services.video_asset_service import VideoAssetService
from main_app.services.video_exporter import VideoExporter


@dataclass(frozen=True)
class AgentAssetRenderContext:
    settings: GroqSettings
    llm_service: CachedLLMService
    cache_count_placeholder: Any
    agent_dashboard_service: AgentDashboardService
    quiz_exporter: QuizExporter
    report_exporter: ReportExporter
    slide_exporter: SlideDeckExporter
    video_service: VideoAssetService
    video_exporter: VideoExporter
    cartoon_service: CartoonShortsAssetService
    cartoon_exporter: CartoonExporter
