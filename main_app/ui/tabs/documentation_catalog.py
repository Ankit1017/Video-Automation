from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

from main_app.constants import TAB_TITLES

UI_DOCUMENTATION_MODE = "UI Documentation"
DEBUG_DOCUMENTATION_MODE = "Debug Documentation"
DOCUMENTATION_MODES = [UI_DOCUMENTATION_MODE, DEBUG_DOCUMENTATION_MODE]


DOCS_WHITELIST: dict[str, str] = {
    "UI Documentation Reference": "docs/UI_DOCUMENTATION_REFERENCE.md",
    "Debug Documentation Reference": "docs/DEBUG_DOCUMENTATION_REFERENCE.md",
    "Video Avatar Mode Guide": "docs/VIDEO_AVATAR_MODE_GUIDE.md",
    "Video Asset Creation E2E": "docs/VIDEO_ASSET_CREATION_E2E_SUMMARY.md",
    "Cartoon Shorts User Guide": "docs/CARTOON_SHORTS_USER_GUIDE.md",
    "Cartoon Shorts Architecture": "docs/CARTOON_SHORTS_ARCHITECTURE.md",
    "Cartoon Shorts Debug Runbook": "docs/CARTOON_SHORTS_DEBUG_RUNBOOK.md",
    "Observability Architecture": "docs/OBSERVABILITY_ARCHITECTURE.md",
    "Observability Debug Cookbook": "docs/OBSERVABILITY_DEBUG_COOKBOOK.md",
    "Operations Runbook": "docs/OPERATIONS_RUNBOOK.md",
    "Agent Workflows and Tools": "docs/AGENT_WORKFLOWS_AND_TOOLS.md",
    "Orchestration State Machine": "docs/ORCHESTRATION_STATE_MACHINE.md",
    "Schema Contracts": "docs/SCHEMA_CONTRACTS.md",
    "Policy Gates": "docs/POLICY_GATES.md",
}


def get_ui_feature_catalog() -> dict[str, dict[str, Any]]:
    return {
        "Detailed Description": {
            "purpose": "Generate a clear long-form explanation for a topic.",
            "inputs": ["Topic", "model settings", "optional web grounding settings"],
            "outputs": ["Structured explanation markdown/text"],
            "typical_workflow": [
                "Enter topic and optional guidance.",
                "Run generation with or without web grounding.",
                "Review output and refine prompts as needed.",
            ],
            "common_mistakes": [
                "Topic is too broad without constraints.",
                "Web sourcing enabled but provider credentials are missing.",
            ],
            "keywords": ["explanation", "topic", "grounding", "long-form"],
            "related_docs": ["docs/UI_DOCUMENTATION_REFERENCE.md"],
        },
        "Mind Map Builder": {
            "purpose": "Build and explore a hierarchical concept map.",
            "inputs": ["Topic", "graph direction/view mode controls"],
            "outputs": ["Mind-map tree and node-level explanation"],
            "typical_workflow": [
                "Generate initial map from topic.",
                "Select nodes to inspect deeper explanations.",
                "Switch graph orientation for readability.",
            ],
            "common_mistakes": [
                "Not selecting a focused node path before explaining.",
                "Expecting graph-style changes to alter generated content.",
            ],
            "keywords": ["mind map", "hierarchy", "nodes", "graph"],
            "related_docs": ["docs/UI_DOCUMENTATION_REFERENCE.md"],
        },
        "Flashcards": {
            "purpose": "Create study flashcards for active recall.",
            "inputs": ["Topic", "navigation controls", "explain card action"],
            "outputs": ["Q/A flashcard set with explanations"],
            "typical_workflow": [
                "Generate card set from topic.",
                "Flip cards to self-test.",
                "Request deeper explanation for difficult cards.",
            ],
            "common_mistakes": [
                "Skipping card explanations for weak areas.",
                "Using vague topics that produce generic cards.",
            ],
            "keywords": ["flashcards", "study", "revision", "qa"],
            "related_docs": ["docs/UI_DOCUMENTATION_REFERENCE.md"],
        },
        "Create Report": {
            "purpose": "Generate report-style output with export support.",
            "inputs": ["Topic", "report format", "optional grounding constraints"],
            "outputs": ["Formatted report content", "report export files"],
            "typical_workflow": [
                "Pick report format and provide topic scope.",
                "Generate draft and validate structure.",
                "Export final report artifact.",
            ],
            "common_mistakes": [
                "Choosing a format without matching audience/goal.",
                "Ignoring citation/source checks when grounding is enabled.",
            ],
            "keywords": ["report", "document", "export", "briefing"],
            "related_docs": ["docs/UI_DOCUMENTATION_REFERENCE.md", "docs/OPERATIONS_RUNBOOK.md"],
        },
        "Data Table": {
            "purpose": "Generate structured tabular comparisons from topic prompts.",
            "inputs": ["Topic", "column preferences", "generation controls"],
            "outputs": ["Columns/rows table data"],
            "typical_workflow": [
                "Define topic and expected table perspective.",
                "Generate table and validate row/column meaning.",
                "Regenerate with tighter constraints if needed.",
            ],
            "common_mistakes": [
                "Asking for too many columns without clear dimensions.",
                "Treating generated rows as fully verified data points.",
            ],
            "keywords": ["table", "structured", "comparison", "rows"],
            "related_docs": ["docs/UI_DOCUMENTATION_REFERENCE.md"],
        },
        "Quiz": {
            "purpose": "Generate interactive quizzes and feedback.",
            "inputs": ["Topic", "question navigation", "hint/explanation actions"],
            "outputs": ["Questions", "answers", "feedback", "quiz exports"],
            "typical_workflow": [
                "Generate quiz set for the target topic.",
                "Attempt each question and review feedback.",
                "Export quiz artifacts for reuse.",
            ],
            "common_mistakes": [
                "Skipping hints/explanations and losing learning value.",
                "Using quiz output as a factual source without review.",
            ],
            "keywords": ["quiz", "questions", "hints", "assessment"],
            "related_docs": ["docs/UI_DOCUMENTATION_REFERENCE.md"],
        },
        "Slide Show": {
            "purpose": "Create presentation-ready slide content and exports.",
            "inputs": ["Topic", "constraints", "representation mode", "job controls"],
            "outputs": ["Slide payload", "PPTX/PDF exports", "background job status"],
            "typical_workflow": [
                "Generate slide outline and content.",
                "Tune design/representation settings.",
                "Run export and verify generated files.",
            ],
            "common_mistakes": [
                "Not checking asynchronous job completion before download.",
                "Over-constraining slides into unreadable density.",
            ],
            "keywords": ["slides", "presentation", "export", "background job"],
            "related_docs": ["docs/UI_DOCUMENTATION_REFERENCE.md", "docs/OPERATIONS_RUNBOOK.md"],
        },
        "Video Builder": {
            "purpose": "Build narrated videos with avatar conversation mode (default) and classic fallback.",
            "inputs": ["Topic", "voice/style controls", "template", "avatar render controls", "job controls"],
            "outputs": ["Video payload", "audio bytes", "rendered video files"],
            "typical_workflow": [
                "Generate video payload from topic.",
                "Preview narration and choose render mode (avatar_conversation/classic_slides).",
                "Run full render/export and validate timeline diagnostics/fallback status.",
            ],
            "common_mistakes": [
                "Ignoring timeline diagnostics before final export.",
                "Expecting instant completion for long rendering jobs.",
            ],
            "keywords": ["video", "narration", "avatars", "render", "timeline"],
            "related_docs": [
                "docs/UI_DOCUMENTATION_REFERENCE.md",
                "docs/VIDEO_ASSET_CREATION_E2E_SUMMARY.md",
                "docs/VIDEO_AVATAR_MODE_GUIDE.md",
            ],
        },
        "Cartoon Shorts Studio": {
            "purpose": "Create animated multi-character cartoon shorts with idea-to-script or manual timeline authoring.",
            "inputs": ["Topic", "idea", "short type", "scene/speaker controls", "timeline source", "output mode"],
            "outputs": ["Cartoon payload", "timeline diagnostics", "9:16 and/or 16:9 MP4 files"],
            "typical_workflow": [
                "Choose idea mode for automatic storyboard or manual mode for timeline JSON.",
                "Generate asset and monitor stage-based background job progress.",
                "Render dual outputs and download script/project/video artifacts.",
            ],
            "common_mistakes": [
                "Invalid manual timeline JSON that skips speaker IDs or turn text.",
                "Expecting dual-format render to complete instantly for long scene timelines.",
            ],
            "keywords": ["cartoon", "shorts", "timeline", "scene", "dual-format"],
            "related_docs": [
                "docs/CARTOON_SHORTS_USER_GUIDE.md",
                "docs/CARTOON_SHORTS_ARCHITECTURE.md",
                "docs/CARTOON_SHORTS_DEBUG_RUNBOOK.md",
            ],
        },
        "Audio Overview": {
            "purpose": "Generate podcast-style audio summaries.",
            "inputs": ["Topic", "constraints", "voice options", "job controls"],
            "outputs": ["Audio script", "audio bytes", "exportable output"],
            "typical_workflow": [
                "Generate audio overview script.",
                "Select language/hyperparameters including Hinglish mode.",
                "Run audio generation and validate playback quality.",
            ],
            "common_mistakes": [
                "Forgetting to adjust narration mode before generation.",
                "Treating long-form audio as guaranteed low-latency output.",
            ],
            "keywords": ["audio", "overview", "narration", "podcast"],
            "related_docs": ["docs/UI_DOCUMENTATION_REFERENCE.md"],
        },
        "Web Sourcing Check": {
            "purpose": "Inspect web grounding retrieval behavior and diagnostics.",
            "inputs": ["Query", "provider", "quality/reliability settings"],
            "outputs": ["Search candidates", "fetched pages", "diagnostics and warnings"],
            "typical_workflow": [
                "Run query with current provider and quality thresholds.",
                "Inspect diagnostics and warning counts.",
                "Tune provider/failover/retry settings and rerun.",
            ],
            "common_mistakes": [
                "Using over-specific queries that return zero candidates.",
                "Ignoring quality thresholds when interpreting fetched pages.",
            ],
            "keywords": ["web sourcing", "provider", "quality", "diagnostics"],
            "related_docs": ["docs/OBSERVABILITY_DEBUG_COOKBOOK.md", "docs/OPERATIONS_RUNBOOK.md"],
        },
        "Cache Center": {
            "purpose": "Inspect and manage LLM cache behavior.",
            "inputs": ["Filter text", "preview limits", "cache actions"],
            "outputs": ["Cache entries table", "cache stats"],
            "typical_workflow": [
                "Filter cache by topic/model details.",
                "Inspect cache payload previews.",
                "Clear stale cache entries when needed.",
            ],
            "common_mistakes": [
                "Clearing cache during active debugging without snapshot.",
                "Assuming cache misses indicate model failure.",
            ],
            "keywords": ["cache", "reuse", "hits", "misses"],
            "related_docs": ["docs/OPERATIONS_RUNBOOK.md"],
        },
        "Documentation Center": {
            "purpose": "Single place for UI usage docs and backend debug docs.",
            "inputs": ["Mode selector", "search query", "doc selector"],
            "outputs": ["In-app guides", "flow cards", "triage playbooks"],
            "typical_workflow": [
                "Use UI mode to learn product usage quickly.",
                "Use Debug mode to map failures to backend checks.",
                "Open curated markdown docs for deeper references.",
            ],
            "common_mistakes": [
                "Using Debug mode without collecting correlation IDs first.",
                "Skipping in-app search for targeted guidance.",
            ],
            "keywords": ["documentation", "ui guide", "debug guide", "runbook"],
            "related_docs": ["docs/UI_DOCUMENTATION_REFERENCE.md", "docs/DEBUG_DOCUMENTATION_REFERENCE.md"],
        },
        "Observability": {
            "purpose": "Inspect unified telemetry metrics/events/payload references.",
            "inputs": ["Metric/event filters", "payload ref lookup"],
            "outputs": ["Tables/charts", "event stream", "downloadable metrics JSON"],
            "typical_workflow": [
                "Start from request/run IDs and filter metrics/events.",
                "Inspect recent telemetry events and statuses.",
                "Use payload references for deep payload inspection.",
            ],
            "common_mistakes": [
                "Debugging without request_id/run_id filters.",
                "Ignoring component labels when triaging failures.",
            ],
            "keywords": ["observability", "metrics", "events", "payloads"],
            "related_docs": ["docs/OBSERVABILITY_ARCHITECTURE.md", "docs/OBSERVABILITY_DEBUG_COOKBOOK.md"],
        },
        "Additional Settings": {
            "purpose": "Configure persistent default settings by group.",
            "inputs": ["Form editor", "JSON editor", "group selector"],
            "outputs": ["Saved session default overrides"],
            "typical_workflow": [
                "Choose group and adjust defaults.",
                "Save and rerun to apply to session state.",
                "Reset group or all overrides as needed.",
            ],
            "common_mistakes": [
                "Saving invalid JSON in advanced editor.",
                "Changing defaults without verifying scope/prefix.",
            ],
            "keywords": ["defaults", "session", "config", "overrides"],
            "related_docs": ["docs/OPERATIONS_RUNBOOK.md"],
        },
        "Chat Bot Intent": {
            "purpose": "Route messages to intents and gather planning hints.",
            "inputs": ["Conversation messages", "planner mode", "context"],
            "outputs": ["Detected intents", "requirements bundle", "chat reply"],
            "typical_workflow": [
                "Submit user intent in chat language.",
                "Review inferred intents and required fields.",
                "Refine prompt before generating assets.",
            ],
            "common_mistakes": [
                "Assuming intent detection is final without review.",
                "Ignoring missing mandatory fields in plan prompts.",
            ],
            "keywords": ["intent", "chat", "routing", "planner"],
            "related_docs": ["docs/AGENT_WORKFLOWS_AND_TOOLS.md"],
        },
        "Agent Dashboard": {
            "purpose": "Plan and orchestrate multi-tool generation workflows.",
            "inputs": ["Planner mode", "tool/workflow actions", "chat history"],
            "outputs": ["Agent plans", "asset runs", "run/stage ledger entries"],
            "typical_workflow": [
                "Generate plan from user prompt.",
                "Confirm/complete required parameters.",
                "Execute assets and inspect stage/run outcomes.",
            ],
            "common_mistakes": [
                "Running without verifying required plan fields.",
                "Ignoring stage-level failures before retrying end-to-end.",
            ],
            "keywords": ["agent", "workflow", "orchestration", "run ledger"],
            "related_docs": [
                "docs/AGENT_WORKFLOWS_AND_TOOLS.md",
                "docs/ORCHESTRATION_STATE_MACHINE.md",
                "docs/POLICY_GATES.md",
            ],
        },
        "Asset History": {
            "purpose": "Browse prior generated assets and rerun/export actions.",
            "inputs": ["Asset filters", "selection controls"],
            "outputs": ["Historical assets", "reusable payloads", "re-export actions"],
            "typical_workflow": [
                "Locate previous run by topic/type.",
                "Inspect generated artifacts and metadata.",
                "Re-export or continue with derivative workflows.",
            ],
            "common_mistakes": [
                "Confusing historical assets with latest run state.",
                "Not validating stale assets against new requirements.",
            ],
            "keywords": ["history", "assets", "rerun", "export"],
            "related_docs": ["docs/OPERATIONS_RUNBOOK.md"],
        },
    }


def get_task_to_tab_matrix() -> list[dict[str, str]]:
    return [
        {
            "user_goal": "Understand a topic quickly",
            "primary_tab": "Detailed Description",
            "supporting_tab": "Web Sourcing Check",
            "output_type": "Narrative explanation",
        },
        {
            "user_goal": "Create study materials",
            "primary_tab": "Flashcards",
            "supporting_tab": "Quiz",
            "output_type": "Q/A cards and assessments",
        },
        {
            "user_goal": "Build a presentation",
            "primary_tab": "Slide Show",
            "supporting_tab": "Video Builder",
            "output_type": "Slides and rendered media",
        },
        {
            "user_goal": "Create animated social media explainers",
            "primary_tab": "Cartoon Shorts Studio",
            "supporting_tab": "Agent Dashboard",
            "output_type": "Cartoon short videos + project timeline",
        },
        {
            "user_goal": "Generate long-form formal output",
            "primary_tab": "Create Report",
            "supporting_tab": "Data Table",
            "output_type": "Report documents",
        },
        {
            "user_goal": "Run multi-asset automation",
            "primary_tab": "Agent Dashboard",
            "supporting_tab": "Asset History",
            "output_type": "Orchestrated asset set",
        },
        {
            "user_goal": "Debug quality/cost/latency issues",
            "primary_tab": "Observability",
            "supporting_tab": "Documentation Center",
            "output_type": "Telemetry and triage steps",
        },
    ]


def get_debug_flow_cards() -> list[dict[str, Any]]:
    return [
        {
            "title": "UI Request Lifecycle",
            "trigger_points": ["Any tab action with generation/execution"],
            "module_paths": ["main_app/app/runtime.py", "main_app/ui/tabs/main_tabs.py"],
            "event_names": ["ui.request", "ui.tab.render"],
            "metric_names": ["ui_request_count", "ui_request_latency_ms"],
            "primary_failure_modes": ["missing request context", "tab render exceptions"],
            "first_checks": ["Confirm `request_id` exists.", "Check tab-level exception in logs/events."],
        },
        {
            "title": "Grounding and Web Sourcing Flow",
            "trigger_points": ["Web-grounded generation in explainer/report/quiz/agent runs"],
            "module_paths": [
                "main_app/services/global_grounding_service.py",
                "main_app/platform/web_sourcing/orchestrator.py",
            ],
            "event_names": [
                "web_sourcing.search",
                "web_sourcing.fetch",
                "web_sourcing.provider_retry",
                "web_sourcing.provider_failover",
            ],
            "metric_names": [
                "web_sourcing_search_total",
                "web_sourcing_fetch_total",
                "web_sourcing_cache_hit_total",
                "web_sourcing_quality_score",
            ],
            "primary_failure_modes": ["no search results", "provider 403/429", "low quality acceptance rate"],
            "first_checks": [
                "Inspect provider diagnostics and warning counts.",
                "Validate quality threshold and strict mode settings.",
                "Confirm fallback provider settings.",
            ],
        },
        {
            "title": "LLM Generation Flow",
            "trigger_points": ["Any generation call via CachedLLMService"],
            "module_paths": ["main_app/services/cached_llm_service.py"],
            "event_names": ["llm.call", "llm.cache_hit", "llm.error"],
            "metric_names": ["llm_tokens_total", "llm_latency_ms", "llm_estimated_cost_usd", "llm_cache_hit_ratio"],
            "primary_failure_modes": ["provider timeout", "token/cost spikes", "cache miss storms"],
            "first_checks": [
                "Filter observability by `request_id` and `run_id`.",
                "Inspect model/max_tokens/temperature for recent requests.",
                "Check OTEL export and local fallback logs.",
            ],
        },
        {
            "title": "Agent Orchestration and Stage Flow",
            "trigger_points": ["Agent Dashboard plan execution", "workflow runs"],
            "module_paths": [
                "main_app/services/agent_dashboard/dashboard_service.py",
                "main_app/services/agent_dashboard/tool_stage_service.py",
                "main_app/services/agent_dashboard/run_ledger_service.py",
                "main_app/services/agent_dashboard/stage_ledger_service.py",
            ],
            "event_names": ["agent.plan", "agent.stage.start", "agent.stage.complete", "agent.stage.failed"],
            "metric_names": ["agent_stage_duration_ms", "agent_stage_failures_total", "agent_runs_total"],
            "primary_failure_modes": ["missing required artifacts", "policy gate rejection", "verification failure"],
            "first_checks": [
                "Find failing `stage_key` and `tool_key`.",
                "Inspect run/stage ledger records for the same `run_id`.",
                "Verify schema/policy gate outcomes.",
            ],
        },
        {
            "title": "Background Job Flow",
            "trigger_points": ["Slideshow/video/audio async exports"],
            "module_paths": ["main_app/services/background_jobs.py"],
            "event_names": ["job.queued", "job.started", "job.completed", "job.failed"],
            "metric_names": ["jobs_running", "job_duration_ms", "job_failures_total"],
            "primary_failure_modes": ["worker exceptions", "context propagation gaps", "stuck running jobs"],
            "first_checks": [
                "Use `job_id` to trace job lifecycle events.",
                "Confirm parent `request_id`/`run_id` propagation.",
                "Check worker pool saturation and retries.",
            ],
        },
        {
            "title": "Export Pipeline Flow",
            "trigger_points": ["Quiz/report/slide/video export actions"],
            "module_paths": [
                "main_app/services/quiz_exporter.py",
                "main_app/services/report_exporter.py",
                "main_app/services/slide_deck_exporter.py",
                "main_app/services/video_exporter.py",
            ],
            "event_names": ["export.started", "export.completed", "export.failed"],
            "metric_names": ["export_duration_ms", "export_failures_total", "export_output_bytes"],
            "primary_failure_modes": ["template/render errors", "invalid payload", "I/O write failures"],
            "first_checks": [
                "Check exporter-specific error message for file path/type.",
                "Inspect generated payload validity before export.",
                "Correlate with recent stage/job failures.",
            ],
        },
        {
            "title": "Observability Signal Flow",
            "trigger_points": ["Any telemetry event/metric/span emission"],
            "module_paths": [
                "main_app/services/telemetry_service.py",
                "main_app/services/observability_service.py",
                "observability/docker-compose.yml",
            ],
            "event_names": ["telemetry.metric", "telemetry.event", "telemetry.payload_ref"],
            "metric_names": ["telemetry_metric_family_count", "telemetry_event_count"],
            "primary_failure_modes": ["OTLP endpoint unavailable", "collector down", "payload vault lookup miss"],
            "first_checks": [
                "Validate `OTEL_EXPORTER_OTLP_ENDPOINT` and collector health.",
                "Confirm fallback buffers are still updating in Observability tab.",
                "Resolve payload via `payload_ref` in payload vault.",
            ],
        },
    ]


def get_debug_playbooks() -> list[dict[str, Any]]:
    return [
        {
            "symptom": "Web sourcing quality is poor or empty",
            "checklist": [
                "Confirm provider and failover settings in Additional Settings.",
                "Inspect diagnostics fields: search_count, fetched_count, accepted_count.",
                "Lower strictness or adjust quality threshold/query variants.",
                "Verify domain filters are not over-restrictive.",
            ],
        },
        {
            "symptom": "LLM latency or cost spikes",
            "checklist": [
                "Filter Observability metrics/events by recent request/run IDs.",
                "Compare model and max token settings with normal baseline.",
                "Check cache hit ratio drop and prompt size changes.",
                "Confirm OTLP exporter is healthy; fallback buffer might hide exporter failures.",
            ],
        },
        {
            "symptom": "Stage failures in Agent Dashboard",
            "checklist": [
                "Locate failing tool/stage from stage ledger.",
                "Check dependency artifacts availability for that stage.",
                "Review schema/policy gate and verification notes.",
                "Retry only failed stage path after fixing root cause.",
            ],
        },
        {
            "symptom": "Background job failures",
            "checklist": [
                "Search events by `job_id` for state transitions.",
                "Confirm worker pool initialized and not saturated.",
                "Verify input payload is complete and serializable.",
                "Check filesystem/output path permissions and write errors.",
            ],
        },
        {
            "symptom": "Export failures",
            "checklist": [
                "Identify exporter type and check exporter-specific error logs.",
                "Validate source artifact payload shape before export.",
                "Check external binary dependencies (for media paths).",
                "Correlate with upstream generation/stage errors.",
            ],
        },
        {
            "symptom": "OTel connectivity errors (localhost:4317 UNAVAILABLE)",
            "checklist": [
                "Ensure Docker Desktop daemon is running and accessible.",
                "Start observability stack from `observability/` using `docker compose up -d`.",
                "Verify collector container health and endpoint config.",
                "If local stack is intentionally down, disable OTEL export temporarily.",
            ],
        },
    ]


def collect_runtime_inventory(
    *,
    enabled_tab_titles: Sequence[str] | None,
    agent_dashboard_service: Any | None,
) -> dict[str, Any]:
    visible_tabs = _normalize_titles(enabled_tab_titles or TAB_TITLES)
    tools: list[dict[str, Any]] = []
    workflows: list[dict[str, Any]] = []
    stage_sequences: dict[str, list[str]] = {}

    if agent_dashboard_service is not None:
        try:
            raw_tools = agent_dashboard_service.list_registered_tools()
        except Exception:  # pragma: no cover - defensive for UI runtime.
            raw_tools = []
        try:
            raw_workflows = agent_dashboard_service.list_registered_workflows()
        except Exception:  # pragma: no cover - defensive for UI runtime.
            raw_workflows = []
        try:
            raw_stage_sequences = agent_dashboard_service.list_tool_stage_sequences()
        except Exception:  # pragma: no cover - defensive for UI runtime.
            raw_stage_sequences = {}

        tools = [_tool_to_row(tool) for tool in raw_tools]
        workflows = [_workflow_to_row(workflow) for workflow in raw_workflows]
        stage_sequences = _normalize_stage_sequences(raw_stage_sequences)

    stage_profiles = sorted(
        {
            " ".join(str(row.get("stage_profile", "")).split()).strip()
            for row in tools
            if " ".join(str(row.get("stage_profile", "")).split()).strip()
        }
    )

    return {
        "visible_tabs": visible_tabs,
        "visible_tab_count": len(visible_tabs),
        "tools": tools,
        "tool_count": len(tools),
        "workflows": workflows,
        "workflow_count": len(workflows),
        "stage_sequences": stage_sequences,
        "stage_profile_count": len(stage_profiles),
        "stage_profiles": stage_profiles,
    }


def filter_ui_feature_catalog(
    *,
    catalog: dict[str, dict[str, Any]],
    query: str,
) -> list[tuple[str, dict[str, Any]]]:
    normalized_query = _normalize_text(query).lower()
    ordered_titles = [title for title in TAB_TITLES if title in catalog]
    remaining_titles = sorted(title for title in catalog if title not in set(ordered_titles))
    titles = [*ordered_titles, *remaining_titles]

    if not normalized_query:
        return [(title, catalog[title]) for title in titles]

    filtered: list[tuple[str, dict[str, Any]]] = []
    for title in titles:
        details = catalog[title]
        haystack = " ".join(
            [
                _normalize_text(title),
                _normalize_text(details.get("purpose", "")),
                " ".join(_normalize_text(item) for item in _string_items(details.get("keywords", []))),
                " ".join(_normalize_text(item) for item in _string_items(details.get("inputs", []))),
                " ".join(_normalize_text(item) for item in _string_items(details.get("outputs", []))),
                " ".join(_normalize_text(item) for item in _string_items(details.get("common_mistakes", []))),
            ]
        ).lower()
        if normalized_query in haystack:
            filtered.append((title, details))
    return filtered


def filter_records_by_query(
    *,
    records: Iterable[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    normalized_query = _normalize_text(query).lower()
    if not normalized_query:
        return list(records)
    filtered: list[dict[str, Any]] = []
    for record in records:
        haystack = _normalize_text(" ".join(str(value) for value in record.values())).lower()
        if normalized_query in haystack:
            filtered.append(record)
    return filtered


def docs_whitelist_labels() -> list[str]:
    return list(DOCS_WHITELIST.keys())


def resolve_whitelisted_doc_path(
    *,
    label: str,
    repo_root: Path | None = None,
) -> Path:
    normalized_label = " ".join(str(label).split()).strip()
    if normalized_label not in DOCS_WHITELIST:
        raise ValueError("Selected document is not in whitelist.")
    root = (repo_root or Path.cwd()).resolve()
    relative = Path(DOCS_WHITELIST[normalized_label])
    target = (root / relative).resolve()
    docs_root = (root / "docs").resolve()
    if docs_root != target.parent and docs_root not in target.parents:
        raise ValueError("Whitelisted document resolved outside docs directory.")
    return target


def missing_whitelisted_docs(*, repo_root: Path | None = None) -> list[str]:
    missing: list[str] = []
    for label in docs_whitelist_labels():
        try:
            path = resolve_whitelisted_doc_path(label=label, repo_root=repo_root)
        except ValueError:
            missing.append(label)
            continue
        if not path.exists():
            missing.append(label)
    return missing


def _normalize_titles(raw_titles: Sequence[str]) -> list[str]:
    output: list[str] = []
    for item in raw_titles:
        normalized = " ".join(str(item).split()).strip()
        if normalized and normalized not in output:
            output.append(normalized)
    return output


def _normalize_text(value: Any) -> str:
    return " ".join(str(value).split()).strip()


def _string_items(values: Any) -> list[str]:
    return [str(item) for item in values] if isinstance(values, list) else []


def _tool_to_row(tool: Any) -> dict[str, Any]:
    execution_spec = tool.execution_spec if isinstance(getattr(tool, "execution_spec", None), dict) else {}
    return {
        "tool_key": _normalize_text(getattr(tool, "key", "")),
        "intent": _normalize_text(getattr(tool, "intent", "")),
        "title": _normalize_text(getattr(tool, "title", "")),
        "description": _normalize_text(getattr(tool, "description", "")),
        "stage_profile": _normalize_text(execution_spec.get("stage_profile", "")),
        "verify_profile": _normalize_text(execution_spec.get("verify_profile", "")),
        "verify_required": bool(execution_spec.get("verify_required", False)),
    }


def _workflow_to_row(workflow: Any) -> dict[str, Any]:
    tool_keys = list(getattr(workflow, "tool_keys", []) or [])
    tool_dependencies = getattr(workflow, "tool_dependencies", {}) or {}
    return {
        "workflow_key": _normalize_text(getattr(workflow, "key", "")),
        "title": _normalize_text(getattr(workflow, "title", "")),
        "description": _normalize_text(getattr(workflow, "description", "")),
        "tool_keys": [str(item) for item in tool_keys if _normalize_text(item)],
        "tool_count": len([item for item in tool_keys if _normalize_text(item)]),
        "dependency_edges": len(tool_dependencies) if isinstance(tool_dependencies, dict) else 0,
    }


def _normalize_stage_sequences(raw_stage_sequences: Any) -> dict[str, list[str]]:
    if not isinstance(raw_stage_sequences, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for tool_key, stages in raw_stage_sequences.items():
        key = _normalize_text(tool_key)
        if not key:
            continue
        sequence = [_normalize_text(stage) for stage in stages] if isinstance(stages, list) else []
        cleaned = [stage for stage in sequence if stage]
        normalized[key] = cleaned
    return normalized
