from __future__ import annotations

from typing import Any, cast

import streamlit as st

from main_app.contracts import QuizPayload, QuizQuestion
from main_app.models import GroqSettings, WebSourcingSettings
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.global_grounding_service import GlobalGroundingService
from main_app.services.quiz_exporter import QuizExporter
from main_app.services.quiz_service import QuizService
from main_app.services.source_grounding_service import SourceGroundingService
from main_app.ui.components import (
    QuizRenderConfig,
    render_quiz_view,
    render_source_grounding_controls,
)
from main_app.ui.error_handling import UI_HANDLED_EXCEPTIONS, report_ui_error

QUIZ_TAB_CSS = """
<style>
    .quiz-headline {
        font-size: 1.9rem;
        font-weight: 700;
        color: #111827;
        margin: 2px 0 2px 0;
    }
    .quiz-subhead {
        color: #4b5563;
        margin: 0 0 12px 0;
    }
    .quiz-progress {
        color: #4b5563;
        font-weight: 600;
        margin-bottom: 10px;
    }
    .quiz-question-card {
        border: 1px solid #e5e7eb;
        border-radius: 14px;
        background: #ffffff;
        padding: 16px;
        margin-bottom: 10px;
    }
    .quiz-question-text {
        margin: 0;
        font-size: 1.24rem;
        line-height: 1.45;
        color: #111827;
        font-weight: 650;
    }
    .quiz-hint-box {
        border: 1px solid #cfd8ff;
        background: #eef2ff;
        border-radius: 12px;
        padding: 12px;
        color: #1f3b8f;
        margin-top: 8px;
        margin-bottom: 8px;
    }
    .quiz-option-card {
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        background: #f9fafb;
        padding: 12px;
        margin-bottom: 8px;
    }
    .quiz-option-card.correct {
        background: #dcfce7;
        border-color: #86efac;
    }
    .quiz-option-card.wrong {
        background: #fee2e2;
        border-color: #fca5a5;
    }
    .quiz-option-top {
        margin: 0;
        color: #111827;
        font-size: 1.05rem;
        line-height: 1.38;
    }
    .quiz-option-note {
        margin: 8px 0 0 0;
        font-size: 0.95rem;
        color: #1f2937;
    }
    .quiz-stats-wrap {
        display: flex;
        gap: 10px;
        margin-bottom: 10px;
    }
    .quiz-stat {
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        background: #f9fafb;
        padding: 10px 12px;
        min-width: 120px;
    }
    .quiz-stat-label {
        color: #6b7280;
        font-size: 0.8rem;
        margin: 0;
    }
    .quiz-stat-value {
        color: #111827;
        font-size: 1.12rem;
        font-weight: 700;
        margin: 0;
    }
</style>
"""


def _quiz_questions(payload: QuizPayload) -> list[QuizQuestion]:
    raw_questions = payload.get("questions", [])
    if not isinstance(raw_questions, list):
        return []
    questions: list[QuizQuestion] = []
    for item in raw_questions:
        if isinstance(item, dict):
            questions.append(item)
    return questions


def _saved_quiz_questions(loaded: dict[str, Any]) -> list[QuizQuestion]:
    quiz_payload = loaded.get("quiz")
    if not isinstance(quiz_payload, dict):
        return []
    return _quiz_questions(cast(QuizPayload, quiz_payload))


def _saved_quiz_label(saved_quizzes: list[dict[str, Any]], quiz_id: str) -> str:
    for item in saved_quizzes:
        if item["id"] == quiz_id:
            topic = item.get("topic", "Untitled Quiz")
            difficulty = item.get("difficulty", "Unknown")
            question_total = item.get("question_total", 0)
            created_at = item.get("created_at", "")
            short_id = quiz_id[:8]
            return f"{topic} | {difficulty} | {question_total}Q | {created_at} | {short_id}"
    return quiz_id


def render_quiz_tab(
    *,
    quiz_service: QuizService,
    quiz_exporter: QuizExporter,
    llm_service: CachedLLMService,
    settings: GroqSettings,
    web_sourcing_settings: WebSourcingSettings,
    cache_count_placeholder: Any,
    source_grounding_service: SourceGroundingService,
    global_grounding_service: GlobalGroundingService,
) -> None:
    def _activate_quiz(topic_text: str, questions_payload: list[QuizQuestion]) -> None:
        st.session_state.quiz_topic = topic_text.strip()
        st.session_state.quiz_questions = [dict(question) for question in questions_payload]
        st.session_state.quiz_runtime_state = {
            "index": 0,
            "selected_answers": {},
            "submitted": {},
            "hints": {},
            "feedback": {},
            "explanations": {},
        }

    st.markdown(QUIZ_TAB_CSS, unsafe_allow_html=True)
    st.markdown('<div class="quiz-headline">Quiz</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="quiz-subhead">Generate questions, attempt answers, get hints and detailed explanations.</div>',
        unsafe_allow_html=True,
    )

    saved_quizzes = quiz_service.list_saved_quizzes()
    with st.container(border=True):
        st.markdown("#### Reattempt Saved Quiz")
        if saved_quizzes:
            saved_ids = [item["id"] for item in saved_quizzes]
            if st.session_state.quiz_selected_saved_id not in saved_ids:
                st.session_state.quiz_selected_saved_id = saved_ids[0]

            selected_saved_id = st.selectbox(
                "Select Previous Quiz",
                options=saved_ids,
                index=saved_ids.index(st.session_state.quiz_selected_saved_id),
                format_func=lambda quiz_id: _saved_quiz_label(saved_quizzes, quiz_id),
                key="quiz_saved_selectbox",
            )
            st.session_state.quiz_selected_saved_id = selected_saved_id

            load_col, info_col = st.columns([0.28, 0.72])
            if load_col.button("Load For Reattempt", key="quiz_load_saved_btn", width="stretch"):
                loaded = quiz_service.load_saved_quiz(selected_saved_id)
                if not loaded:
                    st.error("Unable to load selected quiz from history.")
                else:
                    _activate_quiz(str(loaded.get("topic", "")), _saved_quiz_questions(loaded))
                    st.session_state.quiz_topic_input = loaded["topic"]
                    st.session_state.quiz_difficulty = loaded["difficulty"] if loaded["difficulty"] in {
                        "Beginner",
                        "Intermediate",
                        "Advanced",
                    } else "Intermediate"
                    st.success("Saved quiz loaded. You can reattempt from question 1.")
                    st.rerun()
            info_col.caption(f"Saved quizzes: {len(saved_quizzes)}")
        else:
            st.caption("No saved quizzes yet. Generate a quiz once and it will be stored for future reattempts.")

    setup_col, control_col = st.columns([0.72, 0.28], gap="large")
    with setup_col:
        topic = st.text_input(
            "Quiz Topic",
            placeholder="e.g. Transitioning to Agentic AI Systems",
            key="quiz_topic_input",
        )
        constraints = st.text_area(
            "Optional Quiz Constraints",
            placeholder="e.g. Focus on architecture and production trade-offs.",
            height=90,
            key="quiz_constraints",
        )
        grounding = render_source_grounding_controls(
            key_prefix="quiz",
            source_grounding_service=source_grounding_service,
            global_grounding_service=global_grounding_service,
            web_settings=web_sourcing_settings,
            topic=topic,
            constraints=constraints,
        )

    with control_col:
        st.markdown("#### Quiz Controls")
        question_count = st.slider(
            "Questions",
            min_value=3,
            max_value=25,
            value=10,
            step=1,
            key="quiz_question_count",
        )
        difficulty = st.selectbox(
            "Difficulty",
            options=["Beginner", "Intermediate", "Advanced"],
            index=1,
            key="quiz_difficulty",
        )
        generate_quiz = st.button(
            "Generate Quiz",
            type="primary",
            key="generate_quiz",
            width="stretch",
        )

    if generate_quiz:
        if not settings.has_api_key():
            st.error("Please enter your Groq API key in the sidebar.")
            st.stop()
        if not settings.has_model():
            st.error("Please select or enter a valid model.")
            st.stop()
        if not topic or not topic.strip():
            st.error("Please enter a topic.")
            st.stop()
        if grounding.enabled and not grounding.grounding_context:
            strict_warning = next(
                (item for item in grounding.warnings if "Strict mode is enabled" in str(item)),
                "",
            )
            st.error(strict_warning or "Source-grounded mode is enabled but no valid source text was loaded.")
            st.stop()

        try:
            with st.spinner("Generating quiz..."):
                result = quiz_service.generate_quiz(
                    topic=topic,
                    question_count=question_count,
                    difficulty=difficulty,
                    constraints=constraints,
                    grounding_context=grounding.grounding_context,
                    source_manifest=grounding.source_manifest,
                    require_citations=grounding.require_citations,
                    grounding_metadata=grounding.diagnostics,
                    settings=settings,
                )

            if result.parse_note:
                st.info(result.parse_note)

            if result.parse_error:
                st.error(result.parse_error)
                st.caption("Raw model response:")
                st.code(result.raw_text)
            else:
                parsed = result.parsed_quiz
                if not parsed:
                    st.error("Parsed quiz payload was empty.")
                    st.stop()
                assert parsed is not None
                questions = _quiz_questions(parsed)
                if not questions:
                    st.error("Parsed quiz payload did not contain valid questions.")
                    st.stop()
                _activate_quiz(topic.strip(), questions)
                st.success(f"Generated {len(questions)} quiz questions.")
                st.caption("This quiz is saved to your local quiz history for future reattempts.")
                st.info("Quiz generation intentionally bypasses cache. Hint/feedback/explanations use cache.")
                if grounding.enabled and grounding.require_citations:
                    st.caption("Source-grounded mode enabled. Questions should include citation markers like [S1].")
        except UI_HANDLED_EXCEPTIONS as exc:
            report_ui_error(action="quiz_generate", exc=exc)

    if not st.session_state.quiz_questions:
        return

    def _hint(topic_name: str, question_text: str, options: list[str]) -> tuple[str, bool]:
        return quiz_service.get_hint(
            topic=topic_name,
            question=question_text,
            options=options,
            settings=settings,
        )

    def _feedback(
        topic_name: str,
        question_text: str,
        options: list[str],
        correct_index: int,
        selected_index: int,
    ) -> tuple[dict[str, str], bool]:
        return quiz_service.get_attempt_feedback(
            topic=topic_name,
            question=question_text,
            options=options,
            correct_index=correct_index,
            selected_index=selected_index,
            settings=settings,
        )

    def _explain(
        topic_name: str,
        question_text: str,
        options: list[str],
        correct_index: int,
        selected_index: int,
    ) -> tuple[str, bool]:
        return quiz_service.explain_attempt(
            topic=topic_name,
            question=question_text,
            options=options,
            correct_index=correct_index,
            selected_index=selected_index,
            settings=settings,
        )

    render_quiz_view(
        topic=str(st.session_state.quiz_topic),
        questions_raw=st.session_state.quiz_questions,
        settings=settings,
        config=QuizRenderConfig(
            state_key="quiz_runtime_state",
            choice_key_format="quiz_choice_{index}",
            hint_button_key_format="quiz_hint_btn_{index}",
            submit_button_key_format="quiz_submit_btn_{index}",
            explain_button_key_format="quiz_explain_btn_{index}",
            prev_button_key_format="quiz_prev_{index}",
            next_button_key_format="quiz_next_{index}",
            template_select_key="quiz_pdf_template",
            download_pdf_key="quiz_download_pdf",
            download_pdf_disabled_key="quiz_download_pdf_disabled",
        ),
        hint_fn=_hint,
        feedback_fn=_feedback,
        explain_fn=_explain,
        quiz_exporter=quiz_exporter,
        llm_service=llm_service,
        cache_count_placeholder=cache_count_placeholder,
    )
