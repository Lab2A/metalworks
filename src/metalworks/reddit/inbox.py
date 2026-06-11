"""Reddit inbox: classify /message/inbox entries into typed `InboxItem`s.

Inbox classification, keeping only the PURE
dict→model transforms — the Supabase reads/writes, PostHog emission, the cron
fan-out, triage, and retention cleanup are all left behind (they belong to the
host application, not this library).

The classification (`classify_kind`, `build_permalink`, `inbox_item_from_child`)
is pure: dict in, contract `InboxItem` out, no network. `fetch_inbox` is the
thin networked wrapper that GETs `/message/inbox` (pure `httpx`, paced through a
`RateLimiter`) and runs each child through the classifier. Persistence is a
one-liner delegating to whatever `InboxRepo` the caller supplies.

The kind vocabulary — comment_reply / post_reply / dm / mention / mod — matches
the `InboxItem` contract exactly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx

from metalworks.contract import InboxItem
from metalworks.errors import RateLimitedError, ReauthRequiredError
from metalworks.reddit.ratelimit import RateLimiter, retry_after_seconds

if TYPE_CHECKING:
    from collections.abc import Sequence

    from metalworks.stores.repos import InboxRepo

InboxKind = Literal["comment_reply", "post_reply", "dm", "mention", "mod"]

_INBOX_URL = "https://oauth.reddit.com/message/inbox"
_TIMEOUT_S = 15.0
_MAX_RETRIES = 3
_INBOX_LIMIT = 100


# Narrow `Any` JSON once at the boundary so pyright strict stays clean. (See the
# matching helpers in fetcher.py for the same rationale.)


def _as_dict(value: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return cast("list[Any]", value) if isinstance(value, list) else []


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def classify_kind(child: dict[str, Any]) -> InboxKind | None:
    """Map one `/message/inbox` child to a kind, or None if unrecognized.

    Decision tree (audit-friendly):

    - t1 (comments):
        parent_id starts 't1_' → comment_reply
        parent_id starts 't3_' → post_reply
        (missing was_comment / odd parent) → comment_reply
    - t4 (private messages):
        subject == 'username mention' → mention
        distinguished == 'moderator'  → mod
        otherwise                      → dm

    None signals the caller to skip the entry instead of storing garbage.
    """
    kind_prefix = child.get("kind")
    data = _as_dict(child.get("data"))

    if kind_prefix == "t1":
        parent_id = _str(data.get("parent_id"))
        if not data.get("was_comment", True):
            return "comment_reply"
        if parent_id.startswith("t1_"):
            return "comment_reply"
        if parent_id.startswith("t3_"):
            return "post_reply"
        return "comment_reply"

    if kind_prefix == "t4":
        subject = _str(data.get("subject")).strip().lower()
        if subject == "username mention":
            return "mention"
        distinguished = _str(data.get("distinguished")).strip().lower()
        if distinguished == "moderator":
            return "mod"
        return "dm"

    return None


def build_permalink(data: dict[str, Any]) -> str | None:
    """Build a stable Reddit URL for a message.

    Comments carry a `context` (post permalink + comment id); some carry a bare
    `permalink`. DMs have neither — fall back to the inbox URL so a 'View on
    Reddit' link still goes somewhere useful.
    """
    context = _str(data.get("context"))
    if context:
        return f"https://www.reddit.com{context}"
    permalink = _str(data.get("permalink"))
    if permalink:
        return f"https://www.reddit.com{permalink}"
    return "https://www.reddit.com/message/inbox/"


def inbox_item_from_child(
    child: dict[str, Any], *, account_username: str | None = None
) -> InboxItem | None:
    """Translate one inbox listing child into a contract `InboxItem`.

    Returns None when the entry can't be classified or lacks a stable id /
    timestamp. `account_username` is accepted for parity with the source's
    account-scoping but is not stored on the contract model.
    """
    _ = account_username  # reserved; the contract model is account-agnostic
    data = _as_dict(child.get("data"))
    kind = classify_kind(child)
    if kind is None:
        return None

    message_id = _str(data.get("name"))  # e.g. t1_abc123 or t4_xyz789
    if not message_id:
        return None

    created_utc = data.get("created_utc")
    if created_utc is None:
        return None
    try:
        created_dt = datetime.fromtimestamp(float(created_utc), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None

    return InboxItem(
        message_id=message_id,
        kind=kind,
        author=_str(data.get("author")) or None,
        subject=_str(data.get("subject")) or None,
        body=_str(data.get("body")),
        permalink=build_permalink(data),
        created_utc=created_dt,
        read=not bool(data.get("new", False)),
    )


def persist_inbox(repo: InboxRepo, items: Sequence[InboxItem]) -> None:
    """Upsert classified items through whatever `InboxRepo` the caller supplies."""
    repo.upsert_inbox_items(items)


def fetch_inbox(
    *,
    access_token: str,
    limiter: RateLimiter | None = None,
    user_agent: str = "metalworks/0.1",
    limit: int = _INBOX_LIMIT,
) -> list[InboxItem]:
    """GET /message/inbox and classify every entry into `InboxItem`s.

    Pure `httpx` paced through `limiter`; observes rate-limit headers and backs
    off + retries on 429 before raising `RateLimitedError`. 401/403 →
    `ReauthRequiredError` (commonly a missing `privatemessages` scope).
    """
    lim = limiter or RateLimiter()
    headers = {
        "Authorization": f"bearer {access_token}",
        "User-Agent": user_agent,
    }
    params: dict[str, str | int] = {"limit": limit, "raw_json": 1}

    payload: Any = None
    last_retry_after: float | None = None
    for _attempt in range(_MAX_RETRIES):
        lim.acquire()
        resp = httpx.get(_INBOX_URL, headers=headers, params=params, timeout=_TIMEOUT_S)
        lim.observe_headers(resp.headers)
        if resp.status_code == 429:
            last_retry_after = retry_after_seconds(resp.headers)
            lim.backoff(last_retry_after)
            continue
        if resp.status_code in (401, 403):
            raise ReauthRequiredError()
        resp.raise_for_status()
        payload = resp.json()
        break
    else:
        raise RateLimitedError("Reddit", retry_after_s=last_retry_after)

    children = _as_list(_as_dict(payload).get("children")) or _as_list(
        _as_dict(_as_dict(payload).get("data")).get("children")
    )

    items: list[InboxItem] = []
    for child in children:
        item = inbox_item_from_child(_as_dict(child))
        if item is not None:
            items.append(item)
    return items
