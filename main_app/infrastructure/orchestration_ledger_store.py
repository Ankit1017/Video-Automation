from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from main_app.infrastructure.mongo_base import MongoCollectionConfig, MongoCollectionProvider


class JsonRunLedgerStore:
    def __init__(self, storage_file: Path) -> None:
        self._storage_file = storage_file

    def list_records(self) -> list[dict[str, Any]]:
        payload = self._load_payload()
        records = payload.get("records", [])
        if not isinstance(records, list):
            return []
        return [item for item in records if isinstance(item, dict)]

    def upsert_record(self, record_entry: dict[str, Any]) -> None:
        run_id = " ".join(str(record_entry.get("run_id", "")).split()).strip()
        if not run_id:
            return
        records = self.list_records()
        replaced = False
        for idx, item in enumerate(records):
            item_run_id = " ".join(str(item.get("run_id", "")).split()).strip()
            if item_run_id == run_id:
                records[idx] = dict(record_entry)
                replaced = True
                break
        if not replaced:
            records.append(dict(record_entry))
        self.save_records(records)

    def save_records(self, records: list[dict[str, Any]]) -> None:
        self._storage_file.parent.mkdir(parents=True, exist_ok=True)
        self._storage_file.write_text(
            json.dumps({"records": records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_payload(self) -> dict[str, Any]:
        if not self._storage_file.exists():
            return {"records": []}
        try:
            parsed = json.loads(self._storage_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"records": []}
        if not isinstance(parsed, dict):
            return {"records": []}
        return parsed


class JsonStageLedgerStore:
    def __init__(self, storage_file: Path) -> None:
        self._storage_file = storage_file

    def list_records(self) -> list[dict[str, Any]]:
        payload = self._load_payload()
        records = payload.get("records", [])
        if not isinstance(records, list):
            return []
        return [item for item in records if isinstance(item, dict)]

    def upsert_record(self, record_entry: dict[str, Any]) -> None:
        key = self._record_key(record_entry)
        if not key:
            return
        records = self.list_records()
        replaced = False
        for idx, item in enumerate(records):
            if self._record_key(item) == key:
                records[idx] = dict(record_entry)
                replaced = True
                break
        if not replaced:
            records.append(dict(record_entry))
        self.save_records(records)

    def save_records(self, records: list[dict[str, Any]]) -> None:
        self._storage_file.parent.mkdir(parents=True, exist_ok=True)
        self._storage_file.write_text(
            json.dumps({"records": records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_payload(self) -> dict[str, Any]:
        if not self._storage_file.exists():
            return {"records": []}
        try:
            parsed = json.loads(self._storage_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"records": []}
        if not isinstance(parsed, dict):
            return {"records": []}
        return parsed

    @staticmethod
    def _record_key(record: dict[str, Any]) -> str:
        run_id = " ".join(str(record.get("run_id", "")).split()).strip()
        tool_key = " ".join(str(record.get("tool_key", "")).split()).strip()
        stage_key = " ".join(str(record.get("stage_key", "")).split()).strip()
        attempt = " ".join(str(record.get("attempt", "")).split()).strip() or "1"
        if not run_id or not tool_key or not stage_key:
            return ""
        return f"{run_id}:{tool_key}:{stage_key}:{attempt}"


class MongoRunLedgerStore:
    def __init__(
        self,
        *,
        uri: str,
        db_name: str,
        collection_name: str = "run_ledger",
    ) -> None:
        self._provider = MongoCollectionProvider(
            MongoCollectionConfig(uri=uri, db_name=db_name, collection_name=collection_name)
        )

    @property
    def description(self) -> str:
        return self._provider.description

    def list_records(self) -> list[dict[str, Any]]:
        collection = self._provider.collection()
        records: list[dict[str, Any]] = []
        for item in collection.find({}, {"_id": 0, "record": 1}).sort("started_at_sort", -1):
            record = item.get("record")
            if isinstance(record, dict):
                records.append(record)
        return records

    def upsert_record(self, record_entry: dict[str, Any]) -> None:
        run_id = " ".join(str(record_entry.get("run_id", "")).split()).strip()
        if not run_id:
            return
        collection = self._provider.collection()
        collection.replace_one(
            {"_id": run_id},
            {
                "_id": run_id,
                "started_at_sort": str(record_entry.get("started_at", "")),
                "record": dict(record_entry),
            },
            upsert=True,
        )

    def save_records(self, records: list[dict[str, Any]]) -> None:
        collection = self._provider.collection()
        collection.delete_many({})
        docs: list[dict[str, Any]] = []
        for record in records:
            run_id = " ".join(str(record.get("run_id", "")).split()).strip()
            if not run_id:
                continue
            docs.append(
                {
                    "_id": run_id,
                    "started_at_sort": str(record.get("started_at", "")),
                    "record": dict(record),
                }
            )
        if docs:
            collection.insert_many(docs, ordered=False)


class MongoStageLedgerStore:
    def __init__(
        self,
        *,
        uri: str,
        db_name: str,
        collection_name: str = "stage_ledger",
    ) -> None:
        self._provider = MongoCollectionProvider(
            MongoCollectionConfig(uri=uri, db_name=db_name, collection_name=collection_name)
        )

    @property
    def description(self) -> str:
        return self._provider.description

    def list_records(self) -> list[dict[str, Any]]:
        collection = self._provider.collection()
        records: list[dict[str, Any]] = []
        for item in collection.find({}, {"_id": 0, "record": 1}).sort("started_at_sort", 1):
            record = item.get("record")
            if isinstance(record, dict):
                records.append(record)
        return records

    def upsert_record(self, record_entry: dict[str, Any]) -> None:
        key = self._record_key(record_entry)
        if not key:
            return
        collection = self._provider.collection()
        collection.replace_one(
            {"_id": key},
            {
                "_id": key,
                "started_at_sort": str(record_entry.get("started_at", "")),
                "record": dict(record_entry),
            },
            upsert=True,
        )

    def save_records(self, records: list[dict[str, Any]]) -> None:
        collection = self._provider.collection()
        collection.delete_many({})
        docs: list[dict[str, Any]] = []
        for record in records:
            key = self._record_key(record)
            if not key:
                continue
            docs.append(
                {
                    "_id": key,
                    "started_at_sort": str(record.get("started_at", "")),
                    "record": dict(record),
                }
            )
        if docs:
            collection.insert_many(docs, ordered=False)

    @staticmethod
    def _record_key(record: dict[str, Any]) -> str:
        run_id = " ".join(str(record.get("run_id", "")).split()).strip()
        tool_key = " ".join(str(record.get("tool_key", "")).split()).strip()
        stage_key = " ".join(str(record.get("stage_key", "")).split()).strip()
        attempt = " ".join(str(record.get("attempt", "")).split()).strip() or "1"
        if not run_id or not tool_key or not stage_key:
            return ""
        return f"{run_id}:{tool_key}:{stage_key}:{attempt}"
