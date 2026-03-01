from __future__ import annotations

from typing import Any

import streamlit as st

from main_app.contracts import FlashcardItem, FlashcardsPayload
from main_app.models import GroqSettings
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.flashcards_service import FlashcardsService
from main_app.ui.components import FlashcardsRenderConfig, render_flashcards_view

FLASHCARDS_CSS = """
<style>
    .flashdeck-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin: 6px 0 10px 0;
    }
    .flashdeck-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #171923;
        line-height: 1.15;
        margin: 0;
    }
    .flashdeck-subtitle {
        margin-top: 4px;
        color: #4b5563;
        font-size: 1.05rem;
        font-weight: 500;
    }
    .flashdeck-topic-badge {
        border: 1px solid #cdd7ea;
        background: #eef3ff;
        color: #1f3a8a;
        border-radius: 999px;
        padding: 6px 12px;
        font-size: 0.82rem;
        font-weight: 600;
    }
    .flashdeck-stage {
        position: relative;
        margin: 8px auto 0 auto;
        width: min(100%, 760px);
        min-height: 880px;
        border-radius: 28px;
        border: 1px solid #d9e3ef;
        background: linear-gradient(100deg, #edf1f7 0%, #eef6ea 100%);
        padding: 18px;
    }
    .flashdeck-card-shadow-1 {
        position: absolute;
        left: 50%;
        bottom: 44px;
        transform: translateX(-50%);
        width: min(78%, 410px);
        aspect-ratio: 9 / 16;
        border-radius: 38px;
        border: 1px solid #d2d9e8;
        background: #edf1f8;
        z-index: 1;
    }
    .flashdeck-card-shadow-2 {
        position: absolute;
        left: 50%;
        bottom: 28px;
        transform: translateX(-50%);
        width: min(74%, 392px);
        aspect-ratio: 9 / 16;
        border-radius: 36px;
        border: 1px solid #d2d9e8;
        background: #e9eef6;
        z-index: 2;
    }
    .flashdeck-card-main {
        position: relative;
        z-index: 3;
        width: min(82%, 430px);
        aspect-ratio: 9 / 16;
        margin: 16px auto 0 auto;
        border-radius: 42px;
        border: 1px solid #cfd7e7;
        box-shadow: 0 4px 14px rgba(18, 25, 38, 0.06);
        padding: 40px 32px 88px 32px;
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
    }
    .flashdeck-card-main.question {
        background: #2a2c31;
        color: #f7f8fb;
        border-color: #3d4048;
    }
    .flashdeck-card-main.answer {
        background: #ffffff;
        color: #171923;
    }
    .flashdeck-card-text {
        white-space: pre-wrap;
        overflow-wrap: break-word;
        font-size: clamp(1.8rem, 2.8vw, 3.8rem);
        line-height: 1.24;
        font-weight: 650;
        letter-spacing: -0.01em;
        max-height: 620px;
        overflow-y: auto;
        padding-right: 6px;
    }
    .flashdeck-hint {
        position: absolute;
        left: 0;
        right: 0;
        bottom: 24px;
        text-align: center;
        font-size: 1.03rem;
        font-weight: 550;
        opacity: 0.75;
    }
    .flashdeck-progress-wrap {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-top: 12px;
        margin-bottom: 2px;
    }
    .flashdeck-progress-track {
        flex: 1;
        height: 8px;
        border-radius: 999px;
        background: #e5e7eb;
        overflow: hidden;
    }
    .flashdeck-progress-fill {
        height: 8px;
        border-radius: 999px;
        background: linear-gradient(90deg, #3564ff 0%, #4b7dff 100%);
    }
    .flashdeck-count {
        color: #374151;
        font-weight: 700;
        font-size: 1rem;
        min-width: 105px;
        text-align: right;
    }
    .st-key-flash_nav_prev button,
    .st-key-flash_nav_next button {
        border-radius: 999px !important;
        width: 88px !important;
        height: 88px !important;
        border: 2px solid #3d5afe !important;
        color: #3d5afe !important;
        background: rgba(255, 255, 255, 0.78) !important;
        font-size: 2rem !important;
        font-weight: 700 !important;
        padding: 0 !important;
        min-height: 88px !important;
    }
    .st-key-flash_restart button {
        border-radius: 999px !important;
        width: 56px !important;
        height: 56px !important;
        min-height: 56px !important;
        border: 1px solid #cdd6e8 !important;
        background: #f8fafc !important;
        font-size: 1.25rem !important;
        font-weight: 600 !important;
    }
    .st-key-flash_shuffle button {
        border-radius: 999px !important;
        min-height: 48px !important;
        font-weight: 600 !important;
        border: 1px solid #c8d2e6 !important;
        background: #f8fafc !important;
        color: #111827 !important;
    }
    [class*="st-key-flash_card_action_"] {
        margin-top: -74px !important;
        position: relative;
        z-index: 25;
    }
    [class*="st-key-flash_card_action_"] button {
        border-radius: 999px !important;
        min-height: 48px !important;
        font-weight: 600 !important;
        border: 1px solid #c8d2e6 !important;
        background: #f8fafc !important;
        color: #111827 !important;
    }
    [class*="st-key-flash_card_action_q_"] button {
        background: #2f54ff !important;
        border: 1px solid #2f54ff !important;
        color: #ffffff !important;
    }
    [class*="st-key-flash_card_action_a_"] button {
        background: #f8fafc !important;
        border: 1px solid #c8d2e6 !important;
        color: #111827 !important;
    }
    @media (max-width: 900px) {
        .flashdeck-stage {
            min-height: 760px;
            width: 100%;
        }
        .flashdeck-card-main {
            width: min(90%, 360px);
            padding: 30px 24px 82px 24px;
            border-radius: 34px;
        }
        .flashdeck-card-shadow-1 {
            width: min(84%, 340px);
        }
        .flashdeck-card-shadow-2 {
            width: min(80%, 326px);
        }
        .flashdeck-card-text {
            font-size: clamp(1.5rem, 5.2vw, 2.6rem);
            max-height: 520px;
        }
    }
</style>
"""


def _flashcard_items(payload: FlashcardsPayload) -> list[FlashcardItem]:
    raw_cards = payload.get("cards", [])
    if not isinstance(raw_cards, list):
        return []
    cards: list[FlashcardItem] = []
    for item in raw_cards:
        if isinstance(item, dict):
            cards.append(item)
    return cards


def render_flashcards_tab(
    *,
    flashcards_service: FlashcardsService,
    llm_service: CachedLLMService,
    settings: GroqSettings,
    cache_count_placeholder: Any,
) -> None:
    st.markdown(FLASHCARDS_CSS, unsafe_allow_html=True)

    input_col, settings_col = st.columns([0.7, 0.3], gap="large")
    with input_col:
        st.subheader("Flashcards Topic")
        flashcards_topic_input = st.text_input(
            "Topic for Flashcards",
            placeholder="e.g. Binary Search",
            key="flashcards_topic_input",
        )
        flashcards_constraints = st.text_area(
            "Optional Flashcard Constraints",
            placeholder="e.g. Focus on interview-style questions with practical edge cases.",
            height=90,
            key="flashcards_constraints",
        )

    with settings_col:
        st.markdown("#### Deck Settings")
        flashcards_count = st.number_input(
            "Number of Cards",
            min_value=1,
            max_value=100,
            value=20,
            step=1,
            help="Maximum allowed is 100 cards per topic.",
            key="flashcards_count_input",
        )
        generate_flashcards = st.button(
            "Generate Flashcards",
            type="primary",
            key="generate_flashcards",
            width="stretch",
        )

    if generate_flashcards:
        if not settings.has_api_key():
            st.error("Please enter your Groq API key in the sidebar.")
            st.stop()
        if not settings.has_model():
            st.error("Please select or enter a valid model.")
            st.stop()
        if not flashcards_topic_input or not flashcards_topic_input.strip():
            st.error("Please enter a topic for flashcards.")
            st.stop()

        try:
            with st.spinner("Generating flashcards from Groq..."):
                generation_result = flashcards_service.generate(
                    topic=flashcards_topic_input,
                    card_count=int(flashcards_count),
                    constraints=flashcards_constraints,
                    settings=settings,
                )

            if generation_result.cache_hit:
                st.info("Flashcards served from cache. No API call made.")
            else:
                cache_count_placeholder.caption(f"Cached responses: {llm_service.count}")

            cache_count_placeholder.caption(f"Cached responses: {llm_service.count}")

            if generation_result.parse_note:
                st.info(generation_result.parse_note)

            if generation_result.parse_error:
                st.error(generation_result.parse_error)
                st.caption("Raw model response:")
                st.code(generation_result.raw_text)
            else:
                if not generation_result.parsed_flashcards:
                    st.error("Parsed flashcards payload was empty.")
                    st.stop()
                assert generation_result.parsed_flashcards is not None
                cards = _flashcard_items(generation_result.parsed_flashcards)
                if not cards:
                    st.error("Parsed flashcards payload did not contain valid cards.")
                    st.stop()
                st.session_state.flashcards_topic = flashcards_topic_input.strip()
                st.session_state.flashcards_cards = [dict(card) for card in cards]
                st.session_state.flashcards_index = 0
                st.session_state.flashcards_show_answer = False
                st.session_state.flashcards_explanations = {}
                st.session_state.flashcards_last_explained_index = -1
                st.success(f"Generated {len(st.session_state.flashcards_cards)} flashcards.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Request failed: {exc}")

    if not st.session_state.flashcards_cards:
        return

    cards = st.session_state.flashcards_cards

    def _explain(topic_name: str, question: str, short_answer: str, card_index: int) -> tuple[str, bool]:
        return flashcards_service.explain_card(
            topic=topic_name,
            question=question,
            short_answer=short_answer,
            card_index=card_index,
            settings=settings,
        )

    render_flashcards_view(
        topic=str(st.session_state.flashcards_topic),
        cards=cards,
        settings=settings,
        config=FlashcardsRenderConfig(
            state_index_key="flashcards_index",
            state_show_answer_key="flashcards_show_answer",
            state_explanations_key="flashcards_explanations",
            prev_button_key="flash_nav_prev",
            next_button_key="flash_nav_next",
            see_answer_button_key_format="flash_card_action_q_{index}",
            explain_button_key_format="flash_card_action_a_{index}",
            restart_button_key="flash_restart",
            shuffle_button_key="flash_shuffle",
            download_csv_key="flashcards_download_csv",
        ),
        explain_fn=_explain,
        llm_service=llm_service,
        cache_count_placeholder=cache_count_placeholder,
    )
