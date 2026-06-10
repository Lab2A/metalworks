"""Shared retry/backoff for provider rate limits.

Providers raise differently shaped errors for 429/overloaded conditions, and
this module must not import any provider SDK, so detection is duck-typed:

- an integer ``status_code`` or ``code`` attribute of 429 or 529
  (Anthropic ``RateLimitError``/``OverloadedError``, OpenAI ``RateLimitError``,
  google-genai ``ClientError`` carry one of these), or
- a class name containing ``"RateLimit"`` or ``"ResourceExhausted"``.

``with_backoff`` retries matching errors with jittered exponential backoff and
raises a typed :class:`~metalworks.errors.RateLimitedError` once attempts are
exhausted. Non-matching errors propagate immediately.
"""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING, TypeVar

from metalworks.errors import RateLimitedError

if TYPE_CHECKING:
    from collections.abc import Callable

R = TypeVar("R")

_BASE_DELAY_S = 1.0
_RETRYABLE_STATUS = (429, 529)


def is_rate_limit_error(exc: BaseException) -> bool:
    """Duck-typed check for provider rate-limit / overloaded errors."""
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and value in _RETRYABLE_STATUS:
            return True
    name = type(exc).__name__
    return "RateLimit" in name or "ResourceExhausted" in name


def with_backoff(fn: Callable[[], R], *, provider: str, attempts: int = 3) -> R:
    """Call ``fn``, retrying rate-limit errors with jittered exponential backoff.

    Raises ``RateLimitedError(provider)`` after ``attempts`` rate-limited
    failures; any other exception propagates on first occurrence.
    """
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if not is_rate_limit_error(exc):
                raise
            last = exc
            if attempt < attempts - 1:
                delay = _BASE_DELAY_S * (2**attempt) * (0.5 + random.random())
                time.sleep(delay)
    raise RateLimitedError(provider) from last
