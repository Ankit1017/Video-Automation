from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from main_app.contracts import CartoonPayload, VideoPayload
from main_app.models import GroqSettings
from main_app.ui.components.flashcards_view import FlashcardExplainFn
from main_app.ui.components.quiz_view import QuizExplainFn, QuizFeedbackFn, QuizHintFn
from main_app.ui.components.video_view import VideoBuildFn, VideoSynthesizeFn
from main_app.ui.components.cartoon_view import CartoonBuildFn


class _FlashcardExplainer(Protocol):
    def explain_flashcard(
        self,
        *,
        topic: str,
        question: str,
        short_answer: str,
        card_index: int,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        ...


class _QuizAssistant(Protocol):
    def get_quiz_hint(
        self,
        *,
        topic: str,
        question: str,
        options: list[str],
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        ...

    def get_quiz_attempt_feedback(
        self,
        *,
        topic: str,
        question: str,
        options: list[str],
        correct_index: int,
        selected_index: int,
        settings: GroqSettings,
    ) -> tuple[dict[str, str], bool]:
        ...

    def explain_quiz_attempt(
        self,
        *,
        topic: str,
        question: str,
        options: list[str],
        correct_index: int,
        selected_index: int,
        settings: GroqSettings,
    ) -> tuple[str, bool]:
        ...


class _VideoSynthesizer(Protocol):
    def synthesize_audio(
        self,
        *,
        video_payload: VideoPayload,
        language: str,
        slow: bool,
    ) -> tuple[bytes | None, str | None]:
        ...


class _VideoBuilder(Protocol):
    def build_video_mp4(
        self,
        *,
        topic: str,
        video_payload: VideoPayload,
        audio_bytes: bytes,
        template_key: str | None = None,
        animation_style: str | None = None,
        render_mode: str | None = None,
        allow_fallback: bool | None = None,
    ) -> tuple[bytes | None, str | None]:
        ...


class _CartoonBuilder(Protocol):
    def build_cartoon_mp4s(
        self,
        *,
        topic: str,
        cartoon_payload: CartoonPayload,
        output_mode: str | None = None,
    ) -> tuple[dict[str, bytes], str | None]:
        ...


@dataclass(frozen=True)
class QuizCallbacks:
    hint_fn: QuizHintFn
    feedback_fn: QuizFeedbackFn
    explain_fn: QuizExplainFn


def first_non_empty_topic(*candidates: object, fallback: str) -> str:
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return fallback


def build_flashcard_explain_callback(
    *,
    service: _FlashcardExplainer,
    settings: GroqSettings,
) -> FlashcardExplainFn:
    def _callback(topic: str, question: str, short_answer: str, card_index: int) -> tuple[str, bool]:
        return service.explain_flashcard(
            topic=topic,
            question=question,
            short_answer=short_answer,
            card_index=card_index,
            settings=settings,
        )

    return _callback


def build_quiz_callbacks(
    *,
    service: _QuizAssistant,
    settings: GroqSettings,
) -> QuizCallbacks:
    def _hint(topic: str, question: str, options: list[str]) -> tuple[str, bool]:
        return service.get_quiz_hint(
            topic=topic,
            question=question,
            options=options,
            settings=settings,
        )

    def _feedback(
        topic: str,
        question: str,
        options: list[str],
        correct_index: int,
        selected_index: int,
    ) -> tuple[dict[str, str], bool]:
        return service.get_quiz_attempt_feedback(
            topic=topic,
            question=question,
            options=options,
            correct_index=correct_index,
            selected_index=selected_index,
            settings=settings,
        )

    def _explain(
        topic: str,
        question: str,
        options: list[str],
        correct_index: int,
        selected_index: int,
    ) -> tuple[str, bool]:
        return service.explain_quiz_attempt(
            topic=topic,
            question=question,
            options=options,
            correct_index=correct_index,
            selected_index=selected_index,
            settings=settings,
        )

    return QuizCallbacks(
        hint_fn=_hint,
        feedback_fn=_feedback,
        explain_fn=_explain,
    )


def build_video_synthesize_callback(service: _VideoSynthesizer) -> VideoSynthesizeFn:
    def _callback(video_payload: VideoPayload, language: str, slow: bool) -> tuple[bytes | None, str | None]:
        return service.synthesize_audio(
            video_payload=video_payload,
            language=language,
            slow=slow,
        )

    return _callback


def build_video_build_callback(service: _VideoBuilder) -> VideoBuildFn:
    def _callback(topic: str, video_payload: VideoPayload, audio_bytes: bytes) -> tuple[bytes | None, str | None]:
        metadata = video_payload.get("metadata", {})
        metadata_map = metadata if isinstance(metadata, dict) else {}
        return service.build_video_mp4(
            topic=topic,
            video_payload=video_payload,
            audio_bytes=audio_bytes,
            template_key=str(video_payload.get("video_template", "standard")),
            animation_style=str(video_payload.get("animation_style", "smooth")),
            render_mode=str(video_payload.get("render_mode", "avatar_conversation")),
            allow_fallback=bool(metadata_map.get("avatar_allow_fallback", True)),
        )

    return _callback


def build_cartoon_build_callback(service: _CartoonBuilder) -> CartoonBuildFn:
    def _callback(topic: str, cartoon_payload: CartoonPayload) -> tuple[dict[str, bytes], str | None]:
        return service.build_cartoon_mp4s(
            topic=topic,
            cartoon_payload=cartoon_payload,
            output_mode=str(cartoon_payload.get("output_mode", "dual")),
        )

    return _callback
