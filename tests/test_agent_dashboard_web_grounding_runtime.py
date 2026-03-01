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

from main_app.models import AgentAssetResult, GroqSettings
from main_app.services.agent_dashboard.asset_executor_registry import AgentAssetExecutorRegistry
from main_app.services.agent_dashboard.executor_plugins import topic as topic_plugin
from main_app.services.agent_dashboard.executor_types import (
    AssetExecutionRuntimeContext,
    AssetExecutorPluginContext,
)


class _NoopService:
    pass


class _FakeExplainerService:
    def __init__(self) -> None:
        self.last_call: dict[str, object] = {}

    def generate(self, **kwargs):  # noqa: ANN003
        self.last_call = dict(kwargs)
        return "grounded text", False


class TestAgentDashboardWebGroundingRuntime(unittest.TestCase):
    def test_topic_plugin_forwards_runtime_grounding_context(self) -> None:
        fake_explainer = _FakeExplainerService()
        context = AssetExecutorPluginContext(
            explainer_service=fake_explainer,  # type: ignore[arg-type]
            mind_map_service=_NoopService(),  # type: ignore[arg-type]
            flashcards_service=_NoopService(),  # type: ignore[arg-type]
            data_table_service=_NoopService(),  # type: ignore[arg-type]
            quiz_service=_NoopService(),  # type: ignore[arg-type]
            slideshow_service=_NoopService(),  # type: ignore[arg-type]
            video_service=None,
            audio_overview_service=_NoopService(),  # type: ignore[arg-type]
            report_service=_NoopService(),  # type: ignore[arg-type]
        )
        executor = topic_plugin.PLUGIN.build_executor(context)
        runtime_context = AssetExecutionRuntimeContext(
            grounding_context="[S1] source text",
            source_manifest=[{"source_id": "S1", "name": "example"}],
            require_citations=True,
            diagnostics={"web_sourcing_enabled": True},
        )
        settings = GroqSettings(api_key="k", model="m", temperature=0.2, max_tokens=128)

        result = executor({"topic": "Agentic AI"}, settings, runtime_context)

        self.assertEqual(result.status, "success")
        self.assertEqual(fake_explainer.last_call.get("grounding_context"), "[S1] source text")
        self.assertEqual(fake_explainer.last_call.get("source_manifest"), [{"source_id": "S1", "name": "example"}])
        self.assertEqual(fake_explainer.last_call.get("require_citations"), True)
        self.assertEqual(fake_explainer.last_call.get("grounding_metadata"), {"web_sourcing_enabled": True})

    def test_registry_keeps_backward_compat_with_two_arg_executor(self) -> None:
        registry = AgentAssetExecutorRegistry()

        def legacy_executor(payload: dict[str, object], _settings: GroqSettings) -> AgentAssetResult:
            return AgentAssetResult(
                intent="topic",
                status="success",
                payload=payload,
                content="legacy executor output",
            )

        registry.register("topic", legacy_executor)
        settings = GroqSettings(api_key="k", model="m", temperature=0.2, max_tokens=128)
        runtime_context = AssetExecutionRuntimeContext(grounding_context="ctx")

        result = registry.execute(
            intent="topic",
            payload={"topic": "CDC"},
            settings=settings,
            runtime_context=runtime_context,
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.intent, "topic")


if __name__ == "__main__":
    unittest.main()
