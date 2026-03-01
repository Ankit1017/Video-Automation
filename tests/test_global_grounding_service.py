from __future__ import annotations

from datetime import datetime, timezone
import unittest

from main_app.models import WebSourcingSettings
from main_app.platform.web_sourcing.contracts import FetchedPage, WebSourcingRunResult
from main_app.services.global_grounding_service import GlobalGroundingService
from main_app.services.source_grounding_service import SourceGroundingService


class _UploadedFile:
    def __init__(self, name: str, content: bytes) -> None:
        self.name = name
        self._content = content

    def getvalue(self) -> bytes:
        return self._content


class _FakeWebOrchestrator:
    def run(self, *, topic: str, constraints: str, settings: WebSourcingSettings) -> WebSourcingRunResult:
        del topic, constraints, settings
        return WebSourcingRunResult(
            query="agentic ai production",
            provider="duckduckgo",
            search_results=[],
            fetched_pages=[
                FetchedPage(
                    url="https://example.com/agentic",
                    final_url="https://example.com/agentic",
                    title="Agentic Systems",
                    text=("Web factual source body. " * 100).strip(),
                    content_type="text/html",
                    status_code=200,
                    char_count=2300,
                    truncated=False,
                    retrieved_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    quality_score=0.82,
                    quality_reasons=["strong query match"],
                    domain="example.com",
                )
            ],
            warnings=["web warning sample"],
            diagnostics={"cache_hit": False},
            cache_hit=False,
        )


class TestGlobalGroundingService(unittest.TestCase):
    def test_build_sources_merges_upload_and_web_sources(self) -> None:
        source_service = SourceGroundingService(max_sources=8, max_chars_per_source=5000, max_total_chars=20000)
        service = GlobalGroundingService(
            source_grounding_service=source_service,
            web_orchestrator=_FakeWebOrchestrator(),
        )
        upload = _UploadedFile("notes.txt", b"Uploaded source note one.\nUploaded source note two.")
        settings = WebSourcingSettings(enabled=True)

        sources, warnings, diagnostics = service.build_sources(
            [upload],
            topic="Agentic AI",
            constraints="production",
            web_settings=settings,
            max_sources=6,
        )

        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0].source_id, "S1")
        self.assertEqual(sources[1].source_id, "S2")
        self.assertEqual(sources[0].source_type, "upload")
        self.assertEqual(sources[1].source_type, "web")
        self.assertGreater(sources[1].quality_score, 0.8)
        self.assertTrue(any("web warning sample" in item for item in warnings))
        self.assertTrue(diagnostics.get("web_sourcing_enabled"))
        self.assertEqual(diagnostics.get("web_provider"), "duckduckgo")
        page_summaries = diagnostics.get("web_page_summaries", [])
        self.assertEqual(len(page_summaries), 1)
        self.assertGreater(float(page_summaries[0].get("quality_score", 0.0)), 0.8)
        self.assertIn("web_failover_used", diagnostics)
        self.assertIn("web_retry_events", diagnostics)
        self.assertIn("web_content_cache_hit_count", diagnostics)


if __name__ == "__main__":
    unittest.main()
