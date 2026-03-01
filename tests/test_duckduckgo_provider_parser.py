from __future__ import annotations

import unittest

from main_app.platform.web_sourcing.providers.duckduckgo_provider import DuckDuckGoSearchProvider


class TestDuckDuckGoProviderParser(unittest.TestCase):
    def test_parse_result_link_without_bs4(self) -> None:
        html = """
        <html><body>
            <a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa" class='result-link'>
                Example A
            </a>
            <a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fb" class="result-link">Example B</a>
        </body></html>
        """
        results = DuckDuckGoSearchProvider._parse_results_without_bs4(html, max_results=5)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].url, "https://example.com/a")
        self.assertEqual(results[1].url, "https://example.com/b")

    def test_parse_result_a_without_bs4(self) -> None:
        html = """
        <html><body>
            <a href="https://example.org/x" class="result__a">Result X</a>
            <a class="result__a" href="https://example.org/y">Result Y</a>
        </body></html>
        """
        results = DuckDuckGoSearchProvider._parse_results_without_bs4(html, max_results=5)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].url, "https://example.org/x")
        self.assertEqual(results[1].url, "https://example.org/y")

    def test_unwrap_protocol_relative_redirect_url(self) -> None:
        raw = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.net%2Fpage"
        resolved = DuckDuckGoSearchProvider._unwrap_duckduckgo_redirect(raw)
        self.assertEqual(resolved, "https://example.net/page")


if __name__ == "__main__":
    unittest.main()
