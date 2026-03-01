from __future__ import annotations

import json
from typing import cast

from main_app.contracts import (
    IntentPayload,
    IntentPayloadMap,
    JSONObject,
    JSONValue,
    RequirementFieldSpec,
)
from main_app.parsers.json_utils import extract_json_text, repair_json_text_locally


class IntentRouterPayloadUtils:
    def __init__(self, *, intent_aliases: dict[str, str], intent_order: list[str]) -> None:
        self._intent_aliases = intent_aliases
        self._intent_order = intent_order

    def normalize_intent_name(self, value: str) -> str:
        cleaned = " ".join(str(value).strip().lower().split())
        if not cleaned:
            return ""
        return self._intent_aliases.get(cleaned, cleaned)

    def ordered_intents(self, intents: list[str]) -> list[str]:
        normalized_unique: list[str] = []
        for intent in intents:
            normalized = self.normalize_intent_name(intent)
            if normalized and normalized not in normalized_unique:
                normalized_unique.append(normalized)
        return sorted(
            normalized_unique,
            key=lambda item: self._intent_order.index(item) if item in self._intent_order else 999,
        )

    def find_intent_payload(self, requirement_map: JSONObject, intent: str) -> JSONValue:
        if intent in requirement_map:
            return requirement_map[intent]
        for key, value in requirement_map.items():
            if self.normalize_intent_name(str(key)) == intent:
                return value
        return {}

    @staticmethod
    def merge_payload_maps(
        local_payloads: IntentPayloadMap,
        llm_payloads: IntentPayloadMap,
    ) -> IntentPayloadMap:
        merged: IntentPayloadMap = {}
        intents = list(dict.fromkeys([*local_payloads.keys(), *llm_payloads.keys()]))
        for intent in intents:
            result = dict(llm_payloads.get(intent, {}))
            result.update(local_payloads.get(intent, {}))
            merged[intent] = cast(IntentPayload, result)
        return merged

    @staticmethod
    def parse_json_object(raw_text: str) -> tuple[JSONObject, str | None]:
        json_text = extract_json_text(raw_text)
        if not json_text:
            return {}, "Model output did not contain JSON."
        try:
            parsed = json.loads(json_text)
            if isinstance(parsed, dict):
                return parsed, None
            return {}, "JSON root is not an object."
        except json.JSONDecodeError:
            repaired = repair_json_text_locally(json_text)
            try:
                parsed = json.loads(repaired)
                if isinstance(parsed, dict):
                    return parsed, None
                return {}, "Repaired JSON root is not an object."
            except json.JSONDecodeError as exc:
                return {}, f"JSON parse error: {exc}"

    @staticmethod
    def normalize_field_value(
        meta: RequirementFieldSpec,
        value: object,
        *,
        allow_empty_string: bool,
    ) -> str | int | bool | None:
        field_type = str(meta.get("type", "text"))
        if field_type == "int":
            try:
                if isinstance(value, bool):
                    return None
                if isinstance(value, (int, float, str)):
                    number = int(float(value))
                else:
                    number = int(float(str(value)))
            except (TypeError, ValueError):
                return None
            min_value = int(meta.get("min", number))
            max_value = int(meta.get("max", number))
            return max(min_value, min(number, max_value))

        if field_type == "enum":
            options = [str(option) for option in meta.get("options", [])]
            if not options:
                return None
            raw = str(value).strip()
            if raw in options:
                return raw
            lowered_map = {option.lower(): option for option in options}
            return lowered_map.get(raw.lower())

        if field_type == "bool":
            if isinstance(value, bool):
                return value
            raw = str(value).strip().lower()
            if raw in {"true", "1", "yes", "y"}:
                return True
            if raw in {"false", "0", "no", "n"}:
                return False
            return None

        text = str(value).strip()
        if not text and not allow_empty_string:
            return None
        return text
