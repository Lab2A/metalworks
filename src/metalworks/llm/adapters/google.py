"""Google Gemini ChatModel adapter (``metalworks[google]``, google-genai SDK).

Provider-specific mappings:

- ``thinking_budget`` (tokens) → ``types.ThinkingConfig(thinking_budget=...)``.
  Gemini counts thinking tokens against ``max_output_tokens``, so the adapter
  sends ``max_tokens + thinking_budget`` as the cap when thinking is on.
  NOTE: Gemini 3.x burns ~1-2k hidden thinking tokens even with
  ``thinking_budget=0``, so when the budget is 0 the adapter still adds 2048
  tokens of headroom to ``max_output_tokens`` — otherwise short answers come
  back empty.
- Structured output is ladder tier 1 (native): ``response_mime_type=
  "application/json"`` + ``response_schema=output_model`` (google-genai
  accepts pydantic classes directly). Schema-rejection (HTTP 400 ClientError)
  falls back to tier 3 (schema-in-prompt).
- Grounding uses the ``google_search`` tool. Gemini emits support spans as
  UTF-8 BYTE offsets into the answer text; the protocol requires CHAR
  offsets, so :func:`_convert_grounding` builds an O(n) byte→char offset
  table (offsets not landing on a char boundary round down). Misaligned
  offsets attach the wrong source to a claim — the worst failure class for a
  research product — hence the dedicated pure function + regression tests.
- Multi-part responses: ``response.text`` joins the first candidate's text
  parts, and Google emits per-candidate grounding metadata whose support
  indices refer to that JOINED text — the adapter assumes this and parses
  against ``response.text``.
"""

from __future__ import annotations

import contextlib
import importlib
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel

from metalworks._genai_client import build_genai_client
from metalworks.errors import GroundingUnavailable, MissingExtraError
from metalworks.llm.adapters._retry import with_backoff
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

# Hidden-thinking headroom for thinking_budget == 0 (see module docstring).
_HIDDEN_THINKING_HEADROOM = 2048
# Hard ceiling for max_output_tokens. Vertex rejects > 65536 (the Gemini 3.x
# output cap); adding thinking headroom to a large max_tokens can otherwise
# push the request over the limit.
_MAX_OUTPUT_TOKENS = 65536


def _byte_to_char_offsets(text: str) -> list[int]:
    """O(n) table mapping every UTF-8 byte offset of ``text`` to a char offset.

    ``table[b]`` is the index of the character containing byte ``b`` (so
    offsets landing mid-character round down); ``table[len(utf8)]`` is
    ``len(text)`` so exclusive end offsets convert cleanly.
    """
    table: list[int] = []
    for char_index, char in enumerate(text):
        table.extend([char_index] * len(char.encode("utf-8")))
    table.append(len(text))
    return table


def _convert_grounding(
    text: str, grounding_metadata: Any
) -> tuple[tuple[GroundingChunk, ...], tuple[GroundingSupport, ...]]:
    """Convert Gemini grounding metadata to protocol chunks/supports.

    Pure function over duck-typed metadata (``grounding_chunks`` with
    ``.web.uri``/``.web.title``; ``grounding_supports`` with
    ``.segment.start_index``/``.segment.end_index`` in UTF-8 BYTES and
    ``.grounding_chunk_indices``) so it is unit-testable with SimpleNamespace
    stand-ins. Byte offsets are converted to char offsets via an O(n) table;
    out-of-range offsets clamp, mid-character offsets round down.
    """
    chunks: list[GroundingChunk] = []
    raw_chunks: Any = getattr(grounding_metadata, "grounding_chunks", None)
    for raw_chunk in raw_chunks or ():
        web = getattr(raw_chunk, "web", None)
        chunks.append(
            GroundingChunk(
                uri=(getattr(web, "uri", None) or "") if web is not None else "",
                title=(getattr(web, "title", None) or "") if web is not None else "",
            )
        )

    table = _byte_to_char_offsets(text)
    last = len(table) - 1
    supports: list[GroundingSupport] = []
    raw_supports: Any = getattr(grounding_metadata, "grounding_supports", None)
    for raw_support in raw_supports or ():
        segment = getattr(raw_support, "segment", None)
        if segment is None:
            continue
        end_index = getattr(segment, "end_index", None)
        if end_index is None:
            continue
        start_byte = int(getattr(segment, "start_index", None) or 0)
        end_byte = int(end_index)
        supports.append(
            GroundingSupport(
                start_char=table[min(max(start_byte, 0), last)],
                end_char=table[min(max(end_byte, 0), last)],
                chunk_indices=tuple(
                    int(i) for i in getattr(raw_support, "grounding_chunk_indices", None) or ()
                ),
            )
        )
    return tuple(chunks), tuple(supports)


def _usage_of(response: Any) -> Usage:
    metadata = getattr(response, "usage_metadata", None)
    return Usage(
        input_tokens=int(getattr(metadata, "prompt_token_count", 0) or 0),
        output_tokens=int(getattr(metadata, "candidates_token_count", 0) or 0),
    )


class GoogleChatModel:
    """ChatModel over the google-genai ``generate_content`` API."""

    protocol_version: ClassVar[str] = PROTOCOL_VERSION

    def __init__(
        self,
        model_id: str = "gemini-3.1-pro",
        *,
        api_key: str | None = None,
        on_generation: GenerationHook | None = None,
    ) -> None:
        try:
            types_module = importlib.import_module("google.genai.types")
            errors_module = importlib.import_module("google.genai.errors")
        except ImportError as exc:
            raise MissingExtraError("google", package="google-genai") from exc
        self.model_id = model_id
        self.capabilities = ChatCapabilities(
            native_structured=True,
            tool_calls=True,
            native_grounding=True,
            thinking=True,
        )
        self._on_generation = on_generation
        self._types: Any = types_module
        # Build the client first — it raises MissingKeyError when neither a key
        # nor Vertex creds are present, before we touch the errors module.
        self._client: Any = build_genai_client(api_key=api_key)
        self._client_error: type[Exception] = errors_module.ClientError

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
        config = self._types.GenerateContentConfig(
            **self._config_kwargs(system, max_tokens, temperature, thinking_budget, timeout_s)
        )
        response = with_backoff(
            lambda: self._client.models.generate_content(
                model=self.model_id, contents=user, config=config
            ),
            provider="Google",
        )
        usage = _usage_of(response)
        self._emit("text", usage)
        return TextResult(text=getattr(response, "text", None) or "", usage=usage, raw=response)

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
        config = self._types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=output_model,
            **self._config_kwargs(system, max_tokens, temperature, thinking_budget, timeout_s),
        )
        try:
            response = with_backoff(
                lambda: self._client.models.generate_content(
                    model=self.model_id, contents=user, config=config
                ),
                provider="Google",
            )
        except self._client_error as exc:
            if getattr(exc, "code", None) != 400:
                raise

            # Schema rejected by the API — fall through to ladder tier 3.
            def _text(ask: str) -> str:
                return self.complete_text(
                    system=system,
                    user=ask,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    thinking_budget=thinking_budget,
                    timeout_s=timeout_s,
                ).text

            return prompt_embedded_structured(
                model_id=self.model_id,
                output_model=output_model,
                complete_text=_text,
                user=user,
            )
        self._emit("structured", _usage_of(response))
        payload: Any = getattr(response, "parsed", None)
        if payload is None:
            payload = getattr(response, "text", None) or ""
        return validate_payload(self.model_id, output_model, payload)

    # ── GroundedChatModel ──

    def complete_grounded(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        timeout_s: float = 180.0,
    ) -> GroundedResult:
        types = self._types
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            **self._config_kwargs(system, max_tokens, temperature, 0, timeout_s),
        )
        response = with_backoff(
            lambda: self._client.models.generate_content(
                model=self.model_id, contents=user, config=config
            ),
            provider="Google",
        )
        usage = _usage_of(response)
        self._emit("grounded", usage)
        candidates: list[Any] = list(getattr(response, "candidates", None) or [])
        metadata = getattr(candidates[0], "grounding_metadata", None) if candidates else None
        if metadata is None or not (getattr(metadata, "grounding_chunks", None) or []):
            raise GroundingUnavailable(self.model_id)
        text = getattr(response, "text", None) or ""
        chunks, supports = _convert_grounding(text, metadata)
        return GroundedResult(
            text=text, chunks=chunks, supports=supports, usage=usage, raw=response
        )

    # ── internal ──

    def _config_kwargs(
        self,
        system: str,
        max_tokens: int,
        temperature: float,
        thinking_budget: int,
        timeout_s: float,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "system_instruction": system,
            "temperature": temperature,
            "http_options": self._types.HttpOptions(timeout=int(timeout_s * 1000)),
        }
        if thinking_budget > 0:
            # Thinking tokens count against max_output_tokens on Gemini.
            requested = max_tokens + thinking_budget
            kwargs["thinking_config"] = self._types.ThinkingConfig(thinking_budget=thinking_budget)
        else:
            # Hidden-thinking headroom — see module docstring / project memory:
            # Gemini 3.x burns ~1-2k thinking tokens even at thinking_budget=0.
            requested = max_tokens + _HIDDEN_THINKING_HEADROOM
        kwargs["max_output_tokens"] = min(requested, _MAX_OUTPUT_TOKENS)
        return kwargs

    def _emit(self, kind: str, usage: Usage) -> None:
        """Fire the observability hook; hook exceptions never reach the caller."""
        if self._on_generation is None:
            return
        with contextlib.suppress(Exception):
            self._on_generation(
                {
                    "provider": "google",
                    "model": self.model_id,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "kind": kind,
                }
            )
