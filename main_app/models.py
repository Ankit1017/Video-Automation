from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from main_app.contracts import (
    AssetArtifactEnvelope,
    AudioOverviewPayload,
    CartoonPayload,
    DataTablePayload,
    IntentPayload,
    IntentPayloadMap,
    JSONValue,
    MindMapPayload,
    QuizPayload,
    SlideContent,
    VideoPayload,
    FlashcardsPayload,
)


def _as_intent_payload(value: object) -> IntentPayload:
    if not isinstance(value, dict):
        return {}
    normalized = {str(key): item for key, item in value.items()}
    return cast(IntentPayload, normalized)


def _as_artifact_envelope(value: object) -> AssetArtifactEnvelope | None:
    if not isinstance(value, dict):
        return None
    return cast(AssetArtifactEnvelope, value)


@dataclass(frozen=True)
class GroqSettings:
    api_key: str
    model: str
    temperature: float
    max_tokens: int

    @property
    def normalized_model(self) -> str:
        return self.model.strip()

    def has_api_key(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def has_model(self) -> bool:
        return bool(self.normalized_model)


@dataclass(frozen=True)
class WebSourcingSettings:
    enabled: bool = False
    provider_key: str = "duckduckgo"
    cache_ttl_seconds: int = 21_600
    max_search_results: int = 8
    max_fetch_pages: int = 6
    max_chars_per_page: int = 4_000
    max_total_chars: int = 20_000
    timeout_ms: int = 8_000
    force_refresh: bool = False
    include_domains: list[str] | None = None
    exclude_domains: list[str] | None = None
    allow_recency_days: int | None = None
    strict_mode: bool = False
    query_variant_count: int = 3
    candidate_pool_multiplier: int = 3
    min_quality_score: float = 0.45
    max_results_per_domain: int = 2
    trusted_boost_enabled: bool = True
    trusted_domains: list[str] | None = None
    allow_provider_failover: bool = True
    secondary_provider_key: str = "serper"
    retry_count: int = 2
    retry_base_delay_ms: int = 250
    retry_max_delay_ms: int = 1500
    domain_rate_limit_per_minute: int = 6
    provider_circuit_breaker_enabled: bool = True
    provider_error_threshold: int = 4
    provider_cooldown_seconds: int = 120
    provider_probe_requests: int = 1
    reliability_diagnostics_enabled: bool = True


@dataclass
class MindMapGenerationResult:
    raw_text: str
    parsed_map: MindMapPayload | None
    parse_error: str | None
    parse_note: str | None
    cache_hit: bool


@dataclass
class FlashcardsGenerationResult:
    raw_text: str
    parsed_flashcards: FlashcardsPayload | None
    parse_error: str | None
    parse_note: str | None
    cache_hit: bool


@dataclass(frozen=True)
class ReportFormat:
    key: str
    title: str
    description: str


@dataclass
class ReportGenerationResult:
    content: str
    cache_hit: bool


@dataclass
class DataTableGenerationResult:
    raw_text: str
    parsed_table: DataTablePayload | None
    parse_error: str | None
    parse_note: str | None
    cache_hit: bool


@dataclass
class QuizGenerationResult:
    raw_text: str
    parsed_quiz: QuizPayload | None
    parse_error: str | None
    parse_note: str | None


@dataclass
class SlideShowGenerationResult:
    slides: list[SlideContent] | None
    parse_error: str | None
    parse_notes: list[str]
    cache_hits: int
    total_calls: int
    debug_raw: str | None


@dataclass
class VideoGenerationResult:
    video_payload: VideoPayload | None
    parse_error: str | None
    parse_notes: list[str]
    cache_hits: int
    total_calls: int
    debug_raw: str | None


@dataclass
class AudioOverviewGenerationResult:
    raw_text: str
    parsed_overview: AudioOverviewPayload | None
    parse_error: str | None
    parse_note: str | None
    cache_hit: bool


@dataclass
class CartoonShortsGenerationResult:
    cartoon_payload: CartoonPayload | None
    parse_error: str | None
    parse_notes: list[str]
    cache_hits: int
    total_calls: int
    debug_raw: str | None


@dataclass
class IntentDetectionResult:
    raw_text: str
    intents: list[str] | None
    parse_error: str | None
    parse_note: str | None
    cache_hit: bool


@dataclass
class AgentPlan:
    source_message: str
    planner_mode: str
    intents: list[str]
    payloads: IntentPayloadMap
    missing_mandatory: dict[str, list[str]]
    missing_optional: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_message": self.source_message,
            "planner_mode": self.planner_mode,
            "intents": list(self.intents),
            "payloads": {str(intent): dict(payload) for intent, payload in self.payloads.items()},
            "missing_mandatory": {
                str(intent): [str(field) for field in fields]
                for intent, fields in self.missing_mandatory.items()
            },
            "missing_optional": {
                str(intent): [str(field) for field in fields]
                for intent, fields in self.missing_optional.items()
            },
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "AgentPlan":
        raw = value if isinstance(value, dict) else {}
        payloads_raw = raw.get("payloads", {})
        missing_mandatory_raw = raw.get("missing_mandatory", {})
        missing_optional_raw = raw.get("missing_optional", {})
        return cls(
            source_message=str(raw.get("source_message", "")),
            planner_mode=str(raw.get("planner_mode", "")),
            intents=[str(intent) for intent in raw.get("intents", []) if str(intent).strip()],
            payloads={
                str(intent): _as_intent_payload(payload)
                for intent, payload in (payloads_raw.items() if isinstance(payloads_raw, dict) else [])
                if isinstance(payload, dict)
            },
            missing_mandatory={
                str(intent): [str(field) for field in fields]
                for intent, fields in (missing_mandatory_raw.items() if isinstance(missing_mandatory_raw, dict) else [])
                if isinstance(fields, list)
            },
            missing_optional={
                str(intent): [str(field) for field in fields]
                for intent, fields in (missing_optional_raw.items() if isinstance(missing_optional_raw, dict) else [])
                if isinstance(fields, list)
            },
        )


@dataclass
class AgentAssetResult:
    intent: str
    status: str
    payload: IntentPayload
    title: str = ""
    content: JSONValue | None = None
    error: str = ""
    parse_note: str = ""
    raw_text: str = ""
    cache_hit: bool = False
    audio_bytes: bytes | None = None
    audio_error: str = ""
    artifact: AssetArtifactEnvelope | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "intent": self.intent,
            "status": self.status,
            "payload": dict(self.payload),
            "title": self.title,
            "content": self.content,
            "error": self.error,
            "parse_note": self.parse_note,
            "raw_text": self.raw_text,
            "cache_hit": self.cache_hit,
        }
        if self.audio_bytes is not None:
            data["audio_bytes"] = self.audio_bytes
        if self.audio_error:
            data["audio_error"] = self.audio_error
        if self.artifact is not None:
            data["artifact"] = self.artifact
        return data

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "AgentAssetResult":
        raw = value if isinstance(value, dict) else {}
        payload_raw = raw.get("payload")
        return cls(
            intent=str(raw.get("intent", "")),
            status=str(raw.get("status", "")),
            payload=_as_intent_payload(payload_raw),
            title=str(raw.get("title", "")),
            content=raw.get("content"),  # Preserve stored payload as-is.
            error=str(raw.get("error", "")),
            parse_note=str(raw.get("parse_note", "")),
            raw_text=str(raw.get("raw_text", "")),
            cache_hit=bool(raw.get("cache_hit", False)),
            audio_bytes=raw.get("audio_bytes") if isinstance(raw.get("audio_bytes"), (bytes, bytearray)) else None,
            audio_error=str(raw.get("audio_error", "")),
            artifact=_as_artifact_envelope(raw.get("artifact")),
        )


@dataclass
class AssetHistoryRecord:
    id: str
    asset_type: str
    topic: str
    title: str
    created_at: str
    model: str
    request_payload: IntentPayload
    result_payload: JSONValue
    status: str
    cache_hit: bool
    parse_note: str = ""
    error: str = ""
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "asset_type": self.asset_type,
            "topic": self.topic,
            "title": self.title,
            "created_at": self.created_at,
            "model": self.model,
            "request_payload": dict(self.request_payload),
            "result_payload": self.result_payload,
            "status": self.status,
            "cache_hit": self.cache_hit,
            "parse_note": self.parse_note,
            "error": self.error,
            "raw_text": self.raw_text,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "AssetHistoryRecord":
        raw = value if isinstance(value, dict) else {}
        request_payload = raw.get("request_payload")
        return cls(
            id=str(raw.get("id", "")),
            asset_type=str(raw.get("asset_type", "")),
            topic=str(raw.get("topic", "")),
            title=str(raw.get("title", "")),
            created_at=str(raw.get("created_at", "")),
            model=str(raw.get("model", "")),
            request_payload=_as_intent_payload(request_payload),
            result_payload=cast(JSONValue, raw.get("result_payload")),
            status=str(raw.get("status", "")),
            cache_hit=bool(raw.get("cache_hit", False)),
            parse_note=str(raw.get("parse_note", "")),
            error=str(raw.get("error", "")),
            raw_text=str(raw.get("raw_text", "")),
        )
