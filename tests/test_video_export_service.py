from __future__ import annotations

import os
from pathlib import Path
import unittest

from main_app.services.video_export_service import VideoExportService


class TestVideoExportService(unittest.TestCase):
    def setUp(self) -> None:
        self.service = VideoExportService()

    def test_compute_slide_durations_aligns_to_audio_length(self) -> None:
        slides = [
            {"title": "Intro", "bullets": ["a", "b"]},
            {"title": "Core", "bullets": ["a", "b", "c"]},
            {"title": "Summary", "bullets": ["a"]},
        ]
        scripts = [
            {"slide_index": 1, "estimated_duration_sec": 10, "dialogue": []},
            {"slide_index": 2, "estimated_duration_sec": 20, "dialogue": []},
            {"slide_index": 3, "estimated_duration_sec": 10, "dialogue": []},
        ]
        durations = self.service._compute_slide_durations(
            slides=slides,
            slide_scripts=scripts,
            audio_duration=40.0,
        )
        self.assertEqual(len(durations), 3)
        self.assertAlmostEqual(sum(durations), 40.0, places=2)
        self.assertGreater(durations[1], durations[0])

    def test_compute_slide_durations_fallback_without_scripts(self) -> None:
        slides = [{"title": "One"}, {"title": "Two"}]
        durations = self.service._compute_slide_durations(
            slides=slides,
            slide_scripts=None,
            audio_duration=12.0,
        )
        self.assertEqual(len(durations), 2)
        self.assertAlmostEqual(sum(durations), 12.0, places=2)
        self.assertTrue(all(value >= 2.0 for value in durations))

    def test_build_video_requires_audio(self) -> None:
        data, error = self.service.build_video_mp4(
            topic="Topic",
            video_payload={"slides": [{"title": "A"}]},
            audio_bytes=b"",
        )
        self.assertIsNone(data)
        self.assertIsNotNone(error)
        self.assertIn("Audio is required", error or "")

    def test_resolve_template_key_prefers_explicit_argument(self) -> None:
        key = self.service._resolve_template_key(
            template_key="youtube",
            video_payload={"video_template": "standard"},
        )
        self.assertEqual(key, "youtube")

    def test_resolve_template_key_falls_back_to_payload_then_default(self) -> None:
        from_payload = self.service._resolve_template_key(
            template_key=None,
            video_payload={"video_template": "youtube"},
        )
        fallback = self.service._resolve_template_key(
            template_key="unknown-template",
            video_payload={"video_template": "not-valid"},
        )
        self.assertEqual(from_payload, "youtube")
        self.assertEqual(fallback, "standard")

    def test_font_candidates_include_windows_fonts(self) -> None:
        bold_candidates = self.service._font_candidates(bold=True, mono=False)
        mono_candidates = self.service._font_candidates(bold=False, mono=True)
        self.assertTrue(any("C:\\Windows\\Fonts\\arialbd.ttf" in item for item in bold_candidates))
        self.assertTrue(any("C:\\Windows\\Fonts\\consola.ttf" in item for item in mono_candidates))

    def test_resolve_animation_style_precedence_and_defaults(self) -> None:
        explicit = self.service._resolve_animation_style(
            animation_style="none",
            video_payload={"animation_style": "smooth"},
            selected_template_key="standard",
        )
        from_payload = self.service._resolve_animation_style(
            animation_style=None,
            video_payload={"animation_style": "youtube_dynamic"},
            selected_template_key="standard",
        )
        by_template = self.service._resolve_animation_style(
            animation_style=None,
            video_payload={},
            selected_template_key="youtube",
        )
        fallback = self.service._resolve_animation_style(
            animation_style="invalid",
            video_payload={"animation_style": "bad"},
            selected_template_key="standard",
        )
        self.assertEqual(explicit, "none")
        self.assertEqual(from_payload, "youtube_dynamic")
        self.assertEqual(by_template, "youtube_dynamic")
        self.assertEqual(fallback, "smooth")

    def test_resolve_render_mode_precedence_and_default(self) -> None:
        explicit = self.service._resolve_render_mode(
            render_mode="classic_slides",
            video_payload={"render_mode": "avatar_conversation"},
        )
        from_payload = self.service._resolve_render_mode(
            render_mode=None,
            video_payload={"render_mode": "classic_slides"},
        )
        fallback = self.service._resolve_render_mode(
            render_mode="bad-mode",
            video_payload={},
        )
        self.assertEqual(explicit, "classic_slides")
        self.assertEqual(from_payload, "classic_slides")
        self.assertIn(fallback, {"avatar_conversation", "classic_slides"})

    def test_timeline_turns_by_slide_groups_turns(self) -> None:
        mapping = self.service._timeline_turns_by_slide(
            video_payload={
                "conversation_timeline": {
                    "turns": [
                        {"slide_index": 1, "speaker": "Ava", "text": "one"},
                        {"slide_index": 2, "speaker": "Noah", "text": "two"},
                        {"slide_index": 1, "speaker": "Ava", "text": "three"},
                    ]
                }
            }
        )
        self.assertEqual(sorted(mapping.keys()), [1, 2])
        self.assertEqual(len(mapping[1]), 2)
        self.assertEqual(len(mapping[2]), 1)

    def test_reveal_steps_for_timeline_and_process_flow(self) -> None:
        timeline_steps = self.service._reveal_steps(
            slide={
                "representation": "timeline",
                "layout_payload": {
                    "events": [
                        {"label": "Start", "detail": "Kickoff"},
                        {"label": "Build", "detail": "Implement"},
                        {"label": "Run", "detail": "Operate"},
                    ]
                },
                "bullets": ["Fallback"],
            }
        )
        process_steps = self.service._reveal_steps(
            slide={
                "representation": "process_flow",
                "layout_payload": {
                    "steps": [
                        {"title": "Plan", "detail": "Scope"},
                        {"title": "Build", "detail": "Code"},
                    ]
                },
                "bullets": ["Fallback"],
            }
        )
        self.assertEqual(timeline_steps, [1, 2, 3])
        self.assertEqual(process_steps, [1, 2])

    def test_progressive_reveal_applies_only_to_progressive_representations(self) -> None:
        timeline = self.service._should_use_progressive_reveal(
            slide={"representation": "timeline", "layout_payload": {"events": [{"label": "A", "detail": "B"}]}},
            animation_style="youtube_dynamic",
        )
        metric_cards = self.service._should_use_progressive_reveal(
            slide={
                "representation": "metric_cards",
                "layout_payload": {"cards": [{"label": "L", "value": "V", "context": ""}]},
            },
            animation_style="youtube_dynamic",
        )
        smooth_bullet = self.service._should_use_progressive_reveal(
            slide={"representation": "bullet", "layout_payload": {"items": ["A"]}},
            animation_style="smooth",
        )
        self.assertTrue(timeline)
        self.assertFalse(metric_cards)
        self.assertFalse(smooth_bullet)

    def test_render_workdir_lifecycle(self) -> None:
        workdir = self.service._create_render_workdir()
        self.assertTrue(workdir.exists())
        self.assertTrue(workdir.is_dir())
        self.service._cleanup_render_workdir(workdir)
        self.assertFalse(workdir.exists())

    def test_moviepy_path_is_windows_safe(self) -> None:
        probe = Path.cwd() / ".cache" / "video_render" / "probe.mp3"
        normalized = self.service._moviepy_path(probe)
        if os.name == "nt":
            self.assertNotIn("\\", normalized)
        self.assertTrue(str(normalized).strip())

    def test_ensure_pillow_resample_compat_sets_antialias_from_resampling(self) -> None:
        class _FakeResampling:
            LANCZOS = 123

        class _FakeImage:
            Resampling = _FakeResampling

        self.service._ensure_pillow_resample_compat(image_module=_FakeImage)
        self.assertTrue(hasattr(_FakeImage, "ANTIALIAS"))
        self.assertEqual(_FakeImage.ANTIALIAS, 123)

    def test_ensure_pillow_resample_compat_sets_antialias_from_lanczos_fallback(self) -> None:
        class _FakeImage:
            LANCZOS = 456

        self.service._ensure_pillow_resample_compat(image_module=_FakeImage)
        self.assertTrue(hasattr(_FakeImage, "ANTIALIAS"))
        self.assertEqual(_FakeImage.ANTIALIAS, 456)

    def test_ensure_pillow_resample_compat_keeps_existing_antialias(self) -> None:
        class _FakeImage:
            ANTIALIAS = 789

        self.service._ensure_pillow_resample_compat(image_module=_FakeImage)
        self.assertEqual(_FakeImage.ANTIALIAS, 789)


if __name__ == "__main__":
    unittest.main()
