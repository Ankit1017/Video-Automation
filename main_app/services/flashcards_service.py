from __future__ import annotations

import re
from typing import cast

from main_app.contracts import FlashcardsPayload
from main_app.models import FlashcardsGenerationResult, GroqSettings
from main_app.parsers.flashcards_parser import FlashcardsParser
from main_app.services.asset_history_service import AssetHistoryService
from main_app.services.cached_llm_service import CachedLLMService


class FlashcardsService:
    def __init__(
        self,
        llm_service: CachedLLMService,
        parser: FlashcardsParser,
        history_service: AssetHistoryService | None = None,
    ) -> None:
        self._llm_service = llm_service
        self._parser = parser
        self._history_service = history_service

    def generate(
        self,
        *,
        topic: str,
        card_count: int,
        constraints: str,
        settings: GroqSettings,
    ) -> FlashcardsGenerationResult:
        requested_cards = max(1, min(int(card_count), 100))

        flashcards_system_prompt = (
            "You are a flashcard generator. "
            "Return valid JSON only, with no markdown and no explanations."
        )
        flashcards_user_prompt = (
            f"Create {requested_cards} high-quality flashcards for topic: {topic.strip()}\n\n"
            "Output JSON with this schema:\n"
            "{\n"
            '  "topic": "topic name",\n'
            '  "cards": [\n'
            '    {"question": "clear intuitive question", "short_answer": "1-3 sentence answer"}\n'
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- Keep each question clear, practical, and non-repetitive.\n"
            "- Keep each short_answer concise and factual.\n"
            "- Cover beginner to advanced aspects progressively.\n"
            "- Return JSON only."
        )
        if constraints.strip():
            flashcards_user_prompt += f"\n\nAdditional constraints:\n{constraints.strip()}"

        flashcards_messages = [
            {"role": "system", "content": flashcards_system_prompt},
            {"role": "user", "content": flashcards_user_prompt},
        ]

        raw_text, cache_hit = self._llm_service.call(
            settings=settings,
            messages=flashcards_messages,
            task="flashcards_generate",
            label=f"Flashcards: {topic.strip()}",
            topic=topic.strip(),
        )

        parsed_flashcards, parse_error, parse_note = self._parser.parse(
            raw_text,
            max_cards=requested_cards,
            settings=settings,
        )

        result = FlashcardsGenerationResult(
            raw_text=raw_text,
            parsed_flashcards=cast(FlashcardsPayload | None, parsed_flashcards),
            parse_error=parse_error,
            parse_note=parse_note,
            cache_hit=cache_hit,
        )
        if self._history_service is not None:
            self._history_service.record_generation(
                asset_type="flashcards",
                topic=topic.strip(),
                title=f"Flashcards: {topic.strip()}",
                model=settings.normalized_model,
                request_payload={
                    "topic": topic.strip(),
                    "card_count": requested_cards,
                    "constraints": constraints.strip(),
                },
                result_payload=parsed_flashcards if parsed_flashcards is not None else {},
                status="error" if parse_error else "success",
                cache_hit=cache_hit,
                parse_note=parse_note or "",
                error=parse_error or "",
                raw_text=raw_text if parse_error else "",
            )
        return result

    def explain_card(
        self,
        *,
        topic: str,
        question: str,
        short_answer: str,
        card_index: int,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        explain_system_prompt = "You are an expert educator. Provide a clear and structured explanation."
        safe_question = self.sanitize_card_text(question)
        safe_short_answer = self.sanitize_card_text(short_answer)
        explain_user_prompt = (
            f"Topic: {topic}\n"
            f"Question: {safe_question}\n"
            f"Short answer: {safe_short_answer}\n\n"
            "Provide a proper explanatory answer with:\n"
            "- concept intuition\n"
            "- why this is correct\n"
            "- one practical example\n"
            "- one common mistake"
        )
        explain_messages = [
            {"role": "system", "content": explain_system_prompt},
            {"role": "user", "content": explain_user_prompt},
        ]

        return self._llm_service.call(
            settings=settings,
            messages=explain_messages,
            task="flashcards_explain",
            label=f"Flashcard Explain: {topic} #{card_index + 1}",
            topic=f"{topic} | {safe_question}",
        )

    @staticmethod
    def sanitize_card_text(value: str) -> str:
        clean = re.sub(r"<[^>]+>", "", str(value))
        return " ".join(clean.split())
