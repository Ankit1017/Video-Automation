from __future__ import annotations

from typing import Any

from main_app.services.pptx_export.models import LayoutPlan
from main_app.services.pptx_export.text_utils import normalize_text, prepare_code_payload
from main_app.shared.slideshow.representation_normalizer import normalize_slide_representation


def plan_slide_layout(*, slide: dict[str, Any]) -> LayoutPlan:
    normalized_slide, _ = normalize_slide_representation(slide if isinstance(slide, dict) else {})
    title = normalize_text(normalized_slide.get("title", "")) or "Untitled"
    section = normalize_text(normalized_slide.get("section", ""))
    speaker_notes = str(normalized_slide.get("speaker_notes", "")).strip()

    bullets = normalized_slide.get("bullets", [])
    if not isinstance(bullets, list):
        bullets = []
    bullet_texts = [normalize_text(item) for item in bullets if normalize_text(item)]
    if not bullet_texts:
        bullet_texts = ["Key concept summary for this slide."]
    bullet_texts = bullet_texts[:6]

    raw_code_snippet = str(normalized_slide.get("code_snippet", ""))
    raw_code_language = normalize_text(normalized_slide.get("code_language", ""))
    code_snippet, code_language = prepare_code_payload(
        code_snippet=raw_code_snippet,
        code_language=raw_code_language,
    )
    if code_snippet:
        return LayoutPlan(
            layout_type="split_code",
            title=title,
            section=section,
            bullets=bullet_texts[:5],
            code_snippet=code_snippet,
            code_language=code_language,
            speaker_notes=speaker_notes,
        )

    representation = " ".join(str(normalized_slide.get("representation", "bullet")).split()).strip().lower()
    layout_payload = normalized_slide.get("layout_payload", {})
    payload = layout_payload if isinstance(layout_payload, dict) else {}

    if representation in {"two_column", "comparison"}:
        left_title = normalize_text(payload.get("left_title", "Left" if representation == "two_column" else "Option A"))
        right_title = normalize_text(payload.get("right_title", "Right" if representation == "two_column" else "Option B"))
        left_key = "left_items" if representation == "two_column" else "left_points"
        right_key = "right_items" if representation == "two_column" else "right_points"
        left_items = _normalize_list(payload.get(left_key), limit=4)
        right_items = _normalize_list(payload.get(right_key), limit=4)
        if not left_items and not right_items:
            midpoint = max(1, len(bullet_texts) // 2)
            left_items = bullet_texts[:midpoint]
            right_items = bullet_texts[midpoint:]
        return LayoutPlan(
            layout_type="dual_column",
            title=title,
            section=section,
            bullets=bullet_texts,
            left_title=left_title or "Left",
            right_title=right_title or "Right",
            left_items=left_items or ["No content provided."],
            right_items=right_items or ["No content provided."],
            speaker_notes=speaker_notes,
        )

    if representation == "timeline":
        events = _normalize_timeline_events(payload.get("events"), fallback_bullets=bullet_texts)
        if _too_dense_for_timeline(events):
            return LayoutPlan(
                layout_type="summary",
                title=title,
                section=section,
                bullets=bullet_texts,
                speaker_notes=speaker_notes,
            )
        return LayoutPlan(
            layout_type="timeline",
            title=title,
            section=section,
            bullets=bullet_texts,
            events=events,
            speaker_notes=speaker_notes,
        )

    if representation == "process_flow":
        steps = _normalize_process_steps(payload.get("steps"), fallback_bullets=bullet_texts)
        if _too_dense_for_steps(steps):
            return LayoutPlan(
                layout_type="summary",
                title=title,
                section=section,
                bullets=bullet_texts,
                speaker_notes=speaker_notes,
            )
        return LayoutPlan(
            layout_type="process_flow",
            title=title,
            section=section,
            bullets=bullet_texts,
            steps=steps,
            speaker_notes=speaker_notes,
        )

    if representation == "metric_cards":
        cards = _normalize_metric_cards(payload.get("cards"), fallback_bullets=bullet_texts)
        return LayoutPlan(
            layout_type="metric_cards",
            title=title,
            section=section,
            bullets=bullet_texts,
            cards=cards,
            speaker_notes=speaker_notes,
        )

    return LayoutPlan(
        layout_type="summary",
        title=title,
        section=section,
        bullets=bullet_texts,
        speaker_notes=speaker_notes,
    )


def plan_deck_layout(*, slides: list[dict[str, Any]]) -> list[LayoutPlan]:
    plans: list[LayoutPlan] = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        plans.append(plan_slide_layout(slide=slide))
    return plans


def _normalize_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = normalize_text(item)
        if not text:
            continue
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _normalize_timeline_events(raw_events: Any, *, fallback_bullets: list[str]) -> list[dict[str, str]]:
    parsed: list[dict[str, str]] = []
    if isinstance(raw_events, list):
        for event in raw_events[:5]:
            if not isinstance(event, dict):
                continue
            label = normalize_text(event.get("label", ""))
            detail = normalize_text(event.get("detail", ""))
            if not label and not detail:
                continue
            parsed.append({"label": label or "Milestone", "detail": detail})
    if parsed:
        return parsed
    fallback: list[dict[str, str]] = []
    for index, bullet in enumerate(fallback_bullets[:5], start=1):
        fallback.append({"label": f"Milestone {index}", "detail": bullet})
    if not fallback:
        fallback = [{"label": "Milestone", "detail": "No timeline events provided."}]
    return fallback


def _normalize_process_steps(raw_steps: Any, *, fallback_bullets: list[str]) -> list[dict[str, str]]:
    parsed: list[dict[str, str]] = []
    if isinstance(raw_steps, list):
        for step in raw_steps[:5]:
            if not isinstance(step, dict):
                continue
            title = normalize_text(step.get("title", ""))
            detail = normalize_text(step.get("detail", ""))
            if not title and not detail:
                continue
            parsed.append({"title": title or "Step", "detail": detail})
    if parsed:
        return parsed
    fallback: list[dict[str, str]] = []
    for index, bullet in enumerate(fallback_bullets[:5], start=1):
        fallback.append({"title": f"Step {index}", "detail": bullet})
    if not fallback:
        fallback = [{"title": "Step 1", "detail": "No process steps provided."}]
    return fallback


def _normalize_metric_cards(raw_cards: Any, *, fallback_bullets: list[str]) -> list[dict[str, str]]:
    parsed: list[dict[str, str]] = []
    if isinstance(raw_cards, list):
        for card in raw_cards[:4]:
            if not isinstance(card, dict):
                continue
            label = normalize_text(card.get("label", ""))
            value = normalize_text(card.get("value", ""))
            context = normalize_text(card.get("context", ""))
            if not label and not value and not context:
                continue
            parsed.append({"label": label or "Metric", "value": value, "context": context})
    if parsed:
        return parsed
    fallback: list[dict[str, str]] = []
    for index, bullet in enumerate(fallback_bullets[:4], start=1):
        fallback.append({"label": f"Metric {index}", "value": bullet, "context": ""})
    if not fallback:
        fallback = [{"label": "Metric", "value": "No metric cards provided.", "context": ""}]
    return fallback


def _too_dense_for_timeline(events: list[dict[str, str]]) -> bool:
    if len(events) <= 1:
        return False
    total_chars = sum(len(event.get("label", "")) + len(event.get("detail", "")) for event in events)
    return total_chars > 700


def _too_dense_for_steps(steps: list[dict[str, str]]) -> bool:
    if len(steps) <= 1:
        return False
    total_chars = sum(len(step.get("title", "")) + len(step.get("detail", "")) for step in steps)
    return total_chars > 800

