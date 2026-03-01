from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any
import unicodedata

from main_app.services.pptx_export.asset_loader import discover_font_files
from main_app.services.pptx_export.layout_planner import plan_slide_layout
from main_app.services.pptx_export.models import LayoutPlan, PptxTemplateStyle
from main_app.services.pptx_export.text_utils import normalize_text, split_line_for_slide, trim_code_for_slide


class PdfDeckBuilder:
    def __init__(self, *, style: PptxTemplateStyle) -> None:
        self._style = style
        self._font_map: dict[str, str] = {
            "regular": "Helvetica",
            "bold": "Helvetica-Bold",
            "code": "Courier",
        }

    def build(self, *, topic: str, slides: list[dict[str, Any]]) -> tuple[bytes | None, str | None]:
        try:
            from reportlab.pdfgen import canvas  # type: ignore
            from reportlab.pdfbase import pdfmetrics  # type: ignore
            from reportlab.pdfbase.ttfonts import TTFont  # type: ignore
        except Exception:
            return None, "reportlab is not installed. Install dependencies to enable PDF export."

        self._register_brand_fonts(pdfmetrics=pdfmetrics, TTFont=TTFont)

        page_width = 960.0
        page_height = 540.0
        output = BytesIO()
        pdf = canvas.Canvas(output, pagesize=(page_width, page_height))

        self._add_pdf_title_slide(
            pdf=pdf,
            topic=topic,
            page_width=page_width,
            page_height=page_height,
        )
        for item in slides:
            plan = plan_slide_layout(slide=item if isinstance(item, dict) else {})
            self._add_pdf_content_slide(
                pdf=pdf,
                plan=plan,
                page_width=page_width,
                page_height=page_height,
            )
        pdf.save()
        return output.getvalue(), None

    def _register_brand_fonts(self, *, pdfmetrics: Any, TTFont: Any) -> None:
        fonts = discover_font_files()
        if not fonts:
            return

        registration_plan = [
            ("BrandRegular", fonts.get("regular", "")),
            ("BrandBold", fonts.get("bold", "")),
            ("BrandCode", fonts.get("mono", "")),
        ]
        for alias, font_path in registration_plan:
            path = Path(str(font_path).strip())
            if not str(path).strip() or not path.is_file():
                continue
            try:
                pdfmetrics.registerFont(TTFont(alias, str(path)))
            except Exception:
                continue

        if "BrandRegular" in pdfmetrics.getRegisteredFontNames():
            self._font_map["regular"] = "BrandRegular"
        if "BrandBold" in pdfmetrics.getRegisteredFontNames():
            self._font_map["bold"] = "BrandBold"
        if "BrandCode" in pdfmetrics.getRegisteredFontNames():
            self._font_map["code"] = "BrandCode"

    def _layout(self, key: str, fallback: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        candidate = self._style.layout_presets.get(key)
        if (
            isinstance(candidate, tuple)
            and len(candidate) == 4
            and all(isinstance(item, (int, float)) for item in candidate)
        ):
            return float(candidate[0]), float(candidate[1]), float(candidate[2]), float(candidate[3])
        return fallback

    @staticmethod
    def _set_pdf_fill_color(pdf: Any, color: tuple[int, int, int]) -> None:
        pdf.setFillColorRGB(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)

    @staticmethod
    def _set_pdf_stroke_color(pdf: Any, color: tuple[int, int, int]) -> None:
        pdf.setStrokeColorRGB(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)

    def _add_pdf_title_slide(
        self,
        *,
        pdf: Any,
        topic: str,
        page_width: float,
        page_height: float,
    ) -> None:
        self._draw_pdf_background(
            pdf=pdf,
            page_width=page_width,
            page_height=page_height,
        )

        safe_topic = self._to_pdf_safe_text(normalize_text(topic) or "Slide Deck")
        topic_lines = self._wrap_pdf_text(
            pdf=pdf,
            text=safe_topic,
            font_name=self._font_map["bold"],
            font_size=self._fit_title_font_size(normalize_text(topic)),
            max_width=page_width - 100.0,
            max_lines=3,
        )
        title_size = self._fit_title_font_size(normalize_text(topic))
        title_y = page_height - 145.0
        self._set_pdf_fill_color(pdf, self._style.title_color)
        pdf.setFont(self._font_map["bold"], title_size)
        for line in topic_lines:
            pdf.drawString(50.0, title_y, line)
            title_y -= max(42.0, float(title_size + 8))

        self._set_pdf_fill_color(pdf, self._style.body_color)
        pdf.setFont(self._font_map["regular"], self._style.typography.subtitle_size)
        pdf.drawString(50.0, 110.0, self._to_pdf_safe_text(self._style.branding.footer_text))

        if self._style.branding.show_title_logo:
            lx, ly, lw, lh = self._layout("title_logo_box", (10.55, 0.34, 1.65, 0.65))
            self._draw_pdf_logo(
                pdf=pdf,
                logo_path=self._style.branding.logo_path,
                x=lx * 72.0,
                y=page_height - ((ly + lh) * 72.0),
                width=lw * 72.0,
                height=lh * 72.0,
            )
        pdf.showPage()

    def _add_pdf_content_slide(
        self,
        *,
        pdf: Any,
        plan: LayoutPlan,
        page_width: float,
        page_height: float,
    ) -> None:
        self._draw_pdf_background(
            pdf=pdf,
            page_width=page_width,
            page_height=page_height,
        )

        if plan.section:
            safe_section = self._to_pdf_safe_text(plan.section[:36])
            chip_height = 28.0
            chip_width = min(
                260.0,
                max(120.0, pdf.stringWidth(safe_section, self._font_map["bold"], 12) + 26.0),
            )
            chip_x = page_width - chip_width - 34.0
            chip_y = page_height - 52.0
            self._set_pdf_fill_color(pdf, self._style.section_chip_color)
            self._set_pdf_stroke_color(pdf, self._style.section_chip_color)
            pdf.roundRect(chip_x, chip_y, chip_width, chip_height, 8.0, fill=1, stroke=0)
            self._set_pdf_fill_color(pdf, self._style.section_chip_text_color)
            pdf.setFont(self._font_map["bold"], 12)
            pdf.drawString(chip_x + 12.0, chip_y + 9.0, safe_section)

        title_size = self._fit_title_font_size(plan.title)
        title_lines = self._wrap_pdf_text(
            pdf=pdf,
            text=self._to_pdf_safe_text(plan.title),
            font_name=self._font_map["bold"],
            font_size=title_size,
            max_width=page_width - 80.0,
            max_lines=2,
        )
        self._set_pdf_fill_color(pdf, self._style.title_color)
        pdf.setFont(self._font_map["bold"], title_size)
        title_y = page_height - 86.0
        for line in title_lines:
            pdf.drawString(36.0, title_y, line)
            title_y -= max(26.0, float(title_size + 6))

        content_top = page_height - 160.0
        content_bottom = 54.0

        if plan.layout_type == "split_code" and plan.code_snippet:
            self._draw_pdf_bullets(
                pdf=pdf,
                bullets=plan.bullets[:6],
                x=38.0,
                y_top=content_top,
                width=418.0,
                y_bottom=content_bottom,
                font_size=max(13, self._style.typography.body_size - 2),
            )
            self._draw_pdf_code_panel(
                pdf=pdf,
                code_snippet=plan.code_snippet,
                code_language=plan.code_language,
                x=475.0,
                y_top=content_top,
                width=448.0,
                height=content_top - content_bottom,
            )
        elif plan.layout_type == "dual_column":
            self._draw_pdf_two_column(
                pdf=pdf,
                left_title=plan.left_title or "Left",
                left_items=plan.left_items or ["No content provided."],
                right_title=plan.right_title or "Right",
                right_items=plan.right_items or ["No content provided."],
                y_top=content_top,
                y_bottom=content_bottom,
            )
        elif plan.layout_type == "timeline":
            self._draw_pdf_timeline(
                pdf=pdf,
                events=plan.events,
                y_top=content_top,
                y_bottom=content_bottom,
            )
        elif plan.layout_type == "process_flow":
            self._draw_pdf_process_flow(
                pdf=pdf,
                steps=plan.steps,
                y_top=content_top,
                y_bottom=content_bottom,
            )
        elif plan.layout_type == "metric_cards":
            self._draw_pdf_metric_cards(
                pdf=pdf,
                cards=plan.cards,
                y_top=content_top,
            )
        else:
            self._draw_pdf_bullets(
                pdf=pdf,
                bullets=plan.bullets,
                x=40.0,
                y_top=content_top,
                width=880.0,
                y_bottom=content_bottom,
                font_size=max(14, self._style.typography.body_size - 1),
            )

        self._draw_pdf_footer(pdf=pdf, page_height=page_height)
        pdf.showPage()

    def _draw_pdf_footer(self, *, pdf: Any, page_height: float) -> None:
        self._set_pdf_fill_color(pdf, self._style.body_color)
        pdf.setFont(self._font_map["regular"], max(9, self._style.typography.caption_size))
        pdf.drawString(40.0, 20.0, self._to_pdf_safe_text(self._style.branding.footer_text))
        if self._style.branding.show_footer_logo:
            self._draw_pdf_logo(
                pdf=pdf,
                logo_path=self._style.branding.footer_logo_path or self._style.branding.logo_path,
                x=840.0,
                y=14.0,
                width=90.0,
                height=22.0,
            )

    def _draw_pdf_logo(
        self,
        *,
        pdf: Any,
        logo_path: str,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        path = Path(str(logo_path).strip())
        if not str(path).strip() or not path.is_file():
            return
        try:
            pdf.drawImage(
                str(path),
                x,
                y,
                width=width,
                height=height,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            return

    def _draw_pdf_two_column(
        self,
        *,
        pdf: Any,
        left_title: str,
        left_items: list[str],
        right_title: str,
        right_items: list[str],
        y_top: float,
        y_bottom: float,
    ) -> None:
        self._set_pdf_fill_color(pdf, self._style.title_color)
        pdf.setFont(self._font_map["bold"], max(13, self._style.typography.body_size - 2))
        pdf.drawString(42.0, y_top + 6.0, self._to_pdf_safe_text(normalize_text(left_title) or "Left"))
        pdf.drawString(490.0, y_top + 6.0, self._to_pdf_safe_text(normalize_text(right_title) or "Right"))
        self._draw_pdf_bullets(
            pdf=pdf,
            bullets=left_items[:4],
            x=40.0,
            y_top=y_top - 20.0,
            width=400.0,
            y_bottom=y_bottom,
            font_size=max(12, self._style.typography.body_size - 4),
        )
        self._draw_pdf_bullets(
            pdf=pdf,
            bullets=right_items[:4],
            x=490.0,
            y_top=y_top - 20.0,
            width=430.0,
            y_bottom=y_bottom,
            font_size=max(12, self._style.typography.body_size - 4),
        )

    def _draw_pdf_timeline(
        self,
        *,
        pdf: Any,
        events: list[dict[str, str]],
        y_top: float,
        y_bottom: float,
    ) -> None:
        rows = events[:5] if events else [{"label": "Milestone", "detail": "No timeline events provided."}]
        y = y_top - 8.0
        for event in rows:
            if y < y_bottom + 24.0:
                break
            label = normalize_text(event.get("label", "")) or "Milestone"
            detail = normalize_text(event.get("detail", ""))
            self._set_pdf_fill_color(pdf, self._style.accent_color)
            pdf.circle(48.0, y + 4.0, 3.0, fill=1, stroke=0)
            self._set_pdf_fill_color(pdf, self._style.title_color)
            pdf.setFont(self._font_map["bold"], max(12, self._style.typography.body_size - 5))
            pdf.drawString(60.0, y, self._to_pdf_safe_text(label))
            if detail:
                self._set_pdf_fill_color(pdf, self._style.body_color)
                pdf.setFont(self._font_map["regular"], max(11, self._style.typography.body_size - 7))
                wrapped = self._wrap_pdf_text(
                    pdf=pdf,
                    text=self._to_pdf_safe_text(detail),
                    font_name=self._font_map["regular"],
                    font_size=max(11, self._style.typography.body_size - 7),
                    max_width=840.0,
                    max_lines=2,
                )
                current = y - 14.0
                for line in wrapped:
                    pdf.drawString(60.0, current, line)
                    current -= 14.0
                y = current - 8.0
            else:
                y -= 24.0

    def _draw_pdf_process_flow(
        self,
        *,
        pdf: Any,
        steps: list[dict[str, str]],
        y_top: float,
        y_bottom: float,
    ) -> None:
        rows = steps[:5] if steps else [{"title": "Step 1", "detail": "No process steps provided."}]
        y = y_top - 10.0
        box_height = 62.0
        for idx, step in enumerate(rows, start=1):
            if y - box_height < y_bottom:
                break
            title = normalize_text(step.get("title", "")) or f"Step {idx}"
            detail = normalize_text(step.get("detail", ""))
            self._set_pdf_fill_color(pdf, self._style.section_chip_color)
            self._set_pdf_stroke_color(pdf, self._style.section_chip_color)
            pdf.roundRect(40.0, y - box_height, 880.0, box_height, 8.0, fill=1, stroke=0)
            self._set_pdf_fill_color(pdf, self._style.section_chip_text_color)
            pdf.setFont(self._font_map["bold"], max(11, self._style.typography.body_size - 6))
            pdf.drawString(54.0, y - 22.0, self._to_pdf_safe_text(f"{idx}. {title}"))
            if detail:
                pdf.setFont(self._font_map["regular"], max(10, self._style.typography.body_size - 8))
                wrapped = self._wrap_pdf_text(
                    pdf=pdf,
                    text=self._to_pdf_safe_text(detail),
                    font_name=self._font_map["regular"],
                    font_size=max(10, self._style.typography.body_size - 8),
                    max_width=852.0,
                    max_lines=2,
                )
                current_y = y - 38.0
                for line in wrapped:
                    pdf.drawString(54.0, current_y, line)
                    current_y -= 12.0
            y -= box_height + 10.0

    def _draw_pdf_metric_cards(
        self,
        *,
        pdf: Any,
        cards: list[dict[str, str]],
        y_top: float,
    ) -> None:
        rows = cards[:4] if cards else [{"label": "Metric", "value": "No metric cards provided.", "context": ""}]
        positions = [
            (40.0, y_top - 174.0),
            (500.0, y_top - 174.0),
            (40.0, y_top - 366.0),
            (500.0, y_top - 366.0),
        ]
        for idx, card in enumerate(rows[:4]):
            x, y = positions[idx]
            label = normalize_text(card.get("label", "")) or "Metric"
            value = normalize_text(card.get("value", "")) or "-"
            context = normalize_text(card.get("context", ""))
            self._set_pdf_fill_color(pdf, self._style.section_chip_color)
            self._set_pdf_stroke_color(pdf, self._style.section_chip_color)
            pdf.roundRect(x, y, 420.0, 160.0, 10.0, fill=1, stroke=0)
            self._set_pdf_fill_color(pdf, self._style.section_chip_text_color)
            pdf.setFont(self._font_map["bold"], max(10, self._style.typography.caption_size))
            pdf.drawString(x + 12.0, y + 138.0, self._to_pdf_safe_text(label))
            pdf.setFont(self._font_map["bold"], max(16, self._style.typography.body_size))
            value_wrapped = self._wrap_pdf_text(
                pdf=pdf,
                text=self._to_pdf_safe_text(value),
                font_name=self._font_map["bold"],
                font_size=max(16, self._style.typography.body_size),
                max_width=396.0,
                max_lines=2,
            )
            current_y = y + 108.0
            for line in value_wrapped:
                pdf.drawString(x + 12.0, current_y, line)
                current_y -= 24.0
            if context:
                pdf.setFont(self._font_map["regular"], max(9, self._style.typography.caption_size - 1))
                pdf.drawString(x + 12.0, y + 18.0, self._to_pdf_safe_text(context[:72]))

    def _draw_pdf_background(
        self,
        *,
        pdf: Any,
        page_width: float,
        page_height: float,
    ) -> None:
        self._set_pdf_fill_color(pdf, self._style.background_color)
        self._set_pdf_stroke_color(pdf, self._style.background_color)
        pdf.rect(0.0, 0.0, page_width, page_height, fill=1, stroke=0)
        self._set_pdf_fill_color(pdf, self._style.accent_color)
        self._set_pdf_stroke_color(pdf, self._style.accent_color)
        bar_height = max(8.0, float(self._style.shapes.accent_bar_height_in * 72.0))
        pdf.rect(0.0, page_height - bar_height, page_width, bar_height, fill=1, stroke=0)

    def _draw_pdf_bullets(
        self,
        *,
        pdf: Any,
        bullets: list[str],
        x: float,
        y_top: float,
        width: float,
        y_bottom: float,
        font_size: int,
    ) -> None:
        y = y_top
        line_height = font_size + 5
        bullet_indent = 18.0
        self._set_pdf_fill_color(pdf, self._style.body_color)
        pdf.setFont(self._font_map["regular"], font_size)

        for bullet in bullets[:6]:
            wrapped = self._wrap_pdf_text(
                pdf=pdf,
                text=self._to_pdf_safe_text(bullet),
                font_name=self._font_map["regular"],
                font_size=font_size,
                max_width=width - bullet_indent,
                max_lines=4,
            )
            if not wrapped:
                continue
            needed_height = len(wrapped) * line_height + 7.0
            if y - needed_height < y_bottom:
                break
            pdf.drawString(x, y, "-")
            pdf.drawString(x + bullet_indent, y, wrapped[0])
            y -= line_height
            for continuation in wrapped[1:]:
                pdf.drawString(x + bullet_indent, y, continuation)
                y -= line_height
            y -= 7.0

    def _draw_pdf_code_panel(
        self,
        *,
        pdf: Any,
        code_snippet: str,
        code_language: str,
        x: float,
        y_top: float,
        width: float,
        height: float,
    ) -> None:
        y = y_top - height
        self._set_pdf_fill_color(pdf, self._style.code_panel_color)
        self._set_pdf_stroke_color(pdf, self._style.code_panel_color)
        pdf.roundRect(x, y, width, height, 10.0, fill=1, stroke=0)

        inner_x = x + 14.0
        header_y = y_top - 22.0
        self._set_pdf_fill_color(pdf, self._style.code_text_color)
        pdf.setFont(self._font_map["bold"], 12)
        pdf.drawString(inner_x, header_y, self._to_pdf_safe_text(f"Code ({code_language.lower()})"))

        code_lines = trim_code_for_slide(code_snippet)
        code_font_size = max(9, self._style.typography.code_size - 2)
        pdf.setFont(self._font_map["code"], code_font_size)
        char_width = max(pdf.stringWidth("M", self._font_map["code"], code_font_size), 5.0)
        max_chars = max(18, int((width - 28.0) / char_width))
        max_lines = max(6, int((height - 44.0) / (code_font_size + 2)))
        fitted_lines: list[str] = []
        for line in code_lines:
            for split_line in split_line_for_slide(line=line, max_chars=max_chars):
                if len(fitted_lines) >= max_lines:
                    break
                fitted_lines.append(split_line)
            if len(fitted_lines) >= max_lines:
                break
        if len(fitted_lines) == max_lines and fitted_lines:
            fitted_lines[-1] = (
                fitted_lines[-1][: max_chars - 3] + "..."
                if len(fitted_lines[-1]) > max_chars - 3
                else fitted_lines[-1] + "..."
            )

        current_y = header_y - 16.0
        for line in fitted_lines:
            if current_y < y + 12.0:
                break
            pdf.drawString(inner_x, current_y, self._to_pdf_safe_text(line, preserve_spacing=True))
            current_y -= code_font_size + 2.0

    def _wrap_pdf_text(
        self,
        *,
        pdf: Any,
        text: str,
        font_name: str,
        font_size: int,
        max_width: float,
        max_lines: int | None,
    ) -> list[str]:
        words = self._to_pdf_safe_text(text).split()
        if not words:
            return []

        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if pdf.stringWidth(candidate, font_name, font_size) <= max_width:
                current = candidate
                continue
            lines.append(current)
            current = word
            if max_lines is not None and len(lines) >= max_lines:
                break
        if max_lines is None or len(lines) < max_lines:
            lines.append(current)
        if max_lines is not None and len(lines) > max_lines:
            lines = lines[:max_lines]
        if max_lines is not None and len(lines) == max_lines:
            lines[-1] = self._truncate_pdf_line(
                pdf=pdf,
                text=lines[-1],
                font_name=font_name,
                font_size=font_size,
                max_width=max_width,
            )
        return lines

    @staticmethod
    def _truncate_pdf_line(
        *,
        pdf: Any,
        text: str,
        font_name: str,
        font_size: int,
        max_width: float,
    ) -> str:
        candidate = text
        suffix = "..."
        while candidate and pdf.stringWidth(candidate + suffix, font_name, font_size) > max_width:
            candidate = candidate[:-1]
        return (candidate + suffix) if candidate else suffix

    def _fit_title_font_size(self, title: str) -> int:
        base = max(26, int(self._style.typography.title_size))
        length = len(str(title))
        if length > 130:
            return max(24, base - 8)
        if length > 100:
            return max(26, base - 6)
        if length > 80:
            return max(28, base - 4)
        if length > 60:
            return max(30, base - 2)
        return base

    @staticmethod
    def _to_pdf_safe_text(value: Any, *, preserve_spacing: bool = False) -> str:
        text = str(value or "")
        text = unicodedata.normalize("NFKC", text)
        replacements = {
            "\u2022": "-",
            "\u2013": "-",
            "\u2014": "-",
            "\u2212": "-",
            "\u2018": "'",
            "\u2019": "'",
            "\u201c": '"',
            "\u201d": '"',
            "\u2026": "...",
            "\u00e2\u20ac\u00a2": "-",   # mojibake bullet
            "\u00e2\u20ac\u201c": "-",   # mojibake en dash
            "\u00e2\u20ac\u201d": "-",   # mojibake em dash
            "\u00e2\u20ac\u02dc": "'",   # mojibake left single quote
            "\u00e2\u20ac\u2122": "'",   # mojibake right single quote
            "\u00e2\u20ac\u0153": '"',   # mojibake left double quote
            "\u00e2\u20ac\ufffd": '"',   # mojibake right double quote
            "\u00e2\u20ac\u00a6": "...", # mojibake ellipsis
            "\ufb00": "ff",
            "\ufb01": "fi",
            "\ufb02": "fl",
            "\ufb03": "ffi",
            "\ufb04": "ffl",
            "\u25a0": "",
            "\u25aa": "",
            "\u25ab": "",
            "\u00a0": " ",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)

        normalized = unicodedata.normalize("NFKD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        cleaned = "".join(ch for ch in ascii_text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
        if preserve_spacing:
            return cleaned
        return " ".join(cleaned.split()).strip()
