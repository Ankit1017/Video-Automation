from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from main_app.platform.web_sourcing.content_cache_store import WebContentCacheStore
from main_app.platform.web_sourcing.contracts import DomainPolicyDecision, FetchedPage
from main_app.platform.web_sourcing.crawler import FocusedCrawler


class _CacheAwareCrawler(FocusedCrawler):
    def __init__(self, *, content_cache_store: WebContentCacheStore) -> None:
        super().__init__(content_cache_store=content_cache_store)
        self.fetch_calls = 0

    def _fetch_single(self, **kwargs):  # type: ignore[override]
        url = str(kwargs.get("url", ""))
        self.fetch_calls += 1
        return FetchedPage(
            url=url,
            final_url=url,
            title="Cached Title",
            text="This is cacheable content body. " * 30,
            content_type="text/html",
            status_code=200,
            char_count=900,
            truncated=False,
            retrieved_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )

    def _robots_allows(self, url: str, *, timeout_ms: int):  # type: ignore[override]
        del url, timeout_ms
        return True, ""


class TestCrawlerContentCacheFlow(unittest.TestCase):
    def test_second_fetch_hits_content_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_store = WebContentCacheStore(str(Path(temp_dir) / "content_cache.json"))
            crawler = _CacheAwareCrawler(content_cache_store=cache_store)

            def _policy(url: str) -> DomainPolicyDecision:
                return DomainPolicyDecision(url=url, domain="example.com", allowed=True)

            urls = ["https://example.com/page-1"]
            first_pages, _, first_stats = crawler.fetch_many(
                urls,
                max_pages=3,
                timeout_ms=3000,
                max_chars_per_page=2000,
                max_total_chars=10000,
                policy=_policy,
                content_cache_ttl_seconds=3600,
                content_cache_force_refresh=False,
            )
            second_pages, _, second_stats = crawler.fetch_many(
                urls,
                max_pages=3,
                timeout_ms=3000,
                max_chars_per_page=2000,
                max_total_chars=10000,
                policy=_policy,
                content_cache_ttl_seconds=3600,
                content_cache_force_refresh=False,
            )

            self.assertEqual(len(first_pages), 1)
            self.assertEqual(len(second_pages), 1)
            self.assertEqual(crawler.fetch_calls, 1)
            self.assertEqual(int(first_stats.get("content_cache_hit_count", 0) or 0), 0)
            self.assertEqual(int(first_stats.get("content_cache_miss_count", 0) or 0), 1)
            self.assertEqual(int(second_stats.get("content_cache_hit_count", 0) or 0), 1)


if __name__ == "__main__":
    unittest.main()
