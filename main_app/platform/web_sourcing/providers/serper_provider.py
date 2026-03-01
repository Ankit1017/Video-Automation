from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen

from main_app.platform.web_sourcing.contracts import WebSearchResult


class SerperSearchProvider:
    key = "serper"
    _SEARCH_URL = "https://google.serper.dev/search"

    def __init__(self, api_key: str | None = None) -> None:
        configured_key = api_key if api_key is not None else os.getenv("SERPER_API_KEY", "")
        self._api_key = " ".join(str(configured_key).split()).strip()

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def search(
        self,
        query: str,
        *,
        max_results: int,
        recency_days: int | None,
        timeout_ms: int,
    ) -> list[WebSearchResult]:
        if not self.available:
            raise RuntimeError("Serper provider is not configured (SERPER_API_KEY missing).")
        normalized_query = " ".join(str(query).split()).strip()
        if not normalized_query or max_results <= 0:
            return []

        payload: dict[str, object] = {"q": normalized_query, "num": max_results}
        if recency_days is not None and recency_days > 0:
            payload["tbs"] = f"qdr:d{int(recency_days)}"

        request = Request(
            self._SEARCH_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "X-API-KEY": self._api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        timeout_seconds = max(1.0, float(timeout_ms) / 1000.0)
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(512_000).decode("utf-8", errors="ignore")
        parsed = json.loads(raw)
        organic = parsed.get("organic", []) if isinstance(parsed, dict) else []

        output: list[WebSearchResult] = []
        for rank, item in enumerate(organic if isinstance(organic, list) else [], start=1):
            if not isinstance(item, dict):
                continue
            url = " ".join(str(item.get("link", "")).split()).strip()
            if not url:
                continue
            output.append(
                WebSearchResult(
                    title=" ".join(str(item.get("title", "")).split()).strip() or url,
                    url=url,
                    snippet=" ".join(str(item.get("snippet", "")).split()).strip(),
                    rank=rank,
                )
            )
            if len(output) >= max_results:
                break
        return output
