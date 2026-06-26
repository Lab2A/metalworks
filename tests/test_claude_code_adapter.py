"""Offline tests for the Claude Code (Agent SDK) chat adapter + keyless floor.

Network is blocked (pytest-socket) and the `claude-agent-sdk` package need not be
installed: a fake module is injected into ``sys.modules`` so the adapter binds to
stand-in ``query`` / ``ClaudeAgentOptions`` / ``ResultMessage`` symbols. The real
async→sync bridge (the shared background event loop) IS exercised — the fake
``query`` is a genuine async generator driven through ``run_coroutine_threadsafe``.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType
from typing import Any

import pytest
from pydantic import BaseModel

from metalworks import config
from metalworks.config import _resolve_chat_provider as resolve_provider
from metalworks.errors import MissingExtraError, MissingKeyError


@pytest.fixture(autouse=True)
def _enable_loop_sockets(socket_enabled: None) -> None:
    """The async→sync bridge runs a real asyncio loop whose cross-thread self-pipe
    needs a socketpair. No real network is touched (the SDK is faked); this just
    lifts ``--disable-socket`` for the loopback self-pipe within this module."""


class _Out(BaseModel):
    value: int


def _install_fake_sdk(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result_text: str = "ok",
    structured: dict[str, Any] | None = None,
    is_error: bool = False,
    options_sink: list[dict[str, Any]] | None = None,
) -> ModuleType:
    """Inject a fake ``claude_agent_sdk`` module and return it."""
    mod = ModuleType("claude_agent_sdk")

    class ResultMessage:
        def __init__(self, **kw: Any) -> None:
            self.__dict__.update(kw)

    class ClaudeAgentOptions:
        def __init__(self, **kw: Any) -> None:
            self.kw = kw
            if options_sink is not None:
                options_sink.append(kw)

    async def query(*, prompt: str, options: Any):  # async generator
        yield ResultMessage(
            result=result_text,
            structured_output=structured,
            is_error=is_error,
            usage={"input_tokens": 3, "output_tokens": 5},
        )

    mod.ResultMessage = ResultMessage  # type: ignore[attr-defined]
    mod.ClaudeAgentOptions = ClaudeAgentOptions  # type: ignore[attr-defined]
    mod.query = query  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", mod)
    return mod


def _adapter(monkeypatch: pytest.MonkeyPatch, **kw: Any):
    _install_fake_sdk(monkeypatch, **kw)
    from metalworks.llm.adapters.claude_code import ClaudeCodeChatModel

    return ClaudeCodeChatModel()


# ── adapter behavior ──


def test_complete_text_returns_result(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _adapter(monkeypatch, result_text="Paris.")
    out = model.complete_text(system="s", user="capital of France?")
    assert out.text == "Paris."
    assert out.usage.input_tokens == 3 and out.usage.output_tokens == 5


def test_complete_structured_native(monkeypatch: pytest.MonkeyPatch) -> None:
    """structured_output present → validated directly, no fallback prompt."""
    sink: list[dict[str, Any]] = []
    _install_fake_sdk(monkeypatch, structured={"value": 42}, options_sink=sink)
    from metalworks.llm.adapters.claude_code import ClaudeCodeChatModel

    out = ClaudeCodeChatModel().complete_structured(system="s", user="u", output_model=_Out)
    assert out.value == 42
    # The native structured path set the json_schema output_format.
    assert any(o.get("output_format", {}).get("type") == "json_schema" for o in sink)


def test_complete_structured_falls_back_to_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """structured_output is None → schema-in-prompt ladder parses the JSON text body."""
    model = _adapter(monkeypatch, result_text='{"value": 7}', structured=None)
    out = model.complete_structured(system="s", user="u", output_model=_Out)
    assert out.value == 7


def test_is_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from metalworks.errors import MetalworksError

    model = _adapter(monkeypatch, result_text="boom", is_error=True)
    with pytest.raises(MetalworksError, match="Claude Code reported an error"):
        model.complete_text(system="s", user="u")


def test_non_agentic_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each call disables tools, single-turns, and bypasses permission prompts."""
    sink: list[dict[str, Any]] = []
    _install_fake_sdk(monkeypatch, options_sink=sink)
    from metalworks.llm.adapters.claude_code import ClaudeCodeChatModel

    ClaudeCodeChatModel().complete_text(system="s", user="u")
    assert sink and sink[-1]["allowed_tools"] == []
    assert sink[-1]["max_turns"] == 1
    assert sink[-1]["permission_mode"] == "bypassPermissions"


def test_model_alias_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    sink: list[dict[str, Any]] = []
    _install_fake_sdk(monkeypatch, options_sink=sink)
    from metalworks.llm.adapters.claude_code import ClaudeCodeChatModel

    ClaudeCodeChatModel(model_id="claude-code/opus").complete_text(system="s", user="u")
    assert sink[-1]["model"] == "opus"


def test_missing_extra_when_sdk_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    # A None entry makes `import claude_agent_sdk` raise ImportError.
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    from metalworks.llm.adapters.claude_code import ClaudeCodeChatModel

    with pytest.raises(MissingExtraError):
        ClaudeCodeChatModel()


def test_concurrent_calls_via_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Many sync callers from a thread pool each complete through the shared loop."""
    model = _adapter(monkeypatch, result_text="ok")
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(lambda _i: model.complete_text(system="s", user="u").text, range(12))
        )
    assert results == ["ok"] * 12


# ── keyless floor in config resolution ──

_ALL_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "METALWORKS_MODEL",
    "GOOGLE_GENAI_USE_VERTEXAI",
)


def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env keys, no machine config file leaking a pinned model."""
    for k in _ALL_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(config, "load_config", dict)


def test_floor_engages_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    monkeypatch.setattr(config, "claude_code_available", lambda: True)
    assert resolve_provider(None) == ("claude-code", None)


def test_explicit_key_wins_over_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    monkeypatch.setattr(config, "claude_code_available", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    assert resolve_provider(None) == ("anthropic", None)


def test_no_floor_raises_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    monkeypatch.setattr(config, "claude_code_available", lambda: False)
    with pytest.raises(MissingKeyError):
        resolve_provider(None)


def test_claude_code_ref_routes_native(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    assert resolve_provider("claude-code/opus") == ("claude-code", "opus")
