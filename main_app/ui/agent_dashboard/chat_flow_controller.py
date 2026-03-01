from __future__ import annotations

from typing import Any

from main_app.models import AgentPlan, GroqSettings, WebSourcingSettings
from main_app.services.observability_service import ensure_request_id
from main_app.services.agent_dashboard import AgentDashboardService
from main_app.services.agent_dashboard.executor_types import AssetExecutionRuntimeContext
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.global_grounding_service import GlobalGroundingService
from main_app.services.source_grounding_service import SourceGroundingService
from main_app.services.telemetry_service import ObservabilityEvent
from main_app.ui.agent_dashboard.session_manager import AgentDashboardSessionManager
from main_app.ui.agent_dashboard.state_gateway import SessionStateGateway


class AgentDashboardChatFlowController:
    def __init__(
        self,
        *,
        settings: GroqSettings,
        llm_service: CachedLLMService,
        cache_count_placeholder: Any,
        agent_dashboard_service: AgentDashboardService,
        session_manager: AgentDashboardSessionManager,
        web_sourcing_settings: WebSourcingSettings,
        source_grounding_service: SourceGroundingService,
        global_grounding_service: GlobalGroundingService,
    ) -> None:
        self._settings = settings
        self._llm_service = llm_service
        self._cache_count_placeholder = cache_count_placeholder
        self._agent_dashboard_service = agent_dashboard_service
        self._session_manager = session_manager
        self._web_sourcing_settings = web_sourcing_settings
        self._source_grounding_service = source_grounding_service
        self._global_grounding_service = global_grounding_service
        self._state: SessionStateGateway = session_manager.state

    def process_prompt(
        self,
        *,
        prompt: str,
        active_topic: str,
        planner_mode: str,
        pending_plan: dict[str, Any] | None,
    ) -> None:
        request_id = ensure_request_id()
        telemetry = self._llm_service.observability.telemetry_service if self._llm_service.observability else None
        context_scope = telemetry.context_scope(request_id=request_id) if telemetry is not None else _null_context()
        with context_scope:
            if telemetry is not None:
                telemetry.record_event(
                    ObservabilityEvent(
                        event_name="agent.chat.process_prompt.start",
                        component="agent_dashboard.chat_flow",
                        status="started",
                        timestamp=_now_iso(),
                        attributes={"planner_mode": planner_mode, "has_pending_plan": bool(pending_plan)},
                    )
                )
        history_raw = self._state.get("agent_dashboard_history", [])
        history: list[dict[str, Any]] = history_raw if isinstance(history_raw, list) else []
        history.append({"role": "user", "text": prompt.strip()})
        self._state.set("agent_dashboard_history", history)
        self._session_manager.persist_current_session()

        if pending_plan:
            self._handle_pending_mandatory_flow(
                prompt=prompt,
                plan=pending_plan,
                planner_mode=planner_mode,
            )
            self._session_manager.persist_current_session()
            if telemetry is not None:
                telemetry.record_event(
                    ObservabilityEvent(
                        event_name="agent.chat.process_prompt.end",
                        component="agent_dashboard.chat_flow",
                        status="ok",
                        timestamp=_now_iso(),
                        attributes={"path": "pending_mandatory"},
                    )
                )
            return

        self._handle_new_message_flow(
            prompt=prompt,
            history=history,
            active_topic=active_topic,
            planner_mode=planner_mode,
        )
        self._session_manager.persist_current_session()
        if telemetry is not None:
            telemetry.record_event(
                ObservabilityEvent(
                    event_name="agent.chat.process_prompt.end",
                    component="agent_dashboard.chat_flow",
                    status="ok",
                    timestamp=_now_iso(),
                    attributes={"path": "new_message"},
                )
            )

    def _handle_new_message_flow(
        self,
        *,
        prompt: str,
        history: list[dict[str, Any]],
        active_topic: str,
        planner_mode: str,
    ) -> None:
        plan, notes, error, cache_hit = self._agent_dashboard_service.plan_from_message(
            message=prompt,
            planner_mode=planner_mode,
            settings=self._settings,
            active_topic=active_topic,
        )
        if error or not plan:
            reply_text, fallback_notes, fallback_error, _, topic_candidate = (
                self._agent_dashboard_service.generate_general_chat_reply(
                    message=prompt,
                    history=history,
                    active_topic=active_topic,
                    settings=self._settings,
                )
            )
            combined_notes = [*notes, *fallback_notes]
            if error:
                combined_notes.append(f"Plan generation note: {error}")
            if topic_candidate:
                self._session_manager.update_session_topics(topic_candidate)

            if fallback_error and not reply_text:
                self._append_assistant_entry_with_followups(
                    entry={
                        "role": "assistant",
                        "text": fallback_error,
                        "notes": combined_notes,
                    },
                    last_user_message=prompt,
                )
                return

            self._append_assistant_entry_with_followups(
                entry={
                    "role": "assistant",
                    "text": reply_text or "I can help with that.",
                    "notes": combined_notes,
                },
                last_user_message=prompt,
            )
            return

        plan_topic = self._agent_dashboard_service.extract_primary_topic_from_plan(plan)
        if plan_topic:
            self._session_manager.update_session_topics(plan_topic)

        if self._has_missing_mandatory(plan):
            question = self._agent_dashboard_service.format_missing_mandatory_question(plan)
            self._state.set("agent_dashboard_pending_plan", plan.to_dict())
            self._append_assistant_entry_with_followups(
                entry={
                    "role": "assistant",
                    "text": question or "Mandatory requirement missing. Please provide topic.",
                    "intents": list(plan.intents),
                    "payloads": dict(plan.payloads),
                    "notes": notes,
                },
                last_user_message=prompt,
            )
            return

        self._finalize_and_generate_assets(
            source_plan=plan,
            last_user_message=prompt,
            notes=notes,
            cache_hit=cache_hit,
        )

    def _handle_pending_mandatory_flow(
        self,
        *,
        prompt: str,
        plan: dict[str, Any],
        planner_mode: str,
    ) -> None:
        typed_plan = AgentPlan.from_dict(plan)
        updated_plan, notes, error, cache_hit = self._agent_dashboard_service.apply_mandatory_reply(
            plan=typed_plan,
            user_reply=prompt,
            settings=self._settings,
        )

        if error:
            self._append_assistant_entry_with_followups(
                entry={
                    "role": "assistant",
                    "text": error,
                    "notes": notes,
                    "intents": list(typed_plan.intents),
                    "payloads": dict(typed_plan.payloads),
                },
                last_user_message=prompt,
            )
            self._state.set("agent_dashboard_pending_plan", typed_plan.to_dict())
            return

        updated_plan.planner_mode = planner_mode

        plan_topic = self._agent_dashboard_service.extract_primary_topic_from_plan(updated_plan)
        if plan_topic:
            self._session_manager.update_session_topics(plan_topic)

        if self._has_missing_mandatory(updated_plan):
            question = self._agent_dashboard_service.format_missing_mandatory_question(updated_plan)
            self._state.set("agent_dashboard_pending_plan", updated_plan.to_dict())
            self._append_assistant_entry_with_followups(
                entry={
                    "role": "assistant",
                    "text": question or "Mandatory requirement still missing. Please provide the topic clearly.",
                    "notes": notes,
                    "intents": list(updated_plan.intents),
                    "payloads": dict(updated_plan.payloads),
                },
                last_user_message=prompt,
            )
            return

        self._finalize_and_generate_assets(
            source_plan=updated_plan,
            last_user_message=prompt,
            notes=notes,
            cache_hit=cache_hit,
        )

    def _finalize_and_generate_assets(
        self,
        *,
        source_plan: AgentPlan,
        last_user_message: str,
        notes: list[str],
        cache_hit: bool,
    ) -> None:
        if not self._settings.has_api_key() or not self._settings.has_model():
            combined_notes = [*notes, "Asset generation needs Groq API key and model in sidebar."]
            self._state.set("agent_dashboard_pending_plan", None)
            self._append_assistant_entry_with_followups(
                entry={
                    "role": "assistant",
                    "text": "Requirements are ready, but generation cannot start without Groq API key and model.",
                    "intents": list(source_plan.intents),
                    "payloads": dict(source_plan.payloads),
                    "notes": combined_notes,
                },
                last_user_message=last_user_message,
            )
            return

        auto_filled_plan, fill_notes, fill_cache_hit = self._agent_dashboard_service.auto_fill_optionals(
            plan=source_plan,
            settings=self._settings,
        )
        runtime_context, grounding_notes, blocked = self._build_runtime_grounding_context(
            plan=auto_filled_plan,
            last_user_message=last_user_message,
        )
        if blocked:
            self._state.set("agent_dashboard_pending_plan", None)
            self._append_assistant_entry_with_followups(
                entry={
                    "role": "assistant",
                    "text": "Strict web-grounding mode blocked generation because no valid sources were found.",
                    "intents": list(auto_filled_plan.intents),
                    "payloads": dict(auto_filled_plan.payloads),
                    "notes": [*notes, *fill_notes, *grounding_notes],
                },
                last_user_message=last_user_message,
            )
            return

        assets, generation_notes = self._agent_dashboard_service.generate_assets_from_plan(
            plan=auto_filled_plan,
            settings=self._settings,
            runtime_context=runtime_context,
        )

        all_notes = [*notes, *fill_notes, *grounding_notes, *generation_notes]
        assistant_text = "Processed intents, resolved requirements, and generated assets in this chat."

        self._state.set("agent_dashboard_pending_plan", None)
        generated_topic = self._agent_dashboard_service.extract_primary_topic_from_assets(assets)
        if generated_topic:
            self._session_manager.update_session_topics(generated_topic)

        self._append_assistant_entry_with_followups(
            entry={
                "role": "assistant",
                "text": assistant_text,
                "intents": list(auto_filled_plan.intents),
                "payloads": dict(auto_filled_plan.payloads),
                "assets": [asset.to_dict() for asset in assets],
                "notes": all_notes,
            },
            last_user_message=last_user_message,
        )

        if not (cache_hit and fill_cache_hit):
            self._cache_count_placeholder.caption(f"Cached responses: {self._llm_service.count}")

    def _build_runtime_grounding_context(
        self,
        *,
        plan: AgentPlan,
        last_user_message: str,
    ) -> tuple[AssetExecutionRuntimeContext, list[str], bool]:
        if not self._web_sourcing_settings.enabled:
            return AssetExecutionRuntimeContext(), [], False

        topic = self._agent_dashboard_service.extract_primary_topic_from_plan(plan)
        query_topic = topic or " ".join(str(last_user_message).split()).strip()
        query_constraints = " ".join(str(last_user_message).split()).strip()
        sources, warnings, diagnostics = self._global_grounding_service.build_sources(
            [],
            topic=query_topic,
            constraints=query_constraints,
            web_settings=self._web_sourcing_settings,
            max_sources=min(8, max(1, int(self._web_sourcing_settings.max_fetch_pages))),
        )
        blocked = bool(self._web_sourcing_settings.strict_mode and not sources)
        notes: list[str] = []
        if sources:
            notes.append(f"Web grounding collected {len(sources)} source(s) for this run.")
        for warning in warnings:
            notes.append(f"Web grounding note: {warning}")

        grounding_context = self._source_grounding_service.build_grounding_context(sources)
        source_manifest = self._source_grounding_service.build_source_manifest(sources)
        require_citations = bool(sources)
        runtime_context = AssetExecutionRuntimeContext(
            grounding_context=grounding_context,
            source_manifest=source_manifest,
            require_citations=require_citations,
            diagnostics=dict(diagnostics),
        )
        return runtime_context, notes, blocked

    def _append_assistant_entry_with_followups(
        self,
        *,
        entry: dict[str, Any],
        last_user_message: str,
    ) -> None:
        notes = list(entry.get("notes") or [])
        active_topic = " ".join(str(self._state.get("agent_dashboard_active_topic", "")).split()).strip()
        history_raw = self._state.get("agent_dashboard_history", [])
        history: list[dict[str, Any]] = history_raw if isinstance(history_raw, list) else []
        suggestions, intent_targets, suggestion_error, cache_hit = self._agent_dashboard_service.generate_followup_suggestions(
            last_user_message=last_user_message,
            history=history,
            active_topic=active_topic,
            settings=self._settings,
        )
        if suggestions:
            entry["next_asks"] = suggestions
        if intent_targets:
            entry["next_intents"] = intent_targets
        if suggestion_error:
            notes.append(suggestion_error)
        elif suggestions:
            notes.append("Added AI-suggested next asks that can move toward asset-based flows.")
        if notes:
            entry["notes"] = notes

        history.append(entry)
        self._state.set("agent_dashboard_history", history)
        if not cache_hit:
            self._cache_count_placeholder.caption(f"Cached responses: {self._llm_service.count}")

    @staticmethod
    def _has_missing_mandatory(plan: AgentPlan | dict[str, Any]) -> bool:
        typed_plan = plan if isinstance(plan, AgentPlan) else AgentPlan.from_dict(plan)
        missing_mandatory = typed_plan.missing_mandatory or {}
        for fields in missing_mandatory.values():
            if fields:
                return True
        return False


from contextlib import contextmanager
from typing import Iterator


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def _null_context() -> Iterator[None]:
    yield
