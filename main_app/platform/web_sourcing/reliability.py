from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
import random
import time
from typing import Callable, TypeVar


T = TypeVar("T")


def is_transient_error(error: Exception | None) -> bool:
    if error is None:
        return False
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return True
    message = " ".join(str(error).split()).lower()
    if not message:
        return False
    transient_markers = (
        "timeout",
        "timed out",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "connection refused",
        "503",
        "502",
        "500",
        "429",
        "408",
    )
    return any(marker in message for marker in transient_markers)


@dataclass(frozen=True)
class RetryPolicy:
    retry_count: int = 2
    base_delay_ms: int = 250
    max_delay_ms: int = 1500
    jitter_ms: int = 100

    def run(
        self,
        operation: Callable[[], T],
        *,
        on_retry: Callable[[int, Exception], None] | None = None,
        retryable: Callable[[Exception], bool] = is_transient_error,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> T:
        attempt = 0
        while True:
            try:
                return operation()
            except Exception as exc:
                if attempt >= max(0, int(self.retry_count)) or not retryable(exc):
                    raise
                attempt += 1
                if on_retry is not None:
                    on_retry(attempt, exc)
                delay_ms = min(
                    max(0, int(self.max_delay_ms)),
                    max(0, int(self.base_delay_ms)) * (2 ** (attempt - 1)),
                )
                jitter_ms = random.randint(0, max(0, int(self.jitter_ms)))
                sleep_seconds = max(0.0, float(delay_ms + jitter_ms) / 1000.0)
                sleep_fn(sleep_seconds)


class DomainRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, domain: str, *, per_minute: int, now: float | None = None) -> bool:
        normalized_domain = " ".join(str(domain).split()).strip().lower()
        if not normalized_domain:
            return True
        if int(per_minute) <= 0:
            return True
        current = float(now) if now is not None else time.time()
        window_start = current - 60.0
        with self._lock:
            bucket = self._events[normalized_domain]
            while bucket and bucket[0] <= window_start:
                bucket.popleft()
            if len(bucket) >= int(per_minute):
                return False
            bucket.append(current)
            return True


@dataclass
class _ProviderCircuitState:
    state: str = "closed"
    consecutive_failures: int = 0
    opened_at: float = 0.0
    half_open_remaining: int = 0


class ProviderCircuitBreakerRegistry:
    def __init__(self) -> None:
        self._states: dict[str, _ProviderCircuitState] = {}
        self._lock = Lock()

    def can_attempt(
        self,
        provider_key: str,
        *,
        enabled: bool,
        cooldown_seconds: int,
        probe_requests: int,
        now: float | None = None,
    ) -> tuple[bool, str]:
        if not enabled:
            return True, "disabled"
        normalized = " ".join(str(provider_key).split()).strip().lower()
        if not normalized:
            return False, "invalid_provider_key"
        current = float(now) if now is not None else time.time()
        with self._lock:
            state = self._states.setdefault(normalized, _ProviderCircuitState())
            if state.state == "open":
                cooldown = max(1, int(cooldown_seconds))
                if (current - state.opened_at) < cooldown:
                    return False, "circuit_open"
                state.state = "half_open"
                state.half_open_remaining = max(1, int(probe_requests))
            if state.state == "half_open":
                if state.half_open_remaining <= 0:
                    return False, "half_open_blocked"
                state.half_open_remaining -= 1
                return True, "half_open_probe"
            return True, "closed"

    def record_success(self, provider_key: str, *, enabled: bool) -> None:
        if not enabled:
            return
        normalized = " ".join(str(provider_key).split()).strip().lower()
        if not normalized:
            return
        with self._lock:
            state = self._states.setdefault(normalized, _ProviderCircuitState())
            state.state = "closed"
            state.consecutive_failures = 0
            state.opened_at = 0.0
            state.half_open_remaining = 0

    def record_failure(
        self,
        provider_key: str,
        *,
        enabled: bool,
        error_threshold: int,
        now: float | None = None,
    ) -> None:
        if not enabled:
            return
        normalized = " ".join(str(provider_key).split()).strip().lower()
        if not normalized:
            return
        threshold = max(1, int(error_threshold))
        current = float(now) if now is not None else time.time()
        with self._lock:
            state = self._states.setdefault(normalized, _ProviderCircuitState())
            state.consecutive_failures += 1
            if state.state == "half_open" or state.consecutive_failures >= threshold:
                state.state = "open"
                state.opened_at = current
                state.half_open_remaining = 0

    def state_snapshot(self) -> dict[str, str]:
        with self._lock:
            return {
                provider: state.state
                for provider, state in self._states.items()
            }

    def failure_snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                provider: int(state.consecutive_failures)
                for provider, state in self._states.items()
            }
