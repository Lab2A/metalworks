"""Reddit engagement core: OAuth, search, metrics, inbox, subreddit intel,
posting, and a deterministic compliance gate.

Everything that talks to Reddit goes through a shared `RateLimiter` (token
bucket + 429/Retry-After backoff) — the source had no client-side rate
limiting, which this fixes.

Usage policy: this is for authentic, disclosed engagement only. The posting
path always runs the compliance gate; fabricated personas/backstories are
out of scope by design.
"""

from metalworks.reddit.compliance import heuristic_check, heuristic_check_post
from metalworks.reddit.fetcher import RedditMetrics, post_id_from_url
from metalworks.reddit.inbox import (
    build_permalink,
    classify_kind,
    fetch_inbox,
    inbox_item_from_child,
    persist_inbox,
)
from metalworks.reddit.oauth import PostResult, RedditOAuth, TokenBundle, parse_scopes
from metalworks.reddit.ratelimit import RateLimiter
from metalworks.reddit.search import (
    RedditSearch,
    author_hash,
    comment_from_node,
    post_from_submission,
)
from metalworks.reddit.subreddit import (
    Cache,
    TTLCache,
    extract_rules_summary,
    fetch_subreddit_intel,
    normalize_submission_type,
)

__all__ = [
    "Cache",
    "PostResult",
    "RateLimiter",
    "RedditMetrics",
    "RedditOAuth",
    "RedditSearch",
    "TTLCache",
    "TokenBundle",
    "author_hash",
    "build_permalink",
    "classify_kind",
    "comment_from_node",
    "extract_rules_summary",
    "fetch_inbox",
    "fetch_subreddit_intel",
    "heuristic_check",
    "heuristic_check_post",
    "inbox_item_from_child",
    "normalize_submission_type",
    "parse_scopes",
    "persist_inbox",
    "post_from_submission",
    "post_id_from_url",
]
