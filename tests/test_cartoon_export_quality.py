from __future__ import annotations

import unittest

from main_app.services.cartoon_export_service import (
    _resolve_background_style,
    _resolve_fidelity_preset,
    _resolve_quality_tier,
    _resolve_render_style,
    _resolve_showcase_avatar_mode,
    _target_bitrate_kbps,
    _tier_adjusted_fps,
    CartoonExportService,
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

    def test_fidelity_preset_resolution(self) -> None:
        self.assertEqual(_resolve_fidelity_preset(payload={"metadata": {"fidelity_preset": "auto_profile"}}), "auto_profile")
        self.assertEqual(_resolve_fidelity_preset(payload={"metadata": {"fidelity_preset": "hd_1080p30"}}), "hd_1080p30")
        self.assertEqual(_resolve_fidelity_preset(payload={"metadata": {"fidelity_preset": "uhd_4k30"}}), "uhd_4k30")
        self.assertEqual(_resolve_fidelity_preset(payload={"metadata": {"fidelity_preset": "bad"}}), "auto_profile")

    def test_bitrate_targets_by_preset(self) -> None:
        self.assertEqual(
            _target_bitrate_kbps(
                width=1920,
                height=1080,
                fps=30,
                quality_tier="balanced",
                fidelity_preset="hd_1080p30",
            ),
            6500,
        )
        self.assertEqual(
            _target_bitrate_kbps(
                width=3840,
                height=2160,
                fps=30,
                quality_tier="balanced",
                fidelity_preset="uhd_4k30",
            ),
            18000,
        )

    def test_build_targets_applies_fidelity_preset_dimensions(self) -> None:
        service = CartoonExportService()
        targets = service._build_targets(  # noqa: SLF001
            profile={
                "shorts_width": 540,
                "shorts_height": 960,
                "widescreen_width": 960,
                "widescreen_height": 540,
                "fps": 20,
            },
            output_mode="dual",
            quality_tier="light",
            fidelity_preset="hd_1080p30",
        )
        target_map = {target.key: target for target in targets}
        self.assertEqual(target_map["shorts_9_16"].width, 1080)
        self.assertEqual(target_map["shorts_9_16"].height, 1920)
        self.assertEqual(target_map["widescreen_16_9"].width, 1920)
        self.assertEqual(target_map["widescreen_16_9"].height, 1080)
        self.assertEqual(target_map["shorts_9_16"].fps, 30)

    def test_showcase_avatar_mode_resolution(self) -> None:
        self.assertEqual(
            _resolve_showcase_avatar_mode(
                payload={"metadata": {"showcase_avatar_mode": "cache_sprite"}},
                render_style="character_showcase",
            ),
            "cache_sprite",
        )
        self.assertEqual(
            _resolve_showcase_avatar_mode(
                payload={"metadata": {"showcase_avatar_mode": "procedural_presenter"}},
                render_style="character_showcase",
            ),
            "procedural_presenter",
        )
        self.assertEqual(
            _resolve_showcase_avatar_mode(
                payload={"metadata": {"showcase_avatar_mode": "auto", "pack_motion_warning_count": 6}},
                render_style="character_showcase",
            ),
            "procedural_presenter",
        )


if __name__ == "__main__":
    unittest.main()
