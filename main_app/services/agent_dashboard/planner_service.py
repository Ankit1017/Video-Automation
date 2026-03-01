from __future__ import annotations

from typing import cast

from main_app.contracts import IntentPayload, IntentPayloadMap
from main_app.models import AgentPlan, GroqSettings
from main_app.services.intent import IntentRouterService


def _to_intent_payload(value: object) -> IntentPayload:
    if not isinstance(value, dict):
        return {}
    return cast(IntentPayload, {str(key): item for key, item in value.items()})


class AgentDashboardPlannerService:
    def __init__(self, intent_router: IntentRouterService) -> None:
        self._intent_router = intent_router

    def plan_from_message(
        self,
        *,
        message: str,
        planner_mode: str,
        settings: GroqSettings,
        active_topic: str = "",
    ) -> tuple[AgentPlan | None, list[str], str | None, bool]:
        notes: list[str] = []
        cache_hit_any = False

        detect_result = self._intent_router.detect_intent(
            message=message,
            settings=settings,
            mode=planner_mode,
        )
        if detect_result.parse_note:
            notes.append(detect_result.parse_note)
        cache_hit_any = cache_hit_any or detect_result.cache_hit

        if detect_result.parse_error:
            return None, notes, detect_result.parse_error, cache_hit_any

        if detect_result.intents is not None and not detect_result.intents:
            return None, notes, None, cache_hit_any

        if not detect_result.intents:
            return None, notes, "Could not detect intent.", cache_hit_any

        payloads, prep_note, prep_cache_hit = self._intent_router.prepare_requirements(
            message=message,
            intents=detect_result.intents,
            settings=settings,
            mode=planner_mode,
        )
        if prep_note:
            notes.append(prep_note)
        cache_hit_any = cache_hit_any or prep_cache_hit

        payloads, topic_context_note = self._apply_session_topic_context(
            message=message,
            payloads=payloads,
            active_topic=active_topic,
        )
        if topic_context_note:
            notes.append(topic_context_note)

        plan = self._build_plan(
            message=message,
            planner_mode=planner_mode,
            intents=detect_result.intents,
            payloads=payloads,
        )
        return plan, notes, None, cache_hit_any

    def apply_mandatory_reply(
        self,
        *,
        plan: AgentPlan,
        user_reply: str,
        settings: GroqSettings,
    ) -> tuple[AgentPlan, list[str], str | None, bool]:
        notes: list[str] = []
        cache_hit_any = False
        payloads: IntentPayloadMap = {intent: _to_intent_payload(payload) for intent, payload in plan.payloads.items()}

        topic_value, topic_note, topic_error, topic_cache_hit = self._intent_router.extract_topic_from_message(
            message=user_reply,
            settings=settings,
        )
        if topic_note:
            notes.append(topic_note)
        cache_hit_any = cache_hit_any or topic_cache_hit

        if topic_error and not topic_value:
            return plan, notes, topic_error, cache_hit_any

        if topic_value:
            for intent in plan.intents:
                payload = payloads.get(intent, {})
                missing_mandatory, _ = self._intent_router.evaluate_requirements(intent=intent, payload=payload)
                if "topic" in missing_mandatory:
                    payload["topic"] = topic_value
                payloads[intent] = payload

        updated_plan = self._build_plan(
            message=plan.source_message,
            planner_mode=plan.planner_mode or IntentRouterService.MODE_LOCAL_FIRST,
            intents=plan.intents,
            payloads=payloads,
        )
        return updated_plan, notes, None, cache_hit_any

    def auto_fill_optionals(
        self,
        *,
        plan: AgentPlan,
        settings: GroqSettings,
    ) -> tuple[AgentPlan, list[str], bool]:
        notes: list[str] = []
        cache_hit_any = False
        payloads: IntentPayloadMap = {intent: _to_intent_payload(payload) for intent, payload in plan.payloads.items()}

        source_message = str(plan.source_message)
        for intent in plan.intents:
            payload = payloads.get(intent, {})
            missing_mandatory, missing_optional = self._intent_router.evaluate_requirements(intent=intent, payload=payload)
            if missing_mandatory:
                continue

            if missing_optional and settings.has_api_key() and settings.has_model():
                updated_payload, fill_note, fill_error, fill_cache_hit = self._intent_router.fill_optional_with_llm(
                    intent=intent,
                    message=source_message,
                    payload=payload,
                    missing_optional=missing_optional,
                    settings=settings,
                )
                payload = updated_payload
                cache_hit_any = cache_hit_any or fill_cache_hit
                if fill_error:
                    notes.append(f"{intent}: {fill_error}")
                elif fill_note:
                    notes.append(f"{intent}: {fill_note}")

            _, remaining_optional = self._intent_router.evaluate_requirements(intent=intent, payload=payload)
            if remaining_optional:
                payload = self._intent_router.apply_default_optionals(
                    intent=intent,
                    payload=payload,
                    missing_optional=remaining_optional,
                )
                notes.append(f"{intent}: Applied default values for {len(remaining_optional)} optional field(s).")

            payloads[intent] = payload

        updated_plan = self._build_plan(
            message=source_message,
            planner_mode=plan.planner_mode or IntentRouterService.MODE_LOCAL_FIRST,
            intents=plan.intents,
            payloads=payloads,
        )
        return updated_plan, notes, cache_hit_any

    def format_missing_mandatory_question(self, plan: AgentPlan) -> str:
        missing_intents = []
        missing_map: dict[str, list[str]] = plan.missing_mandatory or {}
        for intent, fields in missing_map.items():
            if "topic" in fields:
                missing_intents.append(intent)
        if not missing_intents:
            return ""

        intents_text = ", ".join(missing_intents)
        return (
            f"I need one mandatory field before I can generate assets. "
            f"Please provide the topic for: {intents_text}."
        )

    def extract_primary_topic_from_plan(self, plan: AgentPlan) -> str:
        payloads: IntentPayloadMap = plan.payloads or {}
        for payload in payloads.values():
            topic = " ".join(str(payload.get("topic", "")).split()).strip()
            if self._intent_router.is_valid_topic(topic):
                return topic
        return ""

    def _build_plan(
        self,
        *,
        message: str,
        planner_mode: str,
        intents: list[str],
        payloads: IntentPayloadMap,
    ) -> AgentPlan:
        missing_mandatory: dict[str, list[str]] = {}
        missing_optional: dict[str, list[str]] = {}
        for intent in intents:
            payload = payloads.get(intent, {})
            mandatory, optional = self._intent_router.evaluate_requirements(intent=intent, payload=payload)
            missing_mandatory[intent] = mandatory
            missing_optional[intent] = optional

        return AgentPlan(
            source_message=message,
            planner_mode=planner_mode,
            intents=intents,
            payloads=payloads,
            missing_mandatory=missing_mandatory,
            missing_optional=missing_optional,
        )

    def _apply_session_topic_context(
        self,
        *,
        message: str,
        payloads: IntentPayloadMap,
        active_topic: str,
    ) -> tuple[IntentPayloadMap, str | None]:
        normalized_active_topic = " ".join(str(active_topic).split()).strip()
        if not normalized_active_topic:
            return payloads, None

        explicit_topic = self._intent_router.infer_topic_from_message_local(message)
        if explicit_topic:
            return payloads, None

        is_followup_reference = self._intent_router.is_followup_reference_message(message)
        has_missing_or_invalid_topic = any(
            not self._intent_router.is_valid_topic(" ".join(str((payload or {}).get("topic", "")).split()).strip())
            for payload in payloads.values()
        )

        if not is_followup_reference and not has_missing_or_invalid_topic:
            return payloads, None

        updated_payloads: IntentPayloadMap = {}
        updated_count = 0

        for intent, payload in payloads.items():
            next_payload = _to_intent_payload(payload)
            current_topic = " ".join(str(next_payload.get("topic", "")).split()).strip()
            should_override = is_followup_reference or not self._intent_router.is_valid_topic(current_topic)
            if should_override and current_topic.lower() != normalized_active_topic.lower():
                next_payload["topic"] = normalized_active_topic
                updated_count += 1
            updated_payloads[intent] = next_payload

        if updated_count == 0:
            return payloads, None

        return (
            updated_payloads,
            (
                f"Session context applied. Reused session topic `{normalized_active_topic}` "
                f"for {updated_count} intent(s)."
            ),
        )
