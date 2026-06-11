"""Adapter tests — all offline (pytest-socket enforces --disable-socket).

Covers:

1. Adapter modules import cleanly without any provider SDK installed.
2. Constructing without the SDK raises MissingExtraError (blocked via the
   ``sys.modules[name] = None`` sentinel — a None entry makes ``import name``
   raise ImportError, so the test holds whether or not the SDK is installed).
3. Constructing with the SDK importable but no key env raises MissingKeyError.
4. The pure parsing functions: anthropic ``_parse_grounded`` (dataclass
   stand-in blocks) and google ``_convert_grounding`` (SimpleNamespace
   stand-ins, including the UTF-8 byte→char regression case).
5. The ``_reasoning_effort`` bucket mapping and the shared ``with_backoff``
   retry helper (fake exceptions, monkeypatched sleep).
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

import metalworks.llm.adapters._retry as retry_module
from metalworks.embeddings.adapters.google import GoogleEmbedding
from metalworks.embeddings.adapters.openai import OpenAIEmbedding
from metalworks.errors import (
    GroundingUnavailable,
    MissingExtraError,
    MissingKeyError,
    RateLimitedError,
)
from metalworks.llm.adapters._retry import is_rate_limit_error, with_backoff
from metalworks.llm.adapters.anthropic import AnthropicChatModel, _parse_grounded
from metalworks.llm.adapters.google import GoogleChatModel, _convert_grounding
from metalworks.llm.adapters.openai import OpenAIChatModel, _reasoning_effort
from metalworks.llm.protocol import GroundingSupport
from metalworks.search.adapters.exa import ExaSearch
from metalworks.search.adapters.tavily import TavilySearch

GOOGLE_MODULES = ("google", "google.genai", "google.genai.types", "google.genai.errors")

ADAPTER_MODULES = (
    "metalworks.llm.adapters",
    "metalworks.llm.adapters._retry",
    "metalworks.llm.adapters.anthropic",
    "metalworks.llm.adapters.openai",
    "metalworks.llm.adapters.google",
    "metalworks.search.adapters",
    "metalworks.search.adapters.exa",
    "metalworks.search.adapters.tavily",
    "metalworks.embeddings.adapters",
    "metalworks.embeddings.adapters.google",
    "metalworks.embeddings.adapters.openai",
)

EXTRA_AND_KEY_CASES = [
    pytest.param(AnthropicChatModel, ("anthropic",), ("ANTHROPIC_API_KEY",), id="anthropic"),
    pytest.param(OpenAIChatModel, ("openai",), ("OPENAI_API_KEY",), id="openai"),
    pytest.param(
        GoogleChatModel, GOOGLE_MODULES, ("GOOGLE_API_KEY", "GEMINI_API_KEY"), id="google"
    ),
    pytest.param(ExaSearch, ("exa_py",), ("EXA_API_KEY",), id="exa"),
    pytest.param(TavilySearch, ("tavily",), ("TAVILY_API_KEY",), id="tavily"),
    pytest.param(
        GoogleEmbedding,
        GOOGLE_MODULES,
        ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        id="google-embedding",
    ),
    pytest.param(OpenAIEmbedding, ("openai",), ("OPENAI_API_KEY",), id="openai-embedding"),
]


# ── 1. import hygiene ──


@pytest.mark.parametrize("module_name", ADAPTER_MODULES)
def test_adapter_module_imports_clean(module_name: str) -> None:
    importlib.import_module(module_name)


# ── 2. MissingExtraError without the SDK ──


@pytest.mark.parametrize(("factory", "blocked", "env_vars"), EXTRA_AND_KEY_CASES)
def test_missing_sdk_raises_missing_extra(
    monkeypatch: pytest.MonkeyPatch,
    factory: Any,
    blocked: tuple[str, ...],
    env_vars: tuple[str, ...],
) -> None:
    for name in blocked:
        monkeypatch.setitem(sys.modules, name, None)  # None entry → ImportError
    with pytest.raises(MissingExtraError) as excinfo:
        factory()
    assert "pip install" in (excinfo.value.fix or "")


# ── 3. MissingKeyError with the SDK importable but no key ──


def _install_fakes(monkeypatch: pytest.MonkeyPatch, names: tuple[str, ...]) -> None:
    for name in names:
        monkeypatch.setitem(sys.modules, name, ModuleType(name))


@pytest.mark.parametrize(("factory", "modules", "env_vars"), EXTRA_AND_KEY_CASES)
def test_missing_key_raises_missing_key(
    monkeypatch: pytest.MonkeyPatch,
    factory: Any,
    modules: tuple[str, ...],
    env_vars: tuple[str, ...],
) -> None:
    _install_fakes(monkeypatch, modules)
    for env_var in env_vars:
        monkeypatch.delenv(env_var, raising=False)
    with pytest.raises(MissingKeyError) as excinfo:
        factory()
    assert env_vars[0] in (excinfo.value.fix or "")


def test_explicit_api_key_beats_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("anthropic")
    module.Anthropic = lambda **_: SimpleNamespace()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", module)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    model = AnthropicChatModel(api_key="sk-test")
    assert model.model_id == "claude-sonnet-4-6"
    assert model.capabilities.native_grounding is True
    assert model.capabilities.native_structured is False


# ── 4a. anthropic offline behavior via a scripted fake client ──


class _FakeMessages:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


def _anthropic_with_response(
    monkeypatch: pytest.MonkeyPatch,
    response: Any,
    hook: Any = None,
) -> tuple[AnthropicChatModel, _FakeMessages]:
    messages = _FakeMessages(response)
    client = SimpleNamespace(messages=messages)
    module = ModuleType("anthropic")
    module.Anthropic = lambda **_: client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", module)
    return AnthropicChatModel(api_key="sk-test", on_generation=hook), messages


def _text_response(*texts: str) -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=t, citations=None) for t in texts],
        usage=SimpleNamespace(input_tokens=3, output_tokens=7),
    )


def test_anthropic_complete_text_concatenates_and_emits_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[dict[str, Any]] = []
    model, messages = _anthropic_with_response(
        monkeypatch, _text_response("hello ", "world"), hook=events.append
    )
    result = model.complete_text(system="s", user="u")
    assert result.text == "hello world"
    assert result.usage.input_tokens == 3
    assert result.usage.output_tokens == 7
    assert events == [
        {
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "input_tokens": 3,
            "output_tokens": 7,
            "kind": "text",
        }
    ]
    assert messages.calls[0]["temperature"] == 0.7


def test_anthropic_thinking_budget_floors_at_1024_and_pads_max_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, messages = _anthropic_with_response(monkeypatch, _text_response("ok"))
    model.complete_text(system="s", user="u", max_tokens=500, thinking_budget=10)
    call = messages.calls[0]
    assert call["thinking"] == {"type": "enabled", "budget_tokens": 1024}
    assert call["max_tokens"] == 500 + 1024  # must exceed the budget
    assert "temperature" not in call  # thinking requires temperature=1 (omitted)


def test_anthropic_hook_exception_never_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    def _exploding_hook(event: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    model, _ = _anthropic_with_response(monkeypatch, _text_response("fine"), hook=_exploding_hook)
    assert model.complete_text(system="s", user="u").text == "fine"


class _Point(BaseModel):
    x: int
    y: int


def test_anthropic_structured_forced_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    response = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input={"x": 1, "y": 2})],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    model, messages = _anthropic_with_response(monkeypatch, response)
    point = model.complete_structured(system="s", user="u", output_model=_Point)
    assert point == _Point(x=1, y=2)
    call = messages.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "emit"}
    assert call["tools"][0]["name"] == "emit"
    assert call["tools"][0]["input_schema"] == _Point.model_json_schema()


def test_anthropic_grounded_without_citations_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model, _ = _anthropic_with_response(monkeypatch, _text_response("no sources here"))
    with pytest.raises(GroundingUnavailable):
        model.complete_grounded(system="s", user="u")


# ── 4b. _parse_grounded (pure, dataclass stand-ins) ──


@dataclass
class _Citation:
    url: str
    title: str = ""
    cited_text: str = ""


@dataclass
class _TextBlock:
    text: str
    citations: list[_Citation] | None = None
    type: str = "text"


@dataclass
class _ToolUseBlock:
    type: str = "server_tool_use"


def test_parse_grounded_spans_and_dedupe() -> None:
    blocks: list[Any] = [
        _TextBlock("Hello. "),
        _ToolUseBlock(),
        _TextBlock(
            "Cited claim.",
            [_Citation("https://a.com", "A"), _Citation("https://b.com", "B")],
        ),
        _TextBlock(" More.", [_Citation("https://a.com", "A again")]),
    ]
    text, chunks, supports = _parse_grounded(blocks)
    assert text == "Hello. Cited claim. More."
    # deduped by url, first-seen order, first-seen title kept
    assert [c.uri for c in chunks] == ["https://a.com", "https://b.com"]
    assert chunks[0].title == "A"
    assert supports == (
        # span of each cited block within the joined text
        GroundingSupport(start_char=7, end_char=19, chunk_indices=(0, 1)),
        GroundingSupport(start_char=19, end_char=25, chunk_indices=(0,)),
    )
    # the spans slice the cited block text exactly
    assert text[supports[0].start_char : supports[0].end_char] == "Cited claim."
    assert text[supports[1].start_char : supports[1].end_char] == " More."


def test_parse_grounded_duplicate_citation_in_one_block_yields_one_index() -> None:
    blocks: list[Any] = [_TextBlock("x", [_Citation("https://a.com"), _Citation("https://a.com")])]
    _, chunks, supports = _parse_grounded(blocks)
    assert len(chunks) == 1
    assert supports[0].chunk_indices == (0,)


def test_parse_grounded_no_citations_returns_empty_provenance() -> None:
    text, chunks, supports = _parse_grounded([_TextBlock("plain answer")])
    assert text == "plain answer"
    assert chunks == ()
    assert supports == ()


def test_parse_grounded_empty_blocks() -> None:
    assert _parse_grounded([]) == ("", (), ())


# ── 4c. _convert_grounding (pure, SimpleNamespace stand-ins) ──


def _metadata(chunks: list[Any], supports: list[Any]) -> SimpleNamespace:
    return SimpleNamespace(grounding_chunks=chunks, grounding_supports=supports)


def _web_chunk(uri: str, title: str) -> SimpleNamespace:
    return SimpleNamespace(web=SimpleNamespace(uri=uri, title=title))


def _support(start_byte: int, end_byte: int, indices: list[int]) -> SimpleNamespace:
    return SimpleNamespace(
        segment=SimpleNamespace(start_index=start_byte, end_index=end_byte),
        grounding_chunk_indices=indices,
    )


def test_convert_grounding_ascii_offsets_pass_through() -> None:
    text = "Solar is cheap. Wind is too."
    metadata = _metadata(
        [_web_chunk("https://a.com", "A"), _web_chunk("https://b.com", "B")],
        [_support(0, 15, [0]), _support(16, 28, [1])],
    )
    chunks, supports = _convert_grounding(text, metadata)
    assert [c.uri for c in chunks] == ["https://a.com", "https://b.com"]
    assert text[supports[0].start_char : supports[0].end_char] == "Solar is cheap."
    assert text[supports[1].start_char : supports[1].end_char] == "Wind is too."
    assert supports[0].chunk_indices == (0,)
    assert supports[1].chunk_indices == (1,)


def test_convert_grounding_multibyte_byte_offsets_become_char_offsets() -> None:
    # "₹" is 3 UTF-8 bytes; Devanagari chars are 3 bytes each — byte offsets
    # diverge from char offsets almost immediately. This is the
    # review-mandated regression net for byte→char conversion.
    text = "₹500 की कीमत बहुत कम है."
    target = "की कीमत"
    start_char = text.index(target)
    end_char = start_char + len(target)
    start_byte = len(text[:start_char].encode("utf-8"))
    end_byte = len(text[:end_char].encode("utf-8"))
    assert (start_byte, end_byte) != (start_char, end_char)  # the test means something

    metadata = _metadata(
        [_web_chunk("https://prices.example", "Prices")],
        [_support(start_byte, end_byte, [0])],
    )
    _, supports = _convert_grounding(text, metadata)
    assert (supports[0].start_char, supports[0].end_char) == (start_char, end_char)
    assert text[supports[0].start_char : supports[0].end_char] == target


def test_convert_grounding_mid_character_byte_offset_rounds_down() -> None:
    text = "₹5"  # "₹" occupies bytes 0-2
    metadata = _metadata(
        [_web_chunk("https://x", "")],
        [_support(1, 4, [0])],  # start lands inside "₹"
    )
    _, supports = _convert_grounding(text, metadata)
    assert supports[0].start_char == 0  # rounded down to the containing char
    assert supports[0].end_char == 2


def test_convert_grounding_clamps_out_of_range_offsets() -> None:
    text = "ab"
    metadata = _metadata([_web_chunk("https://x", "")], [_support(0, 999, [0])])
    _, supports = _convert_grounding(text, metadata)
    assert supports[0].end_char == 2


def test_convert_grounding_skips_malformed_supports_and_keeps_chunk_order() -> None:
    text = "abcdef"
    no_segment = SimpleNamespace(segment=None, grounding_chunk_indices=[0])
    no_end = SimpleNamespace(
        segment=SimpleNamespace(start_index=0, end_index=None),
        grounding_chunk_indices=[0],
    )
    non_web = SimpleNamespace(web=None)  # keeps its slot so indices stay aligned
    metadata = _metadata(
        [non_web, _web_chunk("https://x", "X")],
        [no_segment, no_end, _support(0, 3, [1])],
    )
    chunks, supports = _convert_grounding(text, metadata)
    assert chunks[0].uri == ""
    assert chunks[1].uri == "https://x"
    assert len(supports) == 1
    assert supports[0].chunk_indices == (1,)


def test_convert_grounding_none_metadata_is_empty() -> None:
    assert _convert_grounding("text", None) == ((), ())


# ── 5a. OpenAI reasoning_effort buckets ──


@pytest.mark.parametrize(
    ("budget", "expected"),
    [
        (-5, None),
        (0, None),
        (1, "low"),
        (1024, "low"),
        (1025, "medium"),
        (8192, "medium"),
        (8193, "high"),
        (100_000, "high"),
    ],
)
def test_reasoning_effort_buckets(budget: int, expected: str | None) -> None:
    assert _reasoning_effort(budget) == expected


# ── 5b. with_backoff ──


class _NamedRateLimitError(Exception):
    """Matched by class name ("RateLimit")."""


class _ResourceExhausted(Exception):
    """Matched by class name ("ResourceExhausted")."""


class _Overloaded(Exception):
    status_code = 529


class _GoogleStyle429(Exception):
    code = 429


class _Boring(Exception):
    pass


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(retry_module.time, "sleep", recorded.append)
    return recorded


def test_with_backoff_retries_then_succeeds(sleeps: list[float]) -> None:
    attempts: list[int] = []

    def flaky() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise _NamedRateLimitError()
        return "ok"

    assert with_backoff(flaky, provider="Anthropic") == "ok"
    assert len(attempts) == 3
    assert len(sleeps) == 2
    assert all(delay > 0 for delay in sleeps)
    assert sleeps[1] > sleeps[0] * 0.5  # exponential-ish despite jitter


def test_with_backoff_exhausts_into_rate_limited_error(sleeps: list[float]) -> None:
    def always_429() -> None:
        raise _GoogleStyle429()

    with pytest.raises(RateLimitedError) as excinfo:
        with_backoff(always_429, provider="Google")
    assert "Google" in excinfo.value.message
    assert isinstance(excinfo.value.__cause__, _GoogleStyle429)
    assert len(sleeps) == 2  # no sleep after the final attempt


def test_with_backoff_passes_through_other_errors(sleeps: list[float]) -> None:
    def broken() -> None:
        raise _Boring("nope")

    with pytest.raises(_Boring):
        with_backoff(broken, provider="OpenAI")
    assert sleeps == []


def test_with_backoff_respects_attempts(sleeps: list[float]) -> None:
    calls: list[int] = []

    def overloaded() -> None:
        calls.append(1)
        raise _Overloaded()

    with pytest.raises(RateLimitedError):
        with_backoff(overloaded, provider="Anthropic", attempts=5)
    assert len(calls) == 5


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_NamedRateLimitError(), True),
        (_ResourceExhausted(), True),
        (_Overloaded(), True),
        (_GoogleStyle429(), True),
        (_Boring(), False),
        (ValueError("429"), False),  # message text alone is not a match
    ],
)
def test_is_rate_limit_error(exc: Exception, expected: bool) -> None:
    assert is_rate_limit_error(exc) is expected


# ── OpenAI-compatible adapter (WS2.1: base_url / api_key_env / native_structured) ──


def test_openai_compat_adapter_uses_named_env_and_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("openai")
    from metalworks.llm.adapters.openai import OpenAIChatModel

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    model = OpenAIChatModel(
        model_id="meta-llama/llama-3-70b",
        api_key_env="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
        native_structured=False,
    )
    assert model.model_id == "meta-llama/llama-3-70b"
    # compat endpoints don't advertise OpenAI-only grounding/reasoning
    assert model.capabilities.native_grounding is False
    assert model.capabilities.thinking is False
    assert model.capabilities.native_structured is False


def test_openai_compat_missing_key_names_the_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("openai")
    from metalworks.errors import MissingKeyError
    from metalworks.llm.adapters.openai import OpenAIChatModel

    monkeypatch.delenv("CUSTOM_LLM_KEY", raising=False)
    with pytest.raises(MissingKeyError) as exc:
        OpenAIChatModel(api_key_env="CUSTOM_LLM_KEY", base_url="http://localhost:1234/v1")
    assert "CUSTOM_LLM_KEY" in str(exc.value.fix)
