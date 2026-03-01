from __future__ import annotations

import html as html_lib
import re
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from main_app.platform.web_sourcing.contracts import WebSearchResult

try:
    from bs4 import BeautifulSoup
except ModuleNotFoundError:  # pragma: no cover - handled via fallback parser
    BeautifulSoup = None  # type: ignore[assignment]


class DuckDuckGoSearchProvider:
    key = "duckduckgo"
    _MINI_USER_AGENT = "Mozilla/5.0"
    _FULL_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    _REQUEST_PROFILES: tuple[tuple[str, str], ...] = (
        ("https://duckduckgo.com/html/", _MINI_USER_AGENT),
        ("https://html.duckduckgo.com/html/", _MINI_USER_AGENT),
        ("https://duckduckgo.com/html/", _FULL_USER_AGENT),
        ("https://html.duckduckgo.com/html/", _FULL_USER_AGENT),
        ("https://duckduckgo.com/lite/", _FULL_USER_AGENT),
        ("https://duckduckgo.com/lite/", _MINI_USER_AGENT),
    )

    def search(
        self,
        query: str,
        *,
        max_results: int,
        recency_days: int | None,
        timeout_ms: int,
    ) -> list[WebSearchResult]:
        del recency_days
        normalized_query = " ".join(str(query).split()).strip()
        if not normalized_query or max_results <= 0:
            return []

        params = urlencode({"q": normalized_query})
        timeout_seconds = max(1.0, float(timeout_ms) / 1000.0)
        for base_url, user_agent in self._REQUEST_PROFILES:
            request = Request(
                f"{base_url}?{params}",
                headers={
                    "User-Agent": user_agent,
                    "Accept-Language": "en-US,en;q=0.9",
                },
                method="GET",
            )
            try:
                with urlopen(request, timeout=timeout_seconds) as response:
                    html = response.read(512_000).decode("utf-8", errors="ignore")
            except (OSError, RuntimeError, ValueError):
                continue
            parsed = self._parse_results(html, max_results=max_results)
            if parsed:
                return parsed
            if self._looks_like_anomaly_page(html):
                continue
        return []

    def _parse_results(self, html: str, *, max_results: int) -> list[WebSearchResult]:
        if BeautifulSoup is None:
            return self._parse_results_without_bs4(html=html, max_results=max_results)

        soup = BeautifulSoup(html, "html.parser")
        output: list[WebSearchResult] = []
        anchors = soup.select("a.result__a")
        if not anchors:
            anchors = soup.select("a.result-link")
        for rank, anchor in enumerate(anchors, start=1):
            href = str(anchor.get("href", "")).strip()
            resolved_url = self._unwrap_duckduckgo_redirect(href)
            if not resolved_url:
                continue
            title = " ".join(anchor.get_text(" ").split()).strip()
            snippet_node = anchor.find_parent("div", class_="result")
            snippet = ""
            if snippet_node is not None:
                snippet_tag = snippet_node.select_one(".result__snippet")
                if snippet_tag is not None:
                    snippet = " ".join(snippet_tag.get_text(" ").split()).strip()
            output.append(
                WebSearchResult(
                    title=title or resolved_url,
                    url=resolved_url,
                    snippet=snippet,
                    rank=rank,
                )
            )
            if len(output) >= max_results:
                break
        return output

    @staticmethod
    def _parse_results_without_bs4(html: str, *, max_results: int) -> list[WebSearchResult]:
        # Lightweight fallback parser when bs4 is unavailable.
        output = DuckDuckGoSearchProvider._parse_results_without_bs4_for_class(
            html=html,
            css_class="result__a",
            max_results=max_results,
        )
        if output:
            return output
        output = DuckDuckGoSearchProvider._parse_results_without_bs4_for_class(
            html=html,
            css_class="result-link",
            max_results=max_results,
        )
        return output

    @staticmethod
    def _parse_results_without_bs4_for_class(
        *,
        html: str,
        css_class: str,
        max_results: int,
    ) -> list[WebSearchResult]:
        output: list[WebSearchResult] = []
        anchor_pattern = re.compile(r"<a(?P<attrs>[^>]*)>(?P<title>.*?)</a>", re.IGNORECASE | re.DOTALL)
        class_pattern = re.compile(r"class=(?P<q>['\"])(?P<value>.*?)(?P=q)", re.IGNORECASE | re.DOTALL)
        href_pattern = re.compile(r"href=(?P<q>['\"])(?P<value>.*?)(?P=q)", re.IGNORECASE | re.DOTALL)
        seen_urls: set[str] = set()
        for match in anchor_pattern.finditer(html):
            attrs = str(match.group("attrs") or "")
            class_match = class_pattern.search(attrs)
            if class_match is None:
                continue
            classes = {" ".join(item.split()).strip() for item in str(class_match.group("value") or "").split()}
            if css_class not in classes:
                continue

            href_match = href_pattern.search(attrs)
            if href_match is None:
                continue
            raw_href = str(href_match.group("value") or "").strip()
            resolved = DuckDuckGoSearchProvider._unwrap_duckduckgo_redirect(raw_href)
            if not resolved or resolved in seen_urls:
                continue
            title_html = str(match.group("title") or "")
            title_text = re.sub(r"(?is)<[^>]+>", " ", title_html)
            title_text = html_lib.unescape(" ".join(title_text.split()).strip())
            output.append(
                WebSearchResult(
                    title=title_text or resolved,
                    url=resolved,
                    snippet="",
                    rank=len(output) + 1,
                )
            )
            seen_urls.add(resolved)
            if len(output) >= max_results:
                break
        return output

    @staticmethod
    def _unwrap_duckduckgo_redirect(url: str) -> str:
        raw = str(url or "").strip()
        if raw.startswith("//"):
            raw = f"https:{raw}"
        parsed = urlparse(raw)
        if not parsed.scheme:
            return ""
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            qs = parse_qs(parsed.query)
            redirected = qs.get("uddg", [""])[0]
            return str(redirected).strip()
        return raw

    @staticmethod
    def _looks_like_anomaly_page(html: str) -> bool:
        lowered = str(html or "").lower()
        return (
            "anomaly" in lowered
            or "bots use duckduckgo too" in lowered
            or "please complete the challenge" in lowered
        )
