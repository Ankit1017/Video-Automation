from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from main_app.contracts import QuizHistoryEntry, QuizPayload
from main_app.infrastructure.quiz_history_store import QuizHistoryRepository
from main_app.models import GroqSettings, QuizGenerationResult
from main_app.parsers.json_utils import extract_json_text, repair_json_text_locally
from main_app.parsers.quiz_parser import QuizParser
from main_app.services.asset_history_service import AssetHistoryService
from main_app.services.cached_llm_service import CachedLLMService


logger = logging.getLogger(__name__)


class QuizService:
    def __init__(
        self,
        llm_service: CachedLLMService,
        parser: QuizParser,
        history_store: QuizHistoryRepository,
        asset_history_service: AssetHistoryService | None = None,
    ) -> None:
        self._llm_service = llm_service
        self._parser = parser
        self._history_store = history_store
        self._asset_history_service = asset_history_service

    def generate_quiz(
        self,
        *,
        topic: str,
        question_count: int,
        difficulty: str,
        constraints: str,
        grounding_context: str = "",
        source_manifest: list[dict[str, Any]] | None = None,
        require_citations: bool = False,
        grounding_metadata: dict[str, Any] | None = None,
        settings: GroqSettings,
    ) -> QuizGenerationResult:
        requested_questions = max(3, min(int(question_count), 25))

        system_prompt = (
            "You are an assessment designer. "
            "Create high-quality multiple-choice quiz questions and return strict JSON only."
        )
        user_prompt = (
            f"Create a comprehensive MCQ quiz for topic: {topic.strip()}\n"
            f"Difficulty: {difficulty}\n\n"
            "Output JSON schema:\n"
            "{\n"
            '  "topic": "topic name",\n'
            '  "questions": [\n'
            '    {"question": "...", "options": ["...", "...", "...", "..."], "correct_option_index": 0}\n'
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            f"- Generate exactly {requested_questions} questions when possible.\n"
            "- Each question must have 4 options.\n"
            "- Exactly one correct option.\n"
            "- Questions must be practical and concept-focused, not trivial recall only.\n"
            "- Distractors should be plausible but clearly wrong upon understanding.\n"
            "- Avoid options like 'all of the above' or 'none of the above'.\n"
            "- If grounding sources are provided, include citation markers like [S1] in question stems where relevant.\n"
            "- Return JSON only (no markdown)."
        )
        if grounding_context.strip():
            user_prompt += (
                "\n\nGrounding sources:\n"
                f"{grounding_context.strip()}\n\n"
                "Use these sources for factual grounding while writing questions."
            )
            if require_citations:
                user_prompt += (
                    "\nCitation requirement:\n"
                    "- Each generated question should include at least one valid citation marker like [S1].\n"
                    "- Do not use source IDs that are not present in provided source blocks."
                )

        if constraints.strip():
            user_prompt += f"\n\nAdditional constraints:\n{constraints.strip()}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Quiz generation is intentionally uncached.
        raw_text, _ = self._llm_service.call(
            settings=settings,
            messages=messages,
            task="quiz_generate",
            label=f"Quiz: {topic.strip()}",
            topic=topic.strip(),
            use_cache=False,
        )

        parsed_quiz, parse_error, parse_note = self._parser.parse(
            raw_text,
            settings=settings,
            min_questions=min(3, requested_questions),
            max_questions=requested_questions,
            repair_use_cache=False,
        )

        persistence_note: str | None = None
        if parsed_quiz and not parse_error:
            try:
                self.save_generated_quiz(
                    topic=topic,
                    difficulty=difficulty,
                    constraints=constraints,
                    model=settings.normalized_model,
                    quiz_payload=parsed_quiz,
                )
            except (OSError, PermissionError, ValueError, RuntimeError, TypeError) as exc:
                # History persistence should not block quiz generation.
                logger.exception("Quiz history persistence failed.")
                persistence_note = f"Quiz generated but could not persist history: {exc}"

        if persistence_note:
            parse_note = f"{parse_note} {persistence_note}".strip() if parse_note else persistence_note

        result = QuizGenerationResult(
            raw_text=raw_text,
            parsed_quiz=parsed_quiz,
            parse_error=parse_error,
            parse_note=parse_note,
        )
        if self._asset_history_service is not None:
            self._asset_history_service.record_generation(
                asset_type="quiz",
                topic=topic.strip(),
                title=f"Quiz: {topic.strip()}",
                model=settings.normalized_model,
                request_payload={
                    "topic": topic.strip(),
                    "question_count": requested_questions,
                    "difficulty": difficulty.strip(),
                    "constraints": constraints.strip(),
                    "grounded_mode": bool(grounding_context.strip()),
                    "require_citations": bool(require_citations),
                    "sources": list(source_manifest or []),
                    "grounding_metadata": dict(grounding_metadata or {}),
                },
                result_payload=parsed_quiz if parsed_quiz is not None else {},
                status="error" if parse_error else "success",
                cache_hit=False,
                parse_note=parse_note or "",
                error=parse_error or "",
                raw_text=raw_text if parse_error else "",
            )
        return result

    def list_saved_quizzes(self) -> list[dict[str, Any]]:
        raw_quizzes = self._history_store.list_quizzes()
        summaries: list[dict[str, Any]] = []
        for item in raw_quizzes:
            quiz_id = str(item.get("id", "")).strip()
            payload = item.get("quiz")
            normalized_payload, _ = self._parser.normalize_payload(
                payload,
                min_questions=1,
                max_questions=100,
            )
            if not quiz_id or not normalized_payload:
                continue

            created_at = str(item.get("created_at", "")).strip()
            topic = str(item.get("topic", normalized_payload.get("topic", ""))).strip()
            difficulty = str(item.get("difficulty", "Unknown")).strip() or "Unknown"
            question_total = len(normalized_payload.get("questions", []))
            summaries.append(
                {
                    "id": quiz_id,
                    "topic": topic or "Untitled Quiz",
                    "difficulty": difficulty,
                    "question_total": question_total,
                    "created_at": created_at,
                    "model": str(item.get("model", "")).strip(),
                }
            )

        return sorted(summaries, key=lambda item: item["created_at"], reverse=True)

    def load_saved_quiz(self, quiz_id: str) -> dict[str, Any] | None:
        raw_item = self._history_store.get_quiz(quiz_id)
        if not raw_item:
            return None

        normalized_payload, _ = self._parser.normalize_payload(
            raw_item.get("quiz"),
            min_questions=1,
            max_questions=100,
        )
        if not normalized_payload:
            return None

        return {
            "id": quiz_id,
            "topic": str(raw_item.get("topic", normalized_payload.get("topic", ""))).strip(),
            "difficulty": str(raw_item.get("difficulty", "Unknown")).strip() or "Unknown",
            "created_at": str(raw_item.get("created_at", "")).strip(),
            "quiz": normalized_payload,
        }

    def get_hint(
        self,
        *,
        topic: str,
        question: str,
        options: list[str],
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        option_lines = "\n".join(f"{chr(65 + idx)}. {text}" for idx, text in enumerate(options))
        messages = [
            {
                "role": "system",
                "content": (
                    "You provide hints for quiz questions. Give one concise line. "
                    "Do not reveal the exact answer option."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Topic: {topic}\n"
                    f"Question: {question}\n"
                    f"Options:\n{option_lines}\n\n"
                    "Provide only one-line hint to help reasoning without giving away the answer."
                ),
            },
        ]

        return self._llm_service.call(
            settings=settings,
            messages=messages,
            task="quiz_hint",
            label=f"Quiz Hint: {topic}",
            topic=question,
        )

    def get_attempt_feedback(
        self,
        *,
        topic: str,
        question: str,
        options: list[str],
        correct_index: int,
        selected_index: int,
        settings: GroqSettings,
    ) -> tuple[dict[str, str], bool]:
        option_lines = "\n".join(f"{chr(65 + idx)}. {text}" for idx, text in enumerate(options))
        messages = [
            {
                "role": "system",
                "content": (
                    "You provide concise quiz feedback in strict JSON only. "
                    "No markdown, no extra text."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Topic: {topic}\n"
                    f"Question: {question}\n"
                    f"Options:\n{option_lines}\n"
                    f"Correct option letter: {chr(65 + correct_index)}\n"
                    f"Selected option letter: {chr(65 + selected_index)}\n\n"
                    "Return JSON:\n"
                    "{\n"
                    '  "correct_one_liner": "one concise sentence why the correct option is right",\n'
                    '  "wrong_one_liner": "one concise sentence why selected option is wrong (empty string if selected is correct)"\n'
                    "}"
                ),
            },
        ]

        response_text, cache_hit = self._llm_service.call(
            settings=settings,
            messages=messages,
            task="quiz_attempt_feedback",
            label=f"Quiz Feedback: {topic}",
            topic=question,
        )

        parsed = self._parse_feedback_json(response_text)
        is_correct = selected_index == correct_index

        if not parsed.get("correct_one_liner"):
            parsed["correct_one_liner"] = "The correct option best matches the core concept in the question."
        if is_correct:
            parsed["wrong_one_liner"] = ""
        elif not parsed.get("wrong_one_liner"):
            parsed["wrong_one_liner"] = "That choice misses a key detail required by the question."

        return parsed, cache_hit

    def explain_attempt(
        self,
        *,
        topic: str,
        question: str,
        options: list[str],
        correct_index: int,
        selected_index: int,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        option_lines = "\n".join(f"{chr(65 + idx)}. {text}" for idx, text in enumerate(options))
        selected_letter = chr(65 + selected_index)
        correct_letter = chr(65 + correct_index)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert tutor. Give a clear and comprehensive explanation of quiz answers."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Topic: {topic}\n"
                    f"Question: {question}\n"
                    f"Options:\n{option_lines}\n"
                    f"Selected option: {selected_letter}\n"
                    f"Correct option: {correct_letter}\n\n"
                    "Explain comprehensively:\n"
                    "- why the correct option is correct\n"
                    "- why the selected option is wrong (if wrong)\n"
                    "- short concept summary to avoid this mistake next time"
                ),
            },
        ]

        return self._llm_service.call(
            settings=settings,
            messages=messages,
            task="quiz_explain_attempt",
            label=f"Quiz Explain: {topic}",
            topic=question,
        )

    @staticmethod
    def _parse_feedback_json(raw_text: str) -> dict[str, str]:
        default_payload = {"correct_one_liner": "", "wrong_one_liner": ""}
        json_text = extract_json_text(raw_text) or raw_text
        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError:
            repaired_json = repair_json_text_locally(json_text)
            try:
                parsed = json.loads(repaired_json)
            except json.JSONDecodeError as exc:
                logger.warning("Quiz feedback JSON parse failed after local repair: %s", exc)
                return default_payload
        except TypeError as exc:
            logger.warning("Quiz feedback payload type error: %s", exc)
            return default_payload

        if not isinstance(parsed, dict):
            return default_payload

        correct = " ".join(str(parsed.get("correct_one_liner", "")).split()).strip()
        wrong = " ".join(str(parsed.get("wrong_one_liner", "")).split()).strip()
        return {"correct_one_liner": correct, "wrong_one_liner": wrong}

    def save_generated_quiz(
        self,
        *,
        topic: str,
        difficulty: str,
        constraints: str,
        model: str,
        quiz_payload: QuizPayload,
    ) -> str:
        created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        quiz_id = uuid4().hex[:16]

        record: QuizHistoryEntry = {
            "id": quiz_id,
            "topic": topic.strip(),
            "difficulty": difficulty.strip(),
            "constraints": constraints.strip(),
            "model": model.strip(),
            "created_at": created_at,
            "quiz": quiz_payload,
        }
        self._history_store.upsert_quiz(record)
        return quiz_id
