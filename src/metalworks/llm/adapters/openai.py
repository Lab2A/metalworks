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
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel

from metalworks.errors import GroundingUnavailable, MissingExtraError, MissingKeyError
from metalworks.llm.adapters._retry import with_backoff
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


def _usage_of(response: Any) -> Usage:
    usage = getattr(response, "usage", None)
    return Usage(
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
    )


def _content_of(response: Any) -> str:
    choices: list[Any] = list(getattr(response, "choices", None) or [])
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    return getattr(message, "content", None) or ""


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
        self._client: Any = openai.OpenAI(api_key=key, base_url=resolved_base_url)

    # ── ChatModel ──

    def complete_text(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        thinking_budget: int = 0,
        timeout_s: float = 120.0,
    ) -> TextResult:
        response = with_backoff(
            lambda: self._client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_completion_tokens=max_tokens,
                timeout=timeout_s,
                **self._tuning_kwargs(temperature, thinking_budget),
            ),
            provider="OpenAI",
        )
        usage = _usage_of(response)
        self._emit("text", usage)
        return TextResult(text=_content_of(response), usage=usage, raw=response)

    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        max_tokens: int = 1024,
        temperature: float = 0.7,
        thinking_budget: int = 0,
        timeout_s: float = 120.0,
    ) -> T:
        def _text(ask: str) -> str:
            return self.complete_text(
                system=system,
                user=ask,
                max_tokens=max_tokens,
                temperature=temperature,
                thinking_budget=thinking_budget,
                timeout_s=timeout_s,
            ).text

        if not self.capabilities.native_structured:
            # Compatible endpoint without reliable json_schema support: go
            # straight to ladder tier 3 (schema-in-prompt + one retry).
            return prompt_embedded_structured(
                model_id=self.model_id,
                output_model=output_model,
                complete_text=_text,
                user=user,
            )
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": output_model.__name__,
                "schema": output_model.model_json_schema(),
                "strict": False,
            },
        }
        try:
            response = with_backoff(
                lambda: self._client.chat.completions.create(
                    model=self.model_id,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_completion_tokens=max_tokens,
                    timeout=timeout_s,
                    response_format=response_format,
                    **self._tuning_kwargs(temperature, thinking_budget),
                ),
                provider="OpenAI",
            )
        except self._bad_request_error:
            # Schema rejected by the API — fall through to ladder tier 3.
            return prompt_embedded_structured(
                model_id=self.model_id,
                output_model=output_model,
                complete_text=_text,
                user=user,
            )
        self._emit("structured", _usage_of(response))
        return validate_payload(self.model_id, output_model, _content_of(response))

    # ── GroundedChatModel (capability is False; method raises) ──

    def complete_grounded(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        timeout_s: float = 180.0,
    ) -> GroundedResult:
        raise GroundingUnavailable(
            self.model_id,
            "OpenAI chat completions has no metalworks grounding adapter yet; "
            "use Gemini or an external SearchProvider",
        )

    # ── internal ──

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
