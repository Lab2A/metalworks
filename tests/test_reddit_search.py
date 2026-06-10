"""Reddit search tests — pure mappers + the lazy-import guarantee.

Two things are exercised without ever importing redditwarp:

1. The redditwarp-object → contract mappers (`post_from_submission`,
   `comment_from_node`, `author_hash`) are pure attribute readers, so a plain
   stand-in object stands in for a redditwarp model.
2. The module must import cleanly with redditwarp blocked, and `RedditSearch`
   must raise `MissingExtraError` (not ImportError) when redditwarp is absent.
"""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from metalworks.contract import RedditComment, RedditPost
from metalworks.errors import MissingExtraError
from metalworks.reddit.search import (
    RedditSearch,
    author_hash,
    comment_from_node,
    post_from_submission,
)


def _sub(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def test_author_hash_is_stable_and_pseudonymous() -> None:
    h1 = author_hash("spez")
    h2 = author_hash("spez")
    assert h1 == h2
    assert h1 != author_hash("other")
    assert "spez" not in h1  # pseudonymized, not the raw name
    # Deleted/removed/missing collapse to a single bucket distinct from real users.
    assert author_hash("[deleted]") == author_hash(None) == author_hash("[removed]")
    assert author_hash(None) != author_hash("spez")


def test_post_from_submission_maps_fields() -> None:
    raw: Any = SimpleNamespace(
        id36="p1",
        title="Best mechanical keyboards?",
        selftext="looking for tactile",
        permalink="/r/keyboards/comments/p1/best/",
        subreddit=_sub("keyboards"),
        author="alice",
        score=42,
        comment_count=7,
        created_utc=1_700_000_000,
        flair=SimpleNamespace(label="Discussion"),
        removed_by_category=None,
    )
    post = post_from_submission(raw)
    assert isinstance(post, RedditPost)
    assert post.post_id == "p1"
    assert post.subreddit == "keyboards"
    assert post.score == 42
    assert post.num_comments == 7
    assert post.flair == "Discussion"
    assert post.url == "https://reddit.com/r/keyboards/comments/p1/best/"
    assert post.author == "alice"


def test_post_from_submission_skips_removed_and_titleless() -> None:
    removed: Any = SimpleNamespace(title="x", removed_by_category="moderator")
    assert post_from_submission(removed) is None
    titleless: Any = SimpleNamespace(title="", removed_by_category=None)
    assert post_from_submission(titleless) is None


def test_post_from_submission_absolute_permalink_passthrough() -> None:
    raw: Any = SimpleNamespace(
        id36="p2",
        title="hi",
        permalink="https://reddit.com/r/x/comments/p2/hi/",
        subreddit=_sub("x"),
        removed_by_category=None,
    )
    post = post_from_submission(raw)
    assert post is not None
    assert post.url == "https://reddit.com/r/x/comments/p2/hi/"


def test_comment_from_node_maps_and_hashes_author() -> None:
    raw: Any = SimpleNamespace(
        id36="c1",
        body="try the HHKB",
        author="bob",
        permalink="/r/x/comments/p1/_/c1/",
        score=5,
        created_utc=1_700_000_000,
        parent_id="t1_parent",
    )
    comment = comment_from_node(raw, post_id="p1", subreddit="keyboards")
    assert isinstance(comment, RedditComment)
    assert comment.comment_id == "c1"
    assert comment.post_id == "p1"
    assert comment.parent_id == "t1_parent"
    assert comment.author_hash == author_hash("bob")
    assert comment.permalink == "https://reddit.com/r/x/comments/p1/_/c1/"


def test_comment_from_node_skips_empty_body() -> None:
    raw: Any = SimpleNamespace(id36="c2", body="", author="x")
    assert comment_from_node(raw, post_id="p1", subreddit="x") is None


def test_module_imports_without_redditwarp() -> None:
    """Block redditwarp, reimport the module, and assert the class still
    constructs but raises MissingExtraError when it actually needs redditwarp."""
    saved = {k: v for k, v in sys.modules.items() if k.startswith("redditwarp")}
    for k in list(saved):
        del sys.modules[k]
    sys.modules["redditwarp"] = None  # type: ignore[assignment]
    sys.modules["redditwarp.SYNC"] = None  # type: ignore[assignment]
    try:
        import metalworks.reddit.search as search_mod

        search_mod = importlib.reload(search_mod)
        searcher = search_mod.RedditSearch()
        with pytest.raises(MissingExtraError):
            searcher._client()  # noqa: SLF001  (asserting the lazy-import guard)
    finally:
        sys.modules.pop("redditwarp", None)
        sys.modules.pop("redditwarp.SYNC", None)
        sys.modules.update(saved)
        importlib.reload(importlib.import_module("metalworks.reddit.search"))


def test_search_get_post_returns_none_for_bad_url() -> None:
    # No redditwarp needed: an unparseable URL short-circuits before _client().
    searcher = RedditSearch()
    assert searcher.get_post("https://example.com/not-reddit") is None
