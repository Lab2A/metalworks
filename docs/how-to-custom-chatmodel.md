# How-to: implement a custom ChatModel

metalworks talks to LLMs through a small `ChatModel` protocol. To use a
provider or gateway metalworks does not ship an adapter for, implement the
protocol and run the conformance checks.

## The protocol

```python
from typing import ClassVar, TypeVar
from pydantic import BaseModel
from metalworks.llm.protocol import ChatCapabilities, TextResult, Usage

T = TypeVar("T", bound=BaseModel)

class MyChatModel:
    protocol_version: ClassVar[str] = "1.0"
    model_id = "myprovider/my-model"
    capabilities = ChatCapabilities(
        native_structured=False,  # set True if your provider enforces JSON schema
        tool_calls=True,
        native_grounding=False,
        thinking=False,
    )

    def complete_text(self, *, system, user, max_tokens=1024, temperature=0.7,
                      thinking_budget=0, timeout_s=120.0) -> TextResult:
        text = ...  # call your provider
        return TextResult(text=text, usage=Usage(input_tokens=0, output_tokens=0))

    def complete_structured(self, *, system, user, output_model, max_tokens=1024,
                            temperature=0.7, thinking_budget=0, timeout_s=120.0):
        ...  # see the ladder below
```

## Structured output

If your provider has no native JSON-schema mode, reuse the shared ladder so you
get tool-call extraction with a prompt-embedded fallback and one validation
retry:

```python
from metalworks.llm.structured import prompt_embedded_structured

def complete_structured(self, *, system, user, output_model, **kw):
    return prompt_embedded_structured(
        model_id=self.model_id,
        output_model=output_model,
        complete_text=lambda prompt: self.complete_text(system=system, user=prompt).text,
        user=user,
    )
```

All paths end in `output_model.model_validate(...)` and raise a typed
`StructuredOutputError` on failure, so callers never see a raw `ValidationError`.

## Verify it

```python
from metalworks.llm import ChatModel

def test_my_model_satisfies_protocol():
    assert isinstance(MyChatModel(), ChatModel)  # runtime_checkable
```

Bind your model anywhere a `ChatModel` is expected, including `ResearchDeps`:

```python
deps = ResearchDeps(chat=MyChatModel(), embeddings=..., corpus=..., reader=...)
```
