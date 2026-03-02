from __future__ import annotations

import time
import unittest
from threading import Event

from main_app.services.background_jobs import (
    BackgroundJobContext,
    BackgroundJobManager,
    JobCancelledError,
)
from main_app.services.observability_service import get_request_id


def _wait_for_terminal(
    manager: BackgroundJobManager,
    job_id: str,
    *,
    timeout_seconds: float = 5.0,
) -> str:
    deadline = time.time() + timeout_seconds
    last_status = ""
    while time.time() < deadline:
        snapshot = manager.get_snapshot(job_id)
        if snapshot is None:
            raise AssertionError("Job snapshot not found.")
        last_status = snapshot.status
        if snapshot.is_terminal:
            return snapshot.status
        time.sleep(0.03)
    raise AssertionError(f"Job did not reach terminal state. Last status: {last_status}")


class TestBackgroundJobManager(unittest.TestCase):
    def test_submit_tracks_progress_and_result(self) -> None:
        manager = BackgroundJobManager(max_workers=1)
        self.addCleanup(manager.shutdown, wait=True)

        def _worker(context: BackgroundJobContext) -> dict[str, str]:
            context.update_progress(progress=0.35, message="Step one done")
            time.sleep(0.05)
            context.update_progress(progress=0.9, message="Finalizing")
            return {"status": "ok"}

        job_id = manager.submit(label="Progress Job", worker=_worker)
        terminal_status = _wait_for_terminal(manager, job_id)
        self.assertEqual(terminal_status, "completed")

        snapshot = manager.get_snapshot(job_id)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.status, "completed")
        self.assertEqual(snapshot.result, {"status": "ok"})
        self.assertGreaterEqual(snapshot.progress, 1.0)
        self.assertIsNotNone(snapshot.elapsed_seconds)
        self.assertEqual(snapshot.eta_seconds_remaining, 0.0)

    def test_cancel_queued_job(self) -> None:
        manager = BackgroundJobManager(max_workers=1)
        self.addCleanup(manager.shutdown, wait=True)
        gate = Event()
        started = Event()

        def _blocking_worker(context: BackgroundJobContext) -> str:
            started.set()
            while not gate.is_set():
                context.raise_if_cancelled()
                time.sleep(0.02)
            return "done"

        def _queued_worker(context: BackgroundJobContext) -> str:
            context.update_progress(progress=0.5, message="Should not run")
            return "queued-done"

        first_job = manager.submit(label="Blocking", worker=_blocking_worker)
        started.wait(timeout=1.0)
        queued_job = manager.submit(label="Queued", worker=_queued_worker)

        cancelled = manager.cancel(queued_job)
        self.assertTrue(cancelled)

        gate.set()
        _wait_for_terminal(manager, first_job)
        terminal_status = _wait_for_terminal(manager, queued_job)
        self.assertEqual(terminal_status, "cancelled")

    def test_queued_job_reports_queue_position(self) -> None:
        manager = BackgroundJobManager(max_workers=1)
        self.addCleanup(manager.shutdown, wait=True)
        gate = Event()
        started = Event()

        def _blocking_worker(context: BackgroundJobContext) -> str:
            started.set()
            while not gate.is_set():
                context.raise_if_cancelled()
                time.sleep(0.02)
            return "done"

        def _queued_worker(_context: BackgroundJobContext) -> str:
            return "queued-done"

        first_job = manager.submit(label="Blocking", worker=_blocking_worker)
        started.wait(timeout=1.0)
        queued_job = manager.submit(label="Queued", worker=_queued_worker)

        queued_snapshot = manager.get_snapshot(queued_job)
        self.assertIsNotNone(queued_snapshot)
        assert queued_snapshot is not None
        self.assertEqual(queued_snapshot.status, "queued")
        self.assertEqual(queued_snapshot.queue_position, 1)

        gate.set()
        _wait_for_terminal(manager, first_job)
        _wait_for_terminal(manager, queued_job)

    def test_running_job_exposes_tentative_eta(self) -> None:
        manager = BackgroundJobManager(max_workers=1)
        self.addCleanup(manager.shutdown, wait=True)
        stage_entered = Event()
        release = Event()

        def _worker(context: BackgroundJobContext) -> str:
            context.update_progress(progress=0.25, message="Generating payload")
            stage_entered.set()
            for _ in range(250):
                if release.is_set():
                    break
                time.sleep(0.02)
            context.update_progress(progress=1.0, message="Done")
            return "ok"

        job_id = manager.submit(label="ETA Running", worker=_worker, metadata={"asset": "video"})
        stage_entered.wait(timeout=1.0)
        time.sleep(0.08)
        snapshot = manager.get_snapshot(job_id)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.status, "running")
        self.assertEqual(snapshot.stage_name, "Generating payload")
        self.assertIsNotNone(snapshot.elapsed_seconds)
        self.assertIsNotNone(snapshot.eta_seconds_remaining)
        self.assertTrue(bool(snapshot.estimated_finish_at))
        release.set()
        _wait_for_terminal(manager, job_id)

    def test_queued_job_eta_uses_historical_asset_average(self) -> None:
        manager = BackgroundJobManager(max_workers=1)
        self.addCleanup(manager.shutdown, wait=True)
        release_first = Event()
        first_started = Event()

        def _first_worker(context: BackgroundJobContext) -> str:
            context.update_progress(progress=0.2, message="Stage A")
            first_started.set()
            for _ in range(250):
                if release_first.is_set():
                    break
                time.sleep(0.02)
            context.update_progress(progress=1.0, message="Done")
            return "done"

        first_job = manager.submit(label="First", worker=_first_worker, metadata={"asset": "video"})
        first_started.wait(timeout=1.0)
        release_first.set()
        _wait_for_terminal(manager, first_job)

        block_gate = Event()
        blocker_started = Event()

        def _blocking_worker(context: BackgroundJobContext) -> str:
            context.update_progress(progress=0.15, message="Blocking stage")
            blocker_started.set()
            for _ in range(250):
                if block_gate.is_set():
                    break
                time.sleep(0.02)
            context.update_progress(progress=1.0, message="Done")
            return "done"

        def _queued_worker(_context: BackgroundJobContext) -> str:
            return "queued-done"

        blocking_job = manager.submit(label="Blocking", worker=_blocking_worker, metadata={"asset": "video"})
        blocker_started.wait(timeout=1.0)
        queued_job = manager.submit(label="Queued ETA", worker=_queued_worker, metadata={"asset": "video"})
        queued_snapshot = manager.get_snapshot(queued_job)
        self.assertIsNotNone(queued_snapshot)
        assert queued_snapshot is not None
        self.assertEqual(queued_snapshot.status, "queued")
        self.assertEqual(queued_snapshot.queue_position, 1)
        self.assertIsNotNone(queued_snapshot.historical_avg_duration_seconds)
        self.assertIsNotNone(queued_snapshot.eta_seconds_remaining)
        self.assertTrue(bool(queued_snapshot.estimated_finish_at))
        block_gate.set()
        _wait_for_terminal(manager, blocking_job)
        _wait_for_terminal(manager, queued_job)

    def test_cancel_running_job(self) -> None:
        manager = BackgroundJobManager(max_workers=1)
        self.addCleanup(manager.shutdown, wait=True)
        loop_started = Event()

        def _running_worker(context: BackgroundJobContext) -> str:
            loop_started.set()
            for _ in range(150):
                context.raise_if_cancelled()
                time.sleep(0.01)
            return "not-cancelled"

        job_id = manager.submit(label="Running Cancel", worker=_running_worker)
        loop_started.wait(timeout=1.0)
        manager.cancel(job_id)

        terminal_status = _wait_for_terminal(manager, job_id)
        self.assertEqual(terminal_status, "cancelled")

    def test_retry_terminal_job_creates_new_job(self) -> None:
        manager = BackgroundJobManager(max_workers=1)
        self.addCleanup(manager.shutdown, wait=True)

        def _failing_worker(_context: BackgroundJobContext) -> str:
            raise RuntimeError("forced failure")

        failed_job = manager.submit(label="Failing", worker=_failing_worker)
        first_status = _wait_for_terminal(manager, failed_job)
        self.assertEqual(first_status, "failed")

        retry_job = manager.retry(failed_job)
        self.assertIsNotNone(retry_job)
        assert retry_job is not None
        second_status = _wait_for_terminal(manager, retry_job)
        self.assertEqual(second_status, "failed")

        retry_snapshot = manager.get_snapshot(retry_job)
        self.assertIsNotNone(retry_snapshot)
        assert retry_snapshot is not None
        self.assertEqual(retry_snapshot.retry_of, failed_job)

    def test_worker_can_signal_cancel_explicitly(self) -> None:
        manager = BackgroundJobManager(max_workers=1)
        self.addCleanup(manager.shutdown, wait=True)

        def _cancelled_worker(_context: BackgroundJobContext) -> str:
            raise JobCancelledError("cancelled by worker")

        job_id = manager.submit(label="Explicit Cancel", worker=_cancelled_worker)
        terminal_status = _wait_for_terminal(manager, job_id)
        self.assertEqual(terminal_status, "cancelled")

    def test_each_background_job_has_isolated_request_id_scope(self) -> None:
        manager = BackgroundJobManager(max_workers=1)
        self.addCleanup(manager.shutdown, wait=True)

        def _request_id_worker(_context: BackgroundJobContext) -> str:
            return get_request_id()

        job_a = manager.submit(label="Req A", worker=_request_id_worker)
        job_b = manager.submit(label="Req B", worker=_request_id_worker)

        _wait_for_terminal(manager, job_a)
        _wait_for_terminal(manager, job_b)

        snapshot_a = manager.get_snapshot(job_a)
        snapshot_b = manager.get_snapshot(job_b)
        self.assertIsNotNone(snapshot_a)
        self.assertIsNotNone(snapshot_b)
        assert snapshot_a is not None
        assert snapshot_b is not None
        self.assertTrue(str(snapshot_a.result).startswith("req_"))
        self.assertTrue(str(snapshot_b.result).startswith("req_"))
        self.assertNotEqual(snapshot_a.result, snapshot_b.result)


if __name__ == "__main__":
    unittest.main()
