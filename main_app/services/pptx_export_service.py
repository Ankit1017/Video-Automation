from __future__ import annotations

from typing import Any

from main_app.services.pptx_export.design_tokens import apply_design_tokens
from main_app.services.pptx_export.models import PptxTemplateStyle
from main_app.services.pptx_export.pdf_builder import PdfDeckBuilder
from main_app.services.pptx_export.pptx_builder import PptxDeckBuilder
from main_app.services.pptx_export.templates import PPTX_TEMPLATES, list_template_summaries, resolve_template
from main_app.services.pptx_export.text_utils import (
    normalize_text,
    prepare_code_payload,
    split_line_for_slide,
    trim_code_for_slide,
)


class PptxExportService:
    _TEMPLATES: tuple[PptxTemplateStyle, ...] = PPTX_TEMPLATES

    def list_templates(self) -> list[dict[str, str]]:
        return list_template_summaries()

    def build_pptx(
        self,
        *,
        topic: str,
        slides: list[dict[str, Any]],
        template_key: str,
    ) -> tuple[bytes | None, str | None]:
        try:
            style = apply_design_tokens(self._resolve_template(template_key))
            builder = PptxDeckBuilder(style=style)
            return builder.build(topic=topic, slides=slides)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return None, f"Failed to generate PPTX: {exc}"

    def build_pdf(
        self,
        *,
        topic: str,
        slides: list[dict[str, Any]],
        template_key: str,
    ) -> tuple[bytes | None, str | None]:
        try:
            style = apply_design_tokens(self._resolve_template(template_key))
            builder = PdfDeckBuilder(style=style)
            return builder.build(topic=topic, slides=slides)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return None, f"Failed to generate PDF: {exc}"

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return normalize_text(value)

    def _resolve_template(self, template_key: str) -> PptxTemplateStyle:
        return resolve_template(template_key)

    @staticmethod
    def _trim_code_for_slide(code_snippet: str) -> list[str]:
        return trim_code_for_slide(code_snippet)

    @staticmethod
    def _split_line_for_slide(*, line: str, max_chars: int) -> list[str]:
        return split_line_for_slide(line=line, max_chars=max_chars)

    def _prepare_code_payload(self, *, code_snippet: str, code_language: str) -> tuple[str, str]:
        return prepare_code_payload(code_snippet=code_snippet, code_language=code_language)
