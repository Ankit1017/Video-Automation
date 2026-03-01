from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from threading import Lock
from typing import Any, Iterator
from uuid import uuid4

from main_app.services.telemetry_service import ObservabilityEvent, TelemetryService


logger = logging.getLogger(__name__)

_REQUEST_ID_CONTEXT: ContextVar[str] = ContextVar("request_id", default="")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def create_request_id() -> str:
    return f"req_{uuid4().hex[:12]}"


def get_request_id() -> str:
    return str(_REQUEST_ID_CONTEXT.get("")).strip()


def set_request_id(request_id: str) -> str:
    normalized = " ".join(str(request_id).split()).strip()
    if not normalized:
        normalized = create_request_id()
    _REQUEST_ID_CONTEXT.set(normalized)
    return normalized


def ensure_request_id() -> str:
    existing = get_request_id()
    if existing:
        return existing
    return set_request_id(create_request_id())


def clear_request_id() -> None:
    _REQUEST_ID_CONTEXT.set("")


@contextmanager
def request_id_scope(request_id: str | None = None) -> Iterator[str]:
    scoped_request_id = " ".join(str(request_id or "").split()).strip() or create_request_id()
    token = _REQUEST_ID_CONTEXT.set(scoped_request_id)
    try:
        yield scoped_request_id
    finally:
        _REQUEST_ID_CONTEXT.reset(token)


@dataclass(frozen=True)
class AssetMetricsSnapshot:
    asset: str
    request_count: int
    llm_calls: int
    cache_hits: int
    cache_hit_rate: float
    avg_latency_ms: float
    total_latency_ms: float
    total_estimated_cost_usd: float
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    errors: int
    last_request_id: str
    last_updated_at: str


@dataclass(frozen=True)
class OverallMetricsSnapshot:
    request_count: int
    llm_calls: int
    cache_hits: int
    cache_hit_rate: float
    avg_latency_ms: float
    total_latency_ms: float
    total_estimated_cost_usd: float
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    errors: int
    last_request_id: str
    last_updated_at: str


@dataclass
class _AssetMetricsAccumulator:
    request_ids: set[str] = field(default_factory=set)
    llm_calls: int = 0
    cache_hits: int = 0
    total_latency_ms: float = 0.0
    total_estimated_cost_usd: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    errors: int = 0
    last_request_id: str = ""
    last_updated_at: str = ""


@dataclass(frozen=True)
class _ModelCostRate:
    input_per_1m_tokens_usd: float = 0.0
    output_per_1m_tokens_usd: float = 0.0


class ObservabilityService:
    _TASK_PREFIX_TO_ASSET: tuple[tuple[str, str], ...] = (
        ("topic_explainer", "topic"),
        ("mindmap_", "mindmap"),
        ("flashcards_", "flashcards"),
        ("report_", "report"),
        ("data_table_", "data_table"),
        ("quiz_", "quiz"),
        ("slideshow_", "slideshow"),
        ("video_", "video"),
        ("audio_overview_", "audio_overview"),
        ("intent_", "intent_router"),
        ("agent_", "agent_chat"),
    )

    def __init__(
        self,
        *,
        default_input_cost_per_1m_usd: float | None = None,
        default_output_cost_per_1m_usd: float | None = None,
        telemetry_service: TelemetryService | None = None,
    ) -> None:
        self._lock = Lock()
        self._asset_metrics: dict[str, _AssetMetricsAccumulator] = {}
        self._last_request_id = ""
        self._last_updated_at = ""
        self._telemetry_service = telemetry_service or TelemetryService()
        self._default_rate = _ModelCostRate(
            input_per_1m_tokens_usd=self._resolve_cost_value(
                explicit=default_input_cost_per_1m_usd,
                env_name="LLM_INPUT_COST_PER_1M_USD",
            ),
            output_per_1m_tokens_usd=self._resolve_cost_value(
                explicit=default_output_cost_per_1m_usd,
                env_name="LLM_OUTPUT_COST_PER_1M_USD",
            ),
        )
        self._model_cost_overrides = self._parse_model_cost_overrides(
            os.getenv("LLM_MODEL_COST_OVERRIDES_JSON", "")
        )

    @property
    def telemetry_service(self) -> TelemetryService:
        return self._telemetry_service

    def resolve_asset_name(self, task: str) -> str:
        normalized_task = " ".join(str(task).split()).strip().lower()
        for prefix, asset in self._TASK_PREFIX_TO_ASSET:
            if normalized_task.startswith(prefix):
                return asset
        return "other"

    def record_llm_call(
        self,
        *,
        task: str,
        model: str,
        cache_hit: bool,
        latency_ms: float,
        request_id: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        error: str = "",
    ) -> None:
        normalized_task = " ".join(str(task).split()).strip()
        normalized_model = " ".join(str(model).split()).strip() or "unknown"
        normalized_request_id = " ".join(str(request_id).split()).strip() or ensure_request_id()
        normalized_error = " ".join(str(error).split()).strip()
        normalized_prompt_tokens = max(int(prompt_tokens or 0), 0)
        normalized_completion_tokens = max(int(completion_tokens or 0), 0)
        normalized_total_tokens = max(
            int(total_tokens or 0),
            normalized_prompt_tokens + normalized_completion_tokens,
        )
        normalized_latency_ms = max(float(latency_ms), 0.0)
        asset = self.resolve_asset_name(normalized_task)

        estimated_cost_usd = 0.0
        if not cache_hit and normalized_total_tokens > 0:
            estimated_cost_usd = self._estimate_cost_usd(
                model=normalized_model,
                prompt_tokens=normalized_prompt_tokens,
                completion_tokens=normalized_completion_tokens,
            )

        with self._lock:
            accumulator = self._asset_metrics.setdefault(asset, _AssetMetricsAccumulator())
            accumulator.llm_calls += 1
            accumulator.cache_hits += int(cache_hit)
            accumulator.total_latency_ms += normalized_latency_ms
            accumulator.total_estimated_cost_usd += estimated_cost_usd
            accumulator.total_prompt_tokens += normalized_prompt_tokens
            accumulator.total_completion_tokens += normalized_completion_tokens
            accumulator.total_tokens += normalized_total_tokens
            accumulator.last_request_id = normalized_request_id
            accumulator.last_updated_at = _utc_now_iso()
            if normalized_error:
                accumulator.errors += 1
            if normalized_request_id:
                accumulator.request_ids.add(normalized_request_id)

            self._last_request_id = normalized_request_id
            self._last_updated_at = accumulator.last_updated_at

        logger.info(
            json.dumps(
                {
                    "event": "llm_call",
                    "timestamp": _utc_now_iso(),
                    "request_id": normalized_request_id,
                    "asset": asset,
                    "task": normalized_task,
                    "model": normalized_model,
                    "cache_hit": bool(cache_hit),
                    "latency_ms": round(normalized_latency_ms, 3),
                    "prompt_tokens": normalized_prompt_tokens,
                    "completion_tokens": normalized_completion_tokens,
                    "total_tokens": normalized_total_tokens,
                    "estimated_cost_usd": round(estimated_cost_usd, 8),
                    "error": normalized_error,
                },
                ensure_ascii=False,
            )
        )
        attrs = {
            "asset": asset,
            "task": normalized_task,
            "model": normalized_model,
            "cache_hit": bool(cache_hit),
            "latency_ms": round(normalized_latency_ms, 3),
            "prompt_tokens": normalized_prompt_tokens,
            "completion_tokens": normalized_completion_tokens,
            "total_tokens": normalized_total_tokens,
            "estimated_cost_usd": round(estimated_cost_usd, 8),
            "error": normalized_error,
        }
        with self._telemetry_service.context_scope(request_id=normalized_request_id):
            payload_ref = self._telemetry_service.attach_payload(
                payload={
                    "task": normalized_task,
                    "model": normalized_model,
                    "cache_hit": bool(cache_hit),
                    "latency_ms": normalized_latency_ms,
                    "prompt_tokens": normalized_prompt_tokens,
                    "completion_tokens": normalized_completion_tokens,
                    "total_tokens": normalized_total_tokens,
                    "estimated_cost_usd": estimated_cost_usd,
                    "error": normalized_error,
                },
                kind="llm_call",
            )
            self._telemetry_service.record_metric(
                name="llm_calls_total",
                value=1.0,
                attrs={
                    "asset": asset,
                    "task": normalized_task,
                    "model": normalized_model,
                    "cache_hit": bool(cache_hit),
                },
            )
            self._telemetry_service.record_metric(
                name="llm_latency_ms",
                value=normalized_latency_ms,
                attrs={
                    "asset": asset,
                    "task": normalized_task,
                    "model": normalized_model,
                },
            )
            if normalized_total_tokens > 0:
                self._telemetry_service.record_metric(
                    name="llm_tokens_total",
                    value=float(normalized_total_tokens),
                    attrs={
                        "asset": asset,
                        "task": normalized_task,
                        "model": normalized_model,
                    },
                )
            self._telemetry_service.record_event(
                ObservabilityEvent(
                    event_name="llm.call",
                    component="llm",
                    status="error" if bool(normalized_error) else "ok",
                    timestamp=_utc_now_iso(),
                    attributes=attrs,
                    payload_ref=payload_ref,
                )
            )

    def current_request_id(self) -> str:
        current = get_request_id()
        if current:
            return current
        with self._lock:
            return self._last_request_id

    def asset_metrics(self) -> list[AssetMetricsSnapshot]:
        with self._lock:
            snapshots: list[AssetMetricsSnapshot] = []
            for asset, accumulator in self._asset_metrics.items():
                llm_calls = int(accumulator.llm_calls)
                cache_hits = int(accumulator.cache_hits)
                total_latency_ms = float(accumulator.total_latency_ms)
                cache_hit_rate = (cache_hits / llm_calls) if llm_calls else 0.0
                avg_latency_ms = (total_latency_ms / llm_calls) if llm_calls else 0.0
                snapshots.append(
                    AssetMetricsSnapshot(
                        asset=asset,
                        request_count=len(accumulator.request_ids),
                        llm_calls=llm_calls,
                        cache_hits=cache_hits,
                        cache_hit_rate=cache_hit_rate,
                        avg_latency_ms=avg_latency_ms,
                        total_latency_ms=total_latency_ms,
                        total_estimated_cost_usd=float(accumulator.total_estimated_cost_usd),
                        total_prompt_tokens=int(accumulator.total_prompt_tokens),
                        total_completion_tokens=int(accumulator.total_completion_tokens),
                        total_tokens=int(accumulator.total_tokens),
                        errors=int(accumulator.errors),
                        last_request_id=accumulator.last_request_id,
                        last_updated_at=accumulator.last_updated_at,
                    )
                )
            return sorted(snapshots, key=lambda item: item.asset)

    def overall_metrics(self) -> OverallMetricsSnapshot:
        per_asset = self.asset_metrics()
        if not per_asset:
            return OverallMetricsSnapshot(
                request_count=0,
                llm_calls=0,
                cache_hits=0,
                cache_hit_rate=0.0,
                avg_latency_ms=0.0,
                total_latency_ms=0.0,
                total_estimated_cost_usd=0.0,
                total_prompt_tokens=0,
                total_completion_tokens=0,
                total_tokens=0,
                errors=0,
                last_request_id=self.current_request_id(),
                last_updated_at=self._last_updated_at,
            )

        llm_calls = sum(item.llm_calls for item in per_asset)
        cache_hits = sum(item.cache_hits for item in per_asset)
        total_latency_ms = sum(item.total_latency_ms for item in per_asset)
        cache_hit_rate = (cache_hits / llm_calls) if llm_calls else 0.0
        avg_latency_ms = (total_latency_ms / llm_calls) if llm_calls else 0.0
        unique_request_ids: set[str] = set()
        with self._lock:
            for accumulator in self._asset_metrics.values():
                unique_request_ids.update(accumulator.request_ids)
        request_count = len(unique_request_ids)
        return OverallMetricsSnapshot(
            request_count=request_count,
            llm_calls=llm_calls,
            cache_hits=cache_hits,
            cache_hit_rate=cache_hit_rate,
            avg_latency_ms=avg_latency_ms,
            total_latency_ms=total_latency_ms,
            total_estimated_cost_usd=sum(item.total_estimated_cost_usd for item in per_asset),
            total_prompt_tokens=sum(item.total_prompt_tokens for item in per_asset),
            total_completion_tokens=sum(item.total_completion_tokens for item in per_asset),
            total_tokens=sum(item.total_tokens for item in per_asset),
            errors=sum(item.errors for item in per_asset),
            last_request_id=self.current_request_id(),
            last_updated_at=self._last_updated_at,
        )

    def metrics_table_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for snapshot in self.asset_metrics():
            rows.append(
                {
                    "asset": snapshot.asset,
                    "requests": snapshot.request_count,
                    "llm_calls": snapshot.llm_calls,
                    "cache_hits": snapshot.cache_hits,
                    "cache_hit_rate": round(snapshot.cache_hit_rate * 100.0, 2),
                    "avg_latency_ms": round(snapshot.avg_latency_ms, 2),
                    "total_latency_ms": round(snapshot.total_latency_ms, 2),
                    "prompt_tokens": snapshot.total_prompt_tokens,
                    "completion_tokens": snapshot.total_completion_tokens,
                    "total_tokens": snapshot.total_tokens,
                    "est_cost_usd": round(snapshot.total_estimated_cost_usd, 6),
                    "errors": snapshot.errors,
                    "last_request_id": snapshot.last_request_id,
                }
            )
        return rows

    def reset(self) -> None:
        with self._lock:
            self._asset_metrics.clear()
            self._last_request_id = ""
            self._last_updated_at = ""
        self._telemetry_service.reset_runtime_buffers()

    @contextmanager
    def start_span(
        self,
        *,
        name: str,
        component: str,
        attrs: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, str]]:
        with self._telemetry_service.start_span(name=name, component=component, attrs=attrs):
            context = self._telemetry_service.current_context()
            yield {
                "request_id": context.request_id,
                "session_id": context.session_id,
                "run_id": context.run_id,
                "job_id": context.job_id,
                "trace_id": context.trace_id,
                "span_id": context.span_id,
            }

    def record_metric(self, *, name: str, value: float, attrs: dict[str, Any] | None = None) -> None:
        self._telemetry_service.record_metric(name=name, value=value, attrs=attrs)

    def record_event(self, event: ObservabilityEvent | dict[str, Any]) -> None:
        self._telemetry_service.record_event(event)

    def attach_payload(self, *, payload: Any, kind: str) -> str:
        return self._telemetry_service.attach_payload(payload=payload, kind=kind)

    def telemetry_overview(self) -> dict[str, Any]:
        return self._telemetry_service.telemetry_overview()

    def telemetry_metric_rows(self) -> list[dict[str, Any]]:
        return self._telemetry_service.telemetry_metric_rows()

    def telemetry_recent_metric_rows(self, *, limit: int = 500) -> list[dict[str, Any]]:
        return self._telemetry_service.recent_metric_rows(limit=limit)

    def telemetry_recent_event_rows(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return self._telemetry_service.recent_event_rows(limit=limit)

    def fetch_payload(self, payload_ref: str) -> dict[str, Any] | None:
        return self._telemetry_service.fetch_payload(payload_ref)

    @staticmethod
    def _resolve_cost_value(*, explicit: float | None, env_name: str) -> float:
        if explicit is not None:
            return max(float(explicit), 0.0)
        raw = str(os.getenv(env_name, "")).strip()
        if not raw:
            return 0.0
        try:
            value = float(raw)
        except ValueError:
            return 0.0
        return max(value, 0.0)

    @staticmethod
    def _parse_model_cost_overrides(raw_json: str) -> dict[str, _ModelCostRate]:
        if not raw_json.strip():
            return {}
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning("Invalid LLM_MODEL_COST_OVERRIDES_JSON; ignoring overrides.")
            return {}
        if not isinstance(parsed, dict):
            return {}

        overrides: dict[str, _ModelCostRate] = {}
        for model, value in parsed.items():
            normalized_model = " ".join(str(model).split()).strip()
            if not normalized_model or not isinstance(value, dict):
                continue
            try:
                input_cost = max(float(value.get("input_per_1m_tokens_usd", 0.0)), 0.0)
                output_cost = max(float(value.get("output_per_1m_tokens_usd", 0.0)), 0.0)
            except (TypeError, ValueError):
                continue
            overrides[normalized_model] = _ModelCostRate(
                input_per_1m_tokens_usd=input_cost,
                output_per_1m_tokens_usd=output_cost,
            )
        return overrides

    def _estimate_cost_usd(self, *, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        rate = self._model_cost_overrides.get(model, self._default_rate)
        input_cost = (max(prompt_tokens, 0) / 1_000_000.0) * rate.input_per_1m_tokens_usd
        output_cost = (max(completion_tokens, 0) / 1_000_000.0) * rate.output_per_1m_tokens_usd
        return max(input_cost + output_cost, 0.0)
