from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

from main_app.contracts import IntentPayload
from main_app.infrastructure.asset_history_store import AssetHistoryRepository
from main_app.models import AssetHistoryRecord


logger = logging.getLogger(__name__)


class AssetHistoryService:
    def __init__(self, store: AssetHistoryRepository) -> None:
        self._store = store

    def record_generation(
        self,
        *,
        asset_type: str,
        topic: str,
        title: str,
        model: str,
        request_payload: dict[str, Any],
        result_payload: Any,
        status: str,
        cache_hit: bool,
        parse_note: str = "",
        error: str = "",
        raw_text: str = "",
    ) -> str | None:
        try:
            created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            record = AssetHistoryRecord(
                id=uuid4().hex[:16],
                asset_type=self._normalize_asset_type(asset_type),
                topic=self._clean_text(topic),
                title=self._clean_text(title),
                created_at=created_at,
                model=self._clean_text(model),
                request_payload=cast(IntentPayload, self._safe_dict(request_payload)),
                result_payload=self._json_safe(self._with_operational_defaults(result_payload)),
                status=self._normalize_status(status),
                cache_hit=bool(cache_hit),
                parse_note=self._clean_text(parse_note),
                error=self._clean_text(error),
                raw_text=str(raw_text or ""),
            )
            self._store.upsert_record(record.to_dict())
            return record.id
        except (TypeError, ValueError, OSError, RuntimeError, PermissionError) as exc:
            logger.exception(
                "Asset history persistence failed for asset type `%s`: %s",
                asset_type,
                exc,
            )
            return None

    def list_records(self, *, asset_type: str | None = None) -> list[AssetHistoryRecord]:
        records = [AssetHistoryRecord.from_dict(item) for item in self._store.list_records()]
        normalized_filter = self._normalize_asset_type(asset_type or "")
        if not normalized_filter:
            return records
        return [record for record in records if record.asset_type == normalized_filter]

    def get_record(self, record_id: str) -> AssetHistoryRecord | None:
        item = self._store.get_record(record_id)
        if not item:
            return None
        return AssetHistoryRecord.from_dict(item)

    @staticmethod
    def _normalize_asset_type(value: str) -> str:
        return " ".join(str(value).strip().lower().split())

    @staticmethod
    def _normalize_status(value: str) -> str:
        normalized = " ".join(str(value).strip().lower().split())
        if normalized in {"success", "error"}:
            return normalized
        return "success"

    @staticmethod
    def _clean_text(value: Any) -> str:
        return " ".join(str(value).split()).strip()

    @staticmethod
    def _safe_dict(value: dict[str, Any] | Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {str(key): AssetHistoryService._json_safe(item) for key, item in value.items()}

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): AssetHistoryService._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [AssetHistoryService._json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [AssetHistoryService._json_safe(item) for item in value]
        if isinstance(value, set):
            return [AssetHistoryService._json_safe(item) for item in sorted(value, key=str)]
        if isinstance(value, bytes):
            return f"<bytes:{len(value)}>"
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _with_operational_defaults(value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        result = dict(value)
        artifact = result.get("artifact")
        if not isinstance(artifact, dict):
            return result
        metrics = artifact.get("metrics")
        metrics_dict = dict(metrics) if isinstance(metrics, dict) else {}
        metrics_dict.setdefault("stage_durations_ms", {})
        metrics_dict.setdefault("total_duration_ms", 0)
        metrics_dict.setdefault("retry_count", 0)
        metrics_dict.setdefault("verification_issue_count", 0)
        metrics_dict.setdefault("queue_wait_ms", 0)
        metrics_dict.setdefault("attempt_durations_ms", {})
        metrics_dict.setdefault("policy_enforced", False)
        artifact["metrics"] = metrics_dict
        result["artifact"] = artifact
        return result
