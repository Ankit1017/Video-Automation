from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from main_app.infrastructure.orchestration_ledger_store import JsonRunLedgerStore, JsonStageLedgerStore


class TestOrchestrationLedgerStores(unittest.TestCase):
    def test_json_run_ledger_store_upsert(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonRunLedgerStore(Path(temp_dir) / "run_ledger.json")
            store.upsert_record({"run_id": "run_a", "status": "success", "started_at": "2026-01-01T00:00:00+00:00"})
            store.upsert_record({"run_id": "run_a", "status": "error", "started_at": "2026-01-01T00:00:01+00:00"})
            rows = store.list_records()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].get("status"), "error")

    def test_json_stage_ledger_store_upsert(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonStageLedgerStore(Path(temp_dir) / "stage_ledger.json")
            store.upsert_record(
                {"run_id": "run_a", "tool_key": "topic", "stage_key": "execute", "attempt": 1, "status": "success"}
            )
            store.upsert_record(
                {"run_id": "run_a", "tool_key": "topic", "stage_key": "execute", "attempt": 1, "status": "error"}
            )
            rows = store.list_records()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].get("status"), "error")


if __name__ == "__main__":
    unittest.main()
