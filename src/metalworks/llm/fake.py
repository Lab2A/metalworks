"""FakeChatModel — deterministic, offline, ships in core.

Scripted by output_model type for structured calls and by a queue for text
calls. metalworks' own pipeline tests run on this; users test their
integrations the same way (`metalworks.testing` re-exports it).
"""

from __future__ import annotations

from typing import ClassVar, TypeVar

from pydantic import BaseModel

from metalworks.errors import GroundingUnavailable
from metalworks.llm.protocol import (
    PROTOCOL_VERSION,
    ChatCapabilities,
    GroundedResult,
    TextResult,
    Usage,
)

T = TypeVar("T", bound=BaseModel)


class FakeChatModel:
    """Deterministic ChatModel for tests.

    - `script(MyModel, instance_or_list)` queues structured responses per
      output_model type; a single instance is returned every call, a list is
      consumed FIFO (raises when exhausted).
    - `text_responses` is consumed FIFO for complete_text; when empty, an
      echo of the user prompt is returned.
    - Every call is recorded in `.calls` for assertions.
    """

    protocol_version: ClassVar[str] = PROTOCOL_VERSION

    def __init__(self, *, model_id: str = "fake/chat", grounded: bool = False):
        self.model_id = model_id
        self.capabilities = ChatCapabilities(
            native_structured=True,
            tool_calls=True,
            native_grounding=grounded,
            thinking=False,
        )
        self._structured: dict[type[BaseModel], object] = {}
        self.text_responses: list[str] = []
        self.grounded_results: list[GroundedResult] = []
        self.calls: list[dict[str, object]] = []

    def script(self, output_model: type[T], response: T | list[T]) -> FakeChatModel:
        self._structured[output_model] = response
        return self

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
        self.calls.append({"kind": "text", "system": system, "user": user})
        text = self.text_responses.pop(0) if self.text_responses else f"echo: {user[:200]}"
        return TextResult(text=text, usage=Usage(input_tokens=len(user) // 4, output_tokens=10))

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
        self.calls.append(
            {"kind": "structured", "system": system, "user": user, "output_model": output_model}
        )
        scripted = self._structured.get(output_model)
        if scripted is None:
            raise AssertionError(
                f"FakeChatModel has no scripted response for {output_model.__name__}; "
                f"call .script({output_model.__name__}, instance) in the test."
            )
        result: object
        if isinstance(scripted, list):
            queue: list[object] = scripted
            if not queue:
                raise AssertionError(
                    f"FakeChatModel scripted responses for {output_model.__name__} exhausted."
                )
            result = queue.pop(0)
        else:
            result = scripted
        assert isinstance(result, output_model)
        return result

    # ── GroundedChatModel (only meaningful when constructed grounded=True) ──

    def complete_grounded(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        timeout_s: float = 180.0,
    ) -> GroundedResult:
        self.calls.append({"kind": "grounded", "system": system, "user": user})
        if not self.capabilities.native_grounding:
            raise GroundingUnavailable(self.model_id, "FakeChatModel constructed grounded=False")
        if not self.grounded_results:
            raise AssertionError("FakeChatModel.grounded_results is empty; queue one in the test.")
        return self.grounded_results.pop(0)
