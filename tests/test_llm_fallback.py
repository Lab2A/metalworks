"""FallbackChatModel — opt-in ordered failover over a chain of ChatModels.

All offline. Working links are :class:`FakeChatModel`s; failing links are thin
stubs that raise a chosen error, so we exercise the retryable / non-retryable
decision and the all-fail path without any network or provider SDK.
"""

from __future__ import annotations

from typing import ClassVar, TypeVar

import pytest
from pydantic import BaseModel

from metalworks import config
from metalworks.errors import MissingKeyError, RateLimitedError, StructuredOutputError
from metalworks.llm import (
    PROTOCOL_VERSION,
    ChatCapabilities,
    ChatModel,
    FakeChatModel,
    FallbackChatModel,
    TextResult,
    Usage,
)

T = TypeVar("T", bound=BaseModel)


class Verdict(BaseModel):
    keep: bool
    reason: str


class _RaisingChatModel:
    """A ChatModel whose every completion raises ``exc``. Records `.attempts`."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION

    def __init__(self, exc: Exception, *, model_id: str = "raise/chat") -> None:
        self.model_id = model_id
        self.capabilities = ChatCapabilities(native_structured=True)
        self._exc = exc
        self.attempts = 0

    def complete_text(self, **_: object) -> TextResult:
        self.attempts += 1
        raise self._exc

    def complete_structured(self, *, output_model: type[T], **_: object) -> T:
        self.attempts += 1
        raise self._exc


def test_raising_stub_satisfies_protocol() -> None:
    assert isinstance(_RaisingChatModel(RateLimitedError("x")), ChatModel)


# ── complete_text ────────────────────────────────────────────────────────────


def test_text_falls_through_rate_limit_to_working_fallback() -> None:
    primary = _RaisingChatModel(RateLimitedError("primary"), model_id="primary")
    fallback = FakeChatModel(model_id="fallback")
    fallback.text_responses.append("from fallback")
    chain = FallbackChatModel([primary, fallback])

    out = chain.complete_text(system="s", user="u")

    assert out.text == "from fallback"
    assert primary.attempts == 1  # primary was tried exactly once, then skipped
    assert fallback.calls[0]["kind"] == "text"


def test_text_non_retryable_raises_immediately_without_trying_fallbacks() -> None:
    primary = _RaisingChatModel(MissingKeyError("ANTHROPIC_API_KEY"), model_id="primary")
    fallback = FakeChatModel(model_id="fallback")
    fallback.text_responses.append("should never run")
    chain = FallbackChatModel([primary, fallback])

    with pytest.raises(MissingKeyError):
        chain.complete_text(system="s", user="u")

    assert fallback.calls == []  # the fallback was never consulted


def test_text_all_fail_raises_last_error() -> None:
    first = _RaisingChatModel(RateLimitedError("first"), model_id="first")
    last = _RaisingChatModel(RateLimitedError("LAST"), model_id="last")
    chain = FallbackChatModel([first, last])

    with pytest.raises(RateLimitedError) as exc:
        chain.complete_text(system="s", user="u")

    assert "LAST" in str(exc.value)  # the *last* model's error propagates
    assert first.attempts == 1
    assert last.attempts == 1


# ── complete_structured ──────────────────────────────────────────────────────


def test_structured_falls_through_rate_limit_to_working_fallback() -> None:
    primary = _RaisingChatModel(RateLimitedError("primary"), model_id="primary")
    fallback = FakeChatModel(model_id="fallback").script(
        Verdict, Verdict(keep=True, reason="from fallback")
    )
    chain = FallbackChatModel([primary, fallback])

    out = chain.complete_structured(system="s", user="u", output_model=Verdict)

    assert out.reason == "from fallback"
    assert primary.attempts == 1


def test_structured_non_retryable_raises_immediately() -> None:
    # A StructuredOutputError is a capability error, NOT retryable: a different
    # model won't fix a schema the caller asked for, so we re-raise at once.
    primary = _RaisingChatModel(StructuredOutputError("primary", "bad schema"), model_id="primary")
    fallback = FakeChatModel(model_id="fallback").script(
        Verdict, Verdict(keep=False, reason="never")
    )
    chain = FallbackChatModel([primary, fallback])

    with pytest.raises(StructuredOutputError):
        chain.complete_structured(system="s", user="u", output_model=Verdict)

    assert fallback.calls == []


def test_structured_all_fail_raises_last_error() -> None:
    first = _RaisingChatModel(RateLimitedError("first"), model_id="first")
    last = _RaisingChatModel(RateLimitedError("LAST"), model_id="last")
    chain = FallbackChatModel([first, last])

    with pytest.raises(RateLimitedError) as exc:
        chain.complete_structured(system="s", user="u", output_model=Verdict)

    assert "LAST" in str(exc.value)


# ── duck-typed transient transport error (no SDK) ────────────────────────────


class _Overloaded(Exception):
    """A raw provider-shaped 529 that escaped an adapter's own backoff."""

    status_code = 529


def test_text_falls_through_raw_provider_rate_limit() -> None:
    # is_rate_limit_error recognises status_code 529 → retryable → fall through.
    primary = _RaisingChatModel(_Overloaded(), model_id="primary")
    fallback = FakeChatModel(model_id="fallback")
    fallback.text_responses.append("recovered")
    chain = FallbackChatModel([primary, fallback])

    out = chain.complete_text(system="s", user="u")

    assert out.text == "recovered"


# ── metadata ─────────────────────────────────────────────────────────────────


def test_model_id_and_capabilities_mirror_primary() -> None:
    primary = FakeChatModel(model_id="primary/x")
    fb = FakeChatModel(model_id="fallback/y")
    chain = FallbackChatModel([primary, fb])

    assert chain.model_id == "primary/x|+1 fallbacks"
    assert chain.capabilities is primary.capabilities
    assert chain.protocol_version == PROTOCOL_VERSION


def test_single_model_id_has_no_suffix() -> None:
    chain = FallbackChatModel([FakeChatModel(model_id="solo")])
    assert chain.model_id == "solo"


def test_empty_chain_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        FallbackChatModel([])


def test_first_success_skips_remaining_models() -> None:
    primary = FakeChatModel(model_id="primary")
    primary.text_responses.append("ok")
    never = _RaisingChatModel(RateLimitedError("never"), model_id="never")
    chain = FallbackChatModel([primary, never])

    out = chain.complete_text(system="s", user="u")

    assert out.text == "ok"
    assert never.attempts == 0  # short-circuited on first success


# ── opt-in wiring: no fallbacks → no wrapper / unchanged behaviour ────────────

_CHAT_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
)


def _clear_chat_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _CHAT_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_resolve_chat_chain_no_fallbacks_returns_bare_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    pytest.importorskip("anthropic")
    monkeypatch.chdir(tmp_path)  # type: ignore[arg-type]
    _clear_chat_keys(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    model = config.resolve_chat_chain()

    # No fallbacks configured → exactly the single resolved model, no wrapper.
    assert not isinstance(model, FallbackChatModel)
    assert type(model).__name__ == "AnthropicChatModel"


def test_resolve_chat_chain_wraps_only_when_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    pytest.importorskip("anthropic")
    pytest.importorskip("openai")
    monkeypatch.chdir(tmp_path)  # type: ignore[arg-type]
    _clear_chat_keys(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    chain = config.resolve_chat_chain(fallback_models=["openai/gpt-5"])

    assert isinstance(chain, FallbackChatModel)
    assert len(chain.models) == 2
    assert type(chain.models[0]).__name__ == "AnthropicChatModel"
    assert type(chain.models[1]).__name__ == "OpenAIChatModel"


def test_resolve_models_no_fallbacks_main_is_bare_and_fast_mirrors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    pytest.importorskip("anthropic")
    monkeypatch.chdir(tmp_path)  # type: ignore[arg-type]
    _clear_chat_keys(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    main, fast = config.resolve_models()

    assert not isinstance(main, FallbackChatModel)  # default unchanged
    assert main is fast


def test_config_file_fallback_models_drive_the_chain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    pytest.importorskip("anthropic")
    pytest.importorskip("openai")
    monkeypatch.chdir(tmp_path)  # type: ignore[arg-type]
    _clear_chat_keys(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = tmp_path / "metalworks.toml"  # type: ignore[operator]
    cfg.write_text('fallback_models = ["openai/gpt-5"]\n', encoding="utf-8")

    chain = config.resolve_chat_chain()

    assert isinstance(chain, FallbackChatModel)
    assert len(chain.models) == 2


def test_usage_passes_through_unchanged() -> None:
    # A fallback's TextResult (usage included) is returned verbatim.
    primary = _RaisingChatModel(RateLimitedError("p"))
    fb = FakeChatModel(model_id="fb")
    fb.text_responses.append("hi there")
    chain = FallbackChatModel([primary, fb])
    out = chain.complete_text(system="s", user="user-prompt")
    assert isinstance(out, TextResult)
    assert isinstance(out.usage, Usage)
