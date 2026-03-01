from __future__ import annotations

from typing import cast

from main_app.contracts import DataTablePayload
from main_app.models import DataTableGenerationResult, GroqSettings
from main_app.parsers.data_table_parser import DataTableParser
from main_app.services.asset_history_service import AssetHistoryService
from main_app.services.cached_llm_service import CachedLLMService


class DataTableService:
    def __init__(
        self,
        llm_service: CachedLLMService,
        parser: DataTableParser,
        history_service: AssetHistoryService | None = None,
    ) -> None:
        self._llm_service = llm_service
        self._parser = parser
        self._history_service = history_service

    def generate(
        self,
        *,
        topic: str,
        row_count: int,
        notes: str,
        settings: GroqSettings,
    ) -> DataTableGenerationResult:
        requested_rows = max(3, min(int(row_count), 30))

        system_prompt = (
            "You are a data analyst. "
            "Return strict JSON only, no markdown, no explanation."
        )
        user_prompt = (
            f"Build a comparative data table for topic: {topic.strip()}\n\n"
            "Goal:\n"
            "- Divide the topic into meaningful subtypes/categories\n"
            "- Add relevant attributes as columns\n"
            "- Fill each row with concise factual values\n\n"
            "Output schema:\n"
            "{\n"
            '  "topic": "topic name",\n'
            '  "columns": ["Subtype", "<real_attribute_1>", "<real_attribute_2>", "<real_attribute_3>"],\n'
            '  "rows": [\n'
            '    {"Subtype": "...", "<real_attribute_1>": "...", "<real_attribute_2>": "...", "<real_attribute_3>": "..."}\n'
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            f"- Generate exactly {requested_rows} rows when possible.\n"
            "- Use 4 to 8 columns total, with 'Subtype' as first column.\n"
            "- Use domain-specific attribute names relevant to the topic.\n"
            "- Never use generic column names like `Attribute A`, `Attribute B`, `Field 1`, or `Metric 2`.\n"
            "- Keep cell values short and specific.\n"
            "- Return JSON only."
        )

        if notes.strip():
            user_prompt += f"\n\nAdditional constraints:\n{notes.strip()}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        raw_text, cache_hit = self._llm_service.call(
            settings=settings,
            messages=messages,
            task="data_table_generate",
            label=f"Data Table: {topic.strip()}",
            topic=topic.strip(),
        )

        parsed_table, parse_error, parse_note = self._parser.parse(
            raw_text,
            settings=settings,
            min_rows=min(3, requested_rows),
        )

        result = DataTableGenerationResult(
            raw_text=raw_text,
            parsed_table=cast(DataTablePayload | None, parsed_table),
            parse_error=parse_error,
            parse_note=parse_note,
            cache_hit=cache_hit,
        )
        if self._history_service is not None:
            self._history_service.record_generation(
                asset_type="data table",
                topic=topic.strip(),
                title=f"Data Table: {topic.strip()}",
                model=settings.normalized_model,
                request_payload={
                    "topic": topic.strip(),
                    "row_count": requested_rows,
                    "notes": notes.strip(),
                },
                result_payload=parsed_table if parsed_table is not None else {},
                status="error" if parse_error else "success",
                cache_hit=cache_hit,
                parse_note=parse_note or "",
                error=parse_error or "",
                raw_text=raw_text if parse_error else "",
            )
        return result
