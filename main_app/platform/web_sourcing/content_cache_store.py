from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any


class WebContentCacheStore:
    def __init__(self, path: str = ".cache/web_content_cache.json") -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def get(self, key: str, *, ttl_seconds: int) -> dict[str, Any] | None:
        cache_data = self._load_all()
        payload = cache_data.get(key)
        if not isinstance(payload, dict):
            return None

        stored_at_raw = str(payload.get("stored_at", "")).strip()
        if not stored_at_raw:
            return None
        try:
            stored_at = datetime.fromisoformat(stored_at_raw)
        except ValueError:
            return None
        if stored_at.tzinfo is None:
            stored_at = stored_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - stored_at > timedelta(seconds=max(1, int(ttl_seconds))):
            return None

        value = payload.get("value")
        if not isinstance(value, dict):
            return None
        return value

    def set(self, key: str, value: dict[str, Any]) -> None:
        cache_data = self._load_all()
        cache_data[key] = {
            "stored_at": datetime.now(timezone.utc).isoformat(),
            "value": dict(value),
        }
        self._write_all(cache_data)

    def _load_all(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            loaded = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _write_all(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
