from __future__ import annotations

import ipaddress
import re
from urllib.parse import parse_qsl, urlparse, urlunparse

from main_app.platform.web_sourcing.contracts import DomainPolicyDecision


_TRACKING_PARAMS = (
    "utm_",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
)

_DEFAULT_BLOCKED_DOMAINS = {
    "localhost",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "pinterest.com",
    "youtube.com",
    "youtube-nocookie.com",
    "accounts.google.com",
    "drive.google.com",
    "docs.google.com",
    "mail.google.com",
    "microsoftonline.com",
    "login.live.com",
}

_DEFAULT_BLOCKED_SUFFIXES = (
    ".facebook.com",
    ".instagram.com",
    ".linkedin.com",
    ".twitter.com",
    ".x.com",
    ".tiktok.com",
    ".youtube.com",
    ".googleusercontent.com",
)


def clamp_int(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def normalize_query(topic: str, constraints: str) -> str:
    topic_clean = " ".join(str(topic).split()).strip()
    constraints_clean = " ".join(str(constraints).split()).strip()
    combined = " ".join(part for part in (topic_clean, constraints_clean) if part).strip()
    if len(combined) < 3:
        return ""
    return combined


def parse_domain_list(raw_value: str) -> list[str]:
    if not raw_value:
        return []
    pieces = re.split(r"[,\n;]+", str(raw_value))
    domains: list[str] = []
    for piece in pieces:
        domain = normalize_domain(piece)
        if domain:
            domains.append(domain)
    seen: set[str] = set()
    ordered: list[str] = []
    for domain in domains:
        if domain in seen:
            continue
        seen.add(domain)
        ordered.append(domain)
    return ordered


def normalize_domain(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "://" in text:
        parsed = urlparse(text)
        host = parsed.hostname or ""
    else:
        host = text.split("/")[0]
    host = host.strip().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def domain_matches(domain: str, candidate: str) -> bool:
    normalized_domain = normalize_domain(domain)
    normalized_candidate = normalize_domain(candidate)
    if not normalized_domain or not normalized_candidate:
        return False
    return normalized_domain == normalized_candidate or normalized_domain.endswith(f".{normalized_candidate}")


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = (parsed.netloc or "").lower()
    path = parsed.path or "/"
    query_pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        key_clean = key.strip().lower()
        if not key_clean:
            continue
        if any(key_clean.startswith(prefix) for prefix in _TRACKING_PARAMS):
            continue
        query_pairs.append((key, value))
    query = "&".join(f"{key}={value}" for key, value in query_pairs)
    return urlunparse((scheme, netloc, path, "", query, ""))


def is_supported_content_type(content_type: str) -> bool:
    lowered = str(content_type or "").lower()
    return (
        lowered.startswith("text/html")
        or lowered.startswith("text/plain")
        or lowered.startswith("application/pdf")
    )


def evaluate_domain_policy(
    url: str,
    *,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> DomainPolicyDecision:
    parsed = urlparse(str(url or "").strip())
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        return DomainPolicyDecision(url=url, domain="", allowed=False, reason="unsupported_scheme")

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return DomainPolicyDecision(url=url, domain="", allowed=False, reason="missing_host")

    if _is_local_or_private_host(host):
        return DomainPolicyDecision(url=url, domain=host, allowed=False, reason="private_or_local_host")

    port = parsed.port
    if port not in {None, 80, 443}:
        return DomainPolicyDecision(url=url, domain=host, allowed=False, reason="blocked_port")

    normalized_domain = normalize_domain(host)
    if _is_blocked_domain(normalized_domain):
        return DomainPolicyDecision(url=url, domain=normalized_domain, allowed=False, reason="domain_blocklist")

    include = [normalize_domain(item) for item in (include_domains or []) if normalize_domain(item)]
    exclude = [normalize_domain(item) for item in (exclude_domains or []) if normalize_domain(item)]

    for blocked_domain in exclude:
        if domain_matches(normalized_domain, blocked_domain):
            return DomainPolicyDecision(url=url, domain=normalized_domain, allowed=False, reason="excluded_domain")

    if include:
        if not any(domain_matches(normalized_domain, allowed_domain) for allowed_domain in include):
            return DomainPolicyDecision(url=url, domain=normalized_domain, allowed=False, reason="not_included_domain")

    return DomainPolicyDecision(url=url, domain=normalized_domain, allowed=True, reason="")


def evaluate_text_quality(text: str, *, min_chars: int = 240) -> tuple[bool, str]:
    normalized = " ".join(str(text or "").split()).strip()
    if len(normalized) < min_chars:
        return False, "text_too_short"
    lowered = normalized.lower()
    boilerplate_hits = sum(
        1
        for phrase in (
            "enable cookies",
            "accept cookies",
            "javascript is disabled",
            "sign in",
            "log in",
            "all rights reserved",
        )
        if phrase in lowered
    )
    if boilerplate_hits >= 3:
        return False, "boilerplate_heavy"
    return True, ""


def _is_local_or_private_host(host: str) -> bool:
    normalized = normalize_domain(host)
    if not normalized:
        return True
    if normalized in {"localhost", "0.0.0.0"}:
        return True
    if normalized.endswith(".local") or normalized.endswith(".internal"):
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_reserved
        or address.is_link_local
        or address.is_multicast
    )


def _is_blocked_domain(domain: str) -> bool:
    if domain in _DEFAULT_BLOCKED_DOMAINS:
        return True
    return any(domain.endswith(suffix) for suffix in _DEFAULT_BLOCKED_SUFFIXES)
