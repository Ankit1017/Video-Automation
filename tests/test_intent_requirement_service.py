from __future__ import annotations

import sys
import types

if "groq" not in sys.modules:
    groq_stub = types.ModuleType("groq")

    class _GroqStub:
        def __init__(self, *args, **kwargs):
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=lambda **_kwargs: types.SimpleNamespace(choices=[])))

    groq_stub.Groq = _GroqStub
    sys.modules["groq"] = groq_stub

import unittest

from main_app.models import GroqSettings
from main_app.services.intent.intent_requirement_service import IntentRequirementService
from main_app.services.intent.intent_requirement_spec import INTENT_ALIASES, INTENT_ORDER, REQUIREMENT_SPEC
from main_app.services.intent.intent_router_payload_utils import IntentRouterPayloadUtils
from main_app.services.intent.intent_router_text_utils import IntentRouterTextUtils


class _DummyLLMService:
    def call(self, **_kwargs: object) -> tuple[str, bool]:
        raise AssertionError("LLM call should not be used in this local-mode unit test")


class TestIntentRequirementService(unittest.TestCase):
    def setUp(self) -> None:
        self.service = IntentRequirementService(
            llm_service=_DummyLLMService(),
            payload_utils=IntentRouterPayloadUtils(intent_aliases=INTENT_ALIASES, intent_order=INTENT_ORDER),
            text_utils=IntentRouterTextUtils(),
            requirement_spec=REQUIREMENT_SPEC,
        )
        self.settings_without_llm = GroqSettings(api_key="", model="", temperature=0.2, max_tokens=256)

    def test_prepare_requirements_local_mode(self) -> None:
        payloads, note, cache_hit = self.service.prepare_requirements(
            message="Create a quiz on CDC Pipeline. Focus on production trade-offs.",
            intents=["quiz"],
            settings=self.settings_without_llm,
            mode=IntentRequirementService.MODE_LOCAL_FIRST,
        )

        self.assertIn("quiz", payloads)
        self.assertIn("topic", payloads["quiz"])
        self.assertIn("constraints", payloads["quiz"])
        self.assertIn("CDC Pipeline", payloads["quiz"]["topic"])
        self.assertEqual(payloads["quiz"]["constraints"], "production trade-offs")
        self.assertFalse(cache_hit)
        self.assertIsNotNone(note)

    def test_evaluate_requirements_when_topic_missing(self) -> None:
        missing_mandatory, missing_optional = self.service.evaluate_requirements(intent="quiz", payload={})

        self.assertEqual(missing_mandatory, ["topic"])
        self.assertIn("question_count", missing_optional)
        self.assertIn("difficulty", missing_optional)
        self.assertIn("constraints", missing_optional)

    def test_apply_default_optionals(self) -> None:
        updated = self.service.apply_default_optionals(
            intent="quiz",
            payload={"topic": "CDC Pipeline"},
            missing_optional=["question_count", "difficulty", "constraints"],
        )

        self.assertEqual(updated["question_count"], 10)
        self.assertEqual(updated["difficulty"], "Intermediate")
        self.assertEqual(updated["constraints"], "")

    def test_apply_default_optionals_for_video(self) -> None:
        updated = self.service.apply_default_optionals(
            intent="video",
            payload={"topic": "CDC Pipeline"},
            missing_optional=[
                "speaker_count",
                "code_mode",
                "representation_mode",
                "language",
                "slow_audio",
                "video_template",
                "animation_style",
                "youtube_prompt",
            ],
        )

        self.assertEqual(updated["speaker_count"], 2)
        self.assertEqual(updated["code_mode"], "auto")
        self.assertEqual(updated["representation_mode"], "auto")
        self.assertEqual(updated["language"], "en")
        self.assertFalse(updated["slow_audio"])
        self.assertEqual(updated["video_template"], "standard")
        self.assertEqual(updated["animation_style"], "none")
        self.assertFalse(updated["youtube_prompt"])

    def test_apply_default_optionals_for_slideshow(self) -> None:
        updated = self.service.apply_default_optionals(
            intent="slideshow",
            payload={"topic": "CDC Pipeline"},
            missing_optional=["subtopic_count", "slides_per_subtopic", "code_mode", "representation_mode"],
        )

        self.assertEqual(updated["subtopic_count"], 5)
        self.assertEqual(updated["slides_per_subtopic"], 2)
        self.assertEqual(updated["code_mode"], "auto")
        self.assertEqual(updated["representation_mode"], "auto")

    def test_apply_default_optionals_for_audio_overview(self) -> None:
        updated = self.service.apply_default_optionals(
            intent="audio_overview",
            payload={"topic": "CDC Pipeline"},
            missing_optional=["speaker_count", "turn_count", "language", "youtube_prompt"],
        )

        self.assertEqual(updated["speaker_count"], 2)
        self.assertEqual(updated["turn_count"], 12)
        self.assertEqual(updated["language"], "en")
        self.assertFalse(updated["youtube_prompt"])

    def test_requirement_spec_has_schema_metadata(self) -> None:
        quiz_spec = REQUIREMENT_SPEC.get("quiz", {})
        self.assertEqual(quiz_spec.get("requirements_schema_key"), "quiz")
        self.assertEqual(quiz_spec.get("schema_version"), "v1")


if __name__ == "__main__":
    unittest.main()
