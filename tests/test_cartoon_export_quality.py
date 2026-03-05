from __future__ import annotations

import unittest

from main_app.services.cartoon_export_service import (
    _resolve_quality_tier,
    _tier_adjusted_fps,
)


class TestCartoonExportQuality(unittest.TestCase):
    def test_auto_quality_maps_from_profile(self) -> None:
        self.assertEqual(
            _resolve_quality_tier(payload={"metadata": {"quality_tier": "auto"}}, profile={"profile_key": "gpu_high"}),
            "high",
        )
        self.assertEqual(
            _resolve_quality_tier(payload={"metadata": {"quality_tier": "auto"}}, profile={"profile_key": "gpu_balanced"}),
            "balanced",
        )
        self.assertEqual(
            _resolve_quality_tier(payload={"metadata": {"quality_tier": "auto"}}, profile={"profile_key": "cpu_safe"}),
            "light",
        )

    def test_tier_adjusted_fps_changes_by_tier(self) -> None:
        self.assertGreaterEqual(_tier_adjusted_fps(24, quality_tier="high"), 30)
        self.assertLessEqual(_tier_adjusted_fps(24, quality_tier="light"), 24)
        self.assertGreaterEqual(_tier_adjusted_fps(24, quality_tier="balanced"), 16)


if __name__ == "__main__":
    unittest.main()
