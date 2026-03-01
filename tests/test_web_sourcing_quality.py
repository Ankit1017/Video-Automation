from __future__ import annotations

import unittest

from main_app.models import WebSourcingSettings
from main_app.platform.web_sourcing.contracts import FetchedPage
from main_app.platform.web_sourcing.orchestrator import WebSourcingOrchestrator
from main_app.platform.web_sourcing.quality import score_fetched_page, score_search_candidate


class TestWebSourcingQuality(unittest.TestCase):
    def test_score_fetched_page_is_deterministic(self) -> None:
        kwargs = {
            "query": "transformers architecture ai",
            "title": "Transformers Architecture Guide",
            "text": "Transformers changed AI systems through attention layers. " * 60,
            "snippet": "A practical guide to transformer architecture and implementation.",
            "url": "https://docs.example.com/ai/transformers/2025/01/15/overview",
            "allow_recency_days": 365,
            "trusted_domains": ["docs.example.com"],
            "trusted_boost_enabled": True,
        }
        first = score_fetched_page(**kwargs)
        second = score_fetched_page(**kwargs)
        self.assertEqual(first.quality_score, second.quality_score)
        self.assertEqual(first.reasons, second.reasons)

    def test_trusted_domain_boost_increases_candidate_score(self) -> None:
        base = score_search_candidate(
            query="agentic ai workflows",
            title="Agentic AI Workflows",
            snippet="Designing robust workflows with tools.",
            rank=1,
            url="https://example.com/agentic",
            trusted_domains=["example.com"],
            trusted_boost_enabled=False,
        )
        boosted = score_search_candidate(
            query="agentic ai workflows",
            title="Agentic AI Workflows",
            snippet="Designing robust workflows with tools.",
            rank=1,
            url="https://example.com/agentic",
            trusted_domains=["example.com"],
            trusted_boost_enabled=True,
        )
        self.assertGreater(boosted, base)

    def test_select_pages_enforces_domain_diversity(self) -> None:
        settings = WebSourcingSettings(
            enabled=True,
            max_fetch_pages=4,
            max_total_chars=8000,
            min_quality_score=0.5,
            max_results_per_domain=1,
        )
        pages = [
            FetchedPage(
                url="https://a.example.com/one",
                final_url="https://a.example.com/one",
                title="A1",
                text="A text " * 200,
                content_type="text/html",
                status_code=200,
                char_count=1200,
                truncated=False,
                retrieved_at="2026-03-01T00:00:00+00:00",
                quality_score=0.92,
                quality_reasons=[],
                domain="a.example.com",
            ),
            FetchedPage(
                url="https://a.example.com/two",
                final_url="https://a.example.com/two",
                title="A2",
                text="A text " * 180,
                content_type="text/html",
                status_code=200,
                char_count=1100,
                truncated=False,
                retrieved_at="2026-03-01T00:00:00+00:00",
                quality_score=0.90,
                quality_reasons=[],
                domain="a.example.com",
            ),
            FetchedPage(
                url="https://b.example.com/one",
                final_url="https://b.example.com/one",
                title="B1",
                text="B text " * 180,
                content_type="text/html",
                status_code=200,
                char_count=1100,
                truncated=False,
                retrieved_at="2026-03-01T00:00:00+00:00",
                quality_score=0.88,
                quality_reasons=[],
                domain="b.example.com",
            ),
        ]

        selected, fallback_used, warnings = WebSourcingOrchestrator._select_pages(  # noqa: SLF001
            pages=pages,
            settings=settings,
        )

        self.assertFalse(fallback_used)
        self.assertEqual(len(selected), 2)
        self.assertEqual(len({page.domain for page in selected}), 2)
        self.assertEqual(warnings, [])

    def test_select_pages_uses_best_warn_fallback(self) -> None:
        settings = WebSourcingSettings(
            enabled=True,
            max_fetch_pages=4,
            max_total_chars=8000,
            min_quality_score=0.95,
            max_results_per_domain=2,
        )
        pages = [
            FetchedPage(
                url="https://example.com/a",
                final_url="https://example.com/a",
                title="A",
                text="fallback text " * 120,
                content_type="text/html",
                status_code=200,
                char_count=1500,
                truncated=False,
                retrieved_at="2026-03-01T00:00:00+00:00",
                quality_score=0.72,
                quality_reasons=[],
                domain="example.com",
            ),
            FetchedPage(
                url="https://docs.example.com/b",
                final_url="https://docs.example.com/b",
                title="B",
                text="fallback text " * 100,
                content_type="text/html",
                status_code=200,
                char_count=1200,
                truncated=False,
                retrieved_at="2026-03-01T00:00:00+00:00",
                quality_score=0.68,
                quality_reasons=[],
                domain="docs.example.com",
            ),
            FetchedPage(
                url="https://third.example.com/c",
                final_url="https://third.example.com/c",
                title="C",
                text="fallback text " * 90,
                content_type="text/html",
                status_code=200,
                char_count=1000,
                truncated=False,
                retrieved_at="2026-03-01T00:00:00+00:00",
                quality_score=0.65,
                quality_reasons=[],
                domain="third.example.com",
            ),
        ]

        selected, fallback_used, warnings = WebSourcingOrchestrator._select_pages(  # noqa: SLF001
            pages=pages,
            settings=settings,
        )

        self.assertTrue(fallback_used)
        self.assertEqual(len(selected), 2)
        self.assertTrue(any("quality threshold" in warning.lower() for warning in warnings))


if __name__ == "__main__":
    unittest.main()
