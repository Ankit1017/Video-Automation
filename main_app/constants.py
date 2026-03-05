from pathlib import Path

PAGE_TITLE = "Topic Explainer"
PAGE_LAYOUT = "wide"
APP_TITLE = "Knowledge App"
APP_DESCRIPTION = (
    "Use separate tabs for detailed explanations, hierarchical mind maps, interactive flashcards, "
    "report generation, data table building, quiz practice, slide creation, narrated video generation, "
    "cartoon shorts studio generation, audio overviews, web sourcing checks, documentation center guidance, chat intent detection, "
    "agent dashboard chat orchestration, and asset history."
)

CACHE_FILE = Path(".cache/llm_cache.json")
QUIZ_HISTORY_FILE = Path(".cache/quiz_history.json")
AGENT_DASHBOARD_SESSIONS_FILE = Path(".cache/agent_dashboard_sessions.json")
ASSET_HISTORY_FILE = Path(".cache/asset_history.json")
RUN_LEDGER_FILE = Path(".cache/run_ledger.json")
STAGE_LEDGER_FILE = Path(".cache/stage_ledger.json")
SESSION_DEFAULT_OVERRIDES_FILE = Path(".cache/session_default_overrides.json")
PRESET_MODELS = [
    "llama-3.1-8b-instant",
    "allam-2-7b",
    "groq/compound",
    "groq/compound-mini",
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-guard-4-12b",
    "meta-llama/llama-prompt-guard-2-22m",
    "meta-llama/llama-prompt-guard-2-86m",
    "moonshotai/kimi-k2-instruct",
    "moonshotai/kimi-k2-instruct-0905",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-safeguard-20b",
    "qwen/qwen3-32b",
]
TAB_TITLES = [
    "Detailed Description",
    "Mind Map Builder",
    "Flashcards",
    "Create Report",
    "Data Table",
    "Quiz",
    "Slide Show",
    "Video Builder",
    "Cartoon Shorts Studio",
    "Audio Overview",
    "Web Sourcing Check",
    "Cache Center",
    "Documentation Center",
    "Observability",
    "Additional Settings",
    "Chat Bot Intent",
    "Agent Dashboard",
    "Asset History",
]
