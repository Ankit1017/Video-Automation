from __future__ import annotations

import os
from typing import Any, cast

from main_app.contracts import JSONValue, SlideRepresentation


SUPPORTED_REPRESENTATIONS: tuple[SlideRepresentation, ...] = (
    "bullet",
    "two_column",
    "timeline",
    "comparison",
    "process_flow",
    "metric_cards",
)

_MAX_COUNTS: dict[str, int] = {
    "bullet": 6,
    "two_column": 4,
    "timeline": 5,
    "comparison": 4,
    "process_flow": 5,
    "metric_cards": 4,
}

_PROGRESSIVE_REPRESENTATIONS: set[str] = {"bullet", "timeline", "process_flow"}


def _json_list(value: list[Any]) -> list[JSONValue]:
    return cast(list[JSONValue], value)


def slide_representations_enabled() -> bool:
    raw = " ".join(str(os.getenv("ENABLE_SLIDE_REPRESENTATIONS", "true")).split()).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def normalize_representation_mode(mode: str | None) -> str:
    normalized = " ".join(str(mode or "").split()).strip().lower()
    if normalized in {"auto", "classic", "visual"}:
        return normalized
    return "auto"


def is_progressive_representation(representation: str) -> bool:
    return " ".join(str(representation).split()).strip().lower() in _PROGRESSIVE_REPRESENTATIONS


def normalize_slide_representation(slide: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    working = dict(slide)
    if not slide_representations_enabled():
        fallback = _force_bullet(working)
        fallback["representation"] = "bullet"
        fallback["layout_payload"] = {"items": fallback.get("bullets", [])}
        return fallback, "slide representations are disabled by feature flag; used bullet layout."

    raw_representation = " ".join(str(working.get("representation", "bullet")).split()).strip().lower()
    representation: SlideRepresentation
    note: str | None = None
    if raw_representation in SUPPORTED_REPRESENTATIONS:
        representation = raw_representation  # type: ignore[assignment]
    else:
        representation = "bullet"
        if raw_representation:
            note = f"Unknown representation `{raw_representation}`; used `bullet`."

    raw_payload = working.get("layout_payload")
    layout_payload = coerce_layout_payload(representation=representation, layout_payload=raw_payload)
    bullets = _clean_string_list(working.get("bullets"), max_count=_MAX_COUNTS["bullet"])
    if not bullets:
        bullets = representation_to_bullets(representation=representation, layout_payload=layout_payload)
    if not bullets:
        bullets = ["Key concept summary for this slide."]

    code_snippet = str(working.get("code_snippet", "")).strip()
    if code_snippet and representation != "bullet":
        representation = "bullet"
        layout_payload = {"items": _json_list(bullets[: _MAX_COUNTS["bullet"]])}
        note = "Code snippet present; forced representation to `bullet`."

    if representation == "bullet":
        if not isinstance(layout_payload, dict) or not layout_payload.get("items"):
            layout_payload = {"items": _json_list(bullets[: _MAX_COUNTS["bullet"]])}

    working["representation"] = representation
    working["layout_payload"] = layout_payload
    working["bullets"] = bullets[: _MAX_COUNTS["bullet"]]
    return working, note


def coerce_layout_payload(*, representation: str, layout_payload: Any) -> dict[str, JSONValue]:
    normalized = " ".join(str(representation).split()).strip().lower()
    payload = layout_payload if isinstance(layout_payload, dict) else {}

    if normalized == "two_column":
        return {
            "left_title": _clean_text(payload.get("left_title")) or "Left",
            "left_items": _json_list(_clean_string_list(payload.get("left_items"), max_count=_MAX_COUNTS["two_column"])),
            "right_title": _clean_text(payload.get("right_title")) or "Right",
            "right_items": _json_list(_clean_string_list(payload.get("right_items"), max_count=_MAX_COUNTS["two_column"])),
        }
    if normalized == "timeline":
        events: list[dict[str, JSONValue]] = []
        for event in _ensure_list(payload.get("events"))[: _MAX_COUNTS["timeline"]]:
            if not isinstance(event, dict):
                continue
            label = _clean_text(event.get("label"))
            detail = _clean_text(event.get("detail"))
            if not label and not detail:
                continue
            events.append({"label": label, "detail": detail})
        return {"events": _json_list(events)}
    if normalized == "comparison":
        return {
            "left_title": _clean_text(payload.get("left_title")) or "Option A",
            "left_points": _json_list(_clean_string_list(payload.get("left_points"), max_count=_MAX_COUNTS["comparison"])),
            "right_title": _clean_text(payload.get("right_title")) or "Option B",
            "right_points": _json_list(_clean_string_list(payload.get("right_points"), max_count=_MAX_COUNTS["comparison"])),
        }
    if normalized == "process_flow":
        steps: list[dict[str, JSONValue]] = []
        for step in _ensure_list(payload.get("steps"))[: _MAX_COUNTS["process_flow"]]:
            if not isinstance(step, dict):
                continue
            title = _clean_text(step.get("title"))
            detail = _clean_text(step.get("detail"))
            if not title and not detail:
                continue
            steps.append({"title": title or "Step", "detail": detail})
        return {"steps": _json_list(steps)}
    if normalized == "metric_cards":
        cards: list[dict[str, JSONValue]] = []
        for card in _ensure_list(payload.get("cards"))[: _MAX_COUNTS["metric_cards"]]:
            if not isinstance(card, dict):
                continue
            label = _clean_text(card.get("label"))
            value = _clean_text(card.get("value"))
            context = _clean_text(card.get("context"))
            if not label and not value and not context:
                continue
            cards.append({"label": label, "value": value, "context": context})
        return {"cards": _json_list(cards)}
    return {
        "items": _json_list(_clean_string_list(payload.get("items"), max_count=_MAX_COUNTS["bullet"])),
    }


def representation_to_bullets(*, representation: str, layout_payload: dict[str, JSONValue]) -> list[str]:
    normalized = " ".join(str(representation).split()).strip().lower()
    payload = layout_payload if isinstance(layout_payload, dict) else {}
    bullets: list[str] = []

    if normalized == "two_column":
        left_title = _clean_text(payload.get("left_title"))
        right_title = _clean_text(payload.get("right_title"))
        left_items = _clean_string_list(payload.get("left_items"), max_count=_MAX_COUNTS["two_column"])
        right_items = _clean_string_list(payload.get("right_items"), max_count=_MAX_COUNTS["two_column"])
        bullets.extend(_prefixed_items(left_items, left_title))
        bullets.extend(_prefixed_items(right_items, right_title))
    elif normalized == "timeline":
        for event in _ensure_list(payload.get("events"))[: _MAX_COUNTS["timeline"]]:
            if not isinstance(event, dict):
                continue
            label = _clean_text(event.get("label"))
            detail = _clean_text(event.get("detail"))
            if label and detail:
                bullets.append(f"{label}: {detail}")
            elif label:
                bullets.append(label)
            elif detail:
                bullets.append(detail)
    elif normalized == "comparison":
        left_title = _clean_text(payload.get("left_title"))
        right_title = _clean_text(payload.get("right_title"))
        left_points = _clean_string_list(payload.get("left_points"), max_count=_MAX_COUNTS["comparison"])
        right_points = _clean_string_list(payload.get("right_points"), max_count=_MAX_COUNTS["comparison"])
        bullets.extend(_prefixed_items(left_points, left_title))
        bullets.extend(_prefixed_items(right_points, right_title))
    elif normalized == "process_flow":
        for index, step in enumerate(_ensure_list(payload.get("steps"))[: _MAX_COUNTS["process_flow"]], start=1):
            if not isinstance(step, dict):
                continue
            title = _clean_text(step.get("title")) or f"Step {index}"
            detail = _clean_text(step.get("detail"))
            bullets.append(f"{index}. {title}" + (f": {detail}" if detail else ""))
    elif normalized == "metric_cards":
        for card in _ensure_list(payload.get("cards"))[: _MAX_COUNTS["metric_cards"]]:
            if not isinstance(card, dict):
                continue
            label = _clean_text(card.get("label"))
            value = _clean_text(card.get("value"))
            context = _clean_text(card.get("context"))
            core = " - ".join(part for part in [label, value] if part)
            if not core and context:
                bullets.append(context)
            elif core:
                bullets.append(core + (f" ({context})" if context else ""))
    else:
        bullets.extend(_clean_string_list(payload.get("items"), max_count=_MAX_COUNTS["bullet"]))

    if not bullets:
        fallback_items = _clean_string_list(payload.get("items"), max_count=_MAX_COUNTS["bullet"])
        bullets.extend(fallback_items)
    return bullets[: _MAX_COUNTS["bullet"]]


def _prefixed_items(items: list[str], title: str) -> list[str]:
    if not items:
        return []
    if not title:
        return list(items)
    return [f"{title}: {item}" for item in items]


def _force_bullet(slide: dict[str, Any]) -> dict[str, Any]:
    bullets = _clean_string_list(slide.get("bullets"), max_count=_MAX_COUNTS["bullet"])
    if not bullets:
        bullets = ["Key concept summary for this slide."]
    return {
        "title": slide.get("title", ""),
        "section": slide.get("section", ""),
        "bullets": bullets,
        "speaker_notes": slide.get("speaker_notes", ""),
        "code_snippet": slide.get("code_snippet", ""),
        "code_language": slide.get("code_language", ""),
    }


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _ensure_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _clean_string_list(value: Any, *, max_count: int) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = _clean_text(item)
        if not text:
            continue
        cleaned.append(text)
        if len(cleaned) >= max_count:
            break
    return cleaned
