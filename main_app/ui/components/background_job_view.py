from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from main_app.services.background_jobs import BackgroundJobManager


def render_background_job_panel(
    *,
    manager: BackgroundJobManager,
    job_id: str,
    title: str,
    key_prefix: str,
    allow_retry: bool = True,
) -> str:
    normalized_job_id = " ".join(str(job_id).split()).strip()
    if not normalized_job_id:
        return ""

    snapshot = manager.get_snapshot(normalized_job_id)
    if snapshot is None:
        st.warning("Background job state not found. Start a new generation request.")
        return ""

    with st.container(border=True):
        st.markdown(f"#### {title}")
        st.caption(f"Job ID: `{snapshot.id}`")

        status = snapshot.status.replace("_", " ").title()
        queue_note = ""
        if snapshot.queue_position is not None:
            queue_note = f" | Queue position: {snapshot.queue_position}"
        st.caption(f"Status: {status} | Progress: {int(snapshot.progress * 100)}%{queue_note}")
        st.progress(float(snapshot.progress), text=snapshot.message or status)
        eta_line = _eta_line(snapshot=snapshot)
        if eta_line:
            st.caption(eta_line)
        stage_line = _stage_line(snapshot=snapshot)
        if stage_line:
            st.caption(stage_line)

        if snapshot.error:
            st.error(snapshot.error)

        if snapshot.retry_of:
            st.caption(f"Retry of job `{snapshot.retry_of}`")

        button_col_1, button_col_2, button_col_3 = st.columns([0.33, 0.33, 0.34], gap="small")
        with button_col_1:
            if snapshot.is_active:
                if st.button("Cancel", key=f"{key_prefix}_cancel", width="stretch"):
                    manager.cancel(snapshot.id)
                    st.info("Cancellation requested.")
                    st.rerun()
            else:
                st.button(
                    "Cancel",
                    key=f"{key_prefix}_cancel_disabled",
                    width="stretch",
                    disabled=True,
                )
        with button_col_2:
            if st.button("Refresh Status", key=f"{key_prefix}_refresh", width="stretch"):
                st.rerun()
        with button_col_3:
            if allow_retry and snapshot.is_terminal:
                if st.button("Retry Job", key=f"{key_prefix}_retry", width="stretch"):
                    new_job_id = manager.retry(snapshot.id)
                    if new_job_id:
                        st.success("Retry queued in background.")
                        return new_job_id
                    st.warning("Retry is not available for this job.")
            else:
                st.button(
                    "Retry Job",
                    key=f"{key_prefix}_retry_disabled",
                    width="stretch",
                    disabled=True,
                )

    return normalized_job_id


def _eta_line(*, snapshot: Any) -> str:
    eta_seconds = getattr(snapshot, "eta_seconds_remaining", None)
    eta_at = " ".join(str(getattr(snapshot, "estimated_finish_at", "")).split()).strip()
    historical_avg = getattr(snapshot, "historical_avg_duration_seconds", None)
    elapsed = getattr(snapshot, "elapsed_seconds", None)

    parts: list[str] = []
    if eta_seconds is not None:
        parts.append(f"Tentative completion in {_format_duration(float(eta_seconds))}")
    if eta_at:
        parts.append(f"ETA at {_format_timestamp(eta_at)}")
    if historical_avg is not None:
        parts.append(f"Avg similar job {_format_duration(float(historical_avg))}")
    if elapsed is not None and float(elapsed) > 0:
        parts.append(f"Elapsed {_format_duration(float(elapsed))}")
    if not parts:
        return ""
    return " | ".join(parts)


def _stage_line(*, snapshot: Any) -> str:
    stage_name = " ".join(str(getattr(snapshot, "stage_name", "")).split()).strip()
    if not stage_name:
        return ""
    stage_elapsed = getattr(snapshot, "stage_elapsed_seconds", None)
    stage_eta = getattr(snapshot, "stage_eta_seconds_remaining", None)
    parts = [f"Current stage: {stage_name}"]
    if stage_elapsed is not None:
        parts.append(f"Stage elapsed {_format_duration(float(stage_elapsed))}")
    if stage_eta is not None:
        parts.append(f"Tentative stage end in {_format_duration(float(stage_eta))}")
    return " | ".join(parts)


def _format_duration(seconds: float) -> str:
    safe = max(int(round(seconds)), 0)
    minutes, rem = divmod(safe, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {rem}s"
    if minutes > 0:
        return f"{minutes}m {rem}s"
    return f"{rem}s"


def _format_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
