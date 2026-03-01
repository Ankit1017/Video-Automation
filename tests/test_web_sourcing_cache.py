from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from main_app.platform.web_sourcing.cache_store import WebSourceCacheStore


class TestWebSourceCacheStore(unittest.TestCase):
    def test_cache_set_and_get(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            store = WebSourceCacheStore(str(cache_path))
            store.set("key_1", {"value": 7})

            cached = store.get("key_1", ttl_seconds=3600)
            self.assertIsNotNone(cached)
            self.assertEqual(cached, {"value": 7})

    def test_cache_ttl_expiry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            store = WebSourceCacheStore(str(cache_path))
            store.set("expired_key", {"value": "old"})

            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            raw["expired_key"]["stored_at"] = (
                datetime.now(timezone.utc) - timedelta(hours=7)
            ).isoformat()
            cache_path.write_text(json.dumps(raw), encoding="utf-8")

            cached = store.get("expired_key", ttl_seconds=3600)
            self.assertIsNone(cached)

    def test_cache_handles_corrupted_json_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            cache_path.write_text("{invalid json", encoding="utf-8")

            store = WebSourceCacheStore(str(cache_path))

            cached = store.get("missing", ttl_seconds=3600)
            self.assertIsNone(cached)

            store.set("fresh", {"value": "ok"})
            refreshed = store.get("fresh", ttl_seconds=3600)
            self.assertEqual(refreshed, {"value": "ok"})


if __name__ == "__main__":
    unittest.main()
