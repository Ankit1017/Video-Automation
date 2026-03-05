from __future__ import annotations

from main_app.contracts import ChatHistory
from main_app.models import AgentAssetResult, AgentPlan, GroqSettings
from main_app.services.agent_dashboard.asset_executor_registry import (
    AgentAssetExecutorRegistry,
    build_default_asset_executor_registry,
)
from main_app.services.agent_dashboard.asset_service import AgentDashboardAssetService
from main_app.services.agent_dashboard.executor_types import AssetExecutionRuntimeContext
from main_app.services.agent_dashboard.conversation_service import AgentDashboardConversationService
from main_app.services.agent_dashboard.planner_service import AgentDashboardPlannerService
from main_app.services.audio_overview_service import AudioOverviewService
from main_app.services.cartoon_export_service import CartoonExportService
from main_app.services.cartoon_shorts_asset_service import CartoonShortsAssetService
from main_app.services.data_table_service import DataTableService
from main_app.services.flashcards_service import FlashcardsService
from main_app.services.intent import IntentRouterService
from main_app.services.mind_map_service import MindMapService
from main_app.services.quiz_service import QuizService
from main_app.services.report_service import ReportService
from main_app.services.slideshow_service import SlideShowService
from main_app.domains.topic.services.topic_explainer_service import TopicExplainerService
from main_app.services.video_asset_service import VideoAssetService
from main_app.services.agent_dashboard.tool_registry import AgentToolDefinition
from main_app.services.agent_dashboard.workflow_registry import AgentWorkflowDefinition


class AgentDashboardService:
    def __init__(
        self,
        *,
        intent_router: IntentRouterService,
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
        asset_executor_registry: AgentAssetExecutorRegistry | None = None,
        planner_service: AgentDashboardPlannerService | None = None,
        conversation_service: AgentDashboardConversationService | None = None,
        asset_service: AgentDashboardAssetService | None = None,
    ) -> None:
        registry = asset_executor_registry or build_default_asset_executor_registry(
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
        self._planner = planner_service or AgentDashboardPlannerService(intent_router=intent_router)
        self._conversation = conversation_service or AgentDashboardConversationService(intent_router=intent_router)
        self._assets = asset_service or AgentDashboardAssetService(
            intent_router=intent_router,
            asset_executor_registry=registry,
            mind_map_service=mind_map_service,
            flashcards_service=flashcards_service,
            quiz_service=quiz_service,
        )

    def plan_from_message(
        self,
        *,
        message: str,
        planner_mode: str,
        settings: GroqSettings,
        active_topic: str = "",
    ) -> tuple[AgentPlan | None, list[str], str | None, bool]:
        return self._planner.plan_from_message(
            message=message,
            planner_mode=planner_mode,
            settings=settings,
            active_topic=active_topic,
        )

    def generate_general_chat_reply(
        self,
        *,
        message: str,
        history: ChatHistory,
        active_topic: str,
        settings: GroqSettings,
    ) -> tuple[str | None, list[str], str | None, bool, str]:
        return self._conversation.generate_general_chat_reply(
            message=message,
            history=history,
            active_topic=active_topic,
            settings=settings,
        )

    def generate_followup_suggestions(
        self,
        *,
        last_user_message: str,
        history: ChatHistory,
        active_topic: str,
        settings: GroqSettings,
    ) -> tuple[list[str], list[str], str | None, bool]:
        return self._conversation.generate_followup_suggestions(
            last_user_message=last_user_message,
            history=history,
            active_topic=active_topic,
            settings=settings,
        )

    def apply_mandatory_reply(
        self,
        *,
        plan: AgentPlan,
        user_reply: str,
        settings: GroqSettings,
    ) -> tuple[AgentPlan, list[str], str | None, bool]:
        return self._planner.apply_mandatory_reply(
            plan=plan,
            user_reply=user_reply,
            settings=settings,
        )

    def auto_fill_optionals(
        self,
        *,
        plan: AgentPlan,
        settings: GroqSettings,
    ) -> tuple[AgentPlan, list[str], bool]:
        return self._planner.auto_fill_optionals(
            plan=plan,
            settings=settings,
        )

    def generate_assets_from_plan(
        self,
        *,
        plan: AgentPlan,
        settings: GroqSettings,
        runtime_context: AssetExecutionRuntimeContext | None = None,
    ) -> tuple[list[AgentAssetResult], list[str]]:
        return self._assets.generate_assets_from_plan(
            plan=plan,
            settings=settings,
            runtime_context=runtime_context,
        )

    def explain_mindmap_node(
        self,
        *,
        root_topic: str,
        node_path: str,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        return self._assets.explain_mindmap_node(
            root_topic=root_topic,
            node_path=node_path,
            settings=settings,
        )

    def explain_flashcard(
        self,
        *,
        topic: str,
        question: str,
        short_answer: str,
        card_index: int,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        return self._assets.explain_flashcard(
            topic=topic,
            question=question,
            short_answer=short_answer,
            card_index=card_index,
            settings=settings,
        )

    def get_quiz_hint(
        self,
        *,
        topic: str,
        question: str,
        options: list[str],
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        return self._assets.get_quiz_hint(
            topic=topic,
            question=question,
            options=options,
            settings=settings,
        )

    def get_quiz_attempt_feedback(
        self,
        *,
        topic: str,
        question: str,
        options: list[str],
        correct_index: int,
        selected_index: int,
        settings: GroqSettings,
    ) -> tuple[dict[str, str], bool]:
        return self._assets.get_quiz_attempt_feedback(
            topic=topic,
            question=question,
            options=options,
            correct_index=correct_index,
            selected_index=selected_index,
            settings=settings,
        )

    def explain_quiz_attempt(
        self,
        *,
        topic: str,
        question: str,
        options: list[str],
        correct_index: int,
        selected_index: int,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        return self._assets.explain_quiz_attempt(
            topic=topic,
            question=question,
            options=options,
            correct_index=correct_index,
            selected_index=selected_index,
            settings=settings,
        )

    def format_missing_mandatory_question(self, plan: AgentPlan) -> str:
        return self._planner.format_missing_mandatory_question(plan)

    def extract_primary_topic_from_plan(self, plan: AgentPlan) -> str:
        return self._planner.extract_primary_topic_from_plan(plan)

    def extract_primary_topic_from_assets(self, assets: list[AgentAssetResult]) -> str:
        return self._assets.extract_primary_topic_from_assets(assets)

    def list_registered_tools(self) -> list[AgentToolDefinition]:
        return self._assets.list_registered_tools()

    def list_registered_workflows(self) -> list[AgentWorkflowDefinition]:
        return self._assets.list_registered_workflows()

    def list_tool_stage_sequences(self) -> dict[str, list[str]]:
        return self._assets.list_tool_stage_sequences()
