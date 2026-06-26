"""Offline tests for the Claude Code keyless SearchProvider + search floor.

The `claude-agent-sdk` package need not be installed: a fake module is injected
into ``sys.modules``. The real async→sync bridge (the shared background loop) is
exercised, so this re-enables the loopback self-pipe socket (no real network).
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest

from metalworks import config
from metalworks.config import resolve_search
from metalworks.errors import MissingExtraError

# A WebSearch tool-result body in the real shape: a `Links: [{title,url}]` array.
_REAL = (
    'Web search results for query: "x"\n\nLinks: '
    '[{"title":"A","url":"https://a.com/x"},{"title":"B","url":"https://b.com/y"}]'
)
_SEARCH_KEYS = ("EXA_API_KEY", "TAVILY_API_KEY", "PARALLEL_API_KEY", "FIRECRAWL_API_KEY")


@pytest.fixture(autouse=True)
def _enable_loop_sockets(socket_enabled: None) -> None:
    """The shared async→sync bridge needs a loopback self-pipe socketpair; no
    real network is touched (the SDK is faked)."""


def _install_fake_sdk(
    monkeypatch: pytest.MonkeyPatch,
    *,
    structured: dict[str, Any] | None,
    tool_text: str = _REAL,
) -> None:
    mod = ModuleType("claude_agent_sdk")

    class ResultMessage:
        def __init__(self, **kw: Any) -> None:
            self.__dict__.update(kw)

    class ClaudeAgentOptions:
        def __init__(self, **kw: Any) -> None:
            self.kw = kw

    class ToolResultBlock:
        def __init__(self, content: str) -> None:
            self.content = content

    class _Carrier:
        def __init__(self, content: list[Any]) -> None:
            self.content = content

    async def query(*, prompt: str, options: Any):  # async generator
        yield _Carrier([ToolResultBlock(tool_text)])
        yield ResultMessage(result="done", structured_output=structured, is_error=False)

    mod.query = query  # type: ignore[attr-defined]
    mod.ClaudeAgentOptions = ClaudeAgentOptions  # type: ignore[attr-defined]
    mod.ResultMessage = ResultMessage  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", mod)


def _provider(monkeypatch: pytest.MonkeyPatch, **kw: Any):  # -> ClaudeCodeSearch
    _install_fake_sdk(monkeypatch, **kw)
    from metalworks.search.adapters.claude_code import ClaudeCodeSearch

    return ClaudeCodeSearch()


# ── provider behavior ──


def test_search_keeps_real_urls_drops_invented(monkeypatch: pytest.MonkeyPatch) -> None:
    """A model result whose URL isn't a real WebSearch hit is dropped (no-cite-no-claim)."""
    structured = {
        "results": [
            {"url": "https://a.com/x", "title": "A", "snippet": "real one"},
            {"url": "https://hallucinated.invented/z", "title": "Z", "snippet": "fake"},
        ]
    }
    results = _provider(monkeypatch, structured=structured).search(query="x", max_results=5)
    urls = [r.url for r in results]
    assert urls == ["https://a.com/x"]  # the invented URL was dropped
    assert results[0].snippet == "real one"


def test_search_respects_max_results(monkeypatch: pytest.MonkeyPatch) -> None:
    structured = {
        "results": [
            {"url": "https://a.com/x", "title": "A", "snippet": "s"},
            {"url": "https://b.com/y", "title": "B", "snippet": "s"},
        ]
    }
    results = _provider(monkeypatch, structured=structured).search(query="x", max_results=1)
    assert len(results) == 1


def test_search_falls_back_to_bare_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    """No structured output → still return the real hit URLs (bare), never invented ones."""
    results = _provider(monkeypatch, structured=None).search(query="x", max_results=5)
    assert {r.url for r in results} == {"https://a.com/x", "https://b.com/y"}
    assert all(r.snippet == "" for r in results)


def test_missing_extra_when_sdk_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    from metalworks.search.adapters.claude_code import ClaudeCodeSearch

    with pytest.raises(MissingExtraError):
        ClaudeCodeSearch()


# ── keyless search floor ──


def test_search_floor_engages_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in _SEARCH_KEYS:
        monkeypatch.delenv(k, raising=False)
    _install_fake_sdk(monkeypatch, structured=None)
    monkeypatch.setattr(config, "_claude_code_available", lambda: True)
    from metalworks.search.adapters.claude_code import ClaudeCodeSearch

    assert isinstance(resolve_search(), ClaudeCodeSearch)


def test_search_floor_absent_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in _SEARCH_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(config, "_claude_code_available", lambda: False)
    assert resolve_search() is None
