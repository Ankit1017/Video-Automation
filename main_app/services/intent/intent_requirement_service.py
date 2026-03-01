from __future__ import annotations

import json
from typing import Any, cast

from main_app.contracts import (
    IntentPayload,
    IntentPayloadMap,
    RequirementFieldSpec,
    RequirementSpecMap,
)
from main_app.models import GroqSettings
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.intent.intent_router_payload_utils import IntentRouterPayloadUtils
from main_app.services.intent.intent_router_text_utils import IntentRouterTextUtils


def _to_intent_payload(value: object) -> IntentPayload:
    if not isinstance(value, dict):
        return {}
    return cast(IntentPayload, {str(key): item for key, item in value.items()})


def _set_payload_field(payload: IntentPayload, field_name: str, value: object) -> None:
    cast(dict[str, object], payload)[field_name] = value


class IntentRequirementService:
    MODE_LOCAL_FIRST = "local_first"
    MODE_LLM_DRIVEN = "llm_driven"

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
        self._constraint_field_by_intent = {
            "topic": "additional_instructions",
            "mindmap": "constraints",
            "flashcards": "constraints",
            "quiz": "constraints",
            "slideshow": "constraints",
            "video": "constraints",
            "audio_overview": "constraints",
            "data table": "notes",
            "report": "additional_notes",
        }

    def prepare_requirements(
        self,
        *,
        message: str,
        intents: list[str],
        settings: GroqSettings,
        mode: str = MODE_LOCAL_FIRST,
    ) -> tuple[IntentPayloadMap, str | None, bool]:
        normalized_mode = mode if mode in {self.MODE_LOCAL_FIRST, self.MODE_LLM_DRIVEN} else self.MODE_LOCAL_FIRST
        normalized_intents = [
            intent for intent in self._payload_utils.ordered_intents(intents) if intent in self._requirement_spec
        ]
        if not normalized_intents:
            return {}, "No supported intents to prepare.", False

        if normalized_mode == self.MODE_LLM_DRIVEN:
            if not settings.has_api_key() or not settings.has_model():
                return {}, "LLM-driven preparation requires Groq API key and model.", False

            llm_payload, llm_note, llm_cache_hit = self._extract_requirements_with_llm(
                message=message,
                intents=normalized_intents,
                settings=settings,
            )
            requirement_map = llm_payload.get("requirements", {}) if isinstance(llm_payload, dict) else {}
            if not isinstance(requirement_map, dict):
                requirement_map = {}

            global_topic = (
                self._text_utils.clean_text(llm_payload.get("topic", "")) if isinstance(llm_payload, dict) else ""
            )
            prepared: IntentPayloadMap = {}
            for intent in normalized_intents:
                raw_payload = self._payload_utils.find_intent_payload(requirement_map, intent)
                prepared[intent] = self._normalize_partial_payload(
                    intent=intent,
                    raw_payload=raw_payload,
                    fallback_topic=global_topic,
                )

            final_note: str | None = llm_note or "Requirements extracted via LLM-driven mode."
            return prepared, final_note, llm_cache_hit

        local_prepared, local_note = self._extract_requirements_locally(
            message=message,
            intents=normalized_intents,
        )
        missing_topic_intents = [
            intent
            for intent in normalized_intents
            if not self._text_utils.clean_text(local_prepared.get(intent, {}).get("topic", ""))
        ]
        if not missing_topic_intents:
            return local_prepared, local_note, False

        if not settings.has_api_key() or not settings.has_model():
            note = (
                f"{local_note} Missing topic for intents: {', '.join(missing_topic_intents)}. "
                "LLM fallback unavailable due to missing Groq settings."
            ).strip()
            return local_prepared, note, False

        llm_payload, llm_note, llm_cache_hit = self._extract_requirements_with_llm(
            message=message,
            intents=normalized_intents,
            settings=settings,
        )

        global_topic = self._text_utils.clean_text(llm_payload.get("topic", "")) if isinstance(llm_payload, dict) else ""
        requirement_map = llm_payload.get("requirements", {}) if isinstance(llm_payload, dict) else {}
        if not isinstance(requirement_map, dict):
            requirement_map = {}

        llm_prepared: IntentPayloadMap = {}
        for intent in normalized_intents:
            raw_payload = self._payload_utils.find_intent_payload(requirement_map, intent)
            llm_prepared[intent] = self._normalize_partial_payload(
                intent=intent,
                raw_payload=raw_payload,
                fallback_topic=global_topic,
            )

        merged = self._payload_utils.merge_payload_maps(local_prepared, llm_prepared)
        note_parts: list[str] = [str(part) for part in [local_note, llm_note] if part]
        if note_parts:
            note_parts.append("Local extraction was prioritized; LLM only filled remaining gaps.")
        final_note = " ".join(note_parts).strip() if note_parts else None
        return merged, final_note, llm_cache_hit

    def evaluate_requirements(self, *, intent: str, payload: IntentPayload) -> tuple[list[str], list[str]]:
        spec = self._requirement_spec.get(intent)
        if not spec:
            return ["topic"], []

        missing_mandatory: list[str] = []
        topic_text = self._text_utils.clean_text(payload.get("topic", ""))
        if not IntentRouterTextUtils.is_valid_topic(topic_text):
            missing_mandatory.append("topic")

        missing_optional: list[str] = []
        optional_fields = spec.get("optional", {})
        for field_name in optional_fields:
            if field_name not in payload:
                missing_optional.append(field_name)

        return missing_mandatory, missing_optional

    def optional_field_definitions(self, intent: str) -> dict[str, RequirementFieldSpec]:
        spec = self._requirement_spec.get(intent, {})
        optional = spec.get("optional", {})
        return dict(optional)

    def apply_default_optionals(
        self,
        *,
        intent: str,
        payload: IntentPayload,
        missing_optional: list[str],
    ) -> IntentPayload:
        updated: dict[str, object] = dict(payload)
        optional_defs = self.optional_field_definitions(intent)
        for field_name in missing_optional:
            meta = optional_defs.get(field_name)
            if not meta:
                continue
            updated[field_name] = meta.get("default")
        return _to_intent_payload(updated)

    def apply_user_optionals(
        self,
        *,
        intent: str,
        payload: IntentPayload,
        user_values: IntentPayload,
        missing_optional: list[str],
    ) -> IntentPayload:
        updated: dict[str, object] = dict(payload)
        user_values_map = cast(dict[str, object], user_values)
        optional_defs = self.optional_field_definitions(intent)
        for field_name in missing_optional:
            if field_name not in user_values_map:
                continue
            meta = optional_defs.get(field_name)
            if not meta:
                continue
            user_value = user_values_map.get(field_name)
            normalized = self._payload_utils.normalize_field_value(
                meta,
                user_value,
                allow_empty_string=True,
            )
            if normalized is not None:
                updated[field_name] = normalized
        return _to_intent_payload(updated)

    def fill_optional_with_llm(
        self,
        *,
        intent: str,
        message: str,
        payload: IntentPayload,
        missing_optional: list[str],
        settings: GroqSettings,
    ) -> tuple[IntentPayload, str | None, str | None, bool]:
        optional_defs = self.optional_field_definitions(intent)
        target_fields = [field for field in missing_optional if field in optional_defs]
        if not target_fields:
            return _to_intent_payload(payload), "No optional fields to fill.", None, False

        field_spec_lines: list[str] = []
        for field_name in target_fields:
            meta = optional_defs[field_name]
            line = f"- {field_name} ({meta.get('type', 'text')})"
            if meta.get("type") == "enum":
                line += f" options={meta.get('options', [])}"
            elif meta.get("type") == "int":
                line += f" range={meta.get('min', 0)}..{meta.get('max', 100)}"
            field_spec_lines.append(line)

        system_prompt = "You fill missing asset requirement fields from user message context. Return strict JSON only."
        user_prompt = (
            f"Intent: {intent}\n"
            f"User message: {message.strip()}\n"
            f"Current payload: {json.dumps(payload, ensure_ascii=False)}\n\n"
            "Fill these missing optional fields when inferable:\n"
            + "\n".join(field_spec_lines)
            + "\n\nReturn JSON object with only those field keys you can infer."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        raw_text, cache_hit = self._llm_service.call(
            settings=settings,
            messages=messages,
            task=f"intent_optional_fill_{intent.replace(' ', '_')}",
            label=f"Intent Optional Fill: {intent}",
            topic=message.strip()[:120],
        )

        extracted_json, parse_error = self._payload_utils.parse_json_object(raw_text)
        if parse_error:
            return _to_intent_payload(payload), None, f"Optional fill parse failed: {parse_error}", cache_hit

        updated: dict[str, object] = dict(payload)
        filled_count = 0
        for field_name in target_fields:
            if field_name not in extracted_json:
                continue
            normalized = self._payload_utils.normalize_field_value(
                optional_defs[field_name],
                extracted_json[field_name],
                allow_empty_string=False,
            )
            if normalized is None:
                continue
            updated[field_name] = normalized
            filled_count += 1

        if filled_count == 0:
            return _to_intent_payload(updated), "LLM could not confidently infer optional values.", None, cache_hit

        return _to_intent_payload(updated), f"LLM filled {filled_count} optional field(s).", None, cache_hit

    def _extract_requirements_with_llm(
        self,
        *,
        message: str,
        intents: list[str],
        settings: GroqSettings,
    ) -> tuple[dict[str, object], str | None, bool]:
        default_empty: dict[str, object] = {"topic": "", "requirements": {}}
        if not intents:
            return default_empty, None, False

        intent_specs: list[str] = []
        for intent in intents:
            optional_defs = self.optional_field_definitions(intent)
            opt_parts = []
            for field_name, meta in optional_defs.items():
                field_type = meta.get("type", "text")
                if field_type == "enum":
                    opt_parts.append(f"{field_name}<{field_type}:{meta.get('options', [])}>")
                elif field_type == "int":
                    opt_parts.append(f"{field_name}<{field_type}:{meta.get('min')}..{meta.get('max')}>")
                else:
                    opt_parts.append(f"{field_name}<{field_type}>")
            intent_specs.append(f"- {intent}: topic (mandatory), " + ", ".join(opt_parts))

        system_prompt = (
            "You extract structured asset requirements from user chat. "
            "Return strict JSON only."
        )
        user_prompt = (
            "Detected intents:\n"
            + "\n".join(f"- {intent}" for intent in intents)
            + "\n\nRequirement field specs:\n"
            + "\n".join(intent_specs)
            + "\n\nReturn JSON with this schema:\n"
            "{\n"
            '  "topic": "global topic if present else empty string",\n'
            '  "requirements": {\n'
            '    "<intent>": {\n'
            '      "topic": "topic for this intent if present",\n'
            '      "<optional_field>": "<value if explicitly inferable>"\n'
            "    }\n"
            "  }\n"
            "}\n\nRules:\n"
            "- Include only values inferable from the user message.\n"
            "- If a field is not inferable, omit that key.\n"
            "- Do not fabricate unknown values.\n"
            "- Return JSON only.\n\n"
            f"User message:\n{message.strip()}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        raw_text, cache_hit = self._llm_service.call(
            settings=settings,
            messages=messages,
            task="intent_extract_requirements",
            label=f"Intent Requirement Extract: {message.strip()[:72]}",
            topic=message.strip()[:120],
        )
        parsed_json, parse_error = self._payload_utils.parse_json_object(raw_text)
        if parse_error:
            return default_empty, f"Requirement extraction fallback used: {parse_error}", cache_hit

        topic_text = self._text_utils.clean_text(parsed_json.get("topic", ""))
        if not IntentRouterTextUtils.is_valid_topic(topic_text):
            topic_text = ""

        requirements = parsed_json.get("requirements", {})
        if not isinstance(requirements, dict):
            requirements = {}

        return cast(dict[str, object], {"topic": topic_text, "requirements": requirements}), None, cache_hit

    def _extract_requirements_locally(
        self,
        *,
        message: str,
        intents: list[str],
    ) -> tuple[IntentPayloadMap, str]:
        prepared: IntentPayloadMap = {}
        global_topic = self._text_utils.fallback_topic_from_message(message)
        constraint_text = self._text_utils.extract_constraint_text_from_message(message)

        for intent in intents:
            payload: IntentPayload = {}
            if global_topic:
                payload["topic"] = global_topic

            constraint_field = self._constraint_field_by_intent.get(intent)
            if constraint_text and constraint_field:
                _set_payload_field(payload, constraint_field, constraint_text)

            optional_defs = self.optional_field_definitions(intent)
            for field_name, meta in optional_defs.items():
                if field_name in payload:
                    continue
                extracted_value = self._text_utils.extract_field_from_message(
                    message=message,
                    field_name=field_name,
                )
                if extracted_value is None:
                    continue
                normalized = self._payload_utils.normalize_field_value(
                    meta,
                    extracted_value,
                    allow_empty_string=False,
                )
                if normalized is not None:
                    _set_payload_field(payload, field_name, normalized)

            prepared[intent] = payload

        return prepared, "Requirements were first extracted locally from user message."

    def _normalize_partial_payload(
        self,
        *,
        intent: str,
        raw_payload: Any,
        fallback_topic: str,
    ) -> IntentPayload:
        payload: IntentPayload = {}
        if isinstance(raw_payload, dict):
            topic_value = self._text_utils.clean_text(raw_payload.get("topic", ""))
        else:
            topic_value = ""

        if not topic_value:
            topic_value = self._text_utils.clean_text(fallback_topic)
        if IntentRouterTextUtils.is_valid_topic(topic_value):
            payload["topic"] = topic_value

        optional_defs = self.optional_field_definitions(intent)
        if isinstance(raw_payload, dict):
            for field_name, meta in optional_defs.items():
                if field_name not in raw_payload:
                    continue
                normalized = self._payload_utils.normalize_field_value(
                    meta,
                    raw_payload[field_name],
                    allow_empty_string=False,
                )
                if normalized is not None:
                    _set_payload_field(payload, field_name, normalized)

        return payload
