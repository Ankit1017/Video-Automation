from __future__ import annotations

from main_app.contracts import ChatHistory, RequirementSpecMap
from main_app.models import GroqSettings
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.intent.intent_router_payload_utils import IntentRouterPayloadUtils
from main_app.services.intent.intent_router_text_utils import IntentRouterTextUtils


class IntentConversationService:
    def __init__(
        self,
        *,
        llm_service: CachedLLMService,
        payload_utils: IntentRouterPayloadUtils,
        text_utils: IntentRouterTextUtils,
        requirement_spec: RequirementSpecMap,
    ) -> None:
        self._llm_service = llm_service
        self._payload_utils = payload_utils
        self._text_utils = text_utils
        self._requirement_spec = requirement_spec

    def generate_general_chat_reply(
        self,
        *,
        message: str,
        history: ChatHistory,
        active_topic: str,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        trimmed_history = history[-14:] if isinstance(history, list) else []
        context_messages: list[dict[str, str]] = []
        for item in trimmed_history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip().lower()
            if role not in {"user", "assistant"}:
                continue
            text = self._text_utils.clean_text(item.get("text", ""))
            if not text:
                continue
            context_messages.append({"role": role, "content": text[:1800]})

        if not context_messages or context_messages[-1]["role"] != "user":
            context_messages.append({"role": "user", "content": self._text_utils.clean_text(message)})

        current_topic = self._text_utils.clean_text(active_topic)
        system_prompt = (
            "You are a helpful assistant inside a learning app. "
            "Reply conversationally and clearly. "
            "Use prior chat context when relevant. "
            "If the user changes subject, naturally follow the new subject."
        )
        if current_topic:
            system_prompt += f" Current active topic for context: {current_topic}."

        messages = [{"role": "system", "content": system_prompt}, *context_messages]
        return self._llm_service.call(
            settings=settings,
            messages=messages,
            task="agent_general_chat",
            label=f"Agent Chat: {self._text_utils.clean_text(message)[:72]}",
            topic=current_topic or self._text_utils.clean_text(message)[:120],
        )

    def suggest_next_asks(
        self,
        *,
        last_user_message: str,
        history: ChatHistory,
        active_topic: str,
        settings: GroqSettings,
    ) -> tuple[list[str], list[str], bool, str | None]:
        current_topic = self._text_utils.clean_text(active_topic)
        context_lines: list[str] = []
        trimmed_history = history[-24:] if isinstance(history, list) else []
        for item in trimmed_history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip().lower()
            if role not in {"user", "assistant"}:
                continue
            text = self._text_utils.clean_text(item.get("text", ""))
            if not text:
                continue
            raw_intents = item.get("intents")
            intent_candidates = raw_intents if isinstance(raw_intents, list) else []
            intents = [
                self._text_utils.clean_text(intent)
                for intent in intent_candidates
                if self._text_utils.clean_text(intent)
            ]
            intents_suffix = f" | intents: {', '.join(intents)}" if intents else ""
            context_lines.append(f"{role}: {text[:240]}{intents_suffix}")

        context_block = "\n".join(context_lines[-24:])
        asset_list = ", ".join(f'"{intent}"' for intent in self._requirement_spec.keys())
        system_prompt = (
            "You are a learning assistant coach. "
            "Given the session context, suggest what user can ask next. "
            "Prefer prompts that use app assets when useful."
        )
        user_prompt = (
            "Return strict JSON only with this schema:\n"
            '{ "suggestions": ["..."], "intent_targets": ["topic"] }\n\n'
            "Rules:\n"
            "- Provide exactly 3 suggestions.\n"
            "- Keep each suggestion a single actionable prompt the user can send.\n"
            "- At least 2 suggestions should map to these asset intents: "
            f"{asset_list}.\n"
            "- Use current/previous topic context when relevant.\n"
            "- intent_targets must use only allowed intent names above.\n\n"
            f"Active topic: {current_topic or 'None'}\n"
            f"Last user message: {self._text_utils.clean_text(last_user_message)}\n\n"
            "Session context:\n"
            f"{context_block if context_block else '(empty)'}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        raw_text, cache_hit = self._llm_service.call(
            settings=settings,
            messages=messages,
            task="agent_followup_suggestions",
            label=f"Agent Followup Suggest: {self._text_utils.clean_text(last_user_message)[:72]}",
            topic=current_topic or self._text_utils.clean_text(last_user_message)[:120],
        )

        parsed_json, parse_error = self._payload_utils.parse_json_object(raw_text)
        if parse_error:
            fallback_suggestions = self._fallback_next_asks(
                last_user_message=last_user_message,
                active_topic=current_topic,
            )
            fallback_intents = ["topic", "mindmap", "quiz", "video"]
            return fallback_suggestions, fallback_intents, cache_hit, f"Suggestion parsing fallback used: {parse_error}"

        suggestions_raw = parsed_json.get("suggestions", [])
        suggestions: list[str] = []
        if isinstance(suggestions_raw, list):
            for value in suggestions_raw:
                text = self._text_utils.clean_text(value)
                if text and text not in suggestions:
                    suggestions.append(text)
        elif isinstance(suggestions_raw, str):
            text = self._text_utils.clean_text(suggestions_raw)
            if text:
                suggestions.append(text)

        intent_targets_raw = parsed_json.get("intent_targets", [])
        intent_targets: list[str] = []
        if isinstance(intent_targets_raw, list):
            for value in intent_targets_raw:
                normalized = self._payload_utils.normalize_intent_name(str(value))
                if normalized in self._requirement_spec and normalized not in intent_targets:
                    intent_targets.append(normalized)
        elif isinstance(intent_targets_raw, str):
            normalized = self._payload_utils.normalize_intent_name(intent_targets_raw)
            if normalized in self._requirement_spec:
                intent_targets.append(normalized)

        if not suggestions:
            suggestions = self._fallback_next_asks(
                last_user_message=last_user_message,
                active_topic=current_topic,
            )
        if not intent_targets:
            intent_targets = ["topic", "mindmap", "quiz", "video"]

        return suggestions[:3], intent_targets[:4], cache_hit, None

    def _fallback_next_asks(self, *, last_user_message: str, active_topic: str) -> list[str]:
        topic = active_topic or self._text_utils.fallback_topic_from_message(last_user_message) or "this topic"
        return [
            f"Create a concise mindmap for {topic} with 3 depth levels.",
            f"Generate a 10-question quiz on {topic} with intermediate difficulty.",
            f"Create a narrated video asset for {topic} with multi-voice explanation and code where relevant.",
        ]
