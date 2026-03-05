from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any, Iterator
from uuid import uuid4


logger = logging.getLogger(__name__)

_REQUEST_ID_CONTEXT: ContextVar[str] = ContextVar("telemetry_request_id", default="")
_SESSION_ID_CONTEXT: ContextVar[str] = ContextVar("telemetry_session_id", default="")
_RUN_ID_CONTEXT: ContextVar[str] = ContextVar("telemetry_run_id", default="")
_JOB_ID_CONTEXT: ContextVar[str] = ContextVar("telemetry_job_id", default="")
_TRACE_ID_CONTEXT: ContextVar[str] = ContextVar("telemetry_trace_id", default="")
_SPAN_ID_CONTEXT: ContextVar[str] = ContextVar("telemetry_span_id", default="")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _env_bool(name: str, *, default: bool) -> bool:
    raw = " ".join(str(os.getenv(name, "")).split()).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def create_trace_id() -> str:
    # W3C trace id format: 32 lowercase hex chars.
    return uuid4().hex


def create_span_id() -> str:
    # W3C span id format: 16 lowercase hex chars.
    return uuid4().hex[:16]


def create_session_id() -> str:
    return f"sess_{uuid4().hex[:12]}"


def create_run_id() -> str:
    return f"run_{uuid4().hex[:12]}"


def create_job_id() -> str:
    return f"job_{uuid4().hex[:12]}"


@dataclass(frozen=True)
class TelemetryContext:
    request_id: str = ""
    session_id: str = ""
    run_id: str = ""
    job_id: str = ""
    trace_id: str = ""
    span_id: str = ""


@dataclass(frozen=True)
class ObservabilityEvent:
    event_name: str
    component: str
    status: str
    timestamp: str
    attributes: dict[str, Any] = field(default_factory=dict)
    payload_ref: str = ""


@dataclass
class _MetricAccumulator:
    name: str
    count: int = 0
    sum_value: float = 0.0
    min_value: float = 0.0
    max_value: float = 0.0
    last_value: float = 0.0
    last_timestamp: str = ""
    last_attributes: dict[str, Any] = field(default_factory=dict)


class PayloadVault:
    def __init__(
        self,
        *,
        vault_dir: Path | None = None,
        capture_enabled: bool | None = None,
        retention_days: int | None = None,
        encryption_enabled: bool | None = None,
        encryption_key: str | None = None,
    ) -> None:
        self._vault_dir = vault_dir or Path(
            " ".join(str(os.getenv("OBSERVABILITY_PAYLOAD_VAULT_DIR", ".cache/observability_payloads")).split()).strip()
            or ".cache/observability_payloads"
        )
        self._capture_enabled = (
            bool(capture_enabled)
            if capture_enabled is not None
            else _env_bool("OBSERVABILITY_PAYLOAD_CAPTURE_ENABLED", default=True)
        )
        self._retention_days = max(
            _safe_int(
                retention_days
                if retention_days is not None
                else os.getenv("OBSERVABILITY_PAYLOAD_RETENTION_DAYS", 14),
                default=14,
            ),
            1,
        )
        self._encryption_enabled = (
            bool(encryption_enabled)
            if encryption_enabled is not None
            else _env_bool("OBSERVABILITY_PAYLOAD_ENCRYPTION_ENABLED", default=True)
        )
        self._lock = Lock()
        self._vault_dir.mkdir(parents=True, exist_ok=True)
        self._fernet = self._build_fernet(
            encryption_key=encryption_key
            or " ".join(str(os.getenv("OBSERVABILITY_PAYLOAD_ENCRYPTION_KEY", "")).split()).strip()
        )

    def attach_payload(self, *, payload: Any, kind: str, context: TelemetryContext) -> str:
        if not self._capture_enabled:
            return ""
        ref = f"payload_{uuid4().hex}"
        envelope = {
            "kind": " ".join(str(kind).split()).strip() or "generic",
            "created_at": _utc_now_iso(),
            "context": {
                "request_id": context.request_id,
                "session_id": context.session_id,
                "run_id": context.run_id,
                "job_id": context.job_id,
                "trace_id": context.trace_id,
                "span_id": context.span_id,
            },
            "payload": payload,
        }
        raw = json.dumps(envelope, ensure_ascii=False, default=str).encode("utf-8")
        with self._lock:
            self._purge_expired_locked()
            target = self._vault_dir / f"{ref}.json"
            if self._fernet is not None:
                target = self._vault_dir / f"{ref}.json.enc"
                raw = self._fernet.encrypt(raw)
            try:
                target.write_bytes(raw)
            except OSError as exc:
                logger.warning("Failed to persist payload vault entry `%s`: %s", ref, exc)
                return ""
        return ref

    def get_payload(self, payload_ref: str) -> dict[str, Any] | None:
        ref = " ".join(str(payload_ref).split()).strip()
        if not ref:
            return None
        plain = self._vault_dir / f"{ref}.json"
        encrypted = self._vault_dir / f"{ref}.json.enc"
        path = encrypted if encrypted.exists() else plain
        if not path.exists():
            return None
        try:
            raw = path.read_bytes()
            if path.suffix == ".enc":
                if self._fernet is None:
                    return None
                raw = self._fernet.decrypt(raw)
            parsed = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_expired_locked()

    def _purge_expired_locked(self) -> int:
        deleted = 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        for path in self._vault_dir.glob("payload_*.json*"):
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if modified >= cutoff:
                continue
            try:
                path.unlink(missing_ok=True)
                deleted += 1
            except OSError:
                continue
        return deleted

    def _build_fernet(self, *, encryption_key: str) -> Any:
        if not self._encryption_enabled:
            return None
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            logger.warning("`cryptography` is not installed; payload vault encryption disabled.")
            return None

        normalized_key = encryption_key
        if not normalized_key:
            key_file_raw = " ".join(
                str(os.getenv("OBSERVABILITY_PAYLOAD_KEY_FILE", str(self._vault_dir / ".payload.key"))).split()
            ).strip()
            key_file = Path(key_file_raw or str(self._vault_dir / ".payload.key"))
            try:
                if key_file.exists():
                    normalized_key = key_file.read_text(encoding="utf-8").strip()
                else:
                    key_file.parent.mkdir(parents=True, exist_ok=True)
                    generated = Fernet.generate_key().decode("utf-8")
                    key_file.write_text(generated, encoding="utf-8")
                    normalized_key = generated
            except OSError:
                normalized_key = ""

        if not normalized_key:
            return None
        try:
            return Fernet(normalized_key.encode("utf-8"))
        except (ValueError, TypeError):
            logger.warning("Invalid payload encryption key; payload vault encryption disabled.")
            return None


class OTelBridge:
    def __init__(self) -> None:
        self._enabled = _env_bool("OBSERVABILITY_OTEL_ENABLED", default=True)
        self._tracer = None
        self._meter = None
        self._counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}
        if self._enabled:
            self._setup()

    @property
    def enabled(self) -> bool:
        return bool(self._enabled and self._tracer is not None)

    def _setup(self) -> None:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError:
            self._enabled = False
            logger.warning("OpenTelemetry packages are not installed; OTel export disabled.")
            return

        service_name = " ".join(str(os.getenv("OTEL_SERVICE_NAME", "hatched-studio-app")).split()).strip() or "hatched-studio-app"
        endpoint = " ".join(str(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")).split()).strip() or "http://localhost:4317"
        insecure = _env_bool("OTEL_EXPORTER_OTLP_INSECURE", default=True)
        resource = Resource.create({"service.name": service_name})

        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=endpoint, insecure=insecure)
            )
        )
        self._tracer = tracer_provider.get_tracer("video_automation.telemetry")

        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=endpoint, insecure=insecure)
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        self._meter = meter_provider.get_meter("video_automation.telemetry")

    @contextmanager
    def start_span(self, *, name: str, attributes: dict[str, Any]) -> Iterator[tuple[str, str]]:
        if not self.enabled:
            yield "", ""
            return
        tracer = self._tracer
        if tracer is None:
            yield "", ""
            return
        with tracer.start_as_current_span(name, attributes=attributes) as span:
            span_context = span.get_span_context()
            trace_id = format(span_context.trace_id, "032x")
            span_id = format(span_context.span_id, "016x")
            yield trace_id, span_id

    def record_event(self, *, name: str, attributes: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            from opentelemetry import trace
        except ImportError:
            return
        span = trace.get_current_span()
        if span is None:
            return
        try:
            span.add_event(name=name, attributes=attributes)
        except (TypeError, ValueError):
            return

    def record_metric(self, *, name: str, value: float, attributes: dict[str, Any]) -> None:
        if self._meter is None:
            return
        normalized_name = " ".join(str(name).split()).strip()
        if not normalized_name:
            return
        if normalized_name.endswith("_ms") or "latency" in normalized_name:
            instrument = self._histograms.get(normalized_name)
            if instrument is None:
                instrument = self._meter.create_histogram(normalized_name)  # type: ignore[union-attr]
                self._histograms[normalized_name] = instrument
            instrument.record(float(value), attributes=attributes)
            return

        instrument = self._counters.get(normalized_name)
        if instrument is None:
            instrument = self._meter.create_counter(normalized_name)  # type: ignore[union-attr]
            self._counters[normalized_name] = instrument
        instrument.add(float(value), attributes=attributes)


class TelemetryService:
    def __init__(
        self,
        *,
        payload_vault: PayloadVault | None = None,
        otel_bridge: OTelBridge | None = None,
    ) -> None:
        self._payload_vault = payload_vault or PayloadVault()
        self._otel = otel_bridge or OTelBridge()
        self._lock = Lock()
        self._metrics: dict[str, _MetricAccumulator] = {}
        self._metric_points: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._metric_point_limit = max(
            _safe_int(os.getenv("OBSERVABILITY_RECENT_METRICS_LIMIT", 1000), default=1000),
            100,
        )
        self._event_limit = max(_safe_int(os.getenv("OBSERVABILITY_RECENT_EVENTS_LIMIT", 500), default=500), 50)

    def current_context(self) -> TelemetryContext:
        return TelemetryContext(
            request_id=str(_REQUEST_ID_CONTEXT.get("")).strip(),
            session_id=str(_SESSION_ID_CONTEXT.get("")).strip(),
            run_id=str(_RUN_ID_CONTEXT.get("")).strip(),
            job_id=str(_JOB_ID_CONTEXT.get("")).strip(),
            trace_id=str(_TRACE_ID_CONTEXT.get("")).strip(),
            span_id=str(_SPAN_ID_CONTEXT.get("")).strip(),
        )

    @contextmanager
    def context_scope(
        self,
        *,
        request_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> Iterator[TelemetryContext]:
        tokens = []
        if request_id is not None:
            tokens.append((_REQUEST_ID_CONTEXT, _REQUEST_ID_CONTEXT.set(" ".join(str(request_id).split()).strip())))
        if session_id is not None:
            tokens.append((_SESSION_ID_CONTEXT, _SESSION_ID_CONTEXT.set(" ".join(str(session_id).split()).strip())))
        if run_id is not None:
            tokens.append((_RUN_ID_CONTEXT, _RUN_ID_CONTEXT.set(" ".join(str(run_id).split()).strip())))
        if job_id is not None:
            tokens.append((_JOB_ID_CONTEXT, _JOB_ID_CONTEXT.set(" ".join(str(job_id).split()).strip())))
        if trace_id is not None:
            tokens.append((_TRACE_ID_CONTEXT, _TRACE_ID_CONTEXT.set(" ".join(str(trace_id).split()).strip())))
        if span_id is not None:
            tokens.append((_SPAN_ID_CONTEXT, _SPAN_ID_CONTEXT.set(" ".join(str(span_id).split()).strip())))
        try:
            yield self.current_context()
        finally:
            for context_var, token in reversed(tokens):
                context_var.reset(token)

    @contextmanager
    def start_span(
        self,
        *,
        name: str,
        component: str,
        attrs: dict[str, Any] | None = None,
    ) -> Iterator[TelemetryContext]:
        normalized_name = " ".join(str(name).split()).strip() or "unnamed_span"
        normalized_component = " ".join(str(component).split()).strip() or "unknown_component"
        base_context = self.current_context()
        active_trace_id = base_context.trace_id or create_trace_id()
        parent_span_id = base_context.span_id
        span_attrs = {
            "component": normalized_component,
            "request_id": base_context.request_id,
            "session_id": base_context.session_id,
            "run_id": base_context.run_id,
            "job_id": base_context.job_id,
            "trace_id": active_trace_id,
            "parent_span_id": parent_span_id,
        }
        for key, value in (attrs or {}).items():
            normalized_key = " ".join(str(key).split()).strip()
            if normalized_key:
                span_attrs[normalized_key] = value

        with self._otel.start_span(name=normalized_name, attributes=span_attrs) as (otel_trace_id, otel_span_id):
            next_trace_id = otel_trace_id or active_trace_id
            next_span_id = otel_span_id or create_span_id()
            with self.context_scope(trace_id=next_trace_id, span_id=next_span_id):
                self.record_event(
                    ObservabilityEvent(
                        event_name=f"{normalized_name}.start",
                        component=normalized_component,
                        status="started",
                        timestamp=_utc_now_iso(),
                        attributes=span_attrs,
                    )
                )
                try:
                    yield self.current_context()
                except (ValueError, TypeError, RuntimeError, OSError, KeyError, AttributeError) as exc:
                    self.record_event(
                        ObservabilityEvent(
                            event_name=f"{normalized_name}.error",
                            component=normalized_component,
                            status="error",
                            timestamp=_utc_now_iso(),
                            attributes={**span_attrs, "error": str(exc)},
                        )
                    )
                    raise
                finally:
                    self.record_event(
                        ObservabilityEvent(
                            event_name=f"{normalized_name}.end",
                            component=normalized_component,
                            status="ok",
                            timestamp=_utc_now_iso(),
                            attributes=span_attrs,
                        )
                    )

    def record_metric(self, *, name: str, value: float, attrs: dict[str, Any] | None = None) -> None:
        context = self.current_context()
        normalized_name = " ".join(str(name).split()).strip()
        numeric_value = float(value)
        now_iso = _utc_now_iso()
        merged = {
            "request_id": context.request_id,
            "session_id": context.session_id,
            "run_id": context.run_id,
            "job_id": context.job_id,
            "trace_id": context.trace_id,
            "span_id": context.span_id,
        }
        for key, raw_value in (attrs or {}).items():
            normalized_key = " ".join(str(key).split()).strip()
            if normalized_key:
                merged[normalized_key] = raw_value
        self._otel.record_metric(name=normalized_name, value=numeric_value, attributes=merged)
        if not normalized_name:
            return
        metric_point = {
            "metric_name": normalized_name,
            "value": round(float(numeric_value), 6),
            "timestamp": now_iso,
            "attributes": dict(merged),
        }
        with self._lock:
            self._metric_points.append(metric_point)
            if len(self._metric_points) > self._metric_point_limit:
                overflow = len(self._metric_points) - self._metric_point_limit
                if overflow > 0:
                    del self._metric_points[:overflow]
            accumulator = self._metrics.get(normalized_name)
            if accumulator is None:
                accumulator = _MetricAccumulator(
                    name=normalized_name,
                    count=1,
                    sum_value=numeric_value,
                    min_value=numeric_value,
                    max_value=numeric_value,
                    last_value=numeric_value,
                    last_timestamp=now_iso,
                    last_attributes=dict(merged),
                )
                self._metrics[normalized_name] = accumulator
            else:
                accumulator.count += 1
                accumulator.sum_value += numeric_value
                accumulator.min_value = min(accumulator.min_value, numeric_value)
                accumulator.max_value = max(accumulator.max_value, numeric_value)
                accumulator.last_value = numeric_value
                accumulator.last_timestamp = now_iso
                accumulator.last_attributes = dict(merged)

    def record_event(self, event: ObservabilityEvent | dict[str, Any]) -> None:
        normalized: dict[str, Any]
        if isinstance(event, dict):
            normalized = dict(event)
        elif isinstance(event, ObservabilityEvent) or (
            hasattr(event, "event_name")
            and hasattr(event, "component")
            and hasattr(event, "status")
            and hasattr(event, "timestamp")
        ):
            attributes = getattr(event, "attributes", {})
            normalized = {
                "event_name": str(getattr(event, "event_name", "")),
                "component": str(getattr(event, "component", "")),
                "status": str(getattr(event, "status", "")),
                "timestamp": str(getattr(event, "timestamp", "")),
                "attributes": dict(attributes) if isinstance(attributes, dict) else {},
                "payload_ref": str(getattr(event, "payload_ref", "")),
            }
        else:
            try:
                normalized = dict(event)
            except (TypeError, ValueError):
                logger.warning("Ignoring telemetry event with unsupported shape: %s", type(event).__name__)
                normalized = {}
        context = self.current_context()
        event_name = " ".join(str(normalized.get("event_name", "")).split()).strip() or "event"
        component = " ".join(str(normalized.get("component", "")).split()).strip() or "unknown_component"
        status = " ".join(str(normalized.get("status", "")).split()).strip() or "ok"
        timestamp = " ".join(str(normalized.get("timestamp", "")).split()).strip() or _utc_now_iso()
        payload_ref = " ".join(str(normalized.get("payload_ref", "")).split()).strip()
        raw_attrs = normalized.get("attributes", {})
        attrs = dict(raw_attrs) if isinstance(raw_attrs, dict) else {}
        attrs.update(
            {
                "request_id": context.request_id,
                "session_id": context.session_id,
                "run_id": context.run_id,
                "job_id": context.job_id,
                "trace_id": context.trace_id,
                "span_id": context.span_id,
                "component": component,
                "status": status,
            }
        )
        self._otel.record_event(name=event_name, attributes=attrs)
        stored = {
            "event_name": event_name,
            "component": component,
            "status": status,
            "timestamp": timestamp,
            "payload_ref": payload_ref,
            "attributes": attrs,
        }
        with self._lock:
            self._events.append(stored)
            if len(self._events) > self._event_limit:
                overflow = len(self._events) - self._event_limit
                if overflow > 0:
                    del self._events[:overflow]
        logger.info(
            json.dumps(
                {
                    "event": "telemetry_event",
                    "event_name": event_name,
                    "component": component,
                    "status": status,
                    "timestamp": timestamp,
                    "payload_ref": payload_ref,
                    "attributes": attrs,
                },
                ensure_ascii=False,
                default=str,
            )
        )

    def attach_payload(self, *, payload: Any, kind: str) -> str:
        context = self.current_context()
        return self._payload_vault.attach_payload(payload=payload, kind=kind, context=context)

    def fetch_payload(self, payload_ref: str) -> dict[str, Any] | None:
        return self._payload_vault.get_payload(payload_ref)

    def purge_payloads(self) -> int:
        return self._payload_vault.purge_expired()

    def telemetry_metric_rows(self) -> list[dict[str, Any]]:
        with self._lock:
            rows: list[dict[str, Any]] = []
            for name, metric in self._metrics.items():
                avg_value = (metric.sum_value / metric.count) if metric.count else 0.0
                component = " ".join(str(metric.last_attributes.get("component", "")).split()).strip()
                status = " ".join(str(metric.last_attributes.get("status", "")).split()).strip()
                rows.append(
                    {
                        "metric_name": name,
                        "component": component,
                        "status": status,
                        "count": int(metric.count),
                        "sum": round(float(metric.sum_value), 6),
                        "avg": round(float(avg_value), 6),
                        "min": round(float(metric.min_value), 6),
                        "max": round(float(metric.max_value), 6),
                        "last_value": round(float(metric.last_value), 6),
                        "last_timestamp": metric.last_timestamp,
                        "last_request_id": " ".join(str(metric.last_attributes.get("request_id", "")).split()).strip(),
                        "last_session_id": " ".join(str(metric.last_attributes.get("session_id", "")).split()).strip(),
                        "last_run_id": " ".join(str(metric.last_attributes.get("run_id", "")).split()).strip(),
                        "last_job_id": " ".join(str(metric.last_attributes.get("job_id", "")).split()).strip(),
                        "last_trace_id": " ".join(str(metric.last_attributes.get("trace_id", "")).split()).strip(),
                        "last_span_id": " ".join(str(metric.last_attributes.get("span_id", "")).split()).strip(),
                        "last_attributes": dict(metric.last_attributes),
                    }
                )
            rows.sort(key=lambda item: (str(item.get("metric_name", "")), str(item.get("component", ""))))
            return rows

    def recent_metric_rows(self, *, limit: int = 500) -> list[dict[str, Any]]:
        bounded_limit = max(_safe_int(limit, default=500), 1)
        with self._lock:
            points = self._metric_points[-bounded_limit:]
            return [dict(item) for item in reversed(points)]

    def recent_event_rows(self, *, limit: int = 200) -> list[dict[str, Any]]:
        bounded_limit = max(_safe_int(limit, default=200), 1)
        with self._lock:
            events = self._events[-bounded_limit:]
            return [dict(item) for item in reversed(events)]

    def telemetry_overview(self) -> dict[str, Any]:
        with self._lock:
            unique_components = {
                " ".join(str(item.get("component", "")).split()).strip()
                for item in self._events
                if " ".join(str(item.get("component", "")).split()).strip()
            }
            return {
                "metric_family_count": len(self._metrics),
                "recent_metric_count": len(self._metric_points),
                "recent_event_count": len(self._events),
                "component_count": len(unique_components),
                "metric_capacity": self._metric_point_limit,
                "event_capacity": self._event_limit,
            }

    def reset_runtime_buffers(self) -> None:
        with self._lock:
            self._metrics.clear()
            self._metric_points.clear()
            self._events.clear()
