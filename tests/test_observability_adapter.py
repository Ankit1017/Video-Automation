from __future__ import annotations

import unittest

from main_app.services.observability_service import ObservabilityService


class TestObservabilityAdapter(unittest.TestCase):
    def test_record_llm_call_updates_legacy_metrics_and_telemetry_adapter(self) -> None:
        service = ObservabilityService(
            default_input_cost_per_1m_usd=1.0,
            default_output_cost_per_1m_usd=1.0,
        )
        service.record_llm_call(
            task="topic_explainer",
            model="test-model",
            cache_hit=False,
            latency_ms=123.4,
            request_id="req_test",
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            error="",
        )
        rows = service.metrics_table_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["asset"], "topic")
        self.assertEqual(rows[0]["llm_calls"], 1)
        self.assertEqual(rows[0]["total_tokens"], 1500)


if __name__ == "__main__":
    unittest.main()
