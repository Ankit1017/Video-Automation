from __future__ import annotations

import csv
import io
import json
from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from main_app.contracts import DataTablePayload
from main_app.models import GroqSettings
from main_app.services.cached_llm_service import CachedLLMService
from main_app.services.data_table_service import DataTableService

DATA_TABLE_CSS = """
<style>
    .dt-meta {
        color: #4b5563;
        font-weight: 600;
        margin-top: 2px;
        margin-bottom: 2px;
    }
    .dt-kpi {
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 10px 12px;
        background: #f9fafb;
    }
    .dt-kpi-label {
        color: #6b7280;
        font-size: 0.82rem;
        margin-bottom: 2px;
    }
    .dt-kpi-value {
        color: #111827;
        font-size: 1.15rem;
        font-weight: 700;
    }
</style>
"""


def _table_columns(payload: DataTablePayload) -> list[str]:
    raw_columns = payload.get("columns", [])
    if not isinstance(raw_columns, list):
        return []
    return [str(column).strip() for column in raw_columns if str(column).strip()]


def _table_rows(payload: DataTablePayload, *, columns: list[str]) -> list[dict[str, str]]:
    raw_rows = payload.get("rows", [])
    if not isinstance(raw_rows, list):
        return []
    rows: list[dict[str, str]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            continue
        normalized: dict[str, str] = {}
        for column in columns:
            normalized[column] = str(raw_row.get(column, ""))
        rows.append(normalized)
    return rows


def render_data_table_tab(
    *,
    data_table_service: DataTableService,
    llm_service: CachedLLMService,
    settings: GroqSettings,
    cache_count_placeholder: Any,
) -> None:
    st.markdown(DATA_TABLE_CSS, unsafe_allow_html=True)
    st.subheader("Data Table Builder")

    setup_col, control_col = st.columns([0.72, 0.28], gap="large")

    with setup_col:
        topic = st.text_input(
            "Topic for Data Table",
            placeholder="e.g. Programming Languages",
            key="data_table_topic_input",
        )
        notes = st.text_area(
            "Optional Constraints",
            placeholder="e.g. focus on backend use cases and include performance-related attributes.",
            height=90,
            key="data_table_notes",
        )

    with control_col:
        st.markdown("#### Table Controls")
        row_count = st.slider(
            "Rows",
            min_value=3,
            max_value=30,
            value=10,
            step=1,
            key="data_table_row_count",
        )
        generate_table = st.button(
            "Generate Data Table",
            type="primary",
            key="generate_data_table",
            width="stretch",
        )

    if generate_table:
        if not settings.has_api_key():
            st.error("Please enter your Groq API key in the sidebar.")
            st.stop()
        if not settings.has_model():
            st.error("Please select or enter a valid model.")
            st.stop()
        if not topic or not topic.strip():
            st.error("Please enter a topic.")
            st.stop()

        try:
            with st.spinner("Building data table..."):
                generation_result = data_table_service.generate(
                    topic=topic,
                    row_count=row_count,
                    notes=notes,
                    settings=settings,
                )

            if generation_result.cache_hit:
                st.info("Data table served from cache. No API call made.")
            else:
                cache_count_placeholder.caption(f"Cached responses: {llm_service.count}")

            if generation_result.parse_note:
                st.info(generation_result.parse_note)

            if generation_result.parse_error:
                st.error(generation_result.parse_error)
                st.caption("Raw model response:")
                st.code(generation_result.raw_text)
            else:
                parsed = generation_result.parsed_table
                if not parsed:
                    st.error("Parsed table payload was empty.")
                    st.stop()
                assert parsed is not None
                parsed_payload = parsed
                parsed_columns = _table_columns(parsed_payload)
                parsed_rows = _table_rows(parsed_payload, columns=parsed_columns)
                if not parsed_columns or not parsed_rows:
                    st.error("Parsed table did not contain usable columns/rows.")
                    st.stop()
                st.session_state.data_table_topic = topic.strip()
                st.session_state.data_table_columns = parsed_columns
                st.session_state.data_table_rows = parsed_rows
                st.session_state.data_table_last_note = notes.strip()
                st.success("Data table generated successfully.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Request failed: {exc}")

    if not st.session_state.data_table_rows:
        return

    columns: list[str] = st.session_state.data_table_columns
    rows: list[dict[str, str]] = st.session_state.data_table_rows

    st.markdown("---")
    st.subheader("Generated Data Table")
    st.markdown(
        f'<div class="dt-meta">Topic: {escape(st.session_state.data_table_topic)}</div>',
        unsafe_allow_html=True,
    )

    kpi_cols = st.columns(3)
    kpi_cols[0].markdown(
        f'<div class="dt-kpi"><div class="dt-kpi-label">Rows</div><div class="dt-kpi-value">{len(rows)}</div></div>',
        unsafe_allow_html=True,
    )
    kpi_cols[1].markdown(
        f'<div class="dt-kpi"><div class="dt-kpi-label">Columns</div><div class="dt-kpi-value">{len(columns)}</div></div>',
        unsafe_allow_html=True,
    )
    kpi_cols[2].markdown(
        f'<div class="dt-kpi"><div class="dt-kpi-label">Subtype Column</div><div class="dt-kpi-value">{escape(columns[0])}</div></div>',
        unsafe_allow_html=True,
    )

    dataframe = pd.DataFrame(rows)
    dataframe = dataframe.reindex(columns=columns)
    st.dataframe(dataframe, width="stretch")

    download_col_1, download_col_2 = st.columns(2)

    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({col: row.get(col, "") for col in columns})

    json_payload = {
        "topic": st.session_state.data_table_topic,
        "columns": columns,
        "rows": rows,
    }

    with download_col_1:
        st.download_button(
            "Download CSV",
            data=csv_buffer.getvalue(),
            file_name="data_table.csv",
            mime="text/csv",
            key="download_data_table_csv",
            width="stretch",
        )

    with download_col_2:
        st.download_button(
            "Download JSON",
            data=json.dumps(json_payload, ensure_ascii=False, indent=2),
            file_name="data_table.json",
            mime="application/json",
            key="download_data_table_json",
            width="stretch",
        )
