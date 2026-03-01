from __future__ import annotations

from html import escape
from typing import Any, cast

import streamlit as st

from main_app.contracts import IntentPayload, IntentPayloadMap, RequirementFieldSpec
from main_app.models import GroqSettings
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.intent import IntentRouterService

INTENT_CHAT_TAB_CSS = """
<style>
    .ic-heading {
        font-size: 1.9rem;
        font-weight: 760;
        color: #0f172a;
        margin: 2px 0 2px 0;
    }
    .ic-subheading {
        color: #475569;
        margin: 0 0 12px 0;
    }
    .ic-chip {
        display: inline-block;
        border: 1px solid #93c5fd;
        background: #eff6ff;
        color: #1e3a8a;
        border-radius: 999px;
        padding: 4px 10px;
        margin: 0 8px 8px 0;
        font-size: 0.88rem;
        font-weight: 650;
    }
    .ic-history-box {
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        background: #f8fafc;
        padding: 10px 12px;
        margin-bottom: 8px;
    }
    .ic-history-user {
        margin: 0 0 6px 0;
        color: #111827;
        font-weight: 700;
    }
    .ic-history-intent {
        margin: 0;
        color: #1f2937;
    }
</style>
"""

RESOLUTION_OPTIONS = [
    "go with default requirement fullfiller",
    "get the requirement fullfilled by LLM call",
    "give the these required thing by your own",
]

INTENT_DISPLAY_NAMES = {
    "topic": "topic",
    "mindmap": "mindmap",
    "flashcards": "flashcards",
    "data table": "data table",
    "quiz": "quiz",
    "slideshow": "slideshow",
    "video": "video",
    "audio_overview": "audio_overview",
    "report": "report",
}

PLANNER_MODE_OPTIONS = {
    "Local First (No LLM if possible)": IntentRouterService.MODE_LOCAL_FIRST,
    "Detect and Prepare Using LLM": IntentRouterService.MODE_LLM_DRIVEN,
}


def render_intent_chat_tab(
    *,
    intent_router_service: IntentRouterService,
    llm_service: CachedLLMService,
    settings: GroqSettings,
    cache_count_placeholder: Any,
) -> None:
    st.markdown(INTENT_CHAT_TAB_CSS, unsafe_allow_html=True)
    st.markdown('<div class="ic-heading">Chat Bot Intent</div>', unsafe_allow_html=True)
    st.markdown(
        (
            '<div class="ic-subheading">'
            "Detect one or multiple intents, validate asset requirements, and prepare final payloads only "
            "(no content generation in this tab)."
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    history: list[dict[str, Any]] = st.session_state.intent_chat_history

    top_col_1, top_col_2 = st.columns([0.78, 0.22], vertical_alignment="bottom")
    with top_col_1:
        message = st.text_area(
            "Chat Message",
            placeholder="e.g. Create an advanced quiz, slideshow, and narrated video on Segment Trees with code examples.",
            height=120,
            key="intent_chat_message_input",
        )
    with top_col_2:
        st.markdown("#### Actions")
        planner_mode_label = st.radio(
            "Planner Mode",
            options=list(PLANNER_MODE_OPTIONS.keys()),
            index=0,
            key="intent_chat_planner_mode",
        )
        planner_mode = PLANNER_MODE_OPTIONS[planner_mode_label]
        detect_intent = st.button("Detect + Prepare", type="primary", key="intent_detect_btn", width="stretch")
        if st.button("Clear Chat", key="intent_chat_clear_btn", width="stretch"):
            st.session_state.intent_chat_history = []
            st.session_state.intent_chat_last_intents = []
            st.session_state.intent_chat_requirements_bundle = {}
            st.success("Chat history cleared.")
            st.rerun()

    if detect_intent:
        if not message or not message.strip():
            st.error("Please enter a message.")
            st.stop()
        if planner_mode == IntentRouterService.MODE_LLM_DRIVEN:
            if not settings.has_api_key():
                st.error("Please enter your Groq API key in the sidebar for LLM-driven mode.")
                st.stop()
            if not settings.has_model():
                st.error("Please select or enter a valid model for LLM-driven mode.")
                st.stop()

        try:
            with st.spinner("Detecting intents..."):
                detection_result = intent_router_service.detect_intent(
                    message=message,
                    settings=settings,
                    mode=planner_mode,
                )

            if detection_result.parse_note:
                st.info(detection_result.parse_note)

            if detection_result.parse_error or not detection_result.intents:
                st.error(detection_result.parse_error or "Could not detect intent.")
                st.caption("Raw model response:")
                st.code(detection_result.raw_text)
            else:
                with st.spinner("Preparing asset requirements..."):
                    payloads, prep_note, prep_cache_hit = intent_router_service.prepare_requirements(
                        message=message,
                        intents=detection_result.intents,
                        settings=settings,
                        mode=planner_mode,
                    )

                st.session_state.intent_chat_last_intents = detection_result.intents
                st.session_state.intent_chat_requirements_bundle = {
                    "message": message.strip(),
                    "intents": detection_result.intents,
                    "payloads": payloads,
                    "planner_mode": planner_mode,
                }
                st.session_state.intent_chat_history = [
                    *history,
                    {
                        "message": message.strip(),
                        "intents": detection_result.intents,
                        "planner_mode": planner_mode,
                    },
                ]

                if prep_note:
                    st.info(prep_note)

                if detection_result.cache_hit and prep_cache_hit:
                    st.info("Intent and requirement preparation served from cache.")
                else:
                    cache_count_placeholder.caption(f"Cached responses: {llm_service.count}")

                st.success("Intent and requirement planning prepared.")
                st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Request failed: {exc}")

    latest_intents: list[str] = st.session_state.intent_chat_last_intents
    if latest_intents:
        st.markdown("#### Latest Intent(s)")
        st.markdown("".join(f'<span class="ic-chip">{escape(intent)}</span>' for intent in latest_intents), unsafe_allow_html=True)

    bundle: dict[str, Any] = st.session_state.intent_chat_requirements_bundle
    if bundle and bundle.get("intents"):
        st.markdown("#### Requirement Planner")
        st.caption(f"Message: {bundle.get('message', '')}")
        st.caption(f"Mode: {bundle.get('planner_mode', IntentRouterService.MODE_LOCAL_FIRST)}")

        intents = [str(intent) for intent in bundle.get("intents", [])] if isinstance(bundle.get("intents"), list) else []
        payloads_raw = bundle.get("payloads")
        planner_payloads: IntentPayloadMap = cast(IntentPayloadMap, payloads_raw) if isinstance(payloads_raw, dict) else {}

        all_assets_ready = True
        for intent in intents:
            intent_slug = _intent_slug(intent)
            payload = _to_intent_payload(planner_payloads.get(intent, {}))
            missing_mandatory, missing_optional = intent_router_service.evaluate_requirements(intent=intent, payload=payload)
            optional_definitions = intent_router_service.optional_field_definitions(intent)
            intent_title = INTENT_DISPLAY_NAMES.get(intent, intent)

            with st.container(border=True):
                st.markdown(f"##### Asset: `{intent_title}`")

                if missing_mandatory:
                    all_assets_ready = False
                    st.error("Mandatory requirement missing: `topic`")
                    topic_input = st.text_input(
                        f"Provide topic for {intent_title}",
                        key=f"intent_topic_input_{intent_slug}",
                        placeholder="Enter the topic you want for this asset.",
                    )
                    if st.button("Set Mandatory Topic", key=f"intent_set_topic_btn_{intent_slug}"):
                        topic_text = topic_input.strip()
                        if not topic_text:
                            st.error("Topic cannot be empty.")
                        else:
                            payload["topic"] = topic_text
                            st.session_state.intent_chat_requirements_bundle["payloads"][intent] = payload
                            st.success("Mandatory topic captured.")
                            st.rerun()

                if not missing_mandatory and not missing_optional:
                    st.success("All requirements are fullfilled.")
                    st.markdown("**Data prepared for this asset:**")
                    st.json(payload)
                    continue

                if not missing_mandatory and missing_optional:
                    all_assets_ready = False
                    missing_list_text = ", ".join(f"`{field}`" for field in missing_optional)
                    st.warning(f"Optional requirements not fullfilled: {missing_list_text}")

                    resolution_mode = st.radio(
                        "Choose optional requirement fullfiller",
                        options=RESOLUTION_OPTIONS,
                        key=f"intent_resolution_mode_{intent_slug}",
                    )

                    if resolution_mode == RESOLUTION_OPTIONS[0]:
                        if st.button("Apply Default Optional Requirements", key=f"intent_apply_defaults_{intent_slug}"):
                            updated_payload = intent_router_service.apply_default_optionals(
                                intent=intent,
                                payload=payload,
                                missing_optional=missing_optional,
                            )
                            st.session_state.intent_chat_requirements_bundle["payloads"][intent] = updated_payload
                            st.success("Default optional requirements applied.")
                            st.rerun()

                    elif resolution_mode == RESOLUTION_OPTIONS[1]:
                        if not settings.has_api_key() or not settings.has_model():
                            st.error("Please set valid Groq API settings in sidebar.")
                        elif st.button("Fulfill Optional Requirements by LLM", key=f"intent_apply_llm_{intent_slug}"):
                            with st.spinner("Fulfilling optional requirements..."):
                                updated_payload, fill_note, fill_error, cache_hit = intent_router_service.fill_optional_with_llm(
                                    intent=intent,
                                    message=str(bundle.get("message", "")),
                                    payload=payload,
                                    missing_optional=missing_optional,
                                    settings=settings,
                                )
                            if fill_error:
                                st.error(fill_error)
                            else:
                                st.session_state.intent_chat_requirements_bundle["payloads"][intent] = updated_payload
                                if fill_note:
                                    st.info(fill_note)
                                if not cache_hit:
                                    cache_count_placeholder.caption(f"Cached responses: {llm_service.count}")
                                st.success("Optional requirements updated.")
                                st.rerun()

                    else:
                        user_values: dict[str, Any] = {}
                        for field_name in missing_optional:
                            meta = optional_definitions.get(field_name) or cast(RequirementFieldSpec, {})
                            user_values[field_name] = _render_optional_input_field(
                                intent_slug=intent_slug,
                                field_name=field_name,
                                meta=meta,
                            )

                        if st.button("Apply My Optional Inputs", key=f"intent_apply_manual_{intent_slug}"):
                            updated_payload = intent_router_service.apply_user_optionals(
                                intent=intent,
                                payload=payload,
                                user_values=cast(IntentPayload, user_values),
                                missing_optional=missing_optional,
                            )
                            st.session_state.intent_chat_requirements_bundle["payloads"][intent] = updated_payload
                            st.success("Manual optional inputs applied.")
                            st.rerun()

                st.markdown("**Current payload preview:**")
                st.json(payload)

        if all_assets_ready:
            st.success("All requirements are fullfilled for all detected assets.")
            st.caption("Payloads are ready. You can now route each payload to its respective asset generation flow.")

    if st.session_state.intent_chat_history:
        st.markdown("#### Chat Intent History")
        for entry in reversed(st.session_state.intent_chat_history):
            msg = str(entry.get("message", "")).strip()
            intents = entry.get("intents") or []
            intents_text = ", ".join(str(item) for item in intents) if intents else "N/A"
            mode_text = str(entry.get("planner_mode", IntentRouterService.MODE_LOCAL_FIRST))
            st.markdown(
                (
                    '<div class="ic-history-box">'
                    f'<p class="ic-history-user">Message: {escape(msg)}</p>'
                    f'<p class="ic-history-intent">Intent(s): {escape(intents_text)}</p>'
                    f'<p class="ic-history-intent">Mode: {escape(mode_text)}</p>'
                    "</div>"
                ),
                unsafe_allow_html=True,
            )


def _render_optional_input_field(*, intent_slug: str, field_name: str, meta: RequirementFieldSpec) -> Any:
    field_label = str(meta.get("label", field_name)).strip() or field_name
    field_type = str(meta.get("type", "text")).strip().lower()
    widget_key = f"intent_manual_{intent_slug}_{field_name.replace(' ', '_')}"

    if field_type == "int":
        return int(
            st.number_input(
                field_label,
                min_value=int(meta.get("min", 0)),
                max_value=int(meta.get("max", 100)),
                value=int(meta.get("default", meta.get("min", 0))),
                step=int(meta.get("step", 1)),
                key=widget_key,
            )
        )
    if field_type == "enum":
        options = [str(option) for option in meta.get("options", [])]
        default_value = str(meta.get("default", options[0] if options else "")).strip()
        default_index = options.index(default_value) if default_value in options else 0
        return st.selectbox(
            field_label,
            options=options,
            index=default_index,
            key=widget_key,
        )
    if field_type == "bool":
        return bool(
            st.checkbox(
                field_label,
                value=bool(meta.get("default", False)),
                key=widget_key,
            )
        )

    return st.text_area(
        field_label,
        value=str(meta.get("default", "")),
        key=widget_key,
        height=80,
    )


def _intent_slug(intent: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(intent).lower()).strip("_")


def _to_intent_payload(value: object) -> IntentPayload:
    if not isinstance(value, dict):
        return {}
    return cast(IntentPayload, {str(key): item for key, item in value.items()})
