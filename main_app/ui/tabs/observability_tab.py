from __future__ import annotations

import json
from typing import Any

import streamlit as st

from main_app.services.observability_service import ObservabilityService


def render_observability_tab(*, observability_service: ObservabilityService | None) -> None:
    st.subheader("Observability")
    st.caption("Operational visibility for LLM usage, latency, cache behavior, token volume, and estimated cost.")

    if observability_service is None:
        st.info("Observability service is not available in this session.")
        return

    current_request_id = observability_service.current_request_id()
    st.caption(f"Current request ID: `{current_request_id}`" if current_request_id else "Current request ID: (none)")

    overall = observability_service.overall_metrics()
    rows = observability_service.metrics_table_rows()
    show_progress = bool(st.session_state.get("observability_show_progress", True))
    show_charts = bool(st.session_state.get("observability_show_charts", True))
    show_table = bool(st.session_state.get("observability_show_table", True))
    enable_download = bool(st.session_state.get("observability_enable_download", True))

    metric_cols = st.columns(6)
    metric_cols[0].metric("Requests", str(overall.request_count))
    metric_cols[1].metric("LLM Calls", str(overall.llm_calls))
    metric_cols[2].metric("Cache Hit Rate", f"{overall.cache_hit_rate * 100.0:.2f}%")
    metric_cols[3].metric("Avg Latency", f"{overall.avg_latency_ms:.2f} ms")
    metric_cols[4].metric("Total Tokens", str(overall.total_tokens))
    metric_cols[5].metric("Est. Cost", f"${overall.total_estimated_cost_usd:.6f}")

    if show_progress:
        st.progress(min(max(float(overall.cache_hit_rate), 0.0), 1.0), text="Overall cache hit rate")

    if rows:
        chart_rows = _normalize_chart_rows(rows)
        if show_charts:
            with st.container(border=True):
                st.markdown("#### Per-Asset Charts")
                chart_cols_top = st.columns(2)
                chart_cols_bottom = st.columns(2)
                chart_cols_top[0].bar_chart(chart_rows, x="asset", y="llm_calls")
                chart_cols_top[1].bar_chart(chart_rows, x="asset", y="cache_hit_rate")
                chart_cols_bottom[0].bar_chart(chart_rows, x="asset", y="avg_latency_ms")
                chart_cols_bottom[1].bar_chart(chart_rows, x="asset", y="est_cost_usd")

        if show_table:
            st.markdown("#### Metrics Table")
            st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.info("No observability metrics recorded yet.")

    with st.container(border=True):
        st.markdown("#### Controls")
        action_cols = st.columns(2)
        reset_clicked = action_cols[0].button("Reset Observability Metrics", key="observability_tab_reset")
        if reset_clicked:
            observability_service.reset()
            st.success("Observability metrics reset.")
            st.rerun()

        raw_payload = {
            "overall": {
                "request_count": overall.request_count,
                "llm_calls": overall.llm_calls,
                "cache_hits": overall.cache_hits,
                "cache_hit_rate": overall.cache_hit_rate,
                "avg_latency_ms": overall.avg_latency_ms,
                "total_latency_ms": overall.total_latency_ms,
                "total_estimated_cost_usd": overall.total_estimated_cost_usd,
                "total_prompt_tokens": overall.total_prompt_tokens,
                "total_completion_tokens": overall.total_completion_tokens,
                "total_tokens": overall.total_tokens,
                "errors": overall.errors,
                "last_request_id": overall.last_request_id,
                "last_updated_at": overall.last_updated_at,
            },
            "rows": rows,
        }
        if enable_download:
            action_cols[1].download_button(
                label="Download Metrics JSON",
                data=json.dumps(raw_payload, ensure_ascii=False, indent=2),
                file_name="observability_metrics.json",
                mime="application/json",
                key="observability_tab_download",
            )


def _normalize_chart_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chart_rows: list[dict[str, Any]] = []
    for row in rows:
        asset = " ".join(str(row.get("asset", "")).split()).strip() or "other"
        chart_rows.append(
            {
                "asset": asset,
                "llm_calls": max(int(row.get("llm_calls", 0) or 0), 0),
                "cache_hit_rate": max(float(row.get("cache_hit_rate", 0.0) or 0.0), 0.0),
                "avg_latency_ms": max(float(row.get("avg_latency_ms", 0.0) or 0.0), 0.0),
                "est_cost_usd": max(float(row.get("est_cost_usd", 0.0) or 0.0), 0.0),
            }
        )
    return chart_rows
