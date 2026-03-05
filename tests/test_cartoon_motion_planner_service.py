from __future__ import annotations

import unittest

from main_app.services.cartoon_motion_planner_service import CartoonMotionPlannerService


class TestCartoonMotionPlannerService(unittest.TestCase):
    def setUp(self) -> None:
        self.service = CartoonMotionPlannerService()
        self.scene = {
            "camera_track": {
                "keyframes": [
                    {"t_ms": 0, "x": 0.0, "y": 0.0, "zoom": 1.0, "rotation": 0.0, "ease": "linear"},
                    {"t_ms": 1000, "x": 100.0, "y": -10.0, "zoom": 1.2, "rotation": 5.0, "ease": "linear"},
                ]
            },
            "character_tracks": [
                {
                    "character_id": "ava",
                    "keyframes": [
                        {
                            "t_ms": 0,
                            "x_norm": 0.2,
                            "y_norm": 0.7,
                            "scale": 1.0,
                            "rotation": 0.0,
                            "pose": "idle",
                            "emotion": "neutral",
                            "opacity": 1.0,
                            "z_index": 1,
                            "ease": "linear",
                        },
                        {
                            "t_ms": 1000,
                            "x_norm": 0.6,
                            "y_norm": 0.7,
                            "scale": 1.2,
                            "rotation": 0.0,
                            "pose": "idle",
                            "emotion": "neutral",
                            "opacity": 1.0,
                            "z_index": 1,
                            "ease": "linear",
                        },
                    ],
                }
            ],
        }

    def test_plan_frame_interpolates_camera_and_character_track(self) -> None:
        plan = self.service.plan_frame(
            scene=self.scene,
            character_roster=[{"id": "ava", "name": "Ava"}],
            scene_relative_ms=500,
            scene_duration_ms=1000,
            active_turn={"speaker_id": "ava"},
            active_mouth="A",
        )
        camera = plan.get("camera", {})
        assert isinstance(camera, dict)
        self.assertAlmostEqual(float(camera.get("x", 0.0)), 50.0, delta=1.0)
        characters = plan.get("characters", [])
        assert isinstance(characters, list) and characters
        first = characters[0]
        assert isinstance(first, dict)
        self.assertAlmostEqual(float(first.get("x_norm", 0.0)), 0.4, delta=0.05)
        self.assertEqual(first.get("state"), "talk")
        self.assertEqual(first.get("viseme"), "A")

    def test_blink_precedence_over_talk(self) -> None:
        plan = self.service.plan_frame(
            scene=self.scene,
            character_roster=[{"id": "ava", "name": "Ava"}],
            scene_relative_ms=0,
            scene_duration_ms=1000,
            active_turn={"speaker_id": "ava"},
            active_mouth="E",
        )
        characters = plan.get("characters", [])
        assert isinstance(characters, list) and characters
        first = characters[0]
        assert isinstance(first, dict)
        self.assertEqual(first.get("state"), "blink")
        self.assertEqual(first.get("viseme"), "X")


if __name__ == "__main__":
    unittest.main()
