from __future__ import annotations

import json
from typing import Any

import streamlit as st

from main_app.services.observability_service import ObservabilityService


def render_observability_tab(*, observability_service: ObservabilityService | None) -> None:
    st.subheader("Observability")
    st.caption(
        "Unified observability across LLM, web sourcing, agent orchestration, background jobs, exports, and storage."
    )

    if observability_service is None:
        st.info("Observability service is not available in this session.")
        return

    current_request_id = observability_service.current_request_id()
    st.caption(f"Current request ID: `{current_request_id}`" if current_request_id else "Current request ID: (none)")
    telemetry_context = observability_service.telemetry_service.current_context()
    st.caption(
        "Telemetry Context: "
        f"session=`{telemetry_context.session_id or '-'}` "
        f"run=`{telemetry_context.run_id or '-'}` "
        f"job=`{telemetry_context.job_id or '-'}` "
        f"trace=`{telemetry_context.trace_id or '-'}` "
        f"span=`{telemetry_context.span_id or '-'}`"
    )

    overall = observability_service.overall_metrics()
    rows = observability_service.metrics_table_rows()
    telemetry_overview = observability_service.telemetry_overview()
    telemetry_metric_rows = observability_service.telemetry_metric_rows()
    telemetry_metric_points = observability_service.telemetry_recent_metric_rows(limit=500)
    telemetry_event_rows = observability_service.telemetry_recent_event_rows(limit=250)
    show_progress = bool(st.session_state.get("observability_show_progress", True))
    show_charts = bool(st.session_state.get("observability_show_charts", True))
    show_table = bool(st.session_state.get("observability_show_table", True))
    enable_download = bool(st.session_state.get("observability_enable_download", True))
    show_telemetry_metrics = bool(st.session_state.get("observability_show_telemetry_metrics", True))
    show_telemetry_metric_points = bool(st.session_state.get("observability_show_telemetry_metric_points", True))
    show_telemetry_events = bool(st.session_state.get("observability_show_telemetry_events", True))
    show_payload_lookup = bool(st.session_state.get("observability_show_payload_lookup", True))

    metric_cols = st.columns(5)
    metric_cols[0].metric("Requests", str(overall.request_count))
    metric_cols[1].metric("LLM Calls", str(overall.llm_calls))
    metric_cols[2].metric("Cache Hit Rate", f"{overall.cache_hit_rate * 100.0:.2f}%")
    metric_cols[3].metric("Avg Latency", f"{overall.avg_latency_ms:.2f} ms")
    metric_cols[4].metric("Est. Cost", f"${overall.total_estimated_cost_usd:.6f}")

    metric_cols_2 = st.columns(5)
    metric_cols_2[0].metric("Total Tokens", str(overall.total_tokens))
    metric_cols_2[1].metric("Errors", str(overall.errors))
    metric_cols_2[2].metric("Metric Families", str(telemetry_overview.get("metric_family_count", 0)))
    metric_cols_2[3].metric("Recent Metrics", str(telemetry_overview.get("recent_metric_count", 0)))
    metric_cols_2[4].metric("Recent Events", str(telemetry_overview.get("recent_event_count", 0)))

    metric_cols_3 = st.columns(3)
    metric_cols_3[0].metric("Components", str(telemetry_overview.get("component_count", 0)))
    metric_cols_3[1].metric("Metric Buffer Cap", str(telemetry_overview.get("metric_capacity", 0)))
    metric_cols_3[2].metric("Event Buffer Cap", str(telemetry_overview.get("event_capacity", 0)))

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

    if show_telemetry_metrics:
        with st.container(border=True):
            st.markdown("#### Telemetry Metric Families (Aggregated)")
            if telemetry_metric_rows:
                metric_family_name_query = st.text_input(
                    "Metric name contains",
                    value=str(st.session_state.get("observability_metric_name_filter", "")),
                    key="observability_metric_name_filter",
                )
                metric_family_component_query = st.text_input(
                    "Metric component contains",
                    value=str(st.session_state.get("observability_metric_component_filter", "")),
                    key="observability_metric_component_filter",
                )
                filtered_metric_families = _filter_metric_families(
                    telemetry_metric_rows,
                    metric_name_query=metric_family_name_query,
                    component_query=metric_family_component_query,
                )
                st.caption(f"Showing {len(filtered_metric_families)} of {len(telemetry_metric_rows)} metric families.")
                st.dataframe(filtered_metric_families, width="stretch", hide_index=True)
            else:
                st.info("No telemetry metrics emitted yet.")

    if show_telemetry_metric_points:
        with st.container(border=True):
            st.markdown("#### Recent Telemetry Metric Samples (All Emissions)")
            if telemetry_metric_points:
                metric_name_query = st.text_input(
                    "Filter by metric name",
                    value=str(st.session_state.get("observability_metric_point_name_filter", "")),
                    key="observability_metric_point_name_filter",
                )
                metric_component_query = st.text_input(
                    "Filter by metric component contains",
                    value=str(st.session_state.get("observability_metric_point_component_filter", "")),
                    key="observability_metric_point_component_filter",
                )
                metric_request_id_query = st.text_input(
                    "Filter by request_id contains",
                    value=str(st.session_state.get("observability_metric_point_request_filter", "")),
                    key="observability_metric_point_request_filter",
                )
                metric_run_id_query = st.text_input(
                    "Filter by run_id contains",
                    value=str(st.session_state.get("observability_metric_point_run_filter", "")),
                    key="observability_metric_point_run_filter",
                )
                filtered_metric_points = _filter_metric_points(
                    telemetry_metric_points,
                    metric_name_query=metric_name_query,
                    component_query=metric_component_query,
                    request_id_query=metric_request_id_query,
                    run_id_query=metric_run_id_query,
                )
                st.caption(f"Showing {len(filtered_metric_points)} of {len(telemetry_metric_points)} metric samples.")
                st.dataframe(
                    _normalize_metric_points(filtered_metric_points),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("No telemetry metric samples captured yet.")

    if show_telemetry_events:
        with st.container(border=True):
            st.markdown("#### Recent Telemetry Events")
            if telemetry_event_rows:
                event_name_query = st.text_input(
                    "Filter by event name contains",
                    value=str(st.session_state.get("observability_event_name_filter", "")),
                    key="observability_event_name_filter",
                )
                status_filter = st.selectbox(
                    "Filter by status",
                    options=["all", "ok", "started", "warning", "error", "failed", "completed", "cancelled"],
                    index=0,
                    key="observability_event_status_filter",
                )
                component_query = st.text_input(
                    "Filter by component contains",
                    value=str(st.session_state.get("observability_event_component_filter", "")),
                    key="observability_event_component_filter",
                )
                request_id_query = st.text_input(
                    "Filter by request_id contains",
                    value=str(st.session_state.get("observability_event_request_filter", "")),
                    key="observability_event_request_filter",
                )
                run_id_query = st.text_input(
                    "Filter by run_id contains",
                    value=str(st.session_state.get("observability_event_run_filter", "")),
                    key="observability_event_run_filter",
                )
                filtered_events = _filter_events(
                    telemetry_event_rows,
                    event_name_query=event_name_query,
                    status_filter=status_filter,
                    component_query=component_query,
                    request_id_query=request_id_query,
                    run_id_query=run_id_query,
                )
                st.caption(f"Showing {len(filtered_events)} of {len(telemetry_event_rows)} events.")
                st.dataframe(_normalize_event_rows(filtered_events), width="stretch", hide_index=True)
            else:
                st.info("No telemetry events captured yet.")

    if show_payload_lookup:
        with st.container(border=True):
            st.markdown("#### Payload Lookup")
            payload_ref = st.text_input(
                "Payload Ref",
                value=str(st.session_state.get("observability_payload_ref", "")),
                placeholder="payload_xxx",
                key="observability_payload_ref",
            )
            if payload_ref:
                payload = observability_service.fetch_payload(payload_ref.strip())
                if payload is None:
                    st.warning("Payload not found for this reference.")
                else:
                    st.json(payload)

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
            "telemetry_overview": telemetry_overview,
            "telemetry_metrics": telemetry_metric_rows,
            "telemetry_metric_points": telemetry_metric_points,
            "telemetry_events": telemetry_event_rows,
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


def _filter_events(
    events: list[dict[str, Any]],
    *,
    event_name_query: str,
    status_filter: str,
    component_query: str,
    request_id_query: str,
    run_id_query: str,
) -> list[dict[str, Any]]:
    normalized_event_name_query = " ".join(str(event_name_query).split()).strip().lower()
    normalized_status = " ".join(str(status_filter).split()).strip().lower()
    normalized_component_query = " ".join(str(component_query).split()).strip().lower()
    normalized_request_query = " ".join(str(request_id_query).split()).strip().lower()
    normalized_run_query = " ".join(str(run_id_query).split()).strip().lower()
    output: list[dict[str, Any]] = []
    for event in events:
        event_name = " ".join(str(event.get("event_name", "")).split()).strip().lower()
        status = " ".join(str(event.get("status", "")).split()).strip().lower()
        component = " ".join(str(event.get("component", "")).split()).strip().lower()
        attrs = event.get("attributes", {})
        attrs_dict = attrs if isinstance(attrs, dict) else {}
        request_id = " ".join(str(attrs_dict.get("request_id", "")).split()).strip().lower()
        run_id = " ".join(str(attrs_dict.get("run_id", "")).split()).strip().lower()
        if normalized_event_name_query and normalized_event_name_query not in event_name:
            continue
        if normalized_status != "all" and status != normalized_status:
            continue
        if normalized_component_query and normalized_component_query not in component:
            continue
        if normalized_request_query and normalized_request_query not in request_id:
            continue
        if normalized_run_query and normalized_run_query not in run_id:
            continue
        output.append(event)
    return output


def _filter_metric_families(
    metric_rows: list[dict[str, Any]],
    *,
    metric_name_query: str,
    component_query: str,
) -> list[dict[str, Any]]:
    normalized_metric_name_query = " ".join(str(metric_name_query).split()).strip().lower()
    normalized_component_query = " ".join(str(component_query).split()).strip().lower()
    output: list[dict[str, Any]] = []
    for row in metric_rows:
        metric_name = " ".join(str(row.get("metric_name", "")).split()).strip().lower()
        component = " ".join(str(row.get("component", "")).split()).strip().lower()
        if normalized_metric_name_query and normalized_metric_name_query not in metric_name:
            continue
        if normalized_component_query and normalized_component_query not in component:
            continue
        output.append(row)
    return output


def _filter_metric_points(
    metric_points: list[dict[str, Any]],
    *,
    metric_name_query: str,
    component_query: str,
    request_id_query: str,
    run_id_query: str,
) -> list[dict[str, Any]]:
    normalized_metric_name_query = " ".join(str(metric_name_query).split()).strip().lower()
    normalized_component_query = " ".join(str(component_query).split()).strip().lower()
    normalized_request_query = " ".join(str(request_id_query).split()).strip().lower()
    normalized_run_query = " ".join(str(run_id_query).split()).strip().lower()
    output: list[dict[str, Any]] = []
    for point in metric_points:
        metric_name = " ".join(str(point.get("metric_name", "")).split()).strip().lower()
        attrs = point.get("attributes", {})
        attrs_dict = attrs if isinstance(attrs, dict) else {}
        component = " ".join(str(attrs_dict.get("component", "")).split()).strip().lower()
        request_id = " ".join(str(attrs_dict.get("request_id", "")).split()).strip().lower()
        run_id = " ".join(str(attrs_dict.get("run_id", "")).split()).strip().lower()
        if normalized_metric_name_query and normalized_metric_name_query not in metric_name:
            continue
        if normalized_component_query and normalized_component_query not in component:
            continue
        if normalized_request_query and normalized_request_query not in request_id:
            continue
        if normalized_run_query and normalized_run_query not in run_id:
            continue
        output.append(point)
    return output


def _normalize_metric_points(metric_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for point in metric_points:
        attrs = point.get("attributes", {})
        attrs_dict = attrs if isinstance(attrs, dict) else {}
        output.append(
            {
                "metric_name": " ".join(str(point.get("metric_name", "")).split()).strip(),
                "value": point.get("value", 0.0),
                "timestamp": " ".join(str(point.get("timestamp", "")).split()).strip(),
                "component": " ".join(str(attrs_dict.get("component", "")).split()).strip(),
                "status": " ".join(str(attrs_dict.get("status", "")).split()).strip(),
                "request_id": " ".join(str(attrs_dict.get("request_id", "")).split()).strip(),
                "session_id": " ".join(str(attrs_dict.get("session_id", "")).split()).strip(),
                "run_id": " ".join(str(attrs_dict.get("run_id", "")).split()).strip(),
                "job_id": " ".join(str(attrs_dict.get("job_id", "")).split()).strip(),
                "trace_id": " ".join(str(attrs_dict.get("trace_id", "")).split()).strip(),
                "span_id": " ".join(str(attrs_dict.get("span_id", "")).split()).strip(),
                "attributes": dict(attrs_dict),
            }
        )
    return output


def _normalize_event_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for event in events:
        attrs = event.get("attributes", {})
        attrs_dict = attrs if isinstance(attrs, dict) else {}
        output.append(
            {
                "timestamp": " ".join(str(event.get("timestamp", "")).split()).strip(),
                "event_name": " ".join(str(event.get("event_name", "")).split()).strip(),
                "component": " ".join(str(event.get("component", "")).split()).strip(),
                "status": " ".join(str(event.get("status", "")).split()).strip(),
                "payload_ref": " ".join(str(event.get("payload_ref", "")).split()).strip(),
                "request_id": " ".join(str(attrs_dict.get("request_id", "")).split()).strip(),
                "session_id": " ".join(str(attrs_dict.get("session_id", "")).split()).strip(),
                "run_id": " ".join(str(attrs_dict.get("run_id", "")).split()).strip(),
                "job_id": " ".join(str(attrs_dict.get("job_id", "")).split()).strip(),
                "trace_id": " ".join(str(attrs_dict.get("trace_id", "")).split()).strip(),
                "span_id": " ".join(str(attrs_dict.get("span_id", "")).split()).strip(),
                "attributes": dict(attrs_dict),
            }
        )
    return output
