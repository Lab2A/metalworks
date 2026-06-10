"""Live Reddit metrics via the OAuth-authenticated API (oauth.reddit.com).

Ported from Clique's `services/reddit_fetcher.py`. Two deliberate changes from
the source:

1. **Tokens are injected, never resolved.** The source reached into Supabase to
   look up an account's OAuth token per call (`_resolve_access_token`). Here the
   caller passes `access_token` explicitly — this module has no opinion about
   where credentials live, and stays free of any storage dependency.
2. **Every request flows through a `RateLimiter`.** The source had no
   client-side pacing. We `acquire()` a token before each call, feed Reddit's
   `X-Ratelimit-*` headers back into the limiter on every response, and on a 429
   `backoff()` for the advertised window before a bounded retry — raising
   `RateLimitedError` once retries are exhausted.

Pure `httpx` (a core dependency); no `requests`, no redditwarp. Always uses
oauth.reddit.com with a Bearer token — the source's public-endpoint fallback is
dropped because cloud egress IPs get 403'd there anyway, and this library never
guesses at unauthenticated access.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, cast

import httpx

from metalworks.errors import RateLimitedError, ReauthRequiredError
from metalworks.reddit.ratelimit import RateLimiter, retry_after_seconds

if TYPE_CHECKING:
    from collections.abc import Mapping

_OAUTH_BASE = "https://oauth.reddit.com"
_TIMEOUT_S = 15.0
_MAX_RETRIES = 3

_POST_ID_RE = re.compile(r"/comments/([a-z0-9]+)/")


def post_id_from_url(url: str) -> str | None:
    """Extract the bare base36 post id from a Reddit thread URL."""
    if not url:
        return None
    match = _POST_ID_RE.search(url)
    return match.group(1) if match else None


# ── Strict-safe JSON narrowing ─────────────────────────────────────────────
# `resp.json()` is typed `Any`. Under pyright strict, chaining `.get()` off an
# `Any` leaks "partially unknown" types everywhere. These helpers narrow once,
# at the boundary, into concrete `dict[str, Any]` / `list[Any]` so the rest of
# the parsing is fully typed.


def _as_dict(value: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return cast("list[Any]", value) if isinstance(value, list) else []


def _children(listing: Any) -> list[Any]:
    """Pull `data.children` (a Reddit Listing) as a concrete list."""
    return _as_list(_as_dict(_as_dict(listing).get("data")).get("children"))


class RedditMetrics:
    """Reads live post / comment / subreddit metrics from oauth.reddit.com.

    Tokens are passed per call. A shared `RateLimiter` paces every request and
    absorbs Reddit's rate-limit headers; on 429 we back off and retry up to
    `_MAX_RETRIES` before raising `RateLimitedError`.
    """

    def __init__(
        self,
        *,
        limiter: RateLimiter | None = None,
        user_agent: str = "metalworks/0.1",
    ) -> None:
        self._limiter = limiter or RateLimiter()
        self._user_agent = user_agent

    # ── HTTP core ──────────────────────────────────────────────────────────

    def _get_json(
        self,
        path: str,
        *,
        access_token: str,
        params: Mapping[str, str | int] | None = None,
    ) -> Any:
        """GET <path> from oauth.reddit.com with Bearer auth.

        Paces through the limiter, observes rate-limit headers, and retries a
        bounded number of times on 429 (backing off for the advertised window)
        before raising RateLimitedError. Returns parsed JSON.
        """
        headers = {
            "Authorization": f"bearer {access_token}",
            "User-Agent": self._user_agent,
        }
        merged: dict[str, str | int] = {"raw_json": 1}
        if params:
            merged.update(params)

        url = f"{_OAUTH_BASE}{path}"
        last_retry_after: float | None = None
        for _attempt in range(_MAX_RETRIES):
            self._limiter.acquire()
            resp = httpx.get(url, headers=headers, params=merged, timeout=_TIMEOUT_S)
            self._limiter.observe_headers(resp.headers)

            if resp.status_code == 429:
                last_retry_after = retry_after_seconds(resp.headers)
                self._limiter.backoff(last_retry_after)
                continue
            if resp.status_code in (401, 403):
                raise ReauthRequiredError()
            resp.raise_for_status()
            return resp.json()

        raise RateLimitedError("Reddit", retry_after_s=last_retry_after)

    # ── Public metrics API ─────────────────────────────────────────────────

    def fetch_comment_metrics(
        self, *, access_token: str, comment_id: str, post_id: str
    ) -> dict[str, Any]:
        """Upvotes, direct-reply count, and thread depth for one comment.

        `/comments/<post>/_/<comment>.json` returns
        ``[post_listing, comment_listing]``; the targeted comment is the first
        child of the comment listing.
        """
        payload = self._get_json(
            f"/comments/{post_id}/_/{comment_id}.json",
            access_token=access_token,
            params={"limit": 1},
        )
        payload_list = _as_list(payload)
        if len(payload_list) < 2:
            return {}
        children = _children(payload_list[1])
        if not children:
            return {}
        comment = _as_dict(_as_dict(children[0]).get("data"))
        if not comment:
            return {}

        replies_obj = comment.get("replies")
        comment_replies = len(_children(replies_obj)) if isinstance(replies_obj, dict) else 0

        # Reddit: depth 0 = top-level. Clique's schema: 1 = top-level. +1 aligns.
        depth = comment.get("depth")
        comment_position = (depth + 1) if isinstance(depth, int) else 1

        return {
            "comment_id": comment_id,
            "comment_url": f"https://reddit.com/comments/{post_id}/_/{comment_id}",
            "comment_upvotes": int(comment.get("score") or 0),
            "comment_replies": comment_replies,
            "comment_position": comment_position,
        }

    def fetch_post_metrics(self, *, access_token: str, post_id: str) -> dict[str, Any]:
        """Upvotes, comment count, and author for one submission."""
        payload = self._get_json(
            f"/comments/{post_id}.json",
            access_token=access_token,
            params={"limit": 1},
        )
        payload_list = _as_list(payload)
        if not payload_list:
            return {}
        post_children = _children(payload_list[0])
        if not post_children:
            return {}
        post = _as_dict(_as_dict(post_children[0]).get("data"))
        if not post:
            return {}

        return {
            "post_id": post_id,
            "post_upvotes": int(post.get("score") or 0),
            "post_comments": int(post.get("num_comments") or 0),
            "post_author": post.get("author") or "",
            "created_utc": post.get("created_utc"),
        }

    def fetch_subreddit_info(self, *, access_token: str, subreddit: str) -> dict[str, Any]:
        """Subscriber + active-user counts for a subreddit."""
        sub = subreddit.strip().lstrip("r/").lower()
        if not sub:
            return {}
        payload = self._get_json(f"/r/{sub}/about.json", access_token=access_token)
        data = _as_dict(_as_dict(payload).get("data"))
        return {
            "subscribers": int(data.get("subscribers") or 0),
            "active_users": int(data.get("active_user_count") or 0),
        }
