from __future__ import annotations

import sys
import types
import unittest

if "groq" not in sys.modules:
    groq_stub = types.ModuleType("groq")

    class _GroqStub:
        def __init__(self, *args, **kwargs):
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=lambda **_kwargs: types.SimpleNamespace(choices=[])))

    groq_stub.Groq = _GroqStub
    sys.modules["groq"] = groq_stub

from main_app.models import GroqSettings, SlideShowGenerationResult
from main_app.services.video_asset_service import VideoAssetService


class _FakeLLMService:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def call(self, **kwargs: object) -> tuple[str, bool]:
        messages = kwargs.get("messages", [])
        user_prompt = ""
        if isinstance(messages, list):
            for item in messages:
                if isinstance(item, dict) and str(item.get("role", "")) == "user":
                    user_prompt = str(item.get("content", ""))
                    break
        self.calls.append(
            {
                "task": str(kwargs.get("task", "")),
                "label": str(kwargs.get("label", "")),
                "user_prompt": user_prompt,
            }
        )
        response = (
            "{"
            '"topic":"Segment Trees",'
            '"title":"Slide Narration",'
            '"speakers":[{"name":"Ava","role":"Guide"},{"name":"Noah","role":"Engineer"}],'
            '"dialogue":['
            '{"speaker":"Ava","text":"Ava says: This slide introduces segment trees."},'
            '{"speaker":"Noah","text":"Noah: We split ranges and merge results efficiently."}'
            "],"
            '"summary":"Short explanation."'
            "}"
        )
        return response, False


class _FakeSlideShowService:
    def __init__(self) -> None:
        self.last_kwargs: dict[str, object] = {}

    def generate(self, **_kwargs: object) -> SlideShowGenerationResult:
        self.last_kwargs = dict(_kwargs)
        return SlideShowGenerationResult(
            slides=[
                {"title": "Intro", "section": "Introduction", "bullets": ["What", "Why"], "speaker_notes": ""},
                {"title": "Range Query", "section": "Core", "bullets": ["Split", "Merge"], "speaker_notes": ""},
            ],
            parse_error=None,
            parse_notes=[],
            cache_hits=0,
            total_calls=1,
            debug_raw=None,
        )


class _FakeParser:
    def parse(
        self,
        raw_text: str,
        *,
        settings: GroqSettings,
        min_speakers: int,
        max_speakers: int,
        min_turns: int,
        max_turns: int,
    ) -> tuple[dict[str, object] | None, str | None, str | None]:
        del settings, min_speakers, max_speakers, min_turns, max_turns
        return {
            "topic": "Segment Trees",
            "title": "Slide Narration",
            "speakers": [{"name": "Ava", "role": "Guide"}, {"name": "Noah", "role": "Engineer"}],
            "dialogue": [
                {"speaker": "Ava", "text": "Ava says: This slide introduces segment trees."},
                {"speaker": "Noah", "text": "Noah: We split ranges and merge results efficiently."},
            ],
            "summary": "Short explanation.",
            "raw": raw_text,
        }, None, None


class _FakeAudioOverviewService:
    def __init__(self) -> None:
        self.last_payload: dict[str, object] | None = None

    def synthesize_mp3(
        self,
        *,
        overview_payload: dict[str, object],
        language: str = "en",
        slow: bool = False,
    ) -> tuple[bytes | None, str | None]:
        self.last_payload = {
            "overview_payload": overview_payload,
            "language": language,
            "slow": slow,
        }
        return b"mp3-bytes", None


class TestVideoAssetService(unittest.TestCase):
    def setUp(self) -> None:
        self.llm = _FakeLLMService()
        self.audio_service = _FakeAudioOverviewService()
        self.slideshow_service = _FakeSlideShowService()
        self.service = VideoAssetService(
            llm_service=self.llm,
            slideshow_service=self.slideshow_service,
            script_parser=_FakeParser(),
            audio_overview_service=self.audio_service,
            history_service=None,
        )
        self.settings = GroqSettings(
            api_key="test",
            model="llama-3.1-8b-instant",
            temperature=0.2,
            max_tokens=1024,
        )

    def test_generate_builds_slide_scripts_for_each_slide(self) -> None:
        result = self.service.generate(
            topic="Segment Trees",
            constraints="",
            subtopic_count=4,
            slides_per_subtopic=2,
            code_mode="auto",
            speaker_count=2,
            conversation_style="Educational Discussion",
            settings=self.settings,
        )

        self.assertIsNone(result.parse_error)
        self.assertIsNotNone(result.video_payload)
        payload = result.video_payload or {}
        self.assertEqual(len(payload.get("slides", [])), 2)
        self.assertEqual(len(payload.get("slide_scripts", [])), 2)
        self.assertEqual(payload.get("video_template"), "standard")
        self.assertEqual(payload.get("animation_style"), "smooth")
        self.assertEqual(payload.get("representation_mode"), "auto")
        self.assertEqual(payload.get("render_mode"), "avatar_conversation")
        self.assertTrue(isinstance(payload.get("speaker_roster"), list))
        self.assertGreaterEqual(len(payload.get("speaker_roster", [])), 2)
        timeline = payload.get("conversation_timeline", {})
        self.assertIsInstance(timeline, dict)
        self.assertTrue(isinstance(timeline.get("turns", []), list) and len(timeline.get("turns", [])) > 0)
        metadata = payload.get("metadata", {})
        self.assertIsInstance(metadata, dict)
        self.assertEqual(metadata.get("script_language"), "english")
        self.assertEqual(result.total_calls, 3)
        # 1 per slide narration call
        self.assertEqual(len(self.llm.calls), 2)
        self.assertEqual(self.slideshow_service.last_kwargs.get("representation_mode"), "auto")

        first_dialogue = payload["slide_scripts"][0]["dialogue"][0]["text"]
        self.assertNotIn("Ava says", first_dialogue)

    def test_synthesize_audio_flattens_dialogue(self) -> None:
        generation = self.service.generate(
            topic="Segment Trees",
            constraints="",
            subtopic_count=4,
            slides_per_subtopic=2,
            code_mode="auto",
            speaker_count=2,
            conversation_style="Educational Discussion",
            settings=self.settings,
        )
        payload = generation.video_payload or {}
        audio_bytes, audio_error = self.service.synthesize_audio(
            video_payload=payload,
            language="en",
            slow=False,
        )
        self.assertEqual(audio_bytes, b"mp3-bytes")
        self.assertIsNone(audio_error)
        self.assertIsNotNone(self.audio_service.last_payload)
        overview_payload = self.audio_service.last_payload["overview_payload"]
        self.assertGreaterEqual(len(overview_payload.get("dialogue", [])), 2)

    def test_generate_includes_youtube_prompt_block_when_enabled(self) -> None:
        result = self.service.generate(
            topic="Segment Trees",
            constraints="",
            subtopic_count=2,
            slides_per_subtopic=1,
            code_mode="auto",
            speaker_count=2,
            conversation_style="Educational Discussion",
            video_template="youtube",
            animation_style="youtube_dynamic",
            representation_mode="visual",
            use_youtube_prompt=True,
            settings=self.settings,
        )

        self.assertIsNone(result.parse_error)
        payload = result.video_payload or {}
        self.assertEqual(payload.get("video_template"), "youtube")
        self.assertEqual(payload.get("animation_style"), "youtube_dynamic")
        self.assertEqual(payload.get("representation_mode"), "visual")
        self.assertEqual(self.slideshow_service.last_kwargs.get("representation_mode"), "visual")
        prompt_texts = [item.get("user_prompt", "") for item in self.llm.calls if item.get("task") == "video_slide_script"]
        self.assertTrue(any("Optional YouTube educational creator style" in text for text in prompt_texts))

    def test_generate_excludes_youtube_prompt_block_when_disabled(self) -> None:
        self.llm.calls.clear()
        result = self.service.generate(
            topic="Segment Trees",
            constraints="",
            subtopic_count=2,
            slides_per_subtopic=1,
            code_mode="auto",
            speaker_count=2,
            conversation_style="Educational Discussion",
            use_youtube_prompt=False,
            settings=self.settings,
        )
        self.assertIsNone(result.parse_error)
        prompt_texts = [item.get("user_prompt", "") for item in self.llm.calls if item.get("task") == "video_slide_script"]
        self.assertTrue(prompt_texts)
        self.assertTrue(all("Optional YouTube educational creator style" not in text for text in prompt_texts))

    def test_generate_includes_hinglish_prompt_block_when_enabled(self) -> None:
        result = self.service.generate(
            topic="Segment Trees",
            constraints="",
            subtopic_count=2,
            slides_per_subtopic=1,
            code_mode="auto",
            speaker_count=2,
            conversation_style="Educational Discussion",
            use_hinglish_script=True,
            settings=self.settings,
        )

        self.assertIsNone(result.parse_error)
        payload = result.video_payload or {}
        metadata = payload.get("metadata", {})
        self.assertEqual(metadata.get("script_language"), "hinglish")
        prompt_texts = [item.get("user_prompt", "") for item in self.llm.calls if item.get("task") == "video_slide_script"]
        self.assertTrue(prompt_texts)
        self.assertTrue(any("Optional script language mode: Roman Hinglish." in text for text in prompt_texts))
        self.assertTrue(any("Use only Latin/Roman script" in text for text in prompt_texts))

    def test_generate_supports_explicit_classic_render_mode(self) -> None:
        result = self.service.generate(
            topic="Segment Trees",
            constraints="",
            subtopic_count=2,
            slides_per_subtopic=1,
            code_mode="auto",
            speaker_count=2,
            conversation_style="Educational Discussion",
            render_mode="classic_slides",
            settings=self.settings,
        )
        self.assertIsNone(result.parse_error)
        payload = result.video_payload or {}
        self.assertEqual(payload.get("render_mode"), "classic_slides")
        metadata = payload.get("metadata", {})
        self.assertEqual(metadata.get("render_mode"), "classic_slides")

    def test_generate_excludes_hinglish_prompt_block_when_disabled(self) -> None:
        result = self.service.generate(
            topic="Segment Trees",
            constraints="",
            subtopic_count=2,
            slides_per_subtopic=1,
            code_mode="auto",
            speaker_count=2,
            conversation_style="Educational Discussion",
            use_hinglish_script=False,
            settings=self.settings,
        )

        self.assertIsNone(result.parse_error)
        payload = result.video_payload or {}
        metadata = payload.get("metadata", {})
        self.assertEqual(metadata.get("script_language"), "english")
        prompt_texts = [item.get("user_prompt", "") for item in self.llm.calls if item.get("task") == "video_slide_script"]
        self.assertTrue(prompt_texts)
        self.assertTrue(all("Optional script language mode: Roman Hinglish." not in text for text in prompt_texts))


if __name__ == "__main__":
    unittest.main()
