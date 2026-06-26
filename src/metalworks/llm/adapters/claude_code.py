"""Claude Code ChatModel adapter (``metalworks[claude-code]``).

Runs completions through the **Claude Agent SDK** (``claude-agent-sdk``), which
drives the bundled ``claude`` CLI — so metalworks can run on a user's existing
Claude Code login with **no API key**. This is the keyless chat floor: when no
provider key or model ref is configured, :func:`metalworks.config.resolve_chat`
falls back here instead of raising (mirroring how embeddings fall back to the
local model).

Provider-specific notes:

- **Auth is the host's.** The SDK uses the machine's Claude Code session
  (``claude`` login / ``CLAUDE_CODE_OAUTH_TOKEN``). No key is read here. Cost is
  the user's individual subscription/usage — see the docs' ToS note.
- **Each call spawns the CLI subprocess** (~5-7s/call), so this is the keyless
  convenience path, not the fast path. A configured API key is faster.
- **Async→sync bridge.** The SDK is async-only; the :class:`ChatModel` protocol
  is sync and called from a thread pool. A single shared background event loop
  (a daemon thread) runs each call's coroutine via ``run_coroutine_threadsafe``,
  so concurrent callers each schedule an independent one-shot ``query()``.
- **Non-agentic.** ``allowed_tools=[]`` + ``max_turns=1`` +
  ``permission_mode="bypassPermissions"`` reduce a turn to a plain completion —
  no tools, no file access, no consent prompts.
- **Structured output** is native via ``output_format={"type":"json_schema",
  "schema": ...}`` → ``ResultMessage.structured_output``; on a miss it falls
  through to the schema-in-prompt ladder (tier 3), like the Anthropic adapter.
- ``thinking_budget`` (tokens) → the SDK's ``max_thinking_tokens``.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, ClassVar, TypeVar, cast

from pydantic import BaseModel

from metalworks.errors import MetalworksError, MissingExtraError, StructuredOutputError
from metalworks.llm.adapters._claude_code_runtime import background_loop, sdk_model
from metalworks.llm.adapters._timeout import resolve_timeout_s
from metalworks.llm.protocol import (
    PROTOCOL_VERSION,
    ChatCapabilities,
    GenerationHook,
    TextResult,
    Usage,
)
from metalworks.llm.structured import prompt_embedded_structured, validate_payload

T = TypeVar("T", bound=BaseModel)


def _usage_of(result: Any) -> Usage:
    """Best-effort token counts from ``ResultMessage.usage`` (dict or object)."""
    raw: Any = getattr(result, "usage", None)
    data: dict[str, Any]
    if isinstance(raw, dict):
        data = cast("dict[str, Any]", raw)
    elif raw is not None:
        data = {k: getattr(raw, k, 0) for k in ("input_tokens", "output_tokens")}
    else:
        data = {}

    def _get(key: str) -> int:
        return int(data.get(key, 0) or 0)

    return Usage(input_tokens=_get("input_tokens"), output_tokens=_get("output_tokens"))


class ClaudeCodeChatModel:
    """ChatModel over the Claude Agent SDK (keyless; uses the Claude Code login)."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION

    def __init__(
        self,
        model_id: str = "claude-code/sonnet",
        *,
        on_generation: GenerationHook | None = None,
    ) -> None:
        try:
            sdk = importlib.import_module("claude_agent_sdk")
        except ImportError as exc:
            raise MissingExtraError("claude-code", package="claude-agent-sdk") from exc
        self.model_id = model_id
        self._model = sdk_model(model_id)
        self.capabilities = ChatCapabilities(
            native_structured=True,
            tool_calls=False,
            native_grounding=False,
            thinking=True,
        )
        self._on_generation = on_generation
        # Bind the SDK symbols once (the module returns Any under our typing).
        self._sdk: Any = sdk
        self._query: Any = sdk.query
        self._Options: Any = sdk.ClaudeAgentOptions
        self._ResultMessage: Any = sdk.ResultMessage

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
        result = self._run(
            system=system, user=user, thinking_budget=thinking_budget, timeout_s=timeout_s
        )
        usage = _usage_of(result)
        self._emit("text", usage)
        return TextResult(text=str(getattr(result, "result", "") or ""), usage=usage, raw=result)

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
        output_format = {
            "type": "json_schema",
            "schema": output_model.model_json_schema(),
        }
        result = self._run(
            system=system,
            user=user,
            thinking_budget=thinking_budget,
            timeout_s=timeout_s,
            output_format=output_format,
        )
        self._emit("structured", _usage_of(result))
        structured = getattr(result, "structured_output", None)
        if isinstance(structured, dict):
            with contextlib.suppress(StructuredOutputError):
                return validate_payload(self.model_id, output_model, structured)

        # Native structured missed (None / invalid) — fall through to ladder tier 3.
        def _text(ask: str) -> str:
            return self.complete_text(
                system=system,
                user=ask,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_s=timeout_s,
            ).text

        return prompt_embedded_structured(
            model_id=self.model_id,
            output_model=output_model,
            complete_text=_text,
            user=user,
        )

    # ── internal ──

    def _run(
        self,
        *,
        system: str,
        user: str,
        thinking_budget: int,
        timeout_s: float,
        output_format: dict[str, Any] | None = None,
    ) -> Any:
        """Drive one non-agentic ``query()`` on the shared loop and return the ResultMessage."""
        opts_kwargs: dict[str, Any] = {
            "allowed_tools": [],
            "max_turns": 1,
            "permission_mode": "bypassPermissions",
            "system_prompt": system,
            "model": self._model,
        }
        if thinking_budget > 0:
            opts_kwargs["max_thinking_tokens"] = thinking_budget
        if output_format is not None:
            opts_kwargs["output_format"] = output_format
        options = self._Options(**opts_kwargs)

        async def _drive() -> Any:
            final: Any = None
            async for message in self._query(prompt=user, options=options):
                if isinstance(message, self._ResultMessage):
                    final = message
            return final

        loop = background_loop()
        future = asyncio.run_coroutine_threadsafe(_drive(), loop)
        try:
            result = future.result(timeout=timeout_s)
        except FuturesTimeoutError as exc:
            future.cancel()
            raise MetalworksError(
                f"Claude Code call exceeded the {timeout_s:.0f}s timeout.",
                fix="Raise METALWORKS_LLM_TIMEOUT, or configure an API key for a faster path.",
            ) from exc
        except Exception as exc:  # SDK CLINotFound / ProcessError / connection, etc.
            raise self._map_sdk_error(exc) from exc

        if result is None:
            raise MetalworksError(
                "Claude Code returned no result.",
                fix="Check that the `claude` CLI is logged in (run `claude`), or set an API key.",
            )
        if getattr(result, "is_error", False):
            raise MetalworksError(
                f"Claude Code reported an error: {getattr(result, 'result', '') or 'unknown'}",
                fix="Check that the `claude` CLI is logged in (run `claude`), or set an API key.",
            )
        return result

    def _map_sdk_error(self, exc: Exception) -> MetalworksError:
        """Turn an SDK exception into an actionable metalworks error."""
        name = type(exc).__name__
        if name == "CLINotFoundError":
            return MetalworksError(
                "The Claude Code CLI could not be found.",
                fix='Reinstall the extra: pip install "metalworks[claude-code]".',
            )
        # CLIConnectionError / ProcessError / auth failures land here.
        return MetalworksError(
            f"Claude Code call failed ({name}): {str(exc)[:200]}",
            fix="Make sure the `claude` CLI is installed and logged in (run `claude`), "
            "or set an API key (e.g. ANTHROPIC_API_KEY) for a key-based provider.",
        )

    def _emit(self, kind: str, usage: Usage) -> None:
        """Fire the observability hook; hook exceptions never reach the caller."""
        if self._on_generation is None:
            return
        with contextlib.suppress(Exception):
            self._on_generation(
                {
                    "provider": "claude-code",
                    "model": self.model_id,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "kind": kind,
                }
            )
