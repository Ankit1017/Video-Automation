from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from main_app.services.telemetry_service import PayloadVault, TelemetryService


class _NoopOTelBridge:
    @property
    def enabled(self) -> bool:
        return False

    def start_span(self, *, name: str, attributes: dict[str, object]):  # noqa: ANN001
        from contextlib import contextmanager

        @contextmanager
        def _scope():
            yield "", ""

        return _scope()

    def record_event(self, *, name: str, attributes: dict[str, object]) -> None:  # noqa: ANN001
        del name, attributes

    def record_metric(self, *, name: str, value: float, attributes: dict[str, object]) -> None:  # noqa: ANN001
        del name, value, attributes


class TestTelemetryService(unittest.TestCase):
    def test_context_scope_propagates_ids(self) -> None:
        service = TelemetryService(otel_bridge=_NoopOTelBridge())
        with service.context_scope(request_id="req_1", session_id="sess_1", run_id="run_1", job_id="job_1"):
            context = service.current_context()
            self.assertEqual(context.request_id, "req_1")
            self.assertEqual(context.session_id, "sess_1")
            self.assertEqual(context.run_id, "run_1")
            self.assertEqual(context.job_id, "job_1")

    def test_start_span_generates_trace_and_span_ids(self) -> None:
        service = TelemetryService(otel_bridge=_NoopOTelBridge())
        with service.context_scope(request_id="req_2"):
            with service.start_span(name="test.span", component="unit.test"):
                context = service.current_context()
                self.assertEqual(context.request_id, "req_2")
                self.assertTrue(len(context.trace_id) >= 16)
                self.assertTrue(len(context.span_id) >= 8)

    def test_payload_vault_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = PayloadVault(
                vault_dir=Path(temp_dir),
                capture_enabled=True,
                encryption_enabled=False,
                retention_days=14,
            )
            service = TelemetryService(payload_vault=vault, otel_bridge=_NoopOTelBridge())
            with service.context_scope(request_id="req_3", run_id="run_3"):
                payload_ref = service.attach_payload(payload={"hello": "world"}, kind="unit_payload")
            self.assertTrue(payload_ref.startswith("payload_"))
            payload = service.fetch_payload(payload_ref)
            self.assertIsInstance(payload, dict)
            assert payload is not None
            self.assertEqual(payload.get("kind"), "unit_payload")
            nested = payload.get("payload")
            self.assertTrue(isinstance(nested, dict))
            self.assertEqual(nested.get("hello"), "world")


if __name__ == "__main__":
    unittest.main()
