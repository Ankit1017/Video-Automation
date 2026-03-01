from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from main_app.parsers.audio_overview_parser import AudioOverviewParser
from main_app.parsers.data_table_parser import DataTableParser
from main_app.parsers.flashcards_parser import FlashcardsParser
from main_app.parsers.intent_parser import IntentParser
from main_app.parsers.mind_map_parser import MindMapParser
from main_app.parsers.quiz_parser import QuizParser
from main_app.parsers.slideshow_parser import SlideShowParser
from main_app.services.agent_dashboard import AgentDashboardService
from main_app.services.asset_history_service import AssetHistoryService
from main_app.services.audio_overview_service import AudioOverviewService
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.data_table_service import DataTableService
from main_app.services.flashcards_service import FlashcardsService
from main_app.services.global_grounding_service import GlobalGroundingService
from main_app.services.intent import IntentRouterService
from main_app.services.mind_map_service import MindMapService
from main_app.services.quiz_export_service import QuizExportService
from main_app.services.quiz_service import QuizService
from main_app.services.report_export_service import ReportExportService
from main_app.services.report_service import ReportService
from main_app.services.slideshow_service import SlideShowService
from main_app.services.source_grounding_service import SourceGroundingService
from main_app.domains.topic.services.topic_explainer_service import TopicExplainerService
from main_app.services.video_asset_service import VideoAssetService
from main_app.services.video_export_service import VideoExportService


@dataclass(frozen=True)
class AppContainer:
    explainer_service: TopicExplainerService
    mind_map_service: MindMapService
    flashcards_service: FlashcardsService
    report_service: ReportService
    data_table_service: DataTableService
    quiz_service: QuizService
    slideshow_service: SlideShowService
    audio_overview_service: AudioOverviewService
    video_service: VideoAssetService
    intent_router_service: IntentRouterService
    agent_dashboard_service: AgentDashboardService
    quiz_export_service: QuizExportService
    report_export_service: ReportExportService
    video_export_service: VideoExportService
    source_grounding_service: SourceGroundingService
    global_grounding_service: GlobalGroundingService
    asset_history_service: AssetHistoryService
    agent_dashboard_session_store: Any


def build_app_container(
    *,
    llm_service: CachedLLMService,
    storage_bundle: Any,
) -> AppContainer:
    asset_history_service = AssetHistoryService(storage_bundle.asset_history_store)
    explainer_service = TopicExplainerService(llm_service, history_service=asset_history_service)
    mind_map_service = MindMapService(llm_service, MindMapParser(llm_service), history_service=asset_history_service)
    flashcards_service = FlashcardsService(
        llm_service,
        FlashcardsParser(llm_service),
        history_service=asset_history_service,
    )
    report_service = ReportService(llm_service, history_service=asset_history_service)
    data_table_service = DataTableService(
        llm_service,
        DataTableParser(llm_service),
        history_service=asset_history_service,
    )
    quiz_service = QuizService(
        llm_service,
        QuizParser(llm_service),
        storage_bundle.quiz_history_store,
        asset_history_service=asset_history_service,
    )
    slideshow_service = SlideShowService(
        llm_service,
        SlideShowParser(llm_service),
        history_service=asset_history_service,
    )
    audio_overview_parser = AudioOverviewParser(llm_service)
    audio_overview_service = AudioOverviewService(
        llm_service,
        audio_overview_parser,
        history_service=asset_history_service,
    )
    video_service = VideoAssetService(
        llm_service,
        slideshow_service,
        audio_overview_parser,
        audio_overview_service,
        history_service=asset_history_service,
    )
    source_grounding_service = SourceGroundingService()
    global_grounding_service = GlobalGroundingService(
        source_grounding_service=source_grounding_service,
    )
    intent_router_service = IntentRouterService(llm_service, IntentParser())
    agent_dashboard_service = AgentDashboardService(
        intent_router=intent_router_service,
        explainer_service=explainer_service,
        mind_map_service=mind_map_service,
        flashcards_service=flashcards_service,
        data_table_service=data_table_service,
        quiz_service=quiz_service,
        slideshow_service=slideshow_service,
        video_service=video_service,
        audio_overview_service=audio_overview_service,
        report_service=report_service,
    )
    return AppContainer(
        explainer_service=explainer_service,
        mind_map_service=mind_map_service,
        flashcards_service=flashcards_service,
        report_service=report_service,
        data_table_service=data_table_service,
        quiz_service=quiz_service,
        slideshow_service=slideshow_service,
        audio_overview_service=audio_overview_service,
        video_service=video_service,
        intent_router_service=intent_router_service,
        agent_dashboard_service=agent_dashboard_service,
        quiz_export_service=QuizExportService(),
        report_export_service=ReportExportService(),
        video_export_service=VideoExportService(),
        source_grounding_service=source_grounding_service,
        global_grounding_service=global_grounding_service,
        asset_history_service=asset_history_service,
        agent_dashboard_session_store=storage_bundle.agent_dashboard_session_store,
    )
