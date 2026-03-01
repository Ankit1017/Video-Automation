from __future__ import annotations

import json
import re
from typing import Any

import streamlit as st

from main_app.constants import PRESET_MODELS, TAB_TITLES
from main_app.ui.state import (
    SESSION_DEFAULTS,
    save_session_default_overrides,
    sanitize_session_default_overrides,
)


_GROUP_CONFIG: dict[str, dict[str, tuple[str, ...]]] = {
    "Global App": {
        "keys": (
            "enabled_tab_titles",
            "groq_model_mode",
            "groq_model_select",
            "groq_model_custom",
            "groq_temperature",
            "groq_max_tokens",
        )
    },
    "Web Sourcing": {"prefixes": ("web_sourcing_",)},
    "Cache": {"prefixes": ("cache_center_",)},
    "Observability": {"prefixes": ("observability_",)},
    "Documentation": {"prefixes": ("documentation_",)},
    "Video": {"prefixes": ("video_",)},
    "Slideshow": {"prefixes": ("slideshow_",)},
    "Quiz": {"prefixes": ("quiz_",)},
    "Report": {"prefixes": ("report_",)},
    "Data Table": {"prefixes": ("data_table_",)},
    "Flashcards": {"prefixes": ("flashcards_",)},
    "Mind Map": {"prefixes": ("mind_map_",)},
    "Audio Overview": {"prefixes": ("audio_overview_",)},
    "Agent Dashboard": {"prefixes": ("agent_dashboard_",)},
    "Intent Chat": {"prefixes": ("intent_chat_",)},
}


def render_additional_settings_tab() -> None:
    st.subheader("Additional Settings")
    st.caption(
        "Central control panel for app-wide and asset-level defaults. Save once and defaults are auto-applied on next rerun."
    )

    overrides_state = st.session_state.get("session_default_overrides", {})
    overrides = dict(overrides_state) if isinstance(overrides_state, dict) else {}
    group_names = list(_GROUP_CONFIG.keys())
    selected_group = st.selectbox(
        "Settings Group",
        options=group_names,
        index=0,
        key="additional_settings_group",
    )

    group_keys = _keys_for_group(selected_group)
    if not group_keys:
        st.info("No configurable defaults found for this group.")
        return

    st.markdown("### Form Editor")
    st.caption("Structured field editor for the selected settings group.")
    form_payload, form_errors = _render_group_form_editor(
        selected_group=selected_group,
        group_keys=group_keys,
        current_overrides=overrides,
    )
    form_action_cols = st.columns(2)
    save_group_form = form_action_cols[0].button(
        "Save Group Defaults (Form)",
        type="primary",
        key=f"save_group_form_{selected_group}",
    )
    reset_group_form = form_action_cols[1].button(
        "Reset Group to App Defaults (Form)",
        key=f"reset_group_form_{selected_group}",
    )

    if save_group_form:
        if form_errors:
            for error in form_errors:
                st.error(error)
            return
        _apply_group_payload(
            group_keys=group_keys,
            parsed_group=form_payload,
            current_overrides=overrides,
            success_message=f"Saved `{selected_group}` defaults from form.",
        )
        return

    if reset_group_form:
        _reset_group_overrides(group_keys=group_keys, current_overrides=overrides)
        return

    st.markdown("---")
    st.markdown("### JSON Editor")
    st.caption("Advanced editor for direct JSON control of this group.")
    current_group_payload = {
        key: overrides.get(key, SESSION_DEFAULTS[key])
        for key in group_keys
    }
    editor_key = f"additional_settings_editor_{selected_group.lower().replace(' ', '_')}"
    editor_value = st.text_area(
        "Group Defaults (JSON)",
        value=json.dumps(current_group_payload, ensure_ascii=False, indent=2, sort_keys=True),
        height=360,
        key=editor_key,
    )

    action_cols = st.columns(3)
    save_group = action_cols[0].button("Save Group Defaults", type="primary", key=f"save_group_{selected_group}")
    reset_group = action_cols[1].button("Reset Group to App Defaults", key=f"reset_group_{selected_group}")
    reset_all = action_cols[2].button("Reset All Overrides", key="reset_all_overrides")

    if save_group:
        _save_group_overrides(
            selected_group=selected_group,
            group_keys=group_keys,
            editor_value=editor_value,
            current_overrides=overrides,
        )
        return

    if reset_group:
        _reset_group_overrides(group_keys=group_keys, current_overrides=overrides)
        return

    if reset_all:
        _reset_all_overrides()
        return

    st.markdown("---")
    with st.expander("Advanced: Raw Override Editor (All Asset Keys)", expanded=False):
        st.caption("Use this if you want to edit multiple groups at once.")
        editable_keys = _editable_asset_keys()
        raw_payload = {
            key: overrides.get(key, SESSION_DEFAULTS[key])
            for key in editable_keys
        }
        raw_text = st.text_area(
            "All Asset Defaults (JSON)",
            value=json.dumps(raw_payload, ensure_ascii=False, indent=2, sort_keys=True),
            height=320,
            key="additional_settings_raw_editor",
        )
        if st.button("Save Raw Defaults", type="primary", key="save_raw_overrides"):
            _save_raw_overrides(raw_text=raw_text, allowed_keys=set(editable_keys))
            return

    st.caption(f"Active override keys: {len(overrides)}")


def _render_group_form_editor(
    *,
    selected_group: str,
    group_keys: list[str],
    current_overrides: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    parsed_group: dict[str, Any] = {}
    errors: list[str] = []
    group_slug = _slugify(selected_group)

    for key in group_keys:
        default_value = SESSION_DEFAULTS[key]
        current_value = current_overrides.get(key, default_value)
        field_label = key.replace("_", " ").strip().title()
        widget_key = f"additional_form_{group_slug}_{_slugify(key)}"

        if key == "enabled_tab_titles":
            selected_titles = current_value if isinstance(current_value, list) else default_value
            parsed_group[key] = st.multiselect(
                field_label,
                options=TAB_TITLES,
                default=[title for title in selected_titles if title in TAB_TITLES],
                key=widget_key,
            )
            continue

        if key in {"groq_model_mode"}:
            options = ["Pick from list", "Custom model ID"]
            normalized_current = str(current_value).strip()
            if normalized_current not in options:
                normalized_current = options[0]
            parsed_group[key] = st.selectbox(
                field_label,
                options=options,
                index=options.index(normalized_current),
                key=widget_key,
            )
            continue

        if key in {"groq_model_select"}:
            normalized_current = str(current_value).strip()
            if normalized_current not in PRESET_MODELS:
                normalized_current = PRESET_MODELS[0]
            parsed_group[key] = st.selectbox(
                field_label,
                options=PRESET_MODELS,
                index=PRESET_MODELS.index(normalized_current),
                key=widget_key,
            )
            continue

        if key in {"web_sourcing_provider", "web_sourcing_secondary_provider_key"}:
            options = ["duckduckgo", "serper"]
            normalized_current = str(current_value).strip().lower()
            if normalized_current not in options:
                normalized_current = options[0]
            parsed_group[key] = st.selectbox(
                field_label,
                options=options,
                index=options.index(normalized_current),
                key=widget_key,
            )
            continue

        if isinstance(default_value, bool):
            parsed_group[key] = st.checkbox(
                field_label,
                value=bool(current_value),
                key=widget_key,
            )
            continue

        if isinstance(default_value, int):
            parsed_group[key] = int(
                st.number_input(
                    field_label,
                    value=int(current_value),
                    step=1,
                    key=widget_key,
                )
            )
            continue

        if isinstance(default_value, float):
            parsed_group[key] = float(
                st.number_input(
                    field_label,
                    value=float(current_value),
                    step=0.05,
                    key=widget_key,
                )
            )
            continue

        if isinstance(default_value, str):
            normalized_value = str(current_value)
            is_large_text = key.endswith("_raw") or len(normalized_value) > 120
            if is_large_text:
                parsed_group[key] = st.text_area(
                    field_label,
                    value=normalized_value,
                    height=100,
                    key=widget_key,
                )
            else:
                parsed_group[key] = st.text_input(
                    field_label,
                    value=normalized_value,
                    key=widget_key,
                )
            continue

        json_field_key = f"{widget_key}_json"
        json_value = st.text_area(
            f"{field_label} (JSON)",
            value=json.dumps(current_value, ensure_ascii=False, indent=2, sort_keys=True),
            height=120,
            key=json_field_key,
        )
        try:
            parsed_group[key] = json.loads(json_value)
        except ValueError as exc:
            errors.append(f"`{key}` JSON parse error: {exc}")

    return parsed_group, errors


def _keys_for_group(group_name: str) -> list[str]:
    config = _GROUP_CONFIG.get(group_name, {})
    keys = [key for key in config.get("keys", ()) if key in SESSION_DEFAULTS]
    prefixes = config.get("prefixes", ())
    prefixed_keys = [
        key
        for key in sorted(SESSION_DEFAULTS)
        if any(key.startswith(prefix) for prefix in prefixes)
    ]
    merged = list(dict.fromkeys([*keys, *prefixed_keys]))
    return merged


def _editable_asset_keys() -> list[str]:
    all_keys: list[str] = []
    for config in _GROUP_CONFIG.values():
        for key in config.get("keys", ()):
            if key in SESSION_DEFAULTS:
                all_keys.append(key)
        prefixes = config.get("prefixes", ())
        for session_key in sorted(SESSION_DEFAULTS):
            if any(session_key.startswith(prefix) for prefix in prefixes):
                all_keys.append(session_key)
    return list(dict.fromkeys(all_keys))


def _save_group_overrides(
    *,
    selected_group: str,
    group_keys: list[str],
    editor_value: str,
    current_overrides: dict[str, Any],
) -> None:
    try:
        parsed = json.loads(editor_value)
    except ValueError as exc:
        st.error(f"Invalid JSON for group `{selected_group}`: {exc}")
        return
    if not isinstance(parsed, dict):
        st.error("Group defaults JSON must be an object.")
        return

    parsed_group: dict[str, Any] = {}
    for key, value in parsed.items():
        normalized_key = str(key).strip()
        if normalized_key not in group_keys:
            st.error(f"Key `{normalized_key}` is not part of `{selected_group}` group.")
            return
        parsed_group[normalized_key] = value

    _apply_group_payload(
        group_keys=group_keys,
        parsed_group=parsed_group,
        current_overrides=current_overrides,
        success_message=f"Saved `{selected_group}` defaults.",
    )


def _reset_group_overrides(*, group_keys: list[str], current_overrides: dict[str, Any]) -> None:
    next_overrides = dict(current_overrides)
    for key in group_keys:
        next_overrides.pop(key, None)
    _persist_and_rerun(next_overrides, success_message="Group defaults reset to app defaults.")


def _reset_all_overrides() -> None:
    _persist_and_rerun({}, success_message="All override defaults were reset.")


def _save_raw_overrides(*, raw_text: str, allowed_keys: set[str]) -> None:
    try:
        parsed = json.loads(raw_text)
    except ValueError as exc:
        st.error(f"Invalid JSON in raw editor: {exc}")
        return
    if not isinstance(parsed, dict):
        st.error("Raw defaults JSON must be an object.")
        return
    filtered = {
        str(key).strip(): value
        for key, value in parsed.items()
        if str(key).strip() in allowed_keys
    }
    _persist_and_rerun(filtered, success_message="Raw defaults saved.")


def _apply_group_payload(
    *,
    group_keys: list[str],
    parsed_group: dict[str, Any],
    current_overrides: dict[str, Any],
    success_message: str,
) -> None:
    next_overrides = dict(current_overrides)
    for key in group_keys:
        if key in parsed_group:
            next_overrides[key] = parsed_group[key]
        else:
            next_overrides.pop(key, None)
    _persist_and_rerun(next_overrides, success_message=success_message)


def _slugify(raw_text: str) -> str:
    normalized = " ".join(str(raw_text).split()).strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return slug or "default"


def _persist_and_rerun(overrides: dict[str, Any], *, success_message: str) -> None:
    normalized = sanitize_session_default_overrides(overrides)
    persisted = save_session_default_overrides(normalized)
    st.session_state.session_default_overrides = dict(persisted)
    st.success(success_message)
    st.rerun()
