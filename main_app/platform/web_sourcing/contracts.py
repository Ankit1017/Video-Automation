from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    rank: int = 0


@dataclass(frozen=True)
class DomainPolicyDecision:
    url: str
    domain: str
    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class FetchedPage:
    url: str
    final_url: str
    title: str
    text: str
    content_type: str
    status_code: int
    char_count: int
    truncated: bool
    retrieved_at: str
    quality_score: float = 0.0
    quality_reasons: list[str] = field(default_factory=list)
    domain: str = ""


@dataclass(frozen=True)
class ProviderAttempt:
    provider_key: str
    status: str
    search_count: int = 0
    candidate_url_count: int = 0
    fetched_count: int = 0
    accepted_count: int = 0
    retry_events: int = 0
    error: str = ""
    circuit_state: str = ""


@dataclass
class WebSourcingRunResult:
    query: str
    provider: str
    search_results: list[WebSearchResult]
    fetched_pages: list[FetchedPage]
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    cache_hit: bool = False
