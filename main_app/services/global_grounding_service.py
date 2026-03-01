from __future__ import annotations

from typing import Any, Iterable

from main_app.models import WebSourcingSettings
from main_app.platform.web_sourcing.orchestrator import WebSourcingOrchestrator
from main_app.services.observability_service import ensure_request_id
from main_app.services.source_grounding_service import SourceDocument, SourceGroundingService
from main_app.services.telemetry_service import ObservabilityEvent, TelemetryService


class GlobalGroundingService:
    def __init__(
        self,
        *,
        source_grounding_service: SourceGroundingService,
        web_orchestrator: WebSourcingOrchestrator | None = None,
        telemetry_service: TelemetryService | None = None,
    ) -> None:
        self._source_grounding_service = source_grounding_service
        self._telemetry_service = telemetry_service
        self._web_orchestrator = web_orchestrator or WebSourcingOrchestrator(telemetry_service=telemetry_service)

    def build_sources(
        self,
        uploaded_files: Iterable[Any],
        *,
        topic: str,
        constraints: str,
        web_settings: WebSourcingSettings,
        max_sources: int,
    ) -> tuple[list[SourceDocument], list[str], dict[str, Any]]:
        request_id = ensure_request_id()
        warnings: list[str] = []
        diagnostics: dict[str, Any] = {}
        context_scope = (
            self._telemetry_service.context_scope(request_id=request_id)
            if self._telemetry_service is not None
            else _null_context()
        )
        with context_scope:
            if self._telemetry_service is not None:
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="grounding.build_sources.start",
                        component="grounding.global",
                        status="started",
                        timestamp=_now_iso(),
                        attributes={
                            "web_enabled": bool(web_settings.enabled),
                            "max_sources": int(max_sources),
                        },
                    )
                )

            upload_sources, upload_warnings = self._source_grounding_service.extract_sources(
                uploaded_files,
                max_sources=max_sources,
            )
            warnings.extend(upload_warnings)

            web_sources: list[SourceDocument] = []
            if web_settings.enabled:
                web_result = self._web_orchestrator.run(
                    topic=topic,
                    constraints=constraints,
                    settings=web_settings,
                )
                warnings.extend(web_result.warnings)
                page_summaries: list[dict[str, Any]] = []
                diagnostics.update(
                    {
                        "web_sourcing_enabled": True,
                        "web_provider": web_result.provider,
                        "web_cache_hit": web_result.cache_hit,
                        "web_source_count": len(web_result.fetched_pages),
                        "web_query": web_result.query,
                        "web_search_count": int(web_result.diagnostics.get("search_count", 0) or 0),
                        "web_attempted_count": int(web_result.diagnostics.get("attempted_count", 0) or 0),
                        "web_fetched_count": int(web_result.diagnostics.get("fetched_count", 0) or 0),
                        "web_accepted_count": int(web_result.diagnostics.get("accepted_count", 0) or 0),
                        "web_run_diagnostics": dict(web_result.diagnostics),
                    }
                )
                for page in web_result.fetched_pages:
                    if len(upload_sources) + len(web_sources) >= max_sources:
                        break
                    text = " ".join(str(page.text).split()).strip()
                    if not text:
                        continue
                    page_summaries.append(
                        {
                            "uri": page.final_url or page.url,
                            "title": page.title,
                            "quality_score": float(page.quality_score),
                            "quality_reasons": list(page.quality_reasons),
                            "domain": page.domain,
                        }
                    )
                    web_sources.append(
                        SourceDocument(
                            source_id="",
                            name=page.title or page.final_url or page.url,
                            text=text,
                            char_count=len(text),
                            truncated=bool(page.truncated),
                            source_type="web",
                            uri=page.final_url or page.url,
                            provider=web_result.provider,
                            query=web_result.query,
                            retrieved_at=page.retrieved_at,
                            quality_score=float(page.quality_score),
                        )
                    )
                diagnostics["web_warnings"] = [item for item in warnings if "web" in item.lower()]
                diagnostics["web_page_summaries"] = page_summaries
                diagnostics["web_quality_stats"] = dict(web_result.diagnostics.get("quality_stats", {}))
                diagnostics["web_fallback_quality_mode_used"] = bool(
                    web_result.diagnostics.get("fallback_quality_mode_used", False)
                )
                diagnostics["web_failover_used"] = bool(web_result.diagnostics.get("failover_used", False))
                diagnostics["web_failover_reason"] = str(web_result.diagnostics.get("failover_reason", ""))
                diagnostics["web_retry_events"] = int(web_result.diagnostics.get("retry_events", 0) or 0)
                diagnostics["web_rate_limited_urls"] = int(web_result.diagnostics.get("rate_limited_urls", 0) or 0)
                diagnostics["web_content_cache_hit_count"] = int(
                    web_result.diagnostics.get("content_cache_hit_count", 0) or 0
                )
                diagnostics["web_content_cache_miss_count"] = int(
                    web_result.diagnostics.get("content_cache_miss_count", 0) or 0
                )
                provider_attempts_raw = web_result.diagnostics.get("provider_attempts", [])
                diagnostics["web_provider_attempts"] = (
                    list(provider_attempts_raw)
                    if isinstance(provider_attempts_raw, list)
                    else []
                )
                circuit_state_raw = web_result.diagnostics.get("provider_circuit_state", {})
                diagnostics["web_provider_circuit_state"] = (
                    dict(circuit_state_raw)
                    if isinstance(circuit_state_raw, dict)
                    else {}
                )
                provider_failures_raw = web_result.diagnostics.get("provider_failures", {})
                diagnostics["web_provider_failures"] = (
                    dict(provider_failures_raw)
                    if isinstance(provider_failures_raw, dict)
                    else {}
                )
            else:
                diagnostics.update(
                    {
                        "web_sourcing_enabled": False,
                        "web_provider": "",
                        "web_cache_hit": False,
                        "web_source_count": 0,
                        "web_query": "",
                        "web_search_count": 0,
                        "web_attempted_count": 0,
                        "web_fetched_count": 0,
                        "web_accepted_count": 0,
                        "web_run_diagnostics": {},
                        "web_warnings": [],
                        "web_page_summaries": [],
                        "web_quality_stats": {},
                        "web_fallback_quality_mode_used": False,
                        "web_failover_used": False,
                        "web_failover_reason": "",
                        "web_retry_events": 0,
                        "web_rate_limited_urls": 0,
                        "web_content_cache_hit_count": 0,
                        "web_content_cache_miss_count": 0,
                        "web_provider_attempts": [],
                        "web_provider_circuit_state": {},
                        "web_provider_failures": {},
                    }
                )

            merged = upload_sources + web_sources
            if len(merged) > max_sources:
                merged = merged[:max_sources]
                warnings.append(f"Only the first {max_sources} combined sources were used.")

            final_sources = self._reindex_sources(merged)
            diagnostics["upload_source_count"] = len(upload_sources)
            diagnostics["combined_source_count"] = len(final_sources)
            diagnostics["combined_char_count"] = sum(source.char_count for source in final_sources)

            if web_settings.enabled:
                char_cap = max(2000, int(web_settings.max_total_chars))
                final_sources, cap_warnings = self._enforce_char_cap(final_sources, max_total_chars=char_cap)
                warnings.extend(cap_warnings)

            if self._telemetry_service is not None:
                payload_ref = self._telemetry_service.attach_payload(
                    payload={
                        "diagnostics": diagnostics,
                        "warnings": warnings,
                        "topic": topic,
                        "constraints": constraints,
                    },
                    kind="grounding_build_sources",
                )
                self._telemetry_service.record_metric(
                    name="grounding_sources_total",
                    value=float(len(final_sources)),
                    attrs={"web_enabled": bool(web_settings.enabled)},
                )
                self._telemetry_service.record_event(
                    ObservabilityEvent(
                        event_name="grounding.build_sources.end",
                        component="grounding.global",
                        status="ok",
                        timestamp=_now_iso(),
                        attributes={
                            "upload_source_count": diagnostics.get("upload_source_count", 0),
                            "combined_source_count": diagnostics.get("combined_source_count", 0),
                            "combined_char_count": diagnostics.get("combined_char_count", 0),
                            "web_source_count": diagnostics.get("web_source_count", 0),
                        },
                        payload_ref=payload_ref,
                    )
                )

            return final_sources, warnings, diagnostics

    @staticmethod
    def _reindex_sources(sources: list[SourceDocument]) -> list[SourceDocument]:
        output: list[SourceDocument] = []
        for index, source in enumerate(sources, start=1):
            output.append(
                SourceDocument(
                    source_id=f"S{index}",
                    name=source.name,
                    text=source.text,
                    char_count=len(source.text),
                    truncated=source.truncated,
                    source_type=source.source_type,
                    uri=source.uri,
                    provider=source.provider,
                    query=source.query,
                    retrieved_at=source.retrieved_at,
                    quality_score=source.quality_score,
                )
            )
        return output

    @staticmethod
    def _enforce_char_cap(
        sources: list[SourceDocument],
        *,
        max_total_chars: int,
    ) -> tuple[list[SourceDocument], list[str]]:
        warnings: list[str] = []
        remaining = max_total_chars
        output: list[SourceDocument] = []

        for source in sources:
            if remaining <= 0:
                warnings.append("Combined source char budget reached; extra sources were dropped.")
                break
            text = source.text
            truncated = source.truncated
            if len(text) > remaining:
                text = text[:remaining].rstrip()
                truncated = True
            if not text:
                continue
            output.append(
                SourceDocument(
                    source_id=source.source_id,
                    name=source.name,
                    text=text,
                    char_count=len(text),
                    truncated=truncated,
                    source_type=source.source_type,
                    uri=source.uri,
                    provider=source.provider,
                    query=source.query,
                    retrieved_at=source.retrieved_at,
                    quality_score=source.quality_score,
                )
            )
            remaining -= len(text)
        return output, warnings


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


from contextlib import contextmanager
from typing import Iterator


@contextmanager
def _null_context() -> Iterator[None]:
    yield
