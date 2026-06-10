"""Inbox classification tests — pure dict→model transforms, no network.

These exercise the classification table (comment_reply / post_reply / dm /
mention / mod), permalink building, and the `inbox_item_from_child` mapping
including [deleted]/empty handling. None of this touches redditwarp or httpx, so
it runs on the bare CI matrix.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from metalworks.contract import InboxItem
from metalworks.reddit.inbox import (
    build_permalink,
    classify_kind,
    inbox_item_from_child,
    persist_inbox,
)
from metalworks.stores.memory import MemoryStores


def _t1(*, parent_id: str, was_comment: bool = True) -> dict[str, Any]:
    return {"kind": "t1", "data": {"parent_id": parent_id, "was_comment": was_comment}}


def _t4(*, subject: str = "hello", distinguished: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {"subject": subject}
    if distinguished is not None:
        data["distinguished"] = distinguished
    return {"kind": "t4", "data": data}


@pytest.mark.parametrize(
    ("child", "expected"),
    [
        (_t1(parent_id="t1_abc"), "comment_reply"),
        (_t1(parent_id="t3_xyz"), "post_reply"),
        (_t1(parent_id="", was_comment=False), "comment_reply"),
        (_t1(parent_id="weird"), "comment_reply"),
        (_t4(subject="username mention"), "mention"),
        (_t4(subject="hi", distinguished="moderator"), "mod"),
        (_t4(subject="just a dm"), "dm"),
        ({"kind": "t3", "data": {}}, None),
        ({"kind": None, "data": {}}, None),
    ],
)
def test_classify_kind_table(child: dict[str, Any], expected: str | None) -> None:
    assert classify_kind(child) == expected


def test_build_permalink_prefers_context() -> None:
    out = build_permalink({"context": "/r/x/comments/p1/_/c1/", "permalink": "/other"})
    assert out == "https://www.reddit.com/r/x/comments/p1/_/c1/"


def test_build_permalink_falls_back_to_permalink_then_inbox() -> None:
    assert build_permalink({"permalink": "/message/messages/abc"}) == (
        "https://www.reddit.com/message/messages/abc"
    )
    assert build_permalink({}) == "https://www.reddit.com/message/inbox/"


def test_inbox_item_from_child_full_mapping() -> None:
    child = {
        "kind": "t1",
        "data": {
            "name": "t1_abc123",
            "parent_id": "t3_post1",
            "author": "alice",
            "subject": "post reply",
            "body": "nice thread",
            "context": "/r/x/comments/post1/_/abc123/",
            "created_utc": 1_700_000_000,
            "new": True,
        },
    }
    item = inbox_item_from_child(child)
    assert isinstance(item, InboxItem)
    assert item.message_id == "t1_abc123"
    assert item.kind == "post_reply"
    assert item.author == "alice"
    assert item.body == "nice thread"
    assert item.permalink == "https://www.reddit.com/r/x/comments/post1/_/abc123/"
    assert item.read is False  # new=True → unread
    assert item.created_utc == datetime.fromtimestamp(1_700_000_000, tz=UTC)


def test_inbox_item_read_flag_when_not_new() -> None:
    child = {
        "kind": "t4",
        "data": {"name": "t4_x", "subject": "dm", "body": "hey", "created_utc": 1.0},
    }
    item = inbox_item_from_child(child)
    assert item is not None
    assert item.kind == "dm"
    assert item.read is True  # no `new` key → already read


def test_inbox_item_deleted_author_and_empty_body() -> None:
    child = {
        "kind": "t1",
        "data": {
            "name": "t1_d",
            "parent_id": "t1_p",
            "author": None,
            "body": None,
            "created_utc": 1.0,
        },
    }
    item = inbox_item_from_child(child)
    assert item is not None
    assert item.author is None
    assert item.body == ""


def test_inbox_item_skips_unclassifiable_and_missing_fields() -> None:
    # Unknown kind → skip.
    assert inbox_item_from_child({"kind": "t6", "data": {"name": "x", "created_utc": 1}}) is None
    # Missing name → skip.
    assert inbox_item_from_child({"kind": "t4", "data": {"created_utc": 1}}) is None
    # Missing created_utc → skip.
    assert inbox_item_from_child({"kind": "t4", "data": {"name": "t4_x"}}) is None


def test_persist_inbox_writes_through_repo() -> None:
    store = MemoryStores()
    items = [
        InboxItem(message_id="t4_1", kind="dm", body="a"),
        InboxItem(message_id="t1_2", kind="comment_reply", body="b"),
    ]
    persist_inbox(store, items)
    listed = store.list_inbox_items()
    assert {i.message_id for i in listed} == {"t4_1", "t1_2"}
