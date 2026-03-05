from __future__ import annotations

import unittest
from pathlib import Path

from main_app.models import GroqSettings
from main_app.services.cartoon_character_pack_service import CartoonCharacterPackService
from main_app.services.cartoon_render_profile_service import CartoonRenderProfileService
from main_app.services.cartoon_shorts_asset_service import CartoonShortsAssetService
from main_app.services.cartoon_storyboard_service import CartoonStoryboardService
from main_app.services.cartoon_timeline_service import CartoonTimelineService


class _FailingLLM:
    def call(self, **kwargs):  # noqa: ANN003
        raise RuntimeError("forced failure")


class _StaticLLM:
    def call(self, **kwargs):  # noqa: ANN003
        return (
            '{"scenes":[{"scene_index":1,"title":"Intro","turns":[{"speaker_id":"ava","speaker_name":"Ava","text":"Hello","estimated_duration_ms":2000}]}]}',
            False,
        )


class TestCartoonServices(unittest.TestCase):
    def test_character_pack_fallback_roster(self) -> None:
        service = CartoonCharacterPackService(pack_root=Path("__missing_pack__"))
        roster = service.load_roster(speaker_count=3)
        self.assertEqual(len(roster), 3)
        self.assertTrue(all(str(item.get("id", "")).strip() for item in roster))

    def test_timeline_normalizer_monotonic(self) -> None:
        service = CartoonTimelineService()
        timeline, notes = service.normalize_timeline(
            timeline={
                "scenes": [
                    {
                        "scene_index": 2,
                        "title": "S2",
                        "turns": [
                            {"speaker_id": "ava", "speaker_name": "Ava", "text": "A", "start_ms": 0, "end_ms": 1000},
                        ],
                    },
                    {
                        "scene_index": 1,
                        "title": "S1",
                        "turns": [
                            {"speaker_id": "noah", "speaker_name": "Noah", "text": "B", "start_ms": 0, "end_ms": 800},
                        ],
                    },
                ]
            }
        )
        self.assertTrue(isinstance(timeline.get("scenes", []), list))
        self.assertEqual(len(timeline.get("scenes", [])), 2)
        self.assertIsInstance(notes, list)
        scenes = timeline.get("scenes", [])
        assert isinstance(scenes, list)
        first_scene_turns = scenes[0].get("turns", []) if isinstance(scenes[0], dict) else []
        second_scene_turns = scenes[1].get("turns", []) if isinstance(scenes[1], dict) else []
        self.assertTrue(isinstance(first_scene_turns, list) and isinstance(second_scene_turns, list))
        if first_scene_turns and second_scene_turns and isinstance(first_scene_turns[0], dict) and isinstance(second_scene_turns[0], dict):
            self.assertLess(
                int(first_scene_turns[0].get("start_ms", 0)),
                int(second_scene_turns[0].get("start_ms", 0)),
            )

    def test_storyboard_fallback_on_llm_failure(self) -> None:
        storyboard = CartoonStoryboardService(_FailingLLM())  # type: ignore[arg-type]
        timeline, err, notes, cache_hits, total_calls, raw_text = storyboard.generate_timeline(
            topic="RAG",
            idea="Two bots explain retrieval",
            short_type="educational_explainer",
            character_roster=[
                {"id": "ava", "name": "Ava", "role": "Guide"},
                {"id": "noah", "name": "Noah", "role": "Engineer"},
            ],
            scene_count=3,
            settings=GroqSettings(api_key="k", model="m", temperature=0.2, max_tokens=128),
            language="en",
            use_hinglish_script=False,
        )
        self.assertIsNone(err)
        self.assertGreaterEqual(len(timeline.get("scenes", [])), 2)
        self.assertTrue(any("fallback" in note.lower() for note in notes))
        self.assertEqual(cache_hits, 0)
        self.assertEqual(total_calls, 1)
        self.assertTrue(raw_text in {"", None})

    def test_asset_service_generate_from_storyboard(self) -> None:
        asset_service = CartoonShortsAssetService(
            storyboard_service=CartoonStoryboardService(_StaticLLM()),  # type: ignore[arg-type]
            timeline_service=CartoonTimelineService(),
            character_pack_service=CartoonCharacterPackService(pack_root=Path("__missing_pack__")),
            history_service=None,
        )
        result = asset_service.generate(
            topic="Caching",
            idea="Why caching matters",
            short_type="educational_explainer",
            scene_count=2,
            speaker_count=2,
            output_mode="dual",
            language="en",
            use_hinglish_script=False,
            settings=GroqSettings(api_key="k", model="m", temperature=0.2, max_tokens=128),
        )
        self.assertIsNone(result.parse_error)
        payload = result.cartoon_payload or {}
        self.assertEqual(payload.get("short_type"), "educational_explainer")
        self.assertEqual(payload.get("output_mode"), "dual")
        self.assertEqual(payload.get("render_style"), "scene")
        self.assertEqual(payload.get("background_style"), "auto")
        self.assertEqual(payload.get("showcase_avatar_mode"), "auto")
        self.assertTrue(isinstance(payload.get("timeline", {}), dict))
        self.assertTrue(str(payload.get("script_markdown", "")).strip())

    def test_render_profile_tiers(self) -> None:
        service = CartoonRenderProfileService()

        def _gpu_high() -> tuple[bool, int]:
            return True, 12_000

        def _gpu_low() -> tuple[bool, int]:
            return True, 5_000

        def _cpu() -> tuple[bool, int]:
            return False, 0

        service._detect_gpu = _gpu_high  # type: ignore[assignment]
        self.assertEqual(service.select_profile().get("profile_key"), "gpu_high")
        service._detect_gpu = _gpu_low  # type: ignore[assignment]
        self.assertEqual(service.select_profile().get("profile_key"), "gpu_balanced")
        service._detect_gpu = _cpu  # type: ignore[assignment]
        self.assertEqual(service.select_profile().get("profile_key"), "cpu_safe")


if __name__ == "__main__":
    unittest.main()
