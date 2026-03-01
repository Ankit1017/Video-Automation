from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, Lock
from typing import Any, Callable
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


class BackgroundJobManager:
    def __init__(self, *, max_workers: int = 2, telemetry_service: TelemetryService | None = None) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max(1, int(max_workers)))
        self._lock = Lock()
        self._jobs: dict[str, _BackgroundJobState] = {}
        self._order_counter = 0
        self._telemetry_service = telemetry_service

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
            elif state.status == "running":
                state.status = "cancel_requested"
                state.message = "Cancellation requested. Waiting for safe stop."

            future = state.future

        if future is not None and future.cancel():
            with self._lock:
                state = self._jobs.get(normalized)
                if state is None:
                    return True
                state.status = "cancelled"
                state.progress = min(state.progress, 1.0)
                state.message = "Cancelled before execution."
                state.finished_at = self._now_iso()
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
        with self._lock:
            state = self._jobs.get(normalized)
            if state is None:
                return None
            queued_before = [
                item
                for item in self._jobs.values()
                if item.status == "queued" and item.order_index < state.order_index
            ]
            queue_position = len(queued_before) + 1 if state.status == "queued" else None
            return BackgroundJobSnapshot(
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
            )

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
                            state.status = "cancelled"
                            state.message = "Cancelled before execution."
                            state.finished_at = self._now_iso()
                            return
                        state.status = "running"
                        state.started_at = self._now_iso()
                        state.message = "Running"
                        state.progress = max(state.progress, 0.01)

                    context = BackgroundJobContext(manager=self, job_id=job_id)
                    try:
                        context.raise_if_cancelled()
                        result = state.worker(context)
                        context.raise_if_cancelled()
                        with self._lock:
                            persisted = self._jobs.get(job_id)
                            if persisted is None:
                                return
                            persisted.result = result
                            persisted.status = "completed"
                            persisted.progress = 1.0
                            persisted.message = "Completed"
                            persisted.finished_at = self._now_iso()
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
                            persisted.status = "cancelled"
                            persisted.message = "Cancelled"
                            persisted.finished_at = self._now_iso()
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
                            persisted.status = "failed"
                            persisted.error = str(exc)
                            persisted.message = "Failed"
                            persisted.finished_at = self._now_iso()
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

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


from contextlib import contextmanager
from typing import Iterator


@contextmanager
def _null_context() -> Iterator[None]:
    yield
