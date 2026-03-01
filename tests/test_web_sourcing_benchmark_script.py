from __future__ import annotations

import unittest

from scripts.benchmark_web_sourcing import _is_hard_provider_exhausted, _summarize


class TestWebSourcingBenchmarkScript(unittest.TestCase):
    def test_hard_provider_exhausted_detection(self) -> None:
        self.assertTrue(
            _is_hard_provider_exhausted(
                [{"status": "provider_unavailable"}, {"status": "search_error"}],
                accepted_count=0,
            )
        )
        self.assertFalse(
            _is_hard_provider_exhausted(
                [{"status": "accepted_empty"}],
                accepted_count=0,
            )
        )
        self.assertFalse(
            _is_hard_provider_exhausted(
                [{"status": "provider_unavailable"}],
                accepted_count=1,
            )
        )

    def test_summary_metrics_shape(self) -> None:
        rows = [
            {
                "pass": True,
                "accepted_count": 2,
                "quality_avg": 0.7,
                "fallback_quality_mode_used": False,
                "failover_used": True,
            },
            {
                "pass": False,
                "accepted_count": 0,
                "quality_avg": 0.2,
                "fallback_quality_mode_used": True,
                "failover_used": False,
            },
        ]
        summary = _summarize(rows)
        self.assertEqual(summary["total_queries"], 2)
        self.assertEqual(summary["passed_queries"], 1)
        self.assertAlmostEqual(float(summary["pass_rate"]), 0.5, places=4)
        self.assertIn("avg_accepted_count", summary)
        self.assertIn("avg_quality_score", summary)


if __name__ == "__main__":
    unittest.main()
