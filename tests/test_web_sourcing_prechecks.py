from __future__ import annotations

import unittest

from main_app.platform.web_sourcing.prechecks import (
    canonicalize_url,
    evaluate_domain_policy,
    normalize_query,
    parse_domain_list,
)


class TestWebSourcingPrechecks(unittest.TestCase):
    def test_domain_policy_blocks_private_hosts(self) -> None:
        decision = evaluate_domain_policy("http://127.0.0.1:8000/health")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "private_or_local_host")

    def test_domain_policy_respects_include_and_exclude(self) -> None:
        allowed = evaluate_domain_policy(
            "https://docs.python.org/3/tutorial/",
            include_domains=["python.org"],
            exclude_domains=["example.com"],
        )
        denied = evaluate_domain_policy(
            "https://example.com/docs",
            include_domains=["python.org", "example.com"],
            exclude_domains=["example.com"],
        )
        self.assertTrue(allowed.allowed)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "excluded_domain")

    def test_query_and_domain_parsing_normalization(self) -> None:
        query = normalize_query("  Agentic   AI  ", "  production observability ")
        self.assertEqual(query, "Agentic AI production observability")
        domains = parse_domain_list("docs.python.org, https://www.openai.com\nexample.com")
        self.assertEqual(domains, ["docs.python.org", "openai.com", "example.com"])

    def test_canonicalize_url_drops_tracking_params(self) -> None:
        canonical = canonicalize_url("https://example.com/a?utm_source=x&id=9&fbclid=123")
        self.assertEqual(canonical, "https://example.com/a?id=9")


if __name__ == "__main__":
    unittest.main()
