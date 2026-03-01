from __future__ import annotations

from collections import Counter
from typing import Any

import streamlit as st

from main_app.services.cached_llm_service import CachedLLMService


def render_cache_center_tab(*, llm_service: CachedLLMService, cache_location: str) -> None:
    st.subheader("Cache Center")
    st.caption("Manage LLM cache entries with filters, distributions, and detailed entry inspection.")
    st.caption(f"Storage: `{cache_location}`")

    entries = llm_service.cache_entries_latest_first()
    if not entries:
        st.info("No cache entries available yet.")
        return

    default_filter_text = str(st.session_state.get("cache_center_default_filter_text", "")).strip()
    filter_text = " ".join(
        str(
            st.text_input(
                "Filter entries",
                placeholder="Search by label, task, model, topic, or cache key prefix",
                value=default_filter_text,
                key="cache_center_filter_text",
            )
        ).split()
    ).strip()
    filtered_entries = _filter_entries(entries, filter_text)

    total_chars = sum(max(int(entry.get("response_chars", 0) or 0), 0) for entry in entries)
    avg_chars = (total_chars / len(entries)) if entries else 0.0
    metric_cols = st.columns(4)
    metric_cols[0].metric("Total Entries", str(len(entries)))
    metric_cols[1].metric("Visible Entries", str(len(filtered_entries)))
    metric_cols[2].metric("Total Cached Chars", str(total_chars))
    metric_cols[3].metric("Avg Chars / Entry", f"{avg_chars:.0f}")

    if filtered_entries:
        with st.container(border=True):
            st.markdown("#### Distribution")
            chart_cols = st.columns(2)
            task_rows = _build_distribution_rows(filtered_entries, field_name="task", label_name="task")
            model_rows = _build_distribution_rows(filtered_entries, field_name="model", label_name="model")
            if task_rows:
                chart_cols[0].bar_chart(task_rows, x="task", y="entries")
            else:
                chart_cols[0].caption("No task distribution data.")
            if model_rows:
                chart_cols[1].bar_chart(model_rows, x="model", y="entries")
            else:
                chart_cols[1].caption("No model distribution data.")
    else:
        st.warning("No cache entries matched the filter.")

    table_max_rows = max(int(st.session_state.get("cache_center_table_max_rows", 200) or 200), 1)

    _render_cache_table(filtered_entries, max_rows=table_max_rows)
    _render_cache_entry_inspector(llm_service=llm_service, filtered_entries=filtered_entries)

    with st.container(border=True):
        st.markdown("#### Cache Actions")
        selected_key = st.session_state.get("cache_center_selected_key")
        action_cols = st.columns(3)
        if action_cols[0].button(
            "Clear Selected Entry",
            key="cache_center_clear_selected",
            disabled=not bool(selected_key),
        ):
            llm_service.clear_entry(str(selected_key))
            st.success("Selected cache entry cleared.")
            st.rerun()

        confirm_clear_all = action_cols[1].checkbox("Confirm clear all", key="cache_center_confirm_clear_all")
        if action_cols[2].button(
            "Clear Entire Cache",
            key="cache_center_clear_all",
            disabled=not bool(confirm_clear_all),
        ):
            llm_service.clear_all()
            st.success("All cache entries cleared.")
            st.rerun()


def _filter_entries(entries: list[dict[str, Any]], filter_text: str) -> list[dict[str, Any]]:
    if not filter_text:
        return entries
    normalized_filter = filter_text.lower()
    filtered: list[dict[str, Any]] = []
    for entry in entries:
        search_blob = " ".join(
            [
                str(entry.get("key", "")),
                str(entry.get("label", "")),
                str(entry.get("task", "")),
                str(entry.get("model", "")),
                str(entry.get("topic", "")),
            ]
        ).lower()
        if normalized_filter in search_blob:
            filtered.append(entry)
    return filtered


def _build_distribution_rows(
    entries: list[dict[str, Any]],
    *,
    field_name: str,
    label_name: str,
) -> list[dict[str, Any]]:
    values = [
        " ".join(str(entry.get(field_name, "")).split()).strip() or "(unknown)"
        for entry in entries
    ]
    counts = Counter(values)
    return [
        {label_name: label, "entries": count}
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _render_cache_table(entries: list[dict[str, Any]], *, max_rows: int) -> None:
    st.markdown("#### Cache Entries")
    if not entries:
        st.caption("No rows to display.")
        return

    rows = []
    for entry in entries:
        usage = entry.get("usage") if isinstance(entry.get("usage"), dict) else {}
        token_count = _to_int(usage.get("total_tokens", 0), 0) if isinstance(usage, dict) else 0
        rows.append(
            {
                "key": str(entry.get("key", ""))[:12],
                "label": str(entry.get("label", "")),
                "task": str(entry.get("task", "")),
                "model": str(entry.get("model", "")),
                "topic": str(entry.get("topic", "")),
                "chars": int(entry.get("response_chars", 0) or 0),
                "tokens": token_count,
            }
        )
    if len(rows) > max_rows:
        st.caption(f"Showing first {max_rows} rows out of {len(rows)}.")
    st.dataframe(rows[:max_rows], width="stretch", hide_index=True)


def _render_cache_entry_inspector(
    *,
    llm_service: CachedLLMService,
    filtered_entries: list[dict[str, Any]],
) -> None:
    st.markdown("#### Entry Inspector")
    keys = [str(entry.get("key", "")) for entry in filtered_entries if str(entry.get("key", "")).strip()]
    if not keys:
        st.caption("Select filters that return at least one cache entry.")
        return

    selected_key = st.selectbox(
        "Select Cache Entry",
        options=keys,
        format_func=llm_service.cache_entry_label,
        key="cache_center_selected_key",
    )
    selected_entry = llm_service.cache_entry(str(selected_key))
    if selected_entry is None:
        st.warning("Selected cache entry could not be loaded.")
        return

    usage = selected_entry.get("usage") if isinstance(selected_entry.get("usage"), dict) else {}
    token_count = _to_int(usage.get("total_tokens", 0), 0) if isinstance(usage, dict) else 0
    detail_cols = st.columns(4)
    detail_cols[0].metric("Task", str(selected_entry.get("task", "")) or "(unknown)")
    detail_cols[1].metric("Model", str(selected_entry.get("model", "")) or "(unknown)")
    detail_cols[2].metric("Chars", str(int(selected_entry.get("response_chars", 0) or 0)))
    detail_cols[3].metric("Tokens", str(token_count))

    st.text_input(
        "Topic",
        value=str(selected_entry.get("topic", "")),
        disabled=True,
        key=f"cache_center_topic_{selected_key[:8]}",
    )
    st.text_input(
        "Label",
        value=str(selected_entry.get("label", "")),
        disabled=True,
        key=f"cache_center_label_{selected_key[:8]}",
    )
    st.text_area(
        "Response Preview",
        value=str(selected_entry.get("response", ""))[:max(int(st.session_state.get("cache_center_preview_chars", 12000) or 12000), 1000)],
        height=320,
        disabled=True,
        key=f"cache_center_response_{selected_key[:8]}",
    )


def _to_int(value: object, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        if isinstance(value, (int, float, str)):
            return int(value)
        return int(str(value))
    except (TypeError, ValueError):
        return default
