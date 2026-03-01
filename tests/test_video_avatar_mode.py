from __future__ import annotations

import unittest

from main_app.services.video_conversation_timeline_service import VideoConversationTimelineService
from main_app.services.video_dialogue_audio_service import VideoDialogueAudioService
from main_app.services.video_export_service import VideoExportService
from main_app.services.video_render_profile_service import VideoRenderProfileService


class TestVideoAvatarMode(unittest.TestCase):
    def test_timeline_builder_orders_turns_and_visual_refs(self) -> None:
        service = VideoConversationTimelineService()
        timeline = service.build_timeline(
            slides=[
                {"title": "Slide 1", "representation": "bullet", "bullets": ["A", "B"]},
                {"title": "Slide 2", "representation": "timeline", "bullets": ["C"]},
            ],
            slide_scripts=[
                {
                    "slide_index": 1,
                    "estimated_duration_sec": 8,
                    "dialogue": [
                        {"speaker": "Ava", "text": "Hello"},
                        {"speaker": "Noah", "text": "World"},
                    ],
                },
                {
                    "slide_index": 2,
                    "estimated_duration_sec": 6,
                    "dialogue": [
                        {"speaker": "Ava", "text": "Second slide"},
                    ],
                },
            ],
        )
        turns = timeline.get("turns", [])
        self.assertIsInstance(turns, list)
        self.assertEqual(len(turns), 3)
        self.assertEqual(turns[0].get("turn_index"), 0)
        self.assertEqual(turns[1].get("turn_index"), 1)
        self.assertEqual(turns[2].get("turn_index"), 2)
        self.assertEqual(turns[0].get("slide_index"), 1)
        self.assertEqual(turns[2].get("slide_index"), 2)
        self.assertGreaterEqual(int(turns[1].get("start_ms", 0)), int(turns[0].get("end_ms", 0)))

    def test_dialogue_audio_segment_normalization(self) -> None:
        service = VideoDialogueAudioService()
        segments = service.build_segment_timing(
            timeline={
                "audio_segments": [
                    {"segment_ref": "s001_t001", "speaker": "Ava", "start_ms": 0, "end_ms": 800, "text": "Hello"},
                    {"segment_ref": "s001_t002", "speaker": "Noah", "start_ms": 900, "end_ms": 1500, "text": "World"},
                ]
            }
        )
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].get("duration_ms"), 800)
        self.assertEqual(segments[1].get("duration_ms"), 600)

    def test_render_profile_selection_tiers(self) -> None:
        service = VideoRenderProfileService()

        def _gpu_high() -> tuple[bool, int]:
            return True, 12000

        def _gpu_low() -> tuple[bool, int]:
            return True, 4000

        def _cpu_only() -> tuple[bool, int]:
            return False, 0

        service._detect_gpu = _gpu_high  # type: ignore[assignment]
        self.assertEqual(service.select_profile().get("profile_key"), "gpu_high")
        service._detect_gpu = _gpu_low  # type: ignore[assignment]
        self.assertEqual(service.select_profile().get("profile_key"), "gpu_balanced")
        service._detect_gpu = _cpu_only  # type: ignore[assignment]
        self.assertEqual(service.select_profile().get("profile_key"), "cpu_safe")

    def test_export_render_mode_resolution_prefers_explicit(self) -> None:
        service = VideoExportService()
        resolved = service._resolve_render_mode(
            render_mode="classic_slides",
            video_payload={"render_mode": "avatar_conversation"},
        )
        self.assertEqual(resolved, "classic_slides")


if __name__ == "__main__":
    unittest.main()
