"""Rate limiter tests with injected clock + sleep (no real time)."""

from __future__ import annotations

from metalworks.reddit.ratelimit import RateLimiter, retry_after_seconds


class _FakeTime:
    """Deterministic clock where sleep advances the clock."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.now += s


def test_burst_then_throttle() -> None:
    ft = _FakeTime()
    rl = RateLimiter(rate_per_sec=1.0, burst=3, clock=ft.clock, sleep=ft.sleep)
    # First 3 acquires drain the burst with no sleep.
    for _ in range(3):
        rl.acquire()
    assert ft.slept == []
    # The 4th must wait ~1s for a token to refill.
    rl.acquire()
    assert ft.slept and abs(sum(ft.slept) - 1.0) < 1e-6


def test_sustained_rate_is_respected() -> None:
    ft = _FakeTime()
    rl = RateLimiter(rate_per_sec=2.0, burst=1, clock=ft.clock, sleep=ft.sleep)
    rl.acquire()  # token 0, no wait
    rl.acquire()  # needs 0.5s at 2/s
    rl.acquire()  # another 0.5s
    assert abs(sum(ft.slept) - 1.0) < 1e-6


def test_observe_headers_holds_until_reset() -> None:
    ft = _FakeTime()
    rl = RateLimiter(rate_per_sec=100.0, burst=100, clock=ft.clock, sleep=ft.sleep)
    # Window exhausted, resets in 10s → next acquire holds ~10s despite a full
    # bucket.
    rl.observe_headers({"x-ratelimit-remaining": "0", "x-ratelimit-reset": "10"})
    rl.acquire()
    assert abs(sum(ft.slept) - 10.0) < 1e-6


def test_observe_headers_noop_when_quota_remains() -> None:
    ft = _FakeTime()
    rl = RateLimiter(rate_per_sec=100.0, burst=100, clock=ft.clock, sleep=ft.sleep)
    rl.observe_headers({"x-ratelimit-remaining": "40", "x-ratelimit-reset": "30"})
    rl.acquire()
    assert ft.slept == []


def test_backoff_holds_all_callers() -> None:
    ft = _FakeTime()
    rl = RateLimiter(rate_per_sec=100.0, burst=100, clock=ft.clock, sleep=ft.sleep)
    rl.backoff(7.0)
    rl.acquire()
    assert abs(sum(ft.slept) - 7.0) < 1e-6


def test_retry_after_parsing() -> None:
    assert retry_after_seconds({"retry-after": "12"}) == 12.0
    assert retry_after_seconds({"x-ratelimit-reset": "8"}) == 8.0
    # Retry-After wins over reset.
    assert retry_after_seconds({"retry-after": "3", "x-ratelimit-reset": "99"}) == 3.0
    assert retry_after_seconds({}, default=4.0) == 4.0
    assert retry_after_seconds({"retry-after": "garbage"}, default=4.0) == 4.0
