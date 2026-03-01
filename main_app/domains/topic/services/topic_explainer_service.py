from __future__ import annotations

from typing import Any

from main_app.domains.topic.parser.topic_prompt_builder import build_topic_prompts
from main_app.models import GroqSettings
from main_app.services.asset_history_service import AssetHistoryService
from main_app.services.cached_llm_service import CachedLLMService


class TopicExplainerService:
    def __init__(
        self,
        llm_service: CachedLLMService,
        history_service: AssetHistoryService | None = None,
    ) -> None:
        self._llm_service = llm_service
        self._history_service = history_service

    def generate(
        self,
        *,
        topic: str,
        additional_instructions: str,
        grounding_context: str = "",
        source_manifest: list[dict[str, Any]] | None = None,
        require_citations: bool = False,
        grounding_metadata: dict[str, Any] | None = None,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        normalized_topic = topic.strip()
        normalized_instructions = additional_instructions.strip()
        normalized_grounding = grounding_context.strip()
        system_prompt, user_prompt = build_topic_prompts(
            topic=normalized_topic,
            additional_instructions=normalized_instructions,
            grounding_context=normalized_grounding,
            require_citations=require_citations,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response_text, cache_hit = self._llm_service.call(
            settings=settings,
            messages=messages,
            task="topic_explainer",
            label=f"Explainer: {normalized_topic}",
            topic=normalized_topic,
        )
        if self._history_service is not None:
            self._history_service.record_generation(
                asset_type="topic",
                topic=normalized_topic,
                title=f"Detailed Description: {normalized_topic}",
                model=settings.normalized_model,
                request_payload={
                    "topic": normalized_topic,
                    "additional_instructions": normalized_instructions,
                    "grounded_mode": bool(normalized_grounding),
                    "require_citations": bool(require_citations),
                    "sources": list(source_manifest or []),
                    "grounding_metadata": dict(grounding_metadata or {}),
                },
                result_payload={"content": response_text},
                status="success",
                cache_hit=cache_hit,
            )
        return response_text, cache_hit
