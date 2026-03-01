from __future__ import annotations

import json
from typing import Any

from main_app.models import GroqSettings
from main_app.parsers.json_utils import extract_json_text, repair_json_text_locally
from main_app.services.cached_llm_service import CachedLLMService


class MindMapParser:
    def __init__(self, llm_service: CachedLLMService) -> None:
        self._llm_service = llm_service

    def parse(
        self,
        raw_text: str,
        *,
        max_depth: int,
        settings: GroqSettings,
    ) -> tuple[dict[str, Any] | None, str | None, str | None]:
        json_text = extract_json_text(raw_text)
        if not json_text:
            return None, "Model response did not contain a JSON object.", None

        parse_errors: list[str] = []

        try:
            parsed = json.loads(json_text)
            normalized, schema_error = self._normalize_parsed(parsed, max_depth=max_depth)
            if schema_error:
                return None, schema_error, None
            return normalized, None, None
        except json.JSONDecodeError as exc:
            parse_errors.append(f"original parse: {exc}")

        locally_repaired_json = repair_json_text_locally(json_text)
        if locally_repaired_json != json_text:
            try:
                parsed = json.loads(locally_repaired_json)
                normalized, schema_error = self._normalize_parsed(parsed, max_depth=max_depth)
                if schema_error:
                    return None, schema_error, None
                return normalized, None, "Input JSON had minor syntax issues and was auto-repaired locally."
            except json.JSONDecodeError as exc:
                parse_errors.append(f"local repair parse: {exc}")

        if settings.has_api_key() and settings.has_model():
            try:
                llm_repaired_text, repair_cache_hit = self._repair_json_with_llm(
                    raw_json_text=json_text,
                    settings=settings,
                )
                llm_json_text = extract_json_text(llm_repaired_text) or llm_repaired_text
                parsed = json.loads(llm_json_text)
                normalized, schema_error = self._normalize_parsed(parsed, max_depth=max_depth)
                if schema_error:
                    return None, schema_error, None
                repair_note = "Mind map JSON was repaired using LLM."
                if repair_cache_hit:
                    repair_note += " Repair result was served from cache."
                return normalized, None, repair_note
            except (
                AttributeError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                parse_errors.append(f"LLM repair parse: {exc}")

        return None, "Could not parse JSON mind map: " + " | ".join(parse_errors), None

    def _repair_json_with_llm(self, *, raw_json_text: str, settings: GroqSettings) -> tuple[str, bool]:
        repair_system_prompt = (
            "You repair malformed JSON. "
            "Return strictly valid JSON only. Do not explain, do not add markdown."
        )
        repair_user_prompt = (
            "The following JSON is invalid. Repair it while preserving structure and meaning.\n\n"
            f"{raw_json_text}"
        )
        repair_messages = [
            {"role": "system", "content": repair_system_prompt},
            {"role": "user", "content": repair_user_prompt},
        ]

        return self._llm_service.call(
            settings=settings,
            messages=repair_messages,
            task="mindmap_json_repair",
            label="MindMap JSON Repair",
            topic="mindmap_json_repair",
            temperature_override=0.0,
            max_tokens_override=min(int(settings.max_tokens), 2048),
        )

    def _normalize_parsed(
        self,
        parsed: Any,
        *,
        max_depth: int,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if isinstance(parsed, dict) and isinstance(parsed.get("root"), dict):
            parsed = parsed["root"]

        normalized = self._normalize_node(parsed, max_depth=max_depth)
        if normalized is None:
            return None, "JSON did not match expected mind map schema (`name`, `children`)."
        return normalized, None

    def _normalize_node(
        self,
        node: Any,
        *,
        max_depth: int,
        current_depth: int = 1,
    ) -> dict[str, Any] | None:
        if isinstance(node, str):
            node_name = node.strip()
            return {"name": node_name, "children": []} if node_name else None

        if not isinstance(node, dict):
            return None

        raw_name = node.get("name") or node.get("title") or node.get("topic")
        if raw_name is None:
            return None

        node_name = str(raw_name).strip()
        if not node_name:
            return None

        children: list[dict[str, Any]] = []
        normalized: dict[str, Any] = {"name": node_name, "children": children}
        if current_depth >= max_depth:
            return normalized

        raw_children = node.get("children", [])
        if not isinstance(raw_children, list):
            raw_children = []

        for child in raw_children:
            normalized_child = self._normalize_node(
                child,
                max_depth=max_depth,
                current_depth=current_depth + 1,
            )
            if normalized_child is not None:
                children.append(normalized_child)

        return normalized
