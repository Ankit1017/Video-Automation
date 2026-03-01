from __future__ import annotations

from typing import cast

from main_app.contracts import MindMapPayload
from main_app.models import GroqSettings, MindMapGenerationResult
from main_app.parsers.mind_map_parser import MindMapParser
from main_app.services.asset_history_service import AssetHistoryService
from main_app.services.cached_llm_service import CachedLLMService


class MindMapService:
    def __init__(
        self,
        llm_service: CachedLLMService,
        parser: MindMapParser,
        history_service: AssetHistoryService | None = None,
    ) -> None:
        self._llm_service = llm_service
        self._parser = parser
        self._history_service = history_service

    def generate(
        self,
        *,
        topic: str,
        max_depth: int,
        constraints: str,
        settings: GroqSettings,
    ) -> MindMapGenerationResult:
        mind_map_system_prompt = (
            "You generate hierarchical mind maps as JSON only. "
            "Do not explain anything. Return valid JSON and nothing else."
        )
        mind_map_user_prompt = (
            f"Create a mind map for topic: {topic.strip()}\n"
            "Output JSON with this schema:\n"
            "{\n"
            '  "name": "topic",\n'
            '  "children": [\n'
            '    {"name": "subtopic", "children": [...]}\n'
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            f"- Expand depth up to {max_depth} levels if token budget allows.\n"
            "- Each non-leaf node should have 3 to 6 meaningful children when possible.\n"
            "- Avoid single-chain structure. Keep branching across first 2 levels.\n"
            "- Keep node names short (2 to 6 words).\n"
            "- Use [] for leaf children.\n"
            "- Return JSON only (no markdown, no comments)."
        )
        if constraints.strip():
            mind_map_user_prompt += f"\n\nAdditional constraints:\n{constraints.strip()}"

        messages = [
            {"role": "system", "content": mind_map_system_prompt},
            {"role": "user", "content": mind_map_user_prompt},
        ]

        raw_text, cache_hit = self._llm_service.call(
            settings=settings,
            messages=messages,
            task="mindmap_graph",
            label=f"MindMap Graph: {topic.strip()}",
            topic=topic.strip(),
        )

        parsed_map, parse_error, parse_note = self._parser.parse(
            raw_text,
            max_depth=max_depth,
            settings=settings,
        )
        result = MindMapGenerationResult(
            raw_text=raw_text,
            parsed_map=cast(MindMapPayload | None, parsed_map),
            parse_error=parse_error,
            parse_note=parse_note,
            cache_hit=cache_hit,
        )
        if self._history_service is not None:
            self._history_service.record_generation(
                asset_type="mindmap",
                topic=topic.strip(),
                title=f"Mind Map: {topic.strip()}",
                model=settings.normalized_model,
                request_payload={
                    "topic": topic.strip(),
                    "max_depth": max_depth,
                    "constraints": constraints.strip(),
                },
                result_payload=parsed_map if parsed_map is not None else {},
                status="error" if parse_error else "success",
                cache_hit=cache_hit,
                parse_note=parse_note or "",
                error=parse_error or "",
                raw_text=raw_text if parse_error else "",
            )
        return result

    def explain_node(
        self,
        *,
        root_topic: str,
        node_path: str,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        explain_system_prompt = "You are an expert teacher. Provide detailed, structured, and practical explanations."
        explain_user_prompt = (
            f"Root topic: {root_topic}\n"
            f"Selected node path: {node_path}\n\n"
            "Explain this selected node in detail.\n"
            "Include: definition, key concepts, practical examples, common mistakes, and what to learn next."
        )
        explain_messages = [
            {"role": "system", "content": explain_system_prompt},
            {"role": "user", "content": explain_user_prompt},
        ]

        return self._llm_service.call(
            settings=settings,
            messages=explain_messages,
            task="mindmap_explain",
            label=f"MindMap Explain: {node_path}",
            topic=node_path,
        )
