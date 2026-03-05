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
from main_app.services.agent_dashboard.asset_executor_registry import build_default_asset_executor_registry
from main_app.services.agent_dashboard.asset_service import AgentDashboardAssetService
from main_app.services.agent_dashboard.run_ledger_service import RunLedgerService
from main_app.services.agent_dashboard.stage_ledger_service import StageLedgerService
from main_app.services.asset_history_service import AssetHistoryService
from main_app.services.audio_overview_service import AudioOverviewService
from main_app.services.cartoon_audio_service import CartoonAudioService
from main_app.services.cartoon_character_pack_service import CartoonCharacterPackService
from main_app.services.cartoon_export_service import CartoonExportService
from main_app.services.cartoon_shorts_asset_service import CartoonShortsAssetService
from main_app.services.cartoon_storyboard_service import CartoonStoryboardService
from main_app.services.cartoon_timeline_service import CartoonTimelineService
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
from main_app.services.telemetry_service import TelemetryService


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
    cartoon_shorts_service: CartoonShortsAssetService
    cartoon_audio_service: CartoonAudioService
    cartoon_export_service: CartoonExportService
    intent_router_service: IntentRouterService
    agent_dashboard_service: AgentDashboardService
    quiz_export_service: QuizExportService
    report_export_service: ReportExportService
    video_export_service: VideoExportService
    source_grounding_service: SourceGroundingService
    global_grounding_service: GlobalGroundingService
    asset_history_service: AssetHistoryService
    agent_dashboard_session_store: Any


@dataclass(frozen=True)
class AppServiceFactories:
    topic_explainer_service_cls: type[TopicExplainerService] = TopicExplainerService
    mind_map_parser_cls: type[MindMapParser] = MindMapParser
    mind_map_service_cls: type[MindMapService] = MindMapService
    flashcards_parser_cls: type[FlashcardsParser] = FlashcardsParser
    flashcards_service_cls: type[FlashcardsService] = FlashcardsService
    report_service_cls: type[ReportService] = ReportService
    data_table_parser_cls: type[DataTableParser] = DataTableParser
    data_table_service_cls: type[DataTableService] = DataTableService
    quiz_parser_cls: type[QuizParser] = QuizParser
    quiz_service_cls: type[QuizService] = QuizService
    slideshow_parser_cls: type[SlideShowParser] = SlideShowParser
    slideshow_service_cls: type[SlideShowService] = SlideShowService
    audio_overview_parser_cls: type[AudioOverviewParser] = AudioOverviewParser
    audio_overview_service_cls: type[AudioOverviewService] = AudioOverviewService
    video_asset_service_cls: type[VideoAssetService] = VideoAssetService
    cartoon_storyboard_service_cls: type[CartoonStoryboardService] = CartoonStoryboardService
    cartoon_timeline_service_cls: type[CartoonTimelineService] = CartoonTimelineService
    cartoon_character_pack_service_cls: type[CartoonCharacterPackService] = CartoonCharacterPackService
    cartoon_shorts_asset_service_cls: type[CartoonShortsAssetService] = CartoonShortsAssetService
    cartoon_audio_service_cls: type[CartoonAudioService] = CartoonAudioService
    cartoon_export_service_cls: type[CartoonExportService] = CartoonExportService
    source_grounding_service_cls: type[SourceGroundingService] = SourceGroundingService
    global_grounding_service_cls: type[GlobalGroundingService] = GlobalGroundingService
    intent_parser_cls: type[IntentParser] = IntentParser
    intent_router_service_cls: type[IntentRouterService] = IntentRouterService
    run_ledger_service_cls: type[RunLedgerService] = RunLedgerService
    stage_ledger_service_cls: type[StageLedgerService] = StageLedgerService
    agent_asset_service_cls: type[AgentDashboardAssetService] = AgentDashboardAssetService
    agent_dashboard_service_cls: type[AgentDashboardService] = AgentDashboardService
    quiz_export_service_cls: type[QuizExportService] = QuizExportService
    report_export_service_cls: type[ReportExportService] = ReportExportService
    video_export_service_cls: type[VideoExportService] = VideoExportService
    asset_history_service_cls: type[AssetHistoryService] = AssetHistoryService


def build_app_container(
    *,
    llm_service: CachedLLMService,
    storage_bundle: Any,
    telemetry_service: TelemetryService | None = None,
    factories: AppServiceFactories | None = None,
) -> AppContainer:
    service_factories = factories or AppServiceFactories()
    asset_history_service = service_factories.asset_history_service_cls(storage_bundle.asset_history_store)
    explainer_service = service_factories.topic_explainer_service_cls(llm_service, history_service=asset_history_service)
    mind_map_service = service_factories.mind_map_service_cls(
        llm_service,
        service_factories.mind_map_parser_cls(llm_service),
        history_service=asset_history_service,
    )
    flashcards_service = service_factories.flashcards_service_cls(
        llm_service,
        service_factories.flashcards_parser_cls(llm_service),
        history_service=asset_history_service,
    )
    report_service = service_factories.report_service_cls(llm_service, history_service=asset_history_service)
    data_table_service = service_factories.data_table_service_cls(
        llm_service,
        service_factories.data_table_parser_cls(llm_service),
        history_service=asset_history_service,
    )
    quiz_service = service_factories.quiz_service_cls(
        llm_service,
        service_factories.quiz_parser_cls(llm_service),
        storage_bundle.quiz_history_store,
        asset_history_service=asset_history_service,
    )
    slideshow_service = service_factories.slideshow_service_cls(
        llm_service,
        service_factories.slideshow_parser_cls(llm_service),
        history_service=asset_history_service,
    )
    audio_overview_parser = service_factories.audio_overview_parser_cls(llm_service)
    audio_overview_service = service_factories.audio_overview_service_cls(
        llm_service,
        audio_overview_parser,
        history_service=asset_history_service,
    )
    video_service = service_factories.video_asset_service_cls(
        llm_service,
        slideshow_service,
        audio_overview_parser,
        audio_overview_service,
        history_service=asset_history_service,
    )
    cartoon_storyboard_service = service_factories.cartoon_storyboard_service_cls(llm_service)
    cartoon_timeline_service = service_factories.cartoon_timeline_service_cls()
    cartoon_character_pack_service = service_factories.cartoon_character_pack_service_cls()
    cartoon_shorts_service = service_factories.cartoon_shorts_asset_service_cls(
        storyboard_service=cartoon_storyboard_service,
        timeline_service=cartoon_timeline_service,
        character_pack_service=cartoon_character_pack_service,
        history_service=asset_history_service,
    )
    cartoon_audio_service = service_factories.cartoon_audio_service_cls(audio_overview_service)
    cartoon_export_service = service_factories.cartoon_export_service_cls(telemetry_service=telemetry_service)
    source_grounding_service = service_factories.source_grounding_service_cls()
    global_grounding_service = service_factories.global_grounding_service_cls(
        source_grounding_service=source_grounding_service,
        telemetry_service=telemetry_service,
    )
    intent_router_service = service_factories.intent_router_service_cls(
        llm_service,
        service_factories.intent_parser_cls(),
    )
    run_ledger_service = service_factories.run_ledger_service_cls(store=storage_bundle.run_ledger_store)
    stage_ledger_service = service_factories.stage_ledger_service_cls(store=storage_bundle.stage_ledger_store)
    asset_executor_registry = build_default_asset_executor_registry(
        explainer_service=explainer_service,
        mind_map_service=mind_map_service,
        flashcards_service=flashcards_service,
        data_table_service=data_table_service,
        quiz_service=quiz_service,
        slideshow_service=slideshow_service,
        video_service=video_service,
        cartoon_service=cartoon_shorts_service,
        cartoon_export_service=cartoon_export_service,
        audio_overview_service=audio_overview_service,
        report_service=report_service,
    )
    agent_asset_service = service_factories.agent_asset_service_cls(
        intent_router=intent_router_service,
        asset_executor_registry=asset_executor_registry,
        mind_map_service=mind_map_service,
        flashcards_service=flashcards_service,
        quiz_service=quiz_service,
        run_ledger_service=run_ledger_service,
        stage_ledger_service=stage_ledger_service,
        telemetry_service=telemetry_service,
    )
    agent_dashboard_service = service_factories.agent_dashboard_service_cls(
        intent_router=intent_router_service,
        explainer_service=explainer_service,
        mind_map_service=mind_map_service,
        flashcards_service=flashcards_service,
        data_table_service=data_table_service,
        quiz_service=quiz_service,
        slideshow_service=slideshow_service,
        video_service=video_service,
        cartoon_service=cartoon_shorts_service,
        cartoon_export_service=cartoon_export_service,
        audio_overview_service=audio_overview_service,
        report_service=report_service,
        asset_service=agent_asset_service,
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
        cartoon_shorts_service=cartoon_shorts_service,
        cartoon_audio_service=cartoon_audio_service,
        cartoon_export_service=cartoon_export_service,
        intent_router_service=intent_router_service,
        agent_dashboard_service=agent_dashboard_service,
        quiz_export_service=service_factories.quiz_export_service_cls(telemetry_service=telemetry_service),
        report_export_service=service_factories.report_export_service_cls(telemetry_service=telemetry_service),
        video_export_service=service_factories.video_export_service_cls(telemetry_service=telemetry_service),
        source_grounding_service=source_grounding_service,
        global_grounding_service=global_grounding_service,
        asset_history_service=asset_history_service,
        agent_dashboard_session_store=storage_bundle.agent_dashboard_session_store,
    )
