"""MCP server + tool-body tests (offline).

The tool bodies in metalworks.mcp.tools are plain functions, so they're tested
directly here; the FastMCP registration in metalworks.mcp.server is a thin
wrapper over them. The headline import-safety test proves the module imports
with the `mcp` SDK absent.
"""

from __future__ import annotations

import builtins
import sys
from pathlib import Path
from typing import Any

import pytest

from metalworks.errors import MetalworksError
from metalworks.mcp import tools


def test_server_module_imports_without_mcp_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing the server module must NOT require the `mcp` SDK (lazy import)."""
    # Drop any cached server/mcp modules, then block `mcp` imports and re-import.
    for name in list(sys.modules):
        if name == "mcp" or name.startswith("mcp."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.delitem(sys.modules, "metalworks.mcp.server", raising=False)

    real_import = builtins.__import__

    def _blocked(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError("mcp blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    import importlib

    server_mod = importlib.import_module("metalworks.mcp.server")
    assert server_mod is not None
    # build_server, which needs the SDK, must raise MissingExtraError, not crash.
    from metalworks.errors import MissingExtraError

    with pytest.raises(MissingExtraError):
        server_mod.build_server()


def test_compliance_lint_tool_offline() -> None:
    text = (
        "I had the same problem and switching my evening routine actually fixed it for me "
        "after a couple weeks of consistency."
    )
    result = tools.compliance_lint(text)
    assert "error" not in result
    assert result["pass"] is True
    # A passing lint emits a confirm_token over the exact text.
    assert "confirm_token" in result


def test_compliance_lint_blocks_ai_tells() -> None:
    result = tools.compliance_lint("Great question — check out our product, it's robust!")
    assert result["pass"] is False
    assert "confirm_token" not in result


def test_tier2_missing_key_returns_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Tier-2 tool with no provider key returns a structured error envelope,
    not a raw exception."""
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    result = tools.research_plan_brief("a focus gummy for gen z")
    assert "error" in result
    env = result["error"]
    assert env["error_code"] == "missing_key"
    assert env["fix"]
    assert "API" in env["fix"] or "key" in env["fix"].lower()


def test_discovery_run_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """discovery_run wires chat + a Reddit search into the discovery loop and
    returns gated draft opportunities. Mocked so it stays offline + keyless."""
    from metalworks import config
    from metalworks.contract import RedditPost
    from metalworks.llm import FakeChatModel
    from metalworks.stores import MemoryStores

    class _StubSearch:
        def search_posts(self, query: str, *, subreddit: str | None = None, limit: int = 15):
            return [
                RedditPost(
                    post_id="p1",
                    subreddit="Supplements",
                    title="what helps with the 3pm crash",
                    url="https://reddit.com/r/Supplements/comments/p1/",
                )
            ]

    chat = FakeChatModel()
    monkeypatch.setattr(config, "resolve_chat", lambda *a, **k: chat)
    monkeypatch.setattr(config, "default_store", lambda *a, **k: MemoryStores())
    monkeypatch.setattr("metalworks.reddit.RedditSearch", lambda *a, **k: _StubSearch())

    result = tools.discovery_run(["3pm energy crash"], max_opportunities=5)
    # Either produces opportunities or a clean envelope — never a raw exception.
    assert "opportunities" in result or "error" in result


def test_posting_blocked_without_allow_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("METALWORKS_ALLOW_POSTING", raising=False)
    text = "A perfectly fine and sufficiently long human-sounding reply about my own experience."
    token = tools.compliance_lint(text)["confirm_token"]
    result = tools.reddit_post_comment("https://reddit.com/r/x/comments/abc123/t/", text, token)
    assert "error" in result
    assert result["error"]["error_code"] == "missing_key"  # ALLOW_POSTING gate


def test_posting_rejects_bad_confirm_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METALWORKS_ALLOW_POSTING", "1")
    text = "A perfectly fine and sufficiently long human-sounding reply about my own experience."
    result = tools.reddit_post_comment(
        "https://reddit.com/r/x/comments/abc123/t/", text, "not-the-real-token"
    )
    assert "error" in result
    assert result["error"]["error_code"] == "confirm_token_invalid"


def test_posting_rejects_token_for_different_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METALWORKS_ALLOW_POSTING", "1")
    text_a = "A perfectly fine and sufficiently long human-sounding reply about experience one."
    token_a = tools.compliance_lint(text_a)["confirm_token"]
    text_b = "A different but also perfectly fine and sufficiently long human-sounding reply two."
    # Token from text_a must not authorize posting text_b.
    result = tools.reddit_post_comment("https://reddit.com/r/x/comments/abc123/t/", text_b, token_a)
    assert result["error"]["error_code"] == "confirm_token_invalid"


def test_posting_refuses_on_compliance_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METALWORKS_ALLOW_POSTING", "1")
    bad = "Great question — check out our product, our product is robust!"
    # No valid token exists for blocked text (lint emits none), so even a fake
    # token can't get past the confirm gate — but assert the compliance path too
    # by forging the (deterministic) token and checking the gate still blocks.
    forged = tools._confirm_token_for(bad)  # noqa: SLF001 - intentionally forging to test the gate
    result = tools.reddit_post_comment("https://reddit.com/r/x/comments/abc123/t/", bad, forged)
    assert result["error"]["error_code"] == "compliance_block"


def test_corpus_stats_offline(tmp_path: Path) -> None:
    result = tools.corpus_stats(str(tmp_path / "store.db"))
    assert "error" not in result
    assert result["total_runs"] == 0


def test_research_get_report_not_found(tmp_path: Path) -> None:
    result = tools.research_get_report("nope", str(tmp_path / "store.db"))
    assert result["error"]["error_code"] == "not_found"


def test_serve_sse_refuses_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("METALWORKS_MCP_TOKEN", raising=False)
    from metalworks.mcp import server

    with pytest.raises(MetalworksError) as exc:
        server.serve(transport="sse")
    assert "token" in exc.value.message.lower()


def test_build_server_registers_tools() -> None:
    pytest.importorskip("mcp")
    from metalworks.mcp import server

    built = server.build_server()
    assert built is not None


def test_research_background_job_completes(tmp_path: Path) -> None:
    """The research_start/status/result job pattern runs on a thread, persists to
    the RunRepo, and reaches a terminal status — exercised with the in-memory
    pipeline path (no corpus → empty report) and a directly-built RunRepo."""
    import uuid

    from metalworks.contract import ResearchBrief, TargetSubreddit
    from metalworks.embeddings import FakeEmbedding
    from metalworks.llm import FakeChatModel
    from metalworks.mcp.jobs import start_research_job
    from metalworks.research.deps import ResearchDeps
    from metalworks.stores import MemoryStores

    pytest.importorskip("duckdb")
    from metalworks.research.arctic import ArcticReader
    from sample_corpus import SAMPLE_SUBREDDIT, write_sample_corpus

    root = write_sample_corpus(tmp_path / "corpus")
    store = MemoryStores()
    reader = ArcticReader(data_root=str(root), probe_sleep_s=0.0)
    deps = ResearchDeps(
        chat=FakeChatModel(), embeddings=FakeEmbedding(), corpus=store, reader=reader
    )
    brief = ResearchBrief(
        brief_id="job-brief",
        question="demand for a focus supplement?",
        decision_context="ctx",
        success_criteria=["s"],
        must_address=["m"],
        target_subreddits=[TargetSubreddit(name=SAMPLE_SUBREDDIT, rationale="core")],
        web_research_directions=[],
        time_window_months=1,
        relevance_rubric="r",
    )
    run_id = str(uuid.uuid4())
    thread = start_research_job(run_id=run_id, deps=deps, brief=brief, runs=store)
    thread.join(timeout=30)
    reader.close()

    run = store.get_run(run_id)
    assert run is not None
    assert run.status in ("complete", "failed")
    assert run.status == "complete", run.error
