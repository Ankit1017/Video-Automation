from __future__ import annotations

from main_app.services.intent.intent_requirement_spec import INTENT_ORDER

ASSET_INTENTS: tuple[str, ...] = tuple(INTENT_ORDER)

ASSET_TAB_TITLE_BY_INTENT: dict[str, str] = {
    "topic": "Detailed Description",
    "mindmap": "Mind Map Builder",
    "flashcards": "Flashcards",
    "report": "Create Report",
    "data table": "Data Table",
    "quiz": "Quiz",
    "slideshow": "Slide Show",
    "video": "Video Builder",
    "cartoon_shorts": "Cartoon Shorts Studio",
    "audio_overview": "Audio Overview",
}

ASSET_HISTORY_ORDER: tuple[str, ...] = ASSET_INTENTS


def normalize_intent(intent: str) -> str:
    return " ".join(str(intent).strip().split()).lower()


def ordered_asset_intents(intents: list[str] | tuple[str, ...]) -> list[str]:
    normalized_requested = {normalize_intent(intent) for intent in intents if normalize_intent(intent)}
    return [intent for intent in ASSET_INTENTS if intent in normalized_requested]
