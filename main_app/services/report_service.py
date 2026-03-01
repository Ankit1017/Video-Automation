from __future__ import annotations

from typing import Any

from main_app.models import GroqSettings, ReportFormat, ReportGenerationResult
from main_app.parsers.markdown_utils import normalize_markdown_text
from main_app.services.asset_history_service import AssetHistoryService
from main_app.services.cached_llm_service import CachedLLMService


class ReportService:
    _FORMATS = [
        ReportFormat(
            key="briefing_doc",
            title="Briefing Doc",
            description="Overview of your topic featuring key insights and notable highlights.",
        ),
        ReportFormat(
            key="study_guide",
            title="Study Guide",
            description="Short-answer quiz, suggested essay questions, and glossary of key terms.",
        ),
        ReportFormat(
            key="blog_post",
            title="Blog Post",
            description="Insightful takeaways distilled into a highly readable, structured article.",
        ),
    ]

    def __init__(
        self,
        llm_service: CachedLLMService,
        history_service: AssetHistoryService | None = None,
    ) -> None:
        self._llm_service = llm_service
        self._history_service = history_service

    def list_formats(self) -> list[ReportFormat]:
        return list(self._FORMATS)

    def get_format(self, key: str) -> ReportFormat:
        for report_format in self._FORMATS:
            if report_format.key == key:
                return report_format
        return self._FORMATS[0]

    def generate(
        self,
        *,
        topic: str,
        format_key: str,
        additional_notes: str,
        grounding_context: str = "",
        source_manifest: list[dict[str, Any]] | None = None,
        require_citations: bool = False,
        grounding_metadata: dict[str, Any] | None = None,
        settings: GroqSettings,
    ) -> ReportGenerationResult:
        selected_format = self.get_format(format_key)
        system_prompt = (
            "You are an expert report writer. "
            "Write clear, factual, structured reports in markdown. "
            "Use headings, short paragraphs, and bullet points when useful."
        )
        if grounding_context.strip():
            system_prompt += (
                " Source-grounded mode is enabled. Use the provided source material as primary evidence."
            )

        format_instruction = self._format_instruction(selected_format.key)
        user_prompt = (
            f"Topic: {topic.strip()}\n"
            f"Report format: {selected_format.title}\n\n"
            f"{format_instruction}\n\n"
            "Keep the report practical, informative, and easy to scan."
        )
        if grounding_context.strip():
            user_prompt += (
                "\n\nGrounding sources (cite claims inline as [S1], [S2], etc.):\n"
                f"{grounding_context.strip()}"
            )
            if require_citations:
                user_prompt += (
                    "\n\nCitation requirement:\n"
                    "- Include source citations for major factual claims.\n"
                    "- Do not use source IDs that are not present in the provided sources."
                )

        if additional_notes.strip():
            user_prompt += f"\n\nAdditional notes:\n{additional_notes.strip()}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response_text, cache_hit = self._llm_service.call(
            settings=settings,
            messages=messages,
            task=f"report_generate_{selected_format.key}",
            label=f"Report: {topic.strip()} ({selected_format.title})",
            topic=topic.strip(),
        )
        normalized_content = normalize_markdown_text(response_text)
        if self._history_service is not None:
            self._history_service.record_generation(
                asset_type="report",
                topic=topic.strip(),
                title=f"Report: {topic.strip()} ({selected_format.title})",
                model=settings.normalized_model,
                request_payload={
                    "topic": topic.strip(),
                    "format_key": selected_format.key,
                    "format_title": selected_format.title,
                    "additional_notes": additional_notes.strip(),
                    "grounded_mode": bool(grounding_context.strip()),
                    "require_citations": bool(require_citations),
                    "sources": list(source_manifest or []),
                    "grounding_metadata": dict(grounding_metadata or {}),
                },
                result_payload={"content": normalized_content},
                status="success",
                cache_hit=cache_hit,
            )
        return ReportGenerationResult(content=normalized_content, cache_hit=cache_hit)

    @staticmethod
    def _format_instruction(format_key: str) -> str:
        if format_key == "briefing_doc":
            return (
                "Create a briefing document with these sections:\n"
                "1. Executive Summary\n"
                "2. Context and Background\n"
                "3. Key Insights (with short explanations)\n"
                "4. Risks / Constraints\n"
                "5. Recommended Next Actions"
            )
        if format_key == "study_guide":
            return (
                "Create a study guide with these sections:\n"
                "1. Core Concepts\n"
                "2. Step-by-step Understanding Path\n"
                "3. 8 Short-answer Questions with answers\n"
                "4. 3 Essay-style Questions\n"
                "5. Glossary of key terms"
            )
        if format_key == "blog_post":
            return (
                "Create a blog post with these sections:\n"
                "1. Hooked introduction\n"
                "2. Main explanation with subheadings\n"
                "3. Practical examples\n"
                "4. Common mistakes\n"
                "5. Final takeaway"
            )
        return (
            "Create a briefing-style report with a clear summary, key insights, risks, and practical next steps."
        )
