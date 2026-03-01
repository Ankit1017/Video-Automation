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

from main_app.models import AgentAssetResult
from main_app.services.agent_dashboard.tool_registry import build_default_agent_tool_registry
from main_app.services.agent_dashboard.verification_service import (
    verification_passed,
    verify_asset_result,
)


class TestVerificationService(unittest.TestCase):
    def test_text_profile_pass_and_fail(self) -> None:
        registry = build_default_agent_tool_registry()
        tool = registry.get_by_intent("topic")
        assert tool is not None
        passed = AgentAssetResult(
            intent="topic",
            status="success",
            payload={"topic": "CDC"},
            title="Detailed Description: CDC",
            content="This is a sufficiently long description for verification to pass cleanly.",
        )
        failed = AgentAssetResult(
            intent="topic",
            status="success",
            payload={"topic": "CDC"},
            title="Detailed Description: CDC",
            content="short",
        )
        self.assertTrue(verification_passed(verify_asset_result(result=passed, tool=tool)))
        self.assertFalse(verification_passed(verify_asset_result(result=failed, tool=tool)))

    def test_structured_profile_detects_shape_issues(self) -> None:
        registry = build_default_agent_tool_registry()
        tool = registry.get_by_intent("quiz")
        assert tool is not None
        result = AgentAssetResult(
            intent="quiz",
            status="success",
            payload={"topic": "CDC"},
            title="Quiz: CDC",
            content={"topic": "CDC", "questions": [{"question": "q1", "options": ["a"], "correct_index": 0}]},
        )
        summary = verify_asset_result(result=result, tool=tool)
        self.assertEqual(summary.get("status"), "failed")
        issues = summary.get("issues", [])
        self.assertTrue(isinstance(issues, list) and len(issues) > 0)
        self.assertTrue(all(str(issue.get("path", "")).strip() for issue in issues if isinstance(issue, dict)))

    def test_media_profile_checks_audio_presence(self) -> None:
        registry = build_default_agent_tool_registry()
        tool = registry.get_by_intent("audio_overview")
        assert tool is not None
        result = AgentAssetResult(
            intent="audio_overview",
            status="success",
            payload={"topic": "CDC"},
            title="Audio Overview: CDC",
            content={"topic": "CDC", "dialogue": [{"speaker": "A", "text": "hello"}]},
            audio_bytes=None,
            audio_error="",
        )
        summary = verify_asset_result(result=result, tool=tool)
        self.assertEqual(summary.get("status"), "failed")

    def test_unknown_verify_profile_fallback_adds_warning_issue(self) -> None:
        registry = build_default_agent_tool_registry()
        base_tool = registry.get_by_intent("topic")
        assert base_tool is not None
        from dataclasses import replace

        tool = replace(
            base_tool,
            execution_spec={**dict(base_tool.execution_spec), "verify_profile": "unknown_profile_name"},
        )
        result = AgentAssetResult(
            intent="topic",
            status="success",
            payload={"topic": "CDC"},
            title="Detailed Description: CDC",
            content="This is a sufficiently long description for verification to pass cleanly.",
        )
        summary = verify_asset_result(result=result, tool=tool)
        issues = summary.get("issues", [])
        self.assertTrue(
            any(
                isinstance(issue, dict)
                and str(issue.get("code", "")).strip() == "E_VERIFY_PROFILE_UNKNOWN"
                for issue in issues if isinstance(issues, list)
            )
        )

    def test_video_media_profile_accepts_timeline_and_speaker_roster(self) -> None:
        registry = build_default_agent_tool_registry()
        tool = registry.get_by_intent("video")
        assert tool is not None
        result = AgentAssetResult(
            intent="video",
            status="success",
            payload={"topic": "CDC"},
            title="Video: CDC",
            content={
                "topic": "CDC",
                "slides": [{"title": "Intro", "bullets": ["A"]}],
                "slide_scripts": [{"slide_index": 1, "dialogue": [{"speaker": "Ava", "text": "Hello"}]}],
                "speaker_roster": [{"name": "Ava", "role": "Guide"}, {"name": "Noah", "role": "Engineer"}],
                "conversation_timeline": {
                    "turns": [
                        {
                            "turn_index": 0,
                            "speaker": "Ava",
                            "text": "Hello",
                            "slide_index": 1,
                            "start_ms": 0,
                            "end_ms": 1000,
                            "visual_ref": {"slide_index": 1, "representation": "bullet"},
                            "segment_ref": "s001_t001",
                        }
                    ],
                    "audio_segments": [
                        {"segment_ref": "s001_t001", "start_ms": 0, "end_ms": 1000},
                    ],
                },
            },
            audio_bytes=b"audio",
            audio_error="",
        )
        summary = verify_asset_result(result=result, tool=tool)
        self.assertEqual(summary.get("status"), "passed")

    def test_video_media_profile_rejects_missing_timeline(self) -> None:
        registry = build_default_agent_tool_registry()
        tool = registry.get_by_intent("video")
        assert tool is not None
        result = AgentAssetResult(
            intent="video",
            status="success",
            payload={"topic": "CDC"},
            title="Video: CDC",
            content={
                "topic": "CDC",
                "slides": [{"title": "Intro", "bullets": ["A"]}],
                "slide_scripts": [{"slide_index": 1, "dialogue": [{"speaker": "Ava", "text": "Hello"}]}],
                "speaker_roster": [{"name": "Ava", "role": "Guide"}],
                "conversation_timeline": {"turns": []},
            },
            audio_bytes=b"audio",
            audio_error="",
        )
        summary = verify_asset_result(result=result, tool=tool)
        self.assertEqual(summary.get("status"), "failed")


if __name__ == "__main__":
    unittest.main()
