from __future__ import annotations

import unittest

from main_app.platform.web_sourcing.reliability import (
    DomainRateLimiter,
    ProviderCircuitBreakerRegistry,
    RetryPolicy,
)


class TestWebSourcingReliability(unittest.TestCase):
    def test_retry_policy_retries_transient_errors(self) -> None:
        policy = RetryPolicy(retry_count=2, base_delay_ms=1, max_delay_ms=1, jitter_ms=0)
        calls = {"count": 0}

        def _operation() -> str:
            calls["count"] += 1
            if calls["count"] == 1:
                raise OSError("temporary network issue")
            return "ok"

        result = policy.run(_operation, sleep_fn=lambda _seconds: None)
        self.assertEqual(result, "ok")
        self.assertEqual(calls["count"], 2)

    def test_retry_policy_does_not_retry_non_transient_errors(self) -> None:
        policy = RetryPolicy(retry_count=2, base_delay_ms=1, max_delay_ms=1, jitter_ms=0)
        calls = {"count": 0}

        def _operation() -> str:
            calls["count"] += 1
            raise ValueError("bad input")

        with self.assertRaises(ValueError):
            policy.run(_operation, sleep_fn=lambda _seconds: None)
        self.assertEqual(calls["count"], 1)

    def test_domain_rate_limiter_windowing(self) -> None:
        limiter = DomainRateLimiter()
        self.assertTrue(limiter.allow("example.com", per_minute=2, now=0.0))
        self.assertTrue(limiter.allow("example.com", per_minute=2, now=1.0))
        self.assertFalse(limiter.allow("example.com", per_minute=2, now=2.0))
        self.assertTrue(limiter.allow("example.com", per_minute=2, now=61.0))

    def test_provider_circuit_breaker_lifecycle(self) -> None:
        breaker = ProviderCircuitBreakerRegistry()
        allowed, _ = breaker.can_attempt(
            "duckduckgo",
            enabled=True,
            cooldown_seconds=10,
            probe_requests=1,
            now=0.0,
        )
        self.assertTrue(allowed)

        breaker.record_failure("duckduckgo", enabled=True, error_threshold=2, now=1.0)
        breaker.record_failure("duckduckgo", enabled=True, error_threshold=2, now=2.0)
        allowed_open, reason_open = breaker.can_attempt(
            "duckduckgo",
            enabled=True,
            cooldown_seconds=10,
            probe_requests=1,
            now=5.0,
        )
        self.assertFalse(allowed_open)
        self.assertEqual(reason_open, "circuit_open")

        allowed_probe, reason_probe = breaker.can_attempt(
            "duckduckgo",
            enabled=True,
            cooldown_seconds=10,
            probe_requests=1,
            now=13.0,
        )
        self.assertTrue(allowed_probe)
        self.assertEqual(reason_probe, "half_open_probe")

        allowed_blocked, reason_blocked = breaker.can_attempt(
            "duckduckgo",
            enabled=True,
            cooldown_seconds=10,
            probe_requests=1,
            now=13.1,
        )
        self.assertFalse(allowed_blocked)
        self.assertEqual(reason_blocked, "half_open_blocked")

        breaker.record_success("duckduckgo", enabled=True)
        allowed_closed, reason_closed = breaker.can_attempt(
            "duckduckgo",
            enabled=True,
            cooldown_seconds=10,
            probe_requests=1,
            now=14.0,
        )
        self.assertTrue(allowed_closed)
        self.assertEqual(reason_closed, "closed")


if __name__ == "__main__":
    unittest.main()
