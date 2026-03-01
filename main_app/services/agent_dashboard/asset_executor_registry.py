from __future__ import annotations

import inspect
from typing import Iterable, cast

from main_app.contracts import IntentPayload
from main_app.models import AgentAssetResult, GroqSettings
from main_app.services.agent_dashboard.executor_types import (
    AssetExecutor,
    AnyAssetExecutor,
    AssetExecutionRuntimeContext,
    AssetExecutorRegistration,
    LegacyAssetExecutor,
)
from main_app.services.audio_overview_service import AudioOverviewService
from main_app.services.data_table_service import DataTableService
from main_app.services.flashcards_service import FlashcardsService
from main_app.services.mind_map_service import MindMapService
from main_app.services.quiz_service import QuizService
from main_app.services.report_service import ReportService
from main_app.services.slideshow_service import SlideShowService
from main_app.domains.topic.services.topic_explainer_service import TopicExplainerService
from main_app.services.video_asset_service import VideoAssetService


class AgentAssetExecutorRegistry:
    def __init__(self, executors: dict[str, AnyAssetExecutor] | None = None) -> None:
        self._executors: dict[str, AnyAssetExecutor] = dict(executors or {})

    def register(self, intent: str, executor: AnyAssetExecutor) -> None:
        normalized_intent = " ".join(str(intent).strip().split()).lower()
        if not normalized_intent:
            return
        self._executors[normalized_intent] = executor

    def register_many(self, registrations: Iterable[AssetExecutorRegistration]) -> None:
        for registration in registrations:
            self.register(registration.intent, registration.executor)

    def has_intent(self, intent: str) -> bool:
        normalized_intent = " ".join(str(intent).strip().split()).lower()
        return normalized_intent in self._executors

    def execute(
        self,
        *,
        intent: str,
        payload: IntentPayload,
        settings: GroqSettings,
        runtime_context: AssetExecutionRuntimeContext | None = None,
    ) -> AgentAssetResult:
        normalized_intent = " ".join(str(intent).strip().split()).lower()
        executor = self._executors.get(normalized_intent)
        if executor is None:
            return AgentAssetResult(
                intent=intent,
                status="error",
                error="Unsupported intent.",
                payload=payload,
            )

        try:
            effective_runtime = runtime_context or AssetExecutionRuntimeContext()
            result = self._invoke_executor(
                executor=executor,
                payload=payload,
                settings=settings,
                runtime_context=effective_runtime,
            )
            if not result.intent:
                result.intent = intent
            if not result.payload:
                result.payload = payload
            return result
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError, OSError) as exc:
            return AgentAssetResult(
                intent=intent,
                status="error",
                error=f"Generation failed: {exc}",
                payload=payload,
            )

    @staticmethod
    def _invoke_executor(
        *,
        executor: AnyAssetExecutor,
        payload: IntentPayload,
        settings: GroqSettings,
        runtime_context: AssetExecutionRuntimeContext,
    ) -> AgentAssetResult:
        if AgentAssetExecutorRegistry._supports_runtime_context(executor):
            runtime_executor = cast(AssetExecutor, executor)
            return runtime_executor(payload, settings, runtime_context)
        legacy_executor = cast(LegacyAssetExecutor, executor)
        return legacy_executor(payload, settings)

    @staticmethod
    def _supports_runtime_context(executor: AnyAssetExecutor) -> bool:
        try:
            signature = inspect.signature(executor)
        except (TypeError, ValueError):
            # Prefer modern executor contract when signature introspection fails.
            return True
        positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        has_varargs = any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in signature.parameters.values())
        return has_varargs or len(positional) >= 3

def build_default_asset_executor_registry(
    *,
    explainer_service: TopicExplainerService,
    mind_map_service: MindMapService,
    flashcards_service: FlashcardsService,
    data_table_service: DataTableService,
    quiz_service: QuizService,
    slideshow_service: SlideShowService,
    video_service: VideoAssetService | None = None,
    audio_overview_service: AudioOverviewService,
    report_service: ReportService,
    extra_registrations: Iterable[AssetExecutorRegistration] | None = None,
) -> AgentAssetExecutorRegistry:
    from main_app.services.agent_dashboard.default_asset_executor_registrations import (
        build_default_asset_executor_registrations,
    )

    registry = AgentAssetExecutorRegistry()
    registry.register_many(
        build_default_asset_executor_registrations(
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
    )
    registry.register_many(extra_registrations or [])
    return registry
