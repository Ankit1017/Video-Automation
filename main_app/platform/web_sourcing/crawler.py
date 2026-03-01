from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import re
import urllib.robotparser

from main_app.platform.web_sourcing.contracts import DomainPolicyDecision, FetchedPage
from main_app.platform.web_sourcing.content_cache_store import WebContentCacheStore
from main_app.platform.web_sourcing.prechecks import (
    canonicalize_url,
    is_supported_content_type,
)
from main_app.platform.web_sourcing.reliability import DomainRateLimiter, RetryPolicy
from main_app.services.text_sanitizer import sanitize_text

try:
    from bs4 import BeautifulSoup
except ModuleNotFoundError:  # pragma: no cover - handled with fallback cleaner
    BeautifulSoup = None  # type: ignore[assignment]


class FocusedCrawler:
    _USER_AGENT = "Mozilla/5.0 (compatible; VideoAutomationBot/1.0)"

    def __init__(self, *, content_cache_store: WebContentCacheStore | None = None) -> None:
        self._content_cache_store = content_cache_store or WebContentCacheStore()

    def fetch_many(
        self,
        urls: list[str],
        *,
        max_pages: int,
        timeout_ms: int,
        max_chars_per_page: int,
        max_total_chars: int,
        policy: Callable[[str], DomainPolicyDecision],
        rate_limiter: DomainRateLimiter | None = None,
        rate_limit_per_minute: int = 0,
        retry_policy: RetryPolicy | None = None,
        on_retry_event: Callable[[str, int, Exception], None] | None = None,
        content_cache_ttl_seconds: int = 0,
        content_cache_force_refresh: bool = False,
    ) -> tuple[list[FetchedPage], list[str], dict[str, int]]:
        warnings: list[str] = []
        fetched_pages: list[FetchedPage] = []
        attempted = 0
        fetched = 0
        accepted = 0
        rate_limited_count = 0
        retry_events = 0
        content_cache_hit_count = 0
        content_cache_miss_count = 0
        consumed_chars = 0
        seen_canonical_urls: set[str] = set()
        seen_content_hashes: set[str] = set()
        
        def _emit_retry_event(event_url: str, attempt: int, error: Exception) -> None:
            nonlocal retry_events
            retry_events += 1
            if on_retry_event is not None:
                on_retry_event(event_url, attempt, error)

        for raw_url in urls:
            if accepted >= max_pages:
                break
            if consumed_chars >= max_total_chars:
                warnings.append("Web char budget reached; remaining pages were skipped.")
                break

            decision = policy(raw_url)
            if not isinstance(decision, DomainPolicyDecision) or not decision.allowed:
                reason = decision.reason if isinstance(decision, DomainPolicyDecision) else "policy_rejected"
                warnings.append(f"Skipped URL due to policy ({reason}): {raw_url}")
                continue

            parsed = urlparse(raw_url)
            domain = (parsed.hostname or "").strip().lower()
            if rate_limiter is not None and domain:
                if not rate_limiter.allow(domain, per_minute=rate_limit_per_minute):
                    warnings.append(f"Rate limit exceeded for domain `{domain}`; skipped URL: {raw_url}")
                    rate_limited_count += 1
                    continue

            robots_allowed, robots_warning = self._robots_allows(raw_url, timeout_ms=timeout_ms)
            if robots_warning:
                warnings.append(robots_warning)
            if not robots_allowed:
                warnings.append(f"Skipped due to robots.txt policy: {raw_url}")
                continue

            attempted += 1
            page_or_error: FetchedPage | str | None = None
            if not bool(content_cache_force_refresh) and int(content_cache_ttl_seconds) > 0:
                cached_page = self._get_cached_page(
                    url=raw_url,
                    max_chars_per_page=max_chars_per_page,
                    ttl_seconds=int(content_cache_ttl_seconds),
                )
                if cached_page is not None:
                    page_or_error = cached_page
                    content_cache_hit_count += 1
                else:
                    content_cache_miss_count += 1

            if page_or_error is None:
                page_or_error = self._fetch_single(
                    url=raw_url,
                    timeout_ms=timeout_ms,
                    max_chars_per_page=max_chars_per_page,
                    retry_policy=retry_policy,
                    on_retry_event=_emit_retry_event,
                )
                if isinstance(page_or_error, FetchedPage):
                    self._set_cached_page(page_or_error, max_chars_per_page=max_chars_per_page)
            if isinstance(page_or_error, str):
                warnings.append(page_or_error)
                continue
            fetched += 1

            page = page_or_error
            canonical_url = canonicalize_url(page.final_url or page.url)
            if canonical_url in seen_canonical_urls:
                warnings.append(f"Duplicate URL skipped: {canonical_url}")
                continue

            content_hash = sha256(page.text.encode("utf-8")).hexdigest()
            if content_hash in seen_content_hashes:
                warnings.append(f"Near-duplicate page skipped: {canonical_url}")
                continue

            text = page.text
            remaining = max_total_chars - consumed_chars
            truncated = page.truncated
            if len(text) > remaining:
                text = text[:remaining].rstrip()
                truncated = True

            if not text:
                continue

            stored_page = FetchedPage(
                url=page.url,
                final_url=page.final_url,
                title=page.title,
                text=text,
                content_type=page.content_type,
                status_code=page.status_code,
                char_count=len(text),
                truncated=truncated,
                retrieved_at=page.retrieved_at,
            )
            fetched_pages.append(stored_page)
            seen_canonical_urls.add(canonical_url)
            seen_content_hashes.add(content_hash)
            consumed_chars += len(text)
            accepted += 1

        stats = {
            "attempted_count": attempted,
            "fetched_count": fetched,
            "accepted_count": accepted,
            "rate_limited_count": rate_limited_count,
            "retry_events": retry_events,
            "content_cache_hit_count": content_cache_hit_count,
            "content_cache_miss_count": content_cache_miss_count,
        }
        return fetched_pages, warnings, stats

    def _fetch_single(
        self,
        *,
        url: str,
        timeout_ms: int,
        max_chars_per_page: int,
        retry_policy: RetryPolicy | None = None,
        on_retry_event: Callable[[str, int, Exception], None] | None = None,
    ) -> FetchedPage | str:
        timeout_seconds = max(1.0, float(timeout_ms) / 1000.0)
        request = Request(url, headers={"User-Agent": self._USER_AGENT}, method="GET")
        max_download_bytes = max(250_000, max_chars_per_page * 6)
        
        def _download() -> tuple[int, str, str, bytes]:
            with urlopen(request, timeout=timeout_seconds) as response:
                status = int(getattr(response, "status", 200) or 200)
                final_url = str(response.geturl() or url)
                content_type = str(response.headers.get("Content-Type", "")).strip().lower()
                payload = response.read(max_download_bytes + 1)
                return status, final_url, content_type, payload

        try:
            if retry_policy is None:
                status, final_url, content_type, payload = _download()
            else:
                status, final_url, content_type, payload = retry_policy.run(
                    _download,
                    on_retry=(
                        None
                        if on_retry_event is None
                        else lambda attempt, error: on_retry_event(url, attempt, error)
                    ),
                )
        except Exception as exc:
            return f"Fetch failed for {url}: {exc}"

        if not is_supported_content_type(content_type):
            return f"Skipped unsupported content type `{content_type}`: {final_url}"
        if len(payload) > max_download_bytes:
            return f"Skipped oversized response body (> {max_download_bytes} bytes): {final_url}"

        extracted = self._extract_text(payload=payload, content_type=content_type)
        if not extracted.strip():
            return f"No readable text extracted from: {final_url}"
        normalized = sanitize_text(extracted, keep_citations=True, preserve_newlines=False)
        if not normalized:
            return f"Text became empty after sanitization: {final_url}"

        truncated = False
        if len(normalized) > max_chars_per_page:
            normalized = normalized[:max_chars_per_page].rstrip()
            truncated = True

        title = self._derive_title(text=normalized, url=final_url)
        return FetchedPage(
            url=url,
            final_url=final_url,
            title=title,
            text=normalized,
            content_type=content_type,
            status_code=status,
            char_count=len(normalized),
            truncated=truncated,
            retrieved_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )

    def _extract_text(self, *, payload: bytes, content_type: str) -> str:
        if content_type.startswith("application/pdf"):
            return self._extract_pdf_text(payload)
        if content_type.startswith("text/html"):
            return self._extract_html_text(payload)
        return self._extract_plain_text(payload)

    @staticmethod
    def _extract_plain_text(payload: bytes) -> str:
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return payload.decode(encoding)
            except UnicodeDecodeError:
                continue
        return payload.decode("utf-8", errors="ignore")

    @staticmethod
    def _extract_pdf_text(payload: bytes) -> str:
        try:
            from pypdf import PdfReader
        except ModuleNotFoundError:
            return ""
        try:
            reader = PdfReader(BytesIO(payload))
        except (OSError, RuntimeError, TypeError, ValueError):
            return ""
        chunks: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                chunks.append(text)
        return "\n\n".join(chunks).strip()

    @staticmethod
    def _extract_html_text(payload: bytes) -> str:
        html = payload.decode("utf-8", errors="ignore")
        if BeautifulSoup is None:
            return FocusedCrawler._strip_html_without_bs4(html)
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "aside", "form"]):
            tag.decompose()
        text = soup.get_text("\n")
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())

    @staticmethod
    def _strip_html_without_bs4(html: str) -> str:
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
        return " ".join(text.split())

    @staticmethod
    def _derive_title(*, text: str, url: str) -> str:
        first_sentence = text.split(".")[0].strip()
        if first_sentence and len(first_sentence) <= 120:
            return first_sentence
        parsed = urlparse(url)
        host = parsed.hostname or "Web Source"
        return host

    def _robots_allows(self, url: str, *, timeout_ms: int) -> tuple[bool, str]:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False, f"Invalid URL for robots check: {url}"
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        timeout_seconds = max(1.0, min(3.0, float(timeout_ms) / 1000.0))
        request = Request(robots_url, headers={"User-Agent": self._USER_AGENT}, method="GET")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read(64_000).decode("utf-8", errors="ignore")
        except (OSError, RuntimeError, ValueError):
            return True, f"robots.txt check unavailable for {parsed.netloc}; continuing."

        parser = urllib.robotparser.RobotFileParser()
        parser.parse(raw.splitlines())
        target_path = parsed.path or "/"
        allowed = parser.can_fetch(self._USER_AGENT, target_path)
        return allowed, ""

    def _content_cache_key(self, *, url: str, max_chars_per_page: int) -> str:
        canonical = canonicalize_url(url)
        if not canonical:
            canonical = " ".join(str(url).split()).strip()
        payload = f"{canonical}|max_chars={int(max_chars_per_page)}"
        return sha256(payload.encode("utf-8")).hexdigest()

    def _get_cached_page(
        self,
        *,
        url: str,
        max_chars_per_page: int,
        ttl_seconds: int,
    ) -> FetchedPage | None:
        key = self._content_cache_key(url=url, max_chars_per_page=max_chars_per_page)
        payload = self._content_cache_store.get(key, ttl_seconds=ttl_seconds)
        if not isinstance(payload, dict):
            return None
        try:
            return FetchedPage(
                url=str(payload.get("url", "")),
                final_url=str(payload.get("final_url", "")),
                title=str(payload.get("title", "")),
                text=str(payload.get("text", "")),
                content_type=str(payload.get("content_type", "")),
                status_code=int(payload.get("status_code", 0) or 0),
                char_count=int(payload.get("char_count", 0) or 0),
                truncated=bool(payload.get("truncated", False)),
                retrieved_at=str(payload.get("retrieved_at", "")),
                quality_score=float(payload.get("quality_score", 0.0) or 0.0),
                quality_reasons=[str(item) for item in payload.get("quality_reasons", []) if str(item).strip()],
                domain=str(payload.get("domain", "")),
            )
        except (TypeError, ValueError):
            return None

    def _set_cached_page(self, page: FetchedPage, *, max_chars_per_page: int) -> None:
        key = self._content_cache_key(url=page.final_url or page.url, max_chars_per_page=max_chars_per_page)
        self._content_cache_store.set(
            key,
            {
                "url": page.url,
                "final_url": page.final_url,
                "title": page.title,
                "text": page.text,
                "content_type": page.content_type,
                "status_code": page.status_code,
                "char_count": page.char_count,
                "truncated": page.truncated,
                "retrieved_at": page.retrieved_at,
                "quality_score": page.quality_score,
                "quality_reasons": list(page.quality_reasons),
                "domain": page.domain,
            },
        )
