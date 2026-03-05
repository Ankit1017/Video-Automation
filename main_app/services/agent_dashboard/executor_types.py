from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from main_app.contracts import IntentPayload
from main_app.models import AgentAssetResult, GroqSettings
from main_app.services.audio_overview_service import AudioOverviewService
from main_app.services.cartoon_export_service import CartoonExportService
from main_app.services.cartoon_shorts_asset_service import CartoonShortsAssetService
from main_app.services.data_table_service import DataTableService
from main_app.services.flashcards_service import FlashcardsService
from main_app.services.mind_map_service import MindMapService
from main_app.services.quiz_service import QuizService
from main_app.services.report_service import ReportService
from main_app.services.slideshow_service import SlideShowService
from main_app.domains.topic.services.topic_explainer_service import TopicExplainerService
from main_app.services.video_asset_service import VideoAssetService


@dataclass(frozen=True)
class AssetExecutionRuntimeContext:
    grounding_context: str = ""
    source_manifest: list[dict[str, object]] = field(default_factory=list)
    require_citations: bool = False
    diagnostics: dict[str, object] = field(default_factory=dict)


AssetExecutor = Callable[[IntentPayload, GroqSettings, AssetExecutionRuntimeContext], AgentAssetResult]
LegacyAssetExecutor = Callable[[IntentPayload, GroqSettings], AgentAssetResult]
AnyAssetExecutor = AssetExecutor | LegacyAssetExecutor


@dataclass(frozen=True)
class AssetExecutorRegistration:
    intent: str
    executor: AnyAssetExecutor


@dataclass(frozen=True)
class AssetExecutorPluginContext:
    explainer_service: TopicExplainerService
    mind_map_service: MindMapService
    flashcards_service: FlashcardsService
    data_table_service: DataTableService
    quiz_service: QuizService
    slideshow_service: SlideShowService
    video_service: VideoAssetService | None
    cartoon_service: CartoonShortsAssetService | None
    cartoon_export_service: CartoonExportService | None
    audio_overview_service: AudioOverviewService
    report_service: ReportService


AssetExecutorFactory = Callable[[AssetExecutorPluginContext], AnyAssetExecutor]


@dataclass(frozen=True)
class AssetExecutorPlugin:
    intent: str
    build_executor: AssetExecutorFactory
