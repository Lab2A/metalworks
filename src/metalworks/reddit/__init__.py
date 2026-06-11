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
from metalworks.reddit.fetcher import RedditMetrics
from metalworks.reddit.inbox import fetch_inbox
from metalworks.reddit.oauth import PostResult, RedditOAuth, TokenBundle
from metalworks.reddit.ratelimit import RateLimiter
from metalworks.reddit.search import RedditSearch
from metalworks.reddit.subreddit import Cache, TTLCache, fetch_subreddit_intel

# Public surface: the clients you construct (RedditSearch, RedditOAuth,
# RateLimiter, the injectable Cache/TTLCache), the functions you call
# (fetch_inbox, fetch_subreddit_intel, heuristic_check[_post]), and the result
# types you handle (PostResult, TokenBundle, RedditMetrics). The node→model
# transforms and URL/scope parsers (post_from_submission, build_permalink,
# parse_scopes, …) are internal plumbing — import them from their submodules
# (metalworks.reddit.search / .inbox / .oauth / .subreddit) if you need them.
__all__ = [
    "Cache",
    "PostResult",
    "RateLimiter",
    "RedditMetrics",
    "RedditOAuth",
    "RedditSearch",
    "TTLCache",
    "TokenBundle",
    "fetch_inbox",
    "fetch_subreddit_intel",
    "heuristic_check",
    "heuristic_check_post",
]
