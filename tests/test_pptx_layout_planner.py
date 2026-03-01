from __future__ import annotations

import unittest

from main_app.services.pptx_export.layout_planner import plan_slide_layout


class TestPptxLayoutPlanner(unittest.TestCase):
    def test_code_snippet_forces_split_code_layout(self) -> None:
        plan = plan_slide_layout(
            slide={
                "title": "Implementation",
                "representation": "timeline",
                "layout_payload": {
                    "events": [{"label": "Kickoff", "detail": "Started project"}],
                },
                "code_snippet": "```python\nprint('hello')\n```",
                "code_language": "python",
                "bullets": ["Explain the snippet."],
            }
        )

        self.assertEqual(plan.layout_type, "split_code")
        self.assertEqual(plan.code_language, "python")
        self.assertIn("print('hello')", plan.code_snippet)

    def test_two_column_maps_to_dual_column_layout(self) -> None:
        plan = plan_slide_layout(
            slide={
                "title": "Tradeoffs",
                "representation": "two_column",
                "layout_payload": {
                    "left_title": "Pros",
                    "left_items": ["Fast", "Simple"],
                    "right_title": "Cons",
                    "right_items": ["Cost", "Risk"],
                },
            }
        )

        self.assertEqual(plan.layout_type, "dual_column")
        self.assertEqual(plan.left_title, "Pros")
        self.assertEqual(plan.right_title, "Cons")
        self.assertEqual(plan.left_items, ["Fast", "Simple"])
        self.assertEqual(plan.right_items, ["Cost", "Risk"])

    def test_timeline_overflow_falls_back_to_summary(self) -> None:
        dense_detail = " ".join(["very-dense"] * 120)
        plan = plan_slide_layout(
            slide={
                "title": "Roadmap",
                "representation": "timeline",
                "layout_payload": {
                    "events": [
                        {"label": "Phase 1", "detail": dense_detail},
                        {"label": "Phase 2", "detail": dense_detail},
                        {"label": "Phase 3", "detail": dense_detail},
                    ]
                },
                "bullets": ["Fallback summary bullet."],
            }
        )

        self.assertEqual(plan.layout_type, "summary")
        self.assertEqual(plan.bullets[0], "Fallback summary bullet.")

    def test_process_flow_maps_to_process_layout(self) -> None:
        plan = plan_slide_layout(
            slide={
                "title": "Pipeline",
                "representation": "process_flow",
                "layout_payload": {
                    "steps": [
                        {"title": "Ingest", "detail": "Collect input"},
                        {"title": "Transform", "detail": "Normalize output"},
                    ]
                },
            }
        )

        self.assertEqual(plan.layout_type, "process_flow")
        self.assertEqual(plan.steps[0]["title"], "Ingest")

    def test_metric_cards_maps_to_metric_layout(self) -> None:
        plan = plan_slide_layout(
            slide={
                "title": "KPIs",
                "representation": "metric_cards",
                "layout_payload": {
                    "cards": [
                        {"label": "Latency", "value": "120ms", "context": "p95"},
                    ]
                },
            }
        )

        self.assertEqual(plan.layout_type, "metric_cards")
        self.assertEqual(plan.cards[0]["label"], "Latency")


if __name__ == "__main__":
    unittest.main()
