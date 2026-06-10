"""Client-side rate limiting for Reddit calls.

Two cooperating pieces:

- `RateLimiter`: a thread-safe token bucket. `acquire()` blocks until a token
  is available, so concurrent callers (the discovery loop runs threads) stay
  under a sustained request rate. It also absorbs Reddit's `X-Ratelimit-*`
  response headers — when Reddit says the window is nearly exhausted, the
  limiter pauses until the window resets rather than charging into a 429.
- `retry_after_seconds`: parse a 429's `Retry-After` / `X-Ratelimit-Reset`
  into a sleep duration.

Clock and sleep are injectable so the whole thing is unit-testable without
real time.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping


class RateLimiter:
    """Token bucket with optional header-driven pacing.

    `rate_per_sec` is the sustained fill rate; `burst` is the bucket capacity
    (max tokens available at once). Reddit's OAuth limit is ~60 requests/min,
    so the default 1 req/s with a small burst stays comfortably under it.
    """

    def __init__(
        self,
        *,
        rate_per_sec: float = 1.0,
        burst: int = 5,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be positive")
        self._rate = rate_per_sec
        self._capacity = float(max(1, burst))
        self._tokens = self._capacity
        self._clock = clock
        self._sleep = sleep
        self._last = clock()
        # When header pacing kicks in, no token is granted before this time.
        self._hold_until = 0.0
        self._lock = threading.Lock()

    def _refill_locked(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last = now

    def acquire(self) -> None:
        """Block until one token is available, then consume it."""
        while True:
            with self._lock:
                self._refill_locked()
                now = self._clock()
                hold = max(0.0, self._hold_until - now)
                if hold <= 0 and self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Wait for whichever is longer: the header hold, or the time
                # for the bucket to earn one token.
                wait = hold if hold > 0 else (1.0 - self._tokens) / self._rate
            self._sleep(max(wait, 0.0))

    def observe_headers(self, headers: Mapping[str, str]) -> None:
        """Pace from Reddit's `X-Ratelimit-*` headers.

        When the remaining quota in the current window hits zero, hold all
        callers until the window resets — preempts the 429 entirely.
        """
        remaining = _float_header(headers, "x-ratelimit-remaining")
        reset = _float_header(headers, "x-ratelimit-reset")
        if remaining is None:
            return
        with self._lock:
            if remaining <= 0 and reset is not None and reset > 0:
                self._hold_until = self._clock() + reset

    def backoff(self, seconds: float) -> None:
        """Hold all callers for `seconds` (used on a 429)."""
        with self._lock:
            self._hold_until = self._clock() + max(0.0, seconds)


def _float_header(headers: Mapping[str, str], key: str) -> float | None:
    # httpx headers are case-insensitive, but accept plain dicts too.
    raw = headers.get(key)
    if raw is None and not isinstance(headers, dict):
        raw = headers.get(key.title())
    if raw is None:
        return None
    try:
        return float(str(raw).strip())
    except ValueError:
        return None


def retry_after_seconds(headers: Mapping[str, str], *, default: float = 5.0) -> float:
    """How long to wait after a 429, from `Retry-After` or `X-Ratelimit-Reset`."""
    for key in ("retry-after", "x-ratelimit-reset"):
        val = _float_header(headers, key)
        if val is not None and val >= 0:
            return val
    return default
