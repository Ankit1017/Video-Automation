from __future__ import annotations

from typing import Any

import streamlit as st

from main_app.models import GroqSettings, WebSourcingSettings
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.global_grounding_service import GlobalGroundingService
from main_app.services.source_grounding_service import SourceGroundingService
from main_app.domains.topic.services.topic_explainer_service import TopicExplainerService
from main_app.ui.components import render_source_grounding_controls


def render_explainer_tab(
    *,
    explainer_service: TopicExplainerService,
    llm_service: CachedLLMService,
    settings: GroqSettings,
    web_sourcing_settings: WebSourcingSettings,
    cache_count_placeholder: Any,
    source_grounding_service: SourceGroundingService,
    global_grounding_service: GlobalGroundingService,
) -> None:
    st.subheader("Topic Input")
    topic = st.text_input("Topic", placeholder="e.g. Quantum computing for beginners", key="explainer_topic")
    additional_instructions = st.text_area(
        "Optional Instructions",
        placeholder="e.g. Include real-world examples and key challenges.",
        height=120,
        key="explainer_extra",
    )
    grounding = render_source_grounding_controls(
        key_prefix="explainer",
        source_grounding_service=source_grounding_service,
        global_grounding_service=global_grounding_service,
        web_settings=web_sourcing_settings,
        topic=topic,
        constraints=additional_instructions,
    )

    generate = st.button("Generate Detailed Description", type="primary", key="generate_explainer")
    if not generate:
        return

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
        with st.spinner("Generating response from Groq..."):
            response_text, cache_hit = explainer_service.generate(
                topic=topic,
                additional_instructions=additional_instructions,
                grounding_context=grounding.grounding_context,
                source_manifest=grounding.source_manifest,
                require_citations=grounding.require_citations,
                grounding_metadata=grounding.diagnostics,
                settings=settings,
            )

        if cache_hit:
            st.info("Served from cache. No API call made.")
        else:
            cache_count_placeholder.caption(f"Cached responses: {llm_service.count}")

        st.success("Generated successfully.")
        if grounding.enabled and grounding.require_citations:
            st.caption("Source-grounded mode enabled. Verify citation markers like [S1], [S2] in the response.")
        st.subheader("Detailed Description")
        st.markdown(response_text)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Request failed: {exc}")
