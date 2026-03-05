from __future__ import annotations

import unittest

from main_app.services.cartoon_timeline_service import CartoonTimelineService


class TestCartoonTimelineV2(unittest.TestCase):
    def test_v2_rejects_scene_without_required_tracks(self) -> None:
        service = CartoonTimelineService()
        timeline, notes = service.normalize_timeline(
            timeline={
                "scenes": [
                    {
                        "scene_index": 1,
                        "title": "Intro",
                        "turns": [{"speaker_id": "ava", "speaker_name": "Ava", "text": "Hello"}],
                    }
                ]
            },
            timeline_schema_version="v2",
            character_roster=[{"id": "ava"}],
        )
        self.assertEqual(len(timeline.get("scenes", [])), 0)
        self.assertTrue(any("camera_track" in note for note in notes))

    def test_v1_keeps_scene_without_motion_tracks(self) -> None:
        service = CartoonTimelineService()
        timeline, _ = service.normalize_timeline(
            timeline={
                "scenes": [
                    {
                        "scene_index": 1,
                        "title": "Intro",
                        "turns": [{"speaker_id": "ava", "speaker_name": "Ava", "text": "Hello"}],
                    }
                ]
            },
            timeline_schema_version="v1",
        )
        self.assertEqual(len(timeline.get("scenes", [])), 1)


if __name__ == "__main__":
    unittest.main()
