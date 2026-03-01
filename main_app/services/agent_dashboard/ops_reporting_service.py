from __future__ import annotations

from collections import Counter
from typing import Any

from main_app.models import AssetHistoryRecord


def _as_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


class OpsReportingService:
    def build_summary(self, records: list[AssetHistoryRecord]) -> dict[str, Any]:
        if not records:
            return {
                "total_runs": 0,
                "success_rate_by_intent": {},
                "verify_failure_rate_by_intent": {},
                "top_error_codes": [],
                "stage_duration_ms": {"p50": 0, "p95": 0},
            }

        by_intent_total: Counter[str] = Counter()
        by_intent_success: Counter[str] = Counter()
        by_intent_verify_fail: Counter[str] = Counter()
        error_codes: Counter[str] = Counter()
        durations: list[int] = []

        for record in records:
            intent = " ".join(str(record.asset_type).split()).strip().lower()
            by_intent_total[intent] += 1
            if record.status == "success":
                by_intent_success[intent] += 1
            payload = _as_dict(record.result_payload)
            artifact = _as_dict(payload.get("artifact"))
            provenance = _as_dict(artifact.get("provenance"))
            verification = _as_dict(provenance.get("verification"))
            verify_status = " ".join(str(verification.get("status", "")).split()).strip().lower()
            if verify_status == "failed":
                by_intent_verify_fail[intent] += 1
            issues = _as_list(verification.get("issues"))
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                code = " ".join(str(issue.get("code", "")).split()).strip().upper()
                if code:
                    error_codes[code] += 1
            metrics = _as_dict(artifact.get("metrics"))
            total_duration_raw = metrics.get("total_duration_ms", 0)
            try:
                durations.append(max(0, int(total_duration_raw)))
            except (TypeError, ValueError):
                continue

        success_rate_by_intent = {
            intent: round((by_intent_success[intent] / total) * 100, 2)
            for intent, total in by_intent_total.items()
            if total > 0
        }
        verify_failure_rate_by_intent = {
            intent: round((by_intent_verify_fail[intent] / total) * 100, 2)
            for intent, total in by_intent_total.items()
            if total > 0
        }

        durations_sorted = sorted(durations)
        p50 = _percentile(durations_sorted, 50)
        p95 = _percentile(durations_sorted, 95)

        return {
            "total_runs": len(records),
            "success_rate_by_intent": success_rate_by_intent,
            "verify_failure_rate_by_intent": verify_failure_rate_by_intent,
            "top_error_codes": [
                {"code": code, "count": count}
                for code, count in error_codes.most_common(10)
            ],
            "stage_duration_ms": {"p50": p50, "p95": p95},
        }


def _percentile(sorted_values: list[int], percentile: int) -> int:
    if not sorted_values:
        return 0
    index = int(round((percentile / 100) * (len(sorted_values) - 1)))
    return sorted_values[max(0, min(index, len(sorted_values) - 1))]
