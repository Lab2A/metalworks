"""Per-subreddit intel — description, top-post titles, top comments, rules.

Merges Clique's `subreddit_context.py` (description + top comments) and
`subreddit_submission_rules.py` (the /about-driven rules normalization) into one
`fetch_subreddit_intel` returning the contract `SubredditIntel` model.

Two ports from the source's infrastructure assumptions:

1. **Redis → a pluggable `Cache`.** The source hard-wired a shared Redis client.
   Here `Cache` is a tiny Protocol (`get` / `set`); the default is an in-memory
   `TTLCache`. Redis is just one possible implementation a caller can pass.

2. **redditwarp is lazy + optional.** Same rule as `search.py`: no module-level
   import; `MissingExtraError("reddit")` on ImportError. Every redditwarp call
   is paced with `limiter.acquire()`.

`fetched_at` defaults to `datetime.now(UTC)` but accepts an injectable `clock`
for deterministic tests. (This is library code; the workflow-layer ban on
`Date.now` does not apply here.)
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, cast

from metalworks.contract import SubredditIntel
from metalworks.errors import MissingExtraError
from metalworks.reddit.ratelimit import RateLimiter

if TYPE_CHECKING:
    from collections.abc import Callable

_DESCRIPTION_CHAR_LIMIT = 1500
_TOP_COMMENTS = 5
_DEFAULT_TTL_S = 24 * 3600


class Cache(Protocol):
    """Minimal TTL cache seam. Redis, an LRU, or the default `TTLCache` all fit."""

    def get(self, key: str) -> dict[str, Any] | None: ...

    def set(self, key: str, value: dict[str, Any], ttl_s: int) -> None: ...


class TTLCache:
    """In-memory TTL cache — the zero-infra default `Cache` implementation."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: dict[str, Any], ttl_s: int) -> None:
        self._store[key] = (self._clock() + ttl_s, value)


def normalize_submission_type(raw: Any) -> str | None:
    """Reddit returns 'any' | 'link' | 'self'; tolerate Nones and odd values."""
    if not raw:
        return None
    val = str(raw).strip().lower()
    return val if val in ("any", "link", "self") else None


def extract_rules_summary(rules: list[dict[str, Any]] | list[str]) -> list[str]:
    """Normalize raw rule entries (dicts or strings) into display strings.

    Ported from `subreddit_context._fetch_rules`'s normalization: dicts become
    'short_name: description', strings pass through, each capped at 300 chars,
    up to 8 rules.
    """
    out: list[str] = []
    for rule in rules[:8]:
        if isinstance(rule, str):
            line = rule
        else:
            name = str(rule.get("short_name") or rule.get("name") or "")
            desc = str(rule.get("description") or rule.get("violation_reason") or "")
            line = f"{name}: {desc}" if name and desc else (name or desc)
        if line:
            out.append(line[:300])
    return out


def _client() -> Any:
    """Lazy redditwarp SYNC client; raise MissingExtraError if absent."""
    try:
        import redditwarp.SYNC
    except ImportError as exc:
        raise MissingExtraError("reddit", package="redditwarp") from exc
    return redditwarp.SYNC.Client()


def _fetch_description_and_top(
    client: Any, subreddit: str, limiter: RateLimiter
) -> tuple[str | None, int | None, list[str], list[str]]:
    """Pull (description, subscribers, top_post_titles, top_comments).

    Best-effort: any sub-fetch that fails contributes empty/None rather than
    aborting the whole intel fetch.
    """
    description: str | None = None
    subscribers: int | None = None
    top_titles: list[str] = []
    top_comments: list[str] = []

    limiter.acquire()
    try:
        info: Any = client.p.subreddit.fetch_by_name(subreddit)
    except Exception:
        info = None
    if info is not None:
        raw_desc = getattr(info, "public_description", "") or getattr(info, "description", "") or ""
        description = raw_desc[:_DESCRIPTION_CHAR_LIMIT].strip() or None
        subs = getattr(info, "subscriber_count", None)
        if subs is not None:
            subscribers = int(subs)

    limiter.acquire()
    try:
        top_iter: Any = client.p.subreddit.pull.top(subreddit, amount=1, time="week")
        top_posts = list(top_iter)
    except Exception:
        top_posts = []

    for post in top_posts:
        title = getattr(post, "title", None)
        if title:
            top_titles.append(str(title))
        post_id = getattr(post, "id36", None) or getattr(post, "id", None)
        if not post_id:
            continue
        limiter.acquire()
        comments: list[Any] = []
        try:
            thread: Any = client.p.submission.fetch(post_id)
            raw_comments = getattr(thread, "comments", None)
            if isinstance(raw_comments, list):
                comments = cast("list[Any]", raw_comments)
        except Exception:
            comments = []
        scored: list[tuple[int, str]] = []
        for comment in comments[:30]:
            body = str(getattr(comment, "body", "") or "")
            score = int(getattr(comment, "score", 0) or 0)
            if len(body) > 30 and not body.startswith(("[removed]", "[deleted]")):
                scored.append((score, body))
        scored.sort(key=lambda x: x[0], reverse=True)
        top_comments = [body[:500] for _, body in scored[:_TOP_COMMENTS]]

    return description, subscribers, top_titles, top_comments


def _fetch_rules(client: Any, subreddit: str, limiter: RateLimiter) -> list[str]:
    """Fetch + normalize subreddit rules. Best-effort: [] on any failure."""
    limiter.acquire()
    try:
        rules_data: Any = client.p.subreddit.get_rules(subreddit)
    except Exception:
        return []
    raw: list[dict[str, Any]] = []
    for rule in rules_data:
        raw.append(
            {
                "short_name": getattr(rule, "short_name", "") or "",
                "description": getattr(rule, "description", "") or "",
                "violation_reason": getattr(rule, "violation_reason", "") or "",
            }
        )
    return extract_rules_summary(raw)


def fetch_subreddit_intel(
    name: str,
    *,
    limiter: RateLimiter | None = None,
    user_agent: str = "metalworks/0.1",
    cache: Cache | None = None,
    ttl_s: int = _DEFAULT_TTL_S,
    clock: Callable[[], datetime] | None = None,
) -> SubredditIntel:
    """Fetch community intel for a subreddit → `SubredditIntel`.

    On a cache hit the cached payload is rehydrated into a `SubredditIntel`. On
    a miss, redditwarp (lazy, paced through `limiter`) supplies the description,
    subscriber count, top-post titles, top comments, and rules; the result is
    cached for `ttl_s`. Empty results are not cached so the next call retries.
    """
    _ = user_agent  # redditwarp manages its own transport/user-agent
    lim = limiter or RateLimiter()
    now = (clock or (lambda: datetime.now(UTC)))()
    sub = name.strip().lstrip("r/").lower()
    cache_key = f"metalworks:subintel:{sub}"

    if cache is not None:
        cached = cache.get(cache_key)
        if cached is not None:
            return SubredditIntel.model_validate(cached)

    client = _client()
    description, subscribers, top_titles, _top_comments = _fetch_description_and_top(
        client, sub, lim
    )
    rules = _fetch_rules(client, sub, lim)

    intel = SubredditIntel(
        name=sub,
        title=None,
        description=description,
        subscribers=subscribers,
        rules=rules,
        top_post_titles=top_titles,
        fetched_at=now,
    )

    if cache is not None and (description or rules or top_titles):
        cache.set(cache_key, intel.model_dump(mode="json"), ttl_s)

    return intel
