"""RedditMetrics tests — respx-mocked httpx, no real network.

Covers metric parsing, header observation, the 429 → backoff → retry →
RateLimitedError path, and 401/403 → ReauthRequiredError. No redditwarp here:
this module is pure httpx (a core dependency).
"""

from __future__ import annotations

import httpx
import pytest
import respx

from metalworks.errors import RateLimitedError, ReauthRequiredError
from metalworks.reddit.fetcher import RedditMetrics, post_id_from_url
from metalworks.reddit.ratelimit import RateLimiter


class _SpyLimiter(RateLimiter):
    """RateLimiter that records observe_headers / backoff calls."""

    def __init__(self) -> None:
        super().__init__(rate_per_sec=1000.0, burst=1000, sleep=lambda _s: None)
        self.observed: list[dict[str, str]] = []
        self.backoffs: list[float] = []

    def observe_headers(self, headers: object) -> None:  # type: ignore[override]
        self.observed.append(dict(headers))  # type: ignore[arg-type]
        super().observe_headers(headers)  # type: ignore[arg-type]

    def backoff(self, seconds: float) -> None:
        self.backoffs.append(seconds)
        super().backoff(seconds)


_OAUTH = "https://oauth.reddit.com"


def test_post_id_from_url() -> None:
    assert post_id_from_url("https://reddit.com/r/x/comments/p1/title/") == "p1"
    assert post_id_from_url("garbage") is None
    assert post_id_from_url("") is None


@respx.mock
def test_fetch_post_metrics_parses() -> None:
    respx.get(f"{_OAUTH}/comments/p1.json").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "data": {
                        "children": [{"data": {"score": 99, "num_comments": 12, "author": "a"}}]
                    }
                },
                {"data": {"children": []}},
            ],
            headers={"X-Ratelimit-Remaining": "500", "X-Ratelimit-Reset": "60"},
        )
    )
    limiter = _SpyLimiter()
    metrics = RedditMetrics(limiter=limiter)
    out = metrics.fetch_post_metrics(access_token="tok", post_id="p1")
    assert out["post_upvotes"] == 99
    assert out["post_comments"] == 12
    assert out["post_author"] == "a"
    # Headers were fed to the limiter.
    assert limiter.observed and limiter.observed[0]["x-ratelimit-remaining"] == "500"


@respx.mock
def test_fetch_comment_metrics_parses_replies_and_depth() -> None:
    respx.get(f"{_OAUTH}/comments/p1/_/c1.json").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"data": {"children": []}},
                {
                    "data": {
                        "children": [
                            {
                                "data": {
                                    "score": 7,
                                    "depth": 2,
                                    "replies": {"data": {"children": [{}, {}, {}]}},
                                }
                            }
                        ]
                    }
                },
            ],
        )
    )
    out = RedditMetrics(limiter=_SpyLimiter()).fetch_comment_metrics(
        access_token="tok", comment_id="c1", post_id="p1"
    )
    assert out["comment_upvotes"] == 7
    assert out["comment_replies"] == 3
    assert out["comment_position"] == 3  # depth 2 + 1


@respx.mock
def test_fetch_subreddit_info_parses() -> None:
    respx.get(f"{_OAUTH}/r/keyboards/about.json").mock(
        return_value=httpx.Response(
            200, json={"data": {"subscribers": 1234, "active_user_count": 56}}
        )
    )
    out = RedditMetrics(limiter=_SpyLimiter()).fetch_subreddit_info(
        access_token="tok", subreddit="r/Keyboards"
    )
    assert out == {"subscribers": 1234, "active_users": 56}


@respx.mock
def test_429_backs_off_then_raises_rate_limited() -> None:
    respx.get(f"{_OAUTH}/comments/p1.json").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "2"})
    )
    limiter = _SpyLimiter()
    with pytest.raises(RateLimitedError):
        RedditMetrics(limiter=limiter).fetch_post_metrics(access_token="tok", post_id="p1")
    # Backoff was invoked for the advertised window before giving up.
    assert limiter.backoffs and limiter.backoffs[0] == pytest.approx(2.0)


@respx.mock
def test_429_then_success_recovers() -> None:
    route = respx.get(f"{_OAUTH}/comments/p1.json")

    def _resp(request: httpx.Request) -> httpx.Response:
        if route.call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json=[{"data": {"children": [{"data": {"score": 3, "num_comments": 0}}]}}, {}],
        )

    route.mock(side_effect=_resp)
    out = RedditMetrics(limiter=_SpyLimiter()).fetch_post_metrics(access_token="tok", post_id="p1")
    assert out["post_upvotes"] == 3


@respx.mock
def test_403_raises_reauth_required() -> None:
    respx.get(f"{_OAUTH}/comments/p1.json").mock(return_value=httpx.Response(403))
    with pytest.raises(ReauthRequiredError):
        RedditMetrics(limiter=_SpyLimiter()).fetch_post_metrics(access_token="tok", post_id="p1")
