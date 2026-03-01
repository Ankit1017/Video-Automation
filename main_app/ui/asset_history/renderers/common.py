from __future__ import annotations

import csv
import io
import json
import re
from typing import Any, cast

import streamlit as st

from main_app.domains.topic.renderer.topic_render_model import extract_topic_markdown
from main_app.models import AssetHistoryRecord
from main_app.parsers.markdown_utils import normalize_markdown_text
from main_app.ui.asset_history.context import AssetHistoryRenderContext
from main_app.ui.components import ReportRenderConfig, render_report_view


def _as_payload_map(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _as_dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            items.append({str(key): entry for key, entry in item.items()})
    return items


def _as_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def render_topic_record(record: AssetHistoryRecord, context: AssetHistoryRenderContext) -> None:
    del context
    payload = _as_payload_map(record.result_payload)
    artifact_raw = payload.get("artifact")
    artifact = cast(dict[str, Any] | None, artifact_raw if isinstance(artifact_raw, dict) else None)
    st.subheader("Detailed Description")
    st.markdown(
        extract_topic_markdown(
            content=payload.get("content"),
            result_payload=payload,
            artifact=artifact,
        )
    )


def render_report_record(record: AssetHistoryRecord, context: AssetHistoryRenderContext) -> None:
    payload = _as_payload_map(record.result_payload)
    normalized_content = normalize_markdown_text(str(payload.get("content", "")))
    format_title = str(record.request_payload.get("format_title", "Report")).strip() or "Report"
    st.subheader("Generated Report")
    render_report_view(
        topic=record.topic or "Report",
        format_title=format_title,
        markdown_content=normalized_content,
        config=ReportRenderConfig(
            template_select_key=f"asset_history_report_template_{record.id}",
            download_md_key=f"asset_history_report_download_md_{record.id}",
            download_pdf_key=f"asset_history_report_download_pdf_{record.id}",
            download_pdf_disabled_key=f"asset_history_report_download_pdf_disabled_{record.id}",
        ),
        report_exporter=context.report_exporter,
    )


def render_data_table_record(record: AssetHistoryRecord, context: AssetHistoryRenderContext) -> None:
    del context
    import pandas as pd

    payload = _as_payload_map(record.result_payload)
    columns = _as_string_list(payload.get("columns", []))
    rows = _as_dict_list(payload.get("rows", []))
    if not columns or not rows:
        st.json(record.result_payload)
        return

    st.subheader("Generated Data Table")
    dataframe = pd.DataFrame(rows)
    dataframe = dataframe.reindex(columns=columns)
    st.dataframe(dataframe, width="stretch")

    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        if isinstance(row, dict):
            writer.writerow({col: row.get(col, "") for col in columns})

    safe_topic = re.sub(r"[^a-zA-Z0-9_-]+", "_", record.topic.strip())[:60].strip("_") or "data_table"
    dl_col_1, dl_col_2 = st.columns(2)
    with dl_col_1:
        st.download_button(
            "Download CSV",
            data=csv_buffer.getvalue(),
            file_name=f"{safe_topic}.csv",
            mime="text/csv",
            key=f"asset_history_data_table_csv_{record.id}",
            width="stretch",
        )
    with dl_col_2:
        st.download_button(
            "Download JSON",
            data=json.dumps(payload, ensure_ascii=False, indent=2),
            file_name=f"{safe_topic}.json",
            mime="application/json",
            key=f"asset_history_data_table_json_{record.id}",
            width="stretch",
        )


def render_default_record(record: AssetHistoryRecord, context: AssetHistoryRenderContext) -> None:
    del context
    payload = _as_payload_map(record.result_payload)
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        provenance = artifact.get("provenance")
        if isinstance(provenance, dict):
            verification = provenance.get("verification")
            if isinstance(verification, dict):
                verify_status = " ".join(str(verification.get("status", "")).split()).strip().lower()
                if verify_status:
                    if verify_status == "passed":
                        st.success("Verification: passed")
                    else:
                        st.error("Verification: failed")
                issues = verification.get("issues")
                issue_items = _as_dict_list(issues)
                if issue_items:
                    st.caption("Verification issues")
                    st.table(
                        [
                            {
                                "code": str(issue.get("code", "")),
                                "severity": str(issue.get("severity", "")),
                                "path": str(issue.get("path", "")),
                                "message": str(issue.get("message", "")),
                            }
                            for issue in issue_items
                        ]
                    )
        sections = artifact.get("sections")
        if isinstance(sections, list) and sections:
            for section in sections:
                if not isinstance(section, dict):
                    continue
                title = " ".join(str(section.get("title", "")).split()).strip() or "Section"
                st.markdown(f"**{title}**")
                data = section.get("data")
                if isinstance(data, (dict, list)):
                    st.json(data)
                else:
                    st.write(data)
            return
    st.json(record.result_payload)
