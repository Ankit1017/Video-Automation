from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from main_app.models import WebSourcingSettings
from main_app.platform.web_sourcing.cache_store import WebSourceCacheStore
from main_app.platform.web_sourcing.contracts import FetchedPage, WebSearchResult
from main_app.platform.web_sourcing.orchestrator import WebSourcingOrchestrator


class _FakeProvider:
    key = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str, *, max_results: int, recency_days: int | None, timeout_ms: int) -> list[WebSearchResult]:
        del recency_days, timeout_ms
        self.calls += 1
        return [
            WebSearchResult(
                title=f"Result for {query}",
                url="https://example.com/reference",
                snippet="example snippet",
                rank=1,
            )
        ][:max_results]


class _ZeroResultProvider:
    key = "primary"

    def search(self, query: str, *, max_results: int, recency_days: int | None, timeout_ms: int) -> list[WebSearchResult]:
        del query, max_results, recency_days, timeout_ms
        return []


class _FailingProvider:
    key = "primary"

    def search(self, query: str, *, max_results: int, recency_days: int | None, timeout_ms: int) -> list[WebSearchResult]:
        del query, max_results, recency_days, timeout_ms
        raise OSError("temporary provider outage")


class _SecondaryProvider:
    key = "secondary"

    def search(self, query: str, *, max_results: int, recency_days: int | None, timeout_ms: int) -> list[WebSearchResult]:
        del recency_days, timeout_ms
        return [
            WebSearchResult(
                title=f"Secondary result for {query}",
                url="https://secondary.example.com/reference",
                snippet="secondary snippet",
                rank=1,
            )
        ][:max_results]


class _FakeCrawler:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_many(self, urls, **kwargs):  # noqa: ANN001
        del kwargs
        self.calls += 1
        if not urls:
            return [], ["no_urls"], {"attempted_count": 0, "fetched_count": 0, "accepted_count": 0}
        return (
            [
                FetchedPage(
                    url=urls[0],
                    final_url=urls[0],
                    title="Example",
                    text="A long enough page body with practical information. " * 12,
                    content_type="text/html",
                    status_code=200,
                    char_count=600,
                    truncated=False,
                    retrieved_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                )
            ],
            [],
            {"attempted_count": 1, "fetched_count": 1, "accepted_count": 1},
        )


class _UnavailableSerperProvider:
    key = "serper"

    def search(self, query: str, *, max_results: int, recency_days: int | None, timeout_ms: int) -> list[WebSearchResult]:
        del query, max_results, recency_days, timeout_ms
        raise RuntimeError("Serper provider selected but SERPER_API_KEY is missing.")


class TestWebSourcingOrchestrator(unittest.TestCase):
    def test_orchestrator_uses_cache_with_same_query(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = WebSourceCacheStore(str(Path(temp_dir) / "web_cache.json"))
            provider = _FakeProvider()
            crawler = _FakeCrawler()
            orchestrator = WebSourcingOrchestrator(
                cache_store=cache,
                crawler=crawler,
                providers={"duckduckgo": provider, "fake": provider},
            )
            settings = WebSourcingSettings(
                enabled=True,
                provider_key="fake",
                cache_ttl_seconds=21600,
                max_search_results=8,
                max_fetch_pages=4,
                max_chars_per_page=4000,
                max_total_chars=20000,
                timeout_ms=5000,
                force_refresh=False,
                include_domains=[],
                exclude_domains=[],
                allow_recency_days=None,
                strict_mode=False,
                query_variant_count=1,
            )

            first = orchestrator.run(topic="Agentic AI", constraints="production", settings=settings)
            second = orchestrator.run(topic="Agentic AI", constraints="production", settings=settings)

            self.assertFalse(first.cache_hit)
            self.assertTrue(second.cache_hit)
            self.assertEqual(provider.calls, 1)
            self.assertEqual(crawler.calls, 1)
            self.assertEqual(len(first.fetched_pages), 1)
            self.assertGreaterEqual(float(first.fetched_pages[0].quality_score), 0.0)
            self.assertTrue(first.diagnostics.get("query_variants"))
            self.assertGreaterEqual(int(first.diagnostics.get("candidate_url_count", 0) or 0), 1)
            self.assertEqual(second.diagnostics.get("cache_hit"), True)

    def test_serper_selection_does_not_silently_fallback_to_duckduckgo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = WebSourceCacheStore(str(Path(temp_dir) / "web_cache.json"))
            provider = _FakeProvider()
            crawler = _FakeCrawler()
            orchestrator = WebSourcingOrchestrator(
                cache_store=cache,
                crawler=crawler,
                providers={"duckduckgo": provider, "serper": _UnavailableSerperProvider()},
            )
            settings = WebSourcingSettings(
                enabled=True,
                provider_key="serper",
                cache_ttl_seconds=21600,
                max_search_results=8,
                max_fetch_pages=4,
                max_chars_per_page=4000,
                max_total_chars=20000,
                timeout_ms=5000,
                force_refresh=True,
                include_domains=[],
                exclude_domains=[],
                allow_recency_days=None,
                strict_mode=False,
                query_variant_count=1,
            )

            result = orchestrator.run(topic="Agentic AI", constraints="production", settings=settings)

            self.assertEqual(result.provider, "serper")
            self.assertEqual(len(result.search_results), 0)
            self.assertEqual(len(result.fetched_pages), 0)
            self.assertTrue(any("SERPER_API_KEY" in warning for warning in result.warnings))
            self.assertEqual(int(result.diagnostics.get("search_count", 0) or 0), 0)
            self.assertEqual(int(result.diagnostics.get("accepted_count", 0) or 0), 0)
            self.assertEqual(crawler.calls, 0)

    def test_failover_runs_when_primary_returns_zero_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = WebSourceCacheStore(str(Path(temp_dir) / "web_cache.json"))
            crawler = _FakeCrawler()
            orchestrator = WebSourcingOrchestrator(
                cache_store=cache,
                crawler=crawler,
                providers={
                    "primary": _ZeroResultProvider(),
                    "secondary": _SecondaryProvider(),
                },
            )
            settings = WebSourcingSettings(
                enabled=True,
                provider_key="primary",
                secondary_provider_key="secondary",
                allow_provider_failover=True,
                force_refresh=True,
                query_variant_count=1,
            )

            result = orchestrator.run(topic="Agentic AI", constraints="production", settings=settings)

            self.assertEqual(result.provider, "secondary")
            self.assertGreater(len(result.fetched_pages), 0)
            self.assertTrue(bool(result.diagnostics.get("failover_used", False)))
            self.assertEqual(str(result.diagnostics.get("failover_reason", "")), "primary_search_empty")
            attempts = result.diagnostics.get("provider_attempts", [])
            self.assertEqual(len(attempts), 2)

    def test_failover_runs_when_primary_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = WebSourceCacheStore(str(Path(temp_dir) / "web_cache.json"))
            crawler = _FakeCrawler()
            orchestrator = WebSourcingOrchestrator(
                cache_store=cache,
                crawler=crawler,
                providers={
                    "primary": _FailingProvider(),
                    "secondary": _SecondaryProvider(),
                },
            )
            settings = WebSourcingSettings(
                enabled=True,
                provider_key="primary",
                secondary_provider_key="secondary",
                allow_provider_failover=True,
                force_refresh=True,
                query_variant_count=1,
            )

            result = orchestrator.run(topic="Agentic AI", constraints="production", settings=settings)

            self.assertEqual(result.provider, "secondary")
            self.assertGreater(len(result.fetched_pages), 0)
            self.assertTrue(bool(result.diagnostics.get("failover_used", False)))
            self.assertEqual(str(result.diagnostics.get("failover_reason", "")), "primary_error")
            self.assertTrue(any("failed" in warning.lower() for warning in result.warnings))

    def test_cache_key_invalidates_when_reliability_settings_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = WebSourceCacheStore(str(Path(temp_dir) / "web_cache.json"))
            provider = _FakeProvider()
            crawler = _FakeCrawler()
            orchestrator = WebSourcingOrchestrator(
                cache_store=cache,
                crawler=crawler,
                providers={"fake": provider},
            )
            base_settings = WebSourcingSettings(
                enabled=True,
                provider_key="fake",
                query_variant_count=1,
                force_refresh=False,
                retry_count=1,
            )
            changed_settings = WebSourcingSettings(
                enabled=True,
                provider_key="fake",
                query_variant_count=1,
                force_refresh=False,
                retry_count=2,
            )

            first = orchestrator.run(topic="Agentic AI", constraints="production", settings=base_settings)
            second = orchestrator.run(topic="Agentic AI", constraints="production", settings=changed_settings)

            self.assertFalse(first.cache_hit)
            self.assertFalse(second.cache_hit)
            self.assertEqual(provider.calls, 2)


if __name__ == "__main__":
    unittest.main()
