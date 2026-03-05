from __future__ import annotations

from typing import Any

from main_app.contracts import ArtifactMap, AssetArtifactEnvelope, AssetSection, JSONValue, ToolExecutionSpec
from main_app.models import AgentAssetResult


ARTIFACT_TOPIC_TEXT = "artifact.topic.text"
ARTIFACT_MINDMAP_TREE = "artifact.mindmap.tree"
ARTIFACT_FLASHCARDS_CARDS = "artifact.flashcards.cards"
ARTIFACT_TABLE_DATA = "artifact.table.data"
ARTIFACT_QUIZ_DATA = "artifact.quiz.data"
ARTIFACT_SLIDESHOW_SLIDES = "artifact.slideshow.slides"
ARTIFACT_VIDEO_PAYLOAD = "artifact.video.payload"
ARTIFACT_VIDEO_AUDIO = "artifact.video.audio"
ARTIFACT_CARTOON_PAYLOAD = "artifact.cartoon_shorts.payload"
ARTIFACT_CARTOON_OUTPUTS = "artifact.cartoon_shorts.outputs"
ARTIFACT_AUDIO_OVERVIEW_PAYLOAD = "artifact.audio_overview.payload"
ARTIFACT_AUDIO_OVERVIEW_AUDIO = "artifact.audio_overview.audio"
ARTIFACT_REPORT_TEXT = "artifact.report.text"


def default_produced_artifact_keys_by_intent(intent: str) -> list[str]:
    normalized = " ".join(str(intent).strip().split()).lower()
    if normalized == "topic":
        return [ARTIFACT_TOPIC_TEXT]
    if normalized == "mindmap":
        return [ARTIFACT_MINDMAP_TREE]
    if normalized == "flashcards":
        return [ARTIFACT_FLASHCARDS_CARDS]
    if normalized == "data table":
        return [ARTIFACT_TABLE_DATA]
    if normalized == "quiz":
        return [ARTIFACT_QUIZ_DATA]
    if normalized == "slideshow":
        return [ARTIFACT_SLIDESHOW_SLIDES]
    if normalized == "video":
        return [ARTIFACT_VIDEO_PAYLOAD, ARTIFACT_VIDEO_AUDIO]
    if normalized == "cartoon_shorts":
        return [ARTIFACT_CARTOON_PAYLOAD, ARTIFACT_CARTOON_OUTPUTS]
    if normalized == "audio_overview":
        return [ARTIFACT_AUDIO_OVERVIEW_PAYLOAD, ARTIFACT_AUDIO_OVERVIEW_AUDIO]
    if normalized == "report":
        return [ARTIFACT_REPORT_TEXT]
    return []


def default_required_artifact_keys_by_intent(intent: str) -> list[str]:
    normalized = " ".join(str(intent).strip().split()).lower()
    if normalized == "video":
        return [ARTIFACT_SLIDESHOW_SLIDES]
    return []


def default_optional_required_artifact_keys_by_intent(intent: str) -> list[str]:
    normalized = " ".join(str(intent).strip().split()).lower()
    if normalized in {"mindmap", "flashcards", "data table", "quiz", "slideshow", "audio_overview"}:
        return [ARTIFACT_TOPIC_TEXT]
    if normalized == "cartoon_shorts":
        return [ARTIFACT_TOPIC_TEXT]
    if normalized == "report":
        return [
            ARTIFACT_TOPIC_TEXT,
            ARTIFACT_MINDMAP_TREE,
            ARTIFACT_FLASHCARDS_CARDS,
            ARTIFACT_TABLE_DATA,
            ARTIFACT_QUIZ_DATA,
            ARTIFACT_SLIDESHOW_SLIDES,
            ARTIFACT_VIDEO_PAYLOAD,
            ARTIFACT_CARTOON_PAYLOAD,
            ARTIFACT_AUDIO_OVERVIEW_PAYLOAD,
        ]
    return []


def build_artifact_envelope(
    *,
    intent: str,
    title: str,
    summary: str = "",
    sections: list[AssetSection] | None = None,
    attachments: dict[str, JSONValue] | None = None,
    metrics: dict[str, JSONValue] | None = None,
    provenance: dict[str, JSONValue] | None = None,
) -> AssetArtifactEnvelope:
    return {
        "intent": intent,
        "title": title,
        "summary": summary,
        "sections": list(sections or []),
        "attachments": dict(attachments or {}),
        "metrics": dict(metrics or {}),
        "provenance": dict(provenance or {}),
    }


def legacy_result_to_artifact(result: AgentAssetResult) -> AssetArtifactEnvelope:
    base_title = result.title.strip() or result.intent.strip() or "Asset"
    sections: list[AssetSection] = []
    attachments: dict[str, JSONValue] = {}
    metrics: dict[str, JSONValue] = {"cache_hit": bool(result.cache_hit)}
    provenance: dict[str, JSONValue] = {}

    if result.parse_note.strip():
        provenance["parse_note"] = result.parse_note.strip()
    if result.raw_text.strip():
        provenance["raw_text"] = result.raw_text.strip()

    if result.status != "success":
        sections.append(
            {
                "kind": "meta",
                "key": "error",
                "title": "Error",
                "data": {"message": result.error or "Asset generation failed."},
                "optional": False,
            }
        )
        return build_artifact_envelope(
            intent=result.intent,
            title=base_title,
            summary=result.error or "Asset generation failed.",
            sections=sections,
            attachments=attachments,
            metrics=metrics,
            provenance=provenance,
        )

    content_value: JSONValue = _json_safe(result.content)
    content_kind = _content_kind_for_intent(result.intent, content_value)
    sections.append(
        {
            "kind": content_kind,
            "key": _primary_section_key_for_intent(result.intent),
            "title": "Primary Content",
            "data": content_value,
            "optional": False,
        }
    )

    if result.audio_bytes is not None:
        attachments["audio_bytes"] = f"<bytes:{len(result.audio_bytes)}>"
    if result.audio_error.strip():
        attachments["audio_error"] = result.audio_error.strip()

    return build_artifact_envelope(
        intent=result.intent,
        title=base_title,
        summary=result.parse_note.strip() or "",
        sections=sections,
        attachments=attachments,
        metrics=metrics,
        provenance=provenance,
    )


def collect_produced_artifacts(
    *,
    result: AgentAssetResult,
    execution_spec: ToolExecutionSpec | None,
) -> ArtifactMap:
    produced_map: ArtifactMap = {}
    produced_keys = _extract_dependency_field(execution_spec, "produces_artifacts")
    if not produced_keys:
        return produced_map
    envelope = result.artifact or legacy_result_to_artifact(result)
    sections = envelope.get("sections", []) if isinstance(envelope.get("sections"), list) else []
    section_map: dict[str, JSONValue] = {}
    for section in sections:
        if not isinstance(section, dict):
            continue
        key = " ".join(str(section.get("key", "")).split()).strip()
        if not key:
            continue
        section_map[key] = _json_safe(section.get("data"))
    for artifact_key in produced_keys:
        if artifact_key in section_map:
            produced_map[artifact_key] = section_map[artifact_key]
            continue
        if artifact_key.endswith(".audio") and result.audio_bytes is not None:
            produced_map[artifact_key] = f"<bytes:{len(result.audio_bytes)}>"
            continue
        produced_map[artifact_key] = _json_safe(result.content)
    return produced_map


def required_artifacts(execution_spec: ToolExecutionSpec | None) -> list[str]:
    return _extract_dependency_field(execution_spec, "requires_artifacts")


def optional_required_artifacts(execution_spec: ToolExecutionSpec | None) -> list[str]:
    return _extract_dependency_field(execution_spec, "optional_requires")


def _extract_dependency_field(execution_spec: ToolExecutionSpec | None, field: str) -> list[str]:
    if not isinstance(execution_spec, dict):
        return []
    dependency = execution_spec.get("dependency")
    if not isinstance(dependency, dict):
        return []
    values = dependency.get(field)
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _content_kind_for_intent(intent: str, content: JSONValue) -> str:
    normalized = " ".join(str(intent).strip().split()).lower()
    if normalized in {"topic", "report"} and isinstance(content, str):
        return "text"
    if normalized == "data table":
        return "table"
    if normalized == "slideshow":
        return "slides"
    if normalized == "quiz":
        return "quiz"
    if normalized == "mindmap":
        return "mindmap"
    if normalized in {"video"}:
        return "video"
    if normalized in {"cartoon_shorts"}:
        return "video"
    if normalized in {"audio_overview"}:
        return "audio"
    return "data"


def _primary_section_key_for_intent(intent: str) -> str:
    default_map = {
        "topic": ARTIFACT_TOPIC_TEXT,
        "mindmap": ARTIFACT_MINDMAP_TREE,
        "flashcards": ARTIFACT_FLASHCARDS_CARDS,
        "data table": ARTIFACT_TABLE_DATA,
        "quiz": ARTIFACT_QUIZ_DATA,
        "slideshow": ARTIFACT_SLIDESHOW_SLIDES,
        "video": ARTIFACT_VIDEO_PAYLOAD,
        "cartoon_shorts": ARTIFACT_CARTOON_PAYLOAD,
        "audio_overview": ARTIFACT_AUDIO_OVERVIEW_PAYLOAD,
        "report": ARTIFACT_REPORT_TEXT,
    }
    normalized = " ".join(str(intent).strip().split()).lower()
    return default_map.get(normalized, f"artifact.{normalized or 'unknown'}.primary")


def _json_safe(value: Any) -> JSONValue:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return [_json_safe(item) for item in sorted(value, key=str)]
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
