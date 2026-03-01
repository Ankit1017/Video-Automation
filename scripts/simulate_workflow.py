from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "groq" not in sys.modules:
    groq_stub = types.ModuleType("groq")

    class _GroqStub:
        def __init__(self, *args, **kwargs):
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=lambda **_kwargs: types.SimpleNamespace(choices=[])))

    groq_stub.Groq = _GroqStub
    sys.modules["groq"] = groq_stub

from main_app.models import AgentPlan
from main_app.services.agent_dashboard.asset_executor_registry import AgentAssetExecutorRegistry
from main_app.services.agent_dashboard.asset_service import AgentDashboardAssetService
from main_app.services.agent_dashboard.tool_registry import build_default_agent_tool_registry
from main_app.services.agent_dashboard.workflow_registry import build_default_agent_workflow_registry


class _IntentRouterStub:
    def evaluate_requirements(self, *, intent: str, payload: dict[str, object]) -> tuple[list[str], list[str]]:
        del intent, payload
        return [], []

    def is_valid_topic(self, topic: str) -> bool:
        return bool(str(topic).strip())


class _NoopService:
    def explain_node(self, **_kwargs: object) -> tuple[str, bool]:
        return "", False

    def explain_card(self, **_kwargs: object) -> tuple[str, bool]:
        return "", False

    def get_hint(self, **_kwargs: object) -> tuple[str, bool]:
        return "", False

    def get_attempt_feedback(self, **_kwargs: object) -> tuple[dict[str, str], bool]:
        return {}, False

    def explain_attempt(self, **_kwargs: object) -> tuple[str, bool]:
        return "", False


def _parse_payload_file(path: str) -> dict[str, dict[str, object]]:
    normalized = " ".join(str(path).split()).strip()
    if not normalized:
        return {}
    file_path = Path(normalized)
    if not file_path.exists():
        return {}
    try:
        loaded = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate workflow execution without running tool executors.")
    parser.add_argument("--workflow", default="")
    parser.add_argument("--intents", default="")
    parser.add_argument("--payload-file", default="")
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()
    del args.dry

    tool_registry = build_default_agent_tool_registry()
    workflow_registry = build_default_agent_workflow_registry()
    intents: list[str] = []
    if args.workflow:
        workflow = workflow_registry.get(args.workflow)
        if workflow is None:
            print(f"Unknown workflow: {args.workflow}")
            return 1
        intents = []
        for key in workflow.tool_keys:
            tool = tool_registry.get_by_key(key)
            if tool is not None:
                intents.append(tool.intent)
    elif args.intents:
        intents = [" ".join(item.split()).strip().lower() for item in args.intents.split(",") if item.strip()]
    else:
        print("Provide --workflow or --intents.")
        return 1

    payloads = _parse_payload_file(args.payload_file)
    plan = AgentPlan(
        source_message="simulation",
        planner_mode="local_first",
        intents=intents,
        payloads={intent: payloads.get(intent, {}) for intent in intents},
        missing_mandatory={intent: [] for intent in intents},
        missing_optional={intent: [] for intent in intents},
    )

    service = AgentDashboardAssetService(
        intent_router=_IntentRouterStub(),  # type: ignore[arg-type]
        asset_executor_registry=AgentAssetExecutorRegistry(),
        mind_map_service=_NoopService(),  # type: ignore[arg-type]
        flashcards_service=_NoopService(),  # type: ignore[arg-type]
        quiz_service=_NoopService(),  # type: ignore[arg-type]
        tool_registry=tool_registry,
        workflow_registry=workflow_registry,
    )
    report = service.simulate_plan_execution(plan)

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"Workflow: {report.get('workflow_key', '')}")
    print(f"Run ID: {report.get('run_id', '')}")
    notes = report.get("notes", [])
    if isinstance(notes, list) and notes:
        print("Notes:")
        for note in notes:
            print(f"- {note}")
    nodes = report.get("nodes", [])
    if isinstance(nodes, list):
        print("Nodes:")
        for node in nodes:
            if not isinstance(node, dict):
                continue
            print(f"- {node.get('intent', '')} ({node.get('tool_key', '')})")
            print(f"  states: {' -> '.join(node.get('planned_state_path', []))}")
            print(f"  blocked_by: {', '.join(node.get('blocked_by', [])) or 'none'}")
            print(f"  stages: {', '.join(node.get('expected_stages', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
