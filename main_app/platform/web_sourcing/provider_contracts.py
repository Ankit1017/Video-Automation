from __future__ import annotations

from typing import Protocol

from main_app.platform.web_sourcing.contracts import WebSearchResult


class WebSearchProvider(Protocol):
    key: str

    def search(
        self,
        query: str,
        *,
        max_results: int,
        recency_days: int | None,
        timeout_ms: int,
    ) -> list[WebSearchResult]:
        ...
