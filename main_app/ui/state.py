from __future__ import annotations

import copy
import json
from typing import Any

import streamlit as st

from main_app.constants import PRESET_MODELS, SESSION_DEFAULT_OVERRIDES_FILE, TAB_TITLES
from main_app.infrastructure.cache_store import CacheStore


SESSION_DEFAULTS = {
    "enabled_tab_titles": list(TAB_TITLES),
    "groq_model_mode": "Pick from list",
    "groq_model_select": PRESET_MODELS[0],
    "groq_model_custom": "",
    "groq_temperature": 0.4,
    "groq_max_tokens": 1400,
    "mind_map_tree": None,
    "mind_map_topic": "",
    "mind_map_last_explained_path": "",
    "mind_map_last_explanation": "",
    "mind_map_selected_path": "",
    "mind_map_graph_direction": "TB",
    "mind_map_view_mode": "Full Graph",
    "mind_map_focus_path": "",
    "flashcards_topic": "",
    "flashcards_cards": [],
    "flashcards_index": 0,
    "flashcards_show_answer": False,
    "flashcards_explanations": {},
    "flashcards_last_explained_index": -1,
    "report_selected_format": "briefing_doc",
    "report_last_topic": "",
    "report_last_format_title": "",
    "report_last_content": "",
    "data_table_topic": "",
    "data_table_columns": [],
    "data_table_rows": [],
    "data_table_last_note": "",
    "quiz_topic": "",
    "quiz_questions": [],
    "quiz_index": 0,
    "quiz_selected_answers": {},
    "quiz_submitted": {},
    "quiz_hints": {},
    "quiz_feedback": {},
    "quiz_explanations": {},
    "quiz_selected_saved_id": "",
    "slideshow_topic": "",
    "slideshow_slides": [],
    "slideshow_index": 0,
    "slideshow_outline": [],
    "slideshow_last_constraints": "",
    "slideshow_last_code_mode": "auto",
    "slideshow_representation_mode": "auto",
    "slideshow_last_representation_mode": "auto",
    "slideshow_background_job_id": "",
    "slideshow_background_job_applied_id": "",
    "video_topic": "",
    "video_payload": None,
    "video_audio_bytes": None,
    "video_audio_error": "",
    "video_full_video_bytes": None,
    "video_full_video_error": "",
    "video_last_constraints": "",
    "video_language": "en",
    "video_slow_audio": False,
    "video_template": "standard",
    "video_animation_style": "smooth",
    "video_render_mode": "avatar_conversation",
    "video_avatar_enable_subtitles": True,
    "video_avatar_style_pack": "default",
    "video_avatar_allow_fallback": True,
    "video_representation_mode": "auto",
    "video_use_youtube_prompt": False,
    "video_last_representation_mode": "auto",
    "video_playback_language": "en",
    "video_playback_slow_audio": False,
    "video_slideshow_index": 0,
    "video_background_job_id": "",
    "video_background_job_applied_id": "",
    "audio_overview_topic": "",
    "audio_overview_payload": None,
    "audio_overview_audio_bytes": None,
    "audio_overview_audio_error": "",
    "audio_overview_last_constraints": "",
    "audio_overview_use_youtube_prompt": False,
    "audio_overview_use_hinglish_script": False,
    "audio_overview_background_job_id": "",
    "audio_overview_background_job_applied_id": "",
    "intent_chat_history": [],
    "intent_chat_last_intents": [],
    "intent_chat_requirements_bundle": {},
    "intent_chat_planner_mode": "Local First (No LLM if possible)",
    "agent_dashboard_history": [],
    "agent_dashboard_pending_plan": None,
    "agent_dashboard_planner_mode": "Local First (No LLM if possible)",
    "agent_dashboard_planner_mode_selector": "Local First (No LLM if possible)",
    "agent_dashboard_active_topic": "",
    "agent_dashboard_recent_topics": [],
    "agent_dashboard_session_id": "",
    "agent_dashboard_session_created_at": "",
    "agent_dashboard_selected_saved_session_id": "",
    "agent_dashboard_saved_session_selector": "",
    "agent_dashboard_force_sync_planner_selector": False,
    "agent_dashboard_force_sync_saved_selector": False,
    "agent_dashboard_store_initialized": False,
    "web_sourcing_enabled": False,
    "web_sourcing_provider": "duckduckgo",
    "web_sourcing_cache_ttl_seconds": 21600,
    "web_sourcing_max_search_results": 8,
    "web_sourcing_max_fetch_pages": 6,
    "web_sourcing_max_chars_per_page": 4000,
    "web_sourcing_max_total_chars": 20000,
    "web_sourcing_timeout_ms": 8000,
    "web_sourcing_allow_recency_days": 0,
    "web_sourcing_include_domains_raw": "",
    "web_sourcing_exclude_domains_raw": "",
    "web_sourcing_force_refresh": False,
    "web_sourcing_strict_mode": False,
    "web_sourcing_query_variant_count": 3,
    "web_sourcing_candidate_pool_multiplier": 3,
    "web_sourcing_min_quality_score": 0.45,
    "web_sourcing_max_results_per_domain": 2,
    "web_sourcing_trusted_boost_enabled": True,
    "web_sourcing_trusted_domains_raw": "",
    "web_sourcing_allow_provider_failover": True,
    "web_sourcing_secondary_provider_key": "serper",
    "web_sourcing_retry_count": 2,
    "web_sourcing_retry_base_delay_ms": 250,
    "web_sourcing_retry_max_delay_ms": 1500,
    "web_sourcing_domain_rate_limit_per_minute": 6,
    "web_sourcing_provider_circuit_breaker_enabled": True,
    "web_sourcing_provider_error_threshold": 4,
    "web_sourcing_provider_cooldown_seconds": 120,
    "web_sourcing_provider_probe_requests": 1,
    "web_sourcing_reliability_diagnostics_enabled": True,
    "cache_center_default_filter_text": "",
    "cache_center_table_max_rows": 200,
    "cache_center_preview_chars": 12000,
    "observability_show_progress": True,
    "observability_show_charts": True,
    "observability_show_table": True,
    "observability_enable_download": True,
    "documentation_mode": "UI Documentation",
    "documentation_search_query": "",
    "documentation_selected_debug_doc": "UI Documentation Reference",
    "documentation_ui_section": "Overview",
    "documentation_debug_section": "Overview",
    "documentation_ui_feature_focus": "",
    "documentation_expand_all_ui_sections": False,
    "documentation_show_full_backend_matrix": False,
}


_SESSION_OVERRIDES_KEY = "session_default_overrides"
_SESSION_OVERRIDES_APPLIED_VERSION_KEY = "session_default_overrides_applied_version"


def load_session_default_overrides() -> dict[str, Any]:
    try:
        if not SESSION_DEFAULT_OVERRIDES_FILE.exists():
            return {}
        payload = json.loads(SESSION_DEFAULT_OVERRIDES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return sanitize_session_default_overrides(payload)


def save_session_default_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    normalized = sanitize_session_default_overrides(overrides)
    try:
        SESSION_DEFAULT_OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_DEFAULT_OVERRIDES_FILE.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError:
        return normalized
    return normalized


def sanitize_session_default_overrides(raw: dict[str, Any] | None) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {}
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        normalized_key = str(key).strip()
        if not normalized_key or normalized_key not in SESSION_DEFAULTS:
            continue
        default_value = SESSION_DEFAULTS[normalized_key]
        coerced = _coerce_override_value(value=value, default_value=default_value)
        if _is_json_compatible(coerced):
            normalized[normalized_key] = coerced
    return normalized


def _coerce_override_value(*, value: Any, default_value: Any) -> Any:
    if isinstance(default_value, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = " ".join(value.split()).strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
        return default_value
    if isinstance(default_value, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default_value
    if isinstance(default_value, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default_value
    if isinstance(default_value, str):
        return str(value)
    if isinstance(default_value, list):
        return value if isinstance(value, list) else default_value
    if isinstance(default_value, dict):
        return value if isinstance(value, dict) else default_value
    if default_value is None:
        return value
    return default_value


def _is_json_compatible(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_json_compatible(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_compatible(item) for key, item in value.items())
    return False


def initialize_session_state(cache_store: CacheStore) -> None:
    if "llm_cache" not in st.session_state:
        st.session_state.llm_cache = cache_store.load()

    overrides = load_session_default_overrides()
    st.session_state[_SESSION_OVERRIDES_KEY] = copy.deepcopy(overrides)
    override_version = json.dumps(overrides, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    should_apply_overrides = st.session_state.get(_SESSION_OVERRIDES_APPLIED_VERSION_KEY) != override_version

    for key, default_value in SESSION_DEFAULTS.items():
        if should_apply_overrides and key in overrides:
            st.session_state[key] = copy.deepcopy(overrides[key])
            continue
        if key not in st.session_state:
            st.session_state[key] = copy.deepcopy(default_value)

    st.session_state[_SESSION_OVERRIDES_APPLIED_VERSION_KEY] = override_version
