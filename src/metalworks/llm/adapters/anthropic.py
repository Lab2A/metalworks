"""Anthropic ChatModel adapter (``metalworks[anthropic]``).

Provider-specific mappings:

- ``thinking_budget`` (tokens) → Anthropic extended thinking
  ``{"type": "enabled", "budget_tokens": max(1024, thinking_budget)}`` —
  Anthropic's minimum thinking budget is 1024 tokens. The API additionally
  requires ``max_tokens > budget_tokens`` and ``temperature=1`` while thinking,
  so when thinking is on the adapter sends ``max_tokens + budget`` as the
  output cap (the answer keeps its full ``max_tokens`` of room) and omits
  ``temperature`` (letting it default to 1).
- Structured output is ladder tier 2 (no native schema mode): one forced tool
  named ``emit`` whose input schema is the pydantic JSON schema. Forced
  ``tool_choice`` is incompatible with extended thinking, so
  ``thinking_budget`` is ignored on the structured path. When no ``tool_use``
  block comes back, the adapter falls through to tier 3 (schema-in-prompt).
- Grounding uses the ``web_search_20250305`` server tool. Citations arrive on
  text content blocks (``url``/``title``/``cited_text``); each cited block's
  support span is the char range of that block's text within the concatenated
  answer text.
"""

from __future__ import annotations

import contextlib
import importlib
import os
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel

from metalworks.errors import GroundingUnavailable, MissingExtraError, MissingKeyError
from metalworks.llm.adapters._retry import with_backoff
from metalworks.llm.adapters._timeout import resolve_timeout_s
from metalworks.llm.protocol import (
    PROTOCOL_VERSION,
    ChatCapabilities,
    GenerationHook,
    GroundedResult,
    GroundingChunk,
    GroundingSupport,
    TextResult,
    Usage,
)
from metalworks.llm.structured import prompt_embedded_structured, validate_payload

T = TypeVar("T", bound=BaseModel)

_MIN_THINKING_BUDGET = 1024


def _parse_grounded(
    blocks: list[Any],
) -> tuple[str, tuple[GroundingChunk, ...], tuple[GroundingSupport, ...]]:
    """Walk Anthropic content blocks into (text, chunks, supports).

    Pure function over duck-typed blocks (attrs: ``.type``, ``.text``,
    ``.citations`` with ``.url``/``.title``/``.cited_text``) so it is
    unit-testable with simple stand-in dataclasses. Chunks are deduped by url
    preserving first-seen order; each support span is the char range of its
    block's text within the concatenated text.
    """
    text_parts: list[str] = []
    chunks: list[GroundingChunk] = []
    index_by_url: dict[str, int] = {}
    supports: list[GroundingSupport] = []
    offset = 0
    for block in blocks:
        if getattr(block, "type", None) != "text":
            continue
        block_text: str = getattr(block, "text", None) or ""
        chunk_indices: list[int] = []
        citations: list[Any] = list(getattr(block, "citations", None) or [])
        for citation in citations:
            url: str = getattr(citation, "url", None) or ""
            if not url:
                continue
            if url not in index_by_url:
                index_by_url[url] = len(chunks)
                chunks.append(GroundingChunk(uri=url, title=getattr(citation, "title", None) or ""))
            index = index_by_url[url]
            if index not in chunk_indices:
                chunk_indices.append(index)
        if chunk_indices:
            supports.append(
                GroundingSupport(
                    start_char=offset,
                    end_char=offset + len(block_text),
                    chunk_indices=tuple(chunk_indices),
                )
            )
        text_parts.append(block_text)
        offset += len(block_text)
    return "".join(text_parts), tuple(chunks), tuple(supports)


def _usage_of(response: Any) -> Usage:
    usage = getattr(response, "usage", None)
    return Usage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


class AnthropicChatModel:
    """ChatModel over the Anthropic Messages API."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION

    def __init__(
        self,
        model_id: str = "claude-sonnet-4-6",
        *,
        api_key: str | None = None,
        on_generation: GenerationHook | None = None,
    ) -> None:
        try:
            anthropic = importlib.import_module("anthropic")
        except ImportError as exc:
            raise MissingExtraError("anthropic") from exc
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise MissingKeyError("ANTHROPIC_API_KEY", provider="Anthropic")
        self.model_id = model_id
        self.capabilities = ChatCapabilities(
            native_structured=False,
            tool_calls=True,
            native_grounding=True,
            thinking=True,
        )
        self._on_generation = on_generation
        # max_retries=0: the SDK retries a retryable timeout up to 2x by default,
        # silently multiplying the budget. Off, so metalworks' timeout_s is the
        # single honest budget and ``with_backoff`` stays the sole retry.
        self._client: Any = anthropic.Anthropic(api_key=key, max_retries=0)

    # ── ChatModel ──

    def complete_text(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        thinking_budget: int = 0,
        timeout_s: float | None = None,
    ) -> TextResult:
        timeout_s = resolve_timeout_s(timeout_s)
        request_kwargs: dict[str, Any] = {}
        effective_max_tokens = max_tokens
        if thinking_budget > 0:
            budget = max(_MIN_THINKING_BUDGET, thinking_budget)
            request_kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            # max_tokens must exceed budget_tokens; temperature must be 1 while
            # thinking, so it is omitted (see module docstring).
            effective_max_tokens = max_tokens + budget
        else:
            request_kwargs["temperature"] = temperature
        response = with_backoff(
            lambda: self._client.messages.create(
                model=self.model_id,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=effective_max_tokens,
                timeout=timeout_s,
                **request_kwargs,
            ),
            provider="Anthropic",
        )
        usage = _usage_of(response)
        self._emit("text", usage)
        blocks: list[Any] = list(getattr(response, "content", None) or [])
        text = "".join(
            getattr(block, "text", None) or ""
            for block in blocks
            if getattr(block, "type", None) == "text"
        )
        return TextResult(text=text, usage=usage, raw=response)

    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        thinking_budget: int = 0,
        timeout_s: float | None = None,
    ) -> T:
        timeout_s = resolve_timeout_s(timeout_s)
        emit_tool = {
            "name": "emit",
            "description": "Emit the structured result matching the schema.",
            "input_schema": output_model.model_json_schema(),
        }
        response = with_backoff(
            lambda: self._client.messages.create(
                model=self.model_id,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout_s,
                tools=[emit_tool],
                tool_choice={"type": "tool", "name": "emit"},
            ),
            provider="Anthropic",
        )
        self._emit("structured", _usage_of(response))
        blocks: list[Any] = list(getattr(response, "content", None) or [])
        for block in blocks:
            if getattr(block, "type", None) == "tool_use":
                return validate_payload(self.model_id, output_model, getattr(block, "input", None))

        # No tool_use block came back — fall through to ladder tier 3.
        def _text(ask: str, cap: int) -> str:
            return self.complete_text(
                system=system,
                user=ask,
                max_tokens=cap,
                temperature=temperature,
                timeout_s=timeout_s,
            ).text

        return prompt_embedded_structured(
            model_id=self.model_id,
            output_model=output_model,
            complete_text=_text,
            user=user,
            max_tokens=max_tokens,
        )

    # ── GroundedChatModel ──

    def complete_grounded(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        timeout_s: float | None = None,
    ) -> GroundedResult:
        timeout_s = resolve_timeout_s(timeout_s, floor=300.0)
        response = with_backoff(
            lambda: self._client.messages.create(
                model=self.model_id,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout_s,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
            ),
            provider="Anthropic",
        )
        usage = _usage_of(response)
        self._emit("grounded", usage)
        text, chunks, supports = _parse_grounded(list(getattr(response, "content", None) or []))
        if not chunks:
            raise GroundingUnavailable(self.model_id)
        return GroundedResult(
            text=text, chunks=chunks, supports=supports, usage=usage, raw=response
        )

    # ── internal ──

    def _emit(self, kind: str, usage: Usage) -> None:
        """Fire the observability hook; hook exceptions never reach the caller."""
        if self._on_generation is None:
            return
        with contextlib.suppress(Exception):
            self._on_generation(
                {
                    "provider": "anthropic",
                    "model": self.model_id,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "kind": kind,
                }
            )
