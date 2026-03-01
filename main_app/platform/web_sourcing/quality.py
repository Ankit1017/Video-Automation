from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from urllib.parse import urlparse

from main_app.platform.web_sourcing.prechecks import domain_matches, normalize_domain
from main_app.platform.web_sourcing.query_strategy import tokenize_text


_URL_DATE_PATTERN = re.compile(r"(20\d{2})[-_/](0?[1-9]|1[0-2])[-_/](0?[1-9]|[12]\d|3[01])")
_BOILERPLATE_PHRASES = (
    "accept cookies",
    "enable cookies",
    "cookie policy",
    "javascript is disabled",
    "all rights reserved",
    "sign in",
    "log in",
    "subscribe now",
)
_AUTHORITATIVE_KEYWORDS = (
    "docs.",
    "developer.",
    "wikipedia.org",
    "arxiv.org",
    "github.com",
    "ietf.org",
    "nasa.gov",
)


@dataclass(frozen=True)
class QualityScoreResult:
    quality_score: float
    relevance_score: float
    authority_score: float
    freshness_score: float
    structure_score: float
    reasons: list[str]


def score_search_candidate(
    *,
    query: str,
    title: str,
    snippet: str,
    rank: int,
    url: str,
    trusted_domains: list[str],
    trusted_boost_enabled: bool,
) -> float:
    relevance = _relevance_score(
        query=query,
        title=title,
        snippet=snippet,
        text_head="",
    )
    authority = _authority_score(
        url=url,
        trusted_domains=trusted_domains,
        trusted_boost_enabled=trusted_boost_enabled,
    )
    normalized_rank = max(1, int(rank))
    rank_score = max(0.0, 1.0 - ((normalized_rank - 1) / 20.0))
    score = (relevance * 0.75) + (authority * 0.20) + (rank_score * 0.05)
    return round(_clamp01(score), 4)


def score_fetched_page(
    *,
    query: str,
    title: str,
    text: str,
    snippet: str,
    url: str,
    allow_recency_days: int | None,
    trusted_domains: list[str],
    trusted_boost_enabled: bool,
) -> QualityScoreResult:
    text_head = str(text or "")[:1200]
    relevance = _relevance_score(query=query, title=title, snippet=snippet, text_head=text_head)
    authority = _authority_score(
        url=url,
        trusted_domains=trusted_domains,
        trusted_boost_enabled=trusted_boost_enabled,
    )
    freshness = _freshness_score(
        url=url,
        title=title,
        snippet=snippet,
        text_head=text_head,
        allow_recency_days=allow_recency_days,
    )
    structure = _structure_score(text=text)
    quality = (
        (relevance * 0.50)
        + (authority * 0.20)
        + (freshness * 0.15)
        + (structure * 0.15)
    )
    rounded_quality = round(_clamp01(quality), 4)
    reasons = _quality_reasons(
        relevance=relevance,
        authority=authority,
        freshness=freshness,
        structure=structure,
    )
    reasons.append(
        "scores r="
        f"{relevance:.2f} a={authority:.2f} f={freshness:.2f} s={structure:.2f}"
    )
    return QualityScoreResult(
        quality_score=rounded_quality,
        relevance_score=round(relevance, 4),
        authority_score=round(authority, 4),
        freshness_score=round(freshness, 4),
        structure_score=round(structure, 4),
        reasons=reasons,
    )


def extract_domain(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    return normalize_domain(parsed.hostname or "")


def _relevance_score(*, query: str, title: str, snippet: str, text_head: str) -> float:
    query_tokens = set(tokenize_text(query))
    if not query_tokens:
        return 0.0
    title_tokens = set(tokenize_text(title))
    snippet_tokens = set(tokenize_text(snippet))
    head_tokens = set(tokenize_text(text_head))
    title_overlap = len(query_tokens & title_tokens) / len(query_tokens)
    snippet_overlap = len(query_tokens & snippet_tokens) / len(query_tokens)
    head_overlap = len(query_tokens & head_tokens) / len(query_tokens)
    score = (title_overlap * 0.55) + (snippet_overlap * 0.25) + (head_overlap * 0.20)
    return _clamp01(score)


def _authority_score(*, url: str, trusted_domains: list[str], trusted_boost_enabled: bool) -> float:
    domain = extract_domain(url)
    if not domain:
        return 0.0

    score = 0.40
    if domain.endswith(".gov") or domain.endswith(".edu"):
        score += 0.35
    if any(keyword in domain for keyword in _AUTHORITATIVE_KEYWORDS):
        score += 0.20
    if trusted_boost_enabled and trusted_domains:
        if any(domain_matches(domain, trusted) for trusted in trusted_domains):
            score += 0.25
    return _clamp01(score)


def _freshness_score(
    *,
    url: str,
    title: str,
    snippet: str,
    text_head: str,
    allow_recency_days: int | None,
) -> float:
    reference_text = " ".join([str(url), str(title), str(snippet), str(text_head)[:250]])
    candidate_date = _extract_date(reference_text)
    if candidate_date is None:
        return 0.5

    now = datetime.now(timezone.utc).date()
    age_days = max(0, (now - candidate_date).days)
    if allow_recency_days is not None and allow_recency_days > 0:
        if age_days <= allow_recency_days:
            return 1.0
        if age_days <= allow_recency_days * 2:
            return 0.7
        return 0.25

    if age_days <= 30:
        return 1.0
    if age_days <= 180:
        return 0.8
    if age_days <= 365:
        return 0.6
    if age_days <= 1_095:
        return 0.4
    return 0.2


def _structure_score(*, text: str) -> float:
    cleaned = " ".join(str(text or "").split()).strip()
    length = len(cleaned)
    if length < 120:
        base = 0.05
    elif length < 300:
        base = 0.20
    elif length < 800:
        base = 0.45
    elif length <= 8000:
        base = 1.0
    elif length <= 12000:
        base = 0.85
    elif length <= 20000:
        base = 0.65
    else:
        base = 0.45

    lowered = cleaned.lower()
    boilerplate_hits = sum(1 for phrase in _BOILERPLATE_PHRASES if phrase in lowered)
    boilerplate_penalty = min(0.5, boilerplate_hits * 0.1)
    return _clamp01(base - boilerplate_penalty)


def _extract_date(text: str):
    match = _URL_DATE_PATTERN.search(str(text or ""))
    if match is None:
        return None
    try:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        return datetime(year, month, day, tzinfo=timezone.utc).date()
    except ValueError:
        return None


def _quality_reasons(*, relevance: float, authority: float, freshness: float, structure: float) -> list[str]:
    reasons: list[str] = []
    if relevance >= 0.7:
        reasons.append("strong query match")
    elif relevance < 0.35:
        reasons.append("weak query match")

    if authority >= 0.75:
        reasons.append("authoritative or trusted domain")
    elif authority < 0.4:
        reasons.append("low authority signal")

    if freshness < 0.4:
        reasons.append("possibly stale information")
    if structure < 0.45:
        reasons.append("text quality is weak or boilerplate-heavy")
    if not reasons:
        reasons.append("balanced quality profile")
    return reasons


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
