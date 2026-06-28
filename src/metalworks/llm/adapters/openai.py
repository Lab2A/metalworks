"""OpenAI ChatModel adapter (``metalworks[openai]``), chat.completions API.

Provider-specific mappings:

- ``thinking_budget`` (tokens) → ``reasoning_effort`` buckets via
  :func:`_reasoning_effort`: ``0`` → omitted, ``<=1024`` → ``"low"``,
  ``<=8192`` → ``"medium"``, else ``"high"``. The parameter is only sent for
  reasoning-capable model ids (``o*`` / ``gpt-5*``); on other models the
  budget is ignored without error. Reasoning models reject ``temperature``,
  so it is omitted for them as well.
- Structured output is ladder tier 1 (native): ``response_format`` with a
  ``json_schema`` built from the pydantic model (``strict: False``). If the
  API rejects the schema (``openai.BadRequestError``), the adapter falls back
  to tier 3 (schema-in-prompt).
- Grounding: chat.completions has no metalworks grounding adapter — calling
  ``complete_grounded`` raises ``GroundingUnavailable``. Dispatch on
  ``capabilities.native_grounding`` (False here).
"""

from __future__ import annotations

import contextlib
import importlib
import os
import time
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
    TextResult,
    Usage,
)
from metalworks.llm.structured import prompt_embedded_structured, validate_payload

T = TypeVar("T", bound=BaseModel)


def _reasoning_effort(thinking_budget: int) -> str | None:
    """Map a token-denominated thinking budget to an OpenAI reasoning_effort bucket."""
    if thinking_budget <= 0:
        return None
    if thinking_budget <= 1024:
        return "low"
    if thinking_budget <= 8192:
        return "medium"
    return "high"


def _supports_reasoning(model_id: str) -> bool:
    return model_id.startswith("o") or model_id.startswith("gpt-5")


# Streaming makes the httpx read timeout a per-CHUNK budget (gap between
# tokens), with NO ceiling on total wall-clock — a stream that trickles a byte
# every few seconds, or a half-dead keep-alive socket, can hang a run forever
# (the triaging-stage stall). This factor turns the per-call timeout into an
# overall deadline too: the per-call budget covers time-to-first-token + each
# gap, and N times it bounds the whole stream. METALWORKS_LLM_TIMEOUT scales both.
_STREAM_TOTAL_FACTOR = 4.0
_STREAM_TOTAL_FLOOR_S = 600.0


def _stream_total_budget(timeout_s: float) -> float:
    """Overall wall-clock ceiling for one streamed response."""
    return max(_STREAM_TOTAL_FLOOR_S, timeout_s * _STREAM_TOTAL_FACTOR)


def _consume_stream(stream: Any, *, total_budget_s: float) -> tuple[str, Usage, Any]:
    """Accumulate a streamed chat.completions response into (text, usage, last_chunk).

    Iterates delta chunks, concatenating ``chunk.choices[0].delta.content``
    (guarding ``None``), and captures token usage from the final
    ``include_usage`` chunk (it carries ``.usage`` and an empty ``choices``
    list). The accumulated text equals the non-streamed message content for the
    same response — the streaming change is transparent to callers.

    Raises :class:`TimeoutError` if the stream runs past ``total_budget_s`` of
    wall-clock — the per-chunk httpx read timeout can't catch a stream that
    keeps trickling but never finishes.
    """
    parts: list[str] = []
    usage = Usage()
    last_chunk: Any = None
    deadline = time.monotonic() + total_budget_s
    for chunk in stream:
        if time.monotonic() > deadline:
            with contextlib.suppress(Exception):
                stream.close()
            raise TimeoutError(
                f"OpenAI stream exceeded its {total_budget_s:.0f}s total budget "
                "(model trickled tokens without completing); raise METALWORKS_LLM_TIMEOUT "
                "if this model legitimately needs longer."
            )
        last_chunk = chunk
        choices: list[Any] = list(getattr(chunk, "choices", None) or [])
        if choices:
            delta = getattr(choices[0], "delta", None)
            content = getattr(delta, "content", None)
            if content:
                parts.append(content)
        chunk_usage = getattr(chunk, "usage", None)
        if chunk_usage is not None:
            usage = Usage(
                input_tokens=int(getattr(chunk_usage, "prompt_tokens", 0) or 0),
                output_tokens=int(getattr(chunk_usage, "completion_tokens", 0) or 0),
            )
    return "".join(parts), usage, last_chunk


class OpenAIChatModel:
    """ChatModel over the OpenAI chat.completions API."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION

    def __init__(
        self,
        model_id: str = "gpt-5",
        *,
        api_key: str | None = None,
        api_key_env: str | None = None,
        base_url: str | None = None,
        native_structured: bool = True,
        on_generation: GenerationHook | None = None,
    ) -> None:
        """ChatModel over any OpenAI chat.completions-compatible endpoint.

        Point at a non-OpenAI gateway (OpenRouter, vLLM, LM Studio, Together,
        Groq, a local server) by passing ``base_url`` plus the env var holding
        its key via ``api_key_env``. ``base_url`` also falls back to the
        ``OPENAI_BASE_URL`` env var. Compatible endpoints vary in JSON-schema
        support, so set ``native_structured=False`` to route structured calls
        straight to the schema-in-prompt ladder tier; the default keeps the
        native ``response_format`` path with a tier-3 fallback on rejection.
        Reasoning-effort tuning is suppressed on non-default endpoints.
        """
        try:
            openai = importlib.import_module("openai")
        except ImportError as exc:
            raise MissingExtraError("openai") from exc
        env_var = api_key_env or "OPENAI_API_KEY"
        key = api_key or os.environ.get(env_var)
        if not key:
            raise MissingKeyError(env_var, provider="OpenAI-compatible")
        resolved_base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self.model_id = model_id
        self._is_compat = resolved_base_url is not None
        self.capabilities = ChatCapabilities(
            native_structured=native_structured,
            tool_calls=True,
            native_grounding=False,
            # reasoning_effort is OpenAI-specific; don't advertise thinking on
            # an arbitrary compatible endpoint.
            thinking=not self._is_compat,
        )
        self._on_generation = on_generation
        self._bad_request_error: type[Exception] = openai.BadRequestError
        # max_retries=0: the SDK's default 2 internal retries would silently
        # stack up to 3x the timeout (and re-run the whole hidden-reasoning
        # phase from scratch) on a retryable APITimeoutError. With them off,
        # metalworks' timeout_s is the single honest budget and ``with_backoff``
        # stays the sole retry (rate-limits only).
        self._client: Any = openai.OpenAI(api_key=key, base_url=resolved_base_url, max_retries=0)

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
        budget = resolve_timeout_s(timeout_s)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        def _call() -> tuple[str, Usage, Any]:
            stream = self._client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                max_completion_tokens=max_tokens,
                timeout=self._read_timeout(budget),
                stream=True,
                stream_options={"include_usage": True},
                **self._tuning_kwargs(temperature, thinking_budget),
            )
            return _consume_stream(stream, total_budget_s=_stream_total_budget(budget))

        text, usage, last_chunk = with_backoff(_call, provider="OpenAI")
        self._emit("text", usage)
        return TextResult(text=text, usage=usage, raw=last_chunk)

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
        budget = resolve_timeout_s(timeout_s)

        def _text(ask: str, cap: int) -> str:
            return self.complete_text(
                system=system,
                user=ask,
                max_tokens=cap,
                temperature=temperature,
                thinking_budget=thinking_budget,
                timeout_s=budget,
            ).text

        if not self.capabilities.native_structured:
            # Compatible endpoint without reliable json_schema support: go
            # straight to ladder tier 3 (schema-in-prompt + one retry).
            return prompt_embedded_structured(
                model_id=self.model_id,
                output_model=output_model,
                complete_text=_text,
                user=user,
                max_tokens=max_tokens,
            )
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": output_model.__name__,
                "schema": output_model.model_json_schema(),
                "strict": False,
            },
        }

        def _call() -> tuple[str, Usage, Any]:
            stream = self._client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_completion_tokens=max_tokens,
                timeout=self._read_timeout(budget),
                response_format=response_format,
                stream=True,
                stream_options={"include_usage": True},
                **self._tuning_kwargs(temperature, thinking_budget),
            )
            return _consume_stream(stream, total_budget_s=_stream_total_budget(budget))

        try:
            text, usage, _ = with_backoff(_call, provider="OpenAI")
        except self._bad_request_error:
            # Schema rejected by the API — fall through to ladder tier 3.
            return prompt_embedded_structured(
                model_id=self.model_id,
                output_model=output_model,
                complete_text=_text,
                user=user,
                max_tokens=max_tokens,
            )
        self._emit("structured", usage)
        return validate_payload(self.model_id, output_model, text)

    # ── GroundedChatModel (capability is False; method raises) ──

    def complete_grounded(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        timeout_s: float | None = None,
    ) -> GroundedResult:
        raise GroundingUnavailable(
            self.model_id,
            "OpenAI chat completions has no metalworks grounding adapter yet; "
            "use Gemini or an external SearchProvider",
        )

    # ── internal ──

    @staticmethod
    def _read_timeout(timeout_s: float) -> Any:
        """An ``httpx.Timeout`` whose READ leg is the gap-between-chunks budget.

        Streaming makes ``timeout_s`` a per-chunk read timeout, not a total: a
        reasoning model that takes a long time to the first token, or trickles
        tokens, completes as long as no single gap exceeds ``timeout_s`` — a
        genuinely hung stream (no data for ``timeout_s``) raises cleanly. The
        connect/write/pool legs stay short. httpx is lazy-imported here so
        importing the adapter module stays cheap.
        """
        import httpx

        return httpx.Timeout(connect=15.0, read=timeout_s, write=15.0, pool=15.0)

    def _tuning_kwargs(self, temperature: float, thinking_budget: int) -> dict[str, Any]:
        """Per-model temperature / reasoning_effort handling (see module docstring)."""
        # reasoning_effort is OpenAI-proper; a compatible endpoint may reject it
        # even when the model id pattern-matches (e.g. openai/gpt-5 via OpenRouter).
        if self._is_compat:
            return {"temperature": temperature}
        if _supports_reasoning(self.model_id):
            effort = _reasoning_effort(thinking_budget)
            return {"reasoning_effort": effort} if effort is not None else {}
        return {"temperature": temperature}

    def _emit(self, kind: str, usage: Usage) -> None:
        """Fire the observability hook; hook exceptions never reach the caller."""
        if self._on_generation is None:
            return
        with contextlib.suppress(Exception):
            self._on_generation(
                {
                    "provider": "openai",
                    "model": self.model_id,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "kind": kind,
                }
            )
