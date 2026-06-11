"""ChatModel protocol — the seam every pipeline speaks through.

Design notes (decided in plan review, do not casually change):

- Keyword names mirror the production `llm_client.py` entry points
  (`system`, `user`, `output_model`, `max_tokens`, `temperature`,
  `thinking_budget`) so ports from the source codebase are mechanical.
  The one deliberate difference: no `model=` parameter — the model is bound
  at adapter construction.
- `thinking_budget` is denominated in TOKENS. Adapters map it to their
  provider's mechanism (Anthropic extended thinking budget, OpenAI
  reasoning effort buckets, Gemini thinking_budget) and document the
  mapping.
- `GroundedResult` carries the FULL provenance structure — chunks plus
  supports with character offsets — because downstream span-overlap
  bucketing is the provenance contract. A flat citations list is not
  acceptable. Offsets are CHAR offsets in the protocol; adapters convert
  from whatever the provider emits (Gemini emits UTF-8 byte offsets).
- Dispatch grounding on `capabilities.native_grounding`, never
  `isinstance(model, GroundedChatModel)` — runtime_checkable Protocols only
  check method presence.
- The protocol is versioned as a unit (PROTOCOL_VERSION). Minor = additive
  keyword-only params with defaults; major = breaking.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

PROTOCOL_VERSION = "1.0"

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class ChatCapabilities:
    """What this adapter/model can do natively. Drives ladder + dispatch."""

    native_structured: bool = False
    tool_calls: bool = False
    native_grounding: bool = False
    thinking: bool = False


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


@dataclass(frozen=True)
class TextResult:
    text: str
    usage: Usage = field(default_factory=Usage)
    raw: Any = None  # provider response — escape hatch, never load-bearing


@dataclass(frozen=True)
class GroundingChunk:
    """One retrieved source the grounded answer drew from."""

    uri: str
    title: str = ""
    published_at: str | None = None  # ISO 8601 when the provider exposes it


@dataclass(frozen=True)
class GroundingSupport:
    """A span of the answer text attributed to specific chunks.

    Offsets are CHARACTER offsets into `GroundedResult.text`. Adapters are
    responsible for converting provider-native offsets (Gemini: UTF-8 bytes)
    into char offsets — misaligned offsets attach the wrong source to a
    claim, the worst failure class for a research product.
    """

    start_char: int
    end_char: int
    chunk_indices: tuple[int, ...]


@dataclass(frozen=True)
class GroundedResult:
    text: str
    chunks: tuple[GroundingChunk, ...] = ()
    supports: tuple[GroundingSupport, ...] = ()
    usage: Usage = field(default_factory=Usage)
    raw: Any = None


# Observability hook: adapters call this after every completion when set.
# Attach your own observability here (PostHog, a cost meter, structured
# logging). Signature: (event: dict) -> None. Never raises into the call.
GenerationHook = Callable[[dict[str, Any]], None]


@runtime_checkable
class ChatModel(Protocol):
    """Minimal chat surface every adapter implements."""

    protocol_version: ClassVar[str]
    model_id: str
    capabilities: ChatCapabilities

    def complete_text(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        thinking_budget: int = 0,
        timeout_s: float = 120.0,
    ) -> TextResult: ...

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
    ) -> T: ...


@runtime_checkable
class GroundedChatModel(Protocol):
    """Model-native web grounding (Gemini google_search, Anthropic web_search).

    Presence of this method is NOT how callers decide to use it — check
    `capabilities.native_grounding`. A capable=False adapter may still define
    this method and raise GroundingUnavailable.
    """

    def complete_grounded(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        timeout_s: float = 180.0,
    ) -> GroundedResult: ...
