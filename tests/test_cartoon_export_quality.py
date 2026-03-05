from __future__ import annotations

import unittest

from main_app.services.cartoon_export_service import (
    _resolve_background_style,
    _resolve_quality_tier,
    _resolve_render_style,
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

    def test_render_and_background_style_resolution(self) -> None:
        self.assertEqual(_resolve_render_style(payload={"metadata": {"render_style": "character_showcase"}}), "character_showcase")
        self.assertEqual(_resolve_render_style(payload={"metadata": {"render_style": "scene"}}), "scene")
        self.assertEqual(
            _resolve_background_style(payload={"metadata": {"background_style": "auto"}}, render_style="character_showcase"),
            "chroma_green",
        )
        self.assertEqual(
            _resolve_background_style(payload={"metadata": {"background_style": "auto"}}, render_style="scene"),
            "scene",
        )


if __name__ == "__main__":
    unittest.main()
