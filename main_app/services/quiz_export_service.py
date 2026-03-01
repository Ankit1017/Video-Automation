from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from time import perf_counter
from typing import Any
from typing import Iterator

from main_app.services.observability_service import ensure_request_id
from main_app.services.telemetry_service import ObservabilityEvent, TelemetryService

@dataclass(frozen=True)
class _QuizTemplateStyle:
    key: str
    title: str
    description: str
    page_background: tuple[int, int, int]
    accent: tuple[int, int, int]
    title_color: tuple[int, int, int]
    heading_color: tuple[int, int, int]
    body_color: tuple[int, int, int]
    option_background: tuple[int, int, int]
    answer_background: tuple[int, int, int]


class QuizExportService:
    _TEMPLATES: tuple[_QuizTemplateStyle, ...] = (
        _QuizTemplateStyle(
            key="clean_light",
            title="Clean Light",
            description="Classic clean exam-paper look.",
            page_background=(252, 253, 255),
            accent=(37, 99, 235),
            title_color=(15, 23, 42),
            heading_color=(30, 64, 175),
            body_color=(31, 41, 55),
            option_background=(245, 247, 255),
            answer_background=(235, 245, 255),
        ),
        _QuizTemplateStyle(
            key="academy_beige",
            title="Academy Beige",
            description="Warm printed-paper style for study handouts.",
            page_background=(255, 252, 245),
            accent=(180, 83, 9),
            title_color=(120, 53, 15),
            heading_color=(146, 64, 14),
            body_color=(68, 64, 60),
            option_background=(254, 248, 232),
            answer_background=(255, 243, 214),
        ),
        _QuizTemplateStyle(
            key="mint_modern",
            title="Mint Modern",
            description="Soft green modern worksheet style.",
            page_background=(244, 253, 248),
            accent=(22, 163, 74),
            title_color=(20, 83, 45),
            heading_color=(22, 101, 52),
            body_color=(31, 55, 43),
            option_background=(235, 249, 241),
            answer_background=(220, 252, 231),
        ),
        _QuizTemplateStyle(
            key="slate_tech",
            title="Slate Tech",
            description="Neutral slate style for technical assessments.",
            page_background=(248, 250, 252),
            accent=(71, 85, 105),
            title_color=(15, 23, 42),
            heading_color=(51, 65, 85),
            body_color=(30, 41, 59),
            option_background=(241, 245, 249),
            answer_background=(226, 232, 240),
        ),
    )

    def __init__(self, *, telemetry_service: TelemetryService | None = None) -> None:
        self._telemetry_service = telemetry_service

    def list_templates(self) -> list[dict[str, str]]:
        return [
            {
                "key": template.key,
                "title": template.title,
                "description": template.description,
            }
            for template in self._TEMPLATES
        ]

    def build_question_paper_pdf(
        self,
        *,
        topic: str,
        questions: list[dict[str, Any]],
        template_key: str,
    ) -> tuple[bytes | None, str | None]:
        request_id = ensure_request_id()
        started_at = perf_counter()
        context_scope = (
            self._telemetry_service.context_scope(request_id=request_id)
            if self._telemetry_service is not None
            else _null_context()
        )
        with context_scope:
            if self._telemetry_service is not None:
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="export.quiz.start",
                        component="export.quiz_pdf",
                        status="started",
                        timestamp=_now_iso(),
                        attributes={"template_key": template_key, "question_count": len(questions)},
                    )
                )
        try:
            from reportlab.lib import colors  # type: ignore
            from reportlab.lib.pagesizes import A4  # type: ignore
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # type: ignore
            from reportlab.lib.units import inch  # type: ignore
            from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # type: ignore
        except (ImportError, ModuleNotFoundError):
            return None, "reportlab is not installed. Install dependencies to enable quiz PDF export."

        try:
            style = self._resolve_template(template_key)
            normalized_questions = self._normalize_questions(questions)
            if not normalized_questions:
                return None, "No valid quiz questions available to export."

            color = lambda rgb: colors.Color(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)
            margin = 0.68 * inch
            output = BytesIO()
            document = SimpleDocTemplate(
                output,
                pagesize=A4,
                leftMargin=margin,
                rightMargin=margin,
                topMargin=0.9 * inch,
                bottomMargin=0.75 * inch,
                title=f"{topic.strip() or 'Quiz'} Question Paper",
                author="Knowledge App",
            )

            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                "QuizTitleStyle",
                parent=styles["Title"],
                fontName="Helvetica-Bold",
                fontSize=23,
                leading=30,
                textColor=color(style.title_color),
                spaceAfter=8,
            )
            section_style = ParagraphStyle(
                "QuizSectionStyle",
                parent=styles["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=14,
                leading=19,
                textColor=color(style.heading_color),
                spaceBefore=8,
                spaceAfter=6,
            )
            question_style = ParagraphStyle(
                "QuizQuestionStyle",
                parent=styles["BodyText"],
                fontName="Helvetica-Bold",
                fontSize=11.2,
                leading=15,
                textColor=color(style.body_color),
                spaceAfter=6,
            )
            option_style = ParagraphStyle(
                "QuizOptionStyle",
                parent=styles["BodyText"],
                fontName="Helvetica",
                fontSize=10.2,
                leading=14,
                textColor=color(style.body_color),
            )
            answer_style = ParagraphStyle(
                "QuizAnswerStyle",
                parent=styles["BodyText"],
                fontName="Helvetica",
                fontSize=10.6,
                leading=14.5,
                textColor=color(style.body_color),
            )
            meta_style = ParagraphStyle(
                "QuizMetaStyle",
                parent=styles["BodyText"],
                fontName="Helvetica",
                fontSize=10,
                leading=13,
                textColor=color(style.heading_color),
                spaceAfter=8,
            )

            story: list[Any] = []
            story.append(Paragraph(self._escape(topic.strip() or "Quiz"), title_style))
            story.append(Paragraph("Question Paper", section_style))
            story.append(Paragraph(f"Total Questions: {len(normalized_questions)}", meta_style))
            story.append(Spacer(1, 4))

            for index, question in enumerate(normalized_questions, start=1):
                question_text = self._escape(str(question["question"]))
                story.append(Paragraph(f"Q{index}. {question_text}", question_style))

                option_rows: list[list[Any]] = []
                for opt_idx, option in enumerate(question["options"]):
                    letter = chr(65 + opt_idx)
                    option_rows.append([Paragraph(f"{letter}. {self._escape(option)}", option_style)])

                options_table = Table(option_rows, colWidths=[document.width])
                options_table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), color(style.option_background)),
                            ("LEFTPADDING", (0, 0), (-1, -1), 8),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                            ("LINEABOVE", (0, 0), (-1, -1), 0.2, color(style.page_background)),
                            ("LINEBELOW", (0, 0), (-1, -1), 0.2, color(style.page_background)),
                        ]
                    )
                )
                story.append(options_table)
                story.append(Spacer(1, 10))

            story.append(PageBreak())
            story.append(Paragraph("Answer Key", title_style))
            story.append(Paragraph("Correct option for each question", meta_style))
            story.append(Spacer(1, 4))

            answer_rows: list[list[Any]] = []
            for index, question in enumerate(normalized_questions, start=1):
                correct_index = int(question["correct_index"])
                correct_letter = chr(65 + correct_index)
                correct_text = question["options"][correct_index] if question["options"] else ""
                answer_rows.append(
                    [
                        Paragraph(f"Q{index}", answer_style),
                        Paragraph(f"{correct_letter}. {self._escape(correct_text)}", answer_style),
                    ]
                )

            answer_table = Table(answer_rows, colWidths=[document.width * 0.16, document.width * 0.84])
            answer_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), color(style.answer_background)),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("LINEABOVE", (0, 0), (-1, -1), 0.25, color(style.page_background)),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.25, color(style.page_background)),
                    ]
                )
            )
            story.append(answer_table)

            def on_page(pdf_canvas: Any, doc: Any) -> None:
                self._draw_page_frame(
                    pdf_canvas=pdf_canvas,
                    doc=doc,
                    accent=color(style.accent),
                    heading_color=color(style.heading_color),
                    page_background=color(style.page_background),
                    template_title=style.title,
                )

            document.build(story, onFirstPage=on_page, onLaterPages=on_page)
            output_bytes = output.getvalue()
            if self._telemetry_service is not None:
                duration_ms = max((perf_counter() - started_at) * 1000.0, 0.0)
                payload_ref = self._telemetry_service.attach_payload(
                    payload={"topic": topic, "template_key": template_key, "question_count": len(normalized_questions)},
                    kind="quiz_export",
                )
                self._telemetry_service.record_metric(
                    name="export_quiz_duration_ms",
                    value=duration_ms,
                    attrs={"status": "ok", "template_key": template_key},
                )
                self._telemetry_service.record_metric(
                    name="export_quiz_bytes_total",
                    value=float(len(output_bytes)),
                    attrs={"status": "ok", "template_key": template_key},
                )
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="export.quiz.end",
                        component="export.quiz_pdf",
                        status="ok",
                        timestamp=_now_iso(),
                        attributes={
                            "template_key": template_key,
                            "duration_ms": round(duration_ms, 3),
                            "bytes": len(output_bytes),
                        },
                        payload_ref=payload_ref,
                    )
                )
            return output_bytes, None
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            if self._telemetry_service is not None:
                duration_ms = max((perf_counter() - started_at) * 1000.0, 0.0)
                self._telemetry_service.record_metric(
                    name="export_quiz_duration_ms",
                    value=duration_ms,
                    attrs={"status": "error", "template_key": template_key},
                )
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="export.quiz.end",
                        component="export.quiz_pdf",
                        status="error",
                        timestamp=_now_iso(),
                        attributes={
                            "template_key": template_key,
                            "duration_ms": round(duration_ms, 3),
                            "error": str(exc),
                        },
                    )
                )
            return None, f"Failed to generate quiz PDF: {exc}"

    def _resolve_template(self, template_key: str) -> _QuizTemplateStyle:
        key = " ".join(str(template_key).split()).strip().lower()
        for template in self._TEMPLATES:
            if template.key == key:
                return template
        return self._TEMPLATES[0]

    @staticmethod
    def _normalize_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in questions:
            if not isinstance(item, dict):
                continue
            question_text = " ".join(str(item.get("question", "")).split()).strip()
            raw_options = item.get("options", [])
            if not isinstance(raw_options, list):
                continue
            options = [" ".join(str(option).split()).strip() for option in raw_options if " ".join(str(option).split()).strip()]
            if not question_text or len(options) < 2:
                continue
            try:
                correct_index = int(item.get("correct_index", item.get("correct_option_index", 0)))
            except (TypeError, ValueError):
                correct_index = 0
            correct_index = max(0, min(correct_index, len(options) - 1))
            normalized.append(
                {
                    "question": question_text,
                    "options": options,
                    "correct_index": correct_index,
                }
            )
        return normalized

    @staticmethod
    def _draw_page_frame(
        *,
        pdf_canvas: Any,
        doc: Any,
        accent: Any,
        heading_color: Any,
        page_background: Any,
        template_title: str,
    ) -> None:
        width, height = doc.pagesize
        pdf_canvas.saveState()
        pdf_canvas.setFillColor(page_background)
        pdf_canvas.rect(0, 0, width, height, fill=1, stroke=0)
        pdf_canvas.setFillColor(accent)
        pdf_canvas.rect(0, height - 14, width, 14, fill=1, stroke=0)
        pdf_canvas.setStrokeColor(heading_color)
        pdf_canvas.setLineWidth(0.65)
        pdf_canvas.line(doc.leftMargin, height - 33, width - doc.rightMargin, height - 33)
        pdf_canvas.setFillColor(heading_color)
        pdf_canvas.setFont("Helvetica", 8.4)
        pdf_canvas.drawString(doc.leftMargin, 18, template_title)
        pdf_canvas.drawRightString(width - doc.rightMargin, 18, f"Page {doc.page}")
        pdf_canvas.restoreState()

    @staticmethod
    def _escape(value: str) -> str:
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def _null_context() -> Iterator[None]:
    yield
