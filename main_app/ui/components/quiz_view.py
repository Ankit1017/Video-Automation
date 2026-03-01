from __future__ import annotations

from dataclasses import dataclass
from html import escape
import re
from typing import Any, Callable

import streamlit as st

from main_app.models import GroqSettings
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.quiz_exporter import QuizExporter


QuizHintFn = Callable[[str, str, list[str]], tuple[str, bool]]
QuizFeedbackFn = Callable[[str, str, list[str], int, int], tuple[dict[str, Any], bool]]
QuizExplainFn = Callable[[str, str, list[str], int, int], tuple[str, bool]]


@dataclass(frozen=True)
class QuizRenderConfig:
    state_key: str
    choice_key_format: str
    hint_button_key_format: str
    submit_button_key_format: str
    explain_button_key_format: str
    prev_button_key_format: str
    next_button_key_format: str
    template_select_key: str
    download_pdf_key: str
    download_pdf_disabled_key: str


@dataclass(frozen=True)
class _TemplateSelection:
    options: list[dict[str, str]]
    keys: list[str]
    by_key: dict[str, dict[str, str]]
    selected_key: str


def _normalize_questions(questions_raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_questions: list[dict[str, Any]] = []
    for item in questions_raw:
        if not isinstance(item, dict):
            continue
        question_text = str(item.get("question", "")).strip()
        options = [str(opt).strip() for opt in item.get("options", []) if str(opt).strip()]
        if not question_text or len(options) < 2:
            continue
        raw_correct = item.get("correct_index", item.get("correct_option_index", 0))
        if isinstance(raw_correct, bool):
            correct_index = 0
        else:
            try:
                correct_index = int(raw_correct) if isinstance(raw_correct, (int, float, str)) else int(str(raw_correct))
            except (TypeError, ValueError):
                correct_index = 0
        correct_index = max(0, min(correct_index, len(options) - 1))
        normalized_questions.append(
            {
                "question": question_text,
                "options": options,
                "correct_index": correct_index,
            }
        )
    return normalized_questions


def _ensure_state(config: QuizRenderConfig, total: int) -> dict[str, Any]:
    if config.state_key not in st.session_state or not isinstance(st.session_state[config.state_key], dict):
        st.session_state[config.state_key] = {
            "index": 0,
            "selected_answers": {},
            "submitted": {},
            "hints": {},
            "feedback": {},
            "explanations": {},
        }

    state = st.session_state[config.state_key]
    state.setdefault("index", 0)
    state.setdefault("selected_answers", {})
    state.setdefault("submitted", {})
    state.setdefault("hints", {})
    state.setdefault("feedback", {})
    state.setdefault("explanations", {})

    q_idx = int(state["index"])
    if q_idx < 0 or q_idx >= total:
        state["index"] = 0
    return state


def _render_top_stats(*, q_idx: int, total: int, submitted_map: dict[int, bool], feedback_map: dict[int, dict[str, Any]]) -> None:
    attempted_count = sum(1 for value in submitted_map.values() if value)
    score = sum(1 for idx, fb in feedback_map.items() if submitted_map.get(idx) and fb.get("is_correct"))
    stats_markup = (
        '<div class="quiz-stats-wrap">'
        '<div class="quiz-stat">'
        '<p class="quiz-stat-label">Progress</p>'
        f'<p class="quiz-stat-value">{q_idx + 1} / {total}</p>'
        "</div>"
        '<div class="quiz-stat">'
        '<p class="quiz-stat-label">Attempted</p>'
        f'<p class="quiz-stat-value">{attempted_count}</p>'
        "</div>"
        '<div class="quiz-stat">'
        '<p class="quiz-stat-label">Score</p>'
        f'<p class="quiz-stat-value">{score}</p>'
        "</div>"
        "</div>"
    )
    st.markdown(stats_markup, unsafe_allow_html=True)


def _resolve_templates(config: QuizRenderConfig, quiz_exporter: QuizExporter) -> _TemplateSelection:
    template_options = quiz_exporter.list_templates()
    if not template_options:
        template_options = [
            {
                "key": "default",
                "title": "Default",
                "description": "Default quiz paper template.",
            }
        ]

    template_keys = [
        str(item.get("key", "")).strip()
        for item in template_options
        if str(item.get("key", "")).strip()
    ]
    if not template_keys:
        template_keys = ["default"]
        template_options = [
            {
                "key": "default",
                "title": "Default",
                "description": "Default quiz paper template.",
            }
        ]

    template_by_key = {str(item.get("key", "")).strip(): item for item in template_options}
    current = st.session_state.get(config.template_select_key)
    if current not in template_keys and config.template_select_key in st.session_state:
        del st.session_state[config.template_select_key]
    selected_key = str(st.session_state.get(config.template_select_key, template_keys[0]))
    return _TemplateSelection(
        options=template_options,
        keys=template_keys,
        by_key=template_by_key,
        selected_key=selected_key if selected_key in template_keys else template_keys[0],
    )


def _render_export_controls(
    *,
    topic: str,
    questions: list[dict[str, Any]],
    config: QuizRenderConfig,
    quiz_exporter: QuizExporter,
    templates: _TemplateSelection,
) -> None:
    export_col_1, export_col_2 = st.columns([0.72, 0.28], gap="small")
    selected_template_index = templates.keys.index(templates.selected_key)

    with export_col_1:
        selected_template = st.selectbox(
            "Question Paper Template",
            options=templates.keys,
            index=selected_template_index,
            format_func=lambda value: str(templates.by_key.get(value, {}).get("title", value)),
            key=config.template_select_key,
        )
        selected_template_description = str(templates.by_key.get(selected_template, {}).get("description", "")).strip()
        if selected_template_description:
            st.caption(selected_template_description)

    with export_col_2:
        safe_topic = re.sub(r"[^a-zA-Z0-9_-]+", "_", topic.strip())[:60].strip("_") or "quiz"
        pdf_bytes, pdf_error = quiz_exporter.build_question_paper_pdf(
            topic=topic,
            questions=questions,
            template_key=str(st.session_state.get(config.template_select_key, templates.selected_key)),
        )
        if pdf_bytes is not None:
            st.download_button(
                "Download Quiz Paper (PDF)",
                data=pdf_bytes,
                file_name=f"{safe_topic}_question_paper.pdf",
                mime="application/pdf",
                key=config.download_pdf_key,
                width="stretch",
            )
            st.caption("Includes final separate answer-key page.")
        else:
            st.button(
                "Download Quiz Paper (PDF)",
                disabled=True,
                key=config.download_pdf_disabled_key,
                width="stretch",
            )
            if pdf_error:
                st.caption(pdf_error)


def _render_question_prompt(question_text: str) -> None:
    st.markdown(
        (
            '<div class="quiz-question-card">'
            f'<p class="quiz-question-text">{escape(question_text)}</p>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_pre_submit_options(
    *,
    q_idx: int,
    options: list[str],
    selected_answers: dict[int, int],
    config: QuizRenderConfig,
) -> None:
    default_index = int(selected_answers.get(q_idx, 0))
    if default_index < 0 or default_index >= len(options):
        default_index = 0
    choice = st.radio(
        "Choose one option",
        options=list(range(len(options))),
        index=default_index,
        format_func=lambda opt_idx: f"{chr(65 + opt_idx)}. {options[opt_idx]}",
        key=config.choice_key_format.format(index=q_idx),
    )
    selected_answers[q_idx] = int(choice)


def _render_submitted_options(
    *,
    options: list[str],
    correct_index: int,
    selected_index: int,
    feedback: dict[str, Any],
) -> None:
    is_correct = bool(feedback.get("is_correct", False))
    for opt_idx, opt_text in enumerate(options):
        css_class = "quiz-option-card"
        note = ""
        if opt_idx == correct_index:
            css_class += " correct"
            note = str(feedback.get("correct_one_liner", "")).strip()
        elif opt_idx == selected_index and not is_correct:
            css_class += " wrong"
            note = str(feedback.get("wrong_one_liner", "")).strip()

        note_html = f'<p class="quiz-option-note">{escape(note)}</p>' if note else ""
        st.markdown(
            (
                f'<div class="{css_class}">'
                f'<p class="quiz-option-top">{escape(chr(65 + opt_idx) + ". " + opt_text)}</p>'
                f"{note_html}"
                "</div>"
            ),
            unsafe_allow_html=True,
        )


def _handle_quiz_actions(
    *,
    topic: str,
    question_text: str,
    q_idx: int,
    options: list[str],
    correct_index: int,
    is_submitted: bool,
    selected_answers: dict[int, int],
    submitted_map: dict[int, bool],
    feedback_map: dict[int, dict[str, Any]],
    hint_map: dict[int, str],
    explanation_map: dict[int, str],
    config: QuizRenderConfig,
    hint_fn: QuizHintFn,
    feedback_fn: QuizFeedbackFn,
    explain_fn: QuizExplainFn,
    llm_service: CachedLLMService,
    cache_count_placeholder: Any,
) -> None:
    hint_col, submit_col, explain_col = st.columns([0.24, 0.24, 0.52])
    if not is_submitted:
        if hint_col.button("Hint", key=config.hint_button_key_format.format(index=q_idx), width="stretch"):
            try:
                hint_text, cache_hit = hint_fn(topic, question_text, options)
                hint_map[q_idx] = hint_text
                if cache_hit:
                    st.info("Hint served from cache.")
                else:
                    cache_count_placeholder.caption(f"Cached responses: {llm_service.count}")
                st.rerun()
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
                st.error(f"Hint request failed: {exc}")

        if submit_col.button("Submit Answer", key=config.submit_button_key_format.format(index=q_idx), width="stretch"):
            selected_index = int(selected_answers.get(q_idx, 0))
            try:
                feedback_payload, cache_hit = feedback_fn(
                    topic,
                    question_text,
                    options,
                    correct_index,
                    selected_index,
                )
                feedback_payload["is_correct"] = selected_index == correct_index
                feedback_map[q_idx] = feedback_payload
                submitted_map[q_idx] = True
                if cache_hit:
                    st.info("Attempt feedback served from cache.")
                else:
                    cache_count_placeholder.caption(f"Cached responses: {llm_service.count}")
                st.rerun()
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
                st.error(f"Answer evaluation failed: {exc}")
    else:
        if explain_col.button("Explain This Answer", key=config.explain_button_key_format.format(index=q_idx), width="stretch"):
            selected_index = int(selected_answers.get(q_idx, 0))
            try:
                explanation_text, cache_hit = explain_fn(
                    topic,
                    question_text,
                    options,
                    correct_index,
                    selected_index,
                )
                explanation_map[q_idx] = explanation_text
                if cache_hit:
                    st.info("Explanation served from cache.")
                else:
                    cache_count_placeholder.caption(f"Cached responses: {llm_service.count}")
                st.rerun()
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
                st.error(f"Explanation request failed: {exc}")


def _render_hint_and_feedback(
    *,
    q_idx: int,
    correct_index: int,
    is_submitted: bool,
    hint_map: dict[int, str],
    feedback_map: dict[int, dict[str, Any]],
    explanation_map: dict[int, str],
) -> None:
    if q_idx in hint_map and not is_submitted:
        st.markdown(
            f'<div class="quiz-hint-box"><strong>Hint:</strong> {escape(hint_map[q_idx])}</div>',
            unsafe_allow_html=True,
        )

    if not is_submitted:
        return

    feedback = feedback_map.get(q_idx, {})
    if feedback.get("is_correct"):
        st.success(f"Right answer: {chr(65 + correct_index)}")
        if feedback.get("correct_one_liner"):
            st.info(str(feedback["correct_one_liner"]))
    else:
        st.error(f"Not quite. Correct answer is {chr(65 + correct_index)}.")
        if feedback.get("wrong_one_liner"):
            st.warning(str(feedback["wrong_one_liner"]))
        if feedback.get("correct_one_liner"):
            st.info(f"Why correct option works: {feedback['correct_one_liner']}")

    if q_idx in explanation_map:
        st.markdown("---")
        st.subheader("Detailed Explanation")
        st.markdown(str(explanation_map[q_idx]))


def _render_navigation(*, q_idx: int, total: int, state: dict[str, Any], config: QuizRenderConfig) -> None:
    nav_col_1, _, nav_col_3 = st.columns([0.2, 0.6, 0.2])
    with nav_col_1:
        if st.button(
            "Previous",
            width="stretch",
            disabled=q_idx == 0,
            key=config.prev_button_key_format.format(index=q_idx),
        ):
            state["index"] = max(0, q_idx - 1)
            st.rerun()
    with nav_col_3:
        if st.button(
            "Next",
            width="stretch",
            disabled=q_idx >= total - 1,
            key=config.next_button_key_format.format(index=q_idx),
        ):
            state["index"] = min(total - 1, q_idx + 1)
            st.rerun()


def render_quiz_view(
    *,
    topic: str,
    questions_raw: list[dict[str, Any]],
    settings: GroqSettings,
    config: QuizRenderConfig,
    hint_fn: QuizHintFn,
    feedback_fn: QuizFeedbackFn,
    explain_fn: QuizExplainFn,
    quiz_exporter: QuizExporter,
    llm_service: CachedLLMService,
    cache_count_placeholder: Any,
) -> None:
    del settings
    questions = _normalize_questions(questions_raw)
    if not questions:
        st.warning("No quiz questions available.")
        return

    total = len(questions)
    state = _ensure_state(config, total)
    q_idx = int(state["index"])
    question = questions[q_idx]
    options = question["options"]
    correct_index = int(question["correct_index"])

    submitted_map: dict[int, bool] = state["submitted"]
    selected_answers: dict[int, int] = state["selected_answers"]
    feedback_map: dict[int, dict[str, Any]] = state["feedback"]
    hint_map: dict[int, str] = state["hints"]
    explanation_map: dict[int, str] = state["explanations"]

    _render_top_stats(q_idx=q_idx, total=total, submitted_map=submitted_map, feedback_map=feedback_map)
    templates = _resolve_templates(config, quiz_exporter)
    _render_export_controls(
        topic=topic,
        questions=questions,
        config=config,
        quiz_exporter=quiz_exporter,
        templates=templates,
    )
    _render_question_prompt(question["question"])

    is_submitted = bool(submitted_map.get(q_idx, False))
    if not is_submitted:
        _render_pre_submit_options(
            q_idx=q_idx,
            options=options,
            selected_answers=selected_answers,
            config=config,
        )
    else:
        selected_index = int(selected_answers.get(q_idx, 0))
        _render_submitted_options(
            options=options,
            correct_index=correct_index,
            selected_index=selected_index,
            feedback=feedback_map.get(q_idx, {}),
        )

    _handle_quiz_actions(
        topic=topic,
        question_text=question["question"],
        q_idx=q_idx,
        options=options,
        correct_index=correct_index,
        is_submitted=is_submitted,
        selected_answers=selected_answers,
        submitted_map=submitted_map,
        feedback_map=feedback_map,
        hint_map=hint_map,
        explanation_map=explanation_map,
        config=config,
        hint_fn=hint_fn,
        feedback_fn=feedback_fn,
        explain_fn=explain_fn,
        llm_service=llm_service,
        cache_count_placeholder=cache_count_placeholder,
    )
    _render_hint_and_feedback(
        q_idx=q_idx,
        correct_index=correct_index,
        is_submitted=is_submitted,
        hint_map=hint_map,
        feedback_map=feedback_map,
        explanation_map=explanation_map,
    )
    _render_navigation(q_idx=q_idx, total=total, state=state, config=config)
