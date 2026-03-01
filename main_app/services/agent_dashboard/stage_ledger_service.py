from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from main_app.contracts import StageDiagnostic


class StageLedgerRepository(Protocol):
    def list_records(self) -> list[StageDiagnostic]:
        ...

    def upsert_record(self, record_entry: StageDiagnostic) -> None:
        ...

    def save_records(self, records: list[StageDiagnostic]) -> None:
        ...


@dataclass
class InMemoryStageLedgerStore:
    _records: dict[str, StageDiagnostic]

    def __init__(self) -> None:
        self._records = {}

    def list_records(self) -> list[StageDiagnostic]:
        return sorted(
            self._records.values(),
            key=lambda item: (str(item.get("run_id", "")), str(item.get("started_at", ""))),
        )

    def upsert_record(self, record_entry: StageDiagnostic) -> None:
        key = self._record_key(record_entry)
        if not key:
            return
        self._records[key] = cast(StageDiagnostic, dict(record_entry))

    def save_records(self, records: list[StageDiagnostic]) -> None:
        self._records = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            key = self._record_key(record)
            if key:
                self._records[key] = cast(StageDiagnostic, dict(record))

    @staticmethod
    def _record_key(record: StageDiagnostic | dict[str, Any]) -> str:
        run_id = " ".join(str(record.get("run_id", "")).split()).strip()
        tool_key = " ".join(str(record.get("tool_key", "")).split()).strip()
        stage_key = " ".join(str(record.get("stage_key", "")).split()).strip()
        attempt = " ".join(str(record.get("attempt", "")).split()).strip()
        if not run_id or not tool_key or not stage_key:
            return ""
        return f"{run_id}:{tool_key}:{stage_key}:{attempt or '1'}"


class StageLedgerService:
    def __init__(self, *, store: StageLedgerRepository | None = None) -> None:
        self._store = store or InMemoryStageLedgerStore()

    def record_stage(self, diagnostic: StageDiagnostic) -> None:
        self._store.upsert_record(cast(StageDiagnostic, dict(diagnostic)))

    def list_by_run(self, *, run_id: str) -> list[StageDiagnostic]:
        normalized = " ".join(str(run_id).split()).strip()
        if not normalized:
            return []
        rows = []
        for record in self._store.list_records():
            if " ".join(str(record.get("run_id", "")).split()).strip() != normalized:
                continue
            rows.append(record)
        rows.sort(key=lambda item: (str(item.get("started_at", "")), str(item.get("tool_key", "")), str(item.get("stage_key", ""))))
        return [cast(StageDiagnostic, dict(item)) for item in rows]

    def list_by_tool(self, *, run_id: str, tool_key: str) -> list[StageDiagnostic]:
        run_rows = self.list_by_run(run_id=run_id)
        normalized_tool = " ".join(str(tool_key).split()).strip().lower().replace(" ", "_")
        return [
            row
            for row in run_rows
            if " ".join(str(row.get("tool_key", "")).split()).strip().lower().replace(" ", "_") == normalized_tool
        ]
