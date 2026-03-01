from __future__ import annotations

import re
from typing import Any


class ReportMarkdownRenderer:
    def render_to_flowables(
        self,
        *,
        markdown_text: str,
        body_style: Any,
        heading_styles: dict[int, Any],
        code_style: Any,
        code_label_style: Any,
        code_background: Any,
        max_content_width: float,
        Paragraph: Any,
        Preformatted: Any,
        Spacer: Any,
        Table: Any,
        TableStyle: Any,
    ) -> list[Any]:
        lines = str(markdown_text or "").splitlines()
        flowables: list[Any] = []

        paragraph_parts: list[str] = []
        code_lines: list[str] = []
        code_language = "text"
        in_code_block = False

        def flush_paragraph() -> None:
            if not paragraph_parts:
                return
            paragraph_text = " ".join(part.strip() for part in paragraph_parts if part.strip())
            paragraph_parts.clear()
            if paragraph_text:
                flowables.append(Paragraph(self.escape_inline_markup(paragraph_text), body_style))

        def flush_code_block() -> None:
            nonlocal code_lines, code_language
            if not code_lines:
                flowables.append(Spacer(1, 4))
                code_language = "text"
                return
            trimmed = self.trim_code_lines(code_lines, max_lines=200, max_chars=140)
            code_panel_content = [
                Paragraph(f"Code ({self.escape_inline_markup(code_language.lower())})", code_label_style),
                Preformatted("\n".join(trimmed), code_style),
            ]
            code_table = Table(
                [code_panel_content],
                colWidths=[max_content_width],
            )
            code_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), code_background),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                        ("LINEBELOW", (0, 0), (-1, 0), 0.2, code_background),
                    ]
                )
            )
            flowables.append(code_table)
            flowables.append(Spacer(1, 8))
            code_lines = []
            code_language = "text"

        index = 0
        while index < len(lines):
            raw_line = lines[index]
            line = raw_line.rstrip("\n")
            stripped = line.strip()

            if in_code_block:
                if stripped.startswith("```"):
                    in_code_block = False
                    flush_code_block()
                else:
                    code_lines.append(line.rstrip("\r"))
                index += 1
                continue

            if stripped.startswith("```"):
                flush_paragraph()
                in_code_block = True
                code_language = stripped[3:].strip() or "text"
                code_lines = []
                index += 1
                continue

            heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading_match:
                flush_paragraph()
                level = min(len(heading_match.group(1)), 4)
                heading_text = heading_match.group(2).strip()
                if heading_text:
                    flowables.append(
                        Paragraph(
                            self.escape_inline_markup(heading_text),
                            heading_styles.get(level, heading_styles[4]),
                        )
                    )
                index += 1
                continue

            if re.match(r"^([-_*])\1{2,}$", stripped):
                flush_paragraph()
                flowables.append(Spacer(1, 8))
                index += 1
                continue

            bullet_match = re.match(r"^[-*+]\s+(.+)$", stripped)
            numbered_match = re.match(r"^\d+\.\s+(.+)$", stripped)
            if bullet_match or numbered_match:
                flush_paragraph()
                list_items: list[str] = []
                while index < len(lines):
                    current = lines[index].strip()
                    matched_bullet = re.match(r"^[-*+]\s+(.+)$", current)
                    matched_number = re.match(r"^\d+\.\s+(.+)$", current)
                    if not matched_bullet and not matched_number:
                        break
                    if matched_bullet is not None:
                        item_text = matched_bullet.group(1)
                    elif matched_number is not None:
                        item_text = matched_number.group(1)
                    else:
                        break
                    list_items.append(item_text.strip())
                    index += 1

                for item in list_items:
                    flowables.append(
                        Paragraph(
                            f"&#8226; {self.escape_inline_markup(item)}",
                            body_style,
                        )
                    )
                flowables.append(Spacer(1, 2))
                continue

            if not stripped:
                flush_paragraph()
                flowables.append(Spacer(1, 4))
                index += 1
                continue

            paragraph_parts.append(stripped)
            index += 1

        flush_paragraph()
        if in_code_block:
            flush_code_block()
        return flowables

    @staticmethod
    def escape_inline_markup(text: str) -> str:
        escaped = (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
        escaped = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", escaped)
        escaped = re.sub(r"\*(.+?)\*", r"<i>\1</i>", escaped)
        return escaped

    @staticmethod
    def trim_code_lines(lines: list[str], *, max_lines: int, max_chars: int) -> list[str]:
        normalized: list[str] = []
        for line in lines:
            line_clean = str(line).replace("\t", "    ").rstrip()
            if len(line_clean) <= max_chars:
                normalized.append(line_clean)
            else:
                normalized.append(line_clean[: max_chars - 3] + "...")
            if len(normalized) >= max_lines:
                break
        if len(lines) > max_lines and normalized:
            normalized[-1] = normalized[-1][: max_chars - 3] + "..."
        return normalized or ["# code block"]
