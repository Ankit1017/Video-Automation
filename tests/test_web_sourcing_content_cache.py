from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from main_app.platform.web_sourcing.content_cache_store import WebContentCacheStore


class TestWebContentCacheStore(unittest.TestCase):
    def test_cache_set_and_get(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "content_cache.json"
            store = WebContentCacheStore(str(cache_path))
            store.set("page_key", {"url": "https://example.com", "text": "sample"})

            cached = store.get("page_key", ttl_seconds=3600)
            self.assertIsNotNone(cached)
            self.assertEqual(cached, {"url": "https://example.com", "text": "sample"})

    def test_cache_ttl_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "content_cache.json"
            store = WebContentCacheStore(str(cache_path))
            store.set("expired_page", {"url": "https://example.com", "text": "old"})

            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            raw["expired_page"]["stored_at"] = (
                datetime.now(timezone.utc) - timedelta(hours=8)
            ).isoformat()
            cache_path.write_text(json.dumps(raw), encoding="utf-8")

            cached = store.get("expired_page", ttl_seconds=3600)
            self.assertIsNone(cached)


if __name__ == "__main__":
    unittest.main()
