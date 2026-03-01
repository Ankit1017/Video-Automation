from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, cast

from main_app.contracts import AssetRunSummary, RunLedgerRecord
from main_app.services.agent_dashboard.runtime_config import run_ledger_retention_days


class RunLedgerRepository(Protocol):
    def list_records(self) -> list[RunLedgerRecord]:
        ...

    def upsert_record(self, record_entry: RunLedgerRecord) -> None:
        ...

    def save_records(self, records: list[RunLedgerRecord]) -> None:
        ...


@dataclass
class InMemoryRunLedgerStore:
    _records: dict[str, RunLedgerRecord]

    def __init__(self) -> None:
        self._records = {}

    def list_records(self) -> list[RunLedgerRecord]:
        return sorted(self._records.values(), key=lambda item: str(item.get("started_at", "")), reverse=True)

    def upsert_record(self, record_entry: RunLedgerRecord) -> None:
        run_id = " ".join(str(record_entry.get("run_id", "")).split()).strip()
        if not run_id:
            return
        self._records[run_id] = cast(RunLedgerRecord, dict(record_entry))

    def save_records(self, records: list[RunLedgerRecord]) -> None:
        self._records = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            run_id = " ".join(str(record.get("run_id", "")).split()).strip()
            if run_id:
                self._records[run_id] = cast(RunLedgerRecord, dict(record))


class RunLedgerService:
    def __init__(self, *, store: RunLedgerRepository | None = None) -> None:
        self._store = store or InMemoryRunLedgerStore()

    def record_run(self, record: RunLedgerRecord) -> None:
        normalized = self._normalize_record(record)
        self._store.upsert_record(normalized)
        self._apply_retention()

    def list_runs(self) -> list[RunLedgerRecord]:
        return [self._normalize_record(item) for item in self._store.list_records() if isinstance(item, dict)]

    def query_runs(
        self,
        *,
        workflow_key: str = "",
        intent: str = "",
        status: str = "",
    ) -> list[RunLedgerRecord]:
        normalized_workflow = " ".join(str(workflow_key).split()).strip().lower()
        normalized_intent = " ".join(str(intent).split()).strip().lower()
        normalized_status = " ".join(str(status).split()).strip().lower()
        results: list[RunLedgerRecord] = []
        for record in self.list_runs():
            if normalized_workflow and " ".join(str(record.get("workflow_key", "")).split()).strip().lower() != normalized_workflow:
                continue
            if normalized_status and " ".join(str(record.get("status", "")).split()).strip().lower() != normalized_status:
                continue
            if normalized_intent:
                summaries = record.get("tool_summaries", [])
                if not isinstance(summaries, list):
                    continue
                if not any(
                    isinstance(summary, dict)
                    and " ".join(str(summary.get("intent", "")).split()).strip().lower() == normalized_intent
                    for summary in summaries
                ):
                    continue
            results.append(record)
        return results

    def _apply_retention(self) -> None:
        retention_days = run_ledger_retention_days()
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        retained: list[RunLedgerRecord] = []
        for record in self._store.list_records():
            if not isinstance(record, dict):
                continue
            started_at_raw = " ".join(str(record.get("started_at", "")).split()).strip()
            started_at = self._safe_parse_iso(started_at_raw)
            if started_at is None or started_at >= cutoff:
                retained.append(record)
        self._store.save_records(retained)

    @staticmethod
    def _normalize_record(record: RunLedgerRecord | dict[str, Any]) -> RunLedgerRecord:
        tool_summaries_raw = record.get("tool_summaries")
        error_counts_raw = record.get("error_counts")
        tool_summaries: list[AssetRunSummary] = []
        if isinstance(tool_summaries_raw, list):
            for item in tool_summaries_raw:
                if isinstance(item, dict):
                    tool_summaries.append(cast(AssetRunSummary, item))
        return {
            "run_id": " ".join(str(record.get("run_id", "")).split()).strip(),
            "workflow_key": " ".join(str(record.get("workflow_key", "")).split()).strip(),
            "planner_mode": " ".join(str(record.get("planner_mode", "")).split()).strip(),
            "status": " ".join(str(record.get("status", "")).split()).strip().lower(),
            "started_at": " ".join(str(record.get("started_at", "")).split()).strip(),
            "ended_at": " ".join(str(record.get("ended_at", "")).split()).strip(),
            "tool_summaries": tool_summaries,
            "error_counts": {
                str(key): int(value)
                for key, value in (error_counts_raw.items() if isinstance(error_counts_raw, dict) else [])
                if str(key).strip()
            },
        }

    @staticmethod
    def _safe_parse_iso(value: str) -> datetime | None:
        raw = " ".join(str(value).split()).strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None
