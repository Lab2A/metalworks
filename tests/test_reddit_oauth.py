"""RedditOAuth tests — respx-mocked httpx, real TokenCipher + MemoryStores.

Covers the four rewrite fixes: timeouts (implicit), invalid_grant→reauth,
empty-refresh rejection, and TokenCipher-backed encryption with a real key.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from metalworks.errors import RateLimitedError, ReauthRequiredError
from metalworks.reddit.oauth import RedditOAuth, TokenBundle, parse_scopes
from metalworks.reddit.ratelimit import RateLimiter
from metalworks.stores import MemoryStores

respx = pytest.importorskip("respx")
pytest.importorskip("cryptography")
from metalworks.stores.crypto import TokenCipher  # noqa: E402

_FIXED = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _cipher() -> TokenCipher:
    from cryptography.fernet import Fernet

    return TokenCipher(key=Fernet.generate_key())


def _oauth(accounts: MemoryStores, cipher: TokenCipher) -> RedditOAuth:
    # sleep is a no-op so 429 backoff doesn't actually wait.
    return RedditOAuth(
        accounts=accounts,
        cipher=cipher,
        client_id="cid",
        client_secret="secret",
        limiter=RateLimiter(sleep=lambda _s: None),
        clock=lambda: _FIXED,
    )


@respx.mock
def test_exchange_code_builds_bundle_with_fitness() -> None:
    respx.post("https://www.reddit.com/api/v1/access_token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "acc1",
                "refresh_token": "ref1",
                "expires_in": 3600,
                "scope": "submit read",
            },
        )
    )
    respx.get("https://oauth.reddit.com/api/v1/me").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "brand_founder",
                "id": "u1",
                "comment_karma": 1200,
                "link_karma": 50,
                "has_verified_email": True,
                "created_utc": _FIXED.timestamp() - 400 * 86400,
            },
        )
    )
    oauth = _oauth(MemoryStores(), _cipher())
    bundle = oauth.exchange_code("code", "https://app/callback")
    assert bundle.username == "brand_founder"
    assert bundle.fitness["comment_karma"] == "1200"
    assert bundle.fitness["verified_email"] == "true"
    assert bundle.fitness["account_age_days"] == "400"
    oauth.close()


@respx.mock
def test_refresh_invalid_grant_raises_reauth() -> None:
    respx.post("https://www.reddit.com/api/v1/access_token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    oauth = _oauth(MemoryStores(), _cipher())
    with pytest.raises(ReauthRequiredError):
        oauth.refresh("revoked-token")
    oauth.close()


def test_store_account_rejects_empty_refresh_token() -> None:
    accounts = MemoryStores()
    cipher = _cipher()
    oauth = _oauth(accounts, cipher)
    # Empty refresh token must be stored as NULL, never encrypted "".
    bundle = TokenBundle(
        access_token="acc", refresh_token=None, expires_in=3600, scope="submit", username="u"
    )
    stored = oauth.store_account(bundle)
    assert stored.encrypted_refresh_token is None
    # Access token round-trips through the cipher.
    assert cipher.decrypt(stored.encrypted_access_token) == "acc"
    assert stored.scopes == ["submit"]
    oauth.close()


@respx.mock
def test_valid_access_token_refreshes_and_persists_when_expired() -> None:
    accounts = MemoryStores()
    cipher = _cipher()
    oauth = _oauth(accounts, cipher)
    # Seed an expired account.
    oauth.store_account(
        TokenBundle(
            access_token="old", refresh_token="ref", expires_in=-100, scope="submit", username="u"
        )
    )
    respx.post("https://www.reddit.com/api/v1/access_token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "new", "expires_in": 3600, "scope": "submit"}
        )
    )
    token = oauth.valid_access_token("u")
    assert token == "new"
    # Persisted: the new access token + a future expiry.
    updated = accounts.get_account("u")
    assert updated is not None
    assert cipher.decrypt(updated.encrypted_access_token) == "new"
    assert updated.token_expires_at == _FIXED.timestamp() + 3600
    oauth.close()


def test_valid_access_token_no_account_or_no_refresh_raises_reauth() -> None:
    accounts = MemoryStores()
    cipher = _cipher()
    oauth = _oauth(accounts, cipher)
    with pytest.raises(ReauthRequiredError):
        oauth.valid_access_token("missing")
    # Expired account with no refresh token → reauth.
    oauth.store_account(
        TokenBundle(
            access_token="a", refresh_token=None, expires_in=-100, scope="submit", username="u"
        )
    )
    with pytest.raises(ReauthRequiredError):
        oauth.valid_access_token("u")
    oauth.close()


@respx.mock
def test_post_comment_parses_id_and_builds_url() -> None:
    accounts = MemoryStores()
    cipher = _cipher()
    oauth = _oauth(accounts, cipher)
    oauth.store_account(
        TokenBundle(
            access_token="acc", refresh_token="r", expires_in=3600, scope="submit", username="u"
        )
    )
    respx.post("https://oauth.reddit.com/api/comment").mock(
        return_value=httpx.Response(
            200, json={"json": {"errors": [], "data": {"things": [{"data": {"id": "abc123"}}]}}}
        )
    )
    url = "https://reddit.com/r/Supplements/comments/p1/title/"
    result = oauth.post_comment(username="u", post_url=url, text="a genuinely helpful reply here")
    assert result.success is True
    assert result.comment_id == "abc123"
    assert result.comment_url == f"{url.rstrip('/')}/abc123/"
    oauth.close()


def test_post_comment_invalid_url() -> None:
    oauth = _oauth(MemoryStores(), _cipher())
    result = oauth.post_comment(username="u", post_url="https://reddit.com/not-a-post", text="x")
    assert result.success is False
    assert "Invalid post URL" in (result.error or "")
    oauth.close()


@respx.mock
def test_429_retries_then_raises_rate_limited() -> None:
    respx.post("https://www.reddit.com/api/v1/access_token").mock(
        return_value=httpx.Response(429, headers={"retry-after": "1"}, json={})
    )
    oauth = _oauth(MemoryStores(), _cipher())
    with pytest.raises(RateLimitedError):
        oauth.refresh("ref")
    oauth.close()


def test_parse_scopes() -> None:
    assert parse_scopes("submit read") == ["submit", "read"]
    assert parse_scopes("") is None
    assert parse_scopes(None) is None
