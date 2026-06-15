"""Metalworks facade tests — all offline (pytest-socket enforces --disable-socket).

Covers:

1. Lazy construction: ``Metalworks()`` with no API keys never raises, and the
   namespaces are reachable without resolving a provider.
2. ``MissingKeyError`` surfaces only on a real-key path (a research call with no
   provider key), not at construction.
3. The facade threads one deps object through the pillar arc (offline, with
   injected Fake models over a local corpus).
4. ``.reddit.post`` refuses a compliance-blocked draft and audit-logs it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metalworks import Metalworks
from metalworks.errors import MissingKeyError

_CHAT_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")


def _clear_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (*_CHAT_KEYS, "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)


def test_construct_with_no_keys_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_keys(monkeypatch)
    mw = Metalworks()  # nothing resolved eagerly
    assert mw.reddit is mw.reddit  # namespace is memoized, no provider needed
    assert mw.discovery is mw.discovery


def test_research_without_key_raises_missing_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_keys(monkeypatch)
    with pytest.raises(MissingKeyError):
        Metalworks().research("Is there demand for X?", subreddits=["test"])


def test_post_refuses_and_audits_blocked_draft(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_keys(monkeypatch)
    import json

    from metalworks.reddit import audit

    log_path = tmp_path / "post-log.jsonl"
    monkeypatch.setattr(audit, "DEFAULT_POST_LOG", log_path)

    # An em-dash is a deterministic compliance block, so posting never reaches
    # OAuth (no Reddit creds needed) and the attempt is audit-logged.
    blocked = "This is a genuinely helpful and specific reply — you should try it sometime."
    result = Metalworks().reddit.post(
        "https://reddit.com/r/test/comments/abc123/x/", blocked, username="me"
    )
    assert result.success is False
    assert "compliance gate" in (result.error or "").lower()

    lines = log_path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["action"] == "post_blocked"
    assert record["success"] is False


def test_append_post_log_writes_a_json_line(tmp_path: Path) -> None:
    import json

    from metalworks.reddit.audit import append_post_log

    log_path = tmp_path / "log.jsonl"
    append_post_log({"action": "post", "success": True}, path=log_path)
    append_post_log({"action": "post", "success": False}, path=log_path)
    lines = log_path.read_text().splitlines()
    assert len(lines) == 2
    assert all("ts" in json.loads(line) for line in lines)


def test_pillar_exports_are_importable_from_the_package() -> None:
    # The keystone every downstream pillar needs, and the surface literal a typed
    # caller must name, must both import from their stable package roots.
    from metalworks.contract import SurfaceKind  # noqa: F401
    from metalworks.research import build_positioning_brief  # noqa: F401


def test_facade_runs_the_pillar_arc_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The full arc threads ONE deps object through the pillars via the facade —
    # no hand-built ResearchDeps, no reaching into private internals. Fake models
    # are injected through the public constructor over a local sample corpus.
    pytest.importorskip("duckdb")
    pytest.importorskip("rank_bm25")
    monkeypatch.chdir(tmp_path)
    _clear_keys(monkeypatch)
    from metalworks.contract import ChannelPlan, ContentPlan, PositioningBrief
    from metalworks.embeddings import FakeEmbedding
    from metalworks.llm import FakeChatModel
    from metalworks.research import ResearchDeps
    from metalworks.research.arctic import ArcticReader
    from metalworks.stores import MemoryStores
    from sample_corpus import SAMPLE_SUBREDDIT, write_sample_corpus

    class _NoComments:  # offline comment source — yields nothing, touches no network
        def comments_for_links(self, link_ids: object) -> object:
            return iter([])

    write_sample_corpus(tmp_path / "corpus")
    reader = ArcticReader(data_root=str(tmp_path / "corpus"), probe_sleep_s=0.0)
    mw = Metalworks(
        chat=FakeChatModel(),
        fast_chat=FakeChatModel(),
        embeddings=FakeEmbedding(),
        reader=reader,
        comments=_NoComments(),
        store=MemoryStores(),
    )
    try:
        research = mw.research(
            "Is there demand for a focus supplement?",
            subreddits=[SAMPLE_SUBREDDIT],
            time_window_months=1,  # the sample corpus is a single month
        )
    finally:
        reader.close()

    assert isinstance(mw.deps, ResearchDeps)  # public escape hatch
    assert isinstance(mw.positioning(research), PositioningBrief)  # Pillar B via facade
    assert isinstance(mw.content_plan(research), ContentPlan)  # Pillar G via facade
    assert isinstance(mw.channel_plan(research), ChannelPlan)  # Pillar F (deterministic) via facade
