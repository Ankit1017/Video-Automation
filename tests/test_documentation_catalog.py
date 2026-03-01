from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from main_app.constants import TAB_TITLES
from main_app.ui.tabs.documentation_catalog import (
    collect_runtime_inventory,
    filter_ui_feature_catalog,
    get_ui_feature_catalog,
    missing_whitelisted_docs,
    resolve_whitelisted_doc_path,
)


def test_ui_catalog_covers_all_tab_titles() -> None:
    catalog = get_ui_feature_catalog()
    missing = [title for title in TAB_TITLES if title not in catalog]
    assert not missing


def test_docs_whitelist_paths_exist() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    assert missing_whitelisted_docs(repo_root=repo_root) == []


def test_whitelisted_path_guard_rejects_unknown_label() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError):
        resolve_whitelisted_doc_path(label="not-allowed.md", repo_root=repo_root)


def test_feature_filter_is_deterministic_for_query() -> None:
    catalog = get_ui_feature_catalog()
    first = [title for title, _ in filter_ui_feature_catalog(catalog=catalog, query="quiz")]
    second = [title for title, _ in filter_ui_feature_catalog(catalog=catalog, query="quiz")]
    assert first == second
    assert "Quiz" in first


def test_runtime_inventory_adapter_extracts_tools_workflows_and_stages() -> None:
    tools = [
        SimpleNamespace(
            key="quiz",
            intent="quiz",
            title="Quiz",
            description="Quiz tool",
            execution_spec={
                "stage_profile": "default_asset_profile",
                "verify_profile": "structured_asset_verify",
                "verify_required": True,
            },
        ),
        SimpleNamespace(
            key="video",
            intent="video",
            title="Video Builder",
            description="Video tool",
            execution_spec={
                "stage_profile": "media_asset_profile",
                "verify_profile": "media_asset_verify",
                "verify_required": True,
            },
        ),
    ]
    workflows = [
        SimpleNamespace(
            key="full_asset_suite",
            title="Full Asset Suite",
            description="Runs all tools",
            tool_keys=["quiz", "video"],
            tool_dependencies={"video": ["quiz"]},
        )
    ]

    class _MockService:
        def list_registered_tools(self):  # noqa: ANN201
            return tools

        def list_registered_workflows(self):  # noqa: ANN201
            return workflows

        def list_tool_stage_sequences(self):  # noqa: ANN201
            return {"quiz": ["prepare", "generate", "verify"], "video": ["prepare", "render"]}

    inventory = collect_runtime_inventory(
        enabled_tab_titles=["Quiz", "Documentation Center"],
        agent_dashboard_service=_MockService(),
    )

    assert inventory["visible_tab_count"] == 2
    assert inventory["tool_count"] == 2
    assert inventory["workflow_count"] == 1
    assert inventory["stage_profile_count"] == 2
    assert inventory["stage_sequences"]["quiz"] == ["prepare", "generate", "verify"]
