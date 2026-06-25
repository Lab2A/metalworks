"""FallbackChatModel — an opt-in ordered chain of ChatModels.

When the primary chat model fails with a *retryable* error (a rate-limit /
overloaded condition, or an obvious transient transport error), the chain moves
on to the next configured model. A *non-retryable* error — a config or
capability failure such as :class:`~metalworks.errors.MissingKeyError`,
:class:`~metalworks.errors.MissingExtraError`, or
:class:`~metalworks.errors.StructuredOutputError` — is re-raised immediately:
trying a different provider would neither fix a missing key nor a schema the
model can't satisfy, so falling through would only hide the real fix. If every
model in the chain raises a retryable error, the *last* one is raised.

This wrapper is **opt-in**. With no fallbacks configured, callers get the single
underlying model untouched (see :mod:`metalworks.config`), so default behaviour
is byte-for-byte unchanged.

Retryable is defined narrowly and SDK-free:

- :class:`~metalworks.errors.RateLimitedError` — the typed signal an adapter
  raises once its own backoff is exhausted, and
- anything :func:`metalworks.llm.adapters._retry.is_rate_limit_error`
  recognises as a 429/overloaded/resource-exhausted condition (duck-typed by
  status code or class name) — so a raw provider rate-limit error that escapes
  an adapter still triggers a fallback rather than aborting the chain.

Every other exception (including all other :class:`MetalworksError` subclasses)
is treated as non-retryable and propagates on first occurrence.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, TypeVar

from metalworks.errors import RateLimitedError
from metalworks.llm.adapters._retry import is_rate_limit_error
from metalworks.llm.protocol import (
    PROTOCOL_VERSION,
    ChatCapabilities,
    GroundedResult,
    TextResult,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pydantic import BaseModel

    from metalworks.llm.protocol import ChatModel

    T = TypeVar("T", bound=BaseModel)
else:  # runtime TypeVar so methods can annotate without importing pydantic eagerly
    from pydantic import BaseModel

    T = TypeVar("T", bound=BaseModel)

_log = logging.getLogger("metalworks.llm.fallback")


def _is_retryable(exc: BaseException) -> bool:
    """A retryable error is one a *different* model might succeed past.

    Rate-limit / overloaded / transient-transport conditions qualify; config and
    capability errors (missing key, missing extra, bad schema) do not.
    """
    return isinstance(exc, RateLimitedError) or is_rate_limit_error(exc)


class FallbackChatModel:
    """An ordered chain of :class:`~metalworks.llm.ChatModel`s with failover.

    Each method tries the models in order. On a retryable error it advances to
    the next; on a non-retryable error it re-raises immediately; if all models
    raise retryable errors it raises the last one.

    ``model_id`` is the primary's id, suffixed with ``|+N fallbacks`` so logs and
    run records make the chain visible. ``capabilities`` and ``protocol_version``
    are the primary's — the chain is dispatched as if it were the primary model,
    which keeps grounding dispatch (`capabilities.native_grounding`) and the
    structured ladder consistent with what the primary advertises.
    """

    protocol_version: ClassVar[str] = PROTOCOL_VERSION

    def __init__(self, models: Iterable[ChatModel]) -> None:
        self._models: list[ChatModel] = list(models)
        if not self._models:
            raise ValueError("FallbackChatModel requires at least one model")
        primary = self._models[0]
        extra = len(self._models) - 1
        self.model_id = primary.model_id if extra == 0 else f"{primary.model_id}|+{extra} fallbacks"
        self.capabilities: ChatCapabilities = primary.capabilities

    @property
    def models(self) -> tuple[ChatModel, ...]:
        """The chain, primary first — read-only view for inspection/tests."""
        return tuple(self._models)

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
        last: RateLimitedError | None = None
        for index, model in enumerate(self._models):
            try:
                return model.complete_text(
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    thinking_budget=thinking_budget,
                    timeout_s=timeout_s,
                )
            except Exception as exc:
                last = self._handle(exc, index, "complete_text")
        raise self._exhausted(last)

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
        last: RateLimitedError | None = None
        for index, model in enumerate(self._models):
            try:
                return model.complete_structured(
                    system=system,
                    user=user,
                    output_model=output_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    thinking_budget=thinking_budget,
                    timeout_s=timeout_s,
                )
            except Exception as exc:
                last = self._handle(exc, index, "complete_structured")
        raise self._exhausted(last)

    # ── GroundedChatModel (only meaningful when the primary advertises it) ──

    def complete_grounded(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        timeout_s: float | None = None,
    ) -> GroundedResult:
        last: RateLimitedError | None = None
        for index, model in enumerate(self._models):
            complete_grounded = getattr(model, "complete_grounded", None)
            if complete_grounded is None:
                # A link in the chain can't ground at all — skip it like a
                # retryable failure rather than abort the whole chain.
                _log.debug(
                    "fallback: model[%d] %r has no complete_grounded; skipping",
                    index,
                    getattr(model, "model_id", "?"),
                )
                continue
            try:
                return complete_grounded(
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout_s=timeout_s,
                )
            except Exception as exc:
                last = self._handle(exc, index, "complete_grounded")
        raise self._exhausted(last)

    # ── internals ──

    def _handle(self, exc: BaseException, index: int, method: str) -> RateLimitedError:
        """Decide an exception's fate. Re-raise non-retryable errors; for a
        retryable error, log the failover and return a typed error to carry
        forward as the candidate "last" error.
        """
        if not _is_retryable(exc):
            raise exc
        next_index = index + 1
        if next_index < len(self._models):
            _log.debug(
                "fallback: %s on model[%d] %r failed retryably (%s); trying model[%d] %r",
                method,
                index,
                getattr(self._models[index], "model_id", "?"),
                type(exc).__name__,
                next_index,
                getattr(self._models[next_index], "model_id", "?"),
            )
        else:
            _log.debug(
                "fallback: %s exhausted the chain; last model[%d] %r failed retryably (%s)",
                method,
                index,
                getattr(self._models[index], "model_id", "?"),
                type(exc).__name__,
            )
        if isinstance(exc, RateLimitedError):
            return exc
        # A raw provider rate-limit error escaped an adapter — normalise it to
        # the typed error so the final raise is a clean RateLimitedError.
        return RateLimitedError(getattr(self._models[index], "model_id", "chat model"))

    def _exhausted(self, last: RateLimitedError | None) -> RateLimitedError:
        if last is not None:
            return last
        # Only reachable if the chain was entirely un-callable (e.g. grounding
        # requested but no model in the chain implements it).
        return RateLimitedError(self.model_id)


__all__ = ["FallbackChatModel"]
