from __future__ import annotations

from time import perf_counter

from main_app.services.report_export.models import (
    REPORT_TEMPLATES,
    ReportTemplateStyle,
    list_template_summaries,
    resolve_template,
)
from main_app.services.report_export.pdf_renderer import ReportPdfRenderer
from main_app.services.observability_service import ensure_request_id
from main_app.services.telemetry_service import ObservabilityEvent, TelemetryService


class ReportExportService:
    _TEMPLATES: tuple[ReportTemplateStyle, ...] = REPORT_TEMPLATES

    def __init__(self, *, telemetry_service: TelemetryService | None = None) -> None:
        self._telemetry_service = telemetry_service

    def list_templates(self) -> list[dict[str, str]]:
        return list_template_summaries()

    def build_pdf(
        self,
        *,
        topic: str,
        format_title: str,
        markdown_content: str,
        template_key: str,
    ) -> tuple[bytes | None, str | None]:
        request_id = ensure_request_id()
        started_at = perf_counter()
        if self._telemetry_service is not None:
            with self._telemetry_service.context_scope(request_id=request_id):
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="export.report.start",
                        component="export.report_pdf",
                        status="started",
                        timestamp=_now_iso(),
                        attributes={"template_key": template_key},
                    )
                )
        try:
            style = self._resolve_template(template_key)
            renderer = ReportPdfRenderer(style=style)
            content = renderer.build(
                topic=topic,
                format_title=format_title,
                markdown_content=markdown_content,
            )
            if self._telemetry_service is not None:
                duration_ms = max((perf_counter() - started_at) * 1000.0, 0.0)
                with self._telemetry_service.context_scope(request_id=request_id):
                    payload_ref = self._telemetry_service.attach_payload(
                        payload={
                            "topic": topic,
                            "format_title": format_title,
                            "template_key": template_key,
                            "markdown_chars": len(markdown_content),
                        },
                        kind="report_export",
                    )
                    self._telemetry_service.record_metric(
                        name="export_report_duration_ms",
                        value=duration_ms,
                        attrs={"template_key": template_key, "status": "ok"},
                    )
                    self._telemetry_service.record_metric(
                        name="export_report_bytes_total",
                        value=float(len(content)),
                        attrs={"template_key": template_key, "status": "ok"},
                    )
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="export.report.end",
                            component="export.report_pdf",
                            status="ok",
                            timestamp=_now_iso(),
                            attributes={
                                "template_key": template_key,
                                "duration_ms": round(duration_ms, 3),
                                "bytes": len(content),
                            },
                            payload_ref=payload_ref,
                        )
                    )
            return content, None
        except (ImportError, ModuleNotFoundError):
            return None, "reportlab is not installed. Install dependencies to enable report PDF export."
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as exc:
            if self._telemetry_service is not None:
                duration_ms = max((perf_counter() - started_at) * 1000.0, 0.0)
                with self._telemetry_service.context_scope(request_id=request_id):
                    self._telemetry_service.record_metric(
                        name="export_report_duration_ms",
                        value=duration_ms,
                        attrs={"template_key": template_key, "status": "error"},
                    )
                    self._telemetry_service.record_event(
                        ObservabilityEvent(
                            event_name="export.report.end",
                            component="export.report_pdf",
                            status="error",
                            timestamp=_now_iso(),
                            attributes={
                                "template_key": template_key,
                                "duration_ms": round(duration_ms, 3),
                                "error": str(exc),
                            },
                        )
                    )
            return None, f"Failed to generate report PDF: {exc}"

    @staticmethod
    def _resolve_template(template_key: str) -> ReportTemplateStyle:
        return resolve_template(template_key)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
