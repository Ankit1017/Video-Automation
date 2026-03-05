from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
from typing import Any, Callable, Iterator
from uuid import uuid4

from main_app.services.observability_service import create_request_id, request_id_scope
from main_app.services.telemetry_service import ObservabilityEvent, TelemetryService


BackgroundJobWorker = Callable[["BackgroundJobContext"], Any]
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_JOB_STATUSES = {"queued", "running", "cancel_requested"}


class JobCancelledError(RuntimeError):
    """Raised by a background job worker when cancellation is requested."""


@dataclass(frozen=True)
class BackgroundJobSnapshot:
    id: str
    label: str
    status: str
    progress: float
    message: str
    created_at: str
    started_at: str
    finished_at: str
    error: str
    cancel_requested: bool
    retry_of: str
    queue_position: int | None
    metadata: dict[str, Any]
    result: Any
    elapsed_seconds: float | None
    eta_seconds_remaining: float | None
    estimated_finish_at: str
    stage_name: str
    stage_elapsed_seconds: float | None
    stage_eta_seconds_remaining: float | None
    historical_avg_duration_seconds: float | None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_JOB_STATUSES

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_JOB_STATUSES


class BackgroundJobContext:
    def __init__(self, *, manager: "BackgroundJobManager", job_id: str) -> None:
        self._manager = manager
        self._job_id = job_id

    def update_progress(self, *, progress: float, message: str | None = None) -> None:
        self._manager._set_progress(  # noqa: SLF001
            job_id=self._job_id,
            progress=progress,
            message=message,
        )

    def is_cancel_requested(self) -> bool:
        return self._manager.is_cancel_requested(self._job_id)

    def raise_if_cancelled(self) -> None:
        if self.is_cancel_requested():
            raise JobCancelledError("Job cancellation requested.")


@dataclass
class _BackgroundJobState:
    id: str
    label: str
    status: str
    progress: float
    message: str
    created_at: str
    started_at: str
    finished_at: str
    error: str
    cancel_requested: bool
    cancel_event: Event
    worker: BackgroundJobWorker
    retry_worker: BackgroundJobWorker
    retry_of: str
    metadata: dict[str, Any]
    result: Any
    future: Future[Any] | None
    order_index: int
    request_id: str
    current_stage: str
    stage_started_at: str
    stage_progress_start: float


class BackgroundJobManager:
    def __init__(self, *, max_workers: int = 2, telemetry_service: TelemetryService | None = None) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max(1, int(max_workers)))
        self._lock = Lock()
        self._jobs: dict[str, _BackgroundJobState] = {}
        self._order_counter = 0
        self._telemetry_service = telemetry_service
        self._duration_samples_by_asset: dict[str, list[float]] = {}
        self._stage_duration_samples: dict[str, list[float]] = {}

    def submit(
        self,
        *,
        label: str,
        worker: BackgroundJobWorker,
        metadata: dict[str, Any] | None = None,
        retry_worker: BackgroundJobWorker | None = None,
        retry_of: str = "",
    ) -> str:
        now_iso = self._now_iso()
        job_id = uuid4().hex[:16]
        metadata_payload = dict(metadata or {})
        request_id = " ".join(str(metadata_payload.get("request_id", "")).split()).strip() or create_request_id()
        metadata_payload["request_id"] = request_id
        state = _BackgroundJobState(
            id=job_id,
            label=" ".join(str(label).split()).strip() or "Background Job",
            status="queued",
            progress=0.0,
            message="Queued",
            created_at=now_iso,
            started_at="",
            finished_at="",
            error="",
            cancel_requested=False,
            cancel_event=Event(),
            worker=worker,
            retry_worker=retry_worker or worker,
            retry_of=" ".join(str(retry_of).split()).strip(),
            metadata=metadata_payload,
            result=None,
            future=None,
            order_index=0,
            request_id=request_id,
            current_stage="Queued",
            stage_started_at=now_iso,
            stage_progress_start=0.0,
        )

        with self._lock:
            self._order_counter += 1
            state.order_index = self._order_counter
            self._jobs[job_id] = state

        if self._telemetry_service is not None:
            with self._telemetry_service.context_scope(request_id=request_id, job_id=job_id):
                payload_ref = self._telemetry_service.attach_payload(
                    payload={"label": state.label, "metadata": metadata_payload},
                    kind="background_job_submit",
                )
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="background_job.submit",
                        component="background_jobs.manager",
                        status="queued",
                        timestamp=self._now_iso(),
                        attributes={"job_id": job_id, "label": state.label},
                        payload_ref=payload_ref,
                    )
                )
                self._telemetry_service.record_metric(
                    name="background_jobs_submitted_total",
                    value=1.0,
                    attrs={"label": state.label},
                )

        future = self._executor.submit(self._run_job, job_id)
        with self._lock:
            persisted = self._jobs.get(job_id)
            if persisted is not None:
                persisted.future = future
        return job_id

    def cancel(self, job_id: str) -> bool:
        normalized = " ".join(str(job_id).split()).strip()
        if not normalized:
            return False

        with self._lock:
            state = self._jobs.get(normalized)
            if state is None:
                return False
            if state.status in TERMINAL_JOB_STATUSES:
                return False
            state.cancel_requested = True
            state.cancel_event.set()
            if state.status == "queued":
                state.status = "cancel_requested"
                state.message = "Cancellation requested before start."
                self._transition_stage_locked(
                    state=state,
                    stage_name="Cancellation requested before start.",
                    switched_at=self._now_iso(),
                )
            elif state.status == "running":
                state.status = "cancel_requested"
                state.message = "Cancellation requested. Waiting for safe stop."
                self._transition_stage_locked(
                    state=state,
                    stage_name="Cancellation requested. Waiting for safe stop.",
                    switched_at=self._now_iso(),
                )

            future = state.future

        if future is not None and future.cancel():
            with self._lock:
                state = self._jobs.get(normalized)
                if state is None:
                    return True
                finished_at = self._now_iso()
                self._record_stage_duration_locked(state=state, ended_at=finished_at)
                state.status = "cancelled"
                state.progress = min(state.progress, 1.0)
                state.message = "Cancelled before execution."
                state.finished_at = finished_at
                self._record_job_duration_locked(state=state)
            return True
        return True

    def retry(self, job_id: str) -> str | None:
        normalized = " ".join(str(job_id).split()).strip()
        if not normalized:
            return None
        with self._lock:
            state = self._jobs.get(normalized)
            if state is None:
                return None
            if state.status not in TERMINAL_JOB_STATUSES:
                return None
            label = state.label
            worker = state.retry_worker
            metadata = dict(state.metadata)
        metadata.pop("request_id", None)
        return self.submit(
            label=f"{label} (retry)",
            worker=worker,
            metadata=metadata,
            retry_of=normalized,
        )

    def get_snapshot(self, job_id: str) -> BackgroundJobSnapshot | None:
        normalized = " ".join(str(job_id).split()).strip()
        if not normalized:
            return None
        request_id = ""
        asset_key = "generic"
        with self._lock:
            state = self._jobs.get(normalized)
            if state is None:
                return None
            request_id = state.request_id
            queued_before = [
                item
                for item in self._jobs.values()
                if item.status == "queued" and item.order_index < state.order_index
            ]
            queue_position = len(queued_before) + 1 if state.status == "queued" else None
            now_iso = self._now_iso()
            elapsed_seconds = self._elapsed_seconds(
                started_at=state.started_at,
                finished_at=state.finished_at,
                now_iso=now_iso,
            )
            asset_key = self._asset_key(metadata=state.metadata)
            historical_avg_duration_seconds = self._average_for_asset(asset_key)
            eta_seconds_remaining = self._eta_seconds(
                progress=state.progress,
                elapsed_seconds=elapsed_seconds,
                status=state.status,
                queue_position=queue_position,
                historical_avg_duration_seconds=historical_avg_duration_seconds,
            )
            estimated_finish_at = self._eta_iso(now_iso=now_iso, eta_seconds_remaining=eta_seconds_remaining)
            stage_elapsed_seconds = self._elapsed_seconds(
                started_at=state.stage_started_at,
                finished_at=state.finished_at if state.status in TERMINAL_JOB_STATUSES else "",
                now_iso=now_iso,
            )
            stage_eta_seconds_remaining = self._stage_eta_seconds(
                metadata=state.metadata,
                stage_name=state.current_stage,
                stage_elapsed_seconds=stage_elapsed_seconds,
            )
            asset_key = self._asset_key(metadata=state.metadata)
            snapshot = BackgroundJobSnapshot(
                id=state.id,
                label=state.label,
                status=state.status,
                progress=state.progress,
                message=state.message,
                created_at=state.created_at,
                started_at=state.started_at,
                finished_at=state.finished_at,
                error=state.error,
                cancel_requested=state.cancel_requested,
                retry_of=state.retry_of,
                queue_position=queue_position,
                metadata=dict(state.metadata),
                result=state.result,
                elapsed_seconds=elapsed_seconds,
                eta_seconds_remaining=eta_seconds_remaining,
                estimated_finish_at=estimated_finish_at,
                stage_name=state.current_stage,
                stage_elapsed_seconds=stage_elapsed_seconds,
                stage_eta_seconds_remaining=stage_eta_seconds_remaining,
                historical_avg_duration_seconds=historical_avg_duration_seconds,
            )
        if (
            self._telemetry_service is not None
            and asset_key == "cartoon_shorts"
            and snapshot.eta_seconds_remaining is not None
        ):
            with self._telemetry_service.context_scope(request_id=request_id, job_id=snapshot.id):
                self._telemetry_service.record_metric(
                    name="cartoon_background_eta_seconds",
                    value=float(snapshot.eta_seconds_remaining),
                    attrs={
                        "stage_name": snapshot.stage_name,
                        "status": snapshot.status,
                    },
                )
        return snapshot

    def is_cancel_requested(self, job_id: str) -> bool:
        normalized = " ".join(str(job_id).split()).strip()
        if not normalized:
            return False
        with self._lock:
            state = self._jobs.get(normalized)
            if state is None:
                return False
            return bool(state.cancel_requested or state.cancel_event.is_set())

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                return
            job_request_id = state.request_id

        with request_id_scope(job_request_id):
            telemetry_scope = (
                self._telemetry_service.context_scope(request_id=job_request_id, job_id=job_id)
                if self._telemetry_service is not None
                else _null_context()
            )
            with telemetry_scope:
                span_scope = (
                    self._telemetry_service.start_span(
                        name="background_job.run",
                        component="background_jobs.manager",
                        attrs={"job_id": job_id},
                    )
                    if self._telemetry_service is not None
                    else _null_context()
                )
                with span_scope:
                    with self._lock:
                        state = self._jobs.get(job_id)
                        if state is None:
                            return
                        if state.cancel_event.is_set():
                            finished_at = self._now_iso()
                            self._record_stage_duration_locked(state=state, ended_at=finished_at)
                            state.status = "cancelled"
                            state.message = "Cancelled before execution."
                            state.finished_at = finished_at
                            self._record_job_duration_locked(state=state)
                            return
                        state.status = "running"
                        state.started_at = self._now_iso()
                        state.message = "Running"
                        state.progress = max(state.progress, 0.01)
                        self._transition_stage_locked(state=state, stage_name="Running", switched_at=state.started_at)

                    context = BackgroundJobContext(manager=self, job_id=job_id)
                    try:
                        context.raise_if_cancelled()
                        result = state.worker(context)
                        context.raise_if_cancelled()
                        with self._lock:
                            persisted = self._jobs.get(job_id)
                            if persisted is None:
                                return
                            finished_at = self._now_iso()
                            self._record_stage_duration_locked(state=persisted, ended_at=finished_at)
                            persisted.result = result
                            persisted.status = "completed"
                            persisted.progress = 1.0
                            persisted.message = "Completed"
                            persisted.finished_at = finished_at
                            self._record_job_duration_locked(state=persisted)
                        if self._telemetry_service is not None:
                            self._telemetry_service.record_metric(
                                name="background_jobs_completed_total",
                                value=1.0,
                                attrs={},
                            )
                            self._telemetry_service.record_event(
                                ObservabilityEvent(
                                    event_name="background_job.end",
                                    component="background_jobs.manager",
                                    status="completed",
                                    timestamp=self._now_iso(),
                                    attributes={"job_id": job_id},
                                )
                            )
                    except JobCancelledError:
                        with self._lock:
                            persisted = self._jobs.get(job_id)
                            if persisted is None:
                                return
                            finished_at = self._now_iso()
                            self._record_stage_duration_locked(state=persisted, ended_at=finished_at)
                            persisted.status = "cancelled"
                            persisted.message = "Cancelled"
                            persisted.finished_at = finished_at
                            self._record_job_duration_locked(state=persisted)
                        if self._telemetry_service is not None:
                            self._telemetry_service.record_metric(
                                name="background_jobs_cancelled_total",
                                value=1.0,
                                attrs={},
                            )
                            self._telemetry_service.record_event(
                                ObservabilityEvent(
                                    event_name="background_job.end",
                                    component="background_jobs.manager",
                                    status="cancelled",
                                    timestamp=self._now_iso(),
                                    attributes={"job_id": job_id},
                                )
                            )
                    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError, OSError) as exc:
                        with self._lock:
                            persisted = self._jobs.get(job_id)
                            if persisted is None:
                                return
                            finished_at = self._now_iso()
                            self._record_stage_duration_locked(state=persisted, ended_at=finished_at)
                            persisted.status = "failed"
                            persisted.error = str(exc)
                            persisted.message = "Failed"
                            persisted.finished_at = finished_at
                            self._record_job_duration_locked(state=persisted)
                        if self._telemetry_service is not None:
                            self._telemetry_service.record_metric(
                                name="background_jobs_failed_total",
                                value=1.0,
                                attrs={},
                            )
                            self._telemetry_service.record_event(
                                ObservabilityEvent(
                                    event_name="background_job.end",
                                    component="background_jobs.manager",
                                    status="failed",
                                    timestamp=self._now_iso(),
                                    attributes={"job_id": job_id, "error": str(exc)},
                                )
                            )

    def _set_progress(self, *, job_id: str, progress: float, message: str | None) -> None:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                return
            if state.status in TERMINAL_JOB_STATUSES:
                return
            bounded = min(max(float(progress), 0.0), 1.0)
            state.progress = bounded
            if message is not None:
                cleaned = " ".join(str(message).split()).strip()
                if cleaned:
                    state.message = cleaned
                    self._transition_stage_locked(
                        state=state,
                        stage_name=cleaned,
                        switched_at=self._now_iso(),
                    )

    @staticmethod
    def _sample_push(samples: list[float], value: float, *, max_size: int = 32) -> None:
        samples.append(value)
        if len(samples) > max_size:
            del samples[: len(samples) - max_size]

    @staticmethod
    def _asset_key(*, metadata: dict[str, Any]) -> str:
        value = " ".join(str(metadata.get("asset", "generic")).split()).strip().lower()
        return value or "generic"

    def _average_for_asset(self, asset_key: str) -> float | None:
        samples = self._duration_samples_by_asset.get(asset_key, [])
        if not samples:
            return None
        return float(sum(samples) / len(samples))

    def _average_stage_duration(self, *, metadata: dict[str, Any], stage_name: str) -> float | None:
        if not stage_name:
            return None
        asset_key = self._asset_key(metadata=metadata)
        stage_key = f"{asset_key}::{stage_name.strip().lower()}"
        samples = self._stage_duration_samples.get(stage_key, [])
        if not samples:
            return None
        return float(sum(samples) / len(samples))

    @classmethod
    def _elapsed_seconds(
        cls,
        *,
        started_at: str,
        finished_at: str,
        now_iso: str,
    ) -> float | None:
        if not started_at:
            return None
        started = cls._parse_iso(started_at)
        ended = cls._parse_iso(finished_at) if finished_at else cls._parse_iso(now_iso)
        if started is None or ended is None:
            return None
        return max((ended - started).total_seconds(), 0.0)

    @staticmethod
    def _eta_seconds(
        *,
        progress: float,
        elapsed_seconds: float | None,
        status: str,
        queue_position: int | None,
        historical_avg_duration_seconds: float | None,
    ) -> float | None:
        if status in TERMINAL_JOB_STATUSES:
            return 0.0
        if status == "queued":
            if queue_position is None or historical_avg_duration_seconds is None:
                return None
            return max(float(queue_position) * historical_avg_duration_seconds, 0.0)
        if elapsed_seconds is None:
            return None
        bounded_progress = min(max(float(progress), 0.0), 1.0)
        if bounded_progress > 0.0:
            projected_total = elapsed_seconds / bounded_progress
            return max(projected_total - elapsed_seconds, 0.0)
        if historical_avg_duration_seconds is not None:
            return max(historical_avg_duration_seconds - elapsed_seconds, 0.0)
        return None

    @classmethod
    def _eta_iso(cls, *, now_iso: str, eta_seconds_remaining: float | None) -> str:
        if eta_seconds_remaining is None:
            return ""
        now_dt = cls._parse_iso(now_iso)
        if now_dt is None:
            return ""
        return (now_dt + timedelta(seconds=max(eta_seconds_remaining, 0.0))).replace(microsecond=0).isoformat()

    def _stage_eta_seconds(
        self,
        *,
        metadata: dict[str, Any],
        stage_name: str,
        stage_elapsed_seconds: float | None,
    ) -> float | None:
        if stage_elapsed_seconds is None or not stage_name:
            return None
        average = self._average_stage_duration(metadata=metadata, stage_name=stage_name)
        if average is None:
            return None
        return max(average - stage_elapsed_seconds, 0.0)

    def _transition_stage_locked(self, *, state: _BackgroundJobState, stage_name: str, switched_at: str) -> None:
        cleaned_stage = " ".join(str(stage_name).split()).strip()
        if not cleaned_stage:
            return
        if cleaned_stage == state.current_stage:
            return
        self._record_stage_duration_locked(state=state, ended_at=switched_at)
        state.current_stage = cleaned_stage
        state.stage_started_at = switched_at
        state.stage_progress_start = state.progress

    def _record_stage_duration_locked(self, *, state: _BackgroundJobState, ended_at: str) -> None:
        if not state.current_stage or not state.stage_started_at:
            return
        duration_seconds = self._elapsed_seconds(
            started_at=state.stage_started_at,
            finished_at=ended_at,
            now_iso=ended_at,
        )
        if duration_seconds is None or duration_seconds <= 0.0:
            return
        asset_key = self._asset_key(metadata=state.metadata)
        stage_key = f"{asset_key}::{state.current_stage.strip().lower()}"
        samples = self._stage_duration_samples.setdefault(stage_key, [])
        self._sample_push(samples, duration_seconds)

    def _record_job_duration_locked(self, *, state: _BackgroundJobState) -> None:
        if not state.started_at or not state.finished_at:
            return
        duration_seconds = self._elapsed_seconds(
            started_at=state.started_at,
            finished_at=state.finished_at,
            now_iso=state.finished_at,
        )
        if duration_seconds is None or duration_seconds <= 0.0:
            return
        asset_key = self._asset_key(metadata=state.metadata)
        samples = self._duration_samples_by_asset.setdefault(asset_key, [])
        self._sample_push(samples, duration_seconds)

    @staticmethod
    def _parse_iso(value: str) -> datetime | None:
        text = " ".join(str(value).split()).strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

@contextmanager
def _null_context() -> Iterator[None]:
    yield
