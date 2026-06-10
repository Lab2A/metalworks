"""Reddit OAuth + posting — rewritten on httpx with typed errors.

This is a deliberate rewrite of Clique's `reddit_oauth.py`, not a port. The
source had four problems this fixes (per the plan review):

1. No HTTP timeouts anywhere → a stalled Reddit endpoint hung the caller
   forever. Every call here carries an explicit timeout.
2. Token refresh raised a bare `Exception` with no `invalid_grant`
   discrimination → callers couldn't tell "retry later" from "the user
   revoked access". Refresh now raises `ReauthRequiredError` on invalid_grant.
3. Empty refresh tokens were happily encrypted and stored (Reddit omits the
   refresh token without `duration=permanent`), producing a row that decrypts
   to "" and fails later. We reject/NULL empty refresh tokens.
4. A missing encryption key was silently replaced with an ephemeral one,
   making stored tokens unrecoverable after restart. Encryption is delegated
   to `TokenCipher`, whose key lifecycle persists or hard-fails.

Storage is `AccountRepo` (no Supabase, no Clerk, no plan caps). Tokens are
encrypted at rest via `TokenCipher`. Every Reddit call goes through the shared
`RateLimiter`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from metalworks.errors import (
    MissingKeyError,
    RateLimitedError,
    ReauthRequiredError,
    RedditError,
)
from metalworks.reddit.ratelimit import RateLimiter, retry_after_seconds
from metalworks.stores.repos import StoredRedditAccount

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from metalworks.stores.crypto import TokenCipher
    from metalworks.stores.repos import AccountRepo

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_OAUTH_BASE = "https://oauth.reddit.com"
_EXPIRY_BUFFER_S = 300  # refresh 5 minutes before actual expiry
_MAX_429_RETRIES = 2


@dataclass(frozen=True)
class TokenBundle:
    """The result of an OAuth exchange/refresh, plus account fitness facts."""

    access_token: str
    refresh_token: str | None
    expires_in: int
    scope: str
    username: str | None = None
    reddit_user_id: str | None = None
    fitness: dict[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True)
class PostResult:
    success: bool
    comment_id: str | None = None
    comment_url: str | None = None
    username: str | None = None
    error: str | None = None


def _now_ts(clock: Callable[[], datetime]) -> float:
    return clock().timestamp()


class RedditOAuth:
    """OAuth lifecycle + posting for a single Reddit app's connected accounts."""

    def __init__(
        self,
        *,
        accounts: AccountRepo,
        cipher: TokenCipher,
        client_id: str | None = None,
        client_secret: str | None = None,
        user_agent: str = "metalworks/0.1",
        timeout_s: float = 30.0,
        limiter: RateLimiter | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        cid = client_id or os.environ.get("REDDIT_CLIENT_ID")
        secret = client_secret or os.environ.get("REDDIT_CLIENT_SECRET")
        if not cid or not secret:
            raise MissingKeyError("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET", provider="Reddit")
        self._cid = cid
        self._secret = secret
        self._accounts = accounts
        self._cipher = cipher
        self._ua = user_agent
        self._timeout = timeout_s
        self._limiter = limiter or RateLimiter()
        if clock is None:
            from datetime import UTC, datetime

            def _default_clock() -> datetime:
                return datetime.now(UTC)

            clock = _default_clock
        self._clock = clock
        self._http = httpx.Client(timeout=timeout_s, headers={"User-Agent": user_agent})

    def close(self) -> None:
        self._http.close()

    # ── HTTP helper with rate limiting + 429 backoff ──

    def _request(
        self,
        method: str,
        url: str,
        *,
        auth: tuple[str, str] | None = None,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
    ) -> httpx.Response:
        attempt = 0
        while True:
            self._limiter.acquire()
            resp = self._http.request(method, url, auth=auth, headers=headers, data=data)
            self._limiter.observe_headers(resp.headers)
            if resp.status_code == 429 and attempt < _MAX_429_RETRIES:
                self._limiter.backoff(retry_after_seconds(resp.headers))
                attempt += 1
                continue
            if resp.status_code == 429:
                raise RateLimitedError("Reddit", retry_after_s=retry_after_seconds(resp.headers))
            return resp

    # ── OAuth flows ──

    def exchange_code(self, code: str, redirect_uri: str) -> TokenBundle:
        resp = self._request(
            "POST",
            _TOKEN_URL,
            auth=(self._cid, self._secret),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        if not resp.is_success:
            raise RedditError(f"Token exchange failed: {resp.text[:200]}", status=resp.status_code)
        payload: dict[str, Any] = resp.json()
        access = str(payload["access_token"])
        me = self.fetch_me(access)
        return TokenBundle(
            access_token=access,
            refresh_token=_clean_refresh(payload.get("refresh_token")),
            expires_in=int(payload.get("expires_in", 3600)),
            scope=str(payload.get("scope", "")),
            username=_str_or_none(me.get("name")),
            reddit_user_id=_str_or_none(me.get("id")),
            fitness=_extract_fitness(me, clock=self._clock),
        )

    def refresh(self, refresh_token: str) -> TokenBundle:
        resp = self._request(
            "POST",
            _TOKEN_URL,
            auth=(self._cid, self._secret),
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        if not resp.is_success:
            body = resp.text.lower()
            if resp.status_code in (400, 401) and "invalid_grant" in body:
                raise ReauthRequiredError()
            raise RedditError(f"Token refresh failed: {resp.text[:200]}", status=resp.status_code)
        payload: dict[str, Any] = resp.json()
        return TokenBundle(
            access_token=str(payload["access_token"]),
            refresh_token=_clean_refresh(payload.get("refresh_token")),
            expires_in=int(payload.get("expires_in", 3600)),
            scope=str(payload.get("scope", "")),
        )

    def fetch_me(self, access_token: str) -> dict[str, Any]:
        """`/api/v1/me`. Returns {} on failure (fitness is best-effort)."""
        resp = self._request(
            "GET",
            f"{_OAUTH_BASE}/api/v1/me",
            headers={"Authorization": f"bearer {access_token}"},
        )
        if not resp.is_success:
            return {}
        out: dict[str, Any] = resp.json()
        return out

    # ── Account persistence ──

    def store_account(
        self,
        bundle: TokenBundle,
        *,
        account_type: str | None = None,
        background: str | None = None,
    ) -> StoredRedditAccount:
        """Persist a connected account, tokens encrypted at rest.

        An empty refresh token is stored as NULL, never as encrypted "" — the
        source bug that produced rows which decrypt to empty and fail refresh.
        """
        if not bundle.username:
            raise RedditError("Cannot store account without a resolved username.")
        meta = dict(bundle.fitness)
        if account_type:
            meta["account_type"] = account_type
        if background:
            meta["background"] = background  # authentic only — see USAGE_POLICY
        if bundle.scope:
            meta["reddit_user_id"] = bundle.reddit_user_id or ""
        account = StoredRedditAccount(
            username=bundle.username,
            encrypted_access_token=self._cipher.encrypt(bundle.access_token),
            encrypted_refresh_token=(
                self._cipher.encrypt(bundle.refresh_token) if bundle.refresh_token else None
            ),
            scopes=[s for s in bundle.scope.split() if s],
            token_expires_at=_now_ts(self._clock) + bundle.expires_in,
            metadata=meta,
        )
        self._accounts.save_account(account)
        return account

    def valid_access_token(self, username: str) -> str:
        """A non-expired access token for `username`, refreshing + persisting
        if needed. Raises ReauthRequiredError when re-auth is required."""
        account = self._accounts.get_account(username)
        if account is None:
            raise ReauthRequiredError(username)

        expires_at = account.token_expires_at or 0.0
        if _now_ts(self._clock) < (expires_at - _EXPIRY_BUFFER_S):
            return self._cipher.decrypt(account.encrypted_access_token)

        if not account.encrypted_refresh_token:
            raise ReauthRequiredError(username)
        refresh_token = self._cipher.decrypt(account.encrypted_refresh_token)
        bundle = self.refresh(refresh_token)  # raises ReauthRequiredError on invalid_grant

        updated = account.model_copy(
            update={
                "encrypted_access_token": self._cipher.encrypt(bundle.access_token),
                "token_expires_at": _now_ts(self._clock) + bundle.expires_in,
                "scopes": [s for s in bundle.scope.split() if s] or account.scopes,
            }
        )
        self._accounts.save_account(updated)
        return bundle.access_token

    # ── Posting ──

    def post_comment(self, *, username: str, post_url: str, text: str) -> PostResult:
        """Reply to a submission identified by its URL."""
        match = re.search(r"/comments/([a-z0-9]+)/", post_url)
        if not match:
            return PostResult(success=False, error="Invalid post URL")
        return self._post_to_thing(
            username=username, thing_id=f"t3_{match.group(1)}", body=text, post_url=post_url
        )

    def post_reply(self, *, username: str, parent_thing_id: str, body: str) -> PostResult:
        """Reply to any Reddit thing by fullname (t1_/t3_/t4_) — e.g. inbox replies."""
        if not parent_thing_id:
            return PostResult(success=False, error="parent_thing_id required")
        if not body.strip():
            return PostResult(success=False, error="body required")
        return self._post_to_thing(username=username, thing_id=parent_thing_id, body=body)

    def _post_to_thing(
        self, *, username: str, thing_id: str, body: str, post_url: str | None = None
    ) -> PostResult:
        try:
            access_token = self.valid_access_token(username)
        except ReauthRequiredError as e:
            return PostResult(success=False, error=e.message)
        resp = self._request(
            "POST",
            f"{_OAUTH_BASE}/api/comment",
            headers={"Authorization": f"bearer {access_token}"},
            data={"api_type": "json", "thing_id": thing_id, "text": body},
        )
        if not resp.is_success:
            return PostResult(success=False, error=f"Reddit API error: {resp.status_code}")
        result: dict[str, Any] = resp.json()
        json_block: dict[str, Any] = result.get("json", {}) or {}
        data_block: dict[str, Any] = json_block.get("data", {}) or {}
        things: list[Any] = list(data_block.get("things") or [])
        comment_id: str | None = None
        if things:
            first: dict[str, Any] = things[0].get("data", {}) or {}
            comment_id = _str_or_none(first.get("id"))
        comment_url = f"{post_url.rstrip('/')}/{comment_id}/" if (post_url and comment_id) else None
        return PostResult(
            success=True, comment_id=comment_id, comment_url=comment_url, username=username
        )


# ── Pure helpers ───────────────────────────────────────────────────────────


def _clean_refresh(raw: object) -> str | None:
    """Reddit omits the refresh token without duration=permanent; treat empty
    as None so we never store an encrypted empty string."""
    if isinstance(raw, str) and raw.strip():
        return raw
    return None


def _str_or_none(raw: object) -> str | None:
    return str(raw) if raw not in (None, "") else None


def _extract_fitness(me: dict[str, Any], *, clock: Callable[[], datetime]) -> dict[str, str]:
    """Normalize /api/v1/me into posting-fitness facts (stored as strings)."""
    if not me:
        return {}
    out: dict[str, str] = {}
    if (ck := me.get("comment_karma")) is not None:
        out["comment_karma"] = str(ck)
    if (lk := me.get("link_karma")) is not None:
        out["link_karma"] = str(lk)
    if (ve := me.get("has_verified_email")) is not None:
        out["verified_email"] = str(bool(ve)).lower()
    created = me.get("created_utc")
    if isinstance(created, int | float) and created > 0:
        age_s = _now_ts(clock) - created
        if age_s >= 0:
            out["account_age_days"] = str(int(age_s // 86400))
    return out


def parse_scopes(scope_string: str | None) -> list[str] | None:
    """Granted scopes come space-separated; None distinguishes 'not captured'
    from 'no scopes'."""
    if not scope_string:
        return None
    return [s for s in scope_string.split() if s]


__all__ = ["PostResult", "RedditOAuth", "TokenBundle", "parse_scopes"]
