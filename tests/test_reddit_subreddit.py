"""Subreddit intel tests — pure normalizers + the pluggable cache.

The redditwarp-dependent fetch path is not exercised here (it would need
redditwarp, absent on the bare CI matrix). Instead we cover the pure pieces —
`normalize_submission_type`, `extract_rules_summary`, the `TTLCache`, and the
cache-hit short-circuit of `fetch_subreddit_intel` (which returns before
touching redditwarp). The inbox `fetch_inbox` httpx path is covered via respx.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from metalworks.contract import InboxItem, SubredditIntel
from metalworks.reddit.inbox import fetch_inbox
from metalworks.reddit.ratelimit import RateLimiter
from metalworks.reddit.subreddit import (
    TTLCache,
    extract_rules_summary,
    fetch_subreddit_intel,
    normalize_submission_type,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("any", "any"),
        ("LINK", "link"),
        (" self ", "self"),
        ("restricted", None),
        (None, None),
        ("", None),
    ],
)
def test_normalize_submission_type(raw: object, expected: str | None) -> None:
    assert normalize_submission_type(raw) == expected


def test_extract_rules_summary_dicts_and_strings() -> None:
    rules = [
        {"short_name": "No spam", "description": "Don't spam"},
        {"short_name": "Be civil"},
        "Plain string rule",
        {"violation_reason": "Off-topic"},
    ]
    out = extract_rules_summary(rules)
    assert out == ["No spam: Don't spam", "Be civil", "Plain string rule", "Off-topic"]


def test_extract_rules_summary_caps_at_eight_and_truncates() -> None:
    rules = [f"rule {i}" for i in range(20)]
    out = extract_rules_summary(rules)
    assert len(out) == 8
    long = [{"short_name": "x", "description": "y" * 500}]
    assert len(extract_rules_summary(long)[0]) == 300


def test_ttlcache_get_set_and_expiry() -> None:
    clock = {"t": 0.0}
    cache = TTLCache(clock=lambda: clock["t"])
    cache.set("k", {"v": 1}, ttl_s=10)
    assert cache.get("k") == {"v": 1}
    clock["t"] = 11.0  # past TTL
    assert cache.get("k") is None
    assert cache.get("missing") is None


def test_fetch_subreddit_intel_cache_hit_skips_redditwarp() -> None:
    """A populated cache returns without ever importing redditwarp, so this
    passes on the bare matrix."""
    cache = TTLCache(clock=lambda: 0.0)
    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    cached = SubredditIntel(
        name="saas",
        description="founders",
        subscribers=10_000,
        rules=["No self-promo"],
        top_post_titles=["Launch day"],
        fetched_at=fixed,
    )
    cache.set("metalworks:subintel:saas", cached.model_dump(mode="json"), ttl_s=3600)

    out = fetch_subreddit_intel("r/SaaS", cache=cache, clock=lambda: fixed)
    assert isinstance(out, SubredditIntel)
    assert out.name == "saas"
    assert out.subscribers == 10_000
    assert out.rules == ["No self-promo"]
    assert out.fetched_at == fixed


_INBOX = "https://oauth.reddit.com/message/inbox"


def _fast_limiter() -> RateLimiter:
    return RateLimiter(rate_per_sec=1000.0, burst=1000, sleep=lambda _s: None)


@respx.mock
def test_fetch_inbox_classifies_children() -> None:
    respx.get(_INBOX).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "children": [
                        {
                            "kind": "t1",
                            "data": {
                                "name": "t1_a",
                                "parent_id": "t3_p",
                                "body": "reply",
                                "created_utc": 1_700_000_000,
                            },
                        },
                        {
                            "kind": "t4",
                            "data": {
                                "name": "t4_b",
                                "subject": "username mention",
                                "body": "you were mentioned",
                                "created_utc": 1_700_000_001,
                            },
                        },
                        {"kind": "t6", "data": {"name": "t6_x", "created_utc": 1}},
                    ]
                }
            },
        )
    )
    items = fetch_inbox(access_token="tok", limiter=_fast_limiter())
    assert [i.kind for i in items] == ["post_reply", "mention"]
    assert all(isinstance(i, InboxItem) for i in items)


@respx.mock
def test_fetch_inbox_empty_payload() -> None:
    respx.get(_INBOX).mock(return_value=httpx.Response(200, json={"data": {"children": []}}))
    assert fetch_inbox(access_token="tok", limiter=_fast_limiter()) == []
