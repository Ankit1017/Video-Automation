from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from typing import Any

from main_app.models import WebSourcingSettings
from main_app.platform.web_sourcing.cache_store import WebSourceCacheStore
from main_app.platform.web_sourcing.contracts import (
    DomainPolicyDecision,
    FetchedPage,
    ProviderAttempt,
    WebSearchResult,
    WebSourcingRunResult,
)
from main_app.platform.web_sourcing.crawler import FocusedCrawler
from main_app.platform.web_sourcing.prechecks import (
    canonicalize_url,
    clamp_int,
    evaluate_domain_policy,
    normalize_domain,
    normalize_query,
)
from main_app.platform.web_sourcing.provider_contracts import WebSearchProvider
from main_app.platform.web_sourcing.providers.duckduckgo_provider import DuckDuckGoSearchProvider
from main_app.platform.web_sourcing.providers.serper_provider import SerperSearchProvider
from main_app.platform.web_sourcing.quality import (
    extract_domain,
    score_fetched_page,
    score_search_candidate,
)
from main_app.platform.web_sourcing.query_strategy import build_query_variants
from main_app.platform.web_sourcing.reliability import (
    DomainRateLimiter,
    ProviderCircuitBreakerRegistry,
    RetryPolicy,
)


class WebSourcingOrchestrator:
    def __init__(
        self,
        *,
        cache_store: WebSourceCacheStore | None = None,
        crawler: FocusedCrawler | None = None,
        providers: dict[str, WebSearchProvider] | None = None,
        domain_rate_limiter: DomainRateLimiter | None = None,
        circuit_breakers: ProviderCircuitBreakerRegistry | None = None,
    ) -> None:
        self._cache_store = cache_store or WebSourceCacheStore()
        self._crawler = crawler or FocusedCrawler()
        self._providers = providers or self._build_default_providers()
        self._domain_rate_limiter = domain_rate_limiter or DomainRateLimiter()
        self._circuit_breakers = circuit_breakers or ProviderCircuitBreakerRegistry()

    def run(
        self,
        *,
        topic: str,
        constraints: str,
        settings: WebSourcingSettings,
    ) -> WebSourcingRunResult:
        normalized_settings = self._normalize_settings(settings)
        if not normalized_settings.enabled:
            return WebSourcingRunResult(
                query="",
                provider=normalized_settings.provider_key,
                search_results=[],
                fetched_pages=[],
                warnings=[],
                diagnostics={"enabled": False},
            )

        query = normalize_query(topic, constraints)
        if not query:
            return WebSourcingRunResult(
                query="",
                provider=normalized_settings.provider_key,
                search_results=[],
                fetched_pages=[],
                warnings=["Web sourcing skipped: query is empty after normalization."],
                diagnostics={"enabled": True, "query_empty": True},
            )

        provider_candidates = self._provider_candidates(normalized_settings)
        requested_provider = provider_candidates[0]
        cache_key = self._cache_key(query=query, settings=normalized_settings, provider=requested_provider)
        if not normalized_settings.force_refresh:
            cached = self._cache_store.get(cache_key, ttl_seconds=normalized_settings.cache_ttl_seconds)
            if isinstance(cached, dict):
                cached_result = self._deserialize_run_result(cached)
                cached_result.cache_hit = True
                cached_result.diagnostics["cache_hit"] = True
                return cached_result

        query_variants = build_query_variants(
            query,
            max_variants=normalized_settings.query_variant_count,
        )
        if not query_variants:
            query_variants = [query]

        warnings: list[str] = []
        provider_attempts: list[ProviderAttempt] = []
        failover_used = False
        failover_reason = ""
        total_retry_events = 0
        total_rate_limited = 0
        selected_provider = requested_provider
        selected_payload: dict[str, Any] | None = None

        for index, provider_key in enumerate(provider_candidates):
            can_attempt, circuit_state = self._circuit_breakers.can_attempt(
                provider_key,
                enabled=normalized_settings.provider_circuit_breaker_enabled,
                cooldown_seconds=normalized_settings.provider_cooldown_seconds,
                probe_requests=normalized_settings.provider_probe_requests,
            )
            if not can_attempt:
                warnings.append(f"Provider `{provider_key}` skipped due to circuit breaker state `{circuit_state}`.")
                provider_attempts.append(
                    ProviderAttempt(
                        provider_key=provider_key,
                        status="circuit_open",
                        circuit_state=circuit_state,
                    )
                )
                if index == 0 and len(provider_candidates) > 1:
                    failover_used = True
                    failover_reason = failover_reason or "primary_circuit_open"
                continue

            try:
                provider = self._resolve_provider(provider_key)
            except RuntimeError as exc:
                warnings.append(str(exc))
                provider_attempts.append(
                    ProviderAttempt(
                        provider_key=provider_key,
                        status="provider_unavailable",
                        error=str(exc),
                        circuit_state=circuit_state,
                    )
                )
                self._circuit_breakers.record_failure(
                    provider_key,
                    enabled=normalized_settings.provider_circuit_breaker_enabled,
                    error_threshold=normalized_settings.provider_error_threshold,
                )
                if index == 0 and len(provider_candidates) > 1:
                    failover_used = True
                    failover_reason = failover_reason or "primary_unavailable"
                continue

            attempt_payload = self._run_provider_pipeline(
                provider=provider,
                query=query,
                query_variants=query_variants,
                settings=normalized_settings,
            )
            total_retry_events += int(attempt_payload.get("retry_events", 0) or 0)
            total_rate_limited += int(attempt_payload.get("rate_limited_count", 0) or 0)
            warnings.extend(list(attempt_payload.get("warnings", [])))

            provider_attempts.append(
                ProviderAttempt(
                    provider_key=provider.key,
                    status=str(attempt_payload.get("status", "")),
                    search_count=int(attempt_payload.get("search_count", 0) or 0),
                    candidate_url_count=int(attempt_payload.get("candidate_url_count", 0) or 0),
                    fetched_count=int(attempt_payload.get("fetched_count", 0) or 0),
                    accepted_count=int(attempt_payload.get("accepted_count", 0) or 0),
                    retry_events=int(attempt_payload.get("retry_events", 0) or 0),
                    error=str(attempt_payload.get("error", "")),
                    circuit_state=circuit_state,
                )
            )

            if bool(attempt_payload.get("hard_error", False)):
                self._circuit_breakers.record_failure(
                    provider.key,
                    enabled=normalized_settings.provider_circuit_breaker_enabled,
                    error_threshold=normalized_settings.provider_error_threshold,
                )
                if index == 0 and len(provider_candidates) > 1:
                    failover_used = True
                    failover_reason = failover_reason or "primary_error"
                continue

            self._circuit_breakers.record_success(
                provider.key,
                enabled=normalized_settings.provider_circuit_breaker_enabled,
            )

            selected_provider = provider.key
            selected_payload = attempt_payload
            accepted_count = int(attempt_payload.get("accepted_count", 0) or 0)
            if accepted_count > 0:
                if index > 0:
                    failover_used = True
                    failover_reason = failover_reason or "primary_failed_or_empty"
                break

            if index == 0 and len(provider_candidates) > 1:
                failover_used = True
                status = str(attempt_payload.get("status", "")).strip().lower()
                if status == "search_empty":
                    failover_reason = failover_reason or "primary_search_empty"
                elif status == "accepted_empty":
                    failover_reason = failover_reason or "primary_accepted_empty"
                else:
                    failover_reason = failover_reason or "primary_no_accepted_sources"
                continue
            break

        if selected_payload is None:
            selected_payload = self._empty_attempt_payload()
            warnings.append("All configured providers failed or returned no usable sources for this query.")

        diagnostics: dict[str, Any] = {
            "enabled": True,
            "cache_hit": False,
            "provider_requested": requested_provider,
            "provider_used": selected_provider,
            "query_variants": list(query_variants),
            "search_count": int(selected_payload.get("search_count", 0) or 0),
            "candidate_url_count": int(selected_payload.get("candidate_url_count", 0) or 0),
            "attempted_count": int(selected_payload.get("attempted_count", 0) or 0),
            "fetched_count": int(selected_payload.get("fetched_count", 0) or 0),
            "accepted_count": int(selected_payload.get("accepted_count", 0) or 0),
            "quality_threshold": normalized_settings.min_quality_score,
            "quality_stats": dict(selected_payload.get("quality_stats", {})),
            "fallback_quality_mode_used": bool(selected_payload.get("fallback_quality_mode_used", False)),
            "warning_count": len(warnings),
        }
        if normalized_settings.reliability_diagnostics_enabled:
            diagnostics.update(
                {
                    "provider_attempts": [asdict(item) for item in provider_attempts],
                    "failover_used": bool(failover_used),
                    "failover_reason": failover_reason,
                    "retry_events": int(total_retry_events),
                    "rate_limited_urls": int(total_rate_limited),
                    "content_cache_hit_count": int(selected_payload.get("content_cache_hit_count", 0) or 0),
                    "content_cache_miss_count": int(selected_payload.get("content_cache_miss_count", 0) or 0),
                    "provider_circuit_state": self._circuit_breakers.state_snapshot(),
                    "provider_failures": self._circuit_breakers.failure_snapshot(),
                }
            )

        result = WebSourcingRunResult(
            query=query,
            provider=selected_provider,
            search_results=list(selected_payload.get("search_results", [])),
            fetched_pages=list(selected_payload.get("fetched_pages", [])),
            warnings=warnings,
            diagnostics=diagnostics,
        )
        self._cache_store.set(cache_key, self._serialize_run_result(result))
        return result

    def _run_provider_pipeline(
        self,
        *,
        provider: WebSearchProvider,
        query: str,
        query_variants: list[str],
        settings: WebSourcingSettings,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        raw_search_results: list[WebSearchResult] = []
        search_retry_events = [0]
        search_error_count = 0
        retry_policy = self._build_retry_policy(settings)

        for variant in query_variants:
            def _search_call(*, variant_query: str = variant) -> list[WebSearchResult]:
                return provider.search(
                    variant_query,
                    max_results=max(1, settings.max_search_results),
                    recency_days=settings.allow_recency_days,
                    timeout_ms=settings.timeout_ms,
                )

            try:
                if retry_policy is None:
                    variant_results = _search_call()
                else:
                    variant_results = retry_policy.run(
                        _search_call,
                        on_retry=lambda _attempt, _error: search_retry_events.__setitem__(
                            0,
                            search_retry_events[0] + 1,
                        ),
                    )
            except Exception as exc:
                search_error_count += 1
                warnings.append(f"Web search failed for `{variant}` via `{provider.key}`: {exc}")
                continue

            for result in variant_results:
                raw_search_results.append(
                    WebSearchResult(
                        title=result.title,
                        url=result.url,
                        snippet=result.snippet,
                        rank=max(1, int(result.rank)),
                    )
                )

        if search_error_count == len(query_variants) and not raw_search_results:
            return {
                "status": "search_error",
                "search_results": [],
                "fetched_pages": [],
                "warnings": warnings,
                "search_count": 0,
                "candidate_url_count": 0,
                "attempted_count": 0,
                "fetched_count": 0,
                "accepted_count": 0,
                "quality_stats": {"avg": 0.0, "min": 0.0, "max": 0.0, "above_threshold_count": 0},
                "fallback_quality_mode_used": False,
                "retry_events": int(search_retry_events[0]),
                "rate_limited_count": 0,
                "hard_error": True,
                "error": "search_error",
            }

        ranked_candidates, ranked_search_results = self._rank_search_results(
            query=query,
            search_results=raw_search_results,
            settings=settings,
        )
        if not ranked_candidates:
            return {
                "status": "search_empty",
                "search_results": ranked_search_results,
                "fetched_pages": [],
                "warnings": warnings,
                "search_count": len(ranked_search_results),
                "candidate_url_count": 0,
                "attempted_count": 0,
                "fetched_count": 0,
                "accepted_count": 0,
                "quality_stats": {"avg": 0.0, "min": 0.0, "max": 0.0, "above_threshold_count": 0},
                "fallback_quality_mode_used": False,
                "retry_events": int(search_retry_events[0]),
                "rate_limited_count": 0,
                "hard_error": False,
                "error": "",
            }

        fetch_budget = clamp_int(
            settings.max_fetch_pages * settings.candidate_pool_multiplier,
            minimum=1,
            maximum=60,
        )
        fetch_char_budget = max(
            settings.max_total_chars,
            settings.max_total_chars * settings.candidate_pool_multiplier,
        )
        fetch_char_budget = clamp_int(fetch_char_budget, minimum=2000, maximum=200_000)

        policy = lambda url: self._policy(
            url=url,
            include_domains=settings.include_domains,
            exclude_domains=settings.exclude_domains,
        )
        candidate_urls = [item.url for item in ranked_candidates]
        fetched_pages, fetch_warnings, fetch_stats = self._crawler.fetch_many(
            candidate_urls,
            max_pages=fetch_budget,
            timeout_ms=settings.timeout_ms,
            max_chars_per_page=settings.max_chars_per_page,
            max_total_chars=fetch_char_budget,
            policy=policy,
            rate_limiter=self._domain_rate_limiter,
            rate_limit_per_minute=settings.domain_rate_limit_per_minute,
            retry_policy=retry_policy,
            on_retry_event=None,
            content_cache_ttl_seconds=settings.cache_ttl_seconds,
            content_cache_force_refresh=settings.force_refresh,
        )
        warnings.extend(fetch_warnings)

        snippet_by_canonical_url = {
            canonicalize_url(candidate.url): candidate.snippet
            for candidate in ranked_candidates
            if candidate.url
        }
        scored_pages = self._score_pages(
            query=query,
            pages=fetched_pages,
            snippet_by_canonical_url=snippet_by_canonical_url,
            settings=settings,
        )
        quality_stats = self._quality_stats(scored_pages, threshold=settings.min_quality_score)
        selected_pages, fallback_used, selection_warnings = self._select_pages(pages=scored_pages, settings=settings)
        warnings.extend(selection_warnings)

        status = "success" if selected_pages else "accepted_empty"
        return {
            "status": status,
            "search_results": ranked_search_results,
            "fetched_pages": selected_pages,
            "warnings": warnings,
            "search_count": len(ranked_search_results),
            "candidate_url_count": len(candidate_urls),
            "attempted_count": int(fetch_stats.get("attempted_count", 0) or 0),
            "fetched_count": int(fetch_stats.get("fetched_count", 0) or 0),
            "accepted_count": len(selected_pages),
            "quality_stats": quality_stats,
            "fallback_quality_mode_used": bool(fallback_used),
            "retry_events": int(search_retry_events[0]) + int(fetch_stats.get("retry_events", 0) or 0),
            "rate_limited_count": int(fetch_stats.get("rate_limited_count", 0) or 0),
            "content_cache_hit_count": int(fetch_stats.get("content_cache_hit_count", 0) or 0),
            "content_cache_miss_count": int(fetch_stats.get("content_cache_miss_count", 0) or 0),
            "hard_error": False,
            "error": "",
        }

    @staticmethod
    def _provider_candidates(settings: WebSourcingSettings) -> list[str]:
        primary = WebSourcingOrchestrator._normalize_provider_key(settings.provider_key)
        candidates = [primary]
        if settings.allow_provider_failover:
            secondary = WebSourcingOrchestrator._normalize_provider_key(settings.secondary_provider_key)
            if secondary and secondary not in candidates:
                candidates.append(secondary)
        return [item for item in candidates if item]

    @staticmethod
    def _normalize_provider_key(value: str) -> str:
        normalized = " ".join(str(value or "").split()).strip().lower() or "duckduckgo"
        if normalized in {"surper", "super"}:
            return "serper"
        return normalized

    @staticmethod
    def _normalize_settings(settings: WebSourcingSettings) -> WebSourcingSettings:
        trusted_domains = [
            normalize_domain(item)
            for item in (settings.trusted_domains or [])
            if normalize_domain(item)
        ]
        return WebSourcingSettings(
            enabled=bool(settings.enabled),
            provider_key=WebSourcingOrchestrator._normalize_provider_key(settings.provider_key),
            cache_ttl_seconds=clamp_int(settings.cache_ttl_seconds, minimum=300, maximum=86_400),
            max_search_results=clamp_int(settings.max_search_results, minimum=1, maximum=20),
            max_fetch_pages=clamp_int(settings.max_fetch_pages, minimum=1, maximum=15),
            max_chars_per_page=clamp_int(settings.max_chars_per_page, minimum=600, maximum=20_000),
            max_total_chars=clamp_int(settings.max_total_chars, minimum=2000, maximum=80_000),
            timeout_ms=clamp_int(settings.timeout_ms, minimum=1000, maximum=30_000),
            force_refresh=bool(settings.force_refresh),
            include_domains=list(settings.include_domains or []),
            exclude_domains=list(settings.exclude_domains or []),
            allow_recency_days=settings.allow_recency_days if settings.allow_recency_days is None else int(settings.allow_recency_days),
            strict_mode=bool(settings.strict_mode),
            query_variant_count=clamp_int(settings.query_variant_count, minimum=1, maximum=6),
            candidate_pool_multiplier=clamp_int(settings.candidate_pool_multiplier, minimum=1, maximum=6),
            min_quality_score=WebSourcingOrchestrator._clamp_float(settings.min_quality_score, minimum=0.0, maximum=1.0),
            max_results_per_domain=clamp_int(settings.max_results_per_domain, minimum=1, maximum=5),
            trusted_boost_enabled=bool(settings.trusted_boost_enabled),
            trusted_domains=trusted_domains,
            allow_provider_failover=bool(settings.allow_provider_failover),
            secondary_provider_key=WebSourcingOrchestrator._normalize_provider_key(settings.secondary_provider_key),
            retry_count=clamp_int(settings.retry_count, minimum=0, maximum=5),
            retry_base_delay_ms=clamp_int(settings.retry_base_delay_ms, minimum=50, maximum=3000),
            retry_max_delay_ms=clamp_int(settings.retry_max_delay_ms, minimum=100, maximum=5000),
            domain_rate_limit_per_minute=clamp_int(settings.domain_rate_limit_per_minute, minimum=0, maximum=60),
            provider_circuit_breaker_enabled=bool(settings.provider_circuit_breaker_enabled),
            provider_error_threshold=clamp_int(settings.provider_error_threshold, minimum=1, maximum=20),
            provider_cooldown_seconds=clamp_int(settings.provider_cooldown_seconds, minimum=10, maximum=3600),
            provider_probe_requests=clamp_int(settings.provider_probe_requests, minimum=1, maximum=5),
            reliability_diagnostics_enabled=bool(settings.reliability_diagnostics_enabled),
        )

    def _resolve_provider(self, key: str) -> WebSearchProvider:
        normalized = self._normalize_provider_key(key)
        provider = self._providers.get(normalized)
        if provider is not None:
            return provider
        if normalized == "duckduckgo":
            provider = DuckDuckGoSearchProvider()
            self._providers["duckduckgo"] = provider
            return provider
        if normalized == "serper":
            serper = SerperSearchProvider()
            if serper.available:
                self._providers["serper"] = serper
                return serper
            raise RuntimeError("Serper provider selected but SERPER_API_KEY is missing.")
        raise RuntimeError(f"Unknown web provider selected: {normalized}")

    @staticmethod
    def _policy(
        *,
        url: str,
        include_domains: list[str] | None,
        exclude_domains: list[str] | None,
    ) -> DomainPolicyDecision:
        return evaluate_domain_policy(
            url,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )

    @staticmethod
    def _cache_key(*, query: str, settings: WebSourcingSettings, provider: str) -> str:
        key_payload = {
            "version": 3,
            "provider": provider,
            "query": query,
            "max_search_results": settings.max_search_results,
            "max_fetch_pages": settings.max_fetch_pages,
            "max_chars_per_page": settings.max_chars_per_page,
            "max_total_chars": settings.max_total_chars,
            "include_domains": list(settings.include_domains or []),
            "exclude_domains": list(settings.exclude_domains or []),
            "allow_recency_days": settings.allow_recency_days,
            "query_variant_count": settings.query_variant_count,
            "candidate_pool_multiplier": settings.candidate_pool_multiplier,
            "min_quality_score": settings.min_quality_score,
            "max_results_per_domain": settings.max_results_per_domain,
            "trusted_boost_enabled": settings.trusted_boost_enabled,
            "trusted_domains": list(settings.trusted_domains or []),
            "allow_provider_failover": settings.allow_provider_failover,
            "secondary_provider_key": settings.secondary_provider_key,
            "retry_count": settings.retry_count,
            "retry_base_delay_ms": settings.retry_base_delay_ms,
            "retry_max_delay_ms": settings.retry_max_delay_ms,
            "domain_rate_limit_per_minute": settings.domain_rate_limit_per_minute,
            "provider_circuit_breaker_enabled": settings.provider_circuit_breaker_enabled,
            "provider_error_threshold": settings.provider_error_threshold,
            "provider_cooldown_seconds": settings.provider_cooldown_seconds,
            "provider_probe_requests": settings.provider_probe_requests,
        }
        raw = json.dumps(key_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _serialize_run_result(result: WebSourcingRunResult) -> dict[str, Any]:
        return {
            "query": result.query,
            "provider": result.provider,
            "search_results": [
                {"title": item.title, "url": item.url, "snippet": item.snippet, "rank": item.rank}
                for item in result.search_results
            ],
            "fetched_pages": [
                {
                    "url": item.url,
                    "final_url": item.final_url,
                    "title": item.title,
                    "text": item.text,
                    "content_type": item.content_type,
                    "status_code": item.status_code,
                    "char_count": item.char_count,
                    "truncated": item.truncated,
                    "retrieved_at": item.retrieved_at,
                    "quality_score": item.quality_score,
                    "quality_reasons": list(item.quality_reasons),
                    "domain": item.domain,
                }
                for item in result.fetched_pages
            ],
            "warnings": list(result.warnings),
            "diagnostics": dict(result.diagnostics),
            "cache_hit": bool(result.cache_hit),
        }

    @staticmethod
    def _deserialize_run_result(raw: dict[str, Any]) -> WebSourcingRunResult:
        search_results_raw = raw.get("search_results", [])
        fetched_pages_raw = raw.get("fetched_pages", [])
        search_results = [
            WebSearchResult(
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                snippet=str(item.get("snippet", "")),
                rank=int(item.get("rank", 0) or 0),
            )
            for item in (search_results_raw if isinstance(search_results_raw, list) else [])
            if isinstance(item, dict)
        ]
        fetched_pages = [
            FetchedPage(
                url=str(item.get("url", "")),
                final_url=str(item.get("final_url", "")),
                title=str(item.get("title", "")),
                text=str(item.get("text", "")),
                content_type=str(item.get("content_type", "")),
                status_code=int(item.get("status_code", 0) or 0),
                char_count=int(item.get("char_count", 0) or 0),
                truncated=bool(item.get("truncated", False)),
                retrieved_at=str(item.get("retrieved_at", "")),
                quality_score=float(item.get("quality_score", 0.0) or 0.0),
                quality_reasons=[str(reason) for reason in item.get("quality_reasons", []) if str(reason).strip()],
                domain=str(item.get("domain", "")),
            )
            for item in (fetched_pages_raw if isinstance(fetched_pages_raw, list) else [])
            if isinstance(item, dict)
        ]
        return WebSourcingRunResult(
            query=str(raw.get("query", "")),
            provider=str(raw.get("provider", "duckduckgo")),
            search_results=search_results,
            fetched_pages=fetched_pages,
            warnings=[str(item) for item in raw.get("warnings", []) if str(item).strip()],
            diagnostics=dict(raw.get("diagnostics", {})) if isinstance(raw.get("diagnostics"), dict) else {},
            cache_hit=bool(raw.get("cache_hit", False)),
        )

    @staticmethod
    def _build_default_providers() -> dict[str, WebSearchProvider]:
        providers: dict[str, WebSearchProvider] = {"duckduckgo": DuckDuckGoSearchProvider()}
        serper = SerperSearchProvider()
        if serper.available:
            providers["serper"] = serper
        return providers

    @staticmethod
    def _build_retry_policy(settings: WebSourcingSettings) -> RetryPolicy | None:
        if int(settings.retry_count) <= 0:
            return None
        return RetryPolicy(
            retry_count=int(settings.retry_count),
            base_delay_ms=int(settings.retry_base_delay_ms),
            max_delay_ms=int(settings.retry_max_delay_ms),
        )

    def _rank_search_results(
        self,
        *,
        query: str,
        search_results: list[WebSearchResult],
        settings: WebSourcingSettings,
    ) -> tuple[list[WebSearchResult], list[WebSearchResult]]:
        ranked_candidates: list[tuple[float, str, WebSearchResult]] = []
        best_by_canonical: dict[str, tuple[float, WebSearchResult]] = {}
        for result in search_results:
            canonical_url = canonicalize_url(result.url)
            if not canonical_url:
                continue
            score = score_search_candidate(
                query=query,
                title=result.title,
                snippet=result.snippet,
                rank=result.rank,
                url=result.url,
                trusted_domains=list(settings.trusted_domains or []),
                trusted_boost_enabled=settings.trusted_boost_enabled,
            )
            current_best = best_by_canonical.get(canonical_url)
            candidate_item = WebSearchResult(
                title=result.title,
                url=result.url,
                snippet=result.snippet,
                rank=max(1, int(result.rank)),
            )
            if current_best is None or score > current_best[0]:
                best_by_canonical[canonical_url] = (score, candidate_item)

        for canonical_url, (score, result) in best_by_canonical.items():
            ranked_candidates.append((score, canonical_url, result))

        ranked_candidates.sort(key=lambda item: (-item[0], item[1]))
        pool_limit = clamp_int(
            settings.max_fetch_pages * settings.candidate_pool_multiplier,
            minimum=1,
            maximum=max(1, len(ranked_candidates)),
        )
        selected_candidates = [item[2] for item in ranked_candidates[:pool_limit]]

        ranked_search_results: list[WebSearchResult] = []
        for index, (_, _, result) in enumerate(ranked_candidates[: settings.max_search_results], start=1):
            ranked_search_results.append(
                WebSearchResult(
                    title=result.title,
                    url=result.url,
                    snippet=result.snippet,
                    rank=index,
                )
            )
        return selected_candidates, ranked_search_results

    @staticmethod
    def _score_pages(
        *,
        query: str,
        pages: list[FetchedPage],
        snippet_by_canonical_url: dict[str, str],
        settings: WebSourcingSettings,
    ) -> list[FetchedPage]:
        output: list[FetchedPage] = []
        for page in pages:
            canonical_url = canonicalize_url(page.final_url or page.url)
            snippet = snippet_by_canonical_url.get(canonical_url, "")
            quality = score_fetched_page(
                query=query,
                title=page.title,
                text=page.text,
                snippet=snippet,
                url=page.final_url or page.url,
                allow_recency_days=settings.allow_recency_days,
                trusted_domains=list(settings.trusted_domains or []),
                trusted_boost_enabled=settings.trusted_boost_enabled,
            )
            output.append(
                FetchedPage(
                    url=page.url,
                    final_url=page.final_url,
                    title=page.title,
                    text=page.text,
                    content_type=page.content_type,
                    status_code=page.status_code,
                    char_count=page.char_count,
                    truncated=page.truncated,
                    retrieved_at=page.retrieved_at,
                    quality_score=quality.quality_score,
                    quality_reasons=quality.reasons,
                    domain=extract_domain(page.final_url or page.url),
                )
            )
        output.sort(
            key=lambda item: (
                -float(item.quality_score),
                canonicalize_url(item.final_url or item.url),
            )
        )
        return output

    @staticmethod
    def _select_pages(
        *,
        pages: list[FetchedPage],
        settings: WebSourcingSettings,
    ) -> tuple[list[FetchedPage], bool, list[str]]:
        warnings: list[str] = []
        threshold = float(settings.min_quality_score)
        filtered = [page for page in pages if float(page.quality_score) >= threshold]
        fallback_used = False
        if not filtered and pages:
            fallback_used = True
            fallback_limit = min(max(1, int(settings.max_fetch_pages)), 2)
            filtered = pages[:fallback_limit]
            warnings.append(
                (
                    "No fetched pages met the quality threshold "
                    f"({threshold:.2f}). Returning best available pages with warning."
                )
            )

        selected: list[FetchedPage] = []
        domain_counts: dict[str, int] = {}
        remaining_chars = max(1, int(settings.max_total_chars))
        char_budget_warned = False
        for page in filtered:
            if len(selected) >= settings.max_fetch_pages:
                break
            domain = normalize_domain(page.domain or extract_domain(page.final_url or page.url))
            if domain:
                seen_count = domain_counts.get(domain, 0)
                if seen_count >= settings.max_results_per_domain:
                    continue

            if remaining_chars <= 0:
                if not char_budget_warned:
                    warnings.append("Web char budget reached after quality filtering; extra pages were skipped.")
                    char_budget_warned = True
                break

            text = page.text
            truncated = page.truncated
            if len(text) > remaining_chars:
                text = text[:remaining_chars].rstrip()
                truncated = True
            if not text:
                continue

            selected.append(
                FetchedPage(
                    url=page.url,
                    final_url=page.final_url,
                    title=page.title,
                    text=text,
                    content_type=page.content_type,
                    status_code=page.status_code,
                    char_count=len(text),
                    truncated=truncated,
                    retrieved_at=page.retrieved_at,
                    quality_score=page.quality_score,
                    quality_reasons=list(page.quality_reasons),
                    domain=domain,
                )
            )
            if domain:
                domain_counts[domain] = domain_counts.get(domain, 0) + 1
            remaining_chars -= len(text)
        return selected, fallback_used, warnings

    @staticmethod
    def _quality_stats(pages: list[FetchedPage], *, threshold: float) -> dict[str, float | int]:
        if not pages:
            return {"avg": 0.0, "min": 0.0, "max": 0.0, "above_threshold_count": 0}
        scores = [float(page.quality_score) for page in pages]
        above_threshold_count = sum(1 for score in scores if score >= threshold)
        return {
            "avg": round(sum(scores) / len(scores), 4),
            "min": round(min(scores), 4),
            "max": round(max(scores), 4),
            "above_threshold_count": int(above_threshold_count),
        }

    @staticmethod
    def _clamp_float(value: float, *, minimum: float, maximum: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = minimum
        return max(minimum, min(maximum, numeric))

    @staticmethod
    def _empty_attempt_payload() -> dict[str, Any]:
        return {
            "status": "empty",
            "search_results": [],
            "fetched_pages": [],
            "warnings": [],
            "search_count": 0,
            "candidate_url_count": 0,
            "attempted_count": 0,
            "fetched_count": 0,
            "accepted_count": 0,
            "quality_stats": {"avg": 0.0, "min": 0.0, "max": 0.0, "above_threshold_count": 0},
            "fallback_quality_mode_used": False,
            "retry_events": 0,
            "rate_limited_count": 0,
            "hard_error": False,
            "error": "",
        }
