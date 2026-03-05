from __future__ import annotations

from typing import Iterable

from main_app.services.agent_dashboard.executor_plugins import (
    AssetExecutorPluginContext,
    discover_asset_executor_plugins,
)
from main_app.services.agent_dashboard.executor_types import AssetExecutorRegistration
from main_app.services.agent_dashboard.intent_catalog import ASSET_INTENTS
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


def build_default_asset_executor_registrations(
    *,
    explainer_service: TopicExplainerService,
    mind_map_service: MindMapService,
    flashcards_service: FlashcardsService,
    data_table_service: DataTableService,
    quiz_service: QuizService,
    slideshow_service: SlideShowService,
    video_service: VideoAssetService | None = None,
    cartoon_service: CartoonShortsAssetService | None = None,
    cartoon_export_service: CartoonExportService | None = None,
    audio_overview_service: AudioOverviewService,
    report_service: ReportService,
) -> Iterable[AssetExecutorRegistration]:
    context = AssetExecutorPluginContext(
        explainer_service=explainer_service,
        mind_map_service=mind_map_service,
        flashcards_service=flashcards_service,
        data_table_service=data_table_service,
        quiz_service=quiz_service,
        slideshow_service=slideshow_service,
        video_service=video_service,
        cartoon_service=cartoon_service,
        cartoon_export_service=cartoon_export_service,
        audio_overview_service=audio_overview_service,
        report_service=report_service,
    )
    plugins = discover_asset_executor_plugins()
    plugin_map: dict[str, AssetExecutorRegistration] = {}
    for plugin in plugins:
        normalized_intent = " ".join(str(plugin.intent).strip().split()).lower()
        if not normalized_intent:
            continue
        plugin_map[normalized_intent] = AssetExecutorRegistration(
            intent=normalized_intent,
            executor=plugin.build_executor(context),
        )

    ordered_intents = [intent for intent in ASSET_INTENTS if intent in plugin_map]
    ordered_intents.extend(
        sorted(intent for intent in plugin_map.keys() if intent not in ASSET_INTENTS)
    )
    return [plugin_map[intent] for intent in ordered_intents]
