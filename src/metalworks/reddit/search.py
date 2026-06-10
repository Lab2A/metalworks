"""Reddit search via redditwarp — posts, subreddits, comments, rules.

Ported from Clique's `services/reddit_search.py`, which constructed a fresh
`redditwarp.SYNC.Client()` per call and returned stringly/dict payloads. Two
structural changes:

1. **redditwarp is the optional `[reddit]` extra and is imported lazily** inside
   `_client()`. There is NO module-level `import redditwarp` — a bare
   `import metalworks` must not require it. On ImportError we raise
   `MissingExtraError("reddit", package="redditwarp")` with the install hint.

2. **Every redditwarp call site is wrapped with `self._limiter.acquire()`.**
   This is coarse — redditwarp owns its own HTTP transport, so we cannot route
   its requests through the limiter directly. Acquiring a token immediately
   before each call is how we govern its request rate today. The future upgrade
   path is to drop redditwarp for OAuth'd `httpx` flowing through the limiter
   (header observation + 429 backoff), as `fetcher.py` already does.

Methods return typed contract models (`RedditPost`, `RedditComment`) where the
mapping is clean. The redditwarp objects themselves are held behind `Any`-typed
locals so pyright strict holds without redditwarp's (absent) type stubs; the
dict→model mapping is factored into pure module functions so it can be tested
with no redditwarp present.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from metalworks.contract import RedditComment, RedditPost
from metalworks.errors import MissingExtraError
from metalworks.reddit.ratelimit import RateLimiter

_POST_ID_RE = re.compile(r"/comments/([a-z0-9]+)/")
_DELETED_MARKERS = ("[deleted]", "[removed]")

# Salt for pseudonymous comment-author hashing. Pseudonymization, not
# anonymization — stable within a corpus so the same author maps to the same id.
_AUTHOR_SALT = "metalworks.reddit.v1"


def author_hash(author: str | None) -> str:
    """Salted sha256 of a comment author — stable pseudonymous id.

    `[deleted]` / `[removed]` / missing authors hash a constant marker so they
    don't all collapse to one bucket with the real authors.
    """
    name = (author or "").strip()
    if not name or name.lower() in _DELETED_MARKERS:
        name = "[deleted]"
    digest = hashlib.sha256(f"{_AUTHOR_SALT}:{name}".encode())
    return digest.hexdigest()[:32]


def _to_datetime(epoch: Any) -> datetime | None:
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(float(epoch), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _post_id_from_url(url: str) -> str | None:
    match = _POST_ID_RE.search(url or "")
    return match.group(1) if match else None


def _subreddit_name(obj: Any) -> str:
    """Extract a subreddit name from a redditwarp submission, tolerating both
    the nested `subreddit.name` object and a flat `subreddit_name` string."""
    sub_obj = getattr(obj, "subreddit", None)
    if sub_obj is not None and hasattr(sub_obj, "name"):
        return str(sub_obj.name)
    return str(getattr(obj, "subreddit_name", "") or "unknown")


def _post_url(obj: Any) -> str:
    permalink = str(getattr(obj, "permalink", "") or "")
    if permalink.startswith(("http://", "https://")):
        return permalink
    return f"https://reddit.com{permalink}"


def post_from_submission(obj: Any) -> RedditPost | None:
    """Map a redditwarp submission → `RedditPost`. None for deleted/empty posts.

    Pure aside from attribute access on the passed object, so it can be unit
    tested with a plain stand-in object — no redditwarp required.
    """
    title = str(getattr(obj, "title", "") or "")
    if getattr(obj, "removed_by_category", None) or not title:
        return None

    post_id = str(getattr(obj, "id36", "") or getattr(obj, "id", "") or "")
    if not post_id:
        post_id = _post_id_from_url(_post_url(obj)) or ""
    if not post_id:
        return None

    selftext = str(getattr(obj, "selftext", "") or getattr(obj, "body", "") or "")
    author = getattr(obj, "author_display_name", None) or getattr(obj, "author", None)
    author_str = str(author) if author else None

    flair_obj = getattr(obj, "flair", None)
    flair: str | None = None
    if flair_obj is not None:
        label = getattr(flair_obj, "label", "") or ""
        flair = str(label) or None

    return RedditPost(
        post_id=post_id,
        subreddit=_subreddit_name(obj),
        title=title,
        selftext=selftext,
        url=_post_url(obj),
        author=author_str,
        score=int(getattr(obj, "score", 0) or 0),
        num_comments=int(getattr(obj, "comment_count", 0) or 0),
        created_utc=_to_datetime(getattr(obj, "created_utc", None)),
        flair=flair,
    )


def comment_from_node(obj: Any, *, post_id: str, subreddit: str) -> RedditComment | None:
    """Map a redditwarp comment object → `RedditComment`. None for empty bodies.

    Author is pseudonymized via `author_hash` (sha256). Pure aside from
    attribute access — testable without redditwarp.
    """
    body = str(getattr(obj, "body", "") or "")
    if not body:
        return None

    comment_id = str(getattr(obj, "id36", "") or getattr(obj, "id", "") or "")
    author = getattr(obj, "author_display_name", None) or getattr(obj, "author", None)
    permalink = str(getattr(obj, "permalink", "") or "")
    if permalink and not permalink.startswith(("http://", "https://")):
        permalink = f"https://reddit.com{permalink}"

    parent = getattr(obj, "parent_id", None)
    return RedditComment(
        comment_id=comment_id,
        post_id=post_id,
        subreddit=subreddit,
        body=body,
        permalink=permalink,
        author_hash=author_hash(str(author) if author else None),
        score=int(getattr(obj, "score", 0) or 0),
        created_utc=_to_datetime(getattr(obj, "created_utc", None)),
        parent_id=str(parent) if parent else None,
    )


class RedditSearch:
    """Search Reddit through redditwarp, returning typed contract models.

    redditwarp is lazy-imported in `_client()`; a `RateLimiter` token is
    acquired before every redditwarp call. See the module docstring for why the
    pacing is coarse and what replaces it.
    """

    def __init__(
        self,
        *,
        limiter: RateLimiter | None = None,
        user_agent: str = "metalworks/0.1",
    ) -> None:
        self._limiter = limiter or RateLimiter()
        self._user_agent = user_agent

    def _client(self) -> Any:
        """Construct a redditwarp SYNC client; raise MissingExtraError if absent.

        Lazy by design: importing this module must never require redditwarp.
        """
        try:
            import redditwarp.SYNC
        except ImportError as exc:
            raise MissingExtraError("reddit", package="redditwarp") from exc
        return redditwarp.SYNC.Client()

    # ── Public API ─────────────────────────────────────────────────────────

    def search_posts(
        self,
        query: str,
        *,
        subreddit: str | None = None,
        limit: int = 15,
        sort: str = "relevance",
        time: str = "week",
    ) -> list[RedditPost]:
        """Search submissions (global or within `subreddit`) → list[RedditPost].

        Merges the source's `search_posts_global` + `_structured` variants into
        one typed method. NSFW and deleted/removed posts are filtered out.
        """
        client = self._client()
        sr = (subreddit or "").strip().lstrip("r/")
        self._limiter.acquire()
        results: Any = client.p.submission.search(
            sr=sr, query=query, sort=sort, time=time, amount=limit
        )

        posts: list[RedditPost] = []
        for raw in results:
            if len(posts) >= limit:
                break
            if getattr(raw, "over18", False) or getattr(raw, "nsfw", False):
                continue
            post = post_from_submission(raw)
            if post is not None:
                posts.append(post)
        return posts

    def subreddit_search(
        self, query: str, *, limit: int = 20, min_subscribers: int = 5000
    ) -> list[str]:
        """Search subreddits → list of names (without 'r/').

        Skips NSFW, non-English, and below-threshold subreddits, mirroring the
        source's filters.
        """
        client = self._client()
        self._limiter.acquire()
        results: Any = client.p.subreddit.search(query=query, amount=limit * 3)

        names: list[str] = []
        for raw in results:
            if len(names) >= limit:
                break
            if getattr(raw, "over18", False):
                continue
            lang = str(getattr(raw, "lang", "") or "")
            if lang and lang.lower() != "en":
                continue
            subscribers = int(getattr(raw, "subscriber_count", 0) or 0)
            if subscribers < min_subscribers:
                continue
            name = getattr(raw, "name", None)
            if name:
                names.append(str(name))
        return names

    def get_post_comments(self, post_url: str, *, limit: int = 10) -> list[RedditComment]:
        """Top-level comments for a post URL/id → list[RedditComment]."""
        post_id = _post_id_from_url(post_url) or post_url
        client = self._client()

        self._limiter.acquire()
        submission: Any = client.p.submission.fetch(post_id)
        subreddit = _subreddit_name(submission)

        self._limiter.acquire()
        comment_tree: Any = client.p.comment_tree.fetch(post_id, limit=limit)

        comments: list[RedditComment] = []
        for node in list(comment_tree.children)[:limit]:
            value = getattr(node, "value", None)
            if value is None or not getattr(value, "body", None):
                continue
            comment = comment_from_node(value, post_id=post_id, subreddit=subreddit)
            if comment is not None:
                comments.append(comment)
        return comments

    def get_post(self, url: str) -> RedditPost | None:
        """Fetch a single submission by URL → RedditPost (None if not found)."""
        post_id = _post_id_from_url(url)
        if not post_id:
            return None
        client = self._client()
        self._limiter.acquire()
        submission: Any = client.p.submission.fetch(post_id)
        if not submission:
            return None
        post = post_from_submission(submission)
        if post is None:
            return None
        # The caller's URL is authoritative for the permalink.
        return post.model_copy(update={"url": url})

    def get_subreddit_rules(self, name: str) -> list[str]:
        """Subreddit rules → list of 'short_name: description' strings."""
        sub = name.strip().lstrip("r/")
        client = self._client()
        self._limiter.acquire()
        rules_data: Any = client.p.subreddit.get_rules(sub)

        rules: list[str] = []
        for rule in rules_data:
            short = str(getattr(rule, "short_name", "") or "")
            desc = str(getattr(rule, "description", "") or "")
            line = f"{short}: {desc}" if short and desc else (short or desc)
            if line:
                rules.append(line)
        return rules
